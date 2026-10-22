"""Terminal helper:  python -m plevel_watcher.cli watch [--project DIR]

Runs in your project until you press Ctrl+C. When a saved file contains a line like
`# plevel: write a function that ...`, it asks the local model, shows a diff, and writes the
result into the file only after you approve. Works in any language (#, //, --, <!-- -->).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from . import agent
from .context import Project

POLL_SECONDS = 1.0
MAX_FILE_BYTES = 400_000


def paint(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() else text


def color_diff(diff: str) -> str:
    out = []
    for ln in diff.splitlines():
        if ln.startswith("+") and not ln.startswith("+++"):
            out.append(paint("32", ln))
        elif ln.startswith("-") and not ln.startswith("---"):
            out.append(paint("31", ln))
        elif ln.startswith("@@"):
            out.append(paint("36", ln))
        else:
            out.append(ln)
    return "\n".join(out)


class Watcher:
    def __init__(self, root: Path, model: str, host: str, auto_yes: bool, keep_comment: bool,
                 temperature: float, num_ctx: int, ask=input, out=print):
        self.root = root
        self.model, self.host = model, host
        self.auto_yes, self.keep_comment = auto_yes, keep_comment
        self.temperature, self.num_ctx = temperature, num_ctx
        self.ask, self.out = ask, out
        self.project = Project(root)
        self.seen: dict[str, float] = {}
        self.skipped: set[tuple[str, str]] = set()   # (file, comment) the user said no to
        self.first = True

    # ----------------------------------------------------------- scanning
    def watched_files(self) -> list[Path]:
        files = []
        for rel in self.project._list_paths():
            if self.project._wanted(rel):
                files.append(self.root / rel)
        return files

    def scan(self) -> list[Path]:
        """Files whose modification time changed since the last scan."""
        changed = []
        for p in self.watched_files():
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_size > MAX_FILE_BYTES:
                continue
            key = str(p)
            if key not in self.seen:
                self.seen[key] = st.st_mtime
                if not self.first:
                    changed.append(p)   # brand-new file
            elif st.st_mtime != self.seen[key]:
                self.seen[key] = st.st_mtime
                changed.append(p)
        self.first = False
        return changed

    # ------------------------------------------------------------ working
    def handle(self, path: Path) -> bool:
        """Answer the first open `plevel:` comment in a file. Returns True if the file was changed."""
        if agent.lock_is_fresh(self.root):
            return False                      # the VS Code extension is working on it
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return False
        rel = str(path.relative_to(self.root))
        for cmd in agent.find_commands(text):
            if (rel, cmd.raw) in self.skipped:
                continue
            return self.answer(path, rel, text, cmd)
        return False

    def answer(self, path: Path, rel: str, text: str, cmd: agent.Command) -> bool:
        self.out(paint("1", f"\n▸ {rel}:{cmd.line + 1}  {cmd.task}"))
        self.out(paint("2", f"  asking {self.model}…"))
        t0 = time.time()
        try:
            self.project.refresh()
            code = agent.generate(cmd, str(path), text, self.model, self.host, self.project,
                                  self.temperature, self.num_ctx)
        except Exception as exc:
            self.out(paint("31", f"  could not get an answer: {exc}"))
            self.skipped.add((rel, cmd.raw))
            return False
        if not code.strip():
            self.out(paint("33", "  the model returned nothing"))
            self.skipped.add((rel, cmd.raw))
            return False
        try:
            new = agent.apply_code(text, cmd, code, self.keep_comment)
        except ValueError as exc:
            self.out(paint("33", f"  {exc}"))
            return False
        self.out(paint("2", f"  done in {time.time() - t0:.1f}s. Proposed change:\n"))
        self.out(color_diff(agent.unified_diff(text, new, rel)))
        answer = "y" if self.auto_yes else self.ask("\nApply this change? [y]es / [n]o  ").strip().lower()
        if not answer.startswith("y"):
            self.skipped.add((rel, cmd.raw))
            self.out(paint("2", "  skipped. Edit the comment to ask again."))
            return False
        # re-read in case the file changed while we were waiting
        try:
            current = path.read_text(encoding="utf-8")
            new = agent.apply_code(current, cmd, code, self.keep_comment)
        except (ValueError, OSError):
            self.out(paint("33", "  the file changed in the meantime; save the comment again to retry"))
            return False
        path.write_text(new, encoding="utf-8")
        self.seen[str(path)] = path.stat().st_mtime
        self.out(paint("32", f"  written to {rel}"))
        return True

    def run_once(self) -> int:
        """Look for work once (used by tests). Returns how many files were changed."""
        n = 0
        for p in self.scan():
            while self.handle(p):
                n += 1
        return n

    def run(self):
        self.out(paint("1", f"Plevel watching {self.root}"))
        self.out(f"model {self.model} · write `# plevel: <what you want>` in any file and save. Ctrl+C to stop.")
        n = self.project.refresh()
        self.out(paint("2", f"{n} files indexed for context"))
        self.scan()
        # also answer comments that are already sitting in files when the watcher starts
        for p in self.watched_files():
            self.seen.pop(str(p), None)
        self.first = False
        try:
            while True:
                for p in self.scan():
                    while self.handle(p):
                        pass
                time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            self.out(paint("1", "\nPlevel watcher stopped."))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="plevel", description="Local AI helper for your project folder")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("watch", help="watch a project and answer `# plevel:` comments")
    w.add_argument("--project", default=os.getcwd(), help="project folder (default: current folder)")
    w.add_argument("--model", default=os.environ.get("PLEVEL_MODEL", agent.DEFAULT_MODEL))
    w.add_argument("--host", default=agent.DEFAULT_HOST)
    w.add_argument("--yes", action="store_true", help="apply without asking (git is then your undo)")
    w.add_argument("--keep-comment", action="store_true", help="keep the comment above the new code")
    w.add_argument("--temperature", type=float, default=0.2)
    w.add_argument("--num-ctx", type=int, default=4096)
    args = ap.parse_args(argv)
    root = Path(args.project).resolve()
    if not root.is_dir():
        print(f"Not a folder: {root}")
        return 2
    Watcher(root, args.model, args.host, args.yes, args.keep_comment, args.temperature, args.num_ctx).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
