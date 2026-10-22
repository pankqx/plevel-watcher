#!/usr/bin/env python3
"""Build dist/plevel-watcher-<version>.vsix from vscode-extension/ using only the standard library.

A .vsix is a zip file: [Content_Types].xml + extension.vsixmanifest + extension/<files>.
Installing it with `code --install-extension` registers the extension properly, which a plain
symlink into ~/.vscode/extensions does not (recent VS Code ignores unregistered folders).
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "vscode-extension"
INCLUDE = ["package.json", "extension.js", "core.js", "README.md"]

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension=".json" ContentType="application/json"/>'
    '<Default Extension=".js" ContentType="application/javascript"/>'
    '<Default Extension=".md" ContentType="text/markdown"/>'
    '<Default Extension=".vsixmanifest" ContentType="text/xml"/>'
    "</Types>"
)


def manifest(pkg: dict) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" '
        'xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">'
        "<Metadata>"
        f'<Identity Language="en-US" Id="{escape(pkg["name"])}" Version="{escape(pkg["version"])}" '
        f'Publisher="{escape(pkg["publisher"])}"/>'
        f'<DisplayName>{escape(pkg.get("displayName", pkg["name"]))}</DisplayName>'
        f'<Description xml:space="preserve">{escape(pkg.get("description", ""))}</Description>'
        "<Tags></Tags>"
        f'<Categories>{escape(",".join(pkg.get("categories", ["Other"])))}</Categories>'
        "<GalleryFlags>Public</GalleryFlags>"
        "<Properties>"
        f'<Property Id="Microsoft.VisualStudio.Code.Engine" Value="{escape(pkg["engines"]["vscode"])}"/>'
        '<Property Id="Microsoft.VisualStudio.Code.ExtensionDependencies" Value=""/>'
        '<Property Id="Microsoft.VisualStudio.Code.ExtensionPack" Value=""/>'
        '<Property Id="Microsoft.VisualStudio.Code.ExtensionKind" Value="workspace"/>'
        '<Property Id="Microsoft.VisualStudio.Code.LocalizedLanguages" Value=""/>'
        "</Properties>"
        "</Metadata>"
        '<Installation><InstallationTarget Id="Microsoft.VisualStudio.Code"/></Installation>'
        "<Dependencies/>"
        "<Assets>"
        '<Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true"/>'
        '<Asset Type="Microsoft.VisualStudio.Services.Content.Details" Path="extension/README.md" Addressable="true"/>'
        "</Assets>"
        "</PackageManifest>"
    )


def build(out_dir: Path | None = None) -> Path:
    pkg = json.loads((SRC / "package.json").read_text(encoding="utf-8"))
    out_dir = out_dir or ROOT / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f'{pkg["name"]}-{pkg["version"]}.vsix'
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("extension.vsixmanifest", manifest(pkg))
        for name in INCLUDE:
            f = SRC / name
            if f.exists():
                z.write(f, f"extension/{name}")
    return out


if __name__ == "__main__":
    path = build(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
    print(path)
