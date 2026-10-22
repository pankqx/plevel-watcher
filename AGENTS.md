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
| `watch.sh`, `install.sh` | Launcher and one-time setup (symlinks). |

## Test
`./run_tests.sh` must end with all passes. The extension test (`vscode-extension/test/extension.test.js`) loads the real `extension.js` against a mock `vscode` module and a fake Ollama server; extend it when you change behaviour.

## Gotchas
- Enter detection: a change with empty range and text `"\n"` plus indent, `e.reason` unset (set means undo/redo), while no request is running.
- The comment line may move while the model is thinking; apply re-finds it by exact text and refuses if it changed.
- `.plevel/busy` is the lock the extension holds; the watcher skips work while it is fresh (5 min TTL).
- Only the first fenced block of a reply is used; unclosed fences are accepted.
