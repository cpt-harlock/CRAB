#!/bin/bash
# Congestion experiment (Leonardo DCGP): a tournament_nb victim measured with and
# without a co-running alltoall aggressor sharing the same cells.
#
# A single `cinetic run` submits ONE Slurm job containing BOTH experiments
# (baseline = victim only, loaded = victim + aggressor). They run sequentially on
# the same allocation, so the victim occupies the SAME nodes in both phases and
# the per-node congestion diff is clean.
#
# This launches a PRE-BUILT config from configs/, so its #SBATCH directives are
# already baked in: the gen-time scheduler knobs (PARTITION/QOS/GRES/...) do NOT
# apply here — edit the config, or use run_sweep.sh to inject them on the fly.
# PRESET and CHAIN (from experiment/lib/launch.sh) still apply.
set -uo pipefail

CONFIG="${1:-experiment/congestion/configs/congestion_a2a_n16.json}"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT" || exit 1
source experiment/lib/launch.sh

launch_submit "$CONFIG" "congestion ($CONFIG)"

launch_footer
echo "Result dir: data/leonardo/congestion_a2a_*_<timestamp>/  (baseline/ + loaded/)"
echo "When the job finishes, analyze with: experiment/congestion/analyze.sh"
