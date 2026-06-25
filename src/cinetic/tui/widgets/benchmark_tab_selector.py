from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button
import asyncio

class BenchmarkTabSelector(Horizontal):
    def __init__(self, benchmark_count: int = 1):
        super().__init__()
        self.benchmark_count = benchmark_count
        self.current_benchmark = 0

    def compose(self) -> ComposeResult:
        for i in range(self.benchmark_count):
            yield Button(f"Application {i + 1}", id=f"benchmark-{i}", classes="benchmark-tab")
        yield Button("+", id="add-benchmark", classes="add-benchmark-btn")

    def add_benchmark(self):
        self.benchmark_count += 1
        new_button = Button(f"Application {self.benchmark_count}",
                          id=f"benchmark-{self.benchmark_count - 1}",
                          classes="benchmark-tab")
        self.mount(new_button, before="#add-benchmark")

    def update_benchmark_tabs(self, current: int):
        self.current_benchmark = current
        for i, tab_button in enumerate(self.query(".benchmark-tab")):
            tab_button.variant = "primary" if i == current else "default"

    async def clear_benchmark_forms(self):
        for child in list(self.children):
            if child.id and child.id.startswith("add"):
                continue
            child.remove()
        self.benchmark_count = 0
        self.current_benchmark = 0
        self.update_benchmark_tabs(0)
        await asyncio.sleep(0)
