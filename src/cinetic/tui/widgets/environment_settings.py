from textual.app import ComposeResult
from textual.containers import VerticalScroll, Horizontal, Container
from textual.widgets import Button, Input, Select, Static, TabbedContent, TabPane, TextArea
from textual.message import Message
from .variable_row import VariableRow
import json
import os

class EnvironmentSettings(Container):
    
    class EnvChanged(Message):
        def __init__(self, new_env: dict):
            self.new_env = new_env
            super().__init__()

    def __init__(self):
        super().__init__()
        self.presets = self._load_presets()
        
        # Load logic (.env) remains same...
        selected_preset = ""
        if os.path.exists(".env"):
            try:
                with open(".env", "r") as f: selected_preset = f.read().strip()
            except: pass
        else: selected_preset = "local"
        
        if selected_preset not in self.presets: selected_preset = "local" # Fallback sicuro
        self.current_preset_name = selected_preset 

    def _load_presets(self) -> dict:
        try:
            with open("presets.json", "r") as f: return json.load(f)
        except: return {"local": {"env": {}, "sbatch": [], "header": []}}

    def _save_presets(self):
        with open("presets.json", "w") as f:
            json.dump(self.presets, f, indent=4)

    def compose(self) -> ComposeResult:
        # Top Bar (Select + Save)
        preset_options = [(name, name) for name in self.presets if name != "Custom"]
        preset_options.append(("Custom", "Custom"))

        with Horizontal(classes="top_bar"):
            yield Static("Presets:", classes="label")
            yield Select(preset_options, value=self.current_preset_name, id="preset_select")
            yield Static("", classes="spacer")
            with Horizontal(id="custom_save_area", classes="hidden"):
                yield Button("Save", id="save_preset_btn", variant="success")
                yield Input(placeholder="New Preset Name...", id="custom_preset_name")

        # Main Content with Tabs
        with TabbedContent():
            
            # TAB 1: Environment Variables (Existing logic)
            with TabPane("Environment Variables", id="tab_env"):
                yield VerticalScroll(id="variable_list")
                yield Button("+ Add Variable", id="add_variable_btn", variant="primary")
            
            # TAB 2: SBATCH Directives (New)
            with TabPane("SBATCH Defaults", id="tab_sbatch"):
                yield Static("Enter one directive per line (e.g. --partition=boost_usr_prod)", classes="help_text")
                yield TextArea(id="sbatch_area", language="bash")

            # TAB 3: Header Commands (New)
            with TabPane("Header Commands", id="tab_header"):
                yield Static("Shell commands to run before python (e.g. module load ...)", classes="help_text")
                yield TextArea(id="header_area", language="bash")

    def on_mount(self) -> None:
        self.load_preset(self.current_preset_name)

    def load_preset(self, name: str):
        # 1. Load ENV (Merge _common + preset)
        container = self.query_one("#variable_list")
        container.remove_children()
        
        common_data = self.presets.get("_common", {})
        preset_data = self.presets.get(name, {})

        # Helper per gestire la retrocompatibilità (se il json è vecchio/piatto)
        def get_env(data): return data.get("env", data) if "env" in data else data
        def get_list(data, key): return data.get(key, [])

        final_env = get_env(common_data).copy()
        final_env.update(get_env(preset_data))

        for key, value in final_env.items():
            if isinstance(value, str): # Safety check
                container.mount(VariableRow(key, value))

        # 2. Load SBATCH & HEADER (Direct load, logicamente separiamo common e preset nell'UI? 
        # Per semplicità di editing, mostriamo l'unione modificabile o solo quelli del preset?
        # DECISIONE: In Custom Mode si edita tutto. In Read Mode mostriamo tutto.)
        
        # Nota: Qui mostriamo la lista completa flatten per semplicità di editing
        full_sbatch = get_list(common_data, "sbatch") + get_list(preset_data, "sbatch")
        full_header = get_list(common_data, "header") + get_list(preset_data, "header")

        self.query_one("#sbatch_area", TextArea).text = "\n".join(full_sbatch)
        self.query_one("#header_area", TextArea).text = "\n".join(full_header)

        self._notify_change()

    def _gather_current_state(self):
        # Env Rows
        rows = self.query(VariableRow)
        env_dict = {row.key: row.value for row in rows if row.key}
        
        # Text Areas
        sbatch_text = self.query_one("#sbatch_area", TextArea).text
        sbatch_list = [line.strip() for line in sbatch_text.splitlines() if line.strip()]

        header_text = self.query_one("#header_area", TextArea).text
        header_list = [line.strip() for line in header_text.splitlines() if line.strip()]

        return {
            "env": env_dict,
            "sbatch": sbatch_list,
            "header": header_list
        }

    # Metodo pubblico chiamato da App.py per ottenere lo stato completo
    # (env + sbatch + header), così le direttive SBATCH/header inserite
    # nella UI vengono propagate al config e finiscono nel job file.
    def get_full_state(self) -> dict:
        return self._gather_current_state()

    # Metodo pubblico chiamato da App.py al caricamento di una config,
    # per ripopolare le aree SBATCH/Header con i valori salvati.
    def set_sbatch_header(self, sbatch_list: list, header_list: list) -> None:
        self.query_one("#sbatch_area", TextArea).text = "\n".join(sbatch_list or [])
        self.query_one("#header_area", TextArea).text = "\n".join(header_list or [])

    # Metodo pubblico chiamato da App.py per ottenere la config completa
    @property
    def current_env_dict(self) -> dict:
        # Nota: App.py si aspetta un dizionario piatto per os.environ nell'uso legacy,
        # MA noi abbiamo aggiornato orchestrator.py per gestire la struttura.
        # Tuttavia, App.py potrebbe usare questo per la visualizzazione immediata.
        # Ritorniamo la struttura completa. App.py dovrà essere aggiornato se si aspetta solo env.
        return self._gather_current_state()["env"] 

    # Metodo per salvare il preset custom
    def save_custom_preset(self):
        name_input = self.query_one("#custom_preset_name", Input)
        new_name = name_input.value.strip()
        if not new_name or new_name == "Custom": return
        
        # Salviamo la struttura completa
        self.presets[new_name] = self._gather_current_state()
        self._save_presets()
        # ... update UI options ...
        self.app.notify(f"Preset '{new_name}' saved.")

    def _notify_change(self):
         # Manda solo la parte ENV perché EnvironmentSettings.EnvChanged è usato per 
         # aggiornare variabili globali che forse servono ad altro.
         # Se serve tutto, bisognerebbe aggiornare il messaggio EnvChanged.
         self.post_message(self.EnvChanged(self.current_env_dict))

    # Event Handlers (Button presses, Select changes) rimangono simili ma chiamano load_preset/save_custom
