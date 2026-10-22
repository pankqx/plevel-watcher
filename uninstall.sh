#!/usr/bin/env bash
# Remove Plevel Watcher from VS Code and your PATH. Your projects are not touched.
set -e
if command -v code >/dev/null 2>&1; then
  code --uninstall-extension pankqx.plevel-watcher || true
fi
rm -f "$HOME/.local/bin/plevel-watch" "$HOME/.local/bin/code-plevel"
rm -rf "$HOME/.vscode/extensions/pankqx.plevel-watcher-0.1.0" 2>/dev/null || true
echo "✔ removed. Quit VS Code and open it again."
echo "  To delete the source too:  rm -rf $(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "  Leftover per-project lock folders (.plevel/) are harmless and can be deleted."
