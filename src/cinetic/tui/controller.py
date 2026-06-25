import os
import threading
from typing import Callable, Dict

# Importa il motore e i modelli dalla nuova posizione
from ..core.engine import Engine
from ..core.models import BenchmarkState

LogCallback = Callable[[str], None]

class TUIController:
    def __init__(self, log_callback: LogCallback):
        self.log = log_callback

    def _prepare_environment(self, tui_settings: Dict[str, str], selected_preset: str) -> Dict[str, str]:
        execution_env = os.environ.copy()
        
        if selected_preset != "Custom":
            tui_settings["CINETIC_SYSTEM"] = selected_preset

        for key, value in tui_settings.items():
            if isinstance(value, str) and value == "__CWD__":
                tui_settings[key] = os.getcwd() + "/"
        
        execution_env.update(tui_settings)

        for key, value in execution_env.items():
            if isinstance(value, str):
                execution_env[key] = os.path.expandvars(value)
        
        return execution_env

    def _execute_benchmark_logic(self, benchmark_config: dict, tui_settings: Dict[str, str], selected_preset: str):
        self.log("[bold blue]Preparing to run benchmark...[/]")
        
        try:
            # 1. Prepara l'ambiente
            execution_env = self._prepare_environment(tui_settings, selected_preset)
            self.log("Environment prepared.")

            # 2. Istanzia ed esegui il motore
            self.log("[bold red]Starting benchmark engine...[/]")
            engine = Engine(log_callback=self.log)
            # NOTA: il motore non ha più bisogno di un file di config, passiamo il dizionario
            engine.run(
                config=benchmark_config, 
                environment=execution_env,
            )
            self.log(f"\n[bold green]Benchmark finished successfully.[/]")

        except Exception as e:
            self.log(f"[bold red]An error occurred in the benchmark engine: {e}[/]")

    def run_in_thread(self, benchmark_config: dict, tui_settings: Dict[str, str], selected_preset: str):
        thread = threading.Thread(
            target=self._execute_benchmark_logic,
            args=(benchmark_config, tui_settings, selected_preset)
        )
        thread.start()
