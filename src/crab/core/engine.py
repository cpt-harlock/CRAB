import subprocess
import numpy as np
import scipy.stats as st
import math
import time
import importlib.util
import pathlib
import sys
import os
import datetime
import pandas
import shlex
import json
import shutil
from typing import List, Dict, Any, Callable, Optional, Union

# =============================================================================
# 1. DATA CONTAINERS & UTILITIES
# =============================================================================

def normalize_nodelist(nodelist: Any) -> List[str]:
    """Normalize a config 'nodelist' into an ordered, de-duplicated host list.

    Accepts a Python list or a string with hosts separated by commas and/or
    whitespace (e.g. "node01,node02" or "node01 node02"). Returns [] if empty.
    Note: items are taken verbatim, so already-expanded hostnames are expected
    (the topology selector emits explicit hostnames, not Slurm range syntax).
    """
    if not nodelist:
        return []
    if isinstance(nodelist, str):
        tokens = [h.strip() for h in nodelist.replace(',', ' ').split()]
    else:
        tokens = [str(h).strip() for h in nodelist]

    seen = set()
    result = []
    for host in tokens:
        if host and host not in seen:
            seen.add(host)
            result.append(host)
    return result


class DataContainer:
    """Holds runtime metrics for a specific application."""
    def __init__(self, app_id: int, conv_goal: bool, label: str, unit: str, msg_size: int = 0):
        self.app_id = app_id
        self.conv_run = 0
        self.label = label
        self.unit = unit
        self.conv_goal = conv_goal
        self.converged = False
        self.num_samples = []
        self.data = []
        self.msg_size = msg_size

    def get_title(self) -> str:
        return f"{self.app_id}_{self.label}_{self.unit}"

    def md_to_list(self) -> List[Any]:
        return [self.app_id, self.label, self.unit, self.conv_goal, self.converged, self.conv_run, self.msg_size] + self.num_samples

def check_CI(container_list: List[DataContainer], alpha: float, beta: float, converge_all: bool, run: int) -> bool:
    """Checks statistical convergence based on Confidence Intervals (CI)."""
    for container in container_list:
        if (not container.converged) and (converge_all or container.conv_goal):
            n = len(container.data)
            if n <= 1: continue 
            
            mean = np.mean(container.data)
            sem = st.sem(container.data)
            
            if sem == 0:
                container.converged = True
                container.conv_run = run
                continue
            
            CI_lb, CI_ub = st.t.interval(1 - alpha, n - 1, loc=mean, scale=sem)
            if (CI_ub - CI_lb) < beta * mean:
                container.converged = True
                container.conv_run = run

    check = True
    for container in container_list:
        if (converge_all or container.conv_goal):
            check = check and container.converged
    return check

def run_job(job, wlmanager, ppn: int, pre_commands: List[str] = None):
    """launches an application process via the workload manager."""
    if not job.node_list:
        raise Exception(f"Application {job.id_num} has 0 allocated nodes.")
    
    # Passa pre_commands al workload manager
    cmd_string = wlmanager.run_job(job.node_list, ppn, job.run_app(), pre_commands=pre_commands)
    
    if not cmd_string:
        cmd_string = "echo a > /dev/null"
        raise Exception
    
    cmd = shlex.split(cmd_string)
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
    job.set_process(process)

def end_job(job):
    """Forcefully terminates a job and retrieves output."""
    if hasattr(job, 'process') and job.process:
        job.process.kill()
        out, err = job.process.communicate()
        job.set_output(out, err)

def wait_timed(job, timeout_sec: float) -> bool:
    """Waits for a job with a timeout. Returns True if timed out."""
    try:
        out, err = job.process.communicate(timeout=timeout_sec)
        job.set_output(out, err)
        return False
    except subprocess.TimeoutExpired:
        end_job(job)
        return True

