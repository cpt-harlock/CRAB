#!/usr/bin/env python
"""Congestion-tree footprint test. The incast saturates the root leaf; its
backpressure spreads over the SPINES that carry incast toward that leaf. A victim
ring hop routed through any of those spines is throttled by the tree (the paper's
bystander mechanism) even without sharing the bottleneck link. Measure, per scale:
  - incast spine footprint = #spines carrying >1% of incast,
  - victim overlap = fraction of victim ring hops whose ECMP path touches that
    spine footprint,
  - severity proxy = nsend (incast intensity) x victim overlap.
"""
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
TOPO=Topology.load("topologies/leonardo.json"); GRAPH=build_switch_graph(TOPO); CACHE={}
def leaf(h):
    n=TOPO.nodes.get(h); return n.switches[0] if (n and n.switches) else None
def is_spine(s): return s in TOPO.switches and TOPO.switches[s].role=="spine"
def sw_load(flows):
    sl={}
    for a,b,w in flows:
        la,lb=leaf(a),leaf(b)
        if la is None or lb is None: continue
        r=route(GRAPH,la,lb,CACHE)
        if r is None: continue
        for s,f in r.switch_w.items(): sl[s]=sl.get(s,0.0)+f*w
    return sl
RATIO={32:0.102,64:0.051,128:0.791}
print(f"{'scale':>5} {'ratio':>6} | {'nsend':>5} {'incast_spine_footprint':>22} "
      f"{'victim_overlap':>14} {'nsend x overlap':>15} {'span':>5}")
print("-"*90)
for n in (32,64,128):
    dirs=sorted(glob.glob(f"data/leonardo/congestion_agtr_inc_n{n}_vm16777216_am16777216_*"))
    foot=[]; ov=[]; prod=[]; spans=[]; nss=[]
    for d in dirs:
        pas=glob.glob(d+"/loaded/partition_assignment.json")
        if not pas: continue
        j=json.load(open(pas[0])); apps={a["role"]:a for a in j["apps"]}
        if "victim" not in apps or "aggressor" not in apps: continue
        V=apps["victim"]["nodes"]; A=apps["aggressor"]["nodes"]; root=A[0]; nsend=len(A)-1
        Isl=sw_load([(a,root,1.0) for a in A[1:]]); Inorm={s:v/nsend for s,v in Isl.items()}
        tree_spines={s for s,v in Inorm.items() if is_spine(s) and v>0.01}
        hops=touch=0
        for i in range(len(V)):
            a,b=V[i],V[(i+1)%len(V)]; la,lb=leaf(a),leaf(b)
            if la is None or lb is None: continue
            r=route(GRAPH,la,lb,CACHE)
            if r is None: continue
            hops+=1
            if any(s in tree_spines for s in r.switch_w): touch+=1
        overlap=touch/hops if hops else 0.0
        foot.append(len(tree_spines)); ov.append(overlap); prod.append(nsend*overlap); nss.append(nsend)
        cells=set()
        for h in V+A:
            nn=TOPO.nodes.get(h)
            if nn and nn.switches:
                for c in TOPO.cells:
                    if nn.switches[0] in c.leaf_switches: cells.add(c.name); break
        spans.append(len(cells))
    if ov:
        print(f"{n:>5} {RATIO[n]:>6.3f} | {st.mean(nss):>5.0f} {st.mean(foot):>22.1f} "
              f"{st.mean(ov):>14.3f} {st.mean(prod):>15.1f} {st.mean(spans):>5.1f}")
