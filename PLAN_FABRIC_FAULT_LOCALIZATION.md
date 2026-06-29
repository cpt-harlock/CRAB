# PLAN — Fabric fault localization (slow → switch/link blame)

Status: **DONE** (M1–M4). Implemented in `analysis/blame.py` (+ `--blame` CLI,
`report_plot.plot_blame`, `tests/test_blame.py`). One design change vs the draft
below: Stage A keys on **intra-leaf flows** (a leaf is blamed when ≥2 of its
nodes are slow on same-switch traffic with no single common node) rather than the
residual-on-overall-median sketch — the residual cancels when a bad leaf depresses
its own nodes' medians, and intra-leaf flows cleanly separate leaf/node/spine.
The overall-median lone-node fallback was dropped (it re-introduced the spine
confounder for nodes with no same-switch peer, e.g. interleaved-partition victims).

Addresses gap #2 from the tournament
sanity-check review: today the fabric layer (`analysis/fabric.py`) tells you
which switch/link *carries* the most traffic (ECMP expected **load**); it does
**not** tell you which switch/link is *underperforming*. This plan adds the
inverse — **blame attribution**: take the *slow* flows and find the fabric
element common to them, so the sanity check can point at a bad switch/link, not
just a bad node.

## Relationship to existing code

Reuses, does not replace:
- `fabric.build_switch_graph(topo)` — switch adjacency graph.
- `fabric.route(graph, leaf_a, leaf_b, cache)` — ECMP shortest-path model:
  returns `switch_w` / `link_w` = fraction of shortest paths through each
  element (fractions at any cut sum to 1).
- `fabric.flows_from_analysis(an)` — per-flow `(host_a, host_b, bw)` for
  pairwise/directed/collective, already kind-aware.
- `topo.nodes[host].switches[0]` — a host's leaf switch (deterministic).
- `metrics.Analysis.node_bw_median` — per-node median bandwidth (the node-fault
  control).

New module `analysis/blame.py`; new flag `--blame` (parallel to `--fabric`);
outputs `fabric_blame.{txt,json}` + a plot. No benchmark change required — it
runs on existing tournament output.

## Signal model

Treat each flow's bandwidth as gated by the **worst** element on its path:

```
bw(a,b) ≈ line_rate · min( health[node_a], health[node_b],
                            health[leaf_a], health[leaf_b],
                            min over spine elements on the a→b routes )
```

where `health[e] ∈ (0,1]` (1 = nominal, <1 = degraded). A single bad element
drags down **every** flow that crosses it. Localization = invert this: find the
element(s) whose presence on a path best predicts low bandwidth.

Two regimes, very different tractability:

1. **Endpoint hop (node + leaf): deterministic.** A node's traffic always exits
   through its own NIC and its own leaf — no multipath ambiguity. This is where
   blame is reliable, and it is the common failure mode (a flaky port / cable /
   leaf ASIC). **Priority.**
2. **Core (spine switches + inter-switch links): multipath.** ECMP spreads a
   flow over *k* shortest paths, so one bad link carries only ~1/k of the flow
   and degrades aggregate bandwidth by at most ~1/k — diluted, weak signal for
   large k. Handle with the fractional ECMP model, report with explicit low
   confidence.

## Confounders (must be handled, or the tool lies)

- **Node fault masquerading as leaf fault.** One bad node makes all *its* flows
  slow → its leaf looks bad. Guard: only blame a leaf when **≥2 distinct nodes
  under it** are slow (a single-node signature is a node/NIC fault, already
  reported by `outliers`/peer-profile, not a switch fault).
- **Congestion vs fault.** A *loaded* fabric also slows flows. Blame is only
  meaningful on an **idle** run — exactly the tournament sanity-check use case.
  The report must state this assumption and refuse/flag if run on a `loaded`
  experiment (role context already knows this via `context.is_loaded`).
- **Single-run point estimate.** Same caveat the rest of the analyzer carries;
  state it.

## Method (v1 — robust + explainable, no fancy solver)

