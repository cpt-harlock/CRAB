import os
import sys

# Add the 'src' directory to the Python path so the 'cinetic' package is found.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

if __name__ == "__main__":
    # Backward-compat: an older engine could re-invoke the worker as
    # "<python> <sys.argv[0]> --worker --workdir ...". If the TUI was the entry
    # point, sys.argv[0] is this file, so in worker mode we must NOT relaunch the
    # TUI (which would render ANSI codes into the logs) but run the worker logic.
    if "--worker" in sys.argv:
        from cinetic.cli.orchestrator import run_from_cli
        run_from_cli()
    else:
        from cinetic.tui.app import CineticApp
        app = CineticApp()
        app.run()
