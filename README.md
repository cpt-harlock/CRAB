# ⚡ CINETIC — Co-running INterference & nEtwork-Topology Investigation for Clusters
[![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Build Status](https://img.shields.io/badge/build-passing-brightgreen)](https://github.com/actions)

> **CINETIC is a fork of [CRAB](https://github.com/SharkGamerZ/CRAB)** (Co-Running Applications Benchmarking), rebranded and restructured. Full credit for the original framework goes to the CRAB authors.

**CINETIC** is a flexible and powerful framework for executing, collecting, and analyzing high-performance benchmarks (HPC), optimized for clusters managed by **Slurm**. It allows you to orchestrate combinations of applications, manage system-specific environments, and automate the entire benchmarking process — with a focus on studying **network congestion** caused by co-running applications (victims vs. aggressors).

![asciicast](https://user-images.githubusercontent.com/11363902/203875389-918931a5-e110-4107-8854-c8c3656ab3e2.gif)

## ✨ Key Features

*   **Dual Interface**: Use it either through a **Textual User Interface (TUI)** for interactive usage or a **Command Line Interface (CLI)**
*   **Advanced Environment Management**: Easily define and switch between system environments (e.g., `lumi`, `leonardo`, etc.) via a centralized preset system.
*   **Complex Application Mixes**: Run multiple applications simultaneously, defining "victims" (to be measured) and "aggressors" (to create interference).
*   **Automated Data Collection**: Automatically gathers performance data, analyzes it, and can stop execution once statistical convergence is reached.
*   **Standard Output Formats**: Saves collected data in the standard format CSV, ready for analysis with tools like Pandas or R.
*   **Topology-Aware Node Selection**: Parse the fabric (`ibnetdiscover`) into a neutral topology model and pin jobs to specific nodes — interactively via a clickable **Topology Map**, or by hostname list — so you control exactly where victims and aggressors land.
*   **Built-in Result Analysis**: Turn per-node benchmark dumps into bandwidth/latency reports (per-node, per-round, overall), per-round topology-distance breakdowns, automatic flagging of under-performing nodes, per-node peer profiles, and figures — all with one command.
*   **Extensible Architecture**: Add support for new benchmarks simply by creating a Python "wrapper," without modifying the framework core.

## 📚 Table of Contents

*   [🚀 Installation and Setup](#-installation-and-setup)
*   [🕹️ Using the Framework](#-using-the-framework)
    *   [TUI Mode (Interactive)](#tui-mode-interactive)
    *   [CLI Mode (Command Line)](#cli-mode-command-line)
*   [🗺️ Topology-Aware Node Selection](#️-topology-aware-node-selection)
*   [📊 Analyzing Results](#-analyzing-results)
*   [🏗️ Framework Architecture](#️-framework-architecture)
*   [🧩 Adding a New Benchmark](#-adding-a-new-benchmark)
    *   [Wrapper Structure](#wrapper-structure)
    *   [Mandatory Methods](#mandatory-methods)
*   [📄 Configuration File Format](#-configuration-file-format)
    *   [The `presets.json` File](#the-presetsjson-file)
    *   [The Benchmark Config File](#the-benchmark-config-file)
*   [📜 License](#-license)

## 🚀 Installation and Setup

### Prerequisites

*   Python 3.10+
*   Git
*   A **Slurm**-managed cluster (production use), or a local machine with an **MPI** runtime (`mpirun`) for smaller runs.

### Installation Steps

1.  **Clone the repository:**
    ```bash
    git clone <your-cinetic-repo-url>
    cd cinetic
    ```

2.  **Create a virtual environment (recommended):**
    ```bash
    python -m venv .venv
    source .venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -e .[tui,analysis]   # installs the `cinetic` CLI
    # or, without packaging: pip install -r requirements.txt -r requirements-tui.txt
    ```

4.  **Configure cluster environments:**
    Edit `presets.json` — one entry per system you run on. Each preset has three
    optional sections: `env` (environment variables), `sbatch` (directives added
    to every job script), and `header` (shell commands run at job start, e.g.
    `module load`). The special `_common` preset is merged into every other one.

    ```json
    {
        "_common": {
            "env": { "CINETIC_ROOT": "/absolute/path/to/cinetic" }
        },
        "my_cluster": {
            "env": {
                "CINETIC_WL_MANAGER": "slurm",
                "CINETIC_MPIRUN": "srun",
                "CINETIC_PINNING_FLAGS": "--cpu-bind=cores"
            },
            "sbatch": ["--account=ACCT", "--partition=PART"],
            "header": ["module load openmpi"]
        },
        "local_pc": {
            "env": { "CINETIC_WL_MANAGER": "mpi", "CINETIC_MPIRUN": "mpirun" }
        }
    }
    ```

## 🕹️ Using the Framework

You can interact with CINETIC in two ways: through the TUI or the CLI.

### TUI Mode (Interactive)

The TUI is ideal for configuring and launching experiments visually and interactively.

**How to start it:**
```bash
cinetic tui          # or, legacy shim: python tui.py
````

The interface will guide you through:

1. **Preset Selection**: Choose the target system, or create your custom preset.
2. **Application Setup**: Add benchmarks to run, specifying the wrapper path, arguments, and start/end rules.
3. **Global Options**: Configure node count, allocation mode, timeout, etc.
4. **Execution**: Start the benchmark and monitor logs in real time.

### CLI Mode (Command Line)

The CLI is perfect for automation, scripting, and running batch tests.

**Command syntax:**

```bash
cinetic run --preset <preset_name> --config <path_to_config.json>
```

* `--preset, -p <preset_name>`: Specifies which environment to use, defined in `presets.json` (e.g., `my_cluster`); default is `local`.
* `--config, -c <path_to_config.json>`: The JSON file describing the experiment.

**Example:**

```bash
cinetic run --preset leonardo --config examples/leonardo/leonardo_stress.json
# legacy shim: python cli.py --preset leonardo --config examples/leonardo/leonardo_stress.json
```

Logs are printed to the terminal, and results are written under `data/<system>/<run_name>_<timestamp>/` — together with a snapshot of the config and environment for reproducibility.

## 🗺️ Topology-Aware Node Selection

CINETIC can place your applications on specific nodes based on the cluster's
network topology — essential for congestion studies, where *which* nodes the
victims and aggressors land on determines what you actually measure.

**1. Build a topology model** from your fabric's `ibnetdiscover` output:

```bash
cinetic topo ibnetdiscover.txt -o topologies/mycluster.json
```

This produces a neutral, serializable JSON model of switches (leaf/spine), NICs,
nodes, and **cells** (maximal groups of leaf switches within one spine hop). Any
pair of nodes is then classified by locality — `SAME_SWITCH`, `SAME_CELL`, or
`CROSS_CELL`. Ready-made models for some systems live in `topologies/` (e.g.
`leonardo.json`), and a preset can point to one via an optional `topology` key.

**2. Select the nodes.** In the TUI's **Benchmark Options** tab, the node source
can be:

* **Topology Map** — click **Open Topology Map** to open a graphical selector
  where cells → switches → nodes are clickable; the confirmed selection fills the
  node table and `numnodes`.
* **Node List** — paste a comma/space-separated list of hostnames; the node count
  is inferred automatically.

Either way the selection becomes `global_options.nodelist`. The engine emits
`#SBATCH --nodelist=<hosts>` and forces `--nodes` to match. Node pinning is
**framework-managed**: conflicting user `--nodelist` / `-w` / `--nodes`
directives are ignored so the requested placement is guaranteed. CLI configs can
set `nodelist` directly under `global_options`.

## 📊 Analyzing Results

Benchmarks that dump per-node results — such as `tournament_nb`, which writes one
`node_<host>_rank<r>.csv` per rank — can be analyzed in a single command:

```bash
cinetic analyze <run_dir | exp_dir> --topology topologies/leonardo.json --json
```

The analyzer reports:

* **Bandwidth & latency** per-node, per-round, and overall. Bandwidth is the
  full-duplex aggregate (decimal GB/s; unidirectional is half); latency is the
  per-iteration time (a true latency only when the window size is 1).
* **Per-round topology mix** — how many pairings were `same_switch` / `same_cell`
  / `cross_cell` each round, using the topology model above.
* **Under-performing nodes** — robustly flagged against the median.
* **Per-node peer profiles** — classifies each node's per-peer bandwidth
  (uniform / bimodal / mixed / broadly slow) and auto-detects the single-rail /
  degraded-NIC signature (a fast vs. ~half-rate cluster of peers).
* **Per-round-per-node** view — each node's peer, distance, and bandwidth/latency
  in every round.

Outputs land in `<exp_dir>/analysis/`: `report.txt`, `peer_profiles.txt`,
`per_round_per_node.txt`, `summary.json` (`--json`), and figures. Handy flags:
`--detail` (echo the full tables to stdout), `--topo-graph` (draw the topology
node-link diagram), `--no-plots`, `--show`.

To plot blink microbenchmark scaling results, use `cinetic plot`.

## 🏗️ Framework Architecture

The framework is designed with a clear separation of responsibilities:

1. **Entrypoint (`cinetic` CLI → `src/cinetic/__main__.py`)**: The unified command with `run` / `tui` / `analyze` / `topo` / `plot` subcommands (legacy `cli.py` / `tui.py` shims still work). Its only job is to collect configuration, prepare the environment, and start the engine.
2. **Engine (`engine.py`)**: The core of the framework. Receives a prepared environment and configuration. It handles:

   * Node allocation (via Slurm, if used).
   * Application scheduling.
   * Benchmark process launching through the workload manager.
   * Completion monitoring, data collection, and convergence checking.
3. **Workload Manager (`src/cinetic/core/wl_manager/*.py`)**: Specialized modules that translate a request ("run this command on these nodes") into system-specific commands (e.g., `srun, mpirun ...`). They read their settings from a typed `RuntimeContext` (`src/cinetic/runtime.py`).
4. **Application Wrappers (`wrappers/*.py`)**: Small Python modules that "wrap" a specific benchmark, teaching the framework how to run it and interpret its output.
5. **Topology (`src/cinetic/topology/`)**: Parses `ibnetdiscover` into a neutral topology model (switches, NICs, nodes, cells) used for topology-aware node selection and locality classification.
6. **Analysis (`src/cinetic/analysis/`)**: Turns per-node result dumps into bandwidth/latency reports, per-round topology-distance breakdowns, peer profiles, outlier flags, and figures.

## 🧩 Adding a New Benchmark

Integrating a new executable into the framework is simple and does not require modifying core code. You just need to create a "wrapper."

### Wrapper Structure

1. **Create a new Python file** in `wrappers/`, e.g. `my_benchmark.py`.
2. Inside it, define a class named `app` that inherits from the base class `base` (or from `microbench` for MPI microbenchmarks).

   ```python
   # in wrappers/my_benchmark.py
   from wrappers.base import base

   class app(base):
       # ... implementation here ...
   ```

### Mandatory Methods

Your `app` class must implement a few key methods:

1. **`__init__(self, app_id, collect_flag, args)`**: The constructor. If data collection is required, define metadata here.

   ```python
   def __init__(self, app_id, collect_flag, args):
       super().__init__(app_id, collect_flag, args)  # Call base constructor

       # Define the metrics produced by this benchmark
       self.metadata = [
           {"name": "performance", "unit": "GTEPS", "conv": True},
           {"name": "time", "unit": "s", "conv": False},
       ]
       # Mandatory if collecting data
       self.num_metrics = len(self.metadata)
   ```

2. **`get_binary_path(self)`**: Must return a string with the absolute path to the benchmark executable.

   ```python
   def get_binary_path(self):
       # You can use environment variables from presets for flexibility
       return os.environ["CINETIC_ROOT"] + "/path/to/my/executable"
   ```

3. **`read_data(self)`**: The most important method. It must parse the benchmark output (`self.stdout`) and return the collected data.

   * **Input**: `self.stdout` (a string containing the program output).
   * **Output**: A list of lists. Each sublist corresponds to one metric defined in `self.metadata` and contains all collected samples.

   ```python
   def read_data(self):
       # Example: parsing CSV-like output
       performance_samples = []
       time_samples = []

       for line in self.stdout.splitlines():
           if line.startswith("RESULT:"):
               parts = line.split(",")
               performance_samples.append(float(parts[1]))
               time_samples.append(float(parts[2]))

       # Return data in the same order as in self.metadata
       return [performance_samples, time_samples]
   ```

Once the wrapper is created, you can immediately use it in your JSON configuration files!

## 📄 Configuration File Format

### The `presets.json` File

Defines the per-system environments. Each preset may set three sections:

* `env`: environment variables (`__CWD__` is expanded to the current directory at runtime).
* `sbatch`: a list of `--flag=value` directives appended to every generated job script.
* `header`: a list of shell commands run at the start of the job (e.g. `module load ...`).

`_common` is merged first; a preset's own values override it.

### The `.env` File

The active preset can also be set in an optional `.env` file — a single line containing a valid preset name from `presets.json`. For example:

```
leonardo
```

(The preset can equally be passed with `-p/--preset` or via the `CINETIC_PRESET` environment variable; the default is `local`.)

### The Benchmark Config File

A JSON file describing a single experiment.

* **`global_options`**: Settings applied to the entire test (e.g., `numnodes`, `ppn`, `timeout`). To pin the job to exact hosts, set `nodelist` to a list of hostnames (this overrides `numnodes` and is what the TUI Topology Map / Node List write).
* **`applications`**: A dictionary where each key is a numeric ID and the value describes an application to run.

  * `path`: Path to the Python wrapper file.
  * `args`: String of arguments for the executable.
  * `collect`: `true` if data should be collected, `false` otherwise.
  * `start`: When to start the app — `"0"` (immediately), `"<N>"` (after an `N`-second delay), or `"s<id>"` (after app `<id>` finishes).
  * `end`: When to terminate the app.

    * `""` (empty string): The app is a **victim** — the framework waits for it to finish naturally.
    * `"f"`: The app is an **aggressor** — it is force-terminated once all victims finish.
    * `"<N>"`: The app is terminated after `N` seconds.

## 📜 License

This project is released under the MIT License. See the `LICENSE` file for details.

