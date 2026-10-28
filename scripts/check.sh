#!/usr/bin/env bash
# Fast feedback: lint, types, unit tests (no database, no CDK synth), evals and the release gate.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-.venv/bin/python}
"$PY" -m ruff check src infra tests
"$PY" -m ruff format --check src infra tests
"$PY" -m mypy
"$PY" -m pytest -q -m "not db and not slow"
"$PY" -m powerdesk.cli evals all
"$PY" -m powerdesk.cli gate
