# CRAB — Claude Code Context

## What this project is

**CRAB** (Co-Running Applications Benchmarking) is an HPC benchmarking framework for running, measuring, and analyzing MPI collective benchmarks on Slurm-managed clusters. Its primary use case is studying **network congestion** caused by co-running applications (victims vs. aggressors) on systems like Leonardo @ CINECA.

## How to run

```bash
# CLI (orchestrator mode — submits a Slurm job)
python cli.py -p <preset> -c <config.json>

# TUI (interactive)
python tui.py

# Plot results
python blink_plotter.py
```

The preset can also be set via a `.env` file (single line: preset name) or `CRAB_PRESET` env var. Default is `local`.

## Architecture

```
cli.py / tui.py               # Entrypoints — collect config, set env, call Engine
src/crab/cli/orchestrator.py  # Preset loading, env merging, SBATCH generation → Engine
src/crab/core/engine.py       # Core: NodeAllocator, ExperimentRunner, Engine
src/crab/core/models.py       # AppConfig / BenchmarkState dataclasses (used by TUI)
src/crab/core/wl_manager/     # Workload manager backends: slurm.py, mpi.py
src/crab/topology/            # ibnetdiscover parser → neutral topology JSON (model.py, parser.py)
wrappers/                     # One .py file per benchmark, all extend wrappers/base.py
benchmarks/blink/             # C/C++ MPI microbenchmark sources + pre-built bin/
tests/                        # Standalone-runnable tests (no pytest dep) + fixtures/
```

### Engine execution flow
1. **Orchestrator mode** (`cli.py`): loads preset → merges env/sbatch/header → injects into config → writes `crab_job.sh` → `sbatch crab_job.sh`
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
    "minruns": "5", "maxruns": "20",
    "timeout": "1200.0",
    "alpha": "0.05", "beta": "0.05",
    "convergeall": false,
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
        return os.environ["CRAB_ROOT"] + "/benchmarks/blink/bin/my_bench"
    
    def read_data(self):
        # parse self.stdout, return list-of-lists (one per metadata entry)
        ...
```
`conv: True` = this metric is used for convergence checking (CI-based).

## Topology (network-aware node selection)

`src/crab/topology/` parses `ibnetdiscover` output into a neutral, serializable
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
`topology` key (sibling of `env`/`sbatch`/`header`) pointing to one. The TUI
"Benchmark Options" tab exposes a **Topology Map** node source: the
**Open Topology Map** button opens a graphical `ModalScreen`
(`src/crab/tui/widgets/topology_map.py`) where cells → switches → nodes are
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

Active presets: `local`, `leonardo`, `alps`, `lumi`, `cluster_di`, `haicgu`, `nanjin`, `slimfly`.

Key env vars used by wrappers/engine:
- `CRAB_ROOT` — repo root
- `CRAB_WRAPPERS_PATH` — path searched for relative wrapper paths
- `CRAB_WL_MANAGER` — `slurm` or `mpi`
- `CRAB_MPIRUN` — mpirun/srun executable
- `CRAB_PINNING_FLAGS`, `CRAB_MPIRUN_ADDITIONAL_FLAGS`
- `CRAB_GPU_BENCH`, `CRAB_XCCL_BENCH` — feature flags for GPU/NCCL wrappers

## Output

Results land under `data/<CRAB_SYSTEM>/<name>_<timestamp>/`:
- `config.json`, `environment.json` — reproducibility snapshot
- `crab_job.sh` — submitted Slurm script
- `slurm_output.log`, `slurm_error.log`
- `<exp_id>/data_app_<id>.csv` — collected metrics
- `<exp_id>/error_app_<id>.log` — per-app error logs on non-zero exit

## Dependencies

```
pip install -r requirements.txt      # core: numpy, scipy, pandas, rich
pip install -r requirements-tui.txt  # TUI: textual (and its deps)
```

Python 3.10+. No test suite currently exists.
