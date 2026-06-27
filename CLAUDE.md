# CINETIC — Claude Code Context

## What this project is

**CINETIC** (CINECA Network Integrity Checker) is an HPC framework for running, measuring, and analyzing MPI collective benchmarks on Slurm-managed clusters. Its primary use case is checking **interconnect health under realistic load** — i.e. the **network congestion** caused by co-running applications (victims vs. aggressors) on systems like Leonardo @ CINECA. (Forked from CRAB; see `PLAN_CINETIC_REFACTOR.md` for the rebrand/refactor.)

## How to run

```bash
# Unified CLI (preferred): `cinetic <command>`
cinetic run -p <preset> -c <config.json>   # orchestrate — submits a Slurm job
cinetic tui                                # interactive TUI
cinetic analyze <run_dir|exp_dir> --topology topologies/leonardo.json --json
cinetic topo <ibnetdiscover.txt> -o topology.json
cinetic plot                               # blink result plots

# Legacy entry scripts still work as thin shims:
python cli.py -p <preset> -c <config.json>
python tui.py
python tournament_analyzer.py <run_dir|exp_dir> --topology topologies/leonardo.json --json
```

`cinetic` is the console entry point (`pip install -e .[tui,analysis]`), dispatching
to `src/cinetic/__main__.py`. The worker stage runs inside the Slurm job via the
hidden `cinetic _worker --workdir <dir>` subcommand.

The preset can also be set via a `.env` file (single line: preset name) or `CINETIC_PRESET` env var. Default is `local`. Legacy `CRAB_*` env vars are still read (mirrored to `CINETIC_*`) via `src/cinetic/compat.py`.

## Architecture

```
cli.py / tui.py / ...         # Legacy entry shims → the unified CLI
src/cinetic/__main__.py          # Unified `cinetic` CLI dispatch (run/tui/analyze/topo/plot/_worker)
src/cinetic/runtime.py           # RuntimeContext: typed front door to the resolved CINETIC_* settings
src/cinetic/compat.py            # Legacy CRAB_* → CINETIC_* env shim (warns once)
src/cinetic/cli/orchestrator.py  # Preset loading, env merging, SBATCH generation → Engine
src/cinetic/core/engine.py       # Core: NodeAllocator, ExperimentRunner, Engine
src/cinetic/core/models.py       # AppConfig / BenchmarkState dataclasses (used by TUI)
src/cinetic/core/wl_manager/     # Workload manager backends: slurm.py, mpi.py (take a RuntimeContext)
src/cinetic/topology/            # ibnetdiscover parser → neutral topology JSON (model.py, parser.py)
src/cinetic/analysis/            # tournament_nb result analyzer + analysis/cli.py (the `analyze` subcommand)
wrappers/                     # One .py file per benchmark, all extend wrappers/base.py
benchmarks/blink/             # C/C++ MPI microbenchmark sources + pre-built bin/
tests/                        # Standalone-runnable tests (no pytest dep) + fixtures/
```

### Engine execution flow
1. **Orchestrator mode** (`cli.py`): loads preset → merges env/sbatch/header → injects into config → writes `cinetic_job.sh` → `sbatch cinetic_job.sh`
2. **Worker mode** (inside the Slurm job): reads `config.json` + `environment.json` from the output dir → instantiates `ExperimentRunner` per experiment → runs the event loop → saves CSV results

### Experiment config format (JSON)
```json
{
  "global_options": {
    "numnodes": "8", "ppn": "1",
    "allocationmode": "p",          // l=linear, i=interleaved, p=partitioned
    "partitionsplit": "50:50",
    "allocationsplit": "100-100",
    "partitionlayout": "l",         // l=linear, i=interleaved
    "timeout": "1200.0",            // wall-clock cap on the single run
    "outformat": "csv",
    "name": "optional_run_name",
    "walltime": "00:30:00",
    "nodelist": ["node01", "node02"],   // optional: pin to exact hosts (sets --nodelist; overrides numnodes)
    "sbatch_directives": ["--account=X", "--partition=Y"]
  },
  "experiments": {
    "exp_id": {
      "apps": {
        "0": { "path": "a2a_b.py", "args": "-msgsize 1048576 -iter 100",
               "collect": true, "start": "0", "end": "", "partition": 0 }
      }
    }
  }
}
```

`end` values: `""` = victim (wait to finish), `"f"` = aggressor (killed when victims finish), `"<N>"` = killed after N seconds.
`start` values: `"0"` = start immediately, `"<N>"` = delay N seconds, `"s<id>"` = start after app `id` finishes.

