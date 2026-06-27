"""Cross-experiment comparison (goal 2).

Aligns N analyzed apps (different runs, configs, or dates) by node and by
topology label and computes deltas; the baseline-vs-loaded congestion case (§4)
is the 2-series special case. Consumes the per-app
:class:`~cinetic.analysis.metrics.Analysis` objects — it does not re-parse.

Only same-kind analyses are comparable (a pairwise full-duplex bandwidth is not
the same quantity as a collective busbw); mixed kinds are flagged. With an
ordering (``--x`` or parseable timestamps) it also fits a linear trend of overall
bandwidth, for "is the fabric drifting over time" health tracking.

All numbers inherit the single-final-run caveat (node_*.csv hold one run).

See PLAN_ANALYSIS_REWORK.md §5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

from .metrics import Analysis
from .topo import normalize_host

_LABEL_ORDER = ("same_switch", "same_cell", "cross_cell", "unknown")


@dataclass
class Series:
    label: str
    kind: str
    overall_bw: float
    overall_lat: float
    node_bw: Dict[str, float] = field(default_factory=dict)   # short host -> bw
    node_lat: Dict[str, float] = field(default_factory=dict)
    label_bw: Dict[str, float] = field(default_factory=dict)  # topo label -> bw
    x: Optional[float] = None


@dataclass
class Row:
    """A per-node or per-label row: value in each series + delta% vs series 0."""
    key: str
    values: List[float]
    delta_pct: List[float]


@dataclass
class Trend:
    metric: str
    x: List[float]
    y: List[float]
    slope: float          # units per x
    intercept: float
    r: float              # Pearson correlation


@dataclass
class ComparisonResult:
    series: List[Series]
    kind: str
    relative: bool
    common_nodes: List[str] = field(default_factory=list)
    only_in: Dict[str, List[str]] = field(default_factory=dict)
    node_rows: List[Row] = field(default_factory=list)
    label_rows: List[Row] = field(default_factory=list)
    overall_bw: List[float] = field(default_factory=list)
    overall_bw_delta_pct: List[float] = field(default_factory=list)
    overall_lat: List[float] = field(default_factory=list)
    trend: Optional[Trend] = None
    caveats: List[str] = field(default_factory=list)


def series_from_analysis(label: str, an: Analysis,
                         x: Optional[float] = None) -> Series:
    return Series(
        label=label,
        kind=an.kind,
        overall_bw=an.overall_bw.median,
        overall_lat=an.overall_lat.median,
        node_bw={normalize_host(ns.node): ns.median_bw_gbs for ns in an.nodes},
        node_lat={normalize_host(ns.node): ns.median_lat_s for ns in an.nodes},
        label_bw={k: v.median for k, v in an.by_locality.items()},
        x=x,
    )


def _finite(x) -> bool:
    return x is not None and x == x


def _delta_pct(base: float, other: float) -> float:
    if not (_finite(base) and _finite(other)) or base == 0:
        return float("nan")
    return (other - base) / base * 100.0


def parse_timestamp(name: str) -> Optional[float]:
    """Epoch seconds from a run-dir basename like ``2026-06-26_15-19-25-450961``."""
    for fmt in ("%Y-%m-%d_%H-%M-%S-%f", "%Y-%m-%d_%H-%M-%S"):
        try:
            return datetime.strptime(name, fmt).timestamp()
        except ValueError:
            continue
    return None


def compare(series: List[Series], relative: bool = False) -> ComparisonResult:
    """Align *series* by node + topology label and compute deltas vs series[0]."""
    cr = ComparisonResult(series=series, relative=relative,
                          kind=series[0].kind if series else "?")
    kinds = {s.kind for s in series}
    if len(kinds) > 1:
        cr.kind = "mixed"
        cr.caveats.append(
            f"series span differing kinds {sorted(kinds)} — bandwidths are not "
            "the same quantity; comparison may be invalid.")
    cr.caveats.append(
        "single-run point estimates (node_*.csv hold only the final run).")
    if relative:
        cr.caveats.append("bandwidth normalized to each series' own overall "
                          "median (--bw-relative): param mismatch neutralized.")

    # optional per-series normalization (relative mode)
    def nb(s: Series, h: str) -> float:
        v = s.node_bw.get(h, float("nan"))
        if relative and _finite(s.overall_bw) and s.overall_bw:
            return v / s.overall_bw
        return v

    cr.overall_bw = [s.overall_bw for s in series]
    cr.overall_lat = [s.overall_lat for s in series]
    base_bw = series[0].overall_bw
    cr.overall_bw_delta_pct = [_delta_pct(base_bw, s.overall_bw) for s in series]

    # node alignment
    node_sets = [set(s.node_bw) for s in series]
    common = set.intersection(*node_sets) if node_sets else set()
    union = set.union(*node_sets) if node_sets else set()
    cr.common_nodes = sorted(common)
    for s, ns in zip(series, node_sets):
        missing = sorted(union - ns)
        if missing:
            cr.only_in[s.label] = missing

    for h in sorted(common):
        vals = [nb(s, h) for s in series]
        deltas = [_delta_pct(vals[0], v) for v in vals]
        cr.node_rows.append(Row(key=h, values=vals, delta_pct=deltas))
    # biggest mover (last vs first) first
    cr.node_rows.sort(
        key=lambda r: abs(r.delta_pct[-1]) if _finite(r.delta_pct[-1]) else -1,
        reverse=True)

    # topology-label alignment
    labels = [x for x in _LABEL_ORDER if any(x in s.label_bw for s in series)]
    for lab in labels:
        vals = [s.label_bw.get(lab, float("nan")) for s in series]
        if relative:
            vals = [(v / s.overall_bw) if (_finite(v) and _finite(s.overall_bw)
                                           and s.overall_bw) else float("nan")
                    for v, s in zip(vals, series)]
        deltas = [_delta_pct(vals[0], v) for v in vals]
        cr.label_rows.append(Row(key=lab, values=vals, delta_pct=deltas))

    # trend (needs x on every series and >= 3 points)
    xs = [s.x for s in series]
    if len(series) >= 3 and all(x is not None for x in xs):
        cr.trend = _fit_trend([float(x) for x in xs if x is not None],
                              cr.overall_bw)
    return cr


def _fit_trend(x: List[float], y: List[float]) -> Optional[Trend]:
    ax, ay = np.asarray(x, float), np.asarray(y, float)
    m = np.isfinite(ax) & np.isfinite(ay)
    if m.sum() < 3:
        return None
    ax, ay = ax[m], ay[m]
    # shift x to a 0-based axis so the slope reads in GB/s per x-unit
    x0 = ax - ax.min()
    slope, intercept = np.polyfit(x0, ay, 1)
    r = float(np.corrcoef(x0, ay)[0, 1]) if ax.size > 1 else float("nan")
    return Trend(metric="overall_bw", x=list(map(float, ax)),
                 y=list(map(float, ay)), slope=float(slope),
                 intercept=float(intercept), r=r)


# --------------------------------------------------------------------------- #
# report + summary
# --------------------------------------------------------------------------- #

def _g(x) -> str:
    return "n/a" if not _finite(x) else f"{x:.3f}"


def _pct(x) -> str:
    return "n/a" if not _finite(x) else f"{x:+.1f}%"


def format_comparison(cr: ComparisonResult, top_n: int = 20) -> str:
    unit = "rel" if cr.relative else "GB/s"
    L = ["=" * 78, "CROSS-EXPERIMENT COMPARISON", "=" * 78]
    L.append(f"kind           : {cr.kind}")
    L.append(f"series ({len(cr.series)}), deltas vs '{cr.series[0].label}':")
    for i, s in enumerate(cr.series):
        xs = "" if s.x is None else f"  x={s.x:g}"
        L.append(f"  [{i}] {s.label:<28} overall {_g(s.overall_bw)} GB/s "
                 f"({_pct(cr.overall_bw_delta_pct[i])}){xs}")
    L.append(f"common nodes   : {len(cr.common_nodes)}")
    for lab, miss in cr.only_in.items():
        L.append(f"  only-missing in {lab}: {len(miss)} node(s)")
    L.append("")

    L.append("-- OVERALL BANDWIDTH " + "-" * 57)
    L.append("  " + "  ".join(f"[{i}]{_g(v)}" for i, v in enumerate(cr.overall_bw)))
    L.append("")

    if cr.label_rows:
        L.append(f"-- BY TOPOLOGY LABEL ({unit}) " + "-" * 48)
        head = f"  {'label':<12}" + "".join(f"{'['+str(i)+']':>10}"
                                             for i in range(len(cr.series)))
        L.append(head + f"{'last Δ':>9}")
        for r in cr.label_rows:
            vals = "".join(f"{_g(v):>10}" for v in r.values)
            L.append(f"  {r.key:<12}{vals}{_pct(r.delta_pct[-1]):>9}")
        L.append("")

    if cr.node_rows:
        L.append(f"-- PER NODE (biggest last-series mover first; {unit}) "
                 + "-" * 25)
        head = f"  {'node':<14}" + "".join(f"{'['+str(i)+']':>10}"
                                           for i in range(len(cr.series)))
        L.append(head + f"{'last Δ':>9}")
        for r in cr.node_rows[:top_n]:
            vals = "".join(f"{_g(v):>10}" for v in r.values)
            L.append(f"  {r.key:<14}{vals}{_pct(r.delta_pct[-1]):>9}")
        if len(cr.node_rows) > top_n:
            L.append(f"  ... {len(cr.node_rows) - top_n} more (see JSON)")
        L.append("")

    if cr.trend is not None:
        t = cr.trend
        L.append("-- TREND (overall bandwidth vs x) " + "-" * 44)
        L.append(f"  slope {t.slope:+.4g} GB/s per x-unit   r={_g(t.r)}")
        L.append("")

    L.append("-- NOTES " + "-" * 69)
    for c in cr.caveats:
        L.append(f"  ! {c}")
    L.append("")
    L.append("=" * 78)
    return "\n".join(L)


def build_comparison_summary(cr: ComparisonResult) -> dict:
    return {
        "kind": cr.kind,
        "relative": cr.relative,
        "series": [{"label": s.label, "kind": s.kind, "x": s.x,
                    "overall_bw_gbs": s.overall_bw,
                    "overall_lat_s": s.overall_lat} for s in cr.series],
        "overall_bw_gbs": cr.overall_bw,
        "overall_bw_delta_pct": cr.overall_bw_delta_pct,
        "common_nodes": len(cr.common_nodes),
        "only_in": cr.only_in,
        "by_label": [{"label": r.key, "values": r.values,
                      "delta_pct": r.delta_pct} for r in cr.label_rows],
        "per_node": [{"node": r.key, "values": r.values,
                      "delta_pct": r.delta_pct} for r in cr.node_rows],
        "trend": (None if cr.trend is None else {
            "metric": cr.trend.metric, "slope": cr.trend.slope,
            "intercept": cr.trend.intercept, "r": cr.trend.r,
            "x": cr.trend.x, "y": cr.trend.y}),
        "caveats": cr.caveats,
    }
