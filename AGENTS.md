# AGENTS.md: guide for AI assistants working on Plevel Watcher

Owner: Pank (GitHub `pankqx`). Goal: local, offline "type `# plevel: <task>` and get code" for VS Code and the terminal, using Ollama.

## Hard rules
- Commit as `pankqx <pankqx@gmail.com>` only. No `Co-Authored-By` trailers, no AI names in commits. Commit small and often.
- Offline only: the single network target is Ollama (`127.0.0.1:11434`). No telemetry.
- Python side: standard library only. Extension: plain JavaScript, no build step, no npm dependencies.
- Nothing is written to the user's files without approval unless they chose `--yes` / `plevel.approval = direct`.
- Target hardware: GTX 1650 4 GB; default model `qwen2.5-coder:1.5b`.

## Layout
| Path | Job |
|---|---|
| `plevel_watcher/agent.py` | Engine: comment regex, prompt, `extract_code`, `apply_code`, diff, Ollama streaming, lock helper. |
| `plevel_watcher/cli.py` | `plevel-watch`: polling watcher, diff + approve loop. |
| `plevel_watcher/context.py` | Project indexing and keyword retrieval (copied from the Plevel chat app; keep in sync by hand). |
| `vscode-extension/core.js` | JS twin of the engine (pure functions, no `vscode` import). |
| `vscode-extension/extension.js` | VS Code glue: Enter detection, status bar, diff view, apply, commands. |
| `tests/vectors/comments.json` | Shared cases. Any change to comment parsing, code extraction or apply behaviour must pass in BOTH languages. |
| `tools/make_vsix.py` | Builds `dist/plevel-watcher-<version>.vsix` with the standard library (no vsce/npm). |
| `install.sh` / `uninstall.sh` | Install or update: `plevel-watch` command + `code --install-extension <vsix>`. Uninstall reverses it. |
| `watch.sh` | Launcher for the terminal watcher. |
| `code-plevel.sh` | Fallback: opens VS Code with the extension loaded from the folder (`--extensionDevelopmentPath`). |

## Test
`./run_tests.sh` must end with all passes. The extension test (`vscode-extension/test/extension.test.js`) loads the real `extension.js` against a mock `vscode` module and a fake Ollama server; extend it when you change behaviour.

## Gotchas
- Enter detection: a change with empty range and text `"\n"` plus indent, `e.reason` unset (set means undo/redo), while no request is running.
- The comment line may move while the model is thinking; apply re-finds it by exact text and refuses if it changed.
- `.plevel/busy` is the lock the extension holds; the watcher skips work while it is fresh (5 min TTL).
- Only the first fenced block of a reply is used; unclosed fences are accepted.

## Install, update, disable, remove (users and assistants should give these exact steps)
- **Install / update:** `cd ~/Projects/plevel-watcher && git pull && ./install.sh`, then fully quit and reopen VS Code. Verify with `code --list-extensions | grep plevel` and the **✨ Plevel** status-bar item.
- **Do not install by symlinking into `~/.vscode/extensions`.** Recent VS Code ignores unregistered folders; always go through a `.vsix` (`./install.sh`) or `code-plevel.sh`.
- **Deactivate temporarily:** click **Plevel** in the status bar (Plevel is OFF by default; turning it OFF also cancels any running request and unloads the model), or Ctrl+Alt+O, or Command Palette → "Plevel: Turn on/off", or `plevel.enabled` = false, or Extensions panel → Disable. **Stuck while thinking:** click the status bar item (STOP), Ctrl+Alt+X, or `ollama stop <model>`. Stop the terminal watcher with Ctrl+C.
- **Delete:** `./uninstall.sh` (or `code --uninstall-extension pankqx.plevel-watcher`), then `rm -rf ~/Projects/plevel-watcher` if the source should go too.
- **Try changes without installing:** `./code-plevel.sh ~/some-project`, edit, then Command Palette → "Developer: Reload Window" in that window.

## How to make common changes
- **New comment syntax** (e.g. `%` or `REM`): extend the regex in BOTH `agent.py` (`COMMENT_RE`) and `core.js` (`COMMENT_RE`), add cases to `tests/vectors/comments.json`, run `./run_tests.sh`.
- **Better prompt:** edit `SYSTEM_PROMPT` in both `agent.py` and `core.js` (keep them identical) and `build_messages` in both. Try it on real comments before committing; small models are sensitive to wording.
- **New setting:** add it to `contributes.configuration` in `vscode-extension/package.json`, read it in `cfg()` in `extension.js`, document it in README.
- **New command:** add it to `contributes.commands`, register it with `reg('plevel.xxx', ...)` in `activate`, and add a test in `extension.test.js`.
- **Version bump:** change `version` in `vscode-extension/package.json` and `plevel_watcher/__init__.py`, run `./run_tests.sh` (the vsix test expects the file name to match), tell the user to run `./install.sh`.
- Never edit files outside this repo, and never commit `dist/`.
