# PLAN — Experiments Analysis Rework (v3)

Reworks and extends the result analysis (`src/cinetic/analysis/`, designed in
`PLAN_RESULT_ANALYZER.md`) from a **single-experiment tournament reporter** into
a **congestion-aware, multi-experiment, multi-benchmark** analysis layer with
**fabric-level (link/switch) diagnosis**.

> **v3 — revised for output standardization.** This plan now builds on
> `PLAN_OUTPUT_STANDARDIZATION.md` (M1–M6 **implemented**): every collecting
> benchmark — point-to-point *and* collective — emits the **same** per-node CSV
> schema, files are **namespaced per app**, and the analyzer already parses the
> three benchmark *kinds* (pairwise / collective / directed) and analyzes each
> app independently. That work delivered most of what the old v2 "backends"
> layer was for, so the architecture below collapses the per-benchmark parser
> split and refocuses the rework on the **semantic layer** (roles, congestion,
> comparison, fabric) that standardization does *not* provide.

`PLAN_RESULT_ANALYZER.md` remains the reference for the pairwise math core.
Statuses below: ☐ todo, ◐ partial (exists), ✔ done.

---

## 0. Why

CINETIC's stated purpose is **checking interconnect health under realistic load**
— victims vs. aggressors, the congestion co-running apps inflict on each other.
After standardization the analyzer can read every benchmark uniformly, but it
still cannot express the *congestion story*: it

- treats **one app's output in isolation** (no baseline-vs-loaded comparison),
  even though a multi-app experiment now produces one `analysis/app_<id>/` per
  app side by side;
- has **no notion of app roles** (victim / aggressor / timed) — the per-app
  grouping knows *which app id* produced the data, but not *what that app was
  for*, which the config already encodes (`end=""` victim, `end="f"` aggressor,
  `end="<N>"` timed; `start`/`partition` too);
- never localizes congestion to **switches or links** (only the 3-level
  `Locality` / comm-span class).

The four goals (all in scope, staged): **(1) congestion impact**,
**(2) cross-experiment comparison**, **(3) more benchmarks**, **(4) deeper
topology/link analysis**.

---

## 1. Current state (what we build on)

```
src/cinetic/analysis/
  parse.py       ◐ node_app<id>_*.csv -> Dataset(Match[]) ; tolerant, (op,comm,peer,phase) blocking
                   ✔ per-app grouping (app_ids_in_dir / parse_exp_dir(app_id))
                   ✔ comm_manifest_app<id>.csv -> Dataset.comms ; is_collective
  params.py      ◐ resolve msg_size/window/granularity (CLI/stdout/config/defaults)
  metrics.py     ◐ bandwidth/latency from per-sample bytes/ops basis; robust stats
                   ✔ kind-aware: pairwise (merge) / collective (comm-span) / directed (per-hop)
  topo.py        ◐ FQDN->short normalization, Locality lookup ; ✔ comm_span(members)
  outliers.py    ◐ under-performer flagging (robust z / frac / small-N guard)
  report_text.py ◐ report.txt / peer_profiles.txt / per_round_per_node.txt / summary.json
                   ✔ kind-aware sections (by-distance / by-comm-span / directed)
  report_plot.py ◐ matplotlib figures (by-locality, by-config, CDF, ...)
  cli.py         ◐ `cinetic analyze <dir>` ; ✔ per-app loop -> analysis/app_<id>/
```

