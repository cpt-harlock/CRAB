#!/bin/bash
# Congestion experiment (Leonardo DCGP): a tournament_nb victim measured with and
# without a co-running alltoall aggressor sharing the same cells.
#
# A single `cinetic run` submits ONE Slurm job containing BOTH experiments
# (baseline = victim only, loaded = victim + aggressor). They run sequentially on
# the same allocation, so the victim occupies the SAME nodes in both phases and
# the per-node congestion diff is clean.
set -euo pipefail

CONFIG="${1:-experiment/congestion/configs/congestion_a2a_n16.json}"
PRESET="leonardo"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

echo "=== submitting congestion experiment ($CONFIG) ==="
cinetic run -p "$PRESET" -c "$CONFIG"

echo
echo "Result dir: data/leonardo/congestion_a2a_*_<timestamp>/  (baseline/ + loaded/)"
echo "When the job finishes, analyze with: experiment/congestion/analyze.sh"
