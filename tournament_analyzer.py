#!/usr/bin/env python3
"""Compatibility shim — prefer `cinetic analyze <run_dir|exp_dir> …`.

The analyzer now lives in the package at cinetic.analysis.cli; this thin
wrapper keeps the historical `python tournament_analyzer.py …` invocation
working. See PLAN_RESULT_ANALYZER.md for the design.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from cinetic.analysis.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
