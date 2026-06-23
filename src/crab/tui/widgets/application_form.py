from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import (
    Button, Input, Label, Checkbox, RichLog
)

from textual import on, work
from textual.message import Message

from textual_fspicker import FileOpen

from .environment_settings import EnvironmentSettings

import os
import json
import threading
import subprocess


class ApplicationForm(Vertical):
    def __init__(self, app_ref, benchmark_id: int = 0):
        super().__init__()
        self.app_ref = app_ref
        self.benchmark_id = benchmark_id
        self.form_data = {
            "path": "",
            "args": "",
            "collect": False,
            "start": "",
            "end": ""
        }

    def compose(self) -> ComposeResult:
        yield Label("Application Path:")
        yield Label("Select a file", id="path")
        yield Button("Browse", id="browse-path", variant="primary", classes="browse-btn")

        yield Label("Arguments:")
        yield Input(placeholder="-msgsize 1048576", id="args", value=self.form_data["args"])

        yield Label("Collect Timings:")
        yield Checkbox("Yes", id="collect", value=self.form_data["collect"])

        yield Label("Start Time (s):")
        yield Input(placeholder="0", id="start", value=self.form_data["start"])

        yield Label("End Time (s), 'f' or empty:")
        yield Input(placeholder="f", id="end", value=self.form_data["end"])

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id in self.form_data:
            self.form_data[event.input.id] = event.input.value

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "collect":
            self.form_data["collect"] = event.checkbox.value

    def get_form_data(self):
        path = self.query_one("#path", Label).content
        self.form_data["path"] = path if path != "Select a file" else ""
        return self.form_data.copy()

    def set_form_data(self, data):
        self.form_data.update(data)
        if self.is_mounted:
            for field_id, value in data.items():
                try:
                    if field_id == "path":
                        widget = self.query_one("#path", Label)
                        widget.update(value) if value else widget.update("Select a file")
                        continue

                    widget = self.query_one(f"#{field_id}", (Input, Checkbox))
                    widget.value = value
                except Exception:
                    pass

    def _wrappers_dir(self) -> str:
        """Default browse location: the CRAB wrappers directory, if it exists."""
        raw = os.environ.get("CRAB_WRAPPERS_PATH", "")
        if raw:
            raw = raw.replace("__CWD__", os.getcwd())
            candidate = os.path.expandvars(os.path.expanduser(raw))
        else:
            candidate = os.path.join(os.getcwd(), "wrappers")
        return candidate if os.path.isdir(candidate) else os.getcwd()

    @on(Button.Pressed, "#browse-path")
    @work
    async def browse_path(self):
        file_path = await self.app_ref.push_screen_wait(FileOpen(location=self._wrappers_dir()))
        if not file_path:
            self.notify("File selection cancelled")
            return

        self.query_one("#path", Label).update(str(file_path))

