from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Button, Header, Footer, RichLog
from textual import on, work
from textual.reactive import reactive
from textual_fspicker import FileSave, FileOpen
import json
import os

from .messages import SaveConfiguration, LoadConfiguration, RunBenchmark
from .widgets.tab_selector import TabSelector
from .widgets.applications_setup import ApplicationSetup
from .widgets.benchmark_options import BenchmarkOptions
from .widgets.environment_settings import EnvironmentSettings

from .controller import TUIController

class CineticApp(App):
    CSS_PATH = "assets/cinetic.tcss"
    TITLE = "CINETIC"
    SUB_TITLE = "co-running interference & network-topology investigation"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("l", "load", "Load"),
        ("s", "save", "Save"),
        ("question_mark", "about", "About"),
    ]

    current_tab = reactive(0)

    def __init__(self):
        super().__init__()
        self.current_environment_settings = self._load_default_env()

        # Initialize the controller, passing the logging callback.
        self.controller = TUIController(log_callback=self.log_to_tui)

        self.applications_container = ApplicationSetup(self)
        self.benchmark_container = BenchmarkOptions(self)
        self.env_container = EnvironmentSettings()
        self.log_container = Vertical(
            RichLog(id="runner-log", highlight=True, classes="runner-log-tall"),
            id="log-view-container"
        )
    
    def log_to_tui(self, message: str):
        # Callback the controller uses to push log lines into the TUI.
        log = self.query_one("#runner-log", RichLog)
        self.call_from_thread(log.write, message)

    def action_about(self) -> None:
        self.notify(
            "CINETIC — co-running interference & network-topology "
            "investigation for HPC clusters.",
            title="CINETIC", timeout=6)
    
    def _load_default_env(self):
        try:
            with open("presets.json", "r") as f:
                presets = json.load(f)
                common_vars = presets.get("_common", {})
                local_vars = presets.get("local", {})
                common_vars.update(local_vars)
                return common_vars
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
    
    def compose(self) -> ComposeResult:
        yield Header()
        yield TabSelector(id="tab-selector", app_ref=self)
        with Container(id="main-content-area"):
            yield self.applications_container
            yield self.benchmark_container
            yield self.env_container
            yield self.log_container
        yield Footer()

    def on_mount(self): 
        self.show_tab(0)

    def on_environment_settings_env_changed(self, message: EnvironmentSettings.EnvChanged): 
        """Listen for changes from the environment settings widget."""
        self.current_environment_settings = message.new_env

    def save_benchmark_state(self):
        if self.applications_container and hasattr(self.applications_container, 'save_current_form_state'):
            self.applications_container.save_current_form_state()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id and event.button.id.startswith("tab-"):
            index = int(event.button.id.split("-")[1])
            self.show_tab(index)
            event.stop()

    def show_tab(self, index: int):
        if self.current_tab == 0 and index != 0: self.save_benchmark_state()
        self.current_tab = index
        self.applications_container.display = (index == 0)
        self.benchmark_container.display = (index == 1)
        self.env_container.display = (index == 2)
        self.log_container.display = (index == 3)
        self.update_tabs()

    def update_tabs(self):
        for i, tab_button in enumerate(self.query(".tab")):
            tab_button.variant = "primary" if i == self.current_tab else "default"


    def key_space(self) -> None:
        self.handle_run_request()

    def key_l(self) -> None:
        self.load_form_data()

    def key_s(self) -> None:
        self.save_form_data()

    def key_escape(self) -> None:
        self.query().blur()


    @on(SaveConfiguration)
    @work
    async def save_form_data(self) -> None:
        """
        Handles the request to save the complete configuration.
        Gathers data from all main widgets and saves it to a JSON file.
        """

        # 1. Gather data from the main widgets
        global_options_state = self.benchmark_container.get_state()
        applications_state = self.applications_container.get_state()

        # Include SBATCH directives / header commands from the Environment tab,
        # stored under global_options to match the runtime config structure.
        env_state = self.env_container.get_full_state()
        global_options_state["system_sbatch"] = env_state.get("sbatch", [])
        global_options_state["system_header"] = env_state.get("header", [])

        # 2 Build the complete data structure
        data_to_save = {
            "global_options": global_options_state,
            "applications": applications_state
        }


        # 3. Prompt the user for the file where to save the config
        try:
            file_path = await self.push_screen_wait(FileSave())
            if not file_path:
                self.notify("Save cancelled.", severity="warning")
                return

            file_path_str = str(file_path)
            if not file_path_str.endswith(".json"):
                file_path_str += ".json"
            # 4. Save the data to the specified file
            with open(file_path_str, "w") as f:
                json.dump(data_to_save, f, indent=4)
            self.notify(f"Configuration saved to {os.path.basename(file_path_str)}", severity="information")

        except Exception as e:
            self.notify(f"Error saving file: {e}", severity="error")

    @on(LoadConfiguration)
    @work
    async def load_form_data(self) -> None:
        """
        Handles the request to load a complete configuration.
        Loads data from a JSON file and populates the main widgets accordingly.
        """
        try:
            file_path = await self.push_screen_wait(FileOpen())
            if not file_path:
                self.notify("Load cancelled.", severity="warning")
                return

            file_path_str = str(file_path)
            with open(file_path_str, "r") as f:
                data_loaded = json.load(f)

            # Checks if the loaded data contains the expected sections
            if "global_options" not in data_loaded or "applications" not in data_loaded:
                self.notify("Invalid configuration file: missing required sections.", severity="error")
                return

            # Load data into the respective containers
            loaded_global = data_loaded["global_options"]
            self.benchmark_container.set_state(loaded_global)
            await self.applications_container.set_state(data_loaded["applications"])

            # Restore SBATCH directives / header commands into the Environment tab
            self.env_container.set_sbatch_header(
                loaded_global.get("system_sbatch", []),
                loaded_global.get("system_header", []),
            )

            self.notify(f"Configuration loaded from {os.path.basename(file_path_str)}", severity="information")

        except FileNotFoundError:
            self.notify("File not found.", severity="error")
        except json.JSONDecodeError:
            self.notify("Invalid JSON format in the file.", severity="error")
        except Exception as e:
            self.notify(f"Error loading file: {e}", severity="error")

    @on(RunBenchmark)
    @work
    async def handle_run_request(self) -> None:
        """Handle the benchmark run request."""
        # 1. Prepare the TUI.
        log = self.query_one("#runner-log", RichLog)
        log.clear()
        self.show_tab(3)

        # 2. Collect the benchmark configuration from the UI.
        self.save_benchmark_state()
        global_options_state = self.benchmark_container.get_state()
        applications_state = self.applications_container.get_state()

        # 3. Collect the environment settings from the TUI (env + sbatch + header).
        env_state = self.env_container.get_full_state()
        selected_preset = self.env_container.current_preset_name

        # Inject the SBATCH directives and header commands into global_options,
        # exactly as the CLI orchestrator does, so the Engine writes them into
        # the job file.
        global_options_state["system_sbatch"] = env_state.get("sbatch", [])
        global_options_state["system_header"] = env_state.get("header", [])

        benchmark_config = {
            "global_options": global_options_state,
            "applications": applications_state
        }

        tui_settings = env_state.get("env", {}).copy()

        # 4. Use the controller to run the benchmark in a thread.
        self.controller.run_in_thread(
            benchmark_config=benchmark_config,
            tui_settings=tui_settings,
            selected_preset=selected_preset
        )
