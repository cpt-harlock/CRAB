# Incast congestion on Leonardo: aggressor message size & topology placement

**Date:** 2026-07-03 · **Status:** fixed-size cells at 19–20 reps; matched-size
sweep n64 complete (5 reps), n32/n128 in flight.
**Data:** `data/leonardo/_sweep_analysis/repro_paper/congestion_agtr_inc_{heatmap,rep_stats,rep_detail}.csv`
(fixed 1 MiB aggressor) and `..._ammatch_{heatmap,rep_stats}.csv` (aggressor
message = victim vector size).

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
our original **fixed 1 MiB** aggressor; Section 6 sweeps the alternative
hypothesis that the aggressor scales with the victim's vector size (the heatmap
y-axis), which turns out to resolve the gap between our numbers and the paper's.

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

## 6. Aggressor message size is the dominant knob — and resolves the paper gap

The paper never specifies the aggressor's message size. Testing the hypothesis
that it **matches the victim vector size** (the heatmap y-axis) changes the
picture completely. n64 incast, aggressor message = victim vector, 5 reps:

| victim vec | fixed 1 MiB aggressor | **matched (aggr = victim)** |
|------------|-----------------------|-----------------------------|
| 8 B – 32 KB | 0.97–1.00 | 0.99–1.00 |
| 256 KB | 0.728 ± 0.186 | **1.004 ± 0.012** |
| 2 MB | 0.431 ± 0.151 | **0.290 ± 0.160** (cv 55 %) |
| 16 MB | 0.342 ± 0.063 | **0.051 ± 0.000** (≈20× slowdown) |

The aggressor's message size — not the victim's — sets the severity, with a
crossover at the old fixed 1 MiB point:

- **Below 1 MiB** the matched aggressor is *smaller*, so it congests *less*:
  256 KB goes 0.728 → **1.00** (congestion vanishes).
- **Above 1 MiB** it is *larger*, so it congests *far more*: 16 MB goes
  0.342 → **0.051**.

This **brackets the paper's ≈0.2 collapse** (2 MB = 0.29, 16 MB = 0.05) and shows
our earlier "not as bad as the paper" result was an artifact of an undersized
fixed aggressor at the large-vector cells. The matched-column *shape* also fits
the paper's qualitative description — collapse concentrated at large vectors,
small-vector cells unaffected — which is exactly what "aggressor scales with the
y-axis" predicts (an 8 B incast cannot congest anything).

**Placement dependence sharpens with size, then disappears:** 16 MB matched is
essentially deterministic (std 0.000 — every rep crushed ~20×, placement no
longer matters), whereas 2 MB matched is the knife-edge (cv 55 %, 0.18–0.56),
consistent with the bimodal placement sensitivity of Sec. 1/3. So the finer-grained
placement effect is visible only in a size window where the fabric can *just*
absorb the incast; below it there is no congestion, above it the incast dominates
regardless of where nodes land.

## 7. Next steps

- Complete the matched sweep at **n32 / n128** (in flight) to see whether the
  crossover and the 16 MB determinism hold across scale; extend to n256 when the
  big-QOS allocation frees.
- Replace the cell-span axis with a **fabric-level metric** (existing `--fabric`
  / `--blame` machinery): correlate the victim ratio with *shared-link load*
  between the incast root's flows and the victim ring — the hypothesis coarse
  locality can't test, most relevant in the 2 MB knife-edge window.
- Report the two n64 modes separately (crushed vs escape) where the cell is
  bimodal (2 MB, both fixed and matched).

*Generated from `experiment/congestion/repro_paper/analyze.sh` (rep aggregation +
locality columns; `AGGR_MSG=match` for the matched-size column).*