### Writing a new wrapper
Create `wrappers/my_bench.py`:
```python
from wrappers.base import base   # or from microbench_common import microbench

class app(base):
    metadata = [{"name": "latency", "unit": "s", "conv": True}]
    
    def get_binary_path(self):
        return os.environ["CINETIC_ROOT"] + "/benchmarks/blink/bin/my_bench"
    
    def read_data(self):
        # parse self.stdout, return list-of-lists (one per metadata entry)
        ...
```
`conv` is retained on metadata for compatibility but is currently inert:
convergence-based stopping has been removed, so each experiment runs exactly
once (bounded by `timeout`). Legacy configs may still carry `minruns`/`maxruns`/
`alpha`/`beta`/`convergeall`; they are ignored.

### Writing a benchmark that emits standardized results

A C/C++ MPI benchmark opts into the standardized per-node output (above) by
including `benchmarks/blink/results.h` (header-only; the Makefile lists it as a
prerequisite for every `*.c`/`*.cpp` target — do **not** add a `results.c`, the
glob would build a stray `bin/results`). After the measured loop fills the LRU
`durations[]` ring, call:

```c
cin_write_node_results(
    op,              // op tag string, e.g. "pairwise_fd" / "alltoall" / "allgather_ring"
    comm_id,         // communicator id (0 for COMM_WORLD; matches the manifest)
    MPI_COMM_WORLD,  // comm used to resolve hostnames/ranks for the dump
    durations,       // the LRU sample buffer
    peer,            // int[] per-sample peer rank, or NULL for an opaque collective
    phase,           // int[] per-sample phase/round, or NULL (-1)
    bytes_per_sample,// bandwidth basis (busbw convention; see below)
    ops_per_sample,  // latency basis (op completions per sample)
    curr_iters, max_samples, warm_up_iters);
cin_write_manifest(comm_id);   // race-free; call once after the dump
```

Three flavors, by how `peer`/`phase` are filled:
- **pairwise** (e.g. `tournament_nb.c`): real per-sample `peer` + `phase`; the
  analyzer merges both endpoints into symmetric pairings and classifies each by
  topology locality.
- **collective** (e.g. `ardc_nb.c` allreduce, `a2a_nb.c` alltoall): `peer=NULL`,
  `phase=NULL`; no single peer, so topology is analyzed via the **comm span**
  from the manifest. Set `bytes_per_sample` with the **busbw** convention
  (allreduce `gran*2*(N-1)/N*msg`, alltoall `gran*2*(N-1)*msg`) and
  `ops_per_sample=gran`. Use `-splitsize N` (`MPI_Comm_split`) to populate the
  collective locality axis with sub-communicators of differing span.
- **directed** (e.g. `agtr_comm_only.cpp` ring allgather): real per-sample `peer`
  (e.g. the ring successor) but non-reciprocal; the analyzer detects this
  (reciprocity `< 0.5`), keeps each directed hop separate (no merge), and reports
  per-link bandwidth with real per-hop locality.

Size `max_samples` so the ring buffer doesn't evict measured rounds:
`rounds*iters` for pairwise, `iters` for collectives. Design & milestones:
`PLAN_OUTPUT_STANDARDIZATION.md`.

## Topology (network-aware node selection)

`src/cinetic/topology/` parses `ibnetdiscover` output into a neutral, serializable
JSON model used for topology-aware node selection (see PLAN.md).

```bash
python topology_parser.py <ibnetdiscover.txt> -o topology.json
python tests/test_topology_parser.py          # standalone test, prints PASS/FAIL
```

