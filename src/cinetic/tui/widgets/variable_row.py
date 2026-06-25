from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Input, Button
from textual.message import Message

class VariableRow(Horizontal):
    """A widget for a single environment variable row."""

    class Deleted(Message):
        """Sent when the delete button is pressed."""
        def __init__(self, row_widget: "VariableRow"):
            self.row_widget = row_widget
            super().__init__()

    class Changed(Message):
        """Sent when an input value changes."""
        def __init__(self, key: str, value: str):
            self.key = key
            self.value = value
            super().__init__()

    def __init__(self, key: str = "", value: str = "", **kwargs):
        super().__init__(**kwargs)
        self._key = key
        self._value = value
        self.key_input: Input | None = None
        self.value_input: Input | None = None

    def compose(self) -> ComposeResult:
        self.key_input = Input(value=self._key, placeholder="Variable Name", classes="variable_key")
        self.value_input = Input(value=self._value, placeholder="Variable Value", classes="variable_value")
        
        yield self.key_input
        yield self.value_input
        yield Button("X", variant="error", classes="delete_variable_btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.post_message(self.Deleted(self))

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        if self.key_input and self.value_input:
            self.post_message(self.Changed(self.key_input.value, self.value_input.value))
    
    @property
    def key(self) -> str:
        return self.key_input.value if self.key_input else ""
    
    @property
    def value(self) -> str:
        return self.value_input.value if self.value_input else ""
