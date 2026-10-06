#!/bin/bash
# The Mac test gate: exits non-zero if any test fails (use before every commit).
cd "$(dirname "$0")/.." && DICTADO_DATA_DIR="$(mktemp -d)" "${DICTADO_PY:-.venv/bin/python}" -m pytest -q -p no:cacheprovider "$@"
