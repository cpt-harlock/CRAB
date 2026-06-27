"""ExperimentContext — the semantic layer over a run's config/environment.

The analyzer already groups output files by **app id** (``node_app<id>_*.csv`` ->
``analysis/app_<id>/``), but a bare :class:`~cinetic.analysis.metrics.Analysis`
is *role-blind*: it knows the app id and benchmark kind, not whether the app was
a victim or an aggressor, nor what else ran alongside it. This module reads the
run's ``config.json`` + ``environment.json`` and maps each app id to its **role**
(victim / aggressor / timed), partition, schedule, and the run's system, so the
congestion/comparison layers can read a victim's results *in the context of* the
aggressor co-running in the same experiment.

It degrades gracefully: a bare exp dir with no config.json yields an empty
context (roles unknown), so ``cinetic analyze`` keeps working on anonymous dumps.

See PLAN_ANALYSIS_REWORK.md §3.1.
"""

from __future__ import annotations

import glob
import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

# matches the app-namespaced per-node files (node_app<id>_<host>_rank<r>.csv)
_APP_NODE_RE = re.compile(r"^node_app(\d+)_")


class Role(str, Enum):
    """Derived from an app's ``end`` field (CLAUDE.md config semantics)."""
    VICTIM = "victim"          # end == ""   (waits to finish; the measured one)
    AGGRESSOR = "aggressor"    # end == "f"  (killed when victims finish)
    TIMED = "timed"            # end == "<N>" (killed after N seconds)
    UNKNOWN = "unknown"        # no config / unrecognized


def role_from_end(end: Optional[str]) -> Role:
    """Map an app's ``end`` to a :class:`Role`. ``""`` -> VICTIM, ``"f"`` ->
    AGGRESSOR, a numeric string -> TIMED, anything else / None -> UNKNOWN."""
    if end is None:
        return Role.UNKNOWN
    s = str(end).strip()
    if s == "":
        return Role.VICTIM
    if s.lower() == "f":
        return Role.AGGRESSOR
    try:
        float(s)
        return Role.TIMED
    except ValueError:
        return Role.UNKNOWN


@dataclass
class AppInfo:
    """One app's config entry, joined to the output it produced."""
    app_id: str
    path: str = ""
    args: str = ""
    role: Role = Role.UNKNOWN
    partition: Optional[int] = None
    start: str = "0"
    end: str = ""
    collect: bool = True
    # which output this app produced, detected from files on disk:
    #   "standardized" node_app<id>_*.csv | "generic" data_app_<id>.csv | "none"
    output_kind: str = "none"

    @property
    def wrapper_name(self) -> str:
        """Wrapper basename, e.g. ``tournament_nb.py`` (the benchmark identity)."""
        return os.path.basename(self.path) if self.path else ""

    @property
    def is_victim(self) -> bool:
        return self.role == Role.VICTIM

    @property
    def is_aggressor(self) -> bool:
        """Aggressor-like for impact purposes: explicit aggressors and timed."""
        return self.role in (Role.AGGRESSOR, Role.TIMED)


@dataclass
class ExperimentContext:
    """Roles + metadata for one experiment (one ``<exp_id>/`` dir)."""
    exp_id: str
    exp_dir: str
    system: str = ""
    apps: Dict[str, AppInfo] = field(default_factory=dict)
    global_options: dict = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    @property
    def victims(self) -> List[AppInfo]:
        return [a for a in self.apps.values() if a.role == Role.VICTIM]

    @property
    def aggressors(self) -> List[AppInfo]:
        return [a for a in self.apps.values() if a.is_aggressor]

    @property
    def is_loaded(self) -> bool:
        """An experiment with aggressors is a *loaded* (under-congestion) run."""
        return bool(self.aggressors)

    @property
    def is_baseline(self) -> bool:
        """Victims and no aggressors -> a baseline candidate for §4 comparison."""
        return bool(self.victims) and not self.aggressors

    @property
    def has_roles(self) -> bool:
        return bool(self.apps)

    def app(self, app_id) -> Optional[AppInfo]:
        if app_id is None:
            # Legacy un-prefixed dump: if there's exactly one app, it's that one.
            return next(iter(self.apps.values())) if len(self.apps) == 1 else None
        return self.apps.get(str(app_id))


def _load_json(path: str) -> Optional[dict]:
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as fh:
            return json.load(fh)
    except (ValueError, OSError):
        return None


def _to_int_or_none(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _dir_has_legacy_nodes(exp_dir: str) -> bool:
    """Any un-prefixed ``node_<host>_rank<r>.csv`` (the pre-namespacing format)."""
    return any(not _APP_NODE_RE.match(os.path.basename(p))
               for p in glob.glob(os.path.join(exp_dir, "node_*.csv")))


def _detect_output_kind(exp_dir: str, app_id, single_app: bool) -> str:
    if app_id is not None and glob.glob(
            os.path.join(exp_dir, f"node_app{app_id}_*.csv")):
        return "standardized"
    # A legacy un-prefixed dump predates app-id namespacing; it only occurs for a
    # single app, so attribute it to that app as standardized output.
    if single_app and _dir_has_legacy_nodes(exp_dir):
        return "standardized"
    if app_id is not None and os.path.isfile(
            os.path.join(exp_dir, f"data_app_{app_id}.csv")):
        return "generic"
    return "none"


def load_context(exp_dir: str) -> ExperimentContext:
    """Build the :class:`ExperimentContext` for an experiment dir.

    Reads ``<run_dir>/config.json`` and ``<run_dir>/environment.json`` (the run
    dir is the parent of *exp_dir*). Missing files degrade to an empty/partial
    context rather than raising, so anonymous exp dirs still analyze."""
    exp_dir = os.path.abspath(exp_dir)
    exp_id = os.path.basename(exp_dir.rstrip("/"))
    run_dir = os.path.dirname(exp_dir)
    ctx = ExperimentContext(exp_id=exp_id, exp_dir=exp_dir)

    env = _load_json(os.path.join(run_dir, "environment.json")) or {}
    ctx.system = (env.get("CINETIC_SYSTEM") or env.get("CRAB_SYSTEM")
                  or env.get("HPC_SYSTEM") or "")

    cfg = _load_json(os.path.join(run_dir, "config.json"))
    if not cfg:
        ctx.warnings.append(
            "no config.json next to exp dir; roles unknown (anonymous analysis)")
        return ctx
    ctx.global_options = cfg.get("global_options", {}) or {}

    exps = cfg.get("experiments", {}) or {}
    apps = (exps.get(exp_id) or {}).get("apps")
    if apps is None and len(exps) == 1:
        # The dir was renamed away from its config exp_id; with a single
        # experiment the mapping is unambiguous, so fall back to it.
        apps = next(iter(exps.values())).get("apps", {})
    apps = apps or {}

    single_app = len(apps) == 1
    for aid, spec in apps.items():
        spec = spec or {}
        ctx.apps[str(aid)] = AppInfo(
            app_id=str(aid),
            path=spec.get("path", ""),
            args=spec.get("args", ""),
            role=role_from_end(spec.get("end", "")),
            partition=_to_int_or_none(spec.get("partition")),
            start=str(spec.get("start", "0")),
            end=str(spec.get("end", "")),
            collect=bool(spec.get("collect", True)),
            output_kind=_detect_output_kind(exp_dir, aid, single_app),
        )
    return ctx
