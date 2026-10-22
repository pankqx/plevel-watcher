#!/usr/bin/env bash
# Run from inside any project folder:   ~/Projects/plevel-watcher/watch.sh [--model qwen2.5-coder:7b] [--yes]
# Stops with Ctrl+C.
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$HERE/.venv/bin/python"
[ -x "$PY" ] || PY=python3
cd "${PLEVEL_PROJECT:-$PWD}"
PYTHONPATH="$HERE" exec "$PY" -m plevel_watcher.cli watch --project "$PWD" "$@"
