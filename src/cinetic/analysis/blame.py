"""Fabric fault localization — slow flows -> switch/link blame (gap #2).

The inverse of :mod:`fabric` (which attributes *load*): here we take the *slow*
flows and find the fabric element they share, to point at an under-performing
switch/link rather than just a slow node. See PLAN_FABRIC_FAULT_LOCALIZATION.md.

Signal model: a flow's bandwidth is gated by the worst element on its path,
``bw(a,b) ~ ref * min(health[node_a], health[node_b], health[leaf_a/b],
min spine element)``. Per-flow *slowness* ``s = clamp(1 - bw/ref, 0, 1)``; ref is
``--expected-bw`` if given, else the median flow bandwidth.

Two regimes:
* **Endpoint (node + leaf): deterministic** — a node's traffic always exits via
  its own NIC + leaf, so blame is reliable. A leaf is blamed only when **>=2
  distinct slow nodes** sit under it (a lone slow node is a node/NIC fault, not a
  switch fault — the confounder guard).
* **Spine (switches/links): multipath** — ECMP spreads a flow over k paths, so a
  bad element only carries ~1/k of it; slowness is distributed across candidate
  elements via the same ECMP fractions as the load model and reported **low
  confidence**.

Blame assumes an **idle** fabric (congestion also slows flows); on a `loaded`
experiment the result localizes the *congestion* instead and is flagged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from cinetic.topology.model import Topology
from .fabric import (Edge, build_switch_graph, flows_from_analysis, route,
                     _switch_cell_map)
from .metrics import Analysis
from .topo import normalize_host


def _slowness(bw: float, ref: float) -> float:
    """1 - bw/ref clamped to [0,1]; 0 = at/above ref (healthy)."""
    if not np.isfinite(bw) or ref <= 0:
        return float("nan")
    return float(min(1.0, max(0.0, 1.0 - bw / ref)))


# --------------------------------------------------------------------------- #
# result types
# --------------------------------------------------------------------------- #

@dataclass
class Suspect:
    kind: str                 # leaf | node | spine_switch | link
    name: str                 # ib_name / host / "A--B"
    cell: str = "?"
    confidence: str = "high"  # high (endpoint) | low (spine, ECMP-diluted)
    n_flows: int = 0          # flows implicating this element
    median_slowness: float = float("nan")   # 0..1 (1 = ref bandwidth lost)
    median_bw: float = float("nan")          # GB/s of the implicating flows/nodes
    ref_bw: float = float("nan")
    nodes: List[str] = field(default_factory=list)   # slow nodes involved
    note: str = ""


@dataclass
class BlameResult:
    ref_bw: float
    ref_source: str
    n_flows: int = 0
    resolved_frac: float = 0.0
    is_loaded: bool = False
    n_lone_nodes: int = 0     # nodes with no same-switch peer (not node-blamed)
    leaf_suspects: List[Suspect] = field(default_factory=list)
    node_suspects: List[Suspect] = field(default_factory=list)
    spine_suspects: List[Suspect] = field(default_factory=list)   # switches+links
    warnings: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# computation
# --------------------------------------------------------------------------- #

def _merge_node_medians(analyses: List[Analysis]) -> Dict[str, float]:
    """Per-node median bandwidth across apps; a node slow in any app counts
    (take the min, the worst case)."""
    out: Dict[str, float] = {}
    for an in analyses:
        for ns in an.nodes:
            h = normalize_host(ns.node)
            v = ns.median_bw_gbs
            if not np.isfinite(v):
                continue
            out[h] = min(out[h], v) if h in out else v
    return out


def _leaf_of(topo: Topology, host: str) -> Optional[str]:
    n = topo.nodes.get(host)
    return n.switches[0] if (n is not None and n.switches) else None


def compute_blame(analyses: List[Analysis], topo: Topology,
                  ref_bw: Optional[float] = None,
                  node_slow_frac: float = 0.15,
                  spine_slow_frac: float = 0.15,
                  min_leaf_nodes: int = 2,
                  min_spine_flows: int = 3,
                  min_frac: float = 0.8,
                  is_loaded: bool = False) -> Optional[BlameResult]:
    """Localize under-performance to switches/links. ``None`` when <``min_frac``
    of flow endpoints resolve in the topology (wrong-topology guard)."""
    graph = build_switch_graph(topo)
    cell_of = _switch_cell_map(topo)
    cache: dict = {}

    # 1. collect flows (short hostnames + bandwidth), track resolution
    flows = []
    seen: set = set()
    resolved: set = set()
    for an in analyses:
        for f in flows_from_analysis(an):
            for h in (f.a, f.b):
                seen.add(h)
                if _leaf_of(topo, h) is not None:
                    resolved.add(h)
            flows.append(f)
    resolved_frac = (len(resolved) / len(seen)) if seen else 0.0
    if resolved_frac < min_frac:
        return None

    # 2. reference bandwidth
    bws = np.array([f.bw for f in flows if np.isfinite(f.bw)], dtype=float)
    if ref_bw is not None and np.isfinite(ref_bw) and ref_bw > 0:
        ref, ref_src = float(ref_bw), "expected-bw"
    elif bws.size:
        ref, ref_src = float(np.median(bws)), "median flow bandwidth"
    else:
        return None

    res = BlameResult(ref_bw=ref, ref_source=ref_src, n_flows=len(flows),
                      resolved_frac=resolved_frac, is_loaded=is_loaded)
    if is_loaded:
        res.warnings.append(
            "experiment is LOADED (aggressors present): blame localizes the "
            "induced CONGESTION, not a hardware fault — interpret accordingly.")

    node_med = _merge_node_medians(analyses)   # overall, for reporting/fallback
    node_slow = {h: _slowness(v, ref) for h, v in node_med.items()}

    # --- Stage A: leaf / node blame (deterministic) -------------------------
    # Keyed on INTRA-LEAF flows (both endpoints on the same leaf): a bad leaf
    # slows same-switch traffic, a bad node slows only flows touching it, and a
    # bad spine doesn't touch intra-leaf traffic at all. Per leaf, look at its
    # slow intra-leaf flows: if one node is common to all of them it's a node/NIC
    # fault; otherwise (>=min_leaf_nodes nodes, no single culprit) it's the leaf.
    intra_by_leaf: Dict[str, list] = {}
    nodes_with_intra: set = set()
    for f in flows:
        la, lb = _leaf_of(topo, f.a), _leaf_of(topo, f.b)
        if la is not None and la == lb:
            intra_by_leaf.setdefault(la, []).append(f)
            nodes_with_intra.update((f.a, f.b))

    blamed_nodes: set = set()
    for leaf, iflows in intra_by_leaf.items():
        slow = [f for f in iflows if _slowness(f.bw, ref) >= node_slow_frac]
        if not slow:
            continue
        endpoint_sets = [{f.a, f.b} for f in slow]
        common = set.intersection(*endpoint_sets)
        all_nodes = sorted(set().union(*endpoint_sets))
        med_s = float(np.median([_slowness(f.bw, ref) for f in slow]))
        if common:                       # one node in every slow flow -> node fault
            for h in sorted(common):
                blamed_nodes.add(h)
                res.node_suspects.append(Suspect(
                    kind="node", name=h, cell=cell_of.get(leaf, "?"),
                    confidence="high", n_flows=len(slow),
                    median_slowness=node_slow.get(h, med_s),
                    median_bw=node_med.get(h, ref * (1 - med_s)), ref_bw=ref,
                    nodes=[h],
                    note="slow on its same-switch flows (node/NIC fault)"))
        elif len(all_nodes) >= min_leaf_nodes:   # no single culprit -> leaf fault
            blamed_nodes.update(all_nodes)
            res.leaf_suspects.append(Suspect(
                kind="leaf", name=leaf, cell=cell_of.get(leaf, "?"),
                confidence="high", n_flows=len(slow), median_slowness=med_s,
                median_bw=ref * (1 - med_s), ref_bw=ref, nodes=all_nodes,
                note=f"{len(all_nodes)} nodes slow on same-switch flows, no single "
                     "culprit"))

    # Nodes alone on their leaf (no same-switch peer) are deliberately NOT
    # node-blamed here: with no intra-leaf flow to isolate node vs leaf vs spine,
    # the only signal is the overall median, which a slow spine also depresses —
    # blaming them would re-introduce that confounder. They are still covered by
    # the main report's under-performing-nodes section; here Stage B (spine) is
    # what applies to their cross-leaf flows. (Tracked: node_unassessable.)
    res.n_lone_nodes = len(node_slow.keys() - nodes_with_intra)
    res.leaf_suspects.sort(key=lambda x: x.median_slowness, reverse=True)
    res.node_suspects.sort(key=lambda x: x.median_slowness, reverse=True)

    # --- Stage B: spine blame (multipath, low confidence) -------------------
    # Distribute each flow's slowness over the spine elements on its ECMP routes,
    # weighted by the path fraction; an element is suspect if its weighted-mean
    # slowness is high over enough flows. Endpoint leaves are excluded (Stage A).
    sw_acc: Dict[str, list] = {}   # ib_name -> [sum(frac*s), sum(frac), nflows]
    lk_acc: Dict[Edge, list] = {}
    leaves_seen: set = set()
    for f in flows:
        la, lb = _leaf_of(topo, f.a), _leaf_of(topo, f.b)
        if la is None or lb is None or la == lb:
            continue                       # intra-leaf: no spine involvement
        leaves_seen.update((la, lb))
        s = _slowness(f.bw, ref)
        if not np.isfinite(s):
            continue
        r = route(graph, la, lb, cache)
        if r is None:
            continue
        for sw, frac in r.switch_w.items():
            if sw in (la, lb):
                continue                   # endpoint leaves handled in Stage A
            a = sw_acc.setdefault(sw, [0.0, 0.0, 0])
            a[0] += frac * s; a[1] += frac; a[2] += 1
        for e, frac in r.link_w.items():
            a = lk_acc.setdefault(e, [0.0, 0.0, 0])
            a[0] += frac * s; a[1] += frac; a[2] += 1

    for sw, (wsum, fsum, nf) in sw_acc.items():
        mean_s = wsum / fsum if fsum > 0 else float("nan")
        if mean_s >= spine_slow_frac and nf >= min_spine_flows:
            res.spine_suspects.append(Suspect(
                kind="spine_switch", name=sw, cell=cell_of.get(sw, "?"),
                confidence="low", n_flows=nf, median_slowness=mean_s,
                median_bw=ref * (1 - mean_s), ref_bw=ref,
                note="ECMP-distributed; one of several candidate paths"))
    for (a, b), (wsum, fsum, nf) in lk_acc.items():
        mean_s = wsum / fsum if fsum > 0 else float("nan")
        if mean_s >= spine_slow_frac and nf >= min_spine_flows:
            res.spine_suspects.append(Suspect(
                kind="link", name=f"{a}--{b}", confidence="low", n_flows=nf,
                median_slowness=mean_s, median_bw=ref * (1 - mean_s), ref_bw=ref,
                note="ECMP-distributed candidate link"))
    res.spine_suspects.sort(key=lambda x: x.median_slowness, reverse=True)
    return res


# --------------------------------------------------------------------------- #
# report + summary
# --------------------------------------------------------------------------- #

def _g(x) -> str:
    return "n/a" if x is None or x != x else f"{x:.2f}"


def _pct(x) -> str:
    return "n/a" if x is None or x != x else f"{x * 100:.0f}%"


def format_blame(br: BlameResult, top_n: int = 15) -> str:
    L = ["=" * 78, "FABRIC FAULT LOCALIZATION (slow -> switch/link blame)", "=" * 78]
    L.append(f"flows            : {br.n_flows}")
    L.append(f"host resolution  : {br.resolved_frac:.0%}")
    L.append(f"reference bw     : {_g(br.ref_bw)} GB/s  [{br.ref_source}]")
    L.append("")
    L.append("slowness = 1 - bw/ref (0 = healthy, 1 = no bandwidth).")
    L.append("Leaf/node blame is deterministic (HIGH confidence); spine blame is "
             "ECMP-diluted (LOW).")
    L.append("")

    L.append("-- SUSPECT LEAF SWITCHES (>=2 slow nodes share the leaf) " + "-" * 21)
    L.append(f"  {'switch':<22} {'cell':<8} {'slow':>6} {'med BW':>8} {'nodes'}")
    for s in br.leaf_suspects[:top_n]:
        L.append(f"  {s.name:<22} {s.cell:<8} {_pct(s.median_slowness):>6} "
                 f"{_g(s.median_bw):>8}  {','.join(n.split('.')[0] for n in s.nodes)}")
    if not br.leaf_suspects:
        L.append("  none — no leaf has >=2 co-located slow nodes.")
    L.append("")

    L.append("-- LONE SLOW NODES (node/NIC fault, not the leaf) " + "-" * 28)
    L.append(f"  {'node':<22} {'cell':<8} {'slow':>6} {'med BW':>8}")
    for s in br.node_suspects[:top_n]:
        L.append(f"  {s.name.split('.')[0]:<22} {s.cell:<8} "
                 f"{_pct(s.median_slowness):>6} {_g(s.median_bw):>8}")
    if not br.node_suspects:
        L.append("  none.")
    L.append("")

    L.append("-- CANDIDATE SPINE SWITCHES / LINKS (LOW confidence) " + "-" * 25)
    L.append(f"  {'element':<46} {'slow':>6} {'flows':>6}")
    for s in br.spine_suspects[:top_n]:
        L.append(f"  {s.name:<46} {_pct(s.median_slowness):>6} {s.n_flows:>6}")
    if not br.spine_suspects:
        L.append("  none above threshold.")
    L.append("")

    L.append("-- NOTES " + "-" * 69)
    for w in br.warnings:
        L.append(f"  ! {w}")
    if br.n_lone_nodes:
        L.append(f"  ! {br.n_lone_nodes} node(s) have no same-switch peer in this "
                 "run, so node-vs-leaf cannot be told apart for them — not "
                 "node-blamed (see the main report's under-performing nodes).")
    L.append("  ! ECMP dilution caps spine sensitivity; leaf/node blame is the "
             "trustworthy part.")
    L.append("  ! single-run point estimate; meaningful on an idle fabric.")
    L.append("=" * 78)
    return "\n".join(L)


def build_blame_summary(br: BlameResult) -> dict:
    def sus(s: Suspect) -> dict:
        return {"kind": s.kind, "name": s.name, "cell": s.cell,
                "confidence": s.confidence, "n_flows": s.n_flows,
                "median_slowness": s.median_slowness, "median_bw_gbs": s.median_bw,
                "ref_bw_gbs": s.ref_bw, "nodes": s.nodes, "note": s.note}
    return {
        "ref_bw_gbs": br.ref_bw,
        "ref_source": br.ref_source,
        "n_flows": br.n_flows,
        "resolved_frac": br.resolved_frac,
        "is_loaded": br.is_loaded,
        "leaf_suspects": [sus(s) for s in br.leaf_suspects],
        "node_suspects": [sus(s) for s in br.node_suspects],
        "spine_suspects": [sus(s) for s in br.spine_suspects],
        "warnings": br.warnings,
    }
