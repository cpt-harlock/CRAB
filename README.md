# ⚡ CINETIC — Co-running INterference & nEtwork-Topology Investigation for Clusters
[![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Build Status](https://img.shields.io/badge/build-passing-brightgreen)](https://github.com/actions)

**CINETIC** is a flexible and powerful framework for executing, collecting, and analyzing high-performance benchmarks (HPC), optimized for clusters managed by **Slurm**. It allows you to orchestrate combinations of applications, manage system-specific environments, and automate the entire benchmarking process — with a focus on studying **network congestion** caused by co-running applications (victims vs. aggressors).

![asciicast](https://user-images.githubusercontent.com/11363902/203875389-918931a5-e110-4107-8854-c8c3656ab3e2.gif)

## ✨ Key Features

*   **Dual Interface**: Use it either through a **Textual User Interface (TUI)** for interactive usage or a **Command Line Interface (CLI)**
*   **Advanced Environment Management**: Easily define and switch between system environments (e.g., `lumi`, `leonardo`, ecc.) via a centralized preset system.
*   **Complex Application Mixes**: Run multiple applications simultaneously, defining "victims" (to be measured) and "aggressors" (to create interference).
*   **Automated Data Collection**: Automatically gathers performance data, analyzes it, and can stop execution once statistical convergence is reached.
*   **Standard Output Formats**: Saves collected data in the standard format CSV, ready for analysis with tools like Pandas or R.
*   **Extensible Architecture**: Add support for new benchmarks simply by creating a Python "wrapper," without modifying the framework core.

## 📚 Table of Contents

*   [🚀 Installation and Setup](#-installation-and-setup)
*   [🕹️ Using the Framework](#-using-the-framework)
    *   [TUI Mode (Interactive)](#tui-mode-interactive)
    *   [CLI Mode (Command Line)](#cli-mode-command-line)
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
*   Access to a cluster with **Slurm** (for `auto` node mode) or an environment with **MPI**.

### Installation Steps

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/SharkGamerZ/CRAB
    cd crab
    ```

2.  **Create a virtual environment (recommended):**
    ```bash
    python -m venv .venv
    source .venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Cluster Environments:**
    Open the file `presets.json`. This file is the core of environment management. 
    Add or edit a section for each system you want to run benchmarks on.

    #TODO: specify which ENV are necessary to run.

    ```json
    {
        "_common": {
            "CINETIC_ROOT": "/absolute/path/to/crab"
        },
        "my_cluster": {
            "CINETIC_WL_MANAGER": "slurm",
            "CINETIC_CC": "mpicc",
            "CINETIC_PINNING_FLAGS": "--cpu-bind=core"
        },
        "local_pc": {
            "CINETIC_WL_MANAGER": "mpi",
            "CINETIC_MPIRUN": "mpirun"
        }
    }
    ```

## 🕹️ Using the Framework

You can interact with CINETIC in two ways: through the TUI or the CLI.

### TUI Mode (Interactive)

The TUI is ideal for configuring and launching experiments visually and interactively.

**How to start it:**
```bash
python tui.py
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
python cli.py --preset <preset_name> <path_to_config.json>
```

* `--preset <preset_name>`: Specifies which environment to use, defined in `presets.json` (e.g., `my_cluster`), default is 'local'.
* `<path_to_config.json>`: The JSON file describing the experiment.

**Example:**

```bash
python cli.py --preset my_cluster examples/stress_test.json
```

Logs will be printed to the terminal, and data will be stored in the `data/` directory (or wherever `datapath` is set).

## 🏗️ Framework Architecture

The framework is designed with a clear separation of responsibilities:

1. **Entrypoints (`cli.py` / `tui.py`)**: The user interfaces (CLI or TUI). Their only job is to collect configuration, prepare the environment (`os.environ`), and start the engine.
2. **Engine (`engine.py`)**: The core of the framework. Receives a prepared environment and configuration. It handles:

   * Node allocation (via Slurm, if used).
   * Application scheduling.
   * Benchmark process launching through the workload manager.
   * Completion monitoring, data collection, and convergence checking.
3. **Workload Manager (`src/cinetic/core/wl_manager/*.py`)**: Specialized modules that translate a request ("run this command on these nodes") into system-specific commands (e.g., `srun, mpirun ...`).
4. **Application Wrappers (`wrappers/*.py`)**: Small Python modules that "wrap" a specific benchmark, teaching the framework how to run it and interpret its output.

## 🧩 Adding a New Benchmark

Integrating a new executable into the framework is simple and does not require modifying core code. You just need to create a "wrapper."

### Wrapper Structure

1. **Create a new Python file** in `wrappers/`, e.g. `my_benchmark.py`.
2. Inside it, define a class named `app` inheriting from one the base class (`base`).

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

Defines system environments.

* `_common`: A special object with environment variables shared by all presets.
* `"preset_name"`: An object defining variables for a specific system. These override `_common` values.

### The `.env` File
The name of the used preset can be specified in a optional `.env` file.
The content of the file should only be a valid name of a prest present in `preset.json`.
Example:
```
leonardo
```

### The Benchmark Config File

A JSON file describing a single experiment.

* **`global_options`**: Settings applied to the entire test (e.g., `numnodes`, `ppn`, `timeout`).
* **`applications`**: A dictionary where each key is a numeric ID and the value describes an application to run.

  * `path`: Path to the Python wrapper file.
  * `args`: String of arguments for the executable.
  * `collect`: `true` if data should be collected, `false` otherwise.
  * `start`: Delay (in seconds) before starting the app.
  * `end`: When to terminate the app.

    * `""` (empty string): The app is a "victim." The framework waits for it to finish naturally.
    * `"f"`: The app is an "aggressor." It will be force-terminated once all victims finish.
    * `<number>`: The app will be terminated after a fixed number of seconds.

## 📜 License

This project is released under the MIT License. See the `LICENSE` file for details.

