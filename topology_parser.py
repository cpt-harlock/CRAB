import os
import sys

# Make the 'crab' package under src/ importable, mirroring cli.py / tui.py.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from crab.topology.parser import main

if __name__ == "__main__":
    sys.exit(main())