Per-flow **slowness** `s(a,b) = 1 − bw(a,b) / ref`, where `ref` = `--expected-bw`
nominal if given, else the run's global median bandwidth. `s ≈ 0` healthy, larger
= slower.

**Stage A — leaf-switch blame (deterministic):**
1. Map each flow to its endpoint leaves via `topo.nodes[h].switches[0]`.
2. For each leaf L, gather flows with ≥1 endpoint on L.
3. **Control for node fault:** for flow (a,b), use the residual
   `r(a,b) = s(a,b) − max(node_slowness[a], node_slowness[b])` where
   `node_slowness[x] = 1 − node_bw_median[x]/ref`. A leaf is suspect only if its
   flows are slow *beyond* what the endpoint nodes' own medians explain
   (residual > 0) AND ≥2 distinct slow nodes sit under it.
4. Compare distribution of flows touching L vs not (median slowness, effect
   size). Rank leaves; flag those above a slowness threshold with sufficient
   support.

**Stage B — spine link/switch blame (multipath):**
1. For each slow flow, distribute its slowness across candidate spine elements
   weighted by `route().link_w` / `switch_w` (the same ECMP fractions used for
   load).
2. Aggregate weighted slowness per element; normalize by total fractional
   traversals through it (so a heavily-used healthy link isn't penalized).
3. Flag elements with high mean slowness AND ≥N independent flows AND whose
   non-traversing flows are healthy (separability check).
4. Mark all Stage-B findings **low confidence** (ECMP dilution).

**Output ranking** per suspect element: kind (node/leaf/spine-switch/link),
n_flows, median bw of traversing vs non-traversing, residual effect size,
distinct nodes involved, confidence (high for leaf, low for spine).

## Outputs

- `fabric_blame.txt` — ranked suspects with the comparison columns above, the
  idle-run / single-run caveats, and the ECMP-dilution note.
- `fabric_blame.json` — machine-readable for trend tracking across sanity runs.
- `fabric_blame.png` — suspect elements by residual slowness (bar), traversing
  vs non-traversing bandwidth.
- CLI: `cinetic analyze <dir> --topology … --blame` (auto-skips with a warning
  when host resolution < `min_frac`, mirroring `--fabric`; warns when the
  experiment context is `loaded`).

## Validation (synthetic fixtures, no cluster needed)

Build node CSVs + a small topology where the rank→node→leaf placement is known,
then inject and confirm localization + no false positives:
1. **Healthy** — no element flagged.
2. **One slow node** — flagged as node fault, **not** its leaf.
3. **One slow leaf** (all nodes under it slow on every flow) — flagged as leaf,
   with ≥2 nodes cited; the nodes themselves not individually blamed beyond the
   leaf.
4. **One slow spine link** (only cross-cell flows routed through it slow) —
   flagged as link, low confidence; intra-cell flows healthy.
Add as standalone `tests/test_blame.py` (PASS/FAIL, no pytest), mirroring the
existing topology test style.

## Milestones

- **M1 ✅** — `blame.py`: slowness model + Stage A leaf/node blame (intra-leaf) +
  `fabric_blame.{txt,json}`; `--blame` CLI wiring.
- **M2 ✅** — Stage B spine link/switch blame via ECMP slowness distribution,
  low-confidence labelling.
- **M3 ✅** — confounder hardening: intra-leaf node-vs-leaf separation,
  `loaded`-experiment guard, confidence scoring; `plot_blame`.
- **M4 ✅** — synthetic validation `tests/test_blame.py` (4 scenarios) + CLAUDE.md.

## Known limitations (state in the report)

- ECMP dilution caps spine-element sensitivity; leaf/endpoint blame is the
  trustworthy part.
- Cannot separate two co-located bad elements, or a bad element from a bad node
  sharing the same leaf when only one node sits under it.
- Single-run point estimate; meaningful only on an idle fabric.
- A future benchmark enhancement (per-pair window-timeout counts in the node
  CSV) would give a second, independent blame signal — out of scope here.
```
