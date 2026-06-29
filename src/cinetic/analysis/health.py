"""Benchmark-level health signals scraped from the run's log files.

Some signals are emitted by the benchmark itself (not in the per-node CSVs) and
would otherwise be invisible in the report. The tournament benchmark, for
example, prints ``Total window timeouts: N`` to stderr when a windowed exchange
stalls past its per-window timeout — a *hard* stall, the strongest "this node /
link is sick" signal there is, and far more serious than merely-slow bandwidth.

On a zero-exit run that count lives in ``stderr_app_<id>.log`` (the engine now
persists stderr on success); on a failed run it is in ``error_app_<id>.log`` /
``slurm_error.log``. This module greps those, newest format first, and returns
the total (``None`` when no log carrying the line is found — *unknown*, distinct
from a known zero).
"""

from __future__ import annotations

import glob
import os
import re
from typing import List, Optional

_TIMEOUT_RE = re.compile(r"Total window timeouts:\s*(\d+)")


def _candidate_logs(exp_dir: str, app_id) -> List[str]:
    """Logs that may carry the timeout line, most-specific first."""
    run_dir = os.path.dirname(exp_dir.rstrip(os.sep))
    out: List[str] = []
    if app_id is not None:
        out += [os.path.join(exp_dir, f"stderr_app_{app_id}.log"),
                os.path.join(exp_dir, f"error_app_{app_id}.log")]
    # un-prefixed / wildcard fallbacks for legacy or single-app runs
    out += sorted(glob.glob(os.path.join(exp_dir, "stderr_app_*.log")))
    out += sorted(glob.glob(os.path.join(exp_dir, "error_app_*.log")))
    out += [os.path.join(run_dir, "slurm_error.log")]
    # de-dup, preserve order
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def window_timeouts(exp_dir: str, app_id=None) -> Optional[int]:
    """Total window timeouts for an app, or ``None`` if no log reports it."""
    for path in _candidate_logs(exp_dir, app_id):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        matches = _TIMEOUT_RE.findall(text)
        if matches:
            # last occurrence wins (logs are appended across re-runs)
            return int(matches[-1])
    return None
