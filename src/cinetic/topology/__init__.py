"""Topology-aware node selection support for CRAB.

Parses ``ibnetdiscover`` output into a neutral, serializable representation
(see :mod:`cinetic.topology.model`) that downstream tooling -- such as the TUI
node selector -- can consume without depending on the parser internals.
"""

from cinetic.topology.model import (
    FORMAT_VERSION,
    Cell,
    Link,
    Locality,
    Nic,
    Node,
    Switch,
    Topology,
)
from cinetic.topology.parser import parse_ibnetdiscover

__all__ = [
    "FORMAT_VERSION",
    "Cell",
    "Link",
    "Locality",
    "Nic",
    "Node",
    "Switch",
    "Topology",
    "parse_ibnetdiscover",
]
