#!/usr/bin/env bash
# One-shot installer for px4-flight-doctor.
# Creates a local virtualenv (.venv), installs all dependencies and the
# package itself (editable, so web/ and docs/ resolve from this folder).
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
if ! command -v "$PY" >/dev/null; then
    echo "error: python3 not found (set PYTHON=/path/to/python and retry)"; exit 1
fi

if [ ! -d .venv ]; then
    echo "-> creating virtualenv .venv"
    "$PY" -m venv .venv
fi
echo "-> installing package + dependencies"
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -e . -q

echo
echo "Installed. Two ways to run:"
echo "  .venv/bin/px4doctor <flight.ulg> [--vehicle my_drone.yaml] [--report]   # CLI"
echo "  .venv/bin/px4doctor-web                                                 # web UI at http://127.0.0.1:8050"
echo
echo "Tip: 'source .venv/bin/activate' puts px4doctor / px4doctor-web on your PATH."