def log_data(out_format: str, path_prefix: str, data_containers: List[DataContainer]):
    """Aggregates and saves data to CSV or HDF."""
    apps_data = {}
    for container in data_containers:
        apps_data.setdefault(container.app_id, []).append(container)

    for app_id, containers in apps_data.items():
        all_metrics = []
        app_msg_size = containers[0].msg_size if containers else 0

        for container in containers:
            if not container.data or not container.num_samples: continue

            # Reconstruct run_id column
            run_ids = []
            for i, num in enumerate(container.num_samples):
                run_ids.extend([i + 1] * num)

            # Truncate mismatch
            min_len = min(len(run_ids), len(container.data))
            run_ids = run_ids[:min_len]
            container.data = container.data[:min_len]

            df = pandas.DataFrame({'run_id': run_ids, container.get_title(): container.data})
            df = df.set_index(['run_id', df.groupby('run_id').cumcount()])
            all_metrics.append(df)

        if not all_metrics: continue

        dataframe = pandas.concat(all_metrics, axis=1).reset_index()
        if 'level_1' in dataframe.columns: dataframe = dataframe.drop(columns=['level_1'])
        
        dataframe.insert(1, "msg_size", app_msg_size)
        
        file_name = f"{path_prefix}_app_{app_id}"
        if out_format == 'csv':
            dataframe.to_csv(f"{file_name}.csv", index=False)
        elif out_format == 'hdf':
            dataframe.to_hdf(f"{file_name}.h5", key='df', index=False)

# =============================================================================
# 2. NODE ALLOCATOR LOGIC
# =============================================================================

class NodeAllocator:
    """Encapsulates all strategies for mapping nodes to applications."""

    @staticmethod
    def get_abs_split(split_str: str, num_apps: int, num_nodes: int) -> List[int]:
        """Calculates absolute node counts based on percentage or equal split."""
        if split_str == 'e':
            split_list = [100.0 / num_apps] * num_apps
        else:
            split_list = [float(x) for x in split_str.split(':')]

        if sum(split_list) > 100.1: # float tolerance
            raise Exception("Splits percentages exceed 100.")
        
        split_list = split_list[:num_apps]
        split_absolute = []
        for split in split_list[:-1]:
            split_absolute.append(int(math.ceil(num_nodes * split / 100)))
        
        if num_apps == 1:
            split_absolute = [int(math.ceil(num_nodes * split_list[0] / 100))]
        else:
            split_absolute.append(num_nodes - sum(split_absolute))
            
        return split_absolute

    @staticmethod
    def allocate_linear(apps: List[Any], node_list: List[str], split_counts: List[int]):
        """Allocates contiguous blocks of nodes to applications."""
        idx = 0
        for app, count in zip(apps, split_counts):
            app.set_nodes(node_list[idx : idx + count])
            idx += count

    @staticmethod
    def allocate_interleaved(apps: List[Any], node_list: List[str], split_counts: List[int]):
        """Allocates nodes in a round-robin fashion."""
        num_apps = len(apps)
        alloc_lists = [[] for _ in range(num_apps)]
        counts_copy = list(split_counts)
        
        app_idx = 0
        node_idx = 0
        
        # While there are nodes to assign and demand exists
        while any(counts_copy) and node_idx < len(node_list):
            if counts_copy[app_idx] > 0:
                alloc_lists[app_idx].append(node_list[node_idx])
                counts_copy[app_idx] -= 1
                node_idx += 1
            app_idx = (app_idx + 1) % num_apps

        for app, a_list in zip(apps, alloc_lists):
            app.set_nodes(a_list)

    @staticmethod
    def allocate_partitioned(apps: List[Any], node_list: List[str], options: Dict[str, Any]):
        """
        Advanced allocation: divides nodes into partitions (Victim/Aggressor) 
        and applies sub-rules (Shared vs Dedicated) within partitions.
        """
        num_nodes = len(node_list)
        partition_split = options.get('partitionsplit', '100')
        layout = options.get('partitionlayout', 'l')
        local_rules = [x.strip() for x in options.get('allocationsplit', 'e').split('-')]

        # 1. Determine Partition Sizes
        if partition_split == 'e':
            # Auto-detect based on app partition_ids
            used_ids = set(getattr(a, 'partition_id', 0) for a in apps)
            max_p = max(used_ids) + 1 if used_ids else 1
            pt_counts = [int(math.ceil(num_nodes / max_p)) for _ in range(max_p)]
            # Adjust remainder
            diff = sum(pt_counts) - num_nodes
            if diff != 0: pt_counts[-1] -= diff
        else:
            percs = [float(x) for x in partition_split.split(':')]
            pt_counts = [int(math.ceil(num_nodes * p / 100)) for p in percs[:-1]]
            pt_counts.append(num_nodes - sum(pt_counts))

        # 2. Assign nodes to Partitions (Linear vs Interleaved)
        partitions_nodes = [[] for _ in range(len(pt_counts))]
        
        if layout == 'i':
            node_idx = 0
            while node_idx < num_nodes:
                for p_idx in range(len(pt_counts)):
                    if len(partitions_nodes[p_idx]) < pt_counts[p_idx]:
                        partitions_nodes[p_idx].append(node_list[node_idx])
                        node_idx += 1
                        if node_idx >= num_nodes: break
        else:
            idx = 0
            for p_idx, count in enumerate(pt_counts):
                partitions_nodes[p_idx] = node_list[idx : idx + count]
                idx += count

        # 3. Apply Local Rules to Apps in each Partition
        if len(local_rules) == 1 and len(partitions_nodes) > 1:
            local_rules = local_rules * len(partitions_nodes)

        for p_id, (p_nodes, p_rule) in enumerate(zip(partitions_nodes, local_rules)):
            p_apps = [a for a in apps if getattr(a, 'partition_id', 0) == p_id]
            if not p_apps: continue

            # Shared Mode ('100' or single app 'e')
            if p_rule == '100' or (p_rule == 'e' and len(p_apps) <= 1):
                for app in p_apps:
                    app.set_nodes(p_nodes)
            else:
                # Space Sharing within partition
                sub_split = NodeAllocator.get_abs_split(p_rule, len(p_apps), len(p_nodes))
                NodeAllocator.allocate_linear(p_apps, p_nodes, sub_split)

