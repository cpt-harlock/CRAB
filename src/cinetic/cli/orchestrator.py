import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, Any

# Aggiungi 'src' al path di sistema PRIMA di qualsiasi altro import custom
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from cinetic.compat import apply_legacy_env
from cinetic.core.engine import Engine

def load_environment_config(preset_arg: str) -> Dict[str, Any]:
    presets_filename = "presets.json"
    print(f"Info: Loading preset '{preset_arg}' from {presets_filename}", flush=True)
    try:
        with open(presets_filename, 'r') as f:
            all_presets = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"The presets file '{presets_filename}' was not found.")

    if preset_arg not in all_presets:
        raise KeyError(f"The preset '{preset_arg}' was not found in {presets_filename}.")

    # Carica _common e il preset specifico
    common_preset = all_presets.get("_common", {})
    target_preset = all_presets[preset_arg]

    # 1. Merge Environment Variables (Dict update)
    final_env = common_preset.get("env", {}).copy()
    final_env.update(target_preset.get("env", {}))

    # Assicuriamo che CINETIC_SYSTEM sia impostato
    if "CINETIC_SYSTEM" not in final_env:
        final_env["CINETIC_SYSTEM"] = preset_arg

    # 2. Merge SBATCH directives (List extend)
    # L'ordine è: Common -> Preset. (Engine poi aggiungerà Experiment overrides)
    final_sbatch = common_preset.get("sbatch", []) + target_preset.get("sbatch", [])

    # 3. Merge Header commands (List extend)
    final_header = common_preset.get("header", []) + target_preset.get("header", [])

    # Restituiamo una struttura configurata completa
    return {
        "env": final_env,
        "sbatch": final_sbatch,
        "header": final_header
    }

def prepare_execution_environment(env_dict: Dict[str, str]) -> Dict[str, str]:
    """Processa SOLO le variabili d'ambiente (sostituzione __CWD__ e expandvars)"""
    execution_env = os.environ.copy()
    processed_env = {}
    
    for key, value in env_dict.items():
        if isinstance(value, str):
            value = value.replace("__CWD__", os.getcwd())
        processed_env[key] = str(value)
    
    execution_env.update(processed_env)
    
    final_env = {}
    for key, value in execution_env.items():
        final_env[key] = os.path.expandvars(value)
    return final_env

def run_from_cli():
    # Seed CINETIC_* from any legacy CRAB_* in the surrounding shell/env.
    apply_legacy_env()

    # --- WORKER MODE ---
    if "--worker" in sys.argv:
        try:
            workdir_index = sys.argv.index("--workdir") + 1
            work_dir = sys.argv[workdir_index]

            config_file = os.path.join(work_dir, 'config.json')
            env_file = os.path.join(work_dir, 'environment.json')

            print(f"--- [WORKER MODE DETECTED] Work dir: {work_dir} ---", flush=True)

            with open(config_file, 'r') as f:
                benchmark_config = json.load(f)
            
            # NOTA: environment.json ora contiene solo le ENV vars processate dall'orchestrator
            with open(env_file, 'r') as f:
                execution_env = json.load(f)

            # Legacy snapshots (older runs) may carry CRAB_* keys; mirror them.
            apply_legacy_env(execution_env)

            print(f"--- [WORKER] Environment loaded. Starting engine. ---", flush=True)


            # Time execution
            start = time.time()

            engine = Engine(log_callback=print)
            engine.run(
                config=benchmark_config, 
                environment=execution_env,
                is_worker=True,
                output_dir=work_dir
            )

            elapsed_time = time.time() - start
            total = timedelta(seconds=int(elapsed_time))

            print(f"--- [WORKER] Engine run finished. ---", flush=True)
            print(f"--- Took: " + str(total) + " ---", flush=True)

        except Exception as e:
            print(f"[WORKER FATAL ERROR] {e}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc()
            sys.exit(1)
    
    # --- ORCHESTRATOR MODE ---
    else:
        parser = argparse.ArgumentParser(description="CINETIC Benchmarking Orchestrator.")
        parser.add_argument("-c", "--config", dest="app_config_file", required=True, help="Path to the JSON benchmark config.")
        parser.add_argument("-p", "--preset", help="Name of the preset to use.")
        parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
        args = parser.parse_args()

        try:
            selected_preset = args.preset or os.environ.get("CINETIC_PRESET")
            if os.path.exists(".env") and not selected_preset:
                with open(".env", "r") as f:
                    selected_preset = f.read().strip()
            
            if not selected_preset:
                selected_preset = "local"

            # 1. Carica la configurazione strutturata (Env, Sbatch, Header)
            preset_config = load_environment_config(selected_preset)
            
            # 2. Prepara le variabili d'ambiente (risolve __CWD__ etc)
            execution_env = prepare_execution_environment(preset_config["env"])
            
            # 3. Carica il config dell'esperimento
            with open(args.app_config_file, 'r') as f:
                benchmark_config = json.load(f)

            # 4. Inietta le configurazioni di sistema nelle global_options del benchmark
            # Questo permette all'Engine di accedere a sbatch/header di sistema
            if "global_options" not in benchmark_config:
                benchmark_config["global_options"] = {}
            
            benchmark_config["global_options"]["system_sbatch"] = preset_config["sbatch"]
            benchmark_config["global_options"]["system_header"] = preset_config["header"]

            print("-" * 50)
            print(f"Avvio del motore con il preset '{selected_preset}'...")
            print("-" * 50)

            engine = Engine(log_callback=print)
            engine.run(
                config=benchmark_config, 
                environment=execution_env,
                is_worker=False
            )

            print("-" * 50)
            print("Orchestration complete. Job submitted to SLURM.")
            print("-" * 50)

        except Exception as e:
            print(f"[ORCHESTRATOR FATAL ERROR] {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            sys.exit(1)
