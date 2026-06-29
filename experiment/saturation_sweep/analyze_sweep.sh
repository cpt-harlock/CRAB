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

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"
OUT="data/leonardo/_sweep_analysis/saturation"

for M in $MSG_SIZES; do
  dirs=(); xs=()
  for N in $NODE_COUNTS; do
    d="$(ls -dt data/leonardo/tournament_sat_n${N}_m${M}_* 2>/dev/null | head -1 || true)"
    [ -z "$d" ] && continue
    echo "=== per-run: ${N} nodes, msg ${M} ($d) ==="
    cinetic analyze "$d" --topology "$TOPO" --fabric --json >/dev/null 2>&1
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
