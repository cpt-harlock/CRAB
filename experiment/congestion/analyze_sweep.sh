#!/bin/bash
# Analyze the 2D congestion sweep (nodes x aggressor message size).
#   1. per-run report (+ fabric + baseline-vs-loaded congestion diff) per cell;
#   2. for each node count, a `compare-congestion` across aggressor message sizes
#      (the dose-response at that scale), x = aggressor message size.
# Dose-response tables land under data/leonardo/_sweep_analysis/congestion/n<N>/.
set -uo pipefail

NODE_COUNTS="${NODE_COUNTS:-4 8 16 32 64 128 256 512 1024}"
MSG_SIZES="${MSG_SIZES:-8 64 512 4096 32768 262144 2097152 16777216}"
TOPO="topologies/leonardo.json"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"
OUT="data/leonardo/_sweep_analysis/congestion"

for N in $NODE_COUNTS; do
  dirs=(); xs=()
  for M in $MSG_SIZES; do
    d="$(ls -dt data/leonardo/congestion_a2a_n${N}_m${M}_* 2>/dev/null | head -1 || true)"
    [ -z "$d" ] && continue
    echo "=== per-run: ${N} nodes, aggr msg ${M} ($d) ==="
    cinetic analyze "$d" --topology "$TOPO" --fabric --json >/dev/null 2>&1
    dirs+=("$d"); xs+=("$M")
  done
  if [ "${#dirs[@]}" -ge 2 ]; then
    odir="$OUT/n${N}"; mkdir -p "$odir"
    x_csv="$(IFS=,; echo "${xs[*]}")"
    labels=(); for M in "${xs[@]}"; do labels+=(--label "${M}B"); done
    echo "--- compare-congestion dose-response @ ${N} nodes (x=$x_csv) ---"
    cinetic analyze compare-congestion "${dirs[@]}" "${labels[@]}" \
      --x "$x_csv" --topology "$TOPO" --outdir "$odir" --json
  fi
done
echo
echo "Per-node-count dose-response tables under $OUT/n<N>/congestion_compare.{txt,json,png}"
