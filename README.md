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
./install.sh
ollama pull qwen2.5-coder:1.5b
```
`install.sh` adds the `plevel-watch` terminal command and installs the VS Code extension (it builds a `.vsix` and runs `code --install-extension`). **Fully quit VS Code and open it again.** You should see **✨ Plevel** in the bottom-right status bar.

Check it: `code --list-extensions | grep plevel` prints `pankqx.plevel-watcher`.
Needs Python 3.9+ (standard library only). Node is not needed to use it.

If the `code` command is missing, the script prints a `.vsix` path: in VS Code open Extensions → `⋯` menu → **Install from VSIX…** and pick it.
If it still does not load, use the no-install fallback: `~/Projects/plevel-watcher/code-plevel.sh ~/Projects/my-project` (opens VS Code with Plevel loaded straight from the folder; the window is labelled "Extension Development Host").

## Update
```bash
cd ~/Projects/plevel-watcher && git pull && ./install.sh
```
Then restart VS Code.

## The ON/OFF button (bottom-right status bar)
Plevel starts **OFF** and does nothing until you switch it on, so it never surprises you.
- **○ Plevel OFF** → click it to turn **ON** (**✨ Plevel ON**, highlighted). Click again to turn OFF.
- While it is answering the button shows **Plevel thinking… (click to STOP)**. Click it to stop immediately.
- Turning OFF or pressing STOP cancels the request **and tells Ollama to unload the model**, which frees your GPU memory at once.
- Shortcuts: **Ctrl+Alt+O** on/off, **Ctrl+Alt+X** stop, **Ctrl+Alt+P** run on the current line.
- A request that gets no answer for 3 minutes is stopped automatically, and answers are capped at 1024 tokens (`plevel.maxTokens`).
- Other ways: Extensions panel → Plevel Watcher → **Disable** (or **Disable (Workspace)**). Terminal watcher: **Ctrl+C** or close its terminal.
- If it ever seems stuck, run `ollama stop qwen2.5-coder:1.5b`, or `sudo systemctl restart ollama`.
- Nothing runs when idle. Ollama frees the model about 5 minutes after the last answer.

## Uninstall (delete)
```bash
cd ~/Projects/plevel-watcher && ./uninstall.sh     # removes the extension and the terminal commands
rm -rf ~/Projects/plevel-watcher                    # optional: delete the source
```
Or by hand: Extensions panel → Plevel Watcher → **Uninstall**; `code --uninstall-extension pankqx.plevel-watcher`. Quit and reopen VS Code afterwards. Your projects are never modified by uninstalling; you may delete leftover `.plevel/` folders.

## Troubleshooting
| Symptom | Fix |
|---|---|
| Status bar says **Plevel OFF** | That is the default. Click it once to turn ON. |
| No Plevel item at all in the status bar | Run `./install.sh`, fully quit VS Code (not just reload), reopen. Check `code --list-extensions \| grep plevel`. Use `code-plevel.sh` as a fallback. |
| Enter does nothing | The comment must start the line: `# plevel: task`. If the suggestion popup is open, press **Ctrl+Alt+P** on the line. Make sure the status bar does not say "Plevel off". |
| "Is Ollama running?" error | `sudo systemctl start ollama`, then try again. `ollama list` must show your model. |
| Code appears with Tab, no diff | That is Continue's ghost-text autocomplete, not Plevel. Plevel always shows "thinking…" and a diff. |
| Slow first answer | The model is loading into the GPU. Later answers are faster. |

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
`plevel.model`, `plevel.host`, `plevel.approval` (`diff` or `direct`), `plevel.keepComment`, `plevel.temperature`, `plevel.numCtx`, `plevel.enabled` (default off), `plevel.maxTokens`. Command **Plevel: Choose model** lists your installed models.

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
