"""python tests/test_agent.py   (no Qt needed)"""

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fake_ollama  # noqa: E402
from plevel_watcher import agent  # noqa: E402

V = json.loads((Path(__file__).parent / "vectors" / "comments.json").read_text())


def test_vectors():
    for m in V["matches"]:
        cmds = agent.find_commands(m["line"])
        assert len(cmds) == 1, m
        assert cmds[0].indent == m["indent"] and cmds[0].task == m["task"], (m, cmds[0])
    for line in V["non_matches"]:
        assert not agent.find_commands(line), line
    for e in V["extract"]:
        assert agent.extract_code(e["reply"]) == e["code"], e
    for a in V["apply"]:
        cmd = agent.find_commands(a["text"])[0]
        assert cmd.line == a["line"]
        assert agent.apply_code(a["text"], cmd, a["code"], a["keep"]) == a["out"], a


def test_stale_line_refused():
    text = "x = 1\n# plevel: add y\n"
    cmd = agent.find_commands(text)[0]
    try:
        agent.apply_code("x = 1\n# plevel: something else\n", cmd, "y = 2")
    except ValueError:
        return
    raise AssertionError("should refuse when the comment changed")


def test_window_and_prompt():
    big = "\n".join(f"line{i}" for i in range(500)) + "\n# plevel: do it\n" + "\n".join(f"tail{i}" for i in range(100))
    cmd = agent.find_commands(big)[0]
    w = agent.file_window(big, cmd.line)
    assert "INSTRUCTION IS HERE" in w and "line0" in w and "line499" in w and "line100\n" not in w
    msgs = agent.build_messages(cmd, "app.py", big)
    assert msgs[0]["role"] == "system" and "Python" in msgs[1]["content"] and "do it" in msgs[1]["content"]
    assert len(msgs[1]["content"]) < 12000


def test_ollama_roundtrip():
    server, port = fake_ollama.start(delay=0.001)
    host = f"http://127.0.0.1:{port}"
    text = "import os\n# plevel: write add\n"
    cmd = agent.find_commands(text)[0]
    code = agent.generate(cmd, "t.py", text, host=host)
    assert "def add(a, b):" in code and "```" not in code
    sent = fake_ollama.Handler.last_chat
    assert sent["options"]["temperature"] == 0.2 and sent["messages"][0]["role"] == "system"
    out = agent.apply_code(text, cmd, code)
    assert out.startswith("import os\ndef add") and "plevel" not in out
    d = agent.unified_diff(text, out, "t.py")
    assert "+def add(a, b):" in d and "-# plevel: write add" in d
    server.shutdown()


def test_project_context():
    from plevel_watcher.context import Project
    root = Path(tempfile.mkdtemp())
    (root / "helpers.py").write_text("def slugify_title(t):\n    return t.lower()\n")
    (root / "app.py").write_text("# plevel: use slugify_title\n")
    p = Project(root)
    p.refresh()
    cmd = agent.find_commands((root / "app.py").read_text())[0]
    msgs = agent.build_messages(cmd, str(root / "app.py"), (root / "app.py").read_text(), p)
    assert "slugify_title" in msgs[0]["content"] and "helpers.py" in msgs[0]["content"]


def test_lock():
    root = Path(tempfile.mkdtemp())
    assert not agent.lock_is_fresh(root)
    (root / ".plevel").mkdir()
    (root / agent.LOCK_NAME).write_text("x")
    assert agent.lock_is_fresh(root)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("ALL OK")
