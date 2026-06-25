"""Typed runtime context for the CINETIC framework core.

Historically the engine and workload-manager backends read their configuration
directly from ``os.environ`` (the ``CINETIC_*`` variables a preset exports).
That works, but it is untyped, implicit, and impossible to unit-test without
mutating global process state.

:class:`RuntimeContext` is the typed front door to that configuration. It is
built once from the resolved environment via :meth:`RuntimeContext.from_env`
and handed to the core components, which read their static settings from it.

``os.environ`` is still used deliberately as the *live transport* across the
two real process boundaries CINETIC has — the in-process, ``exec``-loaded
benchmark wrappers (which read ``CINETIC_ROOT`` at import time) and the spawned
MPI/Slurm subprocesses (which inherit the environment) — and for dynamic,
per-experiment values such as the node-results directory. Those are genuine
transport, not configuration, and stay in the environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import ClassVar, Dict, Mapping, Optional

from cinetic.compat import apply_legacy_env


@dataclass(frozen=True)
class RuntimeContext:
    """Immutable snapshot of the resolved framework settings.

    Fields mirror the preset-exported ``CINETIC_*`` variables. The full source
    mapping is retained in :attr:`raw` so benchmark-specific keys (e.g.
    ``CINETIC_MINIFE_PATH``) and pass-through variables remain reachable via
    :meth:`get` without bloating the typed surface.
    """

    root: str = ""
    system: str = "unknown"
    wl_manager: str = "slurm"
    wrappers_path: str = ""
    mpirun: str = ""
    mpirun_map_by_node_flag: str = ""
    mpirun_additional_flags: str = ""
    mpirun_hostnames_flag: str = ""
    pinning_flags: str = ""
    raw: Mapping[str, str] = field(default_factory=dict, repr=False)

    # typed field name -> environment variable name
    ENV_KEYS: ClassVar[Dict[str, str]] = {
        "root": "CINETIC_ROOT",
        "system": "CINETIC_SYSTEM",
        "wl_manager": "CINETIC_WL_MANAGER",
        "wrappers_path": "CINETIC_WRAPPERS_PATH",
        "mpirun": "CINETIC_MPIRUN",
        "mpirun_map_by_node_flag": "CINETIC_MPIRUN_MAP_BY_NODE_FLAG",
        "mpirun_additional_flags": "CINETIC_MPIRUN_ADDITIONAL_FLAGS",
        "mpirun_hostnames_flag": "CINETIC_MPIRUN_HOSTNAMES_FLAG",
        "pinning_flags": "CINETIC_PINNING_FLAGS",
    }

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None) -> "RuntimeContext":
        """Build a context from ``os.environ`` (default) or any given mapping.

        Legacy ``CRAB_*`` keys are mirrored onto ``CINETIC_*`` first, so old run
        snapshots and shells resolve transparently.
        """
        src: Dict[str, str] = dict(os.environ if environ is None else environ)
        apply_legacy_env(src)
        values = {fld: src[key] for fld, key in cls.ENV_KEYS.items() if key in src}
        return cls(raw=src, **values)

    def get(self, name: str, default: str = "") -> str:
        """Read an arbitrary variable from the underlying snapshot."""
        return self.raw.get(name, default)

    def to_env(self) -> Dict[str, str]:
        """Serialize the typed fields back to their ``CINETIC_*`` names."""
        return {
            key: getattr(self, fld)
            for fld, key in self.ENV_KEYS.items()
            if getattr(self, fld) not in ("", None)
        }
