"""Project folder indexing and relevance-based context building.

Pure Python (no Qt) so it can be tested on its own.

How it works:
  1. Scan the folder (using `git ls-files` when it is a git repo, otherwise a
     directory walk) and split text files into ~40-line chunks.
  2. For each question, score chunks by keyword overlap with the question
     (rare words count more, file-name matches count a lot) and pick the best
     ones that fit the token budget.
  3. Add a compact file tree, put everything into the system message, and trim
     old chat history so the whole request fits in the model's context window.

Nothing here understands code semantically: it is keyword retrieval, not
embeddings, so it is fast and needs no extra model.
"""

from __future__ import annotations

import math
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

TEXT_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".java", ".kt", ".kts", ".c", ".h",
    ".cpp", ".hpp", ".cc", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".scala", ".dart",
    ".html", ".htm", ".css", ".scss", ".sass", ".less", ".vue", ".svelte", ".json", ".yml",
    ".yaml", ".toml", ".ini", ".cfg", ".conf", ".env.example", ".xml", ".gradle", ".properties",
    ".md", ".rst", ".txt", ".sql", ".sh", ".bash", ".zsh", ".ps1", ".bat", ".r", ".lua", ".ejs",
    ".dockerfile", ".tf", ".proto", ".graphql", ".csv",
}
SPECIAL_NAMES = {"Dockerfile", "Makefile", "CMakeLists.txt", "Procfile", ".gitignore", ".env.example"}
IGNORE_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build", ".next",
    ".nuxt", "target", ".idea", ".vscode", ".gradle", "vendor", "coverage", ".cache", ".pytest_cache",
    ".mypy_cache", "site-packages", ".dart_tool", "Pods", "bin", "obj", ".svn", ".hg",
}
SKIP_FILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock",
              "composer.lock", "Gemfile.lock"}
SKIP_SUFFIXES = (".min.js", ".min.css", ".map", ".lock")

MAX_FILE_BYTES = 300_000
MAX_TOTAL_BYTES = 40_000_000
MAX_FILES = 4000
CHUNK_LINES = 40
ANSWER_RESERVE = 1200          # tokens kept free for the model's reply (scaled down for tiny windows)
PROJECT_SHARE = 0.55           # max share of the remaining window for project code
TREE_TOKEN_CAP = 500
KEY_FILES = ("README.md", "readme.md", "README.rst", "package.json", "pyproject.toml",
             "requirements.txt", "pom.xml", "build.gradle", "Cargo.toml", "go.mod")

STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "how", "what", "why", "can", "you", "are",
    "does", "not", "from", "have", "has", "into", "when", "where", "which", "there", "their",
    "about", "would", "could", "should", "please", "make", "need", "want", "get", "use",
    "using", "file", "files", "code", "project", "function", "class", "add", "fix", "show",
    "explain", "tell", "help", "work", "works", "working", "error", "line", "lines",
}


def est_tokens(text: str) -> int:
    """Rough token estimate for code and English (about 3.5 characters per token)."""
    return int(len(text) / 3.5) + 1


def split_identifier(word: str) -> list[str]:
    parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", word).replace("_", " ").replace("-", " ").split()
    return [p.lower() for p in parts if len(p) >= 3]


def query_terms(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text):
        for t in [w.lower()] + split_identifier(w):
            if t not in STOPWORDS and len(t) >= 3:
                seen[t] = None
    return list(seen)[:24]


@dataclass
class Chunk:
    path: str
    start: int          # 1-based first line
    end: int            # last line
    text: str
    lower: str
    tokens: int


