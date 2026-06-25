"""Unified CINETIC command-line entry point.

    cinetic run      orchestrate a benchmark (submit a Slurm job)
    cinetic tui      launch the interactive TUI
    cinetic analyze  analyze tournament_nb per-node results
    cinetic topo     parse ibnetdiscover into a neutral topology JSON
    cinetic plot     plot blink results

Works as the installed ``cinetic`` console script, via ``python -m cinetic``,
or as a plain file (``python src/cinetic/__main__.py``) — the engine launches
the in-job worker through the last form (``cinetic _worker --workdir <dir>``).
"""

from __future__ import annotations

import argparse
import os
import sys

# When executed as a bare file (python src/cinetic/__main__.py …) there is no
# package context, so make the 'cinetic' package importable.
if __package__ in (None, ""):
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Subcommands that own their own argparse; we pass the remaining argv straight
# through to each module's main(argv).
_PASSTHROUGH = {
    "run": "orchestrate a benchmark (submit a Slurm job)",
    "tui": "launch the interactive TUI",
    "analyze": "analyze tournament_nb per-node results",
    "topo": "parse ibnetdiscover into a neutral topology JSON",
    "plot": "plot blink results",
}


def _build_parser() -> argparse.ArgumentParser:
    """Parser used only to render top-level help (the hidden _worker command is
    omitted). Actual dispatch is by first token so each subcommand keeps full
    control of its own argv — argparse REMAINDER mishandles ``--help``."""
    parser = argparse.ArgumentParser(
        prog="cinetic",
        description="CINETIC — co-running interference & network-topology "
                    "investigation for HPC clusters.")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    for name, help_text in _PASSTHROUGH.items():
        sub.add_parser(name, help=help_text, add_help=False)
    return parser


def _dispatch(command: str, rest: list[str]) -> int:
    if command == "run":
        from cinetic.cli.orchestrator import orchestrate_main
        return orchestrate_main(rest)
    if command == "tui":
        from cinetic.tui.app import BenchmarkApp
        BenchmarkApp().run()
        return 0
    if command == "analyze":
        from cinetic.analysis.cli import main as analyze_main
        return analyze_main(rest)
    if command == "topo":
        from cinetic.topology.parser import main as topo_main
        return topo_main(rest)
    if command == "plot":
        return _run_plot(rest)
    raise AssertionError(f"unhandled command {command!r}")


def _run_plot(rest: list[str]) -> int:
    """Run the standalone blink plotter with the given argv."""
    import runpy
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    script = os.path.join(repo, "blink_plotter.py")
    if not os.path.isfile(script):
        print(f"error: blink_plotter.py not found at {script}", file=sys.stderr)
        return 2
    sys.argv = [script, *rest]
    runpy.run_path(script, run_name="__main__")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv or argv[0] in ("-h", "--help"):
        _build_parser().print_help()
        return 0

    command, rest = argv[0], argv[1:]

    if command == "_worker":
        wp = argparse.ArgumentParser(prog="cinetic _worker")
        wp.add_argument("--workdir", required=True)
        ns = wp.parse_args(rest)
        from cinetic.cli.orchestrator import run_worker
        return run_worker(ns.workdir)

    if command in _PASSTHROUGH:
        return _dispatch(command, rest)

    sys.stderr.write(f"cinetic: unknown command {command!r}\n\n")
    _build_parser().print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
