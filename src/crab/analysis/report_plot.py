"""Graphical report for the tournament analysis.

Produces, into ``outdir``:
  1. per-node bandwidth bar chart (flagged nodes in red, global median line)
  2. per-node latency bar chart
  3. bandwidth-vs-topology-distance box plot
  4. per-round topology-mix stacked bar with round median bandwidth overlaid
  5. pairwise bandwidth heatmap (node x peer, locality-colored borders)
  6. bandwidth & latency CDFs (slow region shaded)
  7. per-round bandwidth box plot
  8. overview.png — 2x2 summary of the above
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

    # 5. pairwise bandwidth heatmap ---------------------------------------
    p = _plot_heatmap(an, outdir, plt)
    if p:
        paths.append(p)

    # 6. bandwidth & latency CDFs -----------------------------------------
    p = _plot_cdf(an, outliers, outdir, plt)
    if p:
        paths.append(p)

    # 7. per-round bandwidth box plot -------------------------------------
    p = _plot_round_box(an, outdir, plt)
    if p:
        paths.append(p)

    # 8. one-glance overview ----------------------------------------------
    p = _plot_overview(an, outliers, outdir, plt)
    if p:
        paths.append(p)

    if show:
        plt.show()
    return paths


def _plot_overview(an: Analysis, outliers, outdir: str, plt) -> str:
    """A 2x2 summary: per-node BW, BW-by-distance, per-round mix, BW CDF."""
    fig, axs = plt.subplots(2, 2, figsize=(13, 9))
    flagged = {f.node for f in outliers.flagged}

    # A: per-node bandwidth
    ax = axs[0, 0]
    nodes_sorted = sorted(an.nodes, key=lambda x: x.median_bw_gbs)
    labels = [_short(ns.node) for ns in nodes_sorted]
    colors = ["#d62728" if ns.node in flagged else "#1f77b4" for ns in nodes_sorted]
    ax.bar(labels, [ns.median_bw_gbs for ns in nodes_sorted], color=colors)
    gm = float(np.median([ns.median_bw_gbs for ns in an.nodes]))
    ax.axhline(gm, ls="--", color="k", lw=1, label=f"median {gm:.1f}")
    ax.set_ylabel("median BW (GB/s, FD)")
    ax.set_title("Per-node bandwidth (red = slow)")
    ax.tick_params(axis="x", rotation=90, labelsize=7)
    ax.legend(fontsize=8)

    # B: bandwidth by topology distance
    ax = axs[0, 1]
    by_loc = {lab: [] for lab in _LOC_ORDER}
    for pr in an.pairings:
        by_loc[pr.label].extend(bandwidth_gbs(pr.durations, an.params).tolist())
    present = [lab for lab in _LOC_ORDER if by_loc[lab]]
    if present:
        bp = ax.boxplot([by_loc[l] for l in present], tick_labels=present,
                        patch_artist=True, showfliers=False)
        for patch, lab in zip(bp["boxes"], present):
            patch.set_facecolor(_LOC_COLOR[lab])
            patch.set_alpha(0.6)
    ax.set_ylabel("BW (GB/s, FD)")
    ax.set_title("Bandwidth vs topology distance")

    # C: per-round topology mix + median bandwidth
    ax = axs[1, 0]
    if an.rounds:
        rounds = [r.round_index for r in an.rounds]
        bottom = np.zeros(len(an.rounds))
        for lab in _LOC_ORDER:
            h = np.array([r.mix.get(lab, 0) for r in an.rounds], dtype=float)
            if h.sum() == 0:
                continue
            ax.bar(rounds, h, bottom=bottom, label=lab, color=_LOC_COLOR[lab],
                   alpha=0.8)
            bottom += h
        ax.set_xlabel("round")
        ax.set_ylabel("pairings by distance")
        ax.set_xticks(rounds)
        ax.legend(fontsize=7, loc="upper left")
        ax2 = ax.twinx()
        ax2.plot(rounds, [r.bw.median for r in an.rounds], "ko-", lw=1.3)
        ax2.set_ylabel("median BW (GB/s)")
    ax.set_title("Per-round topology mix & bandwidth")

    # D: bandwidth CDF
    ax = axs[1, 1]
    bw = np.concatenate([bandwidth_gbs(p.durations, an.params)
                         for p in an.pairings]) if an.pairings else np.array([])
    bw = bw[np.isfinite(bw)]
    if bw.size:
        a = np.sort(bw)
        ax.plot(a, np.arange(1, a.size + 1) / a.size, lw=1.8)
        if np.isfinite(outliers.median):
            ax.axvline(outliers.median, ls="--", color="k", lw=1,
                       label=f"median {outliers.median:.1f}")
        if np.isfinite(outliers.slow_threshold):
            lo = min(float(bw.min()), outliers.slow_threshold)
            ax.axvspan(lo, outliers.slow_threshold, color="#d62728", alpha=0.12)
            ax.axvline(outliers.slow_threshold, ls=":", color="#d62728", lw=1.2,
                       label=f"slow < {outliers.slow_threshold:.1f}")
        ax.legend(fontsize=8)
    ax.set_xlabel("BW (GB/s, FD)")
    ax.set_ylabel("cumulative fraction")
    ax.grid(True, alpha=0.3)
    ax.set_title("Bandwidth CDF")

    p = an.params
    fig.suptitle(f"{os.path.basename(an.dataset.exp_dir.rstrip(os.sep))}  |  "
                 f"{len(an.dataset.nodes)} nodes, {an.dataset.n_rounds} rounds  |  "
                 f"msg={p.msg_size} window={p.window} gran={p.granularity}",
                 fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out = os.path.join(outdir, "overview.png")
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def _plot_round_box(an: Analysis, outdir: str, plt) -> str:
    """Box plot of per-sample bandwidth, one box per tournament round."""
    rounds = sorted({p.round_index for p in an.pairings})
    if not rounds:
        return ""
    data, labels = [], []
    for r in rounds:
        vals = np.concatenate([bandwidth_gbs(p.durations, an.params)
                               for p in an.pairings if p.round_index == r])
        vals = vals[np.isfinite(vals)]
        if vals.size:
            data.append(vals)
            labels.append(str(r))
    if not data:
        return ""

    fig, ax = plt.subplots(figsize=(max(6, len(data) * 0.6), 4.5))
    bp = ax.boxplot(data, tick_labels=labels, patch_artist=True, showfliers=True)
    for patch in bp["boxes"]:
        patch.set_facecolor("#1f77b4")
        patch.set_alpha(0.6)
    ax.set_xlabel("round")
    ax.set_ylabel("bandwidth (GB/s, full-duplex)")
    ax.set_title("Per-round bandwidth distribution")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    out = os.path.join(outdir, "per_round_bandwidth_box.png")
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def _node_order(an: Analysis) -> list:
    """Order nodes by (cell, switch, name) so heatmap quadrants track topology."""
    topo = an.resolver.topology

    def key(node: str):
        short = _short(node)
        cell = sw = ""
        if topo is not None and short in topo.nodes:
            n = topo.nodes[short]
            cell = n.cell or ""
            sw = n.switches[0] if n.switches else ""
        return (cell, sw, short)

    return sorted((ns.node for ns in an.nodes), key=key)


def _plot_heatmap(an: Analysis, outdir: str, plt) -> str:
    from matplotlib.patches import Rectangle

    order = _node_order(an)
    if len(order) < 2:
        return ""
    idx = {node: i for i, node in enumerate(order)}
    n = len(order)
    mat = np.full((n, n), np.nan)
    loc_at = {}
    for pr in an.pairings:
        if pr.node_a not in idx or pr.node_b not in idx:
            continue
        med = float(np.median(bandwidth_gbs(pr.durations, an.params)))
        i, j = idx[pr.node_a], idx[pr.node_b]
        mat[i, j] = mat[j, i] = med
        loc_at[(i, j)] = loc_at[(j, i)] = pr.label

    fig, ax = plt.subplots(figsize=(max(5, n * 0.7), max(4.5, n * 0.6)))
    masked = np.ma.masked_invalid(mat)
    cmap = plt.get_cmap("viridis").copy()
    cmap.set_bad("lightgray")
    im = ax.imshow(masked, cmap=cmap, aspect="equal")
    fig.colorbar(im, ax=ax, label="median bandwidth (GB/s, full-duplex)")

    labels = [_short(x) for x in order]
    ax.set_xticks(range(n), labels, rotation=90, fontsize=8)
    ax.set_yticks(range(n), labels, fontsize=8)
    ax.set_title("Pairwise bandwidth (border = topology distance)")

    for (i, j), label in loc_at.items():
        ax.add_patch(Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False,
                               edgecolor=_LOC_COLOR.get(label, "#7f7f7f"), lw=2))
    for i in range(n):
        for j in range(n):
            if not np.isnan(mat[i, j]):
                ax.text(j, i, f"{mat[i, j]:.0f}", ha="center", va="center",
                        color="w", fontsize=7)
    # legend for the locality border colors actually present
    present = sorted(set(loc_at.values()))
    handles = [Rectangle((0, 0), 1, 1, fill=False, edgecolor=_LOC_COLOR.get(l, "#7f7f7f"),
                         lw=2, label=l) for l in present]
    if handles:
        ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.25, 1.0),
                  fontsize=8, title="distance")
    fig.tight_layout()
    out = os.path.join(outdir, "pairwise_heatmap.png")
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def _plot_cdf(an: Analysis, outliers, outdir: str, plt) -> str:
    bw = np.concatenate([bandwidth_gbs(p.durations, an.params)
                         for p in an.pairings]) if an.pairings else np.array([])
    lat = np.concatenate([(p.durations / (an.params.window * an.params.granularity))
                          for p in an.pairings]) if an.pairings else np.array([])
    bw = bw[np.isfinite(bw)]
    lat = lat[np.isfinite(lat)]
    if bw.size == 0:
        return ""

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5))

    def cdf(ax, vals, xlabel):
        a = np.sort(vals)
        y = np.arange(1, a.size + 1) / a.size
        ax.plot(a, y, lw=1.8)
        ax.set_xlabel(xlabel)
        ax.set_ylabel("cumulative fraction")
        ax.grid(True, alpha=0.3)

    cdf(ax1, bw, "bandwidth (GB/s, full-duplex)")
    ax1.set_title("Bandwidth CDF")
    if np.isfinite(outliers.median):
        ax1.axvline(outliers.median, ls="--", color="k", lw=1,
                    label=f"node median {outliers.median:.1f}")
    if np.isfinite(outliers.slow_threshold):
        # shade the "slow" region = bandwidth below the threshold; empty (no
        # visible band) when the threshold sits left of all data
        lo = min(float(bw.min()), outliers.slow_threshold)
        ax1.axvspan(lo, outliers.slow_threshold, color="#d62728", alpha=0.12)
        ax1.axvline(outliers.slow_threshold, ls=":", color="#d62728", lw=1.2,
                    label=f"slow < {outliers.slow_threshold:.1f}")
    ax1.legend(fontsize=8)

    cdf(ax2, lat * 1e6, "per-iteration latency (us)")
    suffix = " (amortized)" if an.params.window != 1 else ""
    ax2.set_title("Latency CDF" + suffix)
    ax2.axvline(float(np.median(lat * 1e6)), ls="--", color="k", lw=1,
                label=f"median {np.median(lat) * 1e6:.1f} us")
    ax2.legend(fontsize=8)

    fig.tight_layout()
    out = os.path.join(outdir, "cdf_bandwidth_latency.png")
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out
