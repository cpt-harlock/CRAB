#!/bin/bash
# Tournament bandwidth saturation sweep — 2D: node count x message size.
# One Slurm job per (nodes, msgsize) cell, submitted via the cinetic CLI; configs
# are generated on the fly into generated/ (gitignored). Targets Leonardo Booster
# by default (partition/QOS/reservation set in experiment/lib/launch.sh).
#
# Axes (edit to run a subset):
#   NODE_COUNTS : powers of two, tournament needs an even rank count.
#   MSG_SIZES   : 8 B .. 16 MB, x8 each step.
# Scheduler knobs (PARTITION/ACCOUNT/QOS/GRES/RESERVATION/EXTRA_SBATCH/
# NO_AUTO_QOS/CHAIN/PRESET) come from the shared launcher — see experiment/lib/launch.sh.
set -uo pipefail

NODE_COUNTS="${NODE_COUNTS:-2 4 8 16 32 64 128 256 512 1024}"
MSG_SIZES="${MSG_SIZES:-8 64 512 4096 32768 262144 2097152 16777216}"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT" || exit 1
source experiment/lib/launch.sh
HERE="experiment/saturation_sweep"
GEN="$HERE/generated"
mkdir -p "$GEN"

for N in $NODE_COUNTS; do
  for M in $MSG_SIZES; do
    cfg="$GEN/tournament_n${N}_m${M}.json"
    launch_dep_args
    if python "$HERE/gen_config.py" --nodes "$N" --msgsize "$M" \
         "${LAUNCH_GEN_ARGS[@]}" "${LAUNCH_DEP_ARGS[@]}" -o "$cfg" >/dev/null; then
      launch_submit "$cfg" "saturation: ${N} nodes, msg ${M} B"
    fi
  done
done

launch_footer
echo "Results: data/leonardo/tournament_sat_n<N>_m<M>_<timestamp>/"
echo "Analyze with: $HERE/analyze_sweep.sh"
echo
echo "NB: the full grid is large and the big cells (>=512 nodes, >=2 MB) are heavy"
echo "    — submit a subset first via e.g.  NODE_COUNTS='2 4 8' MSG_SIZES='4096' $0"
