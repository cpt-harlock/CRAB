"""Parse tournament per-node CSV dumps into an in-memory model.

Input files (one per rank) look like::

    node,rank,peer_node,peer_rank,sample,duration_s
    lrdn0271.leonardo.local,0,lrdn0843.leonardo.local,3,0,0.010931789
    ...
    ========================================        <- optional fence
    lrdn0271.leonardo.local,0,lrdn0451.leonardo.local,2,20,0.0109...

The parser is deliberately tolerant (older runs use a different column order
and have no fences):

* columns are resolved **by header name**, not position;
* lines made only of ``=`` are skipped (fences are optional);
* a **block** (one match against one peer) is delimited canonically by a
  **peer change**, so it works with or without fences.

Only the *last* engine run survives in these files (``write_node_results`` opens
with mode ``"w"``), so a parsed :class:`Dataset` describes the final run.
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Match:
    """One node's view of one *block* of samples — a contiguous run with the same
    (op, comm, peer, phase). For a pairwise benchmark a block is one node's
    directed view of one pairing in one round; for a collective it is the whole
    set of samples of that op on that communicator (no single peer)."""

    node: str               # FQDN exactly as written in the file
    rank: int
    peer_node: str          # "" for a collective block
    peer_rank: int          # -1 for a collective block
    round_index: int        # phase if present, else 0-based block order
    durations: List[float] = field(default_factory=list)
    first_sample: int = 0   # sample_idx of the block's first row (wrap probe)
    op: str = "pairwise_fd"           # operation tag (legacy default)
    comm: int = 0                     # communicator id (links to the manifest)
    bytes_per_sample: float = float("nan")   # bandwidth basis (NaN if absent)
    ops_per_sample: float = float("nan")     # latency basis (NaN if absent)

    @property
    def is_collective(self) -> bool:
        return self.peer_rank < 0


@dataclass
class Dataset:
    """Everything parsed from one experiment directory (the final run)."""

    exp_dir: str
    matches: List[Match] = field(default_factory=list)
    nodes: List[str] = field(default_factory=list)        # sorted unique FQDNs
    rank_to_node: Dict[int, str] = field(default_factory=dict)
    n_rounds: int = 0
    wrapped: bool = False
    warnings: List[str] = field(default_factory=list)
    # comm id -> ordered member node list (from comm_manifest.csv; {} if absent)
    comms: Dict[int, List[str]] = field(default_factory=dict)

    def matches_by_node(self) -> Dict[str, List[Match]]:
        out: Dict[str, List[Match]] = {}
        for m in self.matches:
            out.setdefault(m.node, []).append(m)
        return out

    @property
    def is_collective(self) -> bool:
        """A dataset is collective when its samples have no single peer."""
        return bool(self.matches) and all(m.is_collective for m in self.matches)


# ---------------------------------------------------------------------------

def _is_fence(line: str) -> bool:
    s = line.strip()
    return len(s) > 0 and set(s) == {"="}


def _to_int(s: str, default: int) -> int:
    s = s.strip()
    try:
        return int(s)
    except ValueError:
        return default


def _to_float(s: str, default: float) -> float:
    s = s.strip()
    try:
        return float(s)
    except ValueError:
        return default


def parse_node_file(path: str) -> List[Match]:
    """Parse one ``node_<host>_rank<r>.csv`` into ordered :class:`Match` blocks.

    Handles both the legacy tournament header and the standardized superset
    (``op,comm,phase,bytes,ops`` added). The required columns are
    ``node,rank,peer_node,peer_rank,sample,duration_s``; the rest are optional.
    A new block starts whenever (op, comm, peer_rank, phase) changes, so pairwise
    rounds split per peer/round and a collective yields one block per op/comm.
    """
    with open(path) as fh:
        lines = fh.read().splitlines()
    if not lines:
        return []

    header = [c.strip() for c in lines[0].split(",")]
    try:
        col = {name: header.index(name) for name in
               ("node", "rank", "peer_node", "peer_rank", "sample", "duration_s")}
    except ValueError as exc:
        raise ValueError(f"{path}: unexpected header {header!r}") from exc
    # optional standardized columns
    opt = {name: header.index(name) for name in
           ("op", "comm", "phase", "bytes", "ops") if name in header}

    matches: List[Match] = []
    cur: Optional[Match] = None
    prev_key: Optional[tuple] = None
    block_order = 0

    def get(parts, name, default=""):
        i = opt.get(name)
        return parts[i] if i is not None and i < len(parts) else default

    for raw in lines[1:]:
        if not raw.strip() or _is_fence(raw):
            continue
        parts = raw.split(",")
        node = parts[col["node"]].strip()
        rank = int(parts[col["rank"]])
        peer_node = parts[col["peer_node"]].strip()
        peer_rank = int(parts[col["peer_rank"]])
        sample_idx = int(parts[col["sample"]])
        duration = float(parts[col["duration_s"]])
        op = get(parts, "op", "pairwise_fd").strip() or "pairwise_fd"
        comm = _to_int(get(parts, "comm", "0"), 0)
        phase = _to_int(get(parts, "phase", "-1"), -1)
        bps = _to_float(get(parts, "bytes", ""), float("nan"))
        ops = _to_float(get(parts, "ops", ""), float("nan"))

        key = (op, comm, peer_rank, phase)
        if cur is None or key != prev_key:
            # round index: prefer the explicit phase, else block order
            round_index = phase if phase >= 0 else block_order
            cur = Match(node=node, rank=rank, peer_node=peer_node,
                        peer_rank=peer_rank, round_index=round_index,
                        first_sample=sample_idx, op=op, comm=comm,
                        bytes_per_sample=bps, ops_per_sample=ops)
            matches.append(cur)
            block_order += 1
            prev_key = key
        cur.durations.append(duration)

    return matches


def parse_manifest(exp_dir: str) -> Dict[int, List[str]]:
    """Read ``comm_manifest.csv`` (comm,rank,node) -> {comm_id: [node, ...]} in
    rank order. Returns {} if absent."""
    path = os.path.join(exp_dir, "comm_manifest.csv")
    if not os.path.isfile(path):
        return {}
    by_comm: Dict[int, Dict[int, str]] = {}
    with open(path) as fh:
        lines = fh.read().splitlines()
    if not lines:
        return {}
    header = [c.strip() for c in lines[0].split(",")]
    try:
        ci, ri, ni = header.index("comm"), header.index("rank"), header.index("node")
    except ValueError:
        return {}
    for raw in lines[1:]:
        if not raw.strip():
            continue
        parts = raw.split(",")
        if max(ci, ri, ni) >= len(parts):
            continue
        c = _to_int(parts[ci], -1)
        r = _to_int(parts[ri], -1)
        n = parts[ni].strip()
        if c < 0 or r < 0 or not n:
            continue
        by_comm.setdefault(c, {})[r] = n
    return {c: [members[r] for r in sorted(members)]
            for c, members in by_comm.items()}


def parse_exp_dir(exp_dir: str) -> Dataset:
    """Parse every ``node_*.csv`` in *exp_dir* into a :class:`Dataset`."""
    files = sorted(glob.glob(os.path.join(exp_dir, "node_*.csv")))
    ds = Dataset(exp_dir=exp_dir)
    if not files:
        ds.warnings.append(f"no node_*.csv files found in {exp_dir}")
        return ds

    block_counts = []
    for path in files:
        file_matches = parse_node_file(path)
        ds.matches.extend(file_matches)
        block_counts.append(len(file_matches))
        for m in file_matches:
            ds.rank_to_node.setdefault(m.rank, m.node)
            # a non-zero first sample means the ring buffer evicted early rounds
            if m.round_index == 0 and m.first_sample != 0:
                ds.wrapped = True

    ds.nodes = sorted({m.node for m in ds.matches})
    ds.n_rounds = max(block_counts) if block_counts else 0
    ds.comms = parse_manifest(exp_dir)

    # Block-count disagreement is a generic wrap/truncation signal for any
    # per-node format with >1 block per file (i.e. not collectives).
    if not ds.is_collective and len(set(block_counts)) > 1:
        ds.warnings.append(
            f"node files disagree on block count {sorted(set(block_counts))}; "
            "ring-buffer wrap or a truncated run is likely")
        ds.wrapped = True

    # The "rounds == ranks-1" expectation is specific to the all-pairs tournament
    # (op=pairwise_fd); it doesn't hold for collectives or directed patterns
    # (a ring has one block per node), so only apply it there.
    if {m.op for m in ds.matches} == {"pairwise_fd"}:
        n_ranks = len(ds.rank_to_node)
        if n_ranks and ds.n_rounds and ds.n_rounds < n_ranks - 1:
            ds.warnings.append(
                f"observed {ds.n_rounds} rounds but {n_ranks} ranks imply "
                f"{n_ranks - 1}; early rounds were likely evicted (wrap)")
            ds.wrapped = True

    return ds
