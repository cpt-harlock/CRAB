#!/bin/bash
# Analyze the 2D tournament saturation sweep (nodes x message size).
#   1. per-run report (+ fabric) for every (N, M) cell that produced data;
#   2. for each message size, a `compare` across node counts (bandwidth-vs-nodes
#      scaling curve at that message size), x = node count.
# Comparisons land under data/leonardo/_sweep_analysis/saturation/m<M>/.
set -uo pipefail

NODE_COUNTS="${NODE_COUNTS:-2 4 8 16 32 64 128 256 512 1024}"
MSG_SIZES="${MSG_SIZES:-8 64 512 4096 32768 262144 2097152 16777216}"
TOPO="topologies/leonardo.json"
# DATA_DIR: which data/<system> tree to read runs from (default data/leonardo).
# Set DATA_DIR=data/leonardo_maint for maintenance-window runs (leonardo_maint
# preset); OUT then defaults to that tree's own _sweep_analysis.
DATA_DIR="${DATA_DIR:-data/leonardo}"
# FABRIC=1 adds --fabric (ECMP hotspot attribution) to each per-run analyze. It
# is O(nodes*flows) and blows the login-node CPU cap for large runs (>=512
# nodes) — set FABRIC=0 (default) for big sweeps, and/or run this on a compute
# node (srun/sbatch), where there is no 600s per-process CPU limit.
FABRIC="${FABRIC:-0}"
fabric_arg=(); [ "$FABRIC" = 1 ] && fabric_arg=(--fabric)

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"
OUT="${OUT:-$DATA_DIR/_sweep_analysis/saturation}"

for M in $MSG_SIZES; do
  dirs=(); xs=()
  for N in $NODE_COUNTS; do
    d="$(ls -dt ${DATA_DIR}/tournament_sat_n${N}_m${M}_* 2>/dev/null | head -1 || true)"
    [ -z "$d" ] && continue
    echo "=== per-run: ${N} nodes, msg ${M} ($d) ==="
    cinetic analyze "$d" --topology "$TOPO" "${fabric_arg[@]}" --json >/dev/null 2>&1
    dirs+=("$d"); xs+=("$N")
  done
  if [ "${#dirs[@]}" -ge 2 ]; then
    odir="$OUT/m${M}"; mkdir -p "$odir"
    x_csv="$(IFS=,; echo "${xs[*]}")"
    echo "--- compare bandwidth vs nodes @ msg ${M} (x=$x_csv) ---"
    cinetic analyze compare "${dirs[@]}" --x "$x_csv" --topology "$TOPO" \
      --outdir "$odir" --json
  fi
done
echo
echo "Per-msgsize bandwidth-vs-nodes comparisons under $OUT/m<M>/comparison.{txt,json,png}"