**What standardization already gave us (don't rebuild):**

- One uniform per-node format for *all* collecting blink benchmarks
  (`node_app<id>_<host>_rank<r>.csv`, schema
  `node,rank,op,comm,sample,phase,peer_node,peer_rank,bytes,ops,duration_s`),
  with `bytes`/`ops` carrying the bandwidth/latency basis so `metrics.py`
  computes both uniformly regardless of op.
- The **kind** abstraction: `metrics.analyze()` returns `Analysis.kind ∈
  {pairwise, collective, directed}` with `bw_by_label`/`lat_by_label` keyed by
  the right topology axis (locality for pairwise/directed, comm-span for
  collective) — so "more benchmarks" (goal 3) is largely *done* for blink.
- **Per-app separation**: files grouped by `app<id>_` prefix; each app analyzed
  independently into its own subdir. The hook the semantic layer needs (app id →
  output) already exists.
- **`collect` gating**: only `collect:true` apps emit per-node output
  (`CINETIC_COLLECT`); the writer is also keyed by `CINETIC_APP_ID`.

**Key remaining limitation:** the per-app `Analysis` is still **role-blind** — it
knows the app id and the benchmark kind, but not whether the app was a victim or
an aggressor, nor what else ran alongside it. The rework adds that semantic layer
and the comparison/fabric machinery; the per-pairing math, robust stats,
topology normalization, and outlier logic are reused as-is.

---

## 2. Recommended rework depth

**Moderate refactor, not a rewrite** — and *smaller* than v2 anticipated, because
standardization absorbed the per-benchmark parsing. Introduce three new layers
and keep every existing module as a reusable component:

1. **`context.py` — ExperimentContext** (new): the missing semantic layer. Reads
   the run's `config.json` + `environment.json` and maps each **app id** (the
   same id the analyzer already groups files by) to its **role**, partition,
   start/end, nodelist, system, and resolved params. Ties the existing per-app
   `Analysis` objects to *what each app was*.
2. **`compare.py` — Comparison engine** (new): aligns two or more analyzed apps
   (within or across runs) by node / locality / comm-span / link and computes
   **deltas** (baseline-vs-loaded and cross-experiment machinery).
3. **`fabric.py` — link/switch attribution** (new): path candidate sets +
   per-switch/per-link load, for goal 4.

Plus `congestion.py` orchestrating goal 1 on top of (1)+(2)(+3).

Everything funnels into one **report model** (`AnalysisResult` + new
`CongestionResult`/`ComparisonResult`) consumed by `report_text`/`report_plot`,
so outputs stay uniform.

**What v2 had that we now drop / shrink:**

- **No `backends/` package.** v2 planned a `tournament` vs `blink_generic`
  parser split; standardization made the per-node reader the single uniform
  path, so there is nothing to dispatch between for blink. Goal 3 is re-scoped
  in §3.2 to the genuine residual: benchmarks that *don't* emit standardized
  output. That escape hatch is a thin optional reader, not a plugin framework.

Rationale: the per-pairing bandwidth/latency math, robust stats, topology
normalization, kind detection, and outlier logic are correct and verified
against real runs; the gap is purely *semantic* (roles, comparison, link paths).
We add structure around the good core rather than disturb it.

---

## 3. New architecture

```
src/cinetic/analysis/
  context.py          ☐ ExperimentContext: config.json/environment.json -> apps+roles+params
  model.py            ☐ shared result dataclasses (AnalysisResult, CongestionResult, ...)
  congestion.py       ☐ victim/aggressor impact within/across runs (goal 1)
  compare.py          ☐ align + delta across analyzed apps/runs (goal 2)
  fabric.py           ☐ path estimation + per-switch/per-link load attribution (goal 4)
  generic_reader.py   ☐ OPTIONAL: data_app_<id>.csv for non-instrumented apps (goal 3 residual)
  parse.py params.py metrics.py topo.py outliers.py     ◐ reused (standardization-ready)
  report_text.py report_plot.py                          ◐ extended
  cli.py                                                 ◐ subcommands added
```

### 3.1 ExperimentContext (`context.py`) — goal 1 foundation

A **run dir** holds `config.json`, `environment.json`, and ≥1 `<exp_id>/`
subdir. For each experiment, parse `config["experiments"][exp_id]["apps"]`; the
app key **is** the `<id>` already used to namespace `node_app<id>_*.csv` and to
name the `analysis/app_<id>/` subdirs, so the context joins to the existing
per-app analyses directly:

```python
@dataclass
class AppInfo:
    app_id: str
    path: str            # wrapper, e.g. "tournament_nb.py" / "a2a_b.py"
    args: str
    role: Role           # VICTIM | AGGRESSOR | TIMED  (from `end`)
    partition: int
    start: str           # "0" | "<N>" | "s<id>"
    collect: bool        # emitted standardized per-node output? (gates analysis)
    output_kind: str     # "standardized" (node_app<id>_*.csv) | "generic" (data_app_<id>.csv) | "none"

@dataclass
class ExperimentContext:
    exp_id: str
    exp_dir: str
    system: str          # environment.json CINETIC_SYSTEM
    apps: list[AppInfo]
    global_options: dict
    @property
    def victims(self): ...
    @property
    def aggressors(self): ...
    @property
    def is_loaded(self): return bool(self.aggressors)   # baseline vs loaded
```

