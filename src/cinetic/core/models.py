# cinetic/core/models.py
from dataclasses import dataclass, field
from typing import Dict

@dataclass
class AppConfig:
    """Rappresenta la configurazione di una singola applicazione."""
    path: str = ""
    args: str = ""
    collect: bool = False
    start: str = "0"
    end: str = "f"

@dataclass
class BenchmarkState:
    """Rappresenta l'intero stato del benchmark, con più applicazioni."""
    apps: Dict[int, AppConfig] = field(default_factory=lambda: {0: AppConfig()})

    def get_app_config(self, app_id: int) -> AppConfig:
        """Restituisce la config per un'app, creandola se non esiste."""
        if app_id not in self.apps:
            self.apps[app_id] = AppConfig()
        return self.apps[app_id]

    def add_new_app(self) -> int:
        """Aggiunge una nuova configurazione di app e restituisce il suo ID."""
        new_id = max(self.apps.keys()) + 1 if self.apps else 0
        self.apps[new_id] = AppConfig()
        return new_id

    def to_dict(self) -> dict:
        """Converte lo stato in un dizionario serializzabile in JSON."""
        return {str(k): v.__dict__ for k, v in self.apps.items()}

    @classmethod
    def from_dict(cls, data: dict) -> 'BenchmarkState':
        """Crea un'istanza di BenchmarkState da un dizionario."""
        state = cls()
        state.apps = {int(k): AppConfig(**v) for k, v in data.items()}
        return state
