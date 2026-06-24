"""Textual report + machine-readable summary for the tournament analysis."""

from __future__ import annotations

from typing import Optional

from .metrics import Analysis, Stat
from .outliers import OutlierResult


def _short(host: str) -> str:
    return host.split(".")[0]


def _us(x: float) -> str:
    return "n/a" if x != x else f"{x * 1e6:.1f}"      # seconds -> microseconds


def _g(x: float) -> str:
    return "n/a" if x != x else f"{x:.2f}"


def _bw_line(s: Stat) -> str:
    """One line describing a full-duplex bandwidth Stat (also unidirectional)."""
    return (f"median {_g(s.median)} GB/s (uni {_g(s.median / 2)})  "
            f"mean {_g(s.mean)}  min {_g(s.vmin)}  max {_g(s.vmax)}  n={s.n}")


def _lat_line(s: Stat) -> str:
    return (f"median {_us(s.median)} us  mean {_us(s.mean)}  "
            f"p95 {_us(s.p95)}  min {_us(s.vmin)}  max {_us(s.vmax)}")


def format_report(an: Analysis, outliers: OutlierResult,
                  topology_path: Optional[str]) -> str:
    p = an.params
    L = []
    L.append("=" * 78)
    L.append("TOURNAMENT RESULT ANALYSIS")
    L.append("=" * 78)
    L.append(f"exp dir        : {an.dataset.exp_dir}")
    L.append(f"nodes / rounds : {len(an.dataset.nodes)} nodes, "
             f"{an.dataset.n_rounds} rounds, {len(an.pairings)} pairings")
    L.append(f"params         : msg_size={p.msg_size} window={p.window} "
             f"granularity={p.granularity}  [source: {p.source}]")
    L.append(f"bytes/sample   : {p.bytes_per_sample} (full-duplex aggregate)")
    L.append(f"topology       : {topology_path or '(none — locality skipped)'}")
    L.append("")
    L.append("NOTE: bandwidth is full-duplex aggregate, decimal GB/s "
             "(unidirectional = half).")
    lat_note = ("accurate latency only when window==1; here window=%d, so it is an "
                "amortized per-iteration time." % p.window) if p.window != 1 else \
        "window==1: per-iteration latency is a true round-trip time."
    L.append(f"      latency = duration/(window*gran); {lat_note}")

    if an.dataset.wrapped:
        L.append("      WARNING: ring-buffer wrap suspected — early rounds may be "
                 "missing.")
    L.append("")

    L.append("-- OVERALL " + "-" * 67)
    L.append(f"bandwidth : {_bw_line(an.overall_bw)}")
    L.append(f"latency   : {_lat_line(an.overall_lat)}")
    L.append("")

    L.append("-- BANDWIDTH BY TOPOLOGY DISTANCE " + "-" * 44)
    if an.by_locality:
        for label in ("same_switch", "same_cell", "cross_cell", "unknown"):
            if label in an.by_locality:
                L.append(f"  {label:<12}: {_bw_line(an.by_locality[label])}")
    else:
        L.append("  (no pairings)")
    L.append("")

    L.append("-- PER ROUND " + "-" * 65)
    L.append(f"  {'rnd':>3} {'pairs':>5} {'sw':>3} {'cell':>4} {'cross':>5} "
             f"{'unk':>3}  {'med BW':>8}  {'med lat(us)':>11}")
    for r in an.rounds:
        m = r.mix
        L.append(f"  {r.round_index:>3} {r.n_pairings:>5} "
                 f"{m.get('same_switch', 0):>3} {m.get('same_cell', 0):>4} "
                 f"{m.get('cross_cell', 0):>5} {m.get('unknown', 0):>3}  "
                 f"{_g(r.bw.median):>8}  {_us(r.lat.median):>11}")
    L.append("")

    L.append("-- PER NODE (sorted by bandwidth) " + "-" * 44)
    L.append(f"  {'node':<28} {'med BW':>8} {'uni':>7} {'med lat(us)':>11} "
             f"{'n':>5}")
    flagged_nodes = {f.node for f in outliers.flagged}
    for ns in sorted(an.nodes, key=lambda x: x.median_bw_gbs):
        mark = " *SLOW*" if ns.node in flagged_nodes else ""
        L.append(f"  {ns.node:<28} {_g(ns.median_bw_gbs):>8} "
                 f"{_g(ns.median_bw_gbs / 2):>7} {_us(ns.median_lat_s):>11} "
                 f"{ns.bw.n:>5}{mark}")
    L.append("")

    L.append("-- PER-NODE PEER PROFILE (summary) " + "-" * 43)
    L.append("  how each node's bandwidth splits across its peers:")
    for ns in sorted(an.nodes, key=lambda x: x.median_bw_gbs):
        if ns.profile is None:
            continue
        flag = "" if ns.profile.classification in ("uniform",) else "  <--"
        L.append(f"  {_short(ns.node):<12} {ns.profile.classification:<12} "
                 f"{ns.profile.note}{flag}")
    L.append("  (full per-peer and per-round tables: see the analysis dir / "
             "--detail)")
    L.append("")

    L.append("-- UNDER-PERFORMING NODES " + "-" * 52)
    L.append(f"  method: {outliers.method}")
    if outliers.low_confidence:
        L.append("  (LOW CONFIDENCE)")
    L.append(f"  global median {_g(outliers.median)} GB/s, MAD {_g(outliers.mad)}")
    if outliers.flagged:
        L.append(f"  flagged {len(outliers.flagged)} node(s):")
        for f in outliers.flagged:
            L.append(f"    {f.node:<28} {_g(f.value):>8} GB/s  "
                     f"dev {f.deviation_pct:+.1f}%  ({f.reason})")
    else:
        L.append("  none flagged.")
    L.append("")

    if an.warnings:
        L.append("-- WARNINGS " + "-" * 66)
        for w in an.warnings:
            L.append(f"  ! {w}")
        L.append("")

    L.append("=" * 78)
    return "\n".join(L)


