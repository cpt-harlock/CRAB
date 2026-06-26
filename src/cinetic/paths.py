"""Filesystem anchors for the CINETIC repo.

Repo resources — ``presets.json``, ``wrappers/``, ``benchmarks/``, ``topologies/``
— live at the repo root. Resolving them relative to this package (instead of
``os.getcwd()``) lets ``cinetic`` run from any working directory, e.g. a
subfolder. Outputs (``./data``) stay cwd-relative on purpose.
"""

import os


def repo_root() -> str:
    """Absolute path to the repo root (the parent of ``src/``)."""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def presets_path() -> str:
    """Absolute path to ``presets.json`` at the repo root."""
    return os.path.join(repo_root(), "presets.json")


def env_path() -> str:
    """Absolute path to the ``.env`` preset selector at the repo root."""
    return os.path.join(repo_root(), ".env")
