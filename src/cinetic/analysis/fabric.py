"""Fabric (switch/link) load attribution — goal 4.

Moves from "which **node** is slow" to "which **switch/link** is congested" by
estimating, for every flow in an experiment (victim *and* collecting aggressor),
the set of switches/links its traffic could traverse, and tallying expected load.

Routing on a fat-tree is multipath (ECMP), so an exact path is unknowable. We
build the real switch graph from the topology and, for each flow, distribute its
bandwidth across **all shortest paths** between the endpoints' leaf switches,
weighting each switch/link by the fraction of shortest paths through it (the
standard ECMP expected-load model). This is a *candidate* attribution — load
exposure, not a claimed route — and is labelled as such.

Flows per benchmark kind:
* pairwise  — each merged pairing A<->B at its median bandwidth;
* directed  — each per-peer hop A->B (e.g. a ring) at its median bandwidth;
* collective— no per-peer rows, so the communicator (from the manifest) is
  expanded into member pairs, each weighted by the members' per-node busbw
  spread over the comm (approximate; flagged).

See PLAN_ANALYSIS_REWORK.md §6.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from cinetic.topology.model import Topology
from .metrics import Analysis, bandwidth_gbs, match_bw
from .topo import normalize_host

Edge = Tuple[str, str]


# --------------------------------------------------------------------------- #
# switch graph
# --------------------------------------------------------------------------- #

def build_switch_graph(topo: Topology) -> Dict[str, set]:
    """Undirected adjacency of switches (edges = inter-switch links only)."""
    g: Dict[str, set] = {s: set() for s in topo.switches}
    for name, sw in topo.switches.items():
        for lk in sw.links:
            if lk.peer_name in topo.switches:
                g[name].add(lk.peer_name)
                g.setdefault(lk.peer_name, set()).add(name)
    return g


def _bfs_counts(graph: Dict[str, set], src: str):
    """BFS from *src*: (dist, n_shortest_paths) to every reachable switch."""
    dist = {src: 0}
    cnt = {src: 1}
    q = deque([src])
    while q:
        u = q.popleft()
        for v in graph.get(u, ()):
            if v not in dist:
                dist[v] = dist[u] + 1
                cnt[v] = cnt[u]
                q.append(v)
            elif dist[v] == dist[u] + 1:
                cnt[v] += cnt[u]
    return dist, cnt


@dataclass
class Route:
    hops: int                                   # switch hops along the route
    switch_w: Dict[str, float] = field(default_factory=dict)   # switch -> frac
    link_w: Dict[Edge, float] = field(default_factory=dict)    # edge   -> frac


def route(graph: Dict[str, set], la: str, lb: str, cache: dict) -> Optional[Route]:
    """ECMP expected-load route between leaf switches *la* and *lb*.

    Returns the fraction of shortest paths through each switch/link (so per
    flow the fractions at any cut sum to 1), or ``None`` if unreachable."""
    if la == lb:
        return Route(hops=0, switch_w={la: 1.0})
    da, ca = cache.setdefault(la, _bfs_counts(graph, la))
    if lb not in da:
        return None
    db, cb = cache.setdefault(lb, _bfs_counts(graph, lb))
    total = ca[lb]                      # number of shortest paths a->b
    if total <= 0:
        return None
    D = da[lb]
    r = Route(hops=D)
    # a switch w lies on a shortest path iff da[w] + db[w] == D
    for w, d in da.items():
        if w in db and d + db[w] == D:
            r.switch_w[w] = (ca[w] * cb[w]) / total
    # an edge (u,v) lies on a shortest path iff da[u] + 1 + db[v] == D
    for u, du in da.items():
        for v in graph.get(u, ()):
            if v in db and du + 1 + db[v] == D:
                e = (u, v) if u < v else (v, u)
                r.link_w[e] = r.link_w.get(e, 0.0) + (ca[u] * cb[v]) / total
    return r


# --------------------------------------------------------------------------- #
# flows
# --------------------------------------------------------------------------- #

@dataclass
class Flow:
    a: str          # short hostname
    b: str          # short hostname
    bw: float       # GB/s carried by this flow


def flows_from_analysis(an: Analysis) -> List[Flow]:
    """Extract (host_a, host_b, bandwidth) flows from one app's analysis."""
    flows: List[Flow] = []
    if an.kind == "pairwise":
        for pr in an.pairings:
            bw = np.median(bandwidth_gbs(pr.durations, an.params,
                                         pr.bytes_per_sample))
            if np.isfinite(bw):
                flows.append(Flow(normalize_host(pr.node_a),
                                  normalize_host(pr.node_b), float(bw)))
    elif an.kind == "directed":
        for m in an.dataset.matches:
            if m.is_collective or not m.peer_node:
                continue
            bw = np.median(match_bw(m, an.params))
            if np.isfinite(bw):
                flows.append(Flow(normalize_host(m.node),
                                  normalize_host(m.peer_node), float(bw)))
    else:  # collective: expand the communicator into member pairs (approximate)
        nodebw = {normalize_host(ns.node): ns.median_bw_gbs for ns in an.nodes}
        for members in an.dataset.comms.values():
            short = [normalize_host(x) for x in members]
            n = len(short)
            if n < 2:
                continue
            for i in range(n):
                for j in range(i + 1, n):
                    wa = nodebw.get(short[i], float("nan"))
                    wb = nodebw.get(short[j], float("nan"))
                    pair_bw = np.nanmean([wa, wb]) / (n - 1)
                    if np.isfinite(pair_bw):
                        flows.append(Flow(short[i], short[j], float(pair_bw)))
    return flows


