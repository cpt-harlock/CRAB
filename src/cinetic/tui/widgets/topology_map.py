"""Graphical, topology-aware node selector for the CRAB TUI.

Renders a parsed topology (see :mod:`cinetic.topology`) as a 2D map:

    [ cell01 ]            [ cell02 ]
     L1     L2             L3     L4
    ███    ░░░            ░░░    ░░░
    ███    ░░░

Each leaf switch is a column of node blocks grouped under its cell. Clicking a
node block toggles its selection (filled = selected); clicking a switch or cell
header toggles every node beneath it. The screen returns the sorted list of
selected hostnames via :meth:`dismiss`, or ``None`` if cancelled.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, HorizontalScroll, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from cinetic.topology import Topology


class NodeToggled(Message):
    """Posted by a NodeBlock when its selection changes."""

    def __init__(self, hostname: str, selected: bool) -> None:
        self.hostname = hostname
        self.selected = selected
        super().__init__()


class GroupToggle(Message):
    """Posted by a cell/switch header to bulk-toggle its nodes."""

    def __init__(self, hostnames: List[str]) -> None:
        self.hostnames = hostnames
        super().__init__()


class NodeBlock(Static):
    """A single clickable, selectable compute node."""

    selected: reactive[bool] = reactive(False)

    def __init__(self, hostname: str) -> None:
        super().__init__(hostname, classes="node-block")
        self.hostname = hostname

    def watch_selected(self, value: bool) -> None:
        self.set_class(value, "-selected")

    def on_click(self) -> None:
        self.selected = not self.selected
        self.post_message(NodeToggled(self.hostname, self.selected))


class GroupHeader(Static):
    """A clickable header (cell or switch) that bulk-toggles its nodes."""

    def __init__(self, label: str, hostnames: List[str], classes: str) -> None:
        super().__init__(label, classes=classes)
        self.hostnames = hostnames

    def on_click(self) -> None:
        self.post_message(GroupToggle(self.hostnames))


class TopologyMapScreen(ModalScreen[Optional[List[str]]]):
    """Modal screen presenting the graphical topology node selector."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "confirm", "Confirm"),
        ("a", "select_all", "All"),
        ("c", "clear", "Clear"),
        ("i", "invert", "Invert"),
    ]

    def __init__(
        self,
        topology: Topology,
        preselected: Optional[Set[str]] = None,
    ) -> None:
        super().__init__()
        self.topology = topology
        self.preselected = set(preselected or set())
        self.blocks: Dict[str, NodeBlock] = {}

    # -- layout -------------------------------------------------------------
    def _grouped(self):
        """Return {cell_name: {switch_ib: [hostname, ...]}} for display.

        Each node is shown once, under its first leaf switch.
        """
        leaf_to_cell = {
            leaf: cell.name
            for cell in self.topology.cells
            for leaf in cell.leaf_switches
        }
        groups: Dict[str, Dict[str, List[str]]] = {}
        unplaced: Dict[str, List[str]] = {}
        for host in sorted(self.topology.nodes):
            node = self.topology.nodes[host]
            switch = node.switches[0] if node.switches else None
            cell = leaf_to_cell.get(switch) if switch else None
            if cell is None or switch is None:
                unplaced.setdefault(switch or "unknown", []).append(host)
                continue
            groups.setdefault(cell, {}).setdefault(switch, []).append(host)
        if unplaced:
            groups["(unassigned)"] = unplaced
        return groups

    def compose(self) -> ComposeResult:
        with Vertical(id="topo-dialog"):
            yield Static(
                f"Topology map — {self.topology.summary()}",
                id="topo-title",
            )

            groups = self._grouped()
            if not groups:
                yield Static(
                    "No nodes found in this topology file.",
                    id="topo-empty",
                )
            else:
                with HorizontalScroll(id="topo-cells"):
                    for cell_name, switches in groups.items():
                        cell_hosts = [h for hs in switches.values() for h in hs]
                        with Vertical(classes="cell-box"):
                            yield GroupHeader(
                                f"▾ {cell_name} ({len(cell_hosts)})",
                                cell_hosts,
                                classes="cell-header",
                            )
                            with Horizontal(classes="switch-row"):
                                for switch_ib, hosts in switches.items():
                                    with Vertical(classes="switch-col"):
                                        yield GroupHeader(
                                            self._switch_label(switch_ib, len(hosts)),
                                            list(hosts),
                                            classes="switch-header",
                                        )
                                        for host in hosts:
                                            block = NodeBlock(host)
                                            block.selected = host in self.preselected
                                            self.blocks[host] = block
                                            yield block

            with Horizontal(id="topo-footer"):
                yield Static(self._count_text(), id="topo-count")
                yield Button("Select All", id="topo-all")
                yield Button("Clear", id="topo-clear")
                yield Button("Invert", id="topo-invert")
                yield Button("Confirm", id="topo-confirm", variant="success")
                yield Button("Cancel", id="topo-cancel", variant="error")

    def _switch_label(self, switch_ib: str, n: int) -> str:
        sw = self.topology.switches.get(switch_ib)
        # Prefer a short human label from the switch description, else the GUID.
        name = (sw.description.split()[0] if sw and sw.description else switch_ib)
        return f"{name} ({n})"

    # -- selection state ----------------------------------------------------
    def _selected(self) -> List[str]:
        return sorted(h for h, b in self.blocks.items() if b.selected)

    def _count_text(self) -> str:
        return f"Selected: {len(self._selected())} / {len(self.blocks)} nodes"

    def _refresh_count(self) -> None:
        try:
            self.query_one("#topo-count", Static).update(self._count_text())
        except Exception:
            pass

    def _set_many(self, hostnames: List[str], value: bool) -> None:
        for h in hostnames:
            block = self.blocks.get(h)
            if block is not None:
                block.selected = value
        self._refresh_count()

    # -- events -------------------------------------------------------------
    @on(NodeToggled)
    def _on_node_toggled(self, event: NodeToggled) -> None:
        event.stop()
        self._refresh_count()

    @on(GroupToggle)
    def _on_group_toggle(self, event: GroupToggle) -> None:
        event.stop()
        # If every node in the group is already selected, clear it; else fill it.
        all_selected = all(
            self.blocks[h].selected for h in event.hostnames if h in self.blocks
        )
        self._set_many(event.hostnames, not all_selected)

    @on(Button.Pressed, "#topo-all")
    def _btn_all(self) -> None:
        self.action_select_all()

    @on(Button.Pressed, "#topo-clear")
    def _btn_clear(self) -> None:
        self.action_clear()

    @on(Button.Pressed, "#topo-invert")
    def _btn_invert(self) -> None:
        self.action_invert()

    @on(Button.Pressed, "#topo-confirm")
    def _btn_confirm(self) -> None:
        self.action_confirm()

    @on(Button.Pressed, "#topo-cancel")
    def _btn_cancel(self) -> None:
        self.action_cancel()

    # -- actions ------------------------------------------------------------
    def action_select_all(self) -> None:
        self._set_many(list(self.blocks), True)

    def action_clear(self) -> None:
        self._set_many(list(self.blocks), False)

    def action_invert(self) -> None:
        for block in self.blocks.values():
            block.selected = not block.selected
        self._refresh_count()

    def action_confirm(self) -> None:
        self.dismiss(self._selected())

    def action_cancel(self) -> None:
        self.dismiss(None)
