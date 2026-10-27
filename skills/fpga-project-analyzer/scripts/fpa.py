#!/usr/bin/env python3
"""Entry point for running the analyzer from the skill folder (no install needed)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fpalib.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
