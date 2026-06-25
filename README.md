<p align="center">
  <img src="cinetic_logo.png" alt="CINETIC — CINECA Network Integrity Checker" width="520">
</p>

<p align="center">
  <a href="https://www.python.org/"><img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10+-blue.svg"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-yellow.svg"></a>
</p>

**CINETIC** — the **CINECA Network Integrity Checker** — stress-tests a cluster's
interconnect under realistic load and tells you *where* it degrades. You compose
a run from two kinds of MPI jobs: **victims** (the traffic you measure) and
**aggressors** (co-running noise competing for the same links). CINETIC places
them on chosen nodes *by network topology*, runs them under Slurm, and turns the
per-node results into bandwidth/latency reports that pinpoint slow nodes,
single-rail NICs, and congested topology distances.

It targets Slurm machines such as **Leonardo @ CINECA**, and also runs locally
over plain MPI for development.

> **Lineage.** CINETIC is a fork of [CRAB](https://github.com/SharkGamerZ/CRAB)
> (Co-Running Applications Benchmarking). It keeps CRAB's orchestration core and
> refocuses it on interconnect integrity — topology-aware placement, a single
> `cinetic` command, and a built-in result analyzer. Credit for the original
> framework goes to the CRAB authors.

## How it works

1. **Pick a system preset** (`presets.json`) — the environment, Slurm
   directives, and modules for your machine.
2. **Compose a run** — applications tagged *victim* or *aggressor*, with
   start/stop rules, placed on nodes you choose from a **topology map** or a host
   list.
3. **CINETIC submits one Slurm job**, launches the apps via `srun`/`mpirun`,
   watches them, and saves per-node CSVs plus a config/environment snapshot for
   reproducibility.
4. **Analyze** — `cinetic analyze` reads the per-node dumps and reports
   bandwidth, latency, the per-round topology mix, and flags under-performing
   nodes.

Everything runs through one command, `cinetic`: a TUI for composing runs
interactively, a CLI for scripting.

## Install

```bash
git clone <your-cinetic-repo-url> && cd cinetic
python -m venv .venv && source .venv/bin/activate
pip install -e .[tui,analysis]          # provides the `cinetic` command
make -C benchmarks/blink                # build the bundled MPI microbenchmarks
```

Needs Python 3.10+, and either a Slurm allocation (production) or a local MPI
runtime (`mpirun`) for small runs.

## Quickstart

Interactive — compose apps, pick nodes, set options, launch, and watch the log:

```bash
cinetic tui
```

Scripted — run an experiment file against a system preset:

```bash
cinetic run -p leonardo -c examples/leonardo/leonardo_stress.json
```

`-p/--preset` selects a system from `presets.json` (default `local`); `-c/--config`
is the experiment JSON. Results land under `data/<system>/<name>_<timestamp>/`.
The same entry point also exposes `cinetic topo`, `cinetic analyze`, and
`cinetic plot` (below); the legacy `python cli.py` / `python tui.py` shims still
work.

## Topology-aware placement

Where victims and aggressors sit on the fabric decides what you measure, so
placement is first-class. Build a neutral topology model from `ibnetdiscover`:

```bash
cinetic topo ibnetdiscover.txt -o topologies/mycluster.json
```

The model captures switches (leaf/spine), NICs, nodes, and **cells** (leaf groups
within one spine hop), and classifies any node pair as `SAME_SWITCH`,
`SAME_CELL`, or `CROSS_CELL`. In the TUI's **Benchmark Options** tab you then pick
nodes from a clickable **Topology Map** or a **Node List** of hostnames. The
selection becomes `global_options.nodelist`; the engine pins the job with
`#SBATCH --nodelist=…` and forces `--nodes` to match — ignoring any conflicting
user `--nodelist`/`-w`/`--nodes` so the placement is guaranteed.

## Result analysis

```bash
cinetic analyze <run_dir|exp_dir> --topology topologies/leonardo.json --json
```

For benchmarks that dump per-node results (e.g. `tournament_nb`), the analyzer
reports:

- **Bandwidth & latency** per node, per round, and overall (full-duplex
  aggregate GB/s; latency is per-iteration, exact only when the window is 1).
- **Per-round topology mix** — `same_switch` / `same_cell` / `cross_cell` counts.
- **Under-performing nodes**, robustly flagged against the median.
- **Per-node peer profiles** — uniform / bimodal / mixed, auto-detecting the
  single-rail / degraded-NIC signature (a fast vs. ~half-rate cluster of peers).

It writes `report.txt`, `peer_profiles.txt`, `per_round_per_node.txt`,
`summary.json` (`--json`), and figures into `<exp_dir>/analysis/`. `cinetic plot`
renders the blink scaling figures.

## Configuration

**Presets** (`presets.json`) describe each system with three optional sections:
`env` (variables), `sbatch` (job directives), and `header` (startup shell
commands, e.g. `module load`). `_common` is merged into every preset. The active
preset comes from `-p`, a one-line `.env` file, or `$CINETIC_PRESET` (default
`local`).

**Experiment config** (the `-c` JSON) holds `global_options` (e.g. `numnodes`,
`ppn`, `timeout`, or an explicit `nodelist`) and `applications`, a map of apps:

| field | meaning |
|---|---|
| `path` | wrapper file under `wrappers/` |
| `args` | command-line arguments for the binary |
| `collect` | whether to record this app's metrics |
| `start` | `"0"` now · `"<N>"` after N s · `"s<id>"` after app `<id>` finishes |
| `end` | `""` victim (run to completion) · `"f"` aggressor (killed with the victims) · `"<N>"` killed after N s |

Each experiment runs once, bounded by `timeout`.

## Extending: add a benchmark

A benchmark is a small Python wrapper in `wrappers/` that tells CINETIC how to
launch a binary and parse its output — no core changes needed:

```python
from wrappers.base import base   # or `microbench` for the bundled MPI benchmarks

class app(base):
    metadata = [{"name": "latency", "unit": "s"}]

    def get_binary_path(self):
        return os.environ["CINETIC_ROOT"] + "/benchmarks/blink/bin/my_bench"

    def read_data(self):
        # parse self.stdout → a list of lists, one per metadata entry
        ...
```

`read_data` returns one sample list per metric in `metadata`. The wrappers
shipped in `wrappers/` cover the MPI collectives backed by
`benchmarks/blink/bin/` and are ready to drop into any config.

## Credits & License

CINETIC is a fork of [CRAB](https://github.com/SharkGamerZ/CRAB) by its original
authors. Released under the MIT License — see [`LICENSE`](LICENSE).
