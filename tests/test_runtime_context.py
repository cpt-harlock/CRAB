"""Tests for the typed RuntimeContext and its use by the wl_manager backends.

    python tests/test_runtime_context.py
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from cinetic.runtime import RuntimeContext            # noqa: E402
from cinetic.core.wl_manager import mpi, slurm        # noqa: E402


def test_from_env_typed_fields():
    env = {
        "CINETIC_ROOT": "/opt/cinetic",
        "CINETIC_SYSTEM": "leonardo",
        "CINETIC_WL_MANAGER": "mpi",
        "CINETIC_WRAPPERS_PATH": "/opt/cinetic/wrappers",
        "CINETIC_PINNING_FLAGS": "--cpu-bind=cores",
        "CINETIC_MINIFE_PATH": "/opt/minife",  # benchmark-specific, stays in raw
    }
    ctx = RuntimeContext.from_env(env)
    assert ctx.root == "/opt/cinetic"
    assert ctx.system == "leonardo"
    assert ctx.wl_manager == "mpi"
    assert ctx.wrappers_path == "/opt/cinetic/wrappers"
    assert ctx.pinning_flags == "--cpu-bind=cores"
    # untyped keys remain reachable through the raw snapshot
    assert ctx.get("CINETIC_MINIFE_PATH") == "/opt/minife"


def test_defaults_when_unset():
    ctx = RuntimeContext.from_env({})
    assert ctx.system == "unknown"      # engine's historical default
    assert ctx.wl_manager == "slurm"    # default backend
    assert ctx.mpirun == ""
    assert ctx.wrappers_path == ""


def test_legacy_crab_keys_are_mirrored():
    ctx = RuntimeContext.from_env({"CRAB_SYSTEM": "old", "CRAB_ROOT": "/legacy"})
    assert ctx.system == "old"
    assert ctx.root == "/legacy"


def test_existing_cinetic_key_wins_over_legacy():
    ctx = RuntimeContext.from_env({"CRAB_SYSTEM": "old", "CINETIC_SYSTEM": "new"})
    assert ctx.system == "new"


def test_slurm_run_job_uses_ctx_no_env():
    ctx = RuntimeContext(pinning_flags="--cpu-bind=cores")
    cmd = slurm.wl_manager(ctx).run_job(["n1", "n2"], 4, "a.out")
    assert "--nodelist n1,n2" in cmd
    assert "--cpu-bind=cores" in cmd
    assert "-n 8" in cmd and "-N 2" in cmd


def test_mpi_run_job_builds_command_from_ctx():
    ctx = RuntimeContext(
        mpirun="mpirun", mpirun_map_by_node_flag="--map-by node",
        mpirun_additional_flags="--bind-to core", mpirun_hostnames_flag="--host",
        pinning_flags="")
    cmd = mpi.wl_manager(ctx).run_job(["n1", "n2"], 4, "a.out")
    assert cmd.startswith("mpirun --map-by node --bind-to core")
    assert "--host n1,n2" in cmd
    assert "-np 8" in cmd
    assert "  " not in cmd                 # empty flags collapse, no double spaces


def test_frozen_context_is_immutable():
    ctx = RuntimeContext(system="leonardo")
    try:
        ctx.system = "other"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("RuntimeContext should be frozen/immutable")


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
