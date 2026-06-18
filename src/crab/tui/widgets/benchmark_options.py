from textual.containers import Container, VerticalScroll, Horizontal
from textual.widgets import Button, DataTable, Input, Label, Select, Switch
from textual import on

import subprocess
import json
import os

from .topology_map import TopologyMapScreen
from crab.topology import Topology

class BenchmarkOptions(VerticalScroll):
    """Un widget per configurare ed eseguire un benchmark."""

    def __init__(self, app_ref):
        super().__init__()
        self.app_ref = app_ref
        # Hostnames chosen through the graphical topology selector (if used).
        self.selected_nodes: list[str] = []

    def on_mount(self) -> None:
        """Imposta il titolo del bordo quando il widget viene montato."""
        self.border_title = "Benchmark Configuration"

        data_table = self.query_one("#node_table", DataTable)
        data_table.add_column("Available Nodes")

        # The topology button is only relevant for the "topology" source.
        self.query_one("#open_topology", Button).display = False


    def compose(self):
        """Crea i widget figli per il form delle opzioni."""

        # --- Argomenti Posizionali Obbligatori ---
        with Container(classes="option-group"):
            yield Label("Nodes:", classes="option-label")
            yield Select([
                ("All Nodes", "auto"),
                ("Mixed Nodes", "mixed"),
                ("Idle Nodes", "idle"),
                ("From File", "file"),
                ("Topology Map", "topology")
            ], value="auto", id="nodes", classes="option-input")
            yield Input(placeholder="Path to node list file", id="node_file", classes="option-input")
            yield Button("🗺  Open Topology Map", id="open_topology", variant="primary")
            yield DataTable(id="node_table", classes="datatable")

        # --- Argomenti Opzionali ---
        with Container(classes="option-group"):
            yield Label("Number of Nodes:", classes="option-label")
            yield Input(placeholder="e.g., 4", id="numnodes", type="integer", classes="option-input")

        with Container(classes="option-group"):
            yield Label("Allocation Mode:", classes="option-label")
            yield Select([
                ("Linear", "l"),
                ("Cyclic", "c"),
                ("Random", "r"),
                ("Interleaved", "i"),
                ("+Random", "+r")
            ], value="l", id="allocationmode", classes="option-input")

        with Container(classes="option-group"):
            yield Label("Allocation Split:", classes="option-label")
            yield Input(placeholder="e.g., 50:50 or 'e' for even", value="e", id="allocationsplit", classes="option-input")

        with Container(classes="option-group"):
            yield Label("Minimum Runs:", classes="option-label")
            yield Input(value="10", id="minruns", type="integer", classes="option-input")

            yield Label("Maximum Runs:", classes="option-label")
            yield Input(value="1000", id="maxruns", type="integer", classes="option-input")

        with Container(classes="option-group"):
            yield Label("Timeout (seconds):", classes="option-label")
            yield Input(value="100.0", id="timeout", type="number", classes="option-input")

        with Container(classes="option-group"):
            yield Label("Alpha (Confidence):", classes="option-label")
            yield Input(value="0.05", id="alpha", type="number", classes="option-input")
            
        with Container(classes="option-group"):
            yield Label("Beta (Convergence):", classes="option-label")
            yield Input(value="0.05", id="beta", type="number", classes="option-input")

        with Container(classes="option-group"):
            yield Label("Processes Per Node:", classes="option-label")
            yield Input(value="1", id="ppn", type="integer", classes="option-input")

        with Container(classes="option-group"):
            yield Label("Converge All Metrics:", classes="option-label")
            yield Switch(value=True, id="convergeall", classes="option-input")

        with Container(classes="option-group"):
            yield Label("Output Format:", classes="option-label")
            yield Select([
                ("CSV", "csv"),
                ("HDF5", "hdf")
            ], value="csv", id="outformat", classes="option-input")

        with Container(classes="option-group"):
            yield Label("Runtime Output:", classes="option-label")
            yield Select([
                ("Standard Output", "stdout"),
                ("None", "none"),
                ("File", "file"),
                ("Append to File", "+file")
            ], value="stdout", id="runtimeout", classes="option-input")

        with Container(classes="option-group"):
            yield Label("Random Seed:", classes="option-label")
            yield Input(value="1", id="seed", type="integer", classes="option-input")

        with Container(classes="option-group"):
            yield Label("Data Path:", classes="option-label")
            yield Input(value="./data", id="datapath", classes="option-input")

        with Container(classes="option-group"):
            yield Label("Extra Info:", classes="option-label")
            yield Input(placeholder="Details of this specific execution", id="extrainfo", classes="option-input")

        with Container(classes="option-group"):
            yield Label("Replace Mix Args:", classes="option-label")
            yield Input(placeholder="e.g., server:1.2.3.4,client:5.6.7.8", id="replace_mix_args", classes="option-input")


    def get_state(self) -> dict:
        """
        Raccoglie lo stato corrente di tutte le opzioni di benchmark.

        Returns:
            Un dizionario con l'ID di ogni widget come chiave e il suo valore.
        """
        state = {}
        for widget in self.query(".option-input"):
            # Usiamo l'ID del widget come chiave per lo stato
            if widget.id:
                state[widget.id] = widget.value

        # Explicit topology selection -> pass an explicit nodelist to the engine.
        if state.get("nodes") == "topology" and self.selected_nodes:
            state["nodelist"] = list(self.selected_nodes)
        return state

    def set_state(self, state: dict) -> None:
        """
        Imposta lo stato del form in base a un dizionario di dati.

        Args:
            state: Un dizionario dove le chiavi corrispondono agli ID dei widget.
        """
        if not state:
            return

        # 'nodelist' is not a widget: restore it into the topology selection.
        state = dict(state)
        nodelist = state.pop("nodelist", None)
        if nodelist:
            if isinstance(nodelist, str):
                self.selected_nodes = [
                    h.strip() for h in nodelist.replace(",", " ").split() if h.strip()
                ]
            else:
                self.selected_nodes = list(nodelist)

        for widget_id, value in state.items():
            try:
                widget = self.query_one(f"#{widget_id}", (Input, Select, Switch))
                widget.value = value
            except Exception as e:
                self.app.log(f"Could not set state for widget '{widget_id}': {e}")


    @on (Select.Changed)
    def on_select_changed(self, event: Select.Changed) -> None:
        """Gestisce i cambiamenti nelle selezioni."""
        if event.select.id == "nodes":
            node_file_input = self.query_one("#node_file", Input)
            topo_button = self.query_one("#open_topology", Button)
            data_table = self.query_one("#node_table", DataTable)
            data_table.clear()

            # Reset source-specific widgets; re-enable per branch below.
            topo_button.display = (event.value == "topology")
            # Node count is derived from the topology selection, so lock it there.
            self.query_one("#numnodes", Input).disabled = (event.value == "topology")

            if event.value == "file":
                node_file_input.visible = True
                data_table.visible = False
            elif event.value == "topology":
                # Selection happens in the modal map; keep the table for results.
                node_file_input.visible = False
                data_table.visible = True
                if self.selected_nodes:
                    for node in self.selected_nodes:
                        data_table.add_row(node)
                else:
                    data_table.add_row("Open the topology map to select nodes.")
            else:
                data_table.visible= True

                nodelist = ""
                if event.value == "auto":
                    nodelist = subprocess.check_output(["sinfo", "-h", "-o", "%N"], text=True).strip()
                elif event.value == "mixed":
                    nodelist = subprocess.check_output(["sinfo", "-h", "-t", "mix", "-o", "%N"], text=True).strip()
                elif event.value == "idle":
                    nodelist = subprocess.check_output(["sinfo", "-h", "-t", "idle", "-o", "%N"], text=True).strip()

                nodes = nodelist.split("\n")

                if nodes is None or len(nodes) == 0 or (len(nodes) == 1 and nodes[0] == ""):
                    data_table.add_row("No nodes found.")
                else:
                    for node in nodes:
                        data_table.add_row(node)



                node_file_input.visible= False
                node_file_input.value = ""

    # --- Topology-aware node selection ------------------------------------
    @on(Button.Pressed, "#open_topology")
    def _open_topology_map(self) -> None:
        """Load the preset's topology file and open the graphical selector."""
        topo_path = self._resolve_topology_path()
        if not topo_path:
            self.app.notify(
                "No topology file configured for this preset. "
                "Set a 'topology' path in presets.json.",
                severity="warning",
            )
            return
        if not os.path.exists(topo_path):
            self.app.notify(f"Topology file not found: {topo_path}", severity="error")
            return
        try:
            topology = Topology.load(topo_path)
        except Exception as e:  # noqa: BLE001
            self.app.notify(f"Failed to load topology: {e}", severity="error")
            return

        self.app.push_screen(
            TopologyMapScreen(topology, preselected=set(self.selected_nodes)),
            self._apply_topology_selection,
        )

    def _apply_topology_selection(self, selected) -> None:
        """Callback from the topology modal with the chosen hostnames."""
        if selected is None:  # cancelled
            return
        self.selected_nodes = list(selected)

        data_table = self.query_one("#node_table", DataTable)
        data_table.clear()
        if self.selected_nodes:
            for node in self.selected_nodes:
                data_table.add_row(node)
        else:
            data_table.add_row("Open the topology map to select nodes.")

        # Keep the requested node count in sync with the explicit selection.
        self.query_one("#numnodes", Input).value = str(len(self.selected_nodes))
        self.app.notify(f"Selected {len(self.selected_nodes)} node(s) from topology.")

    def _resolve_topology_path(self) -> str:
        """Topology file for the active preset (preset value overrides _common)."""
        try:
            preset_name = self.app_ref.env_container.current_preset_name
        except Exception:
            preset_name = "local"
        try:
            with open("presets.json", "r") as f:
                presets = json.load(f)
        except Exception:
            return ""
        common = presets.get("_common", {}).get("topology", "")
        preset = presets.get(preset_name, {}).get("topology", "")
        return preset or common

