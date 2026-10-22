#!/usr/bin/env bash
# One-time setup:  ./install.sh
#  1. puts `plevel-watch` on your PATH (~/.local/bin)
#  2. installs the VS Code extension (linked from this folder, so `git pull` updates it)
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$HOME/.local/bin"
ln -sf "$HERE/watch.sh" "$HOME/.local/bin/plevel-watch"
chmod +x "$HERE/watch.sh"
echo "✔ plevel-watch command: $HOME/.local/bin/plevel-watch"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "  (add ~/.local/bin to your PATH if 'plevel-watch' is not found)";; esac

EXT_DIR="$HOME/.vscode/extensions/pankqx.plevel-watcher-0.1.0"
mkdir -p "$HOME/.vscode/extensions"
rm -rf "$EXT_DIR"
ln -s "$HERE/vscode-extension" "$EXT_DIR"
echo "✔ VS Code extension linked: $EXT_DIR"
echo "  Restart VS Code (or run 'Developer: Reload Window')."
echo
echo "Make sure Ollama has the model:  ollama pull qwen2.5-coder:1.5b"