# --------------------------------------------------------------------------- #
# attribution
# --------------------------------------------------------------------------- #

@dataclass
class SwitchLoad:
    ib_name: str
    role: str
    cell: str
    load: float


@dataclass
class LinkLoad:
    a: str
    b: str
    load: float


@dataclass
class FabricLoad:
    switches: List[SwitchLoad] = field(default_factory=list)   # sorted desc
    links: List[LinkLoad] = field(default_factory=list)        # sorted desc
    n_flows: int = 0
    n_unresolved: int = 0
    hops_hist: Dict[int, int] = field(default_factory=dict)
    resolved_frac: float = 0.0
    warnings: List[str] = field(default_factory=list)
    approximate_collective: bool = False


def _switch_cell_map(topo: Topology) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for c in topo.cells:
        for s in list(c.leaf_switches) + list(c.spine_switches):
            out[s] = c.name
    return out


def attribute(analyses: List[Analysis], topo: Topology,
              min_frac: float = 0.8) -> Optional[FabricLoad]:
    """Aggregate expected switch/link load across all flows of *analyses*.

    Returns ``None`` (with no attribution) when fewer than *min_frac* of the
    flow endpoints resolve in the topology — the wrong-topology guard."""
    graph = build_switch_graph(topo)
    cell_of = _switch_cell_map(topo)
    cache: dict = {}

    sl: Dict[str, float] = {}
    ll: Dict[Edge, float] = {}
    fl = FabricLoad()
    seen_hosts: set = set()
    resolved_hosts: set = set()

    for an in analyses:
        if an.kind == "collective":
            fl.approximate_collective = True
        for f in flows_from_analysis(an):
            for h in (f.a, f.b):
                seen_hosts.add(h)
            na = topo.nodes.get(f.a)
            nb = topo.nodes.get(f.b)
            if na is not None and na.switches:
                resolved_hosts.add(f.a)
            if nb is not None and nb.switches:
                resolved_hosts.add(f.b)
            if na is None or nb is None or not na.switches or not nb.switches:
                fl.n_unresolved += 1
                continue
            r = route(graph, na.switches[0], nb.switches[0], cache)
            if r is None:
                fl.n_unresolved += 1
                continue
            fl.n_flows += 1
            fl.hops_hist[r.hops] = fl.hops_hist.get(r.hops, 0) + 1
            for sw, frac in r.switch_w.items():
                sl[sw] = sl.get(sw, 0.0) + frac * f.bw
            for e, frac in r.link_w.items():
                ll[e] = ll.get(e, 0.0) + frac * f.bw

    fl.resolved_frac = (len(resolved_hosts) / len(seen_hosts)) if seen_hosts else 0.0
    if fl.resolved_frac < min_frac:
        return None

    fl.switches = sorted(
        (SwitchLoad(ib_name=s, role=topo.switches[s].role if s in topo.switches
                    else "unknown", cell=cell_of.get(s, "?"), load=v)
         for s, v in sl.items()),
        key=lambda x: x.load, reverse=True)
    fl.links = sorted(
        (LinkLoad(a=a, b=b, load=v) for (a, b), v in ll.items()),
        key=lambda x: x.load, reverse=True)
    if fl.approximate_collective:
        fl.warnings.append(
            "collective flows are approximate (manifest member-pair expansion).")
    return fl


