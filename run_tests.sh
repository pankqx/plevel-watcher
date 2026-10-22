#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python3 tests/test_agent.py | tail -1
python3 tests/test_cli.py | tail -1
python3 tests/test_vsix.py | tail -1
(cd vscode-extension && node --test test/*.test.js 2>&1 | grep -E "^# (tests|pass|fail)")
