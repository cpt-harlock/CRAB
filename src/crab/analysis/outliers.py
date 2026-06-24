"""Flag under-performing nodes.

Per-node headline metric = median full-duplex bandwidth across all its matches.
A node is flagged **slow** by a robust z-score (median/MAD) below ``-k``. Because
MAD across a handful of nodes is meaningless (and the data is a single final
run), when the node count is below ``min_nodes`` the absolute ``frac * median``
rule becomes the primary flag and the z-score is demoted, with a low-confidence
warning.
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


@dataclass
class OutlierResult:
    median: float
    mad: float
    slow_threshold: float = float("nan")   # absolute cutoff = frac * median
    flagged: List[Flagged] = field(default_factory=list)
    method: str = ""
    low_confidence: bool = False
    warnings: List[str] = field(default_factory=list)


def detect(node_bw_median: Dict[str, float], k: float = 3.0,
           frac: float = 0.7, min_nodes: int = 8) -> OutlierResult:
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
    if small:
        res.method = (f"absolute frac*median (frac={frac}); robust z demoted "
                      f"(only {n} nodes)")
        res.warnings.append(
            f"low confidence: {n} node(s) and a single final run — robust z-score "
            "is unreliable, using the absolute threshold as primary")
    else:
        res.method = f"robust z-score (k={k}); abs frac*median (frac={frac}) as backup"

    thr_abs = frac * med
    res.slow_threshold = thr_abs
    sigma = mad * MAD_TO_STD

    for node, v in zip(nodes, vals):
        z = (v - med) / sigma if sigma > 0 else float("nan")
        dev = (v - med) / med * 100 if med else float("nan")
        slow_abs = v < thr_abs
        slow_z = (np.isfinite(z) and z < -k)
        # Small-N: the z-score is unreliable (a ~0 MAD blows it up on a trivial
        # spread), so flag on the absolute rule ONLY. Large-N: either rule flags.
        flag = slow_abs if small else (slow_z or slow_abs)
        if flag:
            why = []
            if not small and slow_z:
                why.append(f"z={z:.1f}")
            if slow_abs:
                why.append(f"<{frac:g}x median")
            res.flagged.append(Flagged(node=node, value=v, zscore=z,
                                       deviation_pct=dev, reason=", ".join(why)))

    res.flagged.sort(key=lambda f: f.value)
    return res
