"""Topology distance for node pairs.

Wraps the existing ``cinetic.topology.model.Topology`` and handles the hostname
mismatch: tournament CSVs carry FQDNs (``lrdn0271.leonardo.local``) while the
topology keys are short names (``lrdn0271``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from cinetic.topology.model import Locality, Topology


def normalize_host(host: str) -> str:
    """Strip the domain suffix: ``lrdn0271.leonardo.local`` -> ``lrdn0271``."""
    return host.split(".")[0]


@dataclass
class TopoResolver:
    topology: Optional[Topology]
    resolved: Dict[str, bool] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def _known(self, host: str) -> bool:
        if self.topology is None:
            return False
        short = normalize_host(host)
        ok = short in self.topology.nodes
        self.resolved[host] = ok
        return ok

    def locality(self, host_a: str, host_b: str) -> Optional[Locality]:
        """Classify the pair, or ``None`` if topology/host is unknown."""
        if self.topology is None:
            return None
        a, b = normalize_host(host_a), normalize_host(host_b)
        self.resolved.setdefault(host_a, a in self.topology.nodes)
        self.resolved.setdefault(host_b, b in self.topology.nodes)
        return self.topology.locality(a, b)

    def check_coverage(self, hosts: List[str], min_frac: float = 0.8) -> None:
        """Warn loudly if too few hosts resolve (likely the wrong topology file)."""
        if self.topology is None:
            return
        known = [h for h in hosts if self._known(h)]
        if not hosts:
            return
        frac = len(known) / len(hosts)
        if frac < min_frac:
            unresolved = [h for h in hosts if not self.resolved.get(h)]
            self.warnings.append(
                f"only {len(known)}/{len(hosts)} hosts ({frac:.0%}) resolve in the "
                f"topology — it likely does not match this run's system. "
                f"Unresolved e.g.: {unresolved[:3]}")


def load_topology(path: Optional[str]) -> Optional[Topology]:
    if not path:
        return None
    return Topology.load(path)


# Human-readable labels + a coarse hop estimate for reporting.
LOCALITY_LABEL = {
    Locality.SAME_SWITCH: "same_switch",
    Locality.SAME_CELL: "same_cell",
    Locality.CROSS_CELL: "cross_cell",
}


def locality_label(loc: Optional[Locality]) -> str:
    return LOCALITY_LABEL.get(loc, "unknown")
