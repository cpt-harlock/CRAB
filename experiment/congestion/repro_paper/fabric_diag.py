#!/usr/bin/env python
"""Diagnostic: dump the incast/victim fabric geometry per scale so we can SEE
where the incast concentrates and whether the victim ring overlaps it."""
import glob, json, os, sys, statistics as st
sys.path.insert(0, "src")
# tee stdout to <script>.out so every run persists automatically
class _Tee:
    def __init__(self, *s): self.s = s
    def write(self, x):
        for f in self.s: f.write(x)
    def flush(self):
        for f in self.s: f.flush()
sys.stdout = _Tee(sys.__stdout__,
                  open(os.path.splitext(os.path.abspath(__file__))[0] + ".out", "w"))
from cinetic.topology.model import Topology
from cinetic.analysis.fabric import build_switch_graph, route

TOPO = Topology.load("topologies/leonardo.json")
GRAPH = build_switch_graph(TOPO)
CACHE = {}

def leaf(h):
    n = TOPO.nodes.get(h)
    return n.switches[0] if (n and n.switches) else None
def cell_of(h):
    n = TOPO.nodes.get(h)
    if not n or not n.switches: return None
    for c in TOPO.cells:
        if n.switches[0] in c.leaf_switches: return c.name
    return None
def role(s):
    return TOPO.switches[s].role if s in TOPO.switches else "?"

def sw_load(flows):
    sl = {}
    for a,b,w in flows:
        la,lb=leaf(a),leaf(b)
        if la is None or lb is None: continue
        r=route(GRAPH,la,lb,CACHE)
        if r is None: continue
        for s,frac in r.switch_w.items(): sl[s]=sl.get(s,0.0)+frac*w
    return sl

RATIO={32:0.102,64:0.051,128:0.791}
for n in (32,64,128):
    dirs=sorted(glob.glob(f"data/leonardo/congestion_agtr_inc_n{n}_vm16777216_am16777216_*"))
    print(f"\n########## n{n}  (measured matched-16MiB ratio = {RATIO[n]}) ##########")
    exposures=[]; rootleaf_shares=[]; spans=[]
    for di,d in enumerate(dirs):
        pas=glob.glob(d+"/loaded/partition_assignment.json")
        if not pas: continue
        j=json.load(open(pas[0]))
        apps={a["role"]:a for a in j["apps"]}
        if "victim" not in apps or "aggressor" not in apps: continue
        V=apps["victim"]["nodes"]; A=apps["aggressor"]["nodes"]
        root=A[0]; nsend=len(A)-1
        rleaf=leaf(root); rcell=cell_of(root)
        inc=[(a,root,1.0) for a in A[1:]]
        Isl=sw_load(inc)                       # switch load in sender-units
        Inorm={s:v/nsend for s,v in Isl.items()}   # fraction of incast through switch
        # incast top switches
        top=sorted(Inorm.items(),key=lambda x:-x[1])[:5]
        # victim ring exposure to incast switch load
        ring=[(V[i],V[(i+1)%len(V)],1.0) for i in range(len(V))]
        exps=[]
        for a,b,w in ring:
            la,lb=leaf(a),leaf(b)
            if la is None or lb is None: continue
            r=route(GRAPH,la,lb,CACHE)
            if r is None: continue
            exps.append(sum(frac*Inorm.get(s,0.0) for s,frac in r.switch_w.items()))
        E=st.mean(exps) if exps else 0.0
        exposures.append(E)
        rootleaf_shares.append(Inorm.get(rleaf,0.0))
        # cell span of whole alloc
        cells=set(filter(None,(cell_of(h) for h in V+A)))
        spans.append(len(cells))
        if di<2:  # print first 2 reps in detail
            allcells=sorted(cells)
            print(f"  rep{di}: root={root} rootleaf={rleaf}({role(rleaf)}) rootcell={rcell} "
                  f"nsend={nsend} span={len(cells)}cells victimE={E:.4f}")
            print(f"        incast rootleaf switch-load frac={Inorm.get(rleaf,0):.3f}; top switches: "
                  + ", ".join(f"{s.split(':')[-1][-8:]}({role(s)[0]}){v:.2f}" for s,v in top))
    if exposures:
        print(f"  >> n{n} AGG: victimE={st.mean(exposures):.4f}  rootleaf_incast_share={st.mean(rootleaf_shares):.3f}  span={st.mean(spans):.1f}cells  reps={len(exposures)}")
