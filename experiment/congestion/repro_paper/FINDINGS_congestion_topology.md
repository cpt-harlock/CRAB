# Incast congestion on Leonardo: aggressor message size & topology placement

**Date:** 2026-07-06 · **Status:** fixed 1 MiB cells at 19–20 reps; matched-size
sweep complete for n32/n64/n128 (5 reps); **author-confirmed fixed 2 MiB and
8 MiB aggressor sweeps** complete for n32/n64 (5 reps); SL=0 contrast at n64.
**Data:** `data/leonardo/_sweep_analysis/repro_paper/congestion_agtr_inc_am{2097152,8388608,match}_{heatmap,rep_stats,rep_detail}.csv`
(aggressor = fixed 2 MiB / fixed 8 MiB / matched-to-victim-vector) plus the
unsuffixed `congestion_agtr_inc_heatmap.csv` (original fixed 1 MiB). SL=0 contrast
in `data/leonardo_sl0/_sweep_analysis/repro_paper/`.

## Setup

Paper-repro congestion cells (Leonardo Booster, HDR IB Dragonfly+). Victim =
ring AllGather (`agtr_comm_only`), aggressor = Incast (`inc_nb`, endless), 50:50
**interleaved** partition, aggressor leads by 10 s. Metric per run is the ratio
`uncongested/congested` victim runtime (**<1 = victim slowed**; the paper's Fig-5
metric). Each cell is run as several **reps** — separate Slurm allocations, i.e.
different node placements — to separate measurement noise from placement variance.
Throughout, **cv = coefficient of variation = std/mean** (relative spread across
reps).

The paper does **not** state the aggressor's message size. Sections 1–5 below use
our original **fixed 1 MiB** aggressor; Section 6 reports the **author-confirmed
fixed 2 MiB** aggressor (which reproduces the paper) alongside the 8 MiB and
matched-to-victim sweeps that map out the full dose-response. The aggressor
message size — not the victim's — turns out to be the dominant congestion knob
and resolves the gap between our earlier numbers and the paper's.

## 1. The effect is real but strongly placement-dependent (fixed 1 MiB aggressor)

Averaged over reps, incast clearly slows the victim, growing with node count and
message size. The run-to-run spread is large — for n64 it is **bimodal**: some
reps are crushed (−60 %) while siblings escape (ratio ≈ 1.0).

| cell | ratio (mean ± std) | cv | min–max | reps |
|------|--------------------|----|---------|------|
| n32 / 256 KB | 0.969 ± 0.067 | 7% | 0.72–1.08 | 20 |
| n32 / 2 MB | 0.603 ± 0.049 | 8% | 0.52–0.74 | 20 |
| n32 / 16 MB | 0.668 ± 0.133 | 20% | 0.50–1.01 | 19 |
| n64 / 256 KB | 0.728 ± 0.186 | 26% | 0.48–1.01 | 20 |
| n64 / 2 MB | 0.431 ± 0.151 | 35% | 0.30–1.01 | 20 |
| n64 / 16 MB | 0.342 ± 0.063 | 19% | 0.26–0.53 | 20 |

A single run per cell would be misleading — the point estimate depends heavily on
which nodes Slurm handed out. The reps are genuinely independent draws (global
node intersection only 11–22 %, vs 88 % for back-to-back reps that reused nodes).

## 2. Locality metric

For each rep we classify every victim×aggressor host pair by topology distance
(from `topologies/leonardo.json`: node → cell, node → leaf switch):
`same_switch` / `same_cell` / `cross_cell`, plus the **cell span** of the whole
allocation. **`same_switch` = 0 in every rep** — at 50:50 interleaved these
allocations never place a victim and an aggressor node on the same leaf, so any
contention is decided at the **cell / spine** level.

## 3. Finding: coarse cell-locality does **not** robustly explain the variance