# =============================================================================
# 3. EXPERIMENT RUNNER (Context for a single experiment)
# =============================================================================

class ExperimentRunner:
    """
    Manages the lifecycle of a single experiment within the job.
    Isolates setup, execution, and teardown.
    """
    def __init__(self, exp_name: str, config: Dict[str, Any], global_options: Dict[str, Any], 
                 node_list: List[str], output_dir: str, log_fn: Callable):
        self.name = exp_name
        self.config = config
        self.global_opts = global_options
        self.node_list = node_list
        self.log = log_fn
        
        # Paths
        self.exp_dir = os.path.join(output_dir, self.name)
        os.makedirs(self.exp_dir, exist_ok=True)
        
        # State
        self.apps = []
        self.wlmanager = None
        self.data_containers = []
        self.ppn = int(global_options.get('ppn', 1))

    def setup(self):
        """Loads apps, workload manager, and calculates node layout."""
        self.log(f"[{self.name}] Setting up...")
        
        # 1. Load Applications
        self.apps = []
        app_configs = self.config.get("apps", {})
        sorted_keys = sorted(app_configs.keys(), key=lambda x: int(x) if x.isdigit() else x)
        
        # Dependency tracking
        dependency_map = {}
        static_schedule = []
        
        # Helper to load modules
        def load_module(path):
            name = pathlib.Path(path).stem
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None or spec.loader is None:
                raise ImportError(
                    f"'{path}' is not a loadable Python wrapper. "
                    f"Point the application path to a wrapper .py "
                    f"(e.g. in {os.environ.get('CRAB_WRAPPERS_PATH', 'wrappers')}), "
                    f"not the benchmark binary."
                )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod

        # WLM Loading
        wlm_name = os.environ.get("CRAB_WL_MANAGER", "slurm") # default
        wlm_path = f"./src/crab/core/wl_manager/{wlm_name}.py"
        self.wlmanager = load_module(wlm_path).wl_manager()

        # App Instantiation
        idx_counter = 0
        for key in sorted_keys:
            details = app_configs[key]
            path = details.get("path")
            if not path: continue

            # Controlla la ENV CRAB_WRAPPERS_PATH
            if not os.path.isabs(path) and "CRAB_WRAPPERS_PATH" in os.environ:
                path = os.path.join(os.environ["CRAB_WRAPPERS_PATH"], path)
            
            if not os.path.exists(path):
                 self.log(f"[ERROR] Wrapper not found at: {path}")
                 raise FileNotFoundError(f"Wrapper not found: {path}")

            # Load App Class
            mod_app = load_module(path)
            args = details.get("args", "")
            collect = details.get("collect", False)
            
            app_instance = mod_app.app(idx_counter, collect, args)
            
            # Timing & Partition Metadata
            # Un valore vuoto/whitespace (default della TUI) equivale a "start at 0".
            start_val = str(details.get("start", "0")).strip() or "0"
            manual_partition = details.get("partition")
            app_instance.partition_id = int(manual_partition) if manual_partition is not None else (0 if collect else 1)
            app_instance.start_string = start_val
            app_instance.config_end = str(details.get("end", "")).strip()
            
            self.apps.append(app_instance)
            idx_counter += 1

        # 2. Allocate Nodes
        mode = self.global_opts.get('allocationmode', 'l')
        
        # Merge experiment specific overrides into options for allocator
        alloc_options = self.global_opts.copy()
        # (Future: allow experiment config to override global_opts for splitting)
        
        if mode == 'p':
            NodeAllocator.allocate_partitioned(self.apps, self.node_list, alloc_options)
        elif mode == 'i':
            split = NodeAllocator.get_abs_split(alloc_options.get('allocationsplit', 'e'), len(self.apps), len(self.node_list))
            NodeAllocator.allocate_interleaved(self.apps, self.node_list, split)
        else: # linear
            split = NodeAllocator.get_abs_split(alloc_options.get('allocationsplit', 'e'), len(self.apps), len(self.node_list))
            NodeAllocator.allocate_linear(self.apps, self.node_list, split)

        # 3. Initialize Data Containers
        for app in self.apps:
            if app.collect_flag:
                # Parse msg_size if present in args (for logging)
                msg_size = 0
                tokens = str(app.args).split()
                if "-msgsize" in tokens:
                    try: 
                        msg_size = int(tokens[tokens.index("-msgsize")+1])
                    except: pass
                
                for meta in app.metadata:
                    self.data_containers.append(
                        DataContainer(app.id_num, meta["conv"], meta["name"], meta["unit"], msg_size)
                    )

    def execute(self):
        """Main execution loop (Setup -> Run -> Wait -> Converge)."""
        self.log(f"[{self.name}] Execution started.")

        # Esponiamo la directory dati dell'esperimento ai binari lanciati, così
        # un benchmark può scrivere file per-nodo lì (es. tournament_nb). Path
        # assoluto: i rank condividono il filesystem ma non hanno la CWD su exp_dir.
        os.environ["CRAB_NODE_RESULTS_DIR"] = os.path.abspath(self.exp_dir)

        # Params
        min_runs = int(self.global_opts.get('minruns', 10))
        max_runs = int(self.global_opts.get('maxruns', 20))
        timeout = float(self.global_opts.get('timeout', 1200.0))
        converge_all = bool(self.global_opts.get('convergeall', False))
        alpha = float(self.global_opts.get('alpha', 0.05))
        beta = float(self.global_opts.get('beta', 0.05))

        # Recupera l'header dalle opzioni globali (dove l'Orchestrator lo ha messo)
        # Default a lista vuota se non esiste
        system_header = self.global_opts.get('system_header', [])

        # Schedule Logic Preparation
        dependency_map = {}
        static_schedule = []
        rel_durations = {}
        
        # Build Schedule
        for i, app in enumerate(self.apps):
            # Start
            if app.start_string.startswith('s'):
                dependency_map[i] = int(app.start_string[1:])
            else:
                static_schedule.append((i, 's', float(app.start_string)))
            
            # End
            if app.config_end and app.config_end != 'f':
                val = float(app.config_end)
                if app.start_string.startswith('s'):
                     rel_durations[i] = val
                else:
                    static_schedule.append((i, 'k', val))

        runs = 0
        global_start = time.time()
        converged = False

        try:
            while True:
                # Exit conditions
                elapsed = time.time() - global_start
                if runs >= max_runs or (runs >= min_runs and converged) or elapsed >= timeout:
                    break

                self.log(f"[{self.name}] Run {runs+1}...")
                run_start = time.time()
                
                # Reset ephemeral schedule for this run
                curr_schedule = sorted(static_schedule, key=lambda x: x[2])
                curr_deps = dependency_map.copy()
                running = set()
                finished = set()

                # Inner Event Loop
                while True:
                    now = time.time() - run_start
                    
                    # 1. Time-based events
                    while curr_schedule and curr_schedule[0][2] <= now:
                        aid, action, _ = curr_schedule.pop(0)
                        if action == 's':
                            if aid not in running:
                                run_job(self.apps[aid], self.wlmanager, self.ppn, pre_commands=system_header)
                                running.add(aid)
                        elif action == 'k':
                            if aid in running:
                                end_job(self.apps[aid])
                                running.remove(aid)
                                finished.add(aid)

                    # 2. Check process status
                    for aid in list(running):
                        proc = self.apps[aid].process
                        if proc.poll() is not None:
                            # Il processo è terminato
                            try:
                                out, err = proc.communicate()
                                self.apps[aid].set_output(out, err)
                                
                                # --- INIZIO MODIFICA: Error Logging ---
                                if proc.returncode != 0:
                                    # Costruiamo il messaggio di errore
                                    error_msg = (
                                        f"\n[CRAB ERROR] Experiment '{self.name}' - App {aid} failed!\n"
                                        f"Return Code: {proc.returncode}\n"
                                    )
                                    
                                    # Decodifica STDERR (byte -> string) per sicurezza
                                    if err:
                                        decoded_err = err.decode('utf-8', errors='replace') if isinstance(err, bytes) else err
                                        error_msg += f"--- STDERR ---\n{decoded_err}\n"
                                    
                                    # Decodifica STDOUT (spesso MPI stampa errori qui)
                                    if out:
                                        decoded_out = out.decode('utf-8', errors='replace') if isinstance(out, bytes) else out
                                        error_msg += f"--- STDOUT TAIL ---\n{decoded_out[-2000:]}\n" # Ultimi 2000 caratteri
                                    
                                    error_msg += "------------------------------------------------\n"

                                    # 1. Stampa su sys.stderr (finisce in slurm_error.log)
                                    print(error_msg, file=sys.stderr, flush=True)
                                    
                                    # 2. Salva un file di log dedicato nella cartella dell'esperimento
                                    try:
                                        log_path = os.path.join(self.exp_dir, f"error_app_{aid}.log")
                                        with open(log_path, "w") as f:
                                            f.write(error_msg)
                                    except Exception as e:
                                        print(f"[CRAB WARNING] Could not write error log file: {e}", file=sys.stderr)
                                # --- FINE MODIFICA ---

                                # --- Dump raw stdout on success (solo se stiamo raccogliendo) ---
                                # Utile per ispezionare l'output grezzo del benchmark
                                # (quello che write_results() stampa) senza doverlo parsare.
                                elif self.apps[aid].collect_flag and out:
                                    decoded_out = out.decode('utf-8', errors='replace') if isinstance(out, bytes) else out
                                    try:
                                        stdout_path = os.path.join(self.exp_dir, f"stdout_app_{aid}.log")
                                        with open(stdout_path, "a") as f:
                                            f.write(f"=== Run {runs + 1} ===\n{decoded_out}\n")
                                    except Exception as e:
                                        print(f"[CRAB WARNING] Could not write stdout log file: {e}", file=sys.stderr)

                            except Exception as e:
                                self.log(f"[INTERNAL ERROR] Failed reading output for app {aid}: {e}")

                            running.remove(aid)
                            finished.add(aid)

                    # 3. Check Dependencies
                    started_deps = []
                    for waiter, target in curr_deps.items():
                        if target in finished:
                            run_job(self.apps[waiter], self.wlmanager, self.ppn, pre_commands=system_header)
                            running.add(waiter)
                            if waiter in rel_durations:
                                curr_schedule.append((waiter, 'k', now + rel_durations[waiter]))
                                curr_schedule.sort(key=lambda x: x[2])
                            started_deps.append(waiter)
                    for s in started_deps: del curr_deps[s]

                    if not curr_schedule and not curr_deps and not running:
                        break # Run finished
                    
                    time.sleep(0.05)

                # Collect Data
                c_idx = 0
                for app in self.apps:
                    if app.collect_flag and hasattr(app, 'process') and app.process.returncode == 0:
                        raw_data = app.read_data()
                        for series in raw_data:
                            self.data_containers[c_idx].data.extend(series)
                            self.data_containers[c_idx].num_samples.append(len(series))
                            c_idx += 1

                runs += 1
                if runs >= min_runs:
                    converged = check_CI(self.data_containers, alpha, beta, converge_all, runs)

        finally:
            self.teardown()

    def teardown(self):
        """Ensures all processes are killed before next experiment."""
        for app in self.apps:
            if hasattr(app, 'process') and app.process:
                if app.process.poll() is None:
                    try: app.process.kill() 
                    except: pass

    def save_results(self):
        """Persists data to disk."""
        if self.data_containers:
            out_fmt = self.global_opts.get('outformat', 'csv')
            prefix = os.path.join(self.exp_dir, 'data')
            log_data(out_fmt, prefix, self.data_containers)
            self.log(f"[{self.name}] Data saved to {self.exp_dir}")

