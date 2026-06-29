"""Graphical report for the tournament analysis.

Produces, into ``outdir``:
  1. per-node bandwidth bar chart (flagged nodes in red, global median line)
  2. per-node latency bar chart
  3. bandwidth- and latency-vs-topology-distance box plots (overall average
     drawn as a dashed line)
  3b. the same, "exploded": one box plot per round *configuration* (rounds
      grouped by identical per-locality pairing counts), so each locality's
      bandwidth/latency is shown under a fixed concurrent fabric load, each
      panel annotated with that configuration's average
  4. per-round topology-mix stacked bar with round median bandwidth overlaid
  5. pairwise bandwidth heatmap (node x peer, locality-colored borders)
  6. bandwidth & latency CDFs (slow region shaded)
  7. per-round bandwidth box plot
  8. overview.png — 2x2 summary of the above
  9. (opt, --topo-graph) topology node-link diagram
"""

from __future__ import annotations

import os
from typing import List

import numpy as np

from .metrics import Analysis, bandwidth_gbs, latency_s
from .outliers import OutlierResult

_LOC_ORDER = ["same_switch", "same_cell", "cross_cell", "unknown"]
_LOC_COLOR = {"same_switch": "#2ca02c", "same_cell": "#1f77b4",
              "cross_cell": "#d62728", "unknown": "#7f7f7f"}

# Per-metric plotting config: how to turn a pairing's durations into samples,
# plus axis label, title word, output-file stem and number format. Lets the
# locality / by-config box plots be drawn for bandwidth and latency alike.
_METRIC = {
    "bandwidth": {"ylabel": "bandwidth (GB/s, full-duplex)", "title": "Bandwidth",
                  "file": "bandwidth_by_locality", "fmt": ".2f"},
    "latency":   {"ylabel": "per-iteration latency (us)", "title": "Latency",
                  "file": "latency_by_locality", "fmt": ".1f"},
}


def _pairing_samples(pr, params, kind: str) -> list:
    """One pairing -> metric samples (GB/s for bandwidth, microseconds for
    latency), using the pairing's embedded byte/op basis."""
    if kind == "latency":
        return (latency_s(pr.durations, params, pr.ops_per_sample) * 1e6).tolist()
    return bandwidth_gbs(pr.durations, params, pr.bytes_per_sample).tolist()


def _short(node: str) -> str:
    return node.split(".")[0]


def _config_signature(round_stat) -> tuple:
    """Canonical, hashable signature of a round's topology configuration: the
    tuple of per-locality pairing counts in ``_LOC_ORDER`` (e.g. ``(2, 0, 1, 0)``
    = 2 same_switch + 1 cross_cell). Rounds with the same signature ran under the
    same concurrent fabric load."""
    return tuple(round_stat.mix.get(lab, 0) for lab in _LOC_ORDER)


def _config_label(sig: tuple) -> str:
    parts = [f"{n}x {lab}" for lab, n in zip(_LOC_ORDER, sig) if n]
    return " + ".join(parts) if parts else "empty"


def generate_plots(an: Analysis, outliers: OutlierResult, outdir: str,
                   show: bool = False, topo_graph: bool = False) -> List[str]:
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

    # 3. bandwidth / latency vs topology distance (overall + exploded) -----
    for kind in ("bandwidth", "latency"):
        p = _plot_metric_by_locality(an, outdir, plt, kind)
        if p:
            paths.append(p)
        p = _plot_locality_by_config(an, outdir, plt, kind)
        if p:
            paths.append(p)

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

    # 5. pairwise bandwidth heatmap (pairwise only) -----------------------
    if an.pairings:
        p = _plot_heatmap(an, outdir, plt)
        if p:
            paths.append(p)

    # 6. bandwidth & latency CDFs (both kinds) ----------------------------
    p = _plot_cdf(an, outliers, outdir, plt)
    if p:
        paths.append(p)

    # 7. per-round bandwidth box plot (pairwise only) ---------------------
    p = _plot_round_box(an, outdir, plt)
    if p:
        paths.append(p)

    # 8. one-glance overview (pairwise only; collective views are above) --
    p = _plot_overview(an, outliers, outdir, plt) if an.pairings else ""
    if p:
        paths.append(p)

    # 9. (opt) topology node-link diagram ---------------------------------
    if topo_graph and an.pairings:
        p = _plot_topo_graph(an, outliers, outdir, plt)
        if p:
            paths.append(p)

    if show:
        plt.show()
    return paths


