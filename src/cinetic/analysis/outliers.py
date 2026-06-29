"""Flag under-performing nodes.

Per-node headline metric = median full-duplex bandwidth across all its matches.
A node is flagged **slow** by a robust z-score (median/MAD) below ``-k``. Because
MAD across a handful of nodes is meaningless (and the data is a single final
run), when the node count is below ``min_nodes`` the absolute ``frac * median``
rule becomes the primary flag and the z-score is demoted, with a low-confidence
warning.

Both rules above are **relative** to the run's own median, so they cannot catch a
*fabric-wide* regression (every node equally slow agrees with the median). When a
nominal per-node bandwidth is supplied (``expected_bw``, GB/s, same full-duplex
busbw basis the report prints), a third **absolute-vs-nominal** rule flags any
node below ``expected_frac * expected_bw`` and, if the *median itself* falls under
that floor, raises a fabric-wide-degradation verdict. This rule fires at any node
count — it is the sanity check's defence against uniform degradation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np

MAD_TO_STD = 1.4826


@dataclass
class Flagged:
    node: str
    value: float            # median bandwidth GB/s
    zscore: float           # robust z (nan if undefined)
    deviation_pct: float    # (value - median) / median * 100
    reason: str
    pct_nominal: float = float("nan")   # value / expected_bw * 100 (nan if no nominal)


@dataclass
class OutlierResult:
    median: float
    mad: float
    slow_threshold: float = float("nan")   # absolute cutoff = frac * median
    flagged: List[Flagged] = field(default_factory=list)
    method: str = ""
    low_confidence: bool = False
    warnings: List[str] = field(default_factory=list)
    # absolute-vs-nominal layer (all nan/false when no expected_bw supplied)
    expected_bw: float = float("nan")          # nominal per-node GB/s
    nominal_threshold: float = float("nan")    # expected_frac * expected_bw
    median_pct_nominal: float = float("nan")   # median / expected_bw * 100
    fabric_wide_degraded: bool = False         # median itself below the floor


def detect(node_bw_median: Dict[str, float], k: float = 3.0,
           frac: float = 0.7, min_nodes: int = 8,
           expected_bw: float | None = None,
           expected_frac: float = 0.8) -> OutlierResult:
    items = [(n, v) for n, v in node_bw_median.items() if np.isfinite(v)]
    res = OutlierResult(median=float("nan"), mad=float("nan"))
    if not items:
        res.warnings.append("no finite per-node bandwidth; cannot flag outliers")
        return res

    nodes = [n for n, _ in items]
    vals = np.array([v for _, v in items], dtype=float)
    med = float(np.median(vals))
    mad = float(np.median(np.abs(vals - med)))
    res.median, res.mad = med, mad

    n = len(items)
    small = n < min_nodes
    res.low_confidence = small

    nominal: float | None = None
    if expected_bw is not None:
        eb = float(expected_bw)
        if np.isfinite(eb) and eb > 0:
            nominal = eb
    if nominal is not None:
        res.expected_bw = nominal
        res.nominal_threshold = expected_frac * nominal
        res.median_pct_nominal = med / nominal * 100
        res.fabric_wide_degraded = med < res.nominal_threshold
        if res.fabric_wide_degraded:
            res.warnings.append(
                f"FABRIC-WIDE DEGRADATION: run median {med:.2f} GB/s is "
                f"{res.median_pct_nominal:.0f}% of nominal {nominal:.2f} GB/s "
                f"(< {expected_frac:g}x) — relative outlier rules can miss this")

    nominal_note = (f"; absolute vs nominal (<{expected_frac:g}x {nominal:g} GB/s)"
                    if nominal is not None else "")
    if small:
        res.method = (f"absolute frac*median (frac={frac}); robust z demoted "
                      f"(only {n} nodes){nominal_note}")
        res.warnings.append(
            f"low confidence: {n} node(s) and a single final run — robust z-score "
            "is unreliable, using the absolute threshold as primary")
    else:
        res.method = (f"robust z-score (k={k}); abs frac*median (frac={frac}) "
                      f"as backup{nominal_note}")

    thr_abs = frac * med
    res.slow_threshold = thr_abs
    sigma = mad * MAD_TO_STD

    for node, v in zip(nodes, vals):
        z = (v - med) / sigma if sigma > 0 else float("nan")
        dev = (v - med) / med * 100 if med else float("nan")
        pct_nom = (v / nominal * 100) if nominal is not None else float("nan")
        slow_abs = v < thr_abs
        slow_z = (np.isfinite(z) and z < -k)
        slow_nom = nominal is not None and v < res.nominal_threshold
        # Small-N: the z-score is unreliable (a ~0 MAD blows it up on a trivial
        # spread), so flag on the absolute rule ONLY. Large-N: either rule flags.
        # The nominal rule is absolute, so it fires regardless of node count.
        flag = (slow_abs if small else (slow_z or slow_abs)) or slow_nom
        if flag:
            why = []
            if not small and slow_z:
                why.append(f"z={z:.1f}")
            if slow_abs:
                why.append(f"<{frac:g}x median")
            if slow_nom:
                why.append(f"<{expected_frac:g}x nominal")
            res.flagged.append(Flagged(node=node, value=v, zscore=z,
                                       deviation_pct=dev, reason=", ".join(why),
                                       pct_nominal=pct_nom))

    res.flagged.sort(key=lambda f: f.value)
    return res
