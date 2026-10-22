"""python tests/test_cli.py   (no Qt needed)"""

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fake_ollama  # noqa: E402
from plevel_watcher import agent  # noqa: E402
from plevel_watcher.cli import Watcher  # noqa: E402

server, port = fake_ollama.start(delay=0.001)
HOST = f"http://127.0.0.1:{port}"


def make(answer="y"):
    root = Path(tempfile.mkdtemp())
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / "a.py").write_text("x = 1\n")
    log = []
    w = Watcher(root, "m", HOST, False, False, 0.2, 4096, ask=lambda _p: answer, out=log.append)
    w.scan()   # baseline
    return root, w, log


def test_apply_on_yes():
    root, w, log = make("y")
    (root / "a.py").write_text("x = 1\n# plevel: write add\ny = 2\n")
    assert w.run_once() == 1
    s = (root / "a.py").read_text()
    assert "def add(a, b):" in s and "plevel" not in s and s.startswith("x = 1\n") and s.endswith("y = 2\n"), s
    assert any("+def add" in str(l) for l in log)
    assert w.run_once() == 0   # nothing left to do, no loop


def test_no_changes_on_no():
    root, w, _ = make("n")
    before = "x = 1\n# plevel: write add\n"
    (root / "a.py").write_text(before)
    assert w.run_once() == 0
    assert (root / "a.py").read_text() == before
    assert w.run_once() == 0   # declined comment is not asked again


def test_lock_blocks_watcher():
    root, w, _ = make("y")
    (root / ".plevel").mkdir()
    (root / agent.LOCK_NAME).write_text("busy")
    (root / "a.py").write_text("# plevel: write add\n")
    assert w.run_once() == 0


def test_other_languages_and_new_files():
    root, w, _ = make("y")
    (root / "b.js").write_text("// plevel: add function\n")
    assert w.run_once() == 1
    assert "def add" in (root / "b.js").read_text()   # fake model always answers with python; shape is what we test


def test_model_down():
    root, w, log = make("y")
    w.host = "http://127.0.0.1:1"
    (root / "a.py").write_text("# plevel: write add\n")
    assert w.run_once() == 0
    assert any("could not get an answer" in str(l) for l in log)
    assert (root / "a.py").read_text() == "# plevel: write add\n"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    server.shutdown()
    print("ALL OK")
