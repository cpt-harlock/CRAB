# cinetic/core/models.py — TUI-facing config dataclasses.
from dataclasses import dataclass, field
from typing import Dict

@dataclass
class AppConfig:
    """Configuration of a single application."""
    path: str = ""
    args: str = ""
    collect: bool = False
    start: str = "0"
    end: str = "f"

@dataclass
class BenchmarkState:
    """The full benchmark state, holding multiple applications."""
    apps: Dict[int, AppConfig] = field(default_factory=lambda: {0: AppConfig()})

    def get_app_config(self, app_id: int) -> AppConfig:
        """Return the config for an app, creating it if it does not exist."""
        if app_id not in self.apps:
            self.apps[app_id] = AppConfig()
        return self.apps[app_id]

    def add_new_app(self) -> int:
        """Add a new app configuration and return its ID."""
        new_id = max(self.apps.keys()) + 1 if self.apps else 0
        self.apps[new_id] = AppConfig()
        return new_id

    def to_dict(self) -> dict:
        """Serialize the state into a JSON-serializable dictionary."""
        return {str(k): v.__dict__ for k, v in self.apps.items()}

    @classmethod
    def from_dict(cls, data: dict) -> 'BenchmarkState':
        """Build a BenchmarkState instance from a dictionary."""
        state = cls()
        state.apps = {int(k): AppConfig(**v) for k, v in data.items()}
        return state
