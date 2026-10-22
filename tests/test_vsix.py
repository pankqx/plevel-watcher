"""python3 tests/test_vsix.py"""
import json
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.dom import minidom

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import make_vsix  # noqa: E402


def test_vsix():
    out = make_vsix.build(Path(tempfile.mkdtemp()))
    assert out.name == "plevel-watcher-0.1.0.vsix", out.name
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        assert {"[Content_Types].xml", "extension.vsixmanifest", "extension/package.json",
                "extension/extension.js", "extension/core.js"} <= names, names
        for x in ("[Content_Types].xml", "extension.vsixmanifest"):
            minidom.parseString(z.read(x))            # well-formed XML
        pkg = json.loads(z.read("extension/package.json"))
        man = z.read("extension.vsixmanifest").decode()
        assert pkg["name"] in man and pkg["publisher"] in man and pkg["version"] in man
        assert pkg["main"] == "./extension.js" and "extension/extension.js" in names


if __name__ == "__main__":
    test_vsix()
    print("ok test_vsix\nALL OK")
