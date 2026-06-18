"""Parse ``ibnetdiscover`` output into CRAB's neutral topology representation.

Usage (as a script)::

    python -m crab.topology.parser <ibnetdiscover.txt> [-o topology.json]

The raw input is the plain-text output of the InfiniBand ``ibnetdiscover``
utility. Each device is declared by a ``Switch`` or ``Ca`` (Channel Adapter)
line, followed by indented ``[port] "peer"[port]`` link lines, e.g.::

    Switch  36 "S-005442ba00003080"   # "leaf01" enhanced port 0 lid 1
    [1]     "H-0008f10403960984"[1]   # "lrdn0001 mlx5_0" lid 10 4xHDR
    ...

    Ca      1 "H-0008f10403960984"    # "lrdn0001 mlx5_0"
    [1](...) "S-005442ba00003080"[1]  # lid 1 lmc 0

The regex patterns mirror the reference implementation in
https://github.com/cpt-harlock/cinetic (topology/topology.py) so the two stay
parse-compatible.

Derivation of the four concepts:

* **Switches** are classified ``leaf`` if any of their links land on a CA,
  otherwise ``spine``.
* **NICs** are the ``Ca`` entries; each NIC's leaf switch is the switch peer of
  its links.
* **Nodes** are formed by grouping NICs that share a hostname (the first token
  of the NIC description, e.g. ``lrdn0001`` from ``"lrdn0001 mlx5_0"``).
* **Cells** are connected components of leaf switches under the "share a spine"
  relation -- i.e. maximal sets of leaves mutually reachable through <= 1 spine.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Dict, List, Tuple, Union

from crab.topology.model import Cell, Link, Nic, Node, Switch, Topology

# --- line grammar (kept compatible with cinetic/topology.py) ---------------
RE_SWITCH = re.compile(r'^Switch\s+(\d+)\s+"(S-[0-9a-fA-F]+)"\s*#\s*"([^"]*)"')
RE_CA = re.compile(r'^Ca\s+(\d+)\s+"(H-[0-9a-fA-F]+)"\s*#\s*"([^"]*)"')
RE_LINK = re.compile(r'^\[(\d+)\](?:\([0-9a-fA-F]+\))?\s+"([^"]+)"\[(\d+)\]')
RE_PROP = re.compile(r'^(vendid|devid|sysimgguid|switchguid|caguid|routerguid)=')


def hostname_of(description: str, fallback: str) -> str:
    """Physical-node hostname for a NIC: first token of its description."""
    desc = (description or "").strip()
    return desc.split()[0] if desc else fallback


def _parse_devices(path: Path) -> Tuple[Dict[str, Nic], Dict[str, Switch]]:
    """First pass: read raw Switch/Ca declarations and their link lines."""
    nics: Dict[str, Nic] = {}
    switches: Dict[str, Switch] = {}
    current = None  # Nic | Switch | None

    with open(path) as fh:
        for raw in fh:
            stripped = raw.strip()

            if not stripped:
                current = None
                continue
            if stripped.startswith("#") or RE_PROP.match(stripped):
                continue

            m = RE_SWITCH.match(stripped)
            if m:
                n_ports, ib_name, desc = int(m.group(1)), m.group(2), m.group(3)
                current = Switch(ib_name=ib_name, description=desc, n_ports=n_ports)
                switches[ib_name] = current
                continue

            m = RE_CA.match(stripped)
            if m:
                n_ports, ib_name, desc = int(m.group(1)), m.group(2), m.group(3)
                current = Nic(ib_name=ib_name, description=desc, n_ports=n_ports)
                nics[ib_name] = current
                continue

            m = RE_LINK.match(stripped)
            if m and current is not None:
                current.links.append(
                    Link(
                        local_port=int(m.group(1)),
                        peer_name=m.group(2),
                        peer_port=int(m.group(3)),
                    )
                )

    return nics, switches


def _classify_switches(nics: Dict[str, Nic], switches: Dict[str, Switch]) -> None:
    """A switch with a CA neighbour is a leaf, otherwise a spine."""
    nic_names = set(nics)
    for sw in switches.values():
        has_ca = any(lk.peer_name in nic_names for lk in sw.links)
        sw.role = "leaf" if has_ca else "spine"


def _attach_nics(nics: Dict[str, Nic], switches: Dict[str, Switch]) -> None:
    """Record, for each NIC, the leaf switch it cables to."""
    switch_names = set(switches)
    for nic in nics.values():
        for lk in nic.links:
            if lk.peer_name in switch_names:
                nic.switch = lk.peer_name
                break


def _build_nodes(nics: Dict[str, Nic]) -> Dict[str, Node]:
    """Group NICs into physical nodes by hostname."""
    nodes: Dict[str, Node] = {}
    for nic in nics.values():
        host = hostname_of(nic.description, nic.ib_name)
        nic.node = host
        node = nodes.get(host)
        if node is None:
            node = Node(hostname=host)
            nodes[host] = node
        node.nics.append(nic.ib_name)
        if nic.switch and nic.switch not in node.switches:
            node.switches.append(nic.switch)
    return nodes


def _compute_cells(switches: Dict[str, Switch]) -> List[Cell]:
    """Connected components of leaves under the 'share a spine' relation."""
    spine_names = {n for n, s in switches.items() if s.is_spine}
    leaf_names = {n for n, s in switches.items() if s.is_leaf}

    # leaf -> set of spines it connects to
    leaf_spines: Dict[str, set] = {ln: set() for ln in leaf_names}
    for sw in switches.values():
        if sw.is_leaf:
            for lk in sw.links:
                if lk.peer_name in spine_names:
                    leaf_spines[sw.ib_name].add(lk.peer_name)

    # spine -> leaves hanging off it
    spine_to_leaves: Dict[str, List[str]] = defaultdict(list)
    for leaf, spines in leaf_spines.items():
        for spine in spines:
            spine_to_leaves[spine].append(leaf)

    # leaves sharing a spine are in the same cell
    co_cell: Dict[str, set] = {ln: set() for ln in leaf_names}
    for leaves in spine_to_leaves.values():
        for i, l1 in enumerate(leaves):
            for l2 in leaves[i + 1:]:
                co_cell[l1].add(l2)
                co_cell[l2].add(l1)

    visited: set = set()
    cells: List[Cell] = []
    for start in sorted(leaf_names):
        if start in visited:
            continue
        component: List[str] = []
        q = deque([start])
        while q:
            cur = q.popleft()
            if cur in visited:
                continue
            visited.add(cur)
            component.append(cur)
            q.extend(co_cell[cur] - visited)

        cell_spines: set = set()
        for leaf in component:
            cell_spines |= leaf_spines[leaf]

        idx = len(cells) + 1
        cells.append(
            Cell(
                id=idx,
                name=f"cell{idx:02d}",
                leaf_switches=sorted(component),
                spine_switches=sorted(cell_spines),
            )
        )
    return cells


def _assign_cells(nodes: Dict[str, Node], cells: List[Cell]) -> None:
    """Tag each node with its cell and back-fill cell.nodes."""
    leaf_to_cell = {leaf: cell for cell in cells for leaf in cell.leaf_switches}
    for node in nodes.values():
        # A node's cell is that of its (first) leaf switch.
        for sw in node.switches:
            cell = leaf_to_cell.get(sw)
            if cell is not None:
                node.cell = cell.name
                cell.nodes.append(node.hostname)
                break
    for cell in cells:
        cell.nodes = sorted(set(cell.nodes))


def parse_ibnetdiscover(path: Union[str, Path]) -> Topology:
    """Parse an ``ibnetdiscover`` dump into a :class:`Topology`."""
    path = Path(path)
    nics, switches = _parse_devices(path)
    _classify_switches(nics, switches)
    _attach_nics(nics, switches)
    nodes = _build_nodes(nics)
    cells = _compute_cells(switches)
    _assign_cells(nodes, cells)
    return Topology(switches=switches, nics=nics, nodes=nodes, cells=cells,
                    source=str(path))


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Parse ibnetdiscover output into CRAB's neutral topology JSON."
    )
    parser.add_argument("input", help="Path to ibnetdiscover output file.")
    parser.add_argument(
        "-o", "--output",
        help="Where to write the topology JSON (default: stdout).",
    )
    args = parser.parse_args(argv)

    topo = parse_ibnetdiscover(args.input)
    print(topo.summary(), file=sys.stderr)

    if args.output:
        topo.save(args.output)
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        import json
        print(json.dumps(topo.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