Role mapping (from CLAUDE.md config semantics): `end == ""` → **VICTIM**,
`end == "f"` → **AGGRESSOR**, numeric `end` → **TIMED** (treat as aggressor-like
for impact unless flagged). An experiment with **no aggressors is a baseline**
candidate; with aggressors it's **loaded**.

`output_kind` is derived from the files actually present for that app id:
`node_app<id>_*.csv` → `standardized` (the normal path); else `data_app_<id>.csv`
→ `generic` (§3.2); else `none`. **Collect interaction:** only `collect:true`
apps emit standardized output, so a `collect:false` aggressor is `none` — its
*footprint* is then inferred indirectly (§4), not measured per-node. To get a
measured aggressor footprint + fabric load, run aggressors with `collect:true`
(they now emit the same uniform output as victims).

This is what lets a victim's analysis be read *in the context of* the aggressor
co-running in the same experiment.

### 3.2 More benchmarks (goal 3) — mostly done; residual reader

Standardization already covers every blink benchmark wired to `results.h`
(pairwise, allreduce, alltoall, ring allgather). Extending coverage is now the
**cheap** path documented in `PLAN_OUTPUT_STANDARDIZATION.md` ("writing a
benchmark that emits standardized results"): include `results.h`, fill the
`bytes`/`ops` bases, call the writer. **Prefer this** for any new benchmark — it
drops straight into the uniform pipeline with full topology analysis.

The genuine residual is benchmarks that **cannot** be instrumented (e.g.
externally-built apps: miniFE, graph500, AMG) and only produce
`data_app_<id>.csv` via their wrapper's `read_data`. For those, an **optional**
`generic_reader.py` produces a degraded `AnalysisResult`: node-level metric
series + totals from the wrapper's `metadata` (name/unit), **no** per-pairing /
topology view (the data isn't pairwise). Enough for aggressor throughput and
victim/aggressor comparison; flagged as topology-blind. This is a single small
reader, not a plugin registry.

### 3.3 Result model (`model.py`)

`AnalysisResult` generalizes today's `metrics.analyze()` return — **keep the
existing fields** (`kind`, `pairings`, `bw_by_label`, `lat_by_label`,
`comm_span`, node/round/overall stats) so `report_text`/`report_plot` keep
working — plus: `app_id`, `role`, `output_kind`, and a `context` back-reference.
New `CongestionResult` and `ComparisonResult` defined in §4 / §5.

---

## 4. Congestion impact (goal 1) — `congestion.py`

Quantify how aggressors degrade victims. Two comparison axes; support both:

- **A. Cross-experiment baseline** (preferred, cleanest): a run (or a
  user-pointed dir) contains a **baseline** experiment (victims only) and a
  **loaded** experiment (same victims + aggressors). Compare the victim's
  metrics between the two. Auto-pair by victim app `path` + node set; let
  `--baseline <exp_id|dir>` override.
- **B. In-experiment** (when no separate baseline exists): characterize the
  victim under load only, and compare **per topology axis** — for pairwise
  victims, victim pairings that share a switch/cell with aggressor traffic vs
  those that don't; for collective victims, the per-comm-span buckets — a weaker,
  self-contained signal. Uses §6 fabric attribution.

Both axes consume the **already-computed per-app `Analysis`** objects (victim and
aggressor each have one under `analysis/app_<id>/`); congestion just aligns and
diffs them — it does not re-parse or recompute bandwidth.

Outputs (`CongestionResult`):
- victim **bandwidth/latency degradation %** = `(loaded − baseline)/baseline`,
  per-node and overall, with robust CIs where sample count allows;
- **aggressor footprint**: aggressor throughput + which switches/cells/links it
  loaded (via §6) — available only for `collect:true` aggressors (else inferred);
- a **congestion correlation**: do victim pairings/comm-spans that share fabric
  with aggressor traffic degrade more than those that don't? (the headline);
- honesty notes: per-node files hold only the **final run**, so degradation is a
  single-run point estimate — flag low confidence at small N (reuse the §5 guard
  from `PLAN_RESULT_ANALYZER.md`).

---

## 5. Cross-experiment comparison (goal 2) — `compare.py`

Compare N analyzed apps/datasets (different runs, configs, or dates). Generic;
goal-1 baseline-vs-loaded is its special case.

- **Alignment**: by node identity (short hostname) and by topology label
  (`Locality` class for pairwise/directed, comm-span for collective); optionally
  by `(app_id, role)`. Use the **intersection** of node sets, and report nodes
  present in only some runs. Only compare apps of the **same kind** (don't diff a
  pairwise bandwidth against a collective busbw); warn and skip otherwise.
- **Deltas**: per-node and per-label bandwidth/latency differences and ratios,
  with a robust two-sample comparison where enough samples exist (note the
  single-final-run caveat otherwise).
- **Trend**: when datasets carry a natural order (timestamp from dir name, or a
  `--label`/`--x` axis), emit a time/parameter series (regression slope) — useful
  for "is the fabric degrading over weeks" health tracking.
- Differing benchmark params across runs → compare on the **`--bw-relative`**
  basis (BW normalized to each run's own median) so param mismatch can't
  masquerade as a real difference. The per-sample `bytes`/`ops` basis recorded by
  standardization makes this robust: absolute busbw is comparable across ops, and
  relative mode neutralizes msg-size/window differences.

`ComparisonResult`: aligned tables + delta matrices feeding new report sections
and overlay plots.

---

## 6. Deeper topology / link analysis (goal 4) — `fabric.py`

Move from "which **node** is slow" to "which **switch/link** is congested".

- **Hop-count distance**: extend beyond the 3-level enum. Build a graph from
  `cinetic.topology.model` (leaf↔spine↔core edges) and compute shortest-path hop
  counts between endpoints. The current model has `Switch (leaf/spine)`, `Cell`,
  `Node.switches`; add a graph view here (don't bloat the core model).
- **Path estimation**: for each *link* — a pairwise pairing A↔B, a directed ring
  hop A→B, **or** an expanded collective (use `comm_manifest_app<id>.csv` to
  enumerate the comm's member pairs) — estimate the set of switches/links on its
  route: `leaf(A) → spine(s) → leaf(B)` within a cell, or via core across cells.
  Fat-tree routing is multipath/non-deterministic, so treat this as the
  **candidate link set** (and say so) — enough to attribute *load*, not to claim
  the exact path. The manifest is what makes collective traffic attributable
  despite having no per-peer rows.
- **Per-link / per-switch load attribution**: tally, across all links (victim
  *and* `collect:true` aggressor, weighted by their bandwidth), how much traffic
  each candidate link/switch carries. Rank **hotspots**; cross-reference with
  degraded victim links (ties §4's congestion correlation to physical links).
- **Plots**: N×N pairwise bandwidth **heatmap** (deferred in v1, promote here);
  per-switch/per-link load bar chart; optional `--topo-graph` colored by load.

Guard: if <80% of hosts resolve in the topology (wrong-topology guard from v1),
skip fabric attribution and warn.

---

## 7. CLI / UX

Keep `cinetic analyze <dir>` **backward compatible** (today's per-app report
still works, including the per-app subdirs standardization introduced). Add
subcommands/flags:

```
cinetic analyze <run|exp dir>            # auto: per-exp, per-app, role-aware report (default)
cinetic analyze ... --baseline <exp|dir> # force the congestion baseline (goal 1)
cinetic analyze compare <dirA> <dirB>... # cross-experiment comparison (goal 2)
    [--label L ...] [--x <key>] [--bw-relative]
cinetic analyze ... --fabric             # enable link/switch attribution (goal 4)
cinetic analyze ... --hotspots N         # top-N congested links/switches
```

Existing flags (`--topology --msg-size --window --granularity --outdir --json
--show --no-plots --detail --topo-graph --slow-k --slow-frac --min-nodes`) keep
their meaning. Implementation: extend `cli.py`'s argparse; dispatch `compare`
explicitly; everything else flows through the role-aware default path, which
already loops per app — congestion/fabric hang off that loop.

---

## 8. Outputs (additions)

- **Role-aware report**: existing per-app report, now headed with each
  experiment's victims/aggressors and whether it's baseline or loaded; each
  app's role printed alongside its `app_<id>` banner.
- `congestion.txt` / section: degradation table + congestion correlation (§4).
- `comparison.txt` + `comparison.json`: aligned deltas / trend (§5).
- `fabric.txt`: per-switch/per-link hotspot ranking (§6).
- New figures: degradation bar (baseline vs loaded overlay), pairwise heatmap,
  per-link load chart, trend line. All under `<dir>/analysis/` (per-app subdirs
  for per-app artifacts; run-level artifacts like comparison at the run root).
- `summary.json` gains `role`, `congestion`, `fabric`, `comparison` blocks
  (additive; existing keys — incl. `kind`, `comm_span` — unchanged).

---

## 9. Milestones

1. **Context layer** (`context.py`, `model.py`): parse config/environment, map
   app ids → roles, join to the existing per-app analyses; thread an
   `ExperimentContext` through `cli.py`; report now prints victim/aggressor roles
   per app. *No math change.* Develop against a real run with a victim+aggressor
   experiment (both `collect:true`).
2. **Congestion** (`congestion.py`): baseline-vs-loaded degradation (axis A) by
   diffing per-app analyses; single-run caveats; report section + overlay plot.
   This is reachable right after M1 because the per-app analyses already exist.
3. **Fabric** (`fabric.py`): hop-count + path candidate sets (pairwise, directed,
   and manifest-expanded collective) + per-link load + hotspot table + heatmap.
   Enables axis-B in-experiment congestion correlation.
4. **Compare** (`compare.py`): cross-experiment alignment (same-kind), deltas,
   `--bw-relative`, trend; `compare` subcommand.
5. **Generic reader** (`generic_reader.py`, *optional / as needed*): topology-blind
   `data_app_<id>.csv` support for non-instrumentable apps. Skip if all relevant
   benchmarks can instead be wired to `results.h`.
6. **Polish**: docs in `CLAUDE.md`, summary.json schema, end-to-end smoke test on
   a fresh multi-experiment Leonardo run.

**MVP cut:** milestones 1–2 deliver the core "how much do aggressors hurt
victims" answer — and are now cheaper, since standardization already produces the
per-app, multi-benchmark analyses they diff. Fabric (3) and compare (4) extend it.

---

## 10. Compatibility & risks

- **Backward compat**: `cinetic analyze <single exp dir>` with no config.json
  (e.g. a bare exp dir) must still work — `context.py` degrades to an anonymous
  single-app assumption when config/environment are absent. Legacy un-prefixed
  `node_*.csv` dumps still parse (as one app) and report exactly as before.
- **`collect` gates measurement**: a `collect:false` aggressor emits no per-node
  output, so its footprint/fabric load is inferred, not measured. Recommend
  `collect:true` for aggressors when a measured footprint is wanted; surface the
  distinction in the report.
- **node_*.csv = final run only** (write mode `"w"`): all congestion/comparison
  numbers are single-run point estimates; surface this everywhere (don't imply
  statistical power we don't have at small N).
- **Cross-kind comparisons are invalid**: never diff a pairwise bandwidth against
  a collective busbw or a directed per-link rate; align only within a kind.
- **Path estimation is approximate** (multipath fat-tree): attribute *load to
  candidate links*, never claim an exact route. Keep it clearly labeled.
- **Reuse, don't fork**: `parse.py`/`metrics.py`/`topo.py`/`outliers.py` stay the
  single source of truth; new modules orchestrate, they don't reimplement. In
  particular do not re-derive bandwidth — consume the per-app `Analysis`.

---

## 11. Open questions (assumptions if unanswered)

- **Baseline discovery**: assume baseline = the run's victim-only experiment, or
  a user-pointed dir via `--baseline`. Is there a canonical preset layout that
  always pairs baseline+loaded experiments we can auto-detect? (If yes, encode it.)
- **Aggressor collection policy**: assume aggressors *can* be run `collect:true`
  so they emit standardized output (measured footprint + fabric load). Confirm
  whether the standard aggressor configs set `collect` — if they're typically
  `collect:false`, prioritize the inferred-footprint path in §4.
- **Routing model**: assume fat-tree leaf/spine/core with multipath; if Leonardo's
  exact routing (e.g. adaptive/static, known up/down paths) is available, the
  link attribution can be made exact instead of candidate-set.
- **`TIMED` apps** (`end="<N>"`): treated as aggressor-like for impact — confirm
  whether any victim ever uses a timed stop.
- **Collective congestion attribution**: with no per-peer rows, collective load
  is attributed by expanding the comm manifest into member pairs. Confirm this
  is acceptable (it assumes all-to-all-ish pressure on the comm's link set) or
  whether op-specific patterns (ring/recursive-doubling) should refine it.
```
