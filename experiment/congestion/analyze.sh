#!/bin/bash
# Analyze the congestion experiment. Analyzing the whole run dir gives, per
# experiment, the per-app report (+ fabric), and then the congestion layer
# auto-detects the victim-only `baseline` vs the `loaded` experiment and diffs
# the victim: bandwidth-drop% / latency-increase% overall, per topology label,
# and per node (worst-hit first). Output: <run>/baseline/analysis/congestion.*
set -euo pipefail

TOPO="topologies/leonardo.json"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

# newest congestion run unless one is given
RUN="${1:-$(ls -dt data/leonardo/congestion_a2a_* 2>/dev/null | head -1)}"
if [ -z "${RUN:-}" ] || [ ! -d "$RUN" ]; then
  echo "no congestion run found (data/leonardo/congestion_a2a_*); pass one explicitly" >&2
  exit 1
fi

echo "=== analyzing $RUN (per-exp report + fabric + congestion diff) ==="
cinetic analyze "$RUN" --topology "$TOPO" --fabric --json

echo
echo "Congestion summary written under $RUN/<exp>/analysis/congestion.{txt,json,png}"
