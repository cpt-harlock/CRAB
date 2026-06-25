"""Neutral, serializable representation of an InfiniBand fabric topology.

This module defines a framework-agnostic data model for a network topology made
of four concepts:

* **Switch** -- an IB switch, classified as ``leaf`` (has compute NICs attached)
  or ``spine`` (connects only to other switches).
* **Nic**    -- a single Channel Adapter / HCA (one ``Ca`` entry in
  ``ibnetdiscover``). A NIC belongs to exactly one physical node and is cabled
  to one leaf switch.
* **Node**   -- a physical compute node. It owns one or more NICs and therefore
  is reachable through one or more leaf switches.
* **Cell**   -- a maximal group of leaf switches reachable through at most one
  spine hop (i.e. mutually <= 1 spine away). Two nodes in different cells are
  more than two switches apart. Cells are the coarsest locality bucket.

The representation is intentionally decoupled from how it was produced: the
``parser`` module fills it from raw ``ibnetdiscover`` output, but the JSON form
(:meth:`Topology.to_dict` / :meth:`Topology.save`) is the stable interface
consumed by the rest of CINETIC (e.g. the TUI node selector).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import IntEnum
from pathlib import Path
from typing import Dict, List, Optional, Union

# Bump when the on-disk JSON schema changes in a backward-incompatible way.
FORMAT_VERSION = 1


class Locality(IntEnum):
    """Topological proximity between two nodes (lower == closer)."""

    SAME_SWITCH = 1   # share a leaf switch          (2 switch hops)
    SAME_CELL = 2     # different leaves, same cell   (<= 4 switch hops)
    CROSS_CELL = 3    # different cells               (> 4 switch hops)


@dataclass
class Link:
    """A directed port-to-port connection discovered for a device."""

    local_port: int
    peer_name: str
    peer_port: int


@dataclass
class Switch:
    """An InfiniBand switch."""

    ib_name: str
    description: str = ""
    n_ports: int = 0
    role: str = "unknown"  # "leaf" | "spine" | "unknown"
    links: List[Link] = field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        return self.role == "leaf"

    @property
    def is_spine(self) -> bool:
        return self.role == "spine"


@dataclass
class Nic:
    """A single Channel Adapter (HCA) attached to a compute node."""

    ib_name: str          # e.g. "H-0008f10403960984"
    description: str = ""  # ibnetdiscover NodeDescription, e.g. "lrdn0001 mlx5_0"
    n_ports: int = 0
    node: str = ""         # owning physical node hostname
    switch: Optional[str] = None  # ib_name of the leaf switch this NIC cables to
    links: List[Link] = field(default_factory=list)


@dataclass
class Node:
    """A physical compute node (may own several NICs)."""

    hostname: str
    nics: List[str] = field(default_factory=list)      # NIC ib_names
    switches: List[str] = field(default_factory=list)  # leaf switch ib_names
    cell: Optional[str] = None                         # cell name, e.g. "cell01"


@dataclass
class Cell:
    """A maximal group of leaf switches within <= 1 spine hop of each other."""

    id: int
    name: str
    leaf_switches: List[str] = field(default_factory=list)   # ib_names
    spine_switches: List[str] = field(default_factory=list)  # ib_names
    nodes: List[str] = field(default_factory=list)           # hostnames


class Topology:
    """In-memory container plus (de)serialization of a fabric topology."""

    def __init__(
        self,
        switches: Optional[Dict[str, Switch]] = None,
        nics: Optional[Dict[str, Nic]] = None,
        nodes: Optional[Dict[str, Node]] = None,
        cells: Optional[List[Cell]] = None,
        source: str = "",
    ):
        self.switches: Dict[str, Switch] = switches or {}   # keyed by ib_name
        self.nics: Dict[str, Nic] = nics or {}              # keyed by ib_name
        self.nodes: Dict[str, Node] = nodes or {}           # keyed by hostname
        self.cells: List[Cell] = cells or []
        self.source = source

    # -- convenience views --------------------------------------------------
    @property
    def leaf_switches(self) -> List[Switch]:
        return [s for s in self.switches.values() if s.is_leaf]

    @property
    def spine_switches(self) -> List[Switch]:
        return [s for s in self.switches.values() if s.is_spine]

    @property
    def hostnames(self) -> List[str]:
        return sorted(self.nodes.keys())

    def cell_by_name(self, name: str) -> Optional[Cell]:
        return next((c for c in self.cells if c.name == name), None)

    def nodes_on_switch(self, ib_name: str) -> List[str]:
        """Hostnames of nodes with at least one NIC on the given leaf switch."""
        return sorted(n.hostname for n in self.nodes.values() if ib_name in n.switches)

    def nodes_in_cell(self, name: str) -> List[str]:
        cell = self.cell_by_name(name)
        return list(cell.nodes) if cell else []

    def locality(self, host_a: str, host_b: str) -> Optional[Locality]:
        """Classify the proximity of two nodes, or ``None`` if either is unknown."""
        a = self.nodes.get(host_a)
        b = self.nodes.get(host_b)
        if a is None or b is None:
            return None
        if set(a.switches) & set(b.switches):
            return Locality.SAME_SWITCH
        if a.cell is not None and a.cell == b.cell:
            return Locality.SAME_CELL
        return Locality.CROSS_CELL

    # -- serialization ------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "format_version": FORMAT_VERSION,
            "source": self.source,
            "stats": {
                "n_nodes": len(self.nodes),
                "n_nics": len(self.nics),
                "n_switches": len(self.switches),
                "n_leaf_switches": len(self.leaf_switches),
                "n_spine_switches": len(self.spine_switches),
                "n_cells": len(self.cells),
            },
            "switches": [asdict(s) for s in self.switches.values()],
            "nics": [asdict(n) for n in self.nics.values()],
            "nodes": [asdict(n) for n in self.nodes.values()],
            "cells": [asdict(c) for c in self.cells],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Topology":
        version = data.get("format_version")
        if version != FORMAT_VERSION:
            raise ValueError(
                f"Unsupported topology format_version {version!r} "
                f"(expected {FORMAT_VERSION})."
            )

        def _links(raw: List[dict]) -> List[Link]:
            return [Link(**lk) for lk in raw]

        switches = {}
        for s in data.get("switches", []):
            s = dict(s)
            s["links"] = _links(s.get("links", []))
            switches[s["ib_name"]] = Switch(**s)

        nics = {}
        for n in data.get("nics", []):
            n = dict(n)
            n["links"] = _links(n.get("links", []))
            nics[n["ib_name"]] = Nic(**n)

        nodes = {n["hostname"]: Node(**n) for n in data.get("nodes", [])}
        cells = [Cell(**c) for c in data.get("cells", [])]
        return cls(switches=switches, nics=nics, nodes=nodes, cells=cells,
                   source=data.get("source", ""))

    def save(self, path: Union[str, Path]) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: Union[str, Path]) -> "Topology":
        return cls.from_dict(json.loads(Path(path).read_text()))

    def summary(self) -> str:
        return (
            f"Topology(source={self.source!r}): "
            f"{len(self.nodes)} nodes, {len(self.nics)} NICs, "
            f"{len(self.leaf_switches)} leaf + {len(self.spine_switches)} spine "
            f"switches, {len(self.cells)} cells"
        )
