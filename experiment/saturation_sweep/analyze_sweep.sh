#!/bin/bash
# Analyze the tournament saturation sweep: per-run report (+ fabric) for each
# node count, then a cross-experiment comparison with node count as the x-axis
# (bandwidth-vs-nodes scaling curve). Uses the cinetic analyze CLI only.
set -euo pipefail

NODE_COUNTS="2 4 8 16 32 64"
TOPO="topologies/leonardo.json"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

dirs=()
xs=()
for N in $NODE_COUNTS; do
  # latest run for this node count
  d="$(ls -dt data/leonardo/tournament_sat_n${N}_* 2>/dev/null | head -1 || true)"
  if [ -z "$d" ]; then
    echo "!! no run found for ${N} nodes (data/leonardo/tournament_sat_n${N}_*)" >&2
    continue
  fi
  echo "=== per-run analysis: ${N} nodes ($d) ==="
  cinetic analyze "$d" --topology "$TOPO" --fabric --json
  dirs+=("$d")
  xs+=("$N")
done

if [ "${#dirs[@]}" -ge 2 ]; then
  echo
  echo "=== cross-node-count comparison (bandwidth vs nodes) ==="
  x_csv="$(IFS=,; echo "${xs[*]}")"
  cinetic analyze compare "${dirs[@]}" --x "$x_csv" --topology "$TOPO" --json
  echo "comparison.{txt,json,png} written under ${dirs[0]}/analysis/"
else
  echo "need >= 2 completed runs to compare" >&2
fi
