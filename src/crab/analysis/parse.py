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
    """One node's *directed* view of one pairing in one tournament round."""

    node: str               # FQDN exactly as written in the file
    rank: int
    peer_node: str
    peer_rank: int
    round_index: int        # 0-based block order within this node's file
    durations: List[float] = field(default_factory=list)
    first_sample: int = 0   # sample_idx of the block's first row (wrap probe)


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

    def matches_by_node(self) -> Dict[str, List[Match]]:
        out: Dict[str, List[Match]] = {}
        for m in self.matches:
            out.setdefault(m.node, []).append(m)
        return out


# ---------------------------------------------------------------------------

def _is_fence(line: str) -> bool:
    s = line.strip()
    return len(s) > 0 and set(s) == {"="}


def parse_node_file(path: str) -> List[Match]:
    """Parse one ``node_<host>_rank<r>.csv`` into ordered :class:`Match` blocks."""
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

    matches: List[Match] = []
    cur: Optional[Match] = None
    prev_peer_rank: Optional[int] = None
    round_index = 0

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

        if cur is None or peer_rank != prev_peer_rank:
            cur = Match(node=node, rank=rank, peer_node=peer_node,
                        peer_rank=peer_rank, round_index=round_index,
                        first_sample=sample_idx)
            matches.append(cur)
            round_index += 1
            prev_peer_rank = peer_rank
        cur.durations.append(duration)

    return matches


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

    if len(set(block_counts)) > 1:
        ds.warnings.append(
            f"node files disagree on round count {sorted(set(block_counts))}; "
            "ring-buffer wrap or a truncated run is likely")
        ds.wrapped = True

    n_ranks = len(ds.rank_to_node)
    if n_ranks and ds.n_rounds and ds.n_rounds < n_ranks - 1:
        ds.warnings.append(
            f"observed {ds.n_rounds} rounds but {n_ranks} ranks imply "
            f"{n_ranks - 1}; early rounds were likely evicted (wrap)")
        ds.wrapped = True

    return ds
