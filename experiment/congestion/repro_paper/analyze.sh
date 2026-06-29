#!/bin/bash
# Analyze the paper-repro AllGather-victim experiments and rebuild Figure 5's
# heatmaps: for each aggressor, a (victim vector size x node count) matrix of the
# ratio uncongested/congested victim runtime (>1 = better; the paper's metric).
#
# 1. per-run analyze (baseline-vs-loaded congestion diff) for every cell;
# 2. per node count, a compare-congestion across victim vector sizes;
# 3. a heatmap CSV per aggressor (the Fig-5 ratio), from each run's
#    congestion.json overall {base,loaded}_lat_s.
set -uo pipefail

NODE_COUNTS="${NODE_COUNTS:-16 32 64 128 256}"
VICTIM_MSG_SIZES="${VICTIM_MSG_SIZES:-8 64 512 4096 32768 262144 2097152 16777216}"
AGGRESSORS="${AGGRESSORS:-alltoall incast}"
TOPO="topologies/leonardo.json"

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$REPO_ROOT"
OUT="data/leonardo/_sweep_analysis/repro_paper"; mkdir -p "$OUT"
declare -A ATAG=( [alltoall]=a2a [incast]=inc )

for AGG in $AGGRESSORS; do
  PFX="congestion_agtr_${ATAG[$AGG]}"
  for N in $NODE_COUNTS; do
    dirs=(); xs=()
    for VM in $VICTIM_MSG_SIZES; do
      d="$(ls -dt data/leonardo/${PFX}_n${N}_vm${VM}_am*_* 2>/dev/null | head -1 || true)"
      [ -z "$d" ] && continue
      cinetic analyze "$d" --topology "$TOPO" --json >/dev/null 2>&1
      dirs+=("$d"); xs+=("$VM")
    done
    if [ "${#dirs[@]}" -ge 2 ]; then
      odir="$OUT/${PFX}/n${N}"; mkdir -p "$odir"
      x_csv="$(IFS=,; echo "${xs[*]}")"
      cinetic analyze compare-congestion "${dirs[@]}" --x "$x_csv" \
        --topology "$TOPO" --outdir "$odir" --json >/dev/null 2>&1
    fi
  done

  # --- Figure-5 heatmap: ratio uncongested/congested (rows=vec, cols=nodes) ---
  PFX="$PFX" NODE_COUNTS="$NODE_COUNTS" VICTIM_MSG_SIZES="$VICTIM_MSG_SIZES" \
  OUT="$OUT" .venv/bin/python - <<'PY'
import glob, json, os
pfx=os.environ["PFX"]; nodes=os.environ["NODE_COUNTS"].split()
vms=os.environ["VICTIM_MSG_SIZES"].split(); out=os.environ["OUT"]

def ratio(run):
    js=sorted(glob.glob(f"{run}/analysis/congestion.json"))
    if not js: return None
    d=json.load(open(js[0]))
    if not d: return None
    o=d[0]["overall"]; b,l=o.get("base_lat_s"),o.get("loaded_lat_s")
    return (b/l) if (b and l) else None

rows=[]
for vm in vms:
    cells=[]
    for n in nodes:
        runs=sorted(glob.glob(f"data/leonardo/{pfx}_n{n}_vm{vm}_am*_*"),
                    key=os.path.getmtime)
        r=ratio(runs[-1]) if runs else None
        cells.append(f"{r:.3f}" if r is not None else "")
    rows.append((vm, cells))
path=f"{out}/{pfx}_heatmap.csv"
with open(path,"w") as fh:
    fh.write("victim_vec_bytes," + ",".join(f"n{n}" for n in nodes) + "\n")
    for vm,cells in rows:
        fh.write(vm + "," + ",".join(cells) + "\n")
print(f"  heatmap -> {path}  (ratio uncongested/congested, >1 = better)")
PY
done
echo
echo "Per-node dose-response: $OUT/<pfx>/n<N>/congestion_compare.*"
echo "Fig-5 heatmaps (ratio): $OUT/<pfx>_heatmap.csv"
