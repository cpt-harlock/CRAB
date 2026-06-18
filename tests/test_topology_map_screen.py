"""Headless smoke test of the graphical topology selector modal.

Runs the Textual screen with a pilot, exercises node toggling, bulk group
selection, and the confirm/cancel return values. Requires textual.

    python tests/test_topology_map_screen.py
"""

import asyncio
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from textual.app import App  # noqa: E402

from crab.topology import Topology  # noqa: E402
from crab.tui.widgets.topology_map import (  # noqa: E402
    NodeBlock,
    TopologyMapScreen,
)

TOPO = os.path.join(ROOT, "topologies", "example.json")


class _Harness(App):
    """Minimal app that opens the modal and captures its result."""

    CSS_PATH = os.path.join(ROOT, "src", "crab", "tui", "assets", "tui.tcss")

    def __init__(self, topology, preselected=None):
        super().__init__()
        self.topology = topology
        self.preselected = preselected or set()
        self.result = "UNSET"

    def on_mount(self) -> None:
        self.push_screen(
            TopologyMapScreen(self.topology, preselected=self.preselected),
            lambda r: setattr(self, "result", r),
        )


async def _scenario_confirm_subset():
    topo = Topology.load(TOPO)
    app = _Harness(topo)
    async with app.run_test() as pilot:
        screen = app.screen
        assert isinstance(screen, TopologyMapScreen)
        # All 8 nodes rendered as blocks.
        assert len(screen.blocks) == 8, len(screen.blocks)

        # Toggle two individual nodes on.
        screen.blocks["lrdn0001"].selected = True
        screen.blocks["lrdn0005"].selected = True
        await pilot.pause()
        assert screen._selected() == ["lrdn0001", "lrdn0005"]

        # Confirm.
        screen.action_confirm()
        await pilot.pause()
    assert app.result == ["lrdn0001", "lrdn0005"], app.result


async def _scenario_group_and_cancel():
    topo = Topology.load(TOPO)
    app = _Harness(topo)
    async with app.run_test() as pilot:
        screen = app.screen
        # Selecting all of cell01 should yield its 4 nodes.
        cell01_hosts = topo.nodes_in_cell("cell01")
        screen._set_many(cell01_hosts, True)
        await pilot.pause()
        assert screen._selected() == cell01_hosts

        # Cancel discards everything.
        screen.action_cancel()
        await pilot.pause()
    assert app.result is None, app.result


async def _scenario_preselection_roundtrip():
    topo = Topology.load(TOPO)
    pre = {"lrdn0002", "lrdn0008"}
    app = _Harness(topo, preselected=pre)
    async with app.run_test() as pilot:
        screen = app.screen
        await pilot.pause()
        assert set(screen._selected()) == pre
        screen.action_select_all()
        await pilot.pause()
        assert len(screen._selected()) == 8
        screen.action_confirm()
        await pilot.pause()
    assert len(app.result) == 8


def _run():
    scenarios = [
        _scenario_confirm_subset,
        _scenario_group_and_cancel,
        _scenario_preselection_roundtrip,
    ]
    failed = 0
    for sc in scenarios:
        try:
            asyncio.run(sc())
            print(f"PASS  {sc.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {sc.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {sc.__name__}: {e!r}")
    print("-" * 40)
    if failed:
        print(f"{failed}/{len(scenarios)} scenario(s) failed")
        return 1
    print(f"All {len(scenarios)} scenarios passed")
    return 0


if __name__ == "__main__":
    sys.exit(_run())
