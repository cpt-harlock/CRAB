from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Button
from textual import on

from ..messages import SaveConfiguration, LoadConfiguration, RunBenchmark
from ..constants import SECTIONS

class TabSelector(Horizontal):
    def __init__(self, id, app_ref):
        super().__init__(id=id)
        self.app_ref = app_ref

    def compose(self) -> ComposeResult:
        for index, section in enumerate(SECTIONS):
            yield Button(section, id=f"tab-{index}", classes="tab")

        with Horizontal(classes="action-buttons"):
            yield Button("Save", id="save-form", variant="primary", classes="save-btn")
            yield Button("Load", id="load-form", variant="primary", classes="load-btn")
            yield Button("Run Benchmark", id="run-benchmark", variant="success", classes="run-btn")


    def on_button_pressed(self, event: Button.Pressed) -> None:
        """
        Invia messaggi specifici quando i pulsanti di azione vengono premuti.
        """
        if event.button.id == "save-form":
            self.post_message(SaveConfiguration())
            event.stop()  # Impedisce all'evento di "risalire" ulteriormente
        elif event.button.id == "load-form":
            self.post_message(LoadConfiguration())
            event.stop()
        elif event.button.id == "run-benchmark":
            self.post_message(RunBenchmark())
            event.stop()
