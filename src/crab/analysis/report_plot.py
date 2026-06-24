"""Graphical report (v1 core figures) for the tournament analysis.

Produces, into ``outdir``:
  1. per-node bandwidth bar chart (flagged nodes in red, global median line)
  2. per-node latency bar chart
  3. bandwidth-vs-topology-distance box plot
  4. per-round topology-mix stacked bar with round median bandwidth overlaid
"""

from __future__ import annotations

import os
from typing import List

import numpy as np

from .metrics import Analysis, bandwidth_gbs
from .outliers import OutlierResult

_LOC_ORDER = ["same_switch", "same_cell", "cross_cell", "unknown"]
_LOC_COLOR = {"same_switch": "#2ca02c", "same_cell": "#1f77b4",
              "cross_cell": "#d62728", "unknown": "#7f7f7f"}


def _short(node: str) -> str:
    return node.split(".")[0]


def generate_plots(an: Analysis, outliers: OutlierResult, outdir: str,
                   show: bool = False) -> List[str]:
    import matplotlib
    if not show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(outdir, exist_ok=True)
    paths: List[str] = []
    flagged = {f.node for f in outliers.flagged}

    nodes_sorted = sorted(an.nodes, key=lambda x: x.median_bw_gbs)
    labels = [_short(ns.node) for ns in nodes_sorted]

    # 1. per-node bandwidth ------------------------------------------------
    fig, ax = plt.subplots(figsize=(max(6, len(labels) * 0.5), 4.5))
    vals = [ns.median_bw_gbs for ns in nodes_sorted]
    colors = ["#d62728" if ns.node in flagged else "#1f77b4"
              for ns in nodes_sorted]
    ax.bar(labels, vals, color=colors)
    gm = float(np.median([ns.median_bw_gbs for ns in an.nodes]))
    ax.axhline(gm, ls="--", color="k", lw=1, label=f"global median {gm:.1f}")
    ax.set_ylabel("median bandwidth (GB/s, full-duplex)")
    ax.set_title("Per-node bandwidth (red = under-performing)")
    ax.tick_params(axis="x", rotation=90)
    ax.legend()
    fig.tight_layout()
    p = os.path.join(outdir, "per_node_bandwidth.png")
    fig.savefig(p, dpi=120)
    paths.append(p)
    plt.close(fig)

    # 2. per-node latency --------------------------------------------------
    fig, ax = plt.subplots(figsize=(max(6, len(labels) * 0.5), 4.5))
    lat_us = [ns.median_lat_s * 1e6 for ns in nodes_sorted]
    ax.bar(labels, lat_us, color=colors)
    ax.set_ylabel("median per-iteration latency (us)")
    ax.set_title(f"Per-node latency  [window={an.params.window}"
                 f"{' (amortized)' if an.params.window != 1 else ''}]")
    ax.tick_params(axis="x", rotation=90)
    fig.tight_layout()
    p = os.path.join(outdir, "per_node_latency.png")
    fig.savefig(p, dpi=120)
    paths.append(p)
    plt.close(fig)

    # 3. bandwidth vs topology distance -----------------------------------
    by_loc = {lab: [] for lab in _LOC_ORDER}
    for pr in an.pairings:
        by_loc[pr.label].extend(bandwidth_gbs(pr.durations, an.params).tolist())
    present = [lab for lab in _LOC_ORDER if by_loc[lab]]
    if present:
        fig, ax = plt.subplots(figsize=(6, 4.5))
        data = [by_loc[lab] for lab in present]
        bp = ax.boxplot(data, tick_labels=present, patch_artist=True,
                        showfliers=False)
        for patch, lab in zip(bp["boxes"], present):
            patch.set_facecolor(_LOC_COLOR[lab])
            patch.set_alpha(0.6)
        ax.set_ylabel("bandwidth (GB/s, full-duplex)")
        ax.set_title("Bandwidth vs topology distance")
        fig.tight_layout()
        p = os.path.join(outdir, "bandwidth_by_locality.png")
        fig.savefig(p, dpi=120)
        paths.append(p)
        plt.close(fig)

    # 4. per-round topology mix + median bandwidth ------------------------
    if an.rounds:
        fig, ax = plt.subplots(figsize=(max(6, len(an.rounds) * 0.6), 4.5))
        rounds = [r.round_index for r in an.rounds]
        bottom = np.zeros(len(an.rounds))
        for lab in _LOC_ORDER:
            heights = np.array([r.mix.get(lab, 0) for r in an.rounds], dtype=float)
            if heights.sum() == 0:
                continue
            ax.bar(rounds, heights, bottom=bottom, label=lab,
                   color=_LOC_COLOR[lab], alpha=0.8)
            bottom += heights
        ax.set_xlabel("round")
        ax.set_ylabel("pairings by distance")
        ax.set_title("Per-round topology mix & bandwidth")
        ax.set_xticks(rounds)
        ax.legend(loc="upper left", fontsize=8)

        ax2 = ax.twinx()
        ax2.plot(rounds, [r.bw.median for r in an.rounds], "ko-", lw=1.5,
                 label="median BW")
        ax2.set_ylabel("median bandwidth (GB/s)")
        fig.tight_layout()
        p = os.path.join(outdir, "per_round_mix.png")
        fig.savefig(p, dpi=120)
        paths.append(p)
        plt.close(fig)

    if show:
        plt.show()
    return paths