class Project:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root).resolve()
        self.name = self.root.name
        self._files: dict[str, tuple[float, int, list[Chunk]]] = {}
        self.skipped_large = 0
        self.truncated = False

    # ------------------------------------------------------------ scanning
    def _list_paths(self) -> list[str]:
        if (self.root / ".git").exists():
            try:
                out = subprocess.run(
                    ["git", "ls-files", "-co", "--exclude-standard", "-z"],
                    cwd=self.root, capture_output=True, timeout=15, check=True,
                ).stdout.decode("utf-8", "replace")
                paths = [p for p in out.split("\0") if p]
                if paths:
                    return paths
            except (OSError, subprocess.SubprocessError):
                pass
        paths = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".git")]
            for fn in filenames:
                paths.append(os.path.relpath(os.path.join(dirpath, fn), self.root))
        return paths

    @staticmethod
    def _wanted(rel: str) -> bool:
        p = Path(rel)
        if any(part in IGNORE_DIRS for part in p.parts[:-1]):
            return False
        name = p.name
        if name in SKIP_FILES or name.endswith(SKIP_SUFFIXES):
            return False
        return name in SPECIAL_NAMES or p.suffix.lower() in TEXT_EXTS

    def _chunk_file(self, rel: str, text: str) -> list[Chunk]:
        lines = text.splitlines()
        chunks = []
        for i in range(0, max(len(lines), 1), CHUNK_LINES):
            body = "\n".join(lines[i:i + CHUNK_LINES])
            if not body.strip():
                continue
            chunks.append(Chunk(rel, i + 1, min(i + CHUNK_LINES, len(lines)), body,
                                body.lower(), est_tokens(body)))
        return chunks

    def refresh(self) -> int:
        """(Re)scan the folder; only changed files are re-read. Returns file count."""
        total_bytes = 0
        seen: set[str] = set()
        self.skipped_large = 0
        self.truncated = False
        for rel in self._list_paths():
            if len(seen) >= MAX_FILES:
                self.truncated = True
                break
            if not self._wanted(rel):
                continue
            full = self.root / rel
            try:
                st = full.stat()
            except OSError:
                continue
            if st.st_size > MAX_FILE_BYTES:
                self.skipped_large += 1
                continue
            if total_bytes + st.st_size > MAX_TOTAL_BYTES:
                self.truncated = True
                break
            total_bytes += st.st_size
            cached = self._files.get(rel)
            if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
                seen.add(rel)
                continue
            try:
                raw = full.read_bytes()
            except OSError:
                continue
            if b"\0" in raw[:4096]:
                continue
            self._files[rel] = (st.st_mtime, st.st_size,
                                self._chunk_file(rel, raw.decode("utf-8", "replace")))
            seen.add(rel)
        for gone in set(self._files) - seen:
            del self._files[gone]
        return len(self._files)

    # ----------------------------------------------------------- accessors
    @property
    def file_count(self) -> int:
        return len(self._files)

    @property
    def total_tokens(self) -> int:
        return sum(c.tokens for _, _, chunks in self._files.values() for c in chunks)

    def paths(self) -> list[str]:
        return sorted(self._files)

    def tree_text(self, token_cap: int = TREE_TOKEN_CAP) -> str:
        paths = self.paths()
        text = "\n".join(paths)
        if est_tokens(text) <= token_cap:
            return text
        # too many files: summarise by directory
        counts: dict[str, int] = {}
        for p in paths:
            d = str(Path(p).parent)
            counts[d] = counts.get(d, 0) + 1
        lines = [f"{d}/  ({n} files)" if d != "." else f"./  ({n} files)" for d, n in sorted(counts.items())]
        out, used = [], 0
        for ln in lines:
            used += est_tokens(ln)
            if used > token_cap:
                out.append("... (more folders not shown)")
                break
            out.append(ln)
        return "\n".join(out)

    # ----------------------------------------------------------- retrieval
    def retrieve(self, query: str, budget_tokens: int) -> tuple[list[Chunk], list[Chunk]]:
        """Return (relevant_chunks, key_file_chunks) that fit in budget_tokens."""
        terms = query_terms(query)
        qlower = query.lower()
        all_chunks = [c for _, _, chunks in self._files.values() for c in chunks]
        if not all_chunks or budget_tokens <= 0:
            return [], []

        # document frequency over chunks
        hits: list[tuple[Chunk, dict[str, int]]] = []
        df: dict[str, int] = {t: 0 for t in terms}
        for c in all_chunks:
            counts = {}
            for t in terms:
                n = c.lower.count(t)
                if n:
                    counts[t] = n
                    df[t] += 1
            hits.append((c, counts))
        n_chunks = len(all_chunks)
        idf = {t: math.log(1 + n_chunks / (1 + df[t])) for t in terms}

        # files named in the question get a big boost
        named = {rel for rel in self._files if Path(rel).name.lower() in qlower or rel.lower() in qlower}

        scored: list[tuple[float, Chunk]] = []
        for c, counts in hits:
            score = sum((1 + math.log(n)) * idf[t] for t, n in counts.items())
            plower = c.path.lower()
            score += sum(2.0 * idf[t] for t in terms if t in plower)
            if c.path in named:
                score += 50
            if score > 0:
                scored.append((score, c))
        scored.sort(key=lambda s: -s[0])

        chosen, used = [], 0
        for _, c in scored:
            cost = c.tokens + 25
            if used + cost > budget_tokens:
                continue
            chosen.append(c)
            used += cost
        chosen.sort(key=lambda c: (c.path, c.start))

        # orientation files if there is room left
        key_chunks: list[Chunk] = []
        have = {c.path for c in chosen}
        for rel in KEY_FILES:
            entry = self._files.get(rel)
            if not entry or rel in have:
                continue
            first = entry[2][0] if entry[2] else None
            if first and used + first.tokens + 25 <= budget_tokens:
                key_chunks.append(first)
                used += first.tokens + 25
            if len(key_chunks) >= 2:
                break
        return chosen, key_chunks