def format_peer_profiles(an: Analysis) -> str:
    """Full per-node peer profile: every peer sorted by bandwidth, with locality."""
    L = ["=" * 78, "PER-NODE PEER PROFILE (full)", "=" * 78,
         "For each node, its bandwidth to each peer (sorted slow->fast).", ""]
    for ns in sorted(an.nodes, key=lambda x: x.median_bw_gbs):
        L.append(f"-- {_short(ns.node)}  (median {_g(ns.median_bw_gbs)} GB/s) " +
                 "-" * 30)
        if ns.profile is not None:
            L.append(f"   profile: {ns.profile.classification} — {ns.profile.note}")
        L.append(f"   {'peer':<12} {'distance':<12} {'med BW':>8} {'uni':>7} "
                 f"{'med lat(us)':>11} {'n':>5}")
        for m in sorted(ns.matches, key=lambda x: x.median_bw_gbs):
            L.append(f"   {_short(m.peer_node):<12} {m.locality:<12} "
                     f"{_g(m.median_bw_gbs):>8} {_g(m.median_bw_gbs / 2):>7} "
                     f"{_us(m.median_lat_s):>11} {m.n:>5}")
        L.append("")
    return "\n".join(L)


def format_per_round_per_node(an: Analysis) -> str:
    """Per node, how it performed each round and with whom (+ topology distance)."""
    L = ["=" * 78, "PER-ROUND PER-NODE", "=" * 78,
         "For each node, its peer and bandwidth/latency in each round.", ""]
    for ns in sorted(an.nodes, key=lambda x: _short(x.node)):
        L.append(f"-- {_short(ns.node)} " + "-" * 60)
        L.append(f"   {'round':>5} {'peer':<12} {'distance':<12} {'med BW':>8} "
                 f"{'med lat(us)':>11} {'n':>5}")
        for m in sorted(ns.matches, key=lambda x: x.round_index):
            L.append(f"   {m.round_index:>5} {_short(m.peer_node):<12} "
                     f"{m.locality:<12} {_g(m.median_bw_gbs):>8} "
                     f"{_us(m.median_lat_s):>11} {m.n:>5}")
        L.append("")
    return "\n".join(L)


def _stat_dict(s: Stat) -> dict:
    return {"n": s.n, "median": s.median, "mean": s.mean, "std": s.std,
            "min": s.vmin, "max": s.vmax, "p95": s.p95}


def build_summary(an: Analysis, outliers: OutlierResult) -> dict:
    p = an.params
    return {
        "exp_dir": an.dataset.exp_dir,
        "n_nodes": len(an.dataset.nodes),
        "n_rounds": an.dataset.n_rounds,
        "n_pairings": len(an.pairings),
        "wrapped": an.dataset.wrapped,
        "params": {"msg_size": p.msg_size, "window": p.window,
                   "granularity": p.granularity, "source": p.source,
                   "bytes_per_sample": p.bytes_per_sample},
        "bandwidth_gbs_fullduplex": {
            "overall": _stat_dict(an.overall_bw),
            "by_locality": {k: _stat_dict(v) for k, v in an.by_locality.items()},
        },
        "latency_s_per_iter": {"overall": _stat_dict(an.overall_lat)},
        "rounds": [{"round": r.round_index, "n_pairings": r.n_pairings,
                    "mix": r.mix, "bw": _stat_dict(r.bw),
                    "lat": _stat_dict(r.lat)} for r in an.rounds],
        "nodes": [{"node": ns.node, "median_bw_gbs": ns.median_bw_gbs,
                   "median_lat_s": ns.median_lat_s,
                   "bw": _stat_dict(ns.bw),
                   "profile": (None if ns.profile is None else {
                       "classification": ns.profile.classification,
                       "note": ns.profile.note,
                       "fast_median": ns.profile.fast_median,
                       "slow_median": ns.profile.slow_median,
                       "ratio": ns.profile.ratio,
                       "n_fast": ns.profile.n_fast, "n_slow": ns.profile.n_slow,
                       "slow_peers": ns.profile.slow_peers}),
                   "matches": [{"round": m.round_index, "peer": m.peer_node,
                                "peer_rank": m.peer_rank, "locality": m.locality,
                                "median_bw_gbs": m.median_bw_gbs,
                                "median_lat_s": m.median_lat_s, "n": m.n}
                               for m in ns.matches]} for ns in an.nodes],
        "outliers": {"method": outliers.method,
                     "low_confidence": outliers.low_confidence,
                     "median": outliers.median, "mad": outliers.mad,
                     "flagged": [{"node": f.node, "value": f.value,
                                  "zscore": f.zscore,
                                  "deviation_pct": f.deviation_pct,
                                  "reason": f.reason} for f in outliers.flagged]},
        "warnings": an.warnings,
    }
