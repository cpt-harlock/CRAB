"""Tests for the cross-config congestion comparison (congestion.compare_congestion).

Runnable two ways:
    python tests/test_congestion_compare.py     # standalone, prints PASS/FAIL
    pytest tests/test_congestion_compare.py
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from cinetic.analysis.congestion import (CongestionResult, LabelDegradation,    # noqa: E402
                                         compare_congestion,
                                         format_congestion_comparison,
                                         build_congestion_comparison_summary)


def _cr(bench, overall_drop, by_label):
    return CongestionResult(
        victim_app="0", victim_benchmark=bench,
        baseline_label="baseline", loaded_label="loaded",
        base_overall_bw=24.0, loaded_overall_bw=24.0 * (1 - overall_drop / 100),
        overall_bw_drop_pct=overall_drop,
        base_overall_lat=1e-3, loaded_overall_lat=1e-3, overall_lat_inc_pct=0.0,
        per_label=[LabelDegradation(label=l, base_bw=24.0,
                                    loaded_bw=24.0 * (1 - d / 100), bw_drop_pct=d)
                   for l, d in by_label.items()],
        n_common_nodes=8)


def _items():
    return [
        ("256K", 262144.0, _cr("tournament_nb.py", 3.8, {"same_cell": 3.9, "cross_cell": 4.2})),
        ("1M", 1048576.0, _cr("tournament_nb.py", 28.3, {"same_cell": 14.6, "cross_cell": 37.2})),
        ("4M", 4194304.0, _cr("tournament_nb.py", 1.4, {"same_cell": 0.8, "cross_cell": -1.5})),
    ]


def test_rows_and_label_order():
    cc = compare_congestion(_items())
    assert [r.label for r in cc.rows] == ["256K", "1M", "4M"]
    assert [round(r.overall_bw_drop_pct, 1) for r in cc.rows] == [3.8, 28.3, 1.4]
    # canonical topo order: same_cell before cross_cell
    assert cc.labels_seen == ["same_cell", "cross_cell"]
    assert cc.rows[1].by_label_drop["cross_cell"] == 37.2
    assert cc.rows[1].x == 1048576.0


def test_mixed_benchmark_caveat():
    items = _items()
    items[2] = ("a2a", 5.0, _cr("a2a_nb.py", 5.0, {"cross_cell": 5.0}))
    cc = compare_congestion(items)
    assert any("mix victim benchmarks" in c for c in cc.caveats)


def test_format_and_summary():
    cc = compare_congestion(_items())
    txt = format_congestion_comparison(cc)
    assert "CONGESTION COMPARISON" in txt and "cross_cell" in txt
    assert "+28.3%" in txt
    s = build_congestion_comparison_summary(cc)
    assert len(s["configs"]) == 3 and s["labels"] == ["same_cell", "cross_cell"]
    assert s["configs"][1]["by_label_drop_pct"]["cross_cell"] == 37.2


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
    print(f"{failed}/{len(tests)} failed" if failed else f"All {len(tests)} tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_standalone())