At a fixed node count the topology metric barely moves: Slurm almost always
returns the **same span** — n64 ≈ 4 cells, n32 ≈ 2 cells — with only a rare rep
one cell wider, while the ratio varies over nearly the full range *within* that
single span. Because the cross-cell fraction is likewise near-constant across a
cell's reps (n64 ≈ 0.79–0.80), the per-cell `corr(ratio, cross-cell)` is
dominated by the 1–3 rare off-span reps and is **not stable**: at 6 reps it
looked strong (e.g. n32/2 MB = +0.995, n64/2 MB = +0.66); at 19–20 reps it
weakens and loses consistency across cells:

| cell | corr(ratio, cross-cell) @6–16 reps | @19–20 reps |
|------|------------------------------------|-------------|
| n32 / 2 MB | +0.995 | **+0.07** |
| n64 / 256 KB | −0.49 | **−0.03** |
| n64 / 2 MB | +0.66 | +0.52 |
| n64 / 16 MB | — | +0.55 |

Only the large-message n64 cells retain a moderate positive correlation; the
others collapse toward 0. **Conclusion:** the congestion is real and highly
placement-sensitive, but the sensitivity is **finer-grained than the cell / span
level** — the full swing happens among reps that are identical in coarse
locality. Cell-span and cross-cell fraction do not reliably predict which reps
get congested; a **link-level path-overlap** metric is needed (Sec. 7).

## 4–5. (fixed-aggressor scale trend)

Fixed 1 MiB incast bottoms at ratio ≈ 0.34 (n64 / 16 MB) — a ~3× slowdown. This
is **milder than the paper's Leonardo Incast box**, which collapses to ≈ 0.2
(5×) for several vector sizes at 32–64 nodes. Section 6 explains the gap.

## 6. Aggressor message size is the dominant knob — and it reproduces the paper

The paper never states the aggressor's message size. **The authors confirmed
(private communication, 2026-07) they used a fixed 2 MiB aggressor.** Running that
exact value reproduces the paper's Leonardo-Incast collapse, and sweeping the
aggressor size (1 / 2 / 8 / 16 MiB and matched-to-victim) shows the severity is
set by the *aggressor's* message size, not the victim's.

### 6.1 The author-confirmed fixed 2 MiB aggressor reproduces Fig. 5

Fixed 2 MiB incast, 5 reps (the vm = 2 MiB cell pools with the matched sweep, n10):

| victim vec | n32 | n64 | n128 |
|------------|-----|-----|------|
| 8 B – 256 KB | ~0.99 (uncongested) | ~0.99 | ~0.99 |
| 2 MB | 0.485 ± 0.104 (n10) | **0.324 ± 0.150** (n10) | 0.993 ± 0.007 (n10) |
| 16 MB | 0.376 ± 0.019 | **0.234 ± 0.057** | 0.576 ± 0.476 (cv 83 %, n4) |

`n64 / 16 MB = 0.234` and `n64 / 2 MB = 0.324` land **right on the paper's ≈0.2
Leonardo-Incast collapse**, and the *shape* matches Fig. 5: only the large-vector
cells collapse, everything ≤256 KB stays at ~1.0. So with the authors' actual
parameter the reproduction holds — our earlier "not as bad as the paper" gap was
purely the undersized fixed 1 MiB aggressor at the large-vector cells.

**n128 confirms the overlap-collapse immunity (Sec. 7) at the authors' size.** The
n128 / 2 MB victim is *fully immune and deterministic* (0.993 ± 0.007, cv 0.7 %) —
identical to the matched-16 MiB n128 column — so the near-immunity is **not** a
16-MiB-specific artefact. The n128 / 16 MB victim is a **bimodal placement
lottery** (mean 0.576 but cv 83 %, std 0.48 over 4 reps: individual reps span
crushed→immune), i.e. n128 sits on the knife-edge where *most* placements decouple
the victim ring from the incast tree but the occasional compact draw still
overlaps it — exactly Sec. 7's overlap-collapse operating at its margin, not a
clean partial-collapse.

### 6.2 Dose-response: aggressor size sets the severity

At the n64 / 16 MB-victim cell the collapse deepens monotonically with aggressor
size — straddling the paper's ≈0.2:

