#!/usr/bin/env bash
# Install or update Plevel Watcher:   ./install.sh
#  1. adds the `plevel-watch` terminal command (~/.local/bin)
#  2. builds the VS Code extension (.vsix) and installs it with `code --install-extension`
# Run it again after every `git pull` to update.
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
chmod +x "$HERE/watch.sh" "$HERE/code-plevel.sh"

mkdir -p "$HOME/.local/bin"
ln -sf "$HERE/watch.sh" "$HOME/.local/bin/plevel-watch"
ln -sf "$HERE/code-plevel.sh" "$HOME/.local/bin/code-plevel"
echo "✔ terminal command: plevel-watch (and code-plevel, a fallback launcher)"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "  (add ~/.local/bin to your PATH if 'plevel-watch' is not found)";; esac

# an older version of this installer linked a folder into ~/.vscode/extensions; VS Code ignores that
rm -rf "$HOME/.vscode/extensions/pankqx.plevel-watcher-0.1.0" 2>/dev/null || true

VSIX="$(python3 "$HERE/tools/make_vsix.py")"
echo "✔ built $VSIX"

if command -v code >/dev/null 2>&1; then
  code --install-extension "$VSIX" --force
  echo "✔ installed in VS Code. Fully quit VS Code and open it again."
  echo "  Check:  code --list-extensions | grep plevel      (should print pankqx.plevel-watcher)"
else
  echo "✘ the 'code' command was not found, so the extension was not installed."
  echo "  In VS Code: Extensions panel → ⋯ menu → 'Install from VSIX…' → choose:"
  echo "  $VSIX"
fi
echo
echo "Make sure Ollama has the model:  ollama pull qwen2.5-coder:1.5b"
