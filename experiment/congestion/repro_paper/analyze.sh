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

# --- DATA_DIR: which data/<system> tree to read runs from (default data/leonardo).
#     Set DATA_DIR=data/leonardo_sl0 to analyze the SL=0 arm; OUT then defaults to
#     that tree's own _sweep_analysis so SL=0 outputs never mix with the SL=1 ones.
DATA_DIR="${DATA_DIR:-data/leonardo}"

# --- AGGR_MSG: scope which aggressor message size to aggregate (mirrors run.sh).
#     empty (default) -> am* : every aggressor size for the cell (back-compatible);
#     "match"         -> am<VM> per cell (the aggressor-follows-victim sweep);
#     <number>        -> that exact am. When set, outputs get an _am<val> suffix so
#     a scoped analysis never overwrites the default (fixed-size) heatmap column.
AGGR_MSG="${AGGR_MSG:-}"
if [ -n "$AGGR_MSG" ]; then SUF="_am${AGGR_MSG}"; else SUF=""; fi
amtok() { if [ -z "$AGGR_MSG" ]; then echo "am*"; elif [ "$AGGR_MSG" = match ]; then echo "am$1"; else echo "am${AGGR_MSG}"; fi; }

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$REPO_ROOT"
OUT="${OUT:-$DATA_DIR/_sweep_analysis/repro_paper}"; mkdir -p "$OUT"
declare -A ATAG=( [alltoall]=a2a [incast]=inc )

for AGG in $AGGRESSORS; do
  PFX="congestion_agtr_${ATAG[$AGG]}"
  for N in $NODE_COUNTS; do
    dirs=(); xs=()
    for VM in $VICTIM_MSG_SIZES; do
      # newest-first: analyze every rep of the cell, keep the newest for the
      # per-node dose-response line below (the heatmap aggregates all reps).
      mapfile -t reps < <(ls -dt ${DATA_DIR}/${PFX}_n${N}_vm${VM}_$(amtok "$VM")_* 2>/dev/null || true)
      [ "${#reps[@]}" -eq 0 ] && continue
      for r in "${reps[@]}"; do
        cinetic analyze "$r" --topology "$TOPO" --json >/dev/null 2>&1
      done
      dirs+=("${reps[0]}"); xs+=("$VM")
    done
    if [ "${#dirs[@]}" -ge 2 ]; then
      odir="$OUT/${PFX}${SUF}/n${N}"; mkdir -p "$odir"
      x_csv="$(IFS=,; echo "${xs[*]}")"
      cinetic analyze compare-congestion "${dirs[@]}" --x "$x_csv" \
        --topology "$TOPO" --outdir "$odir" --json >/dev/null 2>&1
    fi
  done

  # --- Figure-5 heatmap: ratio uncongested/congested (rows=vec, cols=nodes),
  #     aggregated over a cell's reps into mean / std / count -----------------
  PFX="$PFX" NODE_COUNTS="$NODE_COUNTS" VICTIM_MSG_SIZES="$VICTIM_MSG_SIZES" \
  OUT="$OUT" TOPO="$TOPO" AGGR_MSG="$AGGR_MSG" SUF="$SUF" DATA_DIR="$DATA_DIR" .venv/bin/python - <<'PY'
import glob, json, os, re, statistics
from itertools import combinations
pfx=os.environ["PFX"]; nodes=os.environ["NODE_COUNTS"].split()
vms=os.environ["VICTIM_MSG_SIZES"].split(); out=os.environ["OUT"]
am=os.environ.get("AGGR_MSG",""); suf=os.environ.get("SUF","")
data_dir=os.environ.get("DATA_DIR","data/leonardo")
def amtok(vm):
    return "am*" if not am else (f"am{vm}" if am=="match" else f"am{am}")
agg=pfx.split("_")[-1]   # a2a / inc

def load_topo(path):
    # node -> cell name, node -> set(leaf switch ids), straight from the JSON
    # (avoids importing cinetic into the .venv used for this block).
    if not path or not os.path.exists(path): return None
    t=json.load(open(path)); n2cell={}; n2sw={}
    for nd in t.get("nodes",[]):
        h=nd.get("hostname","").split(".")[0]
        if not h: continue
        n2cell[h]=nd.get("cell"); n2sw[h]=set(nd.get("switches",[]))
    return (n2cell, n2sw)
topo=load_topo(os.environ.get("TOPO"))

