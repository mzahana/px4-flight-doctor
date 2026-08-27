#!/usr/bin/env python3
"""Entry point for px4-flight-doctor. Run with the project venv:
    .venv/bin/python analyze.py <log.ulg> [options]
or after chmod +x, provided the venv python is first on PATH."""
import sys
from analyzer.cli import main

if __name__ == "__main__":
    sys.exit(main())
