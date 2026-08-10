#!/usr/bin/env python
"""Render a paper-style (De Sensi/Piarulli Fig. 5) congestion heatmap from a
sweep-analysis <pfx>_heatmap.csv (+ _std/_n siblings): victim AllGather vector
size (y) x node count (x), coloured by the ratio uncongested/congested victim
runtime (<1 = victim slowed). Red = congested, green = unaffected; every cell is
annotated with mean / ±std (reps) so magnitude is never colour-alone (CVD-safe).

Usage: plot_heatmap.py <heatmap.csv> [-o out.png] [--title "..."]
"""
import argparse, csv, os, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

SIZES = {8:"8 B",64:"64 B",512:"512 B",4096:"4 KiB",32768:"32 KiB",
         262144:"256 KiB",524288:"512 KiB",1048576:"1 MiB",2097152:"2 MiB",
         4194304:"4 MiB",8388608:"8 MiB",16777216:"16 MiB"}

def load(path):
    rows=list(csv.reader(open(path))); hdr=rows[0][1:]
    vm=[]; M=[]
    for r in rows[1:]:
        vm.append(int(r[0]))
        M.append([float(x) if x not in ("","-") else np.nan for x in r[1:]])
    return hdr, vm, np.array(M)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("-o","--out",default=None)
    ap.add_argument("--title",default=None)
    a=ap.parse_args()
    base=a.csv[:-len("_heatmap.csv")] if a.csv.endswith("_heatmap.csv") else os.path.splitext(a.csv)[0]
    hdr,vm,M=load(a.csv)
    S=load(base+"_heatmap_std.csv")[2] if os.path.exists(base+"_heatmap_std.csv") else np.full_like(M,np.nan)
    N=None
    if os.path.exists(base+"_heatmap_n.csv"):
        N=[[int(x) if x.strip() not in("","-") else 0 for x in r[1:]]
           for r in list(csv.reader(open(base+"_heatmap_n.csv")))[1:]]
        N=np.array(N)

    cols=[c.replace("n","")+" nodes" for c in hdr]
    yl=[SIZES.get(v,str(v)) for v in vm]

    # red(bad,0) -> yellow(0.5) -> green(good,1); values >1 clip to green.
    cmap=LinearSegmentedColormap.from_list("congestion",
        ["#b2182b","#ef8a62","#fddbc7","#f7f7f7","#d9f0d3","#7fbf7b","#1a9850"])
    cmap.set_bad("#dddddd")

    fig,ax=plt.subplots(figsize=(6.2,6.6))
    im=ax.imshow(M,origin="lower",cmap=cmap,vmin=0.0,vmax=1.0,aspect="auto")

    ax.set_xticks(range(len(cols))); ax.set_xticklabels(cols)
    ax.set_yticks(range(len(yl)));  ax.set_yticklabels(yl)
    ax.set_xlabel("Job size (nodes)",fontweight="bold")
    ax.set_ylabel("Victim AllGather vector size",fontweight="bold")
    ax.set_title(a.title or "Incast aggressor (2 MiB) — AllGather victim slowdown\n"
                 "Leonardo Booster · ratio = uncongested/congested runtime (<1 = slowed)",
                 fontsize=10.5)

    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            v=M[i,j]
            if np.isnan(v):
                ax.text(j,i,"—",ha="center",va="center",color="#666"); continue
            ink="white" if (v<0.28 or v>0.97) else "black"
            sd=S[i,j] if S is not None and not np.isnan(S[i,j]) else None
            n=N[i,j] if N is not None else None
            sub = (f"±{sd:.2f}" if sd is not None else "") + (f" (n={n})" if n else "")
            ax.text(j,i+0.14,f"{v:.2f}",ha="center",va="center",
                    color=ink,fontsize=11,fontweight="bold")
            if sub:
                ax.text(j,i-0.22,sub,ha="center",va="center",color=ink,fontsize=7)

    cb=fig.colorbar(im,ax=ax,fraction=0.046,pad=0.04,extend="max")
    cb.set_label("ratio uncongested / congested   (1.0 = no congestion)",fontsize=9)
    ax.set_xticks(np.arange(-.5,len(cols),1),minor=True)
    ax.set_yticks(np.arange(-.5,len(yl),1),minor=True)
    ax.grid(which="minor",color="white",linewidth=1.5); ax.tick_params(which="minor",length=0)
    fig.tight_layout()
    out=a.out or (base+"_fig.png")
    fig.savefig(out,dpi=150,bbox_inches="tight")
    print("wrote",out)

if __name__=="__main__":
    main()
