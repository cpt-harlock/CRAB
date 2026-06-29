#!/bin/bash
# Congestion sweep — 2D: node count x aggressor message size (Leonardo DCGP).
# victim = tournament_nb (fixed saturating size); aggressor = a2a_nb -endl at the
# swept message size. One Slurm job per cell (baseline + loaded in each), configs
# generated on the fly into generated/ (gitignored).
#
# Axes (edit to run a subset):
#   NODE_COUNTS : powers of two >= 4 (split 50:50 -> N/2 must be an even rank
#                 count for the tournament victim).
#   MSG_SIZES   : aggressor message size, 8 B .. 16 MB, x8 each step.
#   VICTIM      : tournament (default) | allgather
#   AGGRESSOR   : alltoall   (default) | incast   (all -> one receiver)
set -euo pipefail

NODE_COUNTS="${NODE_COUNTS:-4 8 16 32 64 128 256 512 1024}"
MSG_SIZES="${MSG_SIZES:-8 64 512 4096 32768 262144 2097152 16777216}"
VICTIM="${VICTIM:-tournament}"
AGGRESSOR="${AGGRESSOR:-alltoall}"
PRESET="leonardo"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"
HERE="experiment/congestion"
GEN="$HERE/generated"
mkdir -p "$GEN"

n=0
for N in $NODE_COUNTS; do
  for M in $MSG_SIZES; do
    cfg="$GEN/congestion_${VICTIM}_${AGGRESSOR}_n${N}_m${M}.json"
    python "$HERE/gen_config.py" --nodes "$N" --aggr-msgsize "$M" \
      --victim "$VICTIM" --aggressor "$AGGRESSOR" -o "$cfg" >/dev/null
    echo "=== submitting congestion ($VICTIM vs $AGGRESSOR): ${N} nodes, aggr msg ${M} B ==="
    cinetic run -p "$PRESET" -c "$cfg"
    n=$((n + 1))
  done
done

echo
echo "Submitted $n job(s): $VICTIM vs $AGGRESSOR over nodes={$NODE_COUNTS} x aggr-msg={$MSG_SIZES}."
echo "Results: data/leonardo/congestion_a2a_n<N>_m<M>_<timestamp>/  (baseline/+loaded/)"
echo "Analyze with: $HERE/analyze_sweep.sh"
echo
echo "NB: small node counts (<32) sit on a single non-blocking leaf -> ~0% drop"
echo "    (negative control); spine congestion needs the larger cells."