# --------------------------------------------------------------------------- #
# report + summary
# --------------------------------------------------------------------------- #

def _g(x) -> str:
    return "n/a" if x is None or x != x else f"{x:.2f}"


def format_fabric(fl: FabricLoad, top_n: int = 15) -> str:
    L = ["=" * 78, "FABRIC LOAD ATTRIBUTION (candidate links/switches)", "=" * 78]
    L.append(f"flows attributed : {fl.n_flows}  (unresolved: {fl.n_unresolved})")
    L.append(f"host resolution  : {fl.resolved_frac:.0%}")
    if fl.hops_hist:
        mix = "  ".join(f"{k}h:{v}" for k, v in sorted(fl.hops_hist.items()))
        L.append(f"switch-hop mix   : {mix}")
    L.append("")
    L.append("Load = sum over flows of (flow bandwidth x fraction of shortest "
             "paths through it).")
    L.append("ECMP expected load — a candidate exposure, not a claimed route.")
    L.append("")

    L.append(f"-- TOP {top_n} SWITCHES (by load) " + "-" * 44)
    L.append(f"  {'switch':<22} {'role':<6} {'cell':<8} {'load GB/s':>10}")
    for s in fl.switches[:top_n]:
        L.append(f"  {s.ib_name:<22} {s.role:<6} {s.cell:<8} {_g(s.load):>10}")
    if not fl.switches:
        L.append("  (none)")
    L.append("")

    L.append(f"-- TOP {top_n} LINKS (by load) " + "-" * 47)
    L.append(f"  {'switch A':<22} {'switch B':<22} {'load GB/s':>10}")
    for lk in fl.links[:top_n]:
        L.append(f"  {lk.a:<22} {lk.b:<22} {_g(lk.load):>10}")
    if not fl.links:
        L.append("  (none — all flows intra-switch)")
    L.append("")

    if fl.warnings:
        L.append("-- NOTES " + "-" * 69)
        for w in fl.warnings:
            L.append(f"  ! {w}")
        L.append("")
    L.append("=" * 78)
    return "\n".join(L)


def build_fabric_summary(fl: FabricLoad, top_n: int = 50) -> dict:
    return {
        "n_flows": fl.n_flows,
        "n_unresolved": fl.n_unresolved,
        "resolved_frac": fl.resolved_frac,
        "hops_hist": fl.hops_hist,
        "approximate_collective": fl.approximate_collective,
        "top_switches": [{"ib_name": s.ib_name, "role": s.role, "cell": s.cell,
                          "load_gbs": s.load} for s in fl.switches[:top_n]],
        "top_links": [{"a": lk.a, "b": lk.b, "load_gbs": lk.load}
                      for lk in fl.links[:top_n]],
        "warnings": fl.warnings,
    }