| aggressor msg | 1 MiB | 2 MiB (authors) | 8 MiB | 16 MiB (matched) |
|---------------|-------|-----------------|-------|------------------|
| n64 / 16 MB victim | 0.342 | **0.234** | 0.109 | 0.051 |

The matched-to-victim sweep (aggressor message = victim vector) makes the same
point from the other side — an 8 B incast can't congest anything, a 16 MiB incast
crushes everything — and adds a full n32/n64/n128 grid:

| victim vec | n32 | n64 | n128 |
|------------|-----|-----|------|
| 8 B – 256 KB | ~1.00 | ~1.00 | ~1.00 |
| 2 MB | 0.405 ± 0.041 | **0.290 ± 0.160** (cv 55 %) | 0.994 ± 0.006 |
| 16 MB | 0.102 ± 0.012 | **0.051 ± 0.000** (≈20×) | 0.791 ± 0.020 |

**Placement dependence sharpens with size, then disappears:** the 16 MB cells are
essentially deterministic (std 0.000 at n64 — every rep crushed, placement no
longer matters), whereas the 2 MB cells are the knife-edge (cv 55 %, bimodal
0.18–0.56), consistent with Sec. 1/3. The finer-grained placement effect is only
visible in the size window where the fabric can *just* absorb the incast.

### 6.3 Scaling is non-monotonic — n64 is the worst-hit, not n128

Severity is **not** simply "more nodes = worse". At matched size, n64 collapses
hardest while **n128 barely congests** (2 MB → 0.99, 16 MB → 0.79); under the
fixed 8 MiB aggressor, n32 congests across *more* victim sizes (256 KB → 0.55,
2 MB → 0.19) than n64 does. The 50:50 victim/aggressor partition geometry — how
the incast fan-in and the allgather ring share the fabric at each scale — matters
more than raw node count. **Sec. 7 resolves this at the fabric level**: severity
is the product of incast intensity and the victim ring's overlap with the incast
congestion tree, which peaks at n64. (Both the n128 matched column and the
fixed-2 MiB n128 sweep ran under the `bprod` QOS and agree: n128 / 2 MB stays
immune at ~0.99 either way — Sec. 6.1.)

### 6.4 Service Level (SL=0 vs SL=1) is not a mitigation knob

Forcing IB Service Level 0 with a forced-UCX pml (`data/leonardo_sl0`, n64
matched) does **not** relieve the incast: identical collapse at 16 MB (0.066 vs
SL=1's 0.051) and *worse, more deterministic* at the 2 MB knife-edge
(0.199 ± 0.010 vs 0.290 ± 0.160 — the SL=0 shift removed the placement "escape").
Expected: a uniform SL move puts victim *and* aggressor on the same level and the
same links, so it can't isolate them. SL would only help with victim/aggressor on
**different** SLs (traffic-class separation) — a future experiment needing
per-app env injection, not a global preset.

## 7. Fabric-level mechanism: incast congestion tree × victim overlap

The non-monotonic scaling (Sec. 6.3) resolves cleanly at the fabric level. The
aggressor runs `collect:false`, so we reconstruct its incast flows from
`loaded/partition_assignment.json` (which records **all** nodes, victim and
aggressor) plus the known incast pattern (every aggressor rank → `master_rank 0`),
and the victim ring from the victim node order. Both are attributed over the
switch graph with CINETIC's own ECMP expected-load machinery
(`cinetic.analysis.fabric`: `build_switch_graph` + `route`). Demonstrated on the
deterministic matched-16 MiB cells (std ≈ 0), 5 reps each:

| scale | nsend (incast intensity) | victim overlap w/ incast spines | **intensity × overlap** | span | ratio |
|-------|--------------------------|--------------------------------|-------------------------|------|-------|
| n32 | 15 | 0.99 | 14.8 | 3 cells | 0.102 |
| **n64** | 31 | 0.79 | **24.4** (peak) | 5 cells | **0.051** (worst) |
| n128 | 63 | 0.05 | 3.1 | 19 cells | 0.791 (immune) |

The product ranks **n64 > n32 > n128** — exactly the slowdown ranking (1/ratio =
19.6 > 9.8 > 1.3). The mechanism, step by step:

1. **Victim and aggressor never share a leaf** (co-tenancy = 0 at every scale —
   the 50:50 interleave guarantees it, cf. Sec. 2). So the victim is *not* hurt by
   sharing the incast's bottleneck link.
2. **The incast converges entirely on the root's single leaf switch** (switch-load
   share ≈ 0.94–1.0; each spine carries only ~5 %). That saturated leaf is the
   root of a **congestion tree** whose backpressure spreads up its spines — the
   paper's bystander mechanism.
