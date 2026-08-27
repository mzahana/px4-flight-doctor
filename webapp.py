#!/usr/bin/env python3
"""Backwards-compatible shim - the app lives in analyzer/webapp.py.
Prefer the installed command:  px4doctor-web"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyzer.webapp import main

if __name__ == "__main__":
    main()
