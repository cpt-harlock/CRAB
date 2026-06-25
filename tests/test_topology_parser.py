"""Tests for the ibnetdiscover topology parser.

Runnable two ways:
    python tests/test_topology_parser.py     # standalone, prints PASS/FAIL
    pytest tests/test_topology_parser.py     # if pytest is available

The fixture ``fixtures/example_ibnetdiscover.txt`` describes a small leaf/spine
fabric with two cells (see the header in that file for the expected layout).
"""

import os
import sys

# Make the 'cinetic' package under src/ importable.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from cinetic.topology import Locality, Topology, parse_ibnetdiscover  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "example_ibnetdiscover.txt")


def _topo():
    return parse_ibnetdiscover(FIXTURE)


def test_counts():
    t = _topo()
    assert len(t.nodes) == 8, f"expected 8 nodes, got {len(t.nodes)}"
    assert len(t.nics) == 9, f"expected 9 NICs, got {len(t.nics)}"
    assert len(t.switches) == 6, f"expected 6 switches, got {len(t.switches)}"
    assert len(t.leaf_switches) == 4, f"expected 4 leaves, got {len(t.leaf_switches)}"
    assert len(t.spine_switches) == 2, f"expected 2 spines, got {len(t.spine_switches)}"
    assert len(t.cells) == 2, f"expected 2 cells, got {len(t.cells)}"


def test_switch_roles():
    t = _topo()
    assert t.switches["S-0000000000000001"].is_spine
    assert t.switches["S-0000000000000002"].is_spine
    for leaf in ("S-0000000000001001", "S-0000000000001002",
                 "S-0000000000002001", "S-0000000000002002"):
        assert t.switches[leaf].is_leaf, f"{leaf} should be a leaf"


def test_node_nic_split():
    t = _topo()
    # lrdn0001 owns two HCAs, both cabled to leaf L1.
    n1 = t.nodes["lrdn0001"]
    assert sorted(n1.nics) == ["H-00000000000000a1", "H-00000000000000a2"]
    assert n1.switches == ["S-0000000000001001"]
    # Single-NIC node.
    assert len(t.nodes["lrdn0002"].nics) == 1
    # Each NIC knows its node and leaf switch.
    assert t.nics["H-00000000000000a1"].node == "lrdn0001"
    assert t.nics["H-00000000000000a1"].switch == "S-0000000000001001"


def test_cells_and_membership():
    t = _topo()
    assert t.nodes_in_cell("cell01") == [
        "lrdn0001", "lrdn0002", "lrdn0003", "lrdn0004"]
    assert t.nodes_in_cell("cell02") == [
        "lrdn0005", "lrdn0006", "lrdn0007", "lrdn0008"]
    cell01 = t.cell_by_name("cell01")
    assert sorted(cell01.leaf_switches) == [
        "S-0000000000001001", "S-0000000000001002"]
    assert cell01.spine_switches == ["S-0000000000000001"]


def test_locality():
    t = _topo()
    assert t.locality("lrdn0001", "lrdn0002") == Locality.SAME_SWITCH
    assert t.locality("lrdn0001", "lrdn0003") == Locality.SAME_CELL
    assert t.locality("lrdn0001", "lrdn0005") == Locality.CROSS_CELL


def test_roundtrip_serialization():
    t = _topo()
    restored = Topology.from_dict(t.to_dict())
    assert restored.to_dict() == t.to_dict()
    assert len(restored.nodes) == len(t.nodes)
    assert restored.locality("lrdn0001", "lrdn0005") == Locality.CROSS_CELL


def _run_standalone():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {fn.__name__}: {e!r}")
    print("-" * 40)
    if failed:
        print(f"{failed}/{len(tests)} test(s) failed")
        return 1
    print(f"All {len(tests)} tests passed")
    print()
    print(_topo().summary())
    return 0


if __name__ == "__main__":
    sys.exit(_run_standalone())
