import os
import sys

# Add the 'src' directory to the Python path so the 'cinetic' package is found.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from cinetic.cli.orchestrator import run_from_cli

if __name__ == "__main__":
    run_from_cli()
