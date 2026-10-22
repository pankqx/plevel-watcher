# Plevel Watcher

Write code by typing a comment. A local Ollama model (default `qwen2.5-coder:1.5b`) answers, you review a diff, and it is written into your file. Fully offline, any language, no cloud.

```python
# plevel: write a program that prints the first 10 primes     ← press Enter
```

Two ways to use it. They share one engine and can run together.

| | What it does |
|---|---|
| **VS Code extension** | Type `# plevel: <task>` and press **Enter**. A diff opens; click **Apply** (or Discard). Works with `#`, `//`, `--`, `/* */`, `<!-- -->`. |
| **Terminal watcher** | `plevel-watch` runs in your project (VS Code terminal) until you press **Ctrl+C**. When any file is saved with a `# plevel:` comment, it asks the model, prints a colored diff and asks `Apply? [y/n]`. |

If you have both running, the extension creates `.plevel/busy` while it works so the watcher stays out of its way.

## Install (Ubuntu)

```bash
cd ~/Projects
git clone https://github.com/pankqx/plevel-watcher
cd plevel-watcher
./install.sh            # adds `plevel-watch` and links the VS Code extension
ollama pull qwen2.5-coder:1.5b
```
Restart VS Code. If the extension does not show up, try it in a throwaway window first: `code --extensionDevelopmentPath ~/Projects/plevel-watcher/vscode-extension ~/some-project`. You need Python 3.9+ (standard library only) and Node is **not** required to use the extension.
Update later with `git pull`.

## Use

**In the editor:** open any file, type `# plevel: add a function that reverses a string`, press Enter. Status bar shows *Plevel thinking…* (click to cancel). If the Enter key accepts an autocomplete suggestion instead, press **Ctrl+Alt+P** on the comment line.

**In the terminal:** open your project, then
```bash
plevel-watch                       # default model, asks before writing
plevel-watch --model qwen2.5-coder:7b
plevel-watch --yes                 # apply without asking (use git as your undo)
plevel-watch --keep-comment        # keep your comment above the generated code
```
Or Command Palette → **Plevel: Start project watcher in terminal**.

### Settings (VS Code → Settings → "plevel")
`plevel.model`, `plevel.host`, `plevel.approval` (`diff` or `direct`), `plevel.keepComment`, `plevel.temperature`, `plevel.numCtx`, `plevel.enabled`. Command **Plevel: Choose model** lists your installed models.

## How it decides what to write
It sends the model your file (the comment is marked, big files are windowed), a list of project files and, in the watcher, the most relevant snippets from other files (keyword search, same engine as the Plevel chat app). The extension also sends the first lines of your other open tabs. Nothing leaves your machine.

## Honest limits
- A 1.5B model writes small functions and scripts well; it can invent functions that do not exist and gets lost across many files. **Review every diff and run the code.**
- It replaces one comment with code; it does not refactor several files at once.
- The extension logic is tested against a mock of the VS Code API; real-editor quirks (autocomplete swallowing Enter, other extensions) may appear. Open an issue with what happened.

## Develop
```bash
./run_tests.sh      # Python core + watcher + extension (needs python3 and node 18+)
```
The Python engine (`plevel_watcher/agent.py`) and the JavaScript one (`vscode-extension/core.js`) are twins, checked against the same cases in `tests/vectors/comments.json`. See `AGENTS.md` before changing anything.

Companion project: [Plevel](https://github.com/pankqx/plevel), the desktop chat app for the same local models.