def _plot_metric_by_locality(an: Analysis, outdir: str, plt, kind: str) -> str:
    """Box plot of a metric (bandwidth or latency) grouped by topology distance
    (pairwise) or communicator span (collective), with a dashed line at the
    overall average. Reads the precomputed per-label sample buckets, so it works
    for both kinds and uses the standardized byte/op basis."""
    m = _METRIC[kind]
    src = an.bw_by_label if kind == "bandwidth" else an.lat_by_label
    scale = 1e6 if kind == "latency" else 1.0          # latency stored in seconds
    by_loc = {lab: (np.asarray(src[lab], dtype=float) * scale)
              for lab in _LOC_ORDER if lab in src and len(src[lab])}
    present = [lab for lab in _LOC_ORDER if lab in by_loc and by_loc[lab].size]
    if not present:
        return ""

    fig, ax = plt.subplots(figsize=(6, 4.5))
    bp = ax.boxplot([by_loc[lab] for lab in present], tick_labels=present,
                    patch_artist=True, showfliers=False)
    for patch, lab in zip(bp["boxes"], present):
        patch.set_facecolor(_LOC_COLOR[lab])
        patch.set_alpha(0.6)

    avg = float(np.mean(np.concatenate([np.asarray(by_loc[lab]) for lab in present])))
    ax.axhline(avg, ls="--", color="k", lw=1, label=f"overall avg {avg:{m['fmt']}}")
    ax.set_ylabel(m["ylabel"])
    ax.set_title(f"{m['title']} vs topology distance")
    ax.legend()
    fig.tight_layout()
    out = os.path.join(outdir, m["file"] + ".png")
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def _plot_locality_by_config(an: Analysis, outdir: str, plt, kind: str) -> str:
    """"Exploded" metric-vs-locality: group rounds by identical topology
    configuration (same per-locality pairing counts), then draw one
    metric-by-locality box plot per configuration, each with a dashed line at
    that configuration's average.

    The aggregate plot pools every pairing sample by its own locality, mixing
    samples taken under very different concurrent conditions (a same_switch pair
    while everyone else is also same_switch vs. while everyone else is
    cross_cell). Holding the round configuration fixed isolates each locality's
    metric under one fabric-load condition.
    """
    if not an.rounds:
        return ""

    m = _METRIC[kind]
    # group round indices by configuration signature
    groups: dict = {}
    for r in an.rounds:
        groups.setdefault(_config_signature(r), []).append(r.round_index)
    if len(groups) < 2:
        # a single configuration -> identical to the aggregate plot
        return ""

    sigs = sorted(groups)                       # deterministic panel order
    n = len(sigs)
    ncols = int(np.ceil(np.sqrt(n)))
    nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(
        nrows, ncols, sharey=True, squeeze=False,
        figsize=(max(4.0, ncols * 3.4), max(3.5, nrows * 3.4)))

    for idx, sig in enumerate(sigs):
        ax = axes[idx // ncols][idx % ncols]
        rset = set(groups[sig])
        by_loc = {lab: [] for lab in _LOC_ORDER}
        for pr in an.pairings:
            if pr.round_index in rset:
                by_loc[pr.label].extend(_pairing_samples(pr, an.params, kind))
        present = [lab for lab in _LOC_ORDER if by_loc[lab]]
        avg = None
        if present:
            bp = ax.boxplot([by_loc[lab] for lab in present], tick_labels=present,
                            patch_artist=True, showfliers=True)
            for patch, lab in zip(bp["boxes"], present):
                patch.set_facecolor(_LOC_COLOR[lab])
                patch.set_alpha(0.6)
            avg = float(np.mean(
                np.concatenate([np.asarray(by_loc[lab]) for lab in present])))
            ax.axhline(avg, ls="--", color="k", lw=0.8)
        nr = len(rset)
        avg_str = f", avg {avg:{m['fmt']}}" if avg is not None else ""
        ax.set_title(
            f"{_config_label(sig)}\n({nr} round{'s' if nr != 1 else ''}{avg_str})",
            fontsize=8)
        ax.tick_params(axis="x", rotation=45, labelsize=8)

    # turn off any empty panels in the grid
    for idx in range(n, nrows * ncols):
        axes[idx // ncols][idx % ncols].axis("off")
    for row in range(nrows):
        axes[row][0].set_ylabel(m["ylabel"])

    fig.suptitle(f"{m['title']} vs topology distance, by round configuration")
    fig.tight_layout()
    out = os.path.join(outdir, m["file"] + "_by_config.png")
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def _plot_topo_graph(an: Analysis, outliers, outdir: str, plt) -> str:
    """Node-link diagram: nodes grouped by cell/switch, colored by bandwidth,
    edges = pairings colored by topology distance. Gated by --topo-graph."""
    from matplotlib.lines import Line2D

    topo = an.resolver.topology
    nodes = [ns.node for ns in an.nodes]
    if len(nodes) < 2:
        return ""
    flagged = {f.node for f in outliers.flagged}
    bw = {ns.node: ns.median_bw_gbs for ns in an.nodes}

    # group by (cell, switch) when topology is known, else one group
    groups: dict = {}
    for node in nodes:
        short = _short(node)
        cell = sw = "unknown"
        if topo is not None and short in topo.nodes:
            n = topo.nodes[short]
            cell = n.cell or "unknown"
            sw = n.switches[0] if n.switches else "unknown"
        groups.setdefault((cell, sw), []).append(node)

    gkeys = sorted(groups)
    ncols = int(np.ceil(np.sqrt(len(gkeys))))
    spacing = 3.0
    pos: dict = {}
    anchors: dict = {}
    for idx, gk in enumerate(gkeys):
        gx = (idx % ncols) * spacing
        gy = -(idx // ncols) * spacing
        anchors[gk] = (gx, gy)
        members = groups[gk]
        m = len(members)
        if m == 1:
            pos[members[0]] = (gx, gy)
        else:
            r = 0.85
            for j, node in enumerate(members):
                ang = 2 * np.pi * j / m
                pos[node] = (gx + r * np.cos(ang), gy + r * np.sin(ang))

    fig, ax = plt.subplots(figsize=(10, 8))

    present_loc = set()
    for pr in an.pairings:
        if pr.node_a not in pos or pr.node_b not in pos:
            continue
        x = [pos[pr.node_a][0], pos[pr.node_b][0]]
        y = [pos[pr.node_a][1], pos[pr.node_b][1]]
        ax.plot(x, y, color=_LOC_COLOR.get(pr.label, "#7f7f7f"), lw=1.4,
                alpha=0.55, zorder=1)
        present_loc.add(pr.label)

    xs = [pos[n][0] for n in nodes]
    ys = [pos[n][1] for n in nodes]
    vals = [bw[n] for n in nodes]
    edgecolors = ["#d62728" if n in flagged else "k" for n in nodes]
    lws = [2.5 if n in flagged else 0.8 for n in nodes]
    sc = ax.scatter(xs, ys, c=vals, cmap="viridis", s=520, edgecolors=edgecolors,
                    linewidths=lws, zorder=2)
    fig.colorbar(sc, ax=ax, label="median bandwidth (GB/s, full-duplex)")
    for n in nodes:
        x, y = pos[n]
        ax.annotate(_short(n), (x, y - 0.32), ha="center", va="top", fontsize=7,
                    color="k", zorder=3)

    for (cell, sw), (gx, gy) in anchors.items():
        tag = cell if sw == "unknown" else f"{cell}·{sw[-4:]}"
        ax.annotate(tag, (gx, gy + 1.4), ha="center", fontsize=7, color="#444",
                    style="italic")

    handles = [Line2D([0], [0], color=_LOC_COLOR.get(l, "#7f7f7f"), lw=2, label=l)
               for l in sorted(present_loc)]
    if handles:
        ax.legend(handles=handles, title="edge = pairing distance", fontsize=8,
                  loc="upper left")

    ax.set_title("Topology node-link graph "
                 "(node color = bandwidth, red ring = slow)")
    ax.set_aspect("equal")
    ax.axis("off")
    ax.margins(0.15)
    fig.tight_layout()
    out = os.path.join(outdir, "topo_graph.png")
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


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
    # Use the precomputed per-label buckets so this works for pairwise and
    # collective alike (bandwidth in GB/s, latency in seconds).
    bw = (np.concatenate(list(an.bw_by_label.values()))
          if an.bw_by_label else np.array([]))
    lat = (np.concatenate(list(an.lat_by_label.values()))
           if an.lat_by_label else np.array([]))
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


def plot_congestion(cr, out_path: str) -> str:
    """Baseline-vs-loaded victim bandwidth: grouped per-node bars + overall lines.

    *cr* is a :class:`cinetic.analysis.congestion.CongestionResult`. Self-contained
    matplotlib import so it can be called independently of generate_plots()."""
    import matplotlib
    if matplotlib.get_backend().lower() != "agg":
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    nodes = [d.node for d in cr.per_node]
    if not nodes:
        return ""
    base = np.array([d.base_bw for d in cr.per_node], dtype=float)
    load = np.array([d.loaded_bw for d in cr.per_node], dtype=float)
    x = np.arange(len(nodes))
    w = 0.4

    fig, ax = plt.subplots(figsize=(max(6, len(nodes) * 0.5), 4.8))
    ax.bar(x - w / 2, base, w, label="baseline", color="#1f77b4")
    ax.bar(x + w / 2, load, w, label="loaded (+aggressors)", color="#d62728")
    if np.isfinite(cr.base_overall_bw):
        ax.axhline(cr.base_overall_bw, ls="--", color="#1f77b4", lw=1,
                   label=f"baseline overall {cr.base_overall_bw:.1f}")
    if np.isfinite(cr.loaded_overall_bw):
        ax.axhline(cr.loaded_overall_bw, ls="--", color="#d62728", lw=1,
                   label=f"loaded overall {cr.loaded_overall_bw:.1f}")
    ax.set_xticks(x)
    ax.set_xticklabels(nodes, rotation=90, fontsize=7)
    ax.set_ylabel("bandwidth (GB/s)")
    drop = cr.overall_bw_drop_pct
    drop_s = "n/a" if drop != drop else f"{drop:+.1f}%"
    bench = f" — {cr.victim_benchmark}" if cr.victim_benchmark else ""
    ax.set_title(f"Congestion impact{bench}: victim bandwidth "
                 f"(overall drop {drop_s})")
    ax.legend(fontsize=8)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def plot_fabric(fl, out_path: str, top_n: int = 15) -> str:
    """Top-N congested switches as a horizontal bar chart, colored by role.

    *fl* is a :class:`cinetic.analysis.fabric.FabricLoad`. Self-contained
    matplotlib import so it can be called independently of generate_plots()."""
    import matplotlib
    if matplotlib.get_backend().lower() != "agg":
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    top = fl.switches[:top_n]
    if not top:
        return ""
    labels = [f"{s.ib_name[-8:]} ({s.cell})" for s in top]
    loads = [s.load for s in top]
    role_color = {"leaf": "#2ca02c", "spine": "#1f77b4", "unknown": "#7f7f7f"}
    colors = [role_color.get(s.role, "#7f7f7f") for s in top]

    y = np.arange(len(top))
    fig, ax = plt.subplots(figsize=(8, max(3, len(top) * 0.4)))
    ax.barh(y, loads, color=colors)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()                         # heaviest at top
    ax.set_xlabel("expected load (GB/s, ECMP candidate exposure)")
    ax.set_title(f"Fabric hotspots — top {len(top)} switches by load")
    from matplotlib.patches import Patch
    seen = {s.role for s in top}
    ax.legend(handles=[Patch(color=role_color.get(r, "#7f7f7f"), label=r)
                       for r in sorted(seen)], fontsize=8)
    ax.grid(True, axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def plot_blame(br, out_path: str, top_n: int = 15) -> str:
    """Suspect fabric elements as a horizontal bar chart of slowness (%).

    *br* is a :class:`cinetic.analysis.blame.BlameResult`. Leaf/node suspects
    (high confidence) and spine suspects (low confidence) are colored apart."""
    import matplotlib
    if matplotlib.get_backend().lower() != "agg":
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    items = ([(s, "leaf") for s in br.leaf_suspects[:top_n]]
             + [(s, "node") for s in br.node_suspects[:top_n]]
             + [(s, "spine") for s in br.spine_suspects[:top_n]])
    if not items:
        return ""
    kind_color = {"leaf": "#d62728", "node": "#ff7f0e", "spine": "#9467bd"}
    labels = [f"{s.name[-12:]} [{k}]" for s, k in items]
    vals = [s.median_slowness * 100 for s, k in items]
    colors = [kind_color[k] for s, k in items]

    y = np.arange(len(items))
    fig, ax = plt.subplots(figsize=(8, max(3, len(items) * 0.4)))
    ax.barh(y, vals, color=colors)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel(f"slowness vs ref {br.ref_bw:.1f} GB/s (%)")
    ax.set_title(f"Fabric fault localization — {len(items)} suspect element(s)")
    from matplotlib.patches import Patch
    seen = {k for _, k in items}
    ax.legend(handles=[Patch(color=kind_color[k],
                             label=f"{k} ({'high' if k != 'spine' else 'low'} conf)")
                       for k in ("leaf", "node", "spine") if k in seen], fontsize=8)
    ax.grid(True, axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def plot_comparison(cr, out_path: str) -> str:
    """Cross-experiment comparison: overall bandwidth per series (+ trend line if
    present) and a grouped per-topology-label bar chart.

    *cr* is a :class:`cinetic.analysis.compare.ComparisonResult`."""
    import matplotlib
    if matplotlib.get_backend().lower() != "agg":
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = [s.label for s in cr.series]
    n = len(cr.series)
    unit = "rel" if cr.relative else "GB/s"
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # left: overall bandwidth per series (line if trend/x, else bars)
    xs = [s.x for s in cr.series]
    if cr.trend is not None and all(x is not None for x in xs):
        ax1.plot(xs, cr.overall_bw, "o-", color="#1f77b4", label="overall BW")
        t = cr.trend
        xx = np.array(sorted(t.x), dtype=float)
        ax1.plot(xx, t.intercept + t.slope * (xx - xx.min()), "--", color="k",
                 label=f"trend {t.slope:+.3g}/x (r={t.r:.2f})")
        ax1.set_xlabel("x")
        ax1.legend(fontsize=8)
    else:
        ax1.bar(np.arange(n), cr.overall_bw, color="#1f77b4")
        ax1.set_xticks(np.arange(n))
        ax1.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
    ax1.set_ylabel("overall bandwidth (GB/s)")
    ax1.set_title("Overall bandwidth per series")
    ax1.grid(True, axis="y", alpha=0.3)

    # right: per-topology-label grouped bars across series
    if cr.label_rows:
        labs = [r.key for r in cr.label_rows]
        x = np.arange(len(labs))
        w = 0.8 / max(1, n)
        for i in range(n):
            vals = [r.values[i] for r in cr.label_rows]
            ax2.bar(x + (i - (n - 1) / 2) * w, vals, w, label=labels[i])
        ax2.set_xticks(x)
        ax2.set_xticklabels(labs, fontsize=8)
        ax2.set_ylabel(f"bandwidth ({unit})")
        ax2.set_title("By topology label")
        ax2.legend(fontsize=7)
        ax2.grid(True, axis="y", alpha=0.3)
    else:
        ax2.axis("off")

    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path