def _fence(chunk: Chunk) -> str:
    ext = Path(chunk.path).suffix.lstrip(".")
    return f"### {chunk.path} (lines {chunk.start}-{chunk.end})\n```{ext}\n{chunk.text}\n```"


def project_block(project: Project, chosen: list[Chunk], key_chunks: list[Chunk],
                  tree: str | None = None) -> str:
    parts = [
        f"PROJECT CONTEXT: the user opened the folder '{project.name}'. Use the files below when "
        "they are relevant. Only part of the project is shown; if the answer depends on code you "
        "cannot see, say so and name the file you would need instead of guessing.",
        "File list:\n" + (tree if tree is not None else project.tree_text()),
    ]
    if chosen:
        parts.append("Relevant code:\n" + "\n\n".join(_fence(c) for c in chosen))
    if key_chunks:
        parts.append("Project overview files:\n" + "\n\n".join(_fence(c) for c in key_chunks))
    return "\n\n".join(parts)


def build_messages(system: str, history: list[tuple[str, str]], project: Project | None,
                   num_ctx: int) -> tuple[list[dict], dict]:
    """Assemble the request. Returns (messages, info) where info describes what was used."""
    query = history[-1][1] if history else ""
    reserve = min(ANSWER_RESERVE, num_ctx // 4)
    avail = max(num_ctx - reserve - est_tokens(system) - est_tokens(query), 256)

    chosen: list[Chunk] = []
    key_chunks: list[Chunk] = []
    block = ""
    if project and project.file_count:
        tree = project.tree_text(min(TREE_TOKEN_CAP, int(avail * 0.15)))
        tree_cost = est_tokens(tree) + 120
        code_budget = max(int(avail * PROJECT_SHARE) - tree_cost, 0)
        chosen, key_chunks = project.retrieve(query, code_budget)
        block = project_block(project, chosen, key_chunks, tree)

    system_full = (system.strip() + "\n\n" + block).strip() if block else system.strip()
    project_tokens = est_tokens(block) if block else 0

    # history: newest first until the budget is used up
    hist_budget = max(num_ctx - reserve - est_tokens(system) - project_tokens, est_tokens(query) + 64)
    kept: list[tuple[str, str]] = []
    used = 0
    for role, content in reversed(history):
        cost = est_tokens(content) + 8
        if kept and used + cost > hist_budget:
            break
        kept.append((role, content))
        used += cost
    kept.reverse()
    dropped = len(history) - len(kept)

    msgs: list[dict] = []
    if system_full:
        msgs.append({"role": "system", "content": system_full})
    msgs += [{"role": r, "content": c} for r, c in kept]

    files = sorted({c.path for c in chosen})
    info = {
        "files": files,
        "chunks": len(chosen),
        "project_tokens": project_tokens,
        "history_dropped": dropped,
        "total_tokens": est_tokens(system_full) + used,
        "num_ctx": num_ctx,
    }
    return msgs, info
