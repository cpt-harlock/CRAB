"""Bandwidth / latency math and robust statistics.

Bandwidth is reported as **full-duplex aggregate** decimal GB/s (both directions
summed, ``/1e9``); the unidirectional figure is half of that. Latency is the
**per-iteration** time ``duration_s / (window * granularity)`` — an amortized,
pipelined figure that is only a true latency when ``window == 1`` (see
``PLAN_RESULT_ANALYZER.md`` §1.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from .params import Params
from .parse import Dataset, Match
from .topo import TopoResolver, locality_label


@dataclass
class Stat:
    n: int = 0
    median: float = float("nan")
    mean: float = float("nan")
    std: float = float("nan")
    vmin: float = float("nan")
    vmax: float = float("nan")
    p95: float = float("nan")


def summarize(values) -> Stat:
    a = np.asarray(values, dtype=float)
    a = a[np.isfinite(a)]
    if a.size == 0:
        return Stat()
    return Stat(n=int(a.size), median=float(np.median(a)), mean=float(np.mean(a)),
                std=float(np.std(a)), vmin=float(np.min(a)), vmax=float(np.max(a)),
                p95=float(np.percentile(a, 95)))


def _finite_pos(x) -> bool:
    return x is not None and x == x and x > 0   # guards None and NaN (x==x is False for NaN)


def bandwidth_gbs(durations, params: Params, bytes_per_sample=None) -> np.ndarray:
    """Bandwidth in decimal GB/s, elementwise. Uses the per-sample byte basis
    when given (the standardized ``bytes`` column), else the params-derived
    full-duplex aggregate (legacy tournament files)."""
    d = np.asarray(durations, dtype=float)
    bps = bytes_per_sample if _finite_pos(bytes_per_sample) else params.bytes_per_sample
    with np.errstate(divide="ignore", invalid="ignore"):
        return bps / d / 1e9


def latency_s(durations, params: Params, ops_per_sample=None) -> np.ndarray:
    """Per-iteration latency in seconds, elementwise. Uses the per-sample op
    basis when given (the standardized ``ops`` column), else
    ``window*granularity`` (legacy tournament files)."""
    d = np.asarray(durations, dtype=float)
    ops = ops_per_sample if _finite_pos(ops_per_sample) else (params.window * params.granularity)
    return d / ops


def match_bw(m, params: Params) -> np.ndarray:
    """Bandwidth series for one Match, using its embedded byte basis if present."""
    return bandwidth_gbs(m.durations, params, getattr(m, "bytes_per_sample", None))


def match_lat(m, params: Params) -> np.ndarray:
    """Latency series for one Match, using its embedded op basis if present."""
    return latency_s(m.durations, params, getattr(m, "ops_per_sample", None))


# ---------------------------------------------------------------------------

@dataclass
class Pairing:
    round_index: int
    node_a: str
    node_b: str
    rank_a: int
    rank_b: int
    durations: np.ndarray            # merged (mean of both endpoints) per sample
    skew: float = 0.0                # mean |A-B| duration, a sync diagnostic
    locality: Optional[object] = None
    label: str = "unknown"
    bytes_per_sample: float = float("nan")   # bandwidth basis (from the match)
    ops_per_sample: float = float("nan")     # latency basis (from the match)


@dataclass
class MatchStat:
    """One node's performance in one round against one peer (directed)."""

    round_index: int
    peer_node: str
    peer_rank: int
    locality: str                    # same_switch / same_cell / cross_cell / unknown
    n: int
    median_bw_gbs: float
    median_lat_s: float
    std_bw_gbs: float = float("nan")
    std_lat_s: float = float("nan")


@dataclass
class PeerProfile:
    """Characterizes how a node's bandwidth is distributed across its peers."""

    classification: str              # uniform / bimodal / broadly_slow / mixed
    note: str                        # human-readable one-liner
    fast_median: float               # GB/s of the fast cluster
    slow_median: float               # GB/s of the slow cluster (nan if none)
    ratio: float                     # slow_median / fast_median (nan if none)
    n_fast: int
    n_slow: int
    slow_peers: List[str] = field(default_factory=list)


@dataclass
class NodeStats:
    node: str
    bw: Stat
    lat: Stat
    median_bw_gbs: float
    median_lat_s: float
    by_locality: Dict[str, Stat] = field(default_factory=dict)
    matches: List[MatchStat] = field(default_factory=list)   # per-round, per-peer
    profile: Optional[PeerProfile] = None


@dataclass
class RoundStats:
    round_index: int
    n_pairings: int
    mix: Dict[str, int]              # label -> count
    bw: Stat
    lat: Stat


@dataclass
class Analysis:
    dataset: Dataset
    params: Params
    resolver: TopoResolver
    pairings: List[Pairing]
    nodes: List[NodeStats]
    rounds: List[RoundStats]
    overall_bw: Stat
    overall_lat: Stat
    by_locality: Dict[str, Stat]
    node_bw_median: Dict[str, float]
    warnings: List[str] = field(default_factory=list)
    # "pairwise" or "collective" — drives which views apply
    kind: str = "pairwise"
    # bandwidth/latency samples bucketed by locality (pairwise) or comm-span
    # (collective) label; the unit feeding the "by locality/span" views
    bw_by_label: Dict[str, np.ndarray] = field(default_factory=dict)
    lat_by_label: Dict[str, np.ndarray] = field(default_factory=dict)
    # comm id -> span label (collective only)
    comm_span: Dict[int, str] = field(default_factory=dict)