def parts(run):
    # victim (end=='') and aggressor (end=='f') node sets from the loaded phase.
    p=os.path.join(run,"loaded","partition_assignment.json")
    if not os.path.exists(p): return None, None
    j=json.load(open(p)); vic=set(); ag=set()
    for a in j.get("apps",[]):
        ns={h.split(".")[0] for h in a.get("nodes",[])}
        if a.get("role")=="victim" or a.get("end","")=="": vic|=ns
        elif a.get("role")=="aggressor" or a.get("end")=="f": ag|=ns
    return (vic or None), (ag or None)

def _loc(a,b,n2cell,n2sw):
    if n2sw.get(a) and n2sw.get(b) and (n2sw[a] & n2sw[b]): return "sw"
    ca,cb=n2cell.get(a),n2cell.get(b)
    if ca is not None and ca==cb: return "cell"
    return "cross"

def va_locality(vic,ag):
    # locality mix over victim x aggressor host pairs, + cell span of the alloc.
    if not topo or not vic or not ag: return None
    n2cell,n2sw=topo; t={"sw":0,"cell":0,"cross":0}; tot=0
    for x in vic:
        if x not in n2cell: continue
        for y in ag:
            if y not in n2cell: continue
            t[_loc(x,y,n2cell,n2sw)]+=1; tot+=1
    if not tot: return None
    span=len({n2cell.get(h) for h in (vic|ag) if n2cell.get(h) is not None})
    return (t["sw"]/tot, t["cell"]/tot, t["cross"]/tot, span)

def pearson(xs,ys):
    if len(xs)<3: return None
    mx=statistics.mean(xs); my=statistics.mean(ys)
    sx=statistics.pstdev(xs); sy=statistics.pstdev(ys)
    if sx==0 or sy==0: return None
    return sum((x-mx)*(y-my) for x,y in zip(xs,ys))/len(xs)/(sx*sy)

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
mean_rows=[]; std_rows=[]; n_rows=[]; pretty_rows=[]; stat_rows=[]; detail_rows=[]
for vm in vms:
    mc=[]; sc=[]; nc=[]; pc=[]
    for n in nodes:
        runs=glob.glob(f"{data_dir}/{pfx}_n{n}_vm{vm}_{amtok(vm)}_*")
        reps=[]                                   # (run, ratio, node_set, locality)
        for run in runs:
            r=ratio(run)
            if r is None: continue                # keep only reps with a ratio
            vic,ag=parts(run)
            reps.append((run, r, node_set(run), va_locality(vic,ag)))
        rs=[r for _,r,_,_ in reps]
        if rs:
            m=statistics.mean(rs)
            sd=statistics.stdev(rs) if len(rs)>1 else 0.0
            cv=100*sd/m if m else 0.0
            mc.append(f"{m:.3f}"); sc.append(f"{sd:.3f}"); nc.append(str(len(rs)))
            pc.append(f"{m:.3f}±{sd:.3f}({len(rs)})")
            ov=overlap([s for _,_,s,_ in reps])
            if ov: alloc,gN,gF,mp,mpF=ov
            else:  alloc,gN,gF,mp,mpF=(len(reps[0][2]) or ""),"","","",""
            fmt=lambda v,d=3: f"{v:.{d}f}" if isinstance(v,float) else v
            # topology-locality of the victim<->aggressor placement, per rep.
            locs=[l for _,_,_,l in reps if l]
            if locs:
                msw=statistics.mean(l[0] for l in locs)
                mcell=statistics.mean(l[1] for l in locs)
                mcross=statistics.mean(l[2] for l in locs)
                mspan=statistics.mean(l[3] for l in locs)
                xs=[l[2] for _,_,_,l in reps if l]      # cross-cell frac
                ys=[r for _,r,_,l in reps if l]         # ratio
                corr=pearson(xs,ys)
                loc_cols=[fmt(mspan,1),fmt(msw),fmt(mcell),fmt(mcross),
                          fmt(corr) if corr is not None else ""]
            else:
                loc_cols=["","","","",""]
            stat_rows.append([agg,n,vm,len(rs),f"{m:.4f}",f"{sd:.4f}",
                              f"{cv:.1f}",f"{min(rs):.4f}",f"{max(rs):.4f}",
                              alloc,gN,fmt(gF),fmt(mp,1),fmt(mpF)]+loc_cols)
            for run,r,_,l in reps:
                detail_rows.append([agg,n,vm,os.path.basename(run),f"{r:.4f}",
                    (fmt(l[0]) if l else ""),(fmt(l[1]) if l else ""),
                    (fmt(l[2]) if l else ""),(l[3] if l else "")])
        else:
            mc.append(""); sc.append(""); nc.append("0"); pc.append("")
    mean_rows.append((vm,mc)); std_rows.append((vm,sc))
    n_rows.append((vm,nc));    pretty_rows.append((vm,pc))