# =============================================================================
# 4. ENGINE (Orchestrator & Worker Entry Point)
# =============================================================================

# ... (Imports e classi precedenti rimangono uguali) ...

class Engine:
    def __init__(self, log_callback: Callable[[str], None] = print):
        self.log = log_callback

    def run(self, config: Dict[str, Any], environment: Dict[str, Any], is_worker: bool = False, output_dir: str = None):
        if is_worker:
            self._run_worker(config, environment, output_dir)
        else:
            self._run_orchestrator(config, environment)

    def _generate_sbatch_header(self, global_opts: Dict[str, Any], data_directory: str) -> List[str]:
        """
        Generates the list of #SBATCH lines handling defaults, overrides, and security.
        """
        # Esplicita lista di nodi (es. dalla mappa topologica della TUI): vincola
        # il job esattamente a questi host e forza il conteggio nodi a combaciare.
        nodelist = normalize_nodelist(global_opts.get('nodelist'))
        num_nodes_directive = len(nodelist) if nodelist else global_opts.get('numnodes')

        # 1. Definizione dei Parametri Protetti (Il framework vince sempre)
        # Mappa: Chiave -> Valore calcolato dal framework
        protected_defaults = {
            'nodes': f"--nodes={num_nodes_directive}",
            'ntasks-per-node': f"--ntasks-per-node={global_opts.get('ppn', 1)}",
            # Alias comuni da bloccare
            'N': None,
            'n': None, # Blocchiamo -n per sicurezza se l'utente prova a passarlo
            # Quando Crab gestisce una selezione esplicita, blocca gli override utente.
            'nodelist': None,
            'w': None,  # alias breve di --nodelist
        }
        if nodelist:
            protected_defaults['nodelist'] = "--nodelist=" + ",".join(nodelist)

        # 2. Definizione dei Default Sovrascrivibili
        # Mappa: Chiave univoca -> Stringa completa direttiva
        directives_map = {
            'job-name': f"--job-name=crab_{global_opts.get('extrainfo', 'job')[:10]}",
            'output': f"--output={os.path.join(data_directory, 'slurm_output.log')}",
            'error': f"--error={os.path.join(data_directory, 'slurm_error.log')}",
            'time': f"--time={global_opts.get('walltime', '00:10:00')}"
        }

        # Uniamo i protetti alla mappa (per averli come base)
        for k, v in protected_defaults.items():
            if v: directives_map[k] = v


        # Recuero i default di sistema passati dall'Orchestrator
        system_defaults = global_opts.get('system_sbatch', [])

        # Parsiamo prima i system defaults (bassa priorità rispetto all'utente, alta rispetto ai base)
        for raw in system_defaults:
             key = raw.lstrip('-').split('=')[0]
             # Non sovrascriviamo i protected
             if key not in protected_defaults: 
                 directives_map[key] = raw


        # 3. Parsing Direttive Utente (dal JSON, Override Finale)
        user_directives = global_opts.get('sbatch_directives', [])
        
        # Supporto legacy: se l'utente passa un dict invece di una lista, lo convertiamo
        if isinstance(user_directives, dict):
            converted = []
            for k, v in user_directives.items():
                if v is True: converted.append(f"--{k}")
                elif v is False: continue
                else: converted.append(f"--{k}={v}")
            user_directives = converted

        for raw_directive in user_directives:
            directive = str(raw_directive).strip()
            
            # A. Security Check (Newline Injection)
            if '\n' in directive or '\r' in directive:
                self.log(f"[SECURITY WARN] Skipping directive containing newlines: {directive}")
                continue

            # B. Estrazione Chiave (Key Extraction)
            # Esempio: "--account=ABC" -> "account"
            # Esempio: "--exclusive" -> "exclusive"
            # Esempio: "-J jobname" -> "J"
            clean_str = directive.lstrip('-')
            if '=' in clean_str:
                key = clean_str.split('=')[0]
            else:
                key = clean_str.split()[0] # Gestisce casi rari come "-J name" se passati come stringa unica
            
            # C. Conflict Resolution
            if key in protected_defaults:
                self.log(f"[CONFIG WARN] User directive '{directive}' ignored. '{key}' is managed by Crab to ensure stability.")
                continue
            
            if key in ['output', 'error', 'o', 'e']:
                self.log(f"[CONFIG WARN] User overrode log path with '{directive}'. Standard logging might be lost.")
            
            # D. Apply (Last write wins for user defaults, except protected)
            directives_map[key] = directive

        # 4. Rendering
        # Restituiamo i valori (le stringhe complete)
        return [f"#SBATCH {v}" for v in directives_map.values()]

    def _run_orchestrator(self, config: Dict[str, Any], environment: Dict[str, Any]):
        self.log("Engine running in ORCHESTRATOR mode.")
        
        if "experiments" not in config:
            if "applications" in config:
                config["experiments"] = {"default_ex": {"apps": config.pop("applications")}}
            else:
                raise ValueError("Config must contain 'experiments' or 'applications'.")

        g_opts = config.get('global_options', {})
        data_path = g_opts.get('datapath', './data')

        # An explicit nodelist (e.g. from the topology selector) defines the node
        # count; fall back to the numnodes field otherwise.
        nodelist = normalize_nodelist(g_opts.get('nodelist'))
        if nodelist:
            num_nodes = len(nodelist)
            g_opts['numnodes'] = num_nodes  # keep downstream consumers consistent
        else:
            num_nodes = int(g_opts.get('numnodes'))

        # Setup Directory
        desc_file = os.path.join(data_path, "description.csv")
        os.makedirs(data_path, exist_ok=True)
        if not os.path.isfile(desc_file):
            with open(desc_file, 'w') as f:
                f.write('system,numnodes,extra,path\n')

        # 1. Genera timestamp base
        timestamp_str = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S-%f')
        
        # 2. Cerca il nome custom nelle opzioni
        custom_name = g_opts.get('name', '')
        
        if custom_name:
            # Sanificazione: mantieni solo alfanumerici, trattini e underscore
            # Sostituisci spazi o altri caratteri con '_'
            safe_name = "".join([c if c.isalnum() or c in ('-', '_') else '_' for c in str(custom_name)])
            # Formato: NAME_TIMESTAMP
            folder_name = f"{safe_name}_{timestamp_str}"
        else:
            # Fallback legacy: solo TIMESTAMP
            folder_name = timestamp_str

        # 3. Costruzione path finale
        runner_id = (environment.get("CRAB_SYSTEM", "unknown") + "/" + folder_name)
        data_directory = os.path.join(data_path, runner_id)
        # --------------------------------------

        os.makedirs(data_directory, exist_ok=True)

        with open(desc_file, 'a+') as f:
            f.write(f"{environment.get('CRAB_SYSTEM')},{num_nodes},{g_opts.get('extrainfo')},{data_directory}\n")

        with open(os.path.join(data_directory, 'config.json'), 'w') as f:
            json.dump(config, f, indent=4)
        with open(os.path.join(data_directory, 'environment.json'), 'w') as f:
            json.dump(environment, f, indent=4)

        # --- GENERAZIONE HEADER SBATCH DINAMICO ---
        sbatch_headers = self._generate_sbatch_header(g_opts, data_directory)

        script_path = os.path.join(data_directory, 'crab_job.sh')
        cmd = f"{sys.executable} {os.path.abspath(sys.argv[0])} --worker --workdir {data_directory}"
        
        with open(script_path, 'w') as f:
            f.write("#!/bin/bash\n\n")
            
            # Scrittura direttive calcolate
            for line in sbatch_headers:
                f.write(f"{line}\n")
            

            venv = os.path.join(os.getcwd(), '.venv/bin/activate')
            if os.path.exists(venv):
                f.write(f"\nsource {venv}\n")

            # Recuperiamo la lista passata dall'Orchestrator nel config
            system_header = g_opts.get('system_header', [])
            if system_header:
                f.write("\n# --- System Setup (Modules & Environment) ---\n")
                for line in system_header:
                    f.write(f"{line}\n")
            
            f.write(f"\n{cmd}\n")

        self.log(f"Submitting: sbatch {script_path}")
        # Capture both streams: sbatch prints submission errors (bad partition,
        # qos, account, ...) to stderr, which check_output would discard. Surface
        # them in the runner log instead of failing with an opaque exit code.
        result = subprocess.run(['sbatch', script_path], text=True,
                                capture_output=True)
        if result.returncode != 0:
            self.log(f"[bold red]Job submission failed: sbatch exited "
                     f"{result.returncode}.[/]")
            err = (result.stderr or "").strip()
            out = (result.stdout or "").strip()
            if err:
                self.log(err)
            if out:
                self.log(out)
            raise RuntimeError("sbatch submission failed — see the log above.")
        self.log(result.stdout.strip())

    def _run_worker(self, config: Dict[str, Any], environment: Dict[str, Any], output_dir: str):
        # ... (Il worker rimane identico a prima) ...
        # (Incolla qui il codice di _run_worker che hai già)
        self.log("--- [WORKER] Started ---")
        
        orig_env = os.environ.copy()
        os.environ.update(environment)
        
        try:
            node_file = "worker_nodelist.txt"
            with open(node_file, "w") as f:
                subprocess.call(["scontrol", "show", "hostnames", os.environ.get('SLURM_NODELIST')], stdout=f)
            nodes_df = pandas.read_csv(node_file, header=None)
            full_node_list = nodes_df.iloc[:, 0].tolist()
            
            global_opts = config.get('global_options', {})
            experiments = config.get('experiments', {})
            sorted_exp_ids = sorted(experiments.keys())

            for exp_id in sorted_exp_ids:
                exp_config = experiments[exp_id]
                self.log(f"\n=== Starting Experiment: {exp_id} ===")
                
                runner = ExperimentRunner(
                    exp_name=exp_id,
                    config=exp_config,
                    global_options=global_opts,
                    node_list=full_node_list,
                    output_dir=output_dir,
                    log_fn=self.log
                )
                try:
                    runner.setup()
                    runner.execute()
                    runner.save_results()
                except Exception as e:
                    self.log(f"[ERROR] Experiment {exp_id} failed: {e}")
                    import traceback
                    traceback.print_exc()
                finally:
                    runner.teardown()
                    time.sleep(2)
            
            self.log("--- [WORKER] All experiments finished ---")

        finally:
            os.environ.clear()
            os.environ.update(orig_env)
            if os.path.exists("worker_nodelist.txt"):
                os.remove("worker_nodelist.txt")