def build_pairings(ds: Dataset, params: Params,
                   resolver: TopoResolver) -> tuple[List[Pairing], List[str]]:
    """Merge each pair of directed Matches into one undirected Pairing."""
    by_key: Dict[tuple, Match] = {(m.round_index, m.rank): m for m in ds.matches}
    warnings: List[str] = []
    pairings: List[Pairing] = []
    seen: set = set()

    for m in ds.matches:
        if m.rank == m.peer_rank:                 # self-pairing (odd world)
            continue
        a, b = sorted((m.rank, m.peer_rank))
        key = (m.round_index, a, b)
        if key in seen:
            continue
        seen.add(key)

        partner = by_key.get((m.round_index, m.peer_rank))
        if partner is None or partner.peer_rank != m.rank:
            warnings.append(
                f"round {m.round_index}: no consistent partner for "
                f"{m.node}<->{m.peer_node}; using one-sided durations")
            da = np.asarray(m.durations, dtype=float)
            merged, skew = da, 0.0
            na, nb = (m.node, m.peer_node)
        else:
            da = np.asarray(m.durations, dtype=float)
            db = np.asarray(partner.durations, dtype=float)
            k = min(da.size, db.size)
            if da.size != db.size:
                warnings.append(
                    f"round {m.round_index}: {m.node}/{m.peer_node} sample count "
                    f"mismatch ({da.size} vs {db.size}); truncating to {k}")
            da, db = da[:k], db[:k]
            merged = (da + db) / 2.0
            skew = float(np.mean(np.abs(da - db))) if k else 0.0
            na = m.node if m.rank == a else partner.node
            nb = partner.node if m.rank == a else m.node

        loc = resolver.locality(na, nb)
        pairings.append(Pairing(round_index=m.round_index, node_a=na, node_b=nb,
                                rank_a=a, rank_b=b, durations=merged, skew=skew,
                                locality=loc, label=locality_label(loc),
                                bytes_per_sample=m.bytes_per_sample,
                                ops_per_sample=m.ops_per_sample))
    return pairings, warnings


def _classify_peer_profile(match_stats: List["MatchStat"],
                           slow_ratio: float = 0.75) -> Optional[PeerProfile]:
    """Detect whether a node's per-peer bandwidth is uniform or splits into a
    fast/slow cluster — the latter is the signature of a degraded rail/NIC that
    only some destinations route over (e.g. single-rail ~half bandwidth)."""
    vals = np.array([m.median_bw_gbs for m in match_stats], dtype=float)
    peers = [m.peer_node for m in match_stats]
    vals = vals[np.isfinite(vals)]
    if vals.size < 3:
        return None

    fast_ref = float(np.median(vals[vals >= np.median(vals)]))  # upper-half median
    slow_mask = vals < slow_ratio * fast_ref
    n_slow = int(slow_mask.sum())
    n_fast = int(vals.size - n_slow)
    fast_med = float(np.median(vals[~slow_mask])) if n_fast else float("nan")
    slow_med = float(np.median(vals[slow_mask])) if n_slow else float("nan")
    ratio = (slow_med / fast_med) if (n_slow and fast_med) else float("nan")
    slow_peers = [p for p, s in zip(peers, slow_mask) if s]

    if n_slow == 0:
        cls, note = "uniform", f"uniform across {n_fast} peers (~{fast_med:.1f} GB/s)"
    elif n_fast == 0:
        cls = "broadly_slow"
        note = f"broadly slow across all {n_slow} peers (~{slow_med:.1f} GB/s)"
    elif n_fast >= 2 and n_slow >= 2:
        cls = "bimodal"
        note = (f"bimodal: {n_fast} peers ~{fast_med:.1f} GB/s, {n_slow} peers "
                f"~{slow_med:.1f} GB/s ({ratio:.2f}x) — possible single-rail/NIC")
    else:
        cls = "mixed"
        note = (f"{n_slow} slow peer(s) ~{slow_med:.1f} vs {n_fast} ~{fast_med:.1f} "
                f"GB/s")
    return PeerProfile(classification=cls, note=note, fast_median=fast_med,
                       slow_median=slow_med, ratio=ratio, n_fast=n_fast,
                       n_slow=n_slow, slow_peers=slow_peers)