def write(path, rows):
    with open(path,"w") as fh:
        fh.write("victim_vec_bytes," + ",".join(f"n{n}" for n in nodes) + "\n")
        for vm,cells in rows:
            fh.write(vm + "," + ",".join(cells) + "\n")

write(f"{out}/{pfx}{suf}_heatmap.csv",     mean_rows)
write(f"{out}/{pfx}{suf}_heatmap_std.csv", std_rows)
write(f"{out}/{pfx}{suf}_heatmap_n.csv",   n_rows)
with open(f"{out}/{pfx}{suf}_rep_stats.csv","w") as fh:
    fh.write("aggressor,nodes,victim_vec_bytes,n_reps,ratio_mean,ratio_std,"
             "ratio_cv_pct,ratio_min,ratio_max,alloc_nodes,global_overlap_nodes,"
             "global_overlap_frac,mean_pairwise_overlap_nodes,mean_pairwise_overlap_frac,"
             "mean_span_cells,mean_va_same_switch_frac,mean_va_same_cell_frac,"
             "mean_va_cross_cell_frac,ratio_vs_crosscell_r\n")
    for r in stat_rows:
        fh.write(",".join(str(c) for c in r) + "\n")
# Per-rep detail: ratio vs victim<->aggressor locality, to test whether the
# low-ratio (strongly congested) reps are the cross-cell placements.
with open(f"{out}/{pfx}{suf}_rep_detail.csv","w") as fh:
    fh.write("aggressor,nodes,victim_vec_bytes,run,ratio,va_same_switch_frac,"
             "va_same_cell_frac,va_cross_cell_frac,alloc_span_cells\n")
    for r in detail_rows:
        fh.write(",".join(str(c) for c in r) + "\n")

print(f"  heatmap -> {out}/{pfx}{suf}_heatmap.csv  (mean ratio uncongested/congested; <1 = victim slowed)")
print(f"    std -> {out}/{pfx}{suf}_heatmap_std.csv   reps -> {out}/{pfx}{suf}_heatmap_n.csv")
print(f"    rep stats (cv, min/max, overlap, locality) -> {out}/{pfx}{suf}_rep_stats.csv")
print(f"    per-rep detail (ratio vs locality) -> {out}/{pfx}{suf}_rep_detail.csv")
print("  mean±std(reps), rows=victim vec bytes, cols=" + " ".join(f"n{n}" for n in nodes) + ":")
for vm,cells in pretty_rows:
    print(f"    {vm:>9} | " + "  ".join(c if c else "-" for c in cells))
# Placement diversity note for the multi-rep cells (low overlap = independent draws).
multi=[r for r in stat_rows if r[3]>1 and r[11]!=""]
if multi:
    print("  placement overlap + victim↔aggressor locality across reps:")
    for r in multi:
        loc=(f"  x-cell {float(r[17])*100:.0f}%" if r[17]!="" else "")
        corr=(f"  corr(ratio,x-cell)={r[18]}" if r[18]!="" else "")
        print(f"    n{r[1]:<4} vm{r[2]:<9} n={r[3]}: "
              f"global {r[10]}/{r[9]} ({float(r[11])*100:.0f}%), "
              f"pairwise {r[12]}/{r[9]} ({float(r[13])*100:.0f}%)  "
              f"ratio {r[4]}±{r[5]} (cv {r[6]}%){loc}{corr}")
PY
done
echo
echo "Per-node dose-response: $OUT/<pfx>/n<N>/congestion_compare.*"
echo "Fig-5 heatmaps: $OUT/<pfx>_heatmap.csv (mean) + _heatmap_std.csv + _heatmap_n.csv"
echo "Per-cell rep stats (cv, min/max, overlap, locality): $OUT/<pfx>_rep_stats.csv"
echo "Per-rep detail (ratio vs victim<->aggressor locality): $OUT/<pfx>_rep_detail.csv"
