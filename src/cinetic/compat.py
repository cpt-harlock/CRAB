"""Backward-compatibility shim for the CRAB -> CINETIC rename.

CINETIC was previously named CRAB. Older run snapshots
(``data/**/environment.json``), example configs, and user shells may still set
``CRAB_*`` environment variables. This module mirrors any legacy ``CRAB_<X>``
onto ``CINETIC_<X>`` when the new key is absent, so existing runs and shells keep
working unchanged. A single deprecation note is emitted per process.

This shim is intentionally small and self-contained; it is the only place that
knows about the legacy prefix and is slated for removal in a future release.
"""

from __future__ import annotations

import os
import sys
from typing import List, MutableMapping, Optional

LEGACY_PREFIX = "CRAB_"
NEW_PREFIX = "CINETIC_"

_warned = False


def apply_legacy_env(mapping: Optional[MutableMapping[str, str]] = None) -> List[str]:
    """Mirror legacy ``CRAB_*`` keys onto ``CINETIC_*`` in-place.

    Operates on ``os.environ`` by default, or on any given mutable mapping (e.g.
    an ``environment.json`` dict loaded in worker mode). Existing ``CINETIC_*``
    keys are never overwritten. Returns the list of legacy keys that were
    migrated and warns once per process if any were found.
    """
    global _warned
    target = os.environ if mapping is None else mapping

    migrated: List[str] = []
    for key in list(target.keys()):
        if key.startswith(LEGACY_PREFIX):
            new_key = NEW_PREFIX + key[len(LEGACY_PREFIX):]
            if new_key not in target:
                target[new_key] = target[key]
                migrated.append(key)

    if migrated and not _warned:
        _warned = True
        print(
            f"[cinetic] note: legacy {LEGACY_PREFIX}* variable(s) detected "
            f"({', '.join(sorted(migrated))}); mapped to {NEW_PREFIX}*. "
            "Please migrate your presets/shell; this shim will be removed "
            "in a future release.",
            file=sys.stderr,
            flush=True,
        )
    return migrated
