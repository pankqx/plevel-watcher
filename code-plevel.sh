#!/usr/bin/env bash
# Fallback: open VS Code with Plevel loaded straight from this folder (no install needed):
#   ~/Projects/plevel-watcher/code-plevel.sh ~/Projects/my-project
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec code --extensionDevelopmentPath "$HERE/vscode-extension" "$@"