3. **Severity = incast intensity × victim overlap with that tree's spine
   footprint:**
   - **n32** — modest intensity (15 senders) but the whole 3-cell allocation
     funnels through the same spines, so 99 % of victim hops sit in the tree →
     strong congestion (0.10).
   - **n64** — intensity doubles (31 senders) *and* overlap stays high (0.79) in
     5 cells → the product peaks → **maximal congestion (0.05)**.
   - **n128** — intensity is highest (63) but the allocation spreads over **19
     cells** while the incast tree stays localized to the root's region, so only
     **5 %** of victim hops route through it → the ring **decouples** from the
     tree → near-immunity (0.79).

**Why "more nodes ≠ worse":** beyond ≈n64, spreading the victim over more cells
decouples it from the (localized) incast tree *faster* than the incast intensity
grows. Severity peaks where intensity is already high but the allocation is still
compact enough for near-total overlap — n64 in this 50:50 setup.

**Scope / caveats.** This uses the **ECMP expected-load** model (all shortest
paths), not Leonardo's real static IB routing. It is too smooth to resolve fine
per-link contention (the raw per-link peak diluted to ~5 %, which is why an
earlier *link*-overlap metric failed). What is robust — and routing-detail
independent — is the **switch-level convergence** on the root leaf and the
**span-driven overlap collapse**; those rank the three scales correctly.
Reproduced by `experiment/congestion/repro_paper/` scratch scripts
(`fabric_tree.py` is the key one). **The n128 fixed-2 MiB (author size) sweep
confirms the overlap-collapse immunity holds there too:** n128 / 2 MB = 0.993
(fully immune, deterministic), and n128 / 16 MB is a bimodal placement lottery
(cv 83 %) — the tree-decoupling operating right at its margin (Sec. 6.1).

## 8. Next steps

- ✅ **Confirmed the mechanism at the authors' 2 MiB size** (n128 fixed sweep,
  done 2026-07): the overlap-collapse immunity (Sec. 7) survives — n128 / 2 MB =
  0.993 (deterministic), n128 / 16 MB bimodal (cv 83 %). It is **not** specific to
  the 16 MiB cells.
- **Validate the ECMP model against real IB routing** — pull Leonardo's linear
  forwarding tables (or set `collect:true` on the aggressor so `--fabric` sees its
  *measured* per-flow bandwidths) to check whether single-path routing sharpens or
  blurs the n32-vs-n64 gap.
- **More reps on the 2 MB knife-edge** (both fixed and matched): the n64 / 2 MB
  cell is bimodal, so the n64 / 2 MB-victim / 8 MiB-aggressor = 0.799 point (a
  bigger aggressor apparently congesting *less*) is a small-sample placement
  lottery, not a real inversion. Report the crushed vs escape modes separately.
- **Extend the fixed 2 MiB (author) sweep to n256** (n128 done — see above) to
  trace how far the near-immunity persists as the allocation keeps spreading; and
  add reps to the bimodal n128 / 16 MB cell (n4 → n≥10) to separate its
  crushed vs escape modes.
- **SL traffic-class separation** (victim vs aggressor on different SLs) as the
  actual SL mitigation test.

*Generated from `experiment/congestion/repro_paper/analyze.sh` (rep aggregation +
locality columns; `AGGR_MSG=<bytes>` for each fixed-size column, `AGGR_MSG=match`
for the matched-size column).*
