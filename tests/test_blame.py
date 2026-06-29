"""Tests for fabric fault localization (analysis/blame.py).

Runnable two ways:
    python tests/test_blame.py     # standalone, prints PASS/FAIL
    pytest tests/test_blame.py     # if pytest is available

Builds a synthetic 2-cell fabric (leaf L1 / leaf L2 / spine SP, 5 nodes each)
and an all-pairs pairwise analysis with injected slowdowns, then checks the
localizer points at the right element and does not false-positive. See
PLAN_FABRIC_FAULT_LOCALIZATION.md §Validation.
"""

import os
import sys
from types import SimpleNamespace

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from cinetic.analysis.blame import compute_blame          # noqa: E402
from cinetic.analysis.params import Params                # noqa: E402

REF = 24.0
L1_NODES = [f"n{i}" for i in range(1, 6)]      # under leaf L1 (cell c1)
L2_NODES = [f"n{i}" for i in range(6, 11)]     # under leaf L2 (cell c2)
ALL_NODES = L1_NODES + L2_NODES
LEAF = {h: "L1" for h in L1_NODES} | {h: "L2" for h in L2_NODES}


def _topo():
    """Duck-typed Topology: L1 -- SP -- L2, nodes split across the two leaves."""
    def sw(name, peers):
        return SimpleNamespace(role="leaf" if name != "SP" else "spine",
                               links=[SimpleNamespace(peer_name=p) for p in peers])
    switches = {"L1": sw("L1", ["SP"]), "L2": sw("L2", ["SP"]),
                "SP": sw("SP", ["L1", "L2"])}
    nodes = {h: SimpleNamespace(switches=[LEAF[h]]) for h in ALL_NODES}
    cells = [SimpleNamespace(name="c1", leaf_switches=["L1"], spine_switches=[]),
             SimpleNamespace(name="c2", leaf_switches=["L2"], spine_switches=[])]
    return SimpleNamespace(switches=switches, nodes=nodes, cells=cells)


def _analysis(bw_func):
    """All-pairs pairwise analysis; bw_func(a,b) -> GB/s sets each flow."""
    pairings, flows_by_node = [], {h: [] for h in ALL_NODES}
    for i in range(len(ALL_NODES)):
        for j in range(i + 1, len(ALL_NODES)):
            a, b = ALL_NODES[i], ALL_NODES[j]
            bw = bw_func(a, b)
            # bandwidth_gbs = bytes/dur/1e9; dur=1 => bytes = bw*1e9
            pairings.append(SimpleNamespace(node_a=a, node_b=b, durations=[1.0],
                                            bytes_per_sample=bw * 1e9))
            flows_by_node[a].append(bw); flows_by_node[b].append(bw)
    import numpy as np
    nodes = [SimpleNamespace(node=h, median_bw_gbs=float(np.median(flows_by_node[h])))
             for h in ALL_NODES]
    return SimpleNamespace(kind="pairwise", pairings=pairings,
                           params=Params(1, 1, 1, "test"), nodes=nodes)


def _blame(bw_func):
    return compute_blame([_analysis(bw_func)], _topo(), ref_bw=REF)


def test_healthy_no_suspects():
    br = _blame(lambda a, b: REF)
    assert not br.leaf_suspects, f"leaf false positive: {br.leaf_suspects}"
    assert not br.node_suspects, f"node false positive: {br.node_suspects}"
    assert not br.spine_suspects, f"spine false positive: {br.spine_suspects}"


def test_slow_node_blamed_as_node_not_leaf():
    # n3 slow on every flow it touches
    br = _blame(lambda a, b: 12.0 if "n3" in (a, b) else REF)
    names = [s.name for s in br.node_suspects]
    assert names == ["n3"], f"expected node n3, got {names}"
    assert not br.leaf_suspects, f"node fault wrongly blamed on a leaf: {br.leaf_suspects}"


def test_slow_leaf_blamed_as_leaf_with_nodes():
    # L1 crossbar degraded: only intra-L1 flows slow
    br = _blame(lambda a, b: 12.0 if LEAF[a] == LEAF[b] == "L1" else REF)
    leaves = [s.name for s in br.leaf_suspects]
    assert leaves == ["L1"], f"expected leaf L1, got {leaves}"
    assert len(br.leaf_suspects[0].nodes) >= 2, "leaf must cite >=2 nodes"
    assert not br.node_suspects, f"leaf fault wrongly blamed on a node: {br.node_suspects}"
    assert not br.spine_suspects, "intra-leaf fault must not implicate the spine"


def test_slow_spine_blamed_low_confidence_no_leaf():
    # only cross-cell flows slow (a spine/uplink issue)
    br = _blame(lambda a, b: 12.0 if LEAF[a] != LEAF[b] else REF)
    assert not br.leaf_suspects, f"spine fault wrongly blamed on a leaf: {br.leaf_suspects}"
    assert not br.node_suspects, f"spine fault wrongly blamed on a node: {br.node_suspects}"
    assert br.spine_suspects, "spine fault should produce spine suspects"
    assert all(s.confidence == "low" for s in br.spine_suspects)
    assert "SP" in " ".join(s.name for s in br.spine_suspects), "SP should be implicated"


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
    return 0


if __name__ == "__main__":
    sys.exit(_run_standalone())
