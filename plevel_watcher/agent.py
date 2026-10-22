"""Plevel agent core: turn a `# plevel: <task>` comment into code. No Qt, standard library only.

Used by the terminal watcher (plevel/cli.py). The VS Code extension has a JavaScript twin
(vscode-plevel/core.js); both are tested against tests/vectors/*.json so they behave the same.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import textwrap
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
if not DEFAULT_HOST.startswith("http"):
    DEFAULT_HOST = "http://" + DEFAULT_HOST
DEFAULT_MODEL = "qwen2.5-coder:1.5b"

# `# plevel: ...`, `// plevel: ...`, `-- plevel: ...`, `<!-- plevel: ... -->`, `/* plevel: ... */`
COMMENT_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<marker>#|//|--|;|%|/\*|<!--)[ \t]*plevel[ \t]*:[ \t]*(?P<task>.*?)"
    r"[ \t]*(?:\*/|-->)?[ \t]*$",
    re.IGNORECASE,
)

LANGS = {
    ".py": ("Python", "#"), ".js": ("JavaScript", "//"), ".mjs": ("JavaScript", "//"),
    ".ts": ("TypeScript", "//"), ".tsx": ("TypeScript React", "//"), ".jsx": ("JavaScript React", "//"),
    ".java": ("Java", "//"), ".kt": ("Kotlin", "//"), ".c": ("C", "//"), ".h": ("C", "//"),
    ".cpp": ("C++", "//"), ".cs": ("C#", "//"), ".go": ("Go", "//"), ".rs": ("Rust", "//"),
    ".rb": ("Ruby", "#"), ".php": ("PHP", "//"), ".swift": ("Swift", "//"), ".sh": ("Bash", "#"),
    ".sql": ("SQL", "--"), ".html": ("HTML", "<!--"), ".css": ("CSS", "/*"), ".yml": ("YAML", "#"),
    ".yaml": ("YAML", "#"), ".toml": ("TOML", "#"), ".md": ("Markdown", "<!--"), ".lua": ("Lua", "--"),
}

SYSTEM_PROMPT = (
    "You are Plevel, a code-writing assistant inside the user's editor. The user wrote an "
    "instruction as a comment in a file. Reply with ONLY the code that should replace that "
    "comment, inside exactly one fenced code block. Match the file's language, naming style and "
    "indentation, and reuse names and imports that already exist in the file. Prefer the "
    "standard library and never invent libraries or functions. If the instruction is a question "
    "that code cannot answer, reply with a short comment block in the file's comment syntax "
    "instead. Do not write any text outside the code block."
)


@dataclass
class Command:
    line: int          # 0-based line number of the comment
    indent: str
    task: str
    raw: str


def find_commands(text: str) -> list[Command]:
    out = []
    for i, line in enumerate(text.split("\n")):
        line = line.rstrip("\r")
        m = COMMENT_RE.match(line)
        if m and m.group("task").strip():
            out.append(Command(i, m.group("indent"), m.group("task").strip(), line))
    return out


def language_of(path: str) -> tuple[str, str]:
    return LANGS.get(Path(path).suffix.lower(), ("code", "#"))


def file_window(text: str, line: int, max_lines: int = 200, before: int = 80, after: int = 40) -> str:
    """The part of the file the model should see; the comment line is marked."""
    lines = text.split("\n")
    marked = list(lines)
    marked[line] = marked[line].rstrip("\r") + "   <-- INSTRUCTION IS HERE"
    if len(lines) <= max_lines:
        return "\n".join(marked)
    head = marked[:20]
    lo = max(20, line - before)
    hi = min(len(lines), line + after + 1)
    parts = head + (["..."] if lo > 20 else []) + marked[lo:hi] + (["..."] if hi < len(lines) else [])
    return "\n".join(parts)


def build_messages(cmd: Command, path: str, text: str, project=None, num_ctx: int = 4096) -> list[dict]:
    lang, _ = language_of(path)
    system = SYSTEM_PROMPT
    if project is not None and getattr(project, "file_count", 0):
        from .context import est_tokens, project_block  # local import keeps startup light
        rel = os.path.relpath(path, project.root) if os.path.isabs(path) else path
        budget = int(num_ctx * 0.3)
        tree = project.tree_text(min(400, int(budget * 0.3)))
        chosen, key = project.retrieve(cmd.task + " " + Path(path).name, max(budget - est_tokens(tree), 0))
        chosen = [c for c in chosen if c.path != rel]
        key = [c for c in key if c.path != rel]
        system += "\n\n" + project_block(project, chosen, key, tree)
    user = (
        f"File: {path} ({lang})\n\n```\n{file_window(text, cmd.line)}\n```\n\n"
        f"Instruction: {cmd.task}\n"
        "Reply with the code that replaces the instruction comment, in one fenced code block."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


_FENCE_OPEN = re.compile(r"^\s{0,3}`{3,}[\w+#.\-]*\s*$")
_FENCE_CLOSE = re.compile(r"^\s{0,3}`{3,}\s*$")


def extract_code(reply: str) -> str:
    """First fenced block of a reply (an unclosed fence is fine); plain text if there is none."""
    lines = reply.replace("\r\n", "\n").split("\n")
    body, inside, found = [], False, False
    for ln in lines:
        if not inside and _FENCE_OPEN.match(ln):
            inside, found = True, True
            continue
        if inside and _FENCE_CLOSE.match(ln):
            break
        if inside:
            body.append(ln)
    code = "\n".join(body) if found else reply
    return code.strip("\n").rstrip()


def reindent(code: str, indent: str) -> str:
    code = textwrap.dedent(code)
    return "\n".join((indent + ln) if ln.strip() else "" for ln in code.split("\n"))


def apply_code(text: str, cmd: Command, code: str, keep_comment: bool = False) -> str:
    """Replace the comment line with the generated code (re-indented to match the comment)."""
    lines = text.split("\n")
    if cmd.line >= len(lines) or lines[cmd.line].rstrip("\r") != cmd.raw:
        raise ValueError("the comment line changed; not applying")
    new = reindent(code, cmd.indent).split("\n")
    if keep_comment:
        new = [cmd.raw] + new
    eol = "\r" if lines[cmd.line].endswith("\r") else ""
    new = [ln + eol for ln in new]
    return "\n".join(lines[:cmd.line] + new + lines[cmd.line + 1:])


def unified_diff(old: str, new: str, path: str) -> str:
    return "".join(difflib.unified_diff(
        old.splitlines(True), new.splitlines(True), f"a/{path}", f"b/{path}", n=2))


# ------------------------------------------------------------------ ollama
def chat_stream(model: str, messages: list[dict], host: str = DEFAULT_HOST,
                temperature: float = 0.2, num_ctx: int = 4096, timeout: float = 300) -> Iterator[str]:
    body = json.dumps({"model": model, "messages": messages, "stream": True,
                       "options": {"temperature": temperature, "num_ctx": num_ctx}}).encode()
    req = urllib.request.Request(host.rstrip("/") + "/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            raw = raw.strip()
            if not raw:
                continue
            obj = json.loads(raw)
            if obj.get("error"):
                raise RuntimeError(obj["error"])
            piece = (obj.get("message") or {}).get("content", "")
            if piece:
                yield piece
            if obj.get("done"):
                break


def generate(cmd: Command, path: str, text: str, model: str = DEFAULT_MODEL, host: str = DEFAULT_HOST,
             project=None, temperature: float = 0.2, num_ctx: int = 4096, on_token=None) -> str:
    msgs = build_messages(cmd, path, text, project, num_ctx)
    reply = []
    for piece in chat_stream(model, msgs, host, temperature, num_ctx):
        reply.append(piece)
        if on_token:
            on_token(piece)
    return extract_code("".join(reply))


# -------------------------------------------------------------------- lock
LOCK_NAME = ".plevel/busy"
LOCK_TTL = 300  # seconds


def lock_is_fresh(root: str | os.PathLike) -> bool:
    try:
        return time.time() - (Path(root) / LOCK_NAME).stat().st_mtime < LOCK_TTL
    except OSError:
        return False
