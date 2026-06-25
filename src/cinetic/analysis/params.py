"""Resolve the tournament benchmark parameters needed for bandwidth/latency.

``duration_s`` in the node CSVs is the wall-time of one sample = ``granularity``
windowed exchanges. We need ``msg_size``, ``window`` and ``granularity`` to turn
it into bytes. They are not in the node CSVs, so resolve them in priority order:

1. explicit CLI overrides;
2. ``stdout_app_<id>.log`` header (present when ``collect=true``) — prints
   ``msg-size``, ``window`` and ``bytes/exchange`` directly;
3. the tournament app's ``args`` in ``config.json`` (``-msgsize/-window/-grty``);
4. the compiled defaults of ``benchmarks/blink/tournament_nb.c``.

The source is recorded so the report can flag a possible mismatch.
"""

from __future__ import annotations

import glob
import json
import os
import re
from dataclasses import dataclass
from typing import Optional

# Compiled defaults — keep in sync with benchmarks/blink/tournament_nb.c.
DEFAULT_MSG_SIZE = 4194304
DEFAULT_WINDOW = 64
DEFAULT_GRANULARITY = 1


@dataclass
class Params:
    msg_size: int
    window: int
    granularity: int
    source: str

    @property
    def bytes_per_exchange(self) -> int:
        """Full-duplex aggregate bytes moved per windowed exchange (both dirs)."""
        return 2 * self.window * self.msg_size

    @property
    def bytes_per_sample(self) -> int:
        return self.bytes_per_exchange * self.granularity


def _find_stdout_log(exp_dir: str) -> Optional[str]:
    logs = sorted(glob.glob(os.path.join(exp_dir, "stdout_app_*.log")))
    return logs[0] if logs else None


def _parse_stdout_header(path: str) -> dict:
    """Pull msg-size/window from the first 'Tournament with ...' header line."""
    out: dict = {}
    try:
        with open(path) as fh:
            for line in fh:
                if "Tournament with" not in line:
                    continue
                m = re.search(r"msg-size:\s*(\d+)", line)
                w = re.search(r"window:\s*(\d+)", line)
                if m:
                    out["msg_size"] = int(m.group(1))
                if w:
                    out["window"] = int(w.group(1))
                break
    except OSError:
        pass
    return out


def _parse_config_args(exp_dir: str) -> dict:
    """Read the tournament app's CLI args from the run's config.json."""
    # config.json sits in the run dir, one level above the exp dir.
    candidates = [
        os.path.join(exp_dir, "config.json"),
        os.path.join(os.path.dirname(exp_dir.rstrip(os.sep)), "config.json"),
    ]
    args = ""
    for cfg in candidates:
        if not os.path.isfile(cfg):
            continue
        try:
            data = json.load(open(cfg))
        except (OSError, json.JSONDecodeError):
            continue
        for exp in data.get("experiments", {}).values():
            for app in exp.get("apps", {}).values():
                if "tournament" in str(app.get("path", "")):
                    args = str(app.get("args", ""))
                    break
        break

    out: dict = {}
    for flag, key in (("-msgsize", "msg_size"), ("-window", "window"),
                      ("-grty", "granularity")):
        m = re.search(rf"{re.escape(flag)}\s+(\d+)", args)
        if m:
            out[key] = int(m.group(1))
    return out


def resolve_params(exp_dir: str,
                   msg_size: Optional[int] = None,
                   window: Optional[int] = None,
                   granularity: Optional[int] = None) -> Params:
    """Resolve params from CLI > stdout header > config args > defaults."""
    sources = []
    msg = win = gran = None

    if msg_size is not None or window is not None or granularity is not None:
        msg, win, gran = msg_size, window, granularity
        sources.append("CLI")

    if msg is None or win is None:
        log = _find_stdout_log(exp_dir)
        if log:
            hdr = _parse_stdout_header(log)
            if hdr:
                msg = msg if msg is not None else hdr.get("msg_size")
                win = win if win is not None else hdr.get("window")
                sources.append(f"stdout header ({os.path.basename(log)})")

    if msg is None or win is None or gran is None:
        cfg = _parse_config_args(exp_dir)
        if cfg:
            msg = msg if msg is not None else cfg.get("msg_size")
            win = win if win is not None else cfg.get("window")
            gran = gran if gran is not None else cfg.get("granularity")
            if cfg:
                sources.append("config.json args")

    if msg is None:
        msg = DEFAULT_MSG_SIZE
        sources.append("default msg_size")
    if win is None:
        win = DEFAULT_WINDOW
        sources.append("default window")
    if gran is None:
        gran = DEFAULT_GRANULARITY
        # only label as a default fallback, not when it came from a real source
        if "config.json args" not in sources and "CLI" not in sources:
            sources.append("default granularity")

    return Params(msg_size=msg, window=win, granularity=gran,
                  source=" + ".join(sources) if sources else "defaults")
