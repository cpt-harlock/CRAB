"""Tests for explicit nodelist wiring into the generated SBATCH header.

    python tests/test_engine_nodelist.py
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from crab.core.engine import Engine, normalize_nodelist  # noqa: E402


def _header(global_opts):
    eng = Engine(log_callback=lambda *_: None)
    return eng._generate_sbatch_header(global_opts, "/tmp/crab_test")


def test_normalize_nodelist():
    assert normalize_nodelist(None) == []
    assert normalize_nodelist("") == []
    assert normalize_nodelist(["a", "b"]) == ["a", "b"]
    assert normalize_nodelist("a,b,c") == ["a", "b", "c"]
    assert normalize_nodelist("a b  c") == ["a", "b", "c"]
    assert normalize_nodelist("a, b , a") == ["a", "b"]  # dedup, order kept


def test_header_with_nodelist():
    lines = _header({
        "numnodes": "99",          # should be overridden by the nodelist length
        "ppn": "1",
        "nodelist": ["lrdn0001", "lrdn0002", "lrdn0003"],
    })
    joined = "\n".join(lines)
    assert "#SBATCH --nodelist=lrdn0001,lrdn0002,lrdn0003" in joined, joined
    assert "#SBATCH --nodes=3" in joined, joined          # count == len(nodelist)
    assert "--nodes=99" not in joined


def test_header_without_nodelist():
    lines = _header({"numnodes": "8", "ppn": "2"})
    joined = "\n".join(lines)
    assert "#SBATCH --nodes=8" in joined, joined
    assert "--nodelist" not in joined, joined
    assert "#SBATCH --ntasks-per-node=2" in joined


def test_user_cannot_override_nodelist():
    lines = _header({
        "numnodes": "2",
        "ppn": "1",
        "nodelist": ["good01", "good02"],
        # Malicious/мismatched user override must be ignored.
        "sbatch_directives": ["--nodelist=evil01", "-w evil02", "--nodes=50"],
    })
    joined = "\n".join(lines)
    assert "evil01" not in joined and "evil02" not in joined, joined
    assert "#SBATCH --nodelist=good01,good02" in joined, joined
    assert "#SBATCH --nodes=2" in joined, joined
    assert "--nodes=50" not in joined


def _run():
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
    sys.exit(_run())
