"""Congestion impact (goal 1): how much aggressors degrade victims.

Diffs a victim's per-app :class:`~cinetic.analysis.metrics.Analysis` between a
**baseline** experiment (victims only) and a **loaded** experiment (same victim +
aggressors). It *consumes* the already-computed Analysis objects (overall +
per-node + per-label stats) — it does not re-parse files or recompute bandwidth.

Sign convention: **bandwidth drop %** is positive when loaded bandwidth is lower
than baseline (the expected congestion direction); **latency increase %** is
positive when loaded latency is higher.

Caveat surfaced everywhere: ``node_*.csv`` hold only the final run, so each
degradation number is a single-run point estimate, not a statistical mean.

See PLAN_ANALYSIS_REWORK.md §4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .metrics import Analysis


def _short(host: str) -> str:
    return host.split(".")[0]


def _finite(x) -> bool:
    return x is not None and x == x   # NaN != NaN


def _drop_pct(base: float, loaded: float) -> float:
    """Bandwidth drop: positive = lower under load."""
    if not (_finite(base) and _finite(loaded)) or base <= 0:
        return float("nan")
    return (base - loaded) / base * 100.0


def _inc_pct(base: float, loaded: float) -> float:
    """Latency increase: positive = higher under load."""
    if not (_finite(base) and _finite(loaded)) or base <= 0:
        return float("nan")
    return (loaded - base) / base * 100.0


@dataclass
class NodeDegradation:
    node: str                # short hostname
    base_bw: float
    loaded_bw: float
    bw_drop_pct: float
    base_lat: float
    loaded_lat: float
    lat_inc_pct: float


@dataclass
class LabelDegradation:
    label: str               # topology label / comm span
    base_bw: float
    loaded_bw: float
    bw_drop_pct: float


@dataclass
class CongestionResult:
    victim_app: Optional[str]
    victim_benchmark: str
    baseline_label: str
    loaded_label: str
    base_overall_bw: float
    loaded_overall_bw: float
    overall_bw_drop_pct: float
    base_overall_lat: float
    loaded_overall_lat: float
    overall_lat_inc_pct: float
    per_node: List[NodeDegradation] = field(default_factory=list)
    per_label: List[LabelDegradation] = field(default_factory=list)
    n_common_nodes: int = 0
    only_in_baseline: List[str] = field(default_factory=list)
    only_in_loaded: List[str] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)


_LABEL_ORDER = ("same_switch", "same_cell", "cross_cell", "unknown")


def compute_congestion(baseline: Analysis, loaded: Analysis,
                       baseline_label: str = "baseline",
                       loaded_label: str = "loaded",
                       victim_benchmark: str = "") -> CongestionResult:
    """Align *baseline* and *loaded* victim analyses and compute degradation."""
    caveats = [
        "single-run point estimate (node_*.csv hold only the final run); "
        "not a statistical mean — interpret small differences cautiously.",
    ]
    if baseline.kind != loaded.kind:
        caveats.append(
            f"baseline kind ({baseline.kind}) != loaded kind ({loaded.kind}); "
            "metrics may not be directly comparable.")

    cr = CongestionResult(
        victim_app=loaded.app_id,
        victim_benchmark=victim_benchmark,
        baseline_label=baseline_label,
        loaded_label=loaded_label,
        base_overall_bw=baseline.overall_bw.median,
        loaded_overall_bw=loaded.overall_bw.median,
        overall_bw_drop_pct=_drop_pct(baseline.overall_bw.median,
                                      loaded.overall_bw.median),
        base_overall_lat=baseline.overall_lat.median,
        loaded_overall_lat=loaded.overall_lat.median,
        overall_lat_inc_pct=_inc_pct(baseline.overall_lat.median,
                                     loaded.overall_lat.median),
        caveats=caveats,
    )

    bmap = {_short(ns.node): ns for ns in baseline.nodes}
    lmap = {_short(ns.node): ns for ns in loaded.nodes}
    common = sorted(set(bmap) & set(lmap))
    cr.n_common_nodes = len(common)
    cr.only_in_baseline = sorted(set(bmap) - set(lmap))
    cr.only_in_loaded = sorted(set(lmap) - set(bmap))
    if not common:
        cr.caveats.append("no common nodes between baseline and loaded; "
                          "per-node degradation unavailable.")

    for h in common:
        b, l = bmap[h], lmap[h]
        cr.per_node.append(NodeDegradation(
            node=h,
            base_bw=b.median_bw_gbs, loaded_bw=l.median_bw_gbs,
            bw_drop_pct=_drop_pct(b.median_bw_gbs, l.median_bw_gbs),
            base_lat=b.median_lat_s, loaded_lat=l.median_lat_s,
            lat_inc_pct=_inc_pct(b.median_lat_s, l.median_lat_s)))
    # worst-hit nodes first
    cr.per_node.sort(key=lambda d: (d.bw_drop_pct if _finite(d.bw_drop_pct)
                                    else -1e9), reverse=True)

    labels = [x for x in _LABEL_ORDER
              if x in baseline.by_locality or x in loaded.by_locality]
    for lab in labels:
        bb = baseline.by_locality.get(lab)
        ll = loaded.by_locality.get(lab)
        bv = bb.median if bb else float("nan")
        lv = ll.median if ll else float("nan")
        cr.per_label.append(LabelDegradation(lab, bv, lv, _drop_pct(bv, lv)))

    return cr


def _g(x) -> str:
    return "n/a" if not _finite(x) else f"{x:.2f}"


def _pct(x) -> str:
    return "n/a" if not _finite(x) else f"{x:+.1f}%"


def format_congestion(cr: CongestionResult) -> str:
    """Human-readable congestion report (one victim, baseline vs loaded)."""
    L = ["=" * 78, "CONGESTION IMPACT (victim degradation under load)", "=" * 78]
    bench = f" [{cr.victim_benchmark}]" if cr.victim_benchmark else ""
    L.append(f"victim app     : {cr.victim_app}{bench}")
    L.append(f"baseline       : {cr.baseline_label}")
    L.append(f"loaded         : {cr.loaded_label}")
    L.append(f"common nodes   : {cr.n_common_nodes}")
    if cr.only_in_baseline:
        L.append(f"  baseline-only: {', '.join(cr.only_in_baseline)}")
    if cr.only_in_loaded:
        L.append(f"  loaded-only  : {', '.join(cr.only_in_loaded)}")
    L.append("")
    L.append("Sign: bandwidth drop% > 0 and latency inc% > 0 mean WORSE under load.")
    L.append("")

    L.append("-- OVERALL " + "-" * 67)
    L.append(f"  bandwidth : {_g(cr.base_overall_bw)} -> {_g(cr.loaded_overall_bw)} "
             f"GB/s   drop {_pct(cr.overall_bw_drop_pct)}")
    L.append(f"  latency   : {_g(cr.base_overall_lat * 1e6)} -> "
             f"{_g(cr.loaded_overall_lat * 1e6)} us   inc "
             f"{_pct(cr.overall_lat_inc_pct)}")
    L.append("")

    if cr.per_label:
        L.append("-- BY TOPOLOGY DISTANCE / COMM SPAN " + "-" * 42)
        L.append(f"  {'label':<12} {'base BW':>9} {'loaded BW':>10} {'drop':>8}")
        for d in cr.per_label:
            L.append(f"  {d.label:<12} {_g(d.base_bw):>9} {_g(d.loaded_bw):>10} "
                     f"{_pct(d.bw_drop_pct):>8}")
        L.append("")

    if cr.per_node:
        L.append("-- PER NODE (worst bandwidth drop first) " + "-" * 37)
        L.append(f"  {'node':<14} {'base BW':>9} {'loaded BW':>10} {'BW drop':>8} "
                 f"{'lat inc':>8}")
        for d in cr.per_node:
            L.append(f"  {d.node:<14} {_g(d.base_bw):>9} {_g(d.loaded_bw):>10} "
                     f"{_pct(d.bw_drop_pct):>8} {_pct(d.lat_inc_pct):>8}")
        L.append("")

    L.append("-- NOTES " + "-" * 69)
    for c in cr.caveats:
        L.append(f"  ! {c}")
    L.append("")
    L.append("=" * 78)
    return "\n".join(L)


def build_congestion_summary(cr: CongestionResult) -> dict:
    return {
        "victim_app": cr.victim_app,
        "victim_benchmark": cr.victim_benchmark,
        "baseline": cr.baseline_label,
        "loaded": cr.loaded_label,
        "overall": {
            "base_bw_gbs": cr.base_overall_bw,
            "loaded_bw_gbs": cr.loaded_overall_bw,
            "bw_drop_pct": cr.overall_bw_drop_pct,
            "base_lat_s": cr.base_overall_lat,
            "loaded_lat_s": cr.loaded_overall_lat,
            "lat_inc_pct": cr.overall_lat_inc_pct,
        },
        "n_common_nodes": cr.n_common_nodes,
        "only_in_baseline": cr.only_in_baseline,
        "only_in_loaded": cr.only_in_loaded,
        "by_label": [{"label": d.label, "base_bw_gbs": d.base_bw,
                      "loaded_bw_gbs": d.loaded_bw, "bw_drop_pct": d.bw_drop_pct}
                     for d in cr.per_label],
        "per_node": [{"node": d.node, "base_bw_gbs": d.base_bw,
                      "loaded_bw_gbs": d.loaded_bw, "bw_drop_pct": d.bw_drop_pct,
                      "base_lat_s": d.base_lat, "loaded_lat_s": d.loaded_lat,
                      "lat_inc_pct": d.lat_inc_pct} for d in cr.per_node],
        "caveats": cr.caveats,
    }


# --------------------------------------------------------------------------- #
# cross-config comparison (dose-response across runs)
# --------------------------------------------------------------------------- #

@dataclass
class CongestionCompareRow:
    label: str                          # per-config label (e.g. "1M/i")
    x: Optional[float]                  # numeric x for a trend (else None)
    victim_benchmark: str
    overall_bw_drop_pct: float
    overall_lat_inc_pct: float
    by_label_drop: Dict[str, float] = field(default_factory=dict)  # topo label -> drop%
    n_common_nodes: int = 0


@dataclass
class CongestionComparison:
    rows: List[CongestionCompareRow] = field(default_factory=list)
    labels_seen: List[str] = field(default_factory=list)   # ordered topo labels
    caveats: List[str] = field(default_factory=list)


def compare_congestion(
        items: Sequence[Tuple[str, Optional[float], CongestionResult]]
) -> CongestionComparison:
    """Aggregate per-run :class:`CongestionResult`s into a cross-config table —
    the dose-response view (victim drop% per config + per topology label)."""
    cc = CongestionComparison(caveats=[
        "single-run point estimates; cross-config deltas carry run-to-run "
        "variance — repeat runs to separate signal from noise.",
    ])
    seen: List[str] = []
    benches = set()
    for label, x, cr in items:
        by = {d.label: d.bw_drop_pct for d in cr.per_label}
        for d in cr.per_label:
            if d.label not in seen:
                seen.append(d.label)
        benches.add(cr.victim_benchmark)
        cc.rows.append(CongestionCompareRow(
            label=label, x=x, victim_benchmark=cr.victim_benchmark,
            overall_bw_drop_pct=cr.overall_bw_drop_pct,
            overall_lat_inc_pct=cr.overall_lat_inc_pct,
            by_label_drop=by, n_common_nodes=cr.n_common_nodes))
    cc.labels_seen = ([l for l in _LABEL_ORDER if l in seen]
                      + [l for l in seen if l not in _LABEL_ORDER])
    if len(benches) > 1:
        cc.caveats.append(
            f"runs mix victim benchmarks ({', '.join(sorted(benches))}); "
            "drops may not be directly comparable.")
    return cc


def format_congestion_comparison(cc: CongestionComparison) -> str:
    L = ["=" * 78, "CONGESTION COMPARISON (victim degradation across configs)",
         "=" * 78]
    benches = sorted({r.victim_benchmark for r in cc.rows if r.victim_benchmark})
    L.append(f"configs        : {len(cc.rows)}")
    L.append(f"victim         : {', '.join(benches) or '(unknown)'}")
    L.append("")
    L.append("bandwidth drop% > 0 = victim is slower under load (more congestion).")
    L.append("")

    have_x = any(r.x is not None for r in cc.rows)
    labels = cc.labels_seen
    head = f"  {'config':<16} {'x':>8} {'overall':>9}  " + \
        "  ".join(f"{l[:10]:>10}" for l in labels)
    L.append(head)
    for r in cc.rows:
        x = _g(r.x) if (have_x and r.x is not None) else "-"
        cells = "  ".join(f"{_pct(r.by_label_drop.get(l, float('nan'))):>10}"
                          for l in labels)
        L.append(f"  {r.label:<16} {x:>8} {_pct(r.overall_bw_drop_pct):>9}  {cells}")
    L.append("")
    L.append("-- NOTES " + "-" * 69)
    for c in cc.caveats:
        L.append(f"  ! {c}")
    L.append("=" * 78)
    return "\n".join(L)


def build_congestion_comparison_summary(cc: CongestionComparison) -> dict:
    return {
        "configs": [{"label": r.label, "x": r.x,
                     "victim_benchmark": r.victim_benchmark,
                     "overall_bw_drop_pct": r.overall_bw_drop_pct,
                     "overall_lat_inc_pct": r.overall_lat_inc_pct,
                     "by_label_drop_pct": r.by_label_drop,
                     "n_common_nodes": r.n_common_nodes} for r in cc.rows],
        "labels": cc.labels_seen,
        "caveats": cc.caveats,
    }
