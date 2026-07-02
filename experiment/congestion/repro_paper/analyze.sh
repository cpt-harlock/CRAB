#!/bin/bash
# Analyze the paper-repro AllGather-victim experiments and rebuild Figure 5's
# heatmaps: for each aggressor, a (victim vector size x node count) matrix of the
# ratio uncongested/congested victim runtime (<1 = victim slowed; the paper's
# metric). Each cell may have several REPS (run.sh REPS=N) — separate Slurm
# allocations, hence different node placements — which are aggregated here into a
# mean +/- std, the replicate-level error bar the in-run iterations can't give.
#
# 1. per-run analyze (baseline-vs-loaded congestion diff) for EVERY rep dir;
# 2. per node count, a compare-congestion across victim vector sizes (newest rep);
# 3. per aggressor, the Fig-5 heatmap of the ratio, aggregated across a cell's
#    reps: <pfx>_heatmap.csv (mean), _heatmap_std.csv (std), _heatmap_n.csv (#reps).
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
      # newest-first: analyze every rep of the cell, keep the newest for the
      # per-node dose-response line below (the heatmap aggregates all reps).
      mapfile -t reps < <(ls -dt data/leonardo/${PFX}_n${N}_vm${VM}_am*_* 2>/dev/null || true)
      [ "${#reps[@]}" -eq 0 ] && continue
      for r in "${reps[@]}"; do
        cinetic analyze "$r" --topology "$TOPO" --json >/dev/null 2>&1
      done
      dirs+=("${reps[0]}"); xs+=("$VM")
    done
    if [ "${#dirs[@]}" -ge 2 ]; then
      odir="$OUT/${PFX}/n${N}"; mkdir -p "$odir"
      x_csv="$(IFS=,; echo "${xs[*]}")"
      cinetic analyze compare-congestion "${dirs[@]}" --x "$x_csv" \
        --topology "$TOPO" --outdir "$odir" --json >/dev/null 2>&1
    fi
  done

  # --- Figure-5 heatmap: ratio uncongested/congested (rows=vec, cols=nodes),
  #     aggregated over a cell's reps into mean / std / count -----------------
  PFX="$PFX" NODE_COUNTS="$NODE_COUNTS" VICTIM_MSG_SIZES="$VICTIM_MSG_SIZES" \
  OUT="$OUT" .venv/bin/python - <<'PY'
import glob, json, os, re, statistics
from itertools import combinations
pfx=os.environ["PFX"]; nodes=os.environ["NODE_COUNTS"].split()
vms=os.environ["VICTIM_MSG_SIZES"].split(); out=os.environ["OUT"]
agg=pfx.split("_")[-1]   # a2a / inc

def ratio(run):
    js=sorted(glob.glob(f"{run}/analysis/congestion.json"))
    if not js: return None
    d=json.load(open(js[0]))
    if not d: return None
    o=d[0]["overall"]; b,l=o.get("base_lat_s"),o.get("loaded_lat_s")
    return (b/l) if (b and l) else None

def node_set(run):
    # Full allocation (victim + aggressor) as short hostnames, from the
    # partition assignment; fall back to the collecting app's per-node CSVs.
    for ph in ("loaded","baseline"):
        p=os.path.join(run,ph,"partition_assignment.json")
        if not os.path.exists(p): continue
        j=json.load(open(p)); ns=set()
        for a in j.get("apps",[]):
            ns.update(h.split(".")[0] for h in a.get("nodes",[]))
        if not ns:
            for v in j.get("partitions",{}).values():
                ns.update(h.split(".")[0] for h in v)
        if ns: return ns
    ns=set()
    for ph in ("loaded","baseline"):
        for f in glob.glob(os.path.join(run,ph,"node_app*_*.csv")):
            m=re.match(r"node_app\d+_(.+)_rank\d+\.csv", os.path.basename(f))
            if m: ns.add(m.group(1).split(".")[0])
        if ns: break
    return ns

def overlap(sets):
    # Placement recurrence across a cell's reps. Returns (alloc, gN, gFrac,
    # meanPairN, meanPairFrac) or None when <2 non-empty sets.
    sets=[s for s in sets if s]
    if len(sets)<2: return None
    alloc=statistics.median(len(s) for s in sets)
    gN=len(set.intersection(*sets))
    pair=[len(a & b) for a,b in combinations(sets,2)]
    mp=statistics.mean(pair)
    return alloc, gN, (gN/alloc if alloc else 0), mp, (mp/alloc if alloc else 0)

