#!/bin/bash
# The Mac test gate: exits non-zero if any test fails (use before every commit and push).
# The suite runs on a throwaway data folder; the personal-data check then reads the real history
# (~/Library/Application Support/Ecoscribe) so no dictation text can reach the repo (CLAUDE.md rule 7).
cd "$(dirname "$0")/.." || exit 1
PY="${ECOSCRIBE_PY:-.venv/bin/python}"
ECOSCRIBE_DATA_DIR="$(mktemp -d)" "$PY" -m pytest -q -p no:cacheprovider "$@" || exit 1
[ $# -eq 0 ] || exit 0  # a subset run: skip the history check
env -u ECOSCRIBE_DATA_DIR "$PY" -m pytest -q -p no:cacheprovider tests/test_no_personal_data.py
