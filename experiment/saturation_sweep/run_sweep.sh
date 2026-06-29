#!/bin/bash
# Tournament bandwidth saturation sweep over node counts (Leonardo DCGP).
#
# A node-count sweep cannot share one Slurm allocation (every experiment in a
# job receives the full allocation), so this submits ONE job per node count via
# the cinetic CLI — it is just a loop around `cinetic run`, nothing custom.
#
# Run from anywhere; it cd's to the repo root so cinetic resolves presets/paths.
set -euo pipefail

# even node counts only (tournament needs an even rank count with ppn=1)
NODE_COUNTS="2 4 8 16 32 64"
PRESET="leonardo"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"
CFG_DIR="experiment/saturation_sweep/configs"

for N in $NODE_COUNTS; do
  cfg="$CFG_DIR/tournament_N${N}.json"
  if [ ! -f "$cfg" ]; then
    echo "!! missing config $cfg (skipping)" >&2
    continue
  fi
  echo "=== submitting tournament saturation: ${N} nodes ($cfg) ==="
  cinetic run -p "$PRESET" -c "$cfg"
done

echo
echo "Submitted node counts: ${NODE_COUNTS}"
echo "Results will land under data/leonardo/tournament_sat_n<N>_<timestamp>/"
echo "When the jobs finish, analyze with: experiment/saturation_sweep/analyze_sweep.sh"