def _node_stats(node: str, matches: List[Match], params: Params,
                label_fn) -> NodeStats:
    """Per-node bandwidth/latency. ``label_fn(match)`` gives the locality (pairwise)
    or comm-span (collective) label. Bandwidth/latency use each match's embedded
    byte/op basis (falling back to params for legacy files)."""
    bw_all: List[np.ndarray] = []
    lat_all: List[np.ndarray] = []
    by_loc: Dict[str, List[float]] = {}
    match_stats: List[MatchStat] = []
    for m in matches:
        label = label_fn(m)
        mbw = match_bw(m, params)
        mlat = match_lat(m, params)
        bw_all.append(mbw)
        lat_all.append(mlat)
        by_loc.setdefault(label, []).extend(mbw.tolist())
        match_stats.append(MatchStat(
            round_index=m.round_index, peer_node=m.peer_node,
            peer_rank=m.peer_rank, locality=label, n=len(m.durations),
            median_bw_gbs=float(np.median(mbw)) if mbw.size else float("nan"),
            median_lat_s=float(np.median(mlat)) if mlat.size else float("nan"),
            std_bw_gbs=float(np.std(mbw)) if mbw.size else float("nan"),
            std_lat_s=float(np.std(mlat)) if mlat.size else float("nan")))
    bw = summarize(np.concatenate(bw_all) if bw_all else np.array([]))
    lat = summarize(np.concatenate(lat_all) if lat_all else np.array([]))
    by_locality = {k: summarize(v) for k, v in by_loc.items()}
    match_stats.sort(key=lambda s: s.round_index)

    return NodeStats(node=node, bw=bw, lat=lat,
                     median_bw_gbs=bw.median, median_lat_s=lat.median,
                     by_locality=by_locality, matches=match_stats,
                     profile=_classify_peer_profile(match_stats))


def analyze(ds: Dataset, params: Params, resolver: TopoResolver) -> Analysis:
    resolver.check_coverage(ds.nodes)
    collective = ds.is_collective

    # Per-sample label: pairwise -> locality of (node, peer); collective -> the
    # communicator's span class (from the manifest). Computed once per comm.
    span = {cid: resolver.comm_span(members) for cid, members in ds.comms.items()}

    def label_fn(m: Match) -> str:
        if m.is_collective:
            return span.get(m.comm, "unknown")
        return locality_label(resolver.locality(m.node, m.peer_node))

    # per node (directed matches / per-node collective samples)
    nodes = [_node_stats(node, ms, params, label_fn)
             for node, ms in sorted(ds.matches_by_node().items())]
    node_bw_median = {ns.node: ns.median_bw_gbs for ns in nodes}

    pairings: List[Pairing] = []
    rounds: List[RoundStats] = []
    pair_warn: List[str] = []
    bw_by_label: Dict[str, list] = {}
    lat_by_label: Dict[str, list] = {}

    if collective:
        # No pairs: each node's per-sample bandwidth/latency, bucketed by the
        # communicator's span. (One value per node-sample; no merge/double-count
        # question since there are no peer pairs.)
        for m in ds.matches:
            lab = label_fn(m)
            bw_by_label.setdefault(lab, []).extend(match_bw(m, params).tolist())
            lat_by_label.setdefault(lab, []).extend(match_lat(m, params).tolist())
    else:
        pairings, pair_warn = build_pairings(ds, params, resolver)
        # per round (one value per pairing-sample)
        for r in sorted({p.round_index for p in pairings}):
            ps = [p for p in pairings if p.round_index == r]
            mix: Dict[str, int] = {}
            for p in ps:
                mix[p.label] = mix.get(p.label, 0) + 1
            bw = np.concatenate([bandwidth_gbs(p.durations, params,
                                               p.bytes_per_sample) for p in ps]) \
                if ps else np.array([])
            lat = np.concatenate([latency_s(p.durations, params,
                                            p.ops_per_sample) for p in ps]) \
                if ps else np.array([])
            rounds.append(RoundStats(round_index=r, n_pairings=len(ps), mix=mix,
                                      bw=summarize(bw), lat=summarize(lat)))
        # by-locality over pairings (one merged value per pair-sample)
        for p in pairings:
            bw_by_label.setdefault(p.label, []).extend(
                bandwidth_gbs(p.durations, params, p.bytes_per_sample).tolist())
            lat_by_label.setdefault(p.label, []).extend(
                latency_s(p.durations, params, p.ops_per_sample).tolist())

    bw_by_label = {k: np.asarray(v, dtype=float) for k, v in bw_by_label.items()}
    lat_by_label = {k: np.asarray(v, dtype=float) for k, v in lat_by_label.items()}
    all_bw = (np.concatenate(list(bw_by_label.values()))
              if bw_by_label else np.array([]))
    all_lat = (np.concatenate(list(lat_by_label.values()))
               if lat_by_label else np.array([]))
    overall_bw = summarize(all_bw)
    overall_lat = summarize(all_lat)
    by_locality = {k: summarize(v) for k, v in bw_by_label.items()}

    warnings = list(ds.warnings) + list(resolver.warnings) + pair_warn
    return Analysis(dataset=ds, params=params, resolver=resolver, pairings=pairings,
                    nodes=nodes, rounds=rounds, overall_bw=overall_bw,
                    overall_lat=overall_lat, by_locality=by_locality,
                    node_bw_median=node_bw_median, warnings=warnings,
                    kind="collective" if collective else "pairwise",
                    bw_by_label=bw_by_label, lat_by_label=lat_by_label,
                    comm_span=span)