# Aggregate all reps of each (vm, n) cell; collect ratio + placement stats.
mean_rows=[]; std_rows=[]; n_rows=[]; pretty_rows=[]; stat_rows=[]
for vm in vms:
    mc=[]; sc=[]; nc=[]; pc=[]
    for n in nodes:
        runs=glob.glob(f"data/leonardo/{pfx}_n{n}_vm{vm}_am*_*")
        pairs=[(ratio(x), node_set(x)) for x in runs]
        pairs=[(r,s) for r,s in pairs if r is not None]   # keep aggregated reps
        rs=[r for r,_ in pairs]
        if rs:
            m=statistics.mean(rs)
            sd=statistics.stdev(rs) if len(rs)>1 else 0.0
            cv=100*sd/m if m else 0.0
            mc.append(f"{m:.3f}"); sc.append(f"{sd:.3f}"); nc.append(str(len(rs)))
            pc.append(f"{m:.3f}±{sd:.3f}({len(rs)})")
            ov=overlap([s for _,s in pairs])
            if ov: alloc,gN,gF,mp,mpF=ov
            else:  alloc,gN,gF,mp,mpF=(len(pairs[0][1]) or ""),"","","",""
            fmt=lambda v,d=3: f"{v:.{d}f}" if isinstance(v,float) else v
            stat_rows.append([agg,n,vm,len(rs),f"{m:.4f}",f"{sd:.4f}",
                              f"{cv:.1f}",f"{min(rs):.4f}",f"{max(rs):.4f}",
                              alloc,gN,fmt(gF),fmt(mp,1),fmt(mpF)])
        else:
            mc.append(""); sc.append(""); nc.append("0"); pc.append("")
    mean_rows.append((vm,mc)); std_rows.append((vm,sc))
    n_rows.append((vm,nc));    pretty_rows.append((vm,pc))

def write(path, rows):
    with open(path,"w") as fh:
        fh.write("victim_vec_bytes," + ",".join(f"n{n}" for n in nodes) + "\n")
        for vm,cells in rows:
            fh.write(vm + "," + ",".join(cells) + "\n")

write(f"{out}/{pfx}_heatmap.csv",     mean_rows)
write(f"{out}/{pfx}_heatmap_std.csv", std_rows)
write(f"{out}/{pfx}_heatmap_n.csv",   n_rows)
with open(f"{out}/{pfx}_rep_stats.csv","w") as fh:
    fh.write("aggressor,nodes,victim_vec_bytes,n_reps,ratio_mean,ratio_std,"
             "ratio_cv_pct,ratio_min,ratio_max,alloc_nodes,global_overlap_nodes,"
             "global_overlap_frac,mean_pairwise_overlap_nodes,mean_pairwise_overlap_frac\n")
    for r in stat_rows:
        fh.write(",".join(str(c) for c in r) + "\n")

print(f"  heatmap -> {out}/{pfx}_heatmap.csv  (mean ratio uncongested/congested; <1 = victim slowed)")
print(f"    std -> {out}/{pfx}_heatmap_std.csv   reps -> {out}/{pfx}_heatmap_n.csv")
print(f"    rep stats (cv, min/max, placement overlap) -> {out}/{pfx}_rep_stats.csv")
print("  mean±std(reps), rows=victim vec bytes, cols=" + " ".join(f"n{n}" for n in nodes) + ":")
for vm,cells in pretty_rows:
    print(f"    {vm:>9} | " + "  ".join(c if c else "-" for c in cells))
# Placement diversity note for the multi-rep cells (low overlap = independent draws).
multi=[r for r in stat_rows if r[3]>1 and r[11]!=""]
if multi:
    print("  placement overlap across reps (global ∩ / mean pairwise ∩, of alloc):")
    for r in multi:
        print(f"    n{r[1]:<4} vm{r[2]:<9} n={r[3]}: "
              f"global {r[10]}/{r[9]} ({float(r[11])*100:.0f}%), "
              f"pairwise {r[12]}/{r[9]} ({float(r[13])*100:.0f}%)  "
              f"ratio {r[4]}±{r[5]} (cv {r[6]}%)")
PY
done
echo
echo "Per-node dose-response: $OUT/<pfx>/n<N>/congestion_compare.*"
echo "Fig-5 heatmaps: $OUT/<pfx>_heatmap.csv (mean) + _heatmap_std.csv + _heatmap_n.csv"
echo "Per-cell rep stats (cv, min/max, placement overlap): $OUT/<pfx>_rep_stats.csv"