Model (`model.py`): `Switch` (leaf/spine), `Nic` (one HCA / `Ca` entry), `Node`
(physical host owning >=1 NIC), `Cell` (maximal group of leaf switches within
<=1 spine hop). `Topology.to_dict()/from_dict()/save()/load()` handle JSON; the
`Locality` enum classifies node pairs as SAME_SWITCH / SAME_CELL / CROSS_CELL.
Parser regex grammar is kept compatible with the reference repo
[cinetic](https://github.com/cpt-harlock/cinetic) (`topology/topology.py`).

Neutral-format topology files live in `topologies/`. Presets may set an optional
`topology` key (sibling of `env`/`sbatch`/`header`) pointing to one — this is
only a **default**: the TUI shows the path in an editable field with a Browse…
file picker, so the user can load any topology JSON. The TUI
"Benchmark Options" tab exposes a **Topology Map** node source: the
**Open Topology Map** button opens a graphical `ModalScreen`
(`src/cinetic/tui/widgets/topology_map.py`) where cells → switches → nodes are
clickable; the confirmed selection fills the node table and `numnodes`.
The selection is passed to Slurm as `global_options.nodelist` (list of
hostnames): the engine emits `#SBATCH --nodelist=<hosts>` and forces `--nodes`
to match. It is framework-managed — user `--nodelist`/`-w`/`--nodes` overrides
are ignored (`normalize_nodelist()` + `_generate_sbatch_header()` in
`engine.py`). CLI configs may set `nodelist` directly under `global_options`.

## Building MPI benchmarks

```bash
cd benchmarks/blink
make        # uses mpicc / mpicxx, outputs to bin/
make clean
```

Flags: `-lm -D_GNU_SOURCE -O3` (C), `-std=c++17` (C++).

## Presets (`presets.json`)

Each preset has three sections:
- `env`: dict of env vars (`__CWD__` is replaced with `os.getcwd()` at runtime)
- `sbatch`: list of `--flag=value` strings appended to every job script
- `header`: list of shell commands run at job start (e.g., `module load openmpi`)

`_common` is merged first; preset-specific values override it.

Active presets: `local`, `leonardo` (plus the `example_preset` template).

Key env vars actually read by the engine/CLI:
- `CINETIC_ROOT` — repo root (used by every wrapper's `get_binary_path`)
- `CINETIC_WRAPPERS_PATH` — path searched for relative wrapper paths
- `CINETIC_WL_MANAGER` — `slurm` or `mpi`
- `CINETIC_PINNING_FLAGS` — CPU-binding flags (read by both backends)
- `CINETIC_MPIRUN`, `CINETIC_MPIRUN_MAP_BY_NODE_FLAG`,
  `CINETIC_MPIRUN_HOSTNAMES_FLAG`, `CINETIC_MPIRUN_ADDITIONAL_FLAGS` — used by
  the `mpi` backend only (the `slurm` backend invokes `srun` directly)

Framework-managed (not user-set): `CINETIC_SYSTEM` (from the preset name),
`CINETIC_PRESET` (preset selector), `CINETIC_NODE_RESULTS_DIR` (set per
experiment by the engine). A handful of benchmark wrappers read their own path
vars on demand (e.g. `CINETIC_MINIFE_PATH`, `CINETIC_G500_PATH`,
`CINETIC_AMG_PATH`, `CINETIC_IB_DEVICES`); set those only when running the
corresponding benchmark.

## Output

Results land under `data/<CINETIC_SYSTEM>/<name>_<timestamp>/`:
- `config.json`, `environment.json` — reproducibility snapshot
- `cinetic_job.sh` — submitted Slurm script
- `slurm_output.log`, `slurm_error.log`
- `<exp_id>/data_app_<id>.csv` — collected metrics (wrapper-parsed stdout)
- `<exp_id>/error_app_<id>.log` — per-app error logs on non-zero exit

### Standardized per-node output

Benchmarks that opt in (via `results.h`, see below) also write **per-node CSV
dumps** the analyzer reads uniformly across point-to-point *and* collective ops.
Files are namespaced by **app id** (`<id>` = the app's key in the experiment
config) because every app in an experiment shares this dir but is a separate
`mpirun`/`srun` with its own rank space — without the prefix, co-located apps
would clobber each other:
- `<exp_id>/node_app<id>_<host>_rank<r>.csv` — one file per rank, columns
  `node,rank,op,comm,sample,phase,peer_node,peer_rank,bytes,ops,duration_s`
  (strict superset of the legacy tournament format; parsed by header name).
  `bytes` is the bandwidth basis (analyzer: `bandwidth = bytes/duration`),
  `ops` the latency basis (`latency = duration/ops`); `peer_rank < 0` marks a
  collective sample (no single peer). Only the final engine run survives (mode
  `"w"`); a fixed-size LRU ring buffer keeps the last `max_samples` samples.
- `<exp_id>/comm_manifest_app<id>.csv` — `comm,rank,node`, mapping each
  communicator id to its member nodes (the "peer set" for collective topology
  analysis). Written race-free by a single WORLD-rank-0 gather.

Only **collecting** apps (`collect: true`) emit these — the engine sets
`CINETIC_APP_ID`/`CINETIC_COLLECT` per app (forwarded via `srun --export=ALL`
or the mpi backend's `env VAR=…` prefix), and `results.h` skips the writers
when `CINETIC_COLLECT=0`. Legacy un-prefixed dumps (`node_<host>_rank<r>.csv`,
`comm_manifest.csv`) still parse as a single app.

## Result analyzer (`tournament_analyzer.py` / `cinetic analyze`)

Analyzes the **standardized per-node CSV dumps** (see *Standardized per-node
output* above) — both the legacy tournament format and the unified superset.
Backed by `src/cinetic/analysis/`: `parse` (format-tolerant: columns by name,
blocks split on `(op,comm,peer,phase)` change; reads `comm_manifest.csv`) →
`params` (msg_size/window/granularity from CLI → `stdout_app_*.log` header →
`config.json` args → C defaults; per-sample `bytes`/`ops` from the file override
these as the bandwidth/latency basis) → `metrics` (robust stats) → `topo` (wraps
`cinetic.topology.model`; normalizes FQDN→short host; adds `comm_span`) →
`outliers` → `report_text`/`report_plot`.

The analyzer auto-detects one of three **kinds** and adapts the report:
- **pairwise** — symmetric merge into pairings; per-round **topology distance**
  mix (same_switch / same_cell / cross_cell via `Topology.locality()`), per-node
  peer profile (uniform / bimodal / mixed / broadly_slow, with single-rail/NIC
  detection), and the per-round-per-node view.
- **collective** (`peer_rank < 0`) — no single peer, so topology is bucketed by
  **comm span** (worst pairwise locality among each communicator's manifest
  members) with a "bandwidth by comm span" report/plots and a per-communicator
  view; plus a per-node straggler view.
- **directed** (non-reciprocal peers, reciprocity `< 0.5`, e.g. ring) — per-match
  (no merge), reporting per-link bandwidth labelled by real per-hop locality.

Reports **bandwidth** (busbw aggregate decimal GB/s; convention printed in the
report) and **latency** (`duration/ops`), robust stats with std dev, and flagged
under-performing nodes. Writes `report.txt`, `peer_profiles.txt` (pairwise),
`per_round_per_node.txt`, `summary.json` (`--json`), and figures to
`<exp_dir>/analysis/`; `--detail` echoes the per-peer / per-round tables to
stdout. A multi-app experiment is analyzed **per app** (files grouped by the
`app<id>_` prefix); each app gets its own `analysis/app_<id>/` subdir (a
single-app or legacy dir writes straight to `analysis/`). Designs:
`PLAN_RESULT_ANALYZER.md` (pairwise core),
`PLAN_OUTPUT_STANDARDIZATION.md` (collective/directed standardization),
`PLAN_ANALYSIS_REWORK.md` (analysis rework).

### Congestion-aware analysis (roles, congestion, fabric, compare)

On top of the per-app reports, the analyzer adds a **semantic + comparison**
layer (`PLAN_ANALYSIS_REWORK.md`). It reads the run's `config.json` /
`environment.json` to learn what each app *was*, then diffs and attributes:

- **Roles** (`analysis/context.py`): each app id → role from its `end` field
  (`""`=victim, `"f"`=aggressor, `"<N>"`=timed), partition, system, and detected
  `output_kind`. The report gains an `app / role` line + a `BASELINE`/`LOADED`
  experiment header; `summary.json` gains a `role` block. Degrades to anonymous
  analysis when there is no config.
- **Congestion impact** (`analysis/congestion.py`, goal 1): diffs a victim's
  analysis between a **baseline** experiment (victims only) and a **loaded** one
  (same victim + aggressors) → bandwidth-drop% / latency-increase% overall, per
  topology label, and per node (worst-hit first). Auto-detects a victim-only
  baseline in the run, or `--baseline <dir>`; `--no-congestion` skips. Writes
  `congestion.txt`/`.json` + a baseline-vs-loaded overlay plot. Single-run
  point estimate (final-run-only) is flagged.
- **Fabric load** (`analysis/fabric.py`, goal 4, `--fabric`): builds the switch
  graph from the topology and attributes each flow's bandwidth across **all
  shortest paths** between endpoint leaf switches (exact ECMP expected load) to
  rank hotspot **switches/links**. Flows: pairwise pairings, directed hops, and
  manifest-expanded collective member pairs. Combines all of an experiment's
  collecting apps (concurrent fabric load). `--hotspots N`; writes
  `fabric.txt`/`.json` + a per-switch load bar. Skips (warns) when <80% of hosts
  resolve. Candidate exposure, not a claimed route.
- **Cross-experiment compare** (`analysis/compare.py`, goal 2,
  `cinetic analyze compare <dirA> <dirB> …`): aligns N run/exp dirs by node +
  topology label (same-kind only; mixed flagged), reports deltas vs the first
  series, fits an overall-bandwidth **trend** (auto run-dir timestamps or
  `--x index|timestamp|<nums>`), and supports `--bw-relative` (normalize to each
  series' own median). Writes `comparison.txt`/`.json` + an overlay plot.

These layers **consume** the per-app `Analysis` objects (they never re-parse or
recompute bandwidth). `model.py` from the plan was folded in: role fields live on
`metrics.Analysis`; result types live in their own modules.

## Dependencies

```
pip install -r requirements.txt      # core: numpy, scipy, pandas, rich
pip install -r requirements-tui.txt  # TUI: textual (and its deps)
```

Python 3.10+. No test suite currently exists.
