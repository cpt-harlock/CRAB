#!/bin/bash
# Tournament bandwidth saturation sweep — 2D: node count x message size
# (Leonardo DCGP). One Slurm job per (nodes, msgsize) cell, submitted via the
# cinetic CLI; configs are generated on the fly into generated/ (gitignored).
#
# Axes (edit to run a subset):
#   NODE_COUNTS : powers of two, tournament needs an even rank count.
#   MSG_SIZES   : 8 B .. 16 MB, x8 each step.
set -euo pipefail

NODE_COUNTS="${NODE_COUNTS:-2 4 8 16 32 64 128 256 512 1024}"
MSG_SIZES="${MSG_SIZES:-8 64 512 4096 32768 262144 2097152 16777216}"
PRESET="leonardo"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"
HERE="experiment/saturation_sweep"
GEN="$HERE/generated"
mkdir -p "$GEN"

n=0
for N in $NODE_COUNTS; do
  for M in $MSG_SIZES; do
    cfg="$GEN/tournament_n${N}_m${M}.json"
    python "$HERE/gen_config.py" --nodes "$N" --msgsize "$M" -o "$cfg" >/dev/null
    echo "=== submitting saturation: ${N} nodes, msg ${M} B ==="
    cinetic run -p "$PRESET" -c "$cfg"
    n=$((n + 1))
  done
done

echo
echo "Submitted $n job(s) over nodes={$NODE_COUNTS} x msg={$MSG_SIZES}."
echo "Results: data/leonardo/tournament_sat_n<N>_m<M>_<timestamp>/"
echo "Analyze with: $HERE/analyze_sweep.sh"
echo
echo "NB: the full grid is large and the big cells (>=512 nodes, >=2 MB) are heavy"
echo "    — submit a subset first via e.g.  NODE_COUNTS='2 4 8' MSG_SIZES='4096' $0"
