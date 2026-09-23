"""Translate BACTalk's CDL substitutes with the pinned modelica-json (decision 016).

Each ``BACTalk.CdlSubstitutes.<Name>`` in
``src/bactalk/integrations/cdl_substitutes/BACTalk/CdlSubstitutes/<Name>.mo`` is a CDL
block diagram with the interface of ``Buildings.Templates.Plants.Controls.Utilities.<Name>``,
which LBNL writes as equations. The translated CXF is renamed to the class it replaces
and committed next to the source as ``<Name>.jsonld``; ``manifest.json`` records both
digests. ``--check`` re-translates and fails on any difference.

Usage::

    PYTHONPATH=src .venv/bin/python scripts/build_cdl_substitutes.py [--check]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "bactalk" / "integrations" / "cdl_substitutes"
SOURCES = PACKAGE / "BACTalk" / "CdlSubstitutes"
MODELICA_JSON = ROOT / ".vendor" / "modelica-json"
BUILDINGS = ROOT / ".vendor" / "modelica-buildings" / "Buildings"
SOURCE_PREFIX = "BACTalk.CdlSubstitutes."
TARGET_PREFIX = "Buildings.Templates.Plants.Controls.Utilities."


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def translate(name: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="bactalk-substitutes-") as directory:
        library = Path(directory) / "lib"
        library.mkdir()
        (library / "Buildings").symlink_to(BUILDINGS, target_is_directory=True)
        (library / "BACTalk").symlink_to(SOURCES.parent, target_is_directory=True)
        output = Path(directory) / "out"
        environment = {**os.environ, "MODELICAPATH": str(library)}
        subprocess.run(
            [
                "node",
                str(MODELICA_JSON / "app.js"),
                "-f",
                str(library / "BACTalk" / "CdlSubstitutes" / f"{name}.mo"),
                "-o",
                "cxf",
                "-m",
                "cdl",
                "-d",
                str(output),
                "-p",
                "-l",
                "error",
            ],
            cwd=MODELICA_JSON,
            check=True,
            capture_output=True,
            text=True,
            env=environment,
            timeout=300,
        )
        produced = output / "cxf" / "BACTalk" / "CdlSubstitutes" / f"{name}.jsonld"
        text = produced.read_text(encoding="utf-8")
    # The substitute takes the place of LBNL's class: every identifier it mints moves
    # into that class's namespace, so a parent's reference resolves to it unchanged.
    renamed = text.replace(SOURCE_PREFIX + name, TARGET_PREFIX + name)
    if SOURCE_PREFIX in renamed:
        raise RuntimeError(f"{name} still references {SOURCE_PREFIX}")
    return json.loads(renamed)


def render(document: dict) -> str:
    return json.dumps(document, indent=1, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    names = sorted(path.stem for path in SOURCES.glob("*.mo") if path.stem != "package")
    manifest: dict[str, dict[str, str]] = {}
    stale: list[str] = []
    for name in names:
        rendered = render(translate(name))
        target = PACKAGE / f"{name}.jsonld"
        manifest[name] = {
            "replaces": TARGET_PREFIX + name,
            "source": f"BACTalk/CdlSubstitutes/{name}.mo",
            "source_sha256": _digest((SOURCES / f"{name}.mo").read_bytes()),
            "cxf_sha256": _digest(rendered.encode()),
        }
        if args.check:
            if not target.is_file() or target.read_text(encoding="utf-8") != rendered:
                stale.append(name)
        else:
            target.write_text(rendered, encoding="utf-8")
        print(f"{'checked' if args.check else 'wrote'} {name}", flush=True)
    manifest_text = json.dumps(manifest, indent=1, sort_keys=True) + "\n"
    manifest_path = PACKAGE / "manifest.json"
    if args.check:
        if (
            not manifest_path.is_file()
            or manifest_path.read_text(encoding="utf-8") != manifest_text
        ):
            stale.append("manifest.json")
        if stale:
            print("stale: " + ", ".join(stale), file=sys.stderr)
            return 1
        return 0
    manifest_path.write_text(manifest_text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
