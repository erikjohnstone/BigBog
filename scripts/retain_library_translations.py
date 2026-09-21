"""Regenerate the retained LBNL translations under ``src/bactalk/library_demo/``.

Needs the vendored toolchain (``make bootstrap-full``): modelica-json, the Open
Control Engine and the pinned Modelica Buildings checkout. The envelope is the
one ``bactalk.library_demo`` reads and ``tests/test_lbnl_demo.py`` checks
against a fresh translation on the integration tier.

Usage::

    PYTHONPATH=src .venv/bin/python scripts/retain_library_translations.py [--check]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bactalk.integrations.g36_library import G36Library
from bactalk.library_demo import RETAINED, retained_translation
from bactalk.stack_lock import stack_lock_path

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "src" / "bactalk" / "library_demo"
SCHEMA = "bactalk.retained-library-translation/v1"
NOTE = (
    "Retained so a base install can build the demo without the vendored translation "
    "toolchain. tests/test_lbnl_demo.py re-translates on the integration tier and fails "
    "if this drifts."
)


def _lock_component(name: str) -> dict:
    lock = json.loads(stack_lock_path().read_text(encoding="utf-8"))
    components = lock.get("components", lock)
    entry = components[name]
    return {
        "repository": entry["repository"],
        "revision": entry["revision"],
        "tag": entry.get("release") or entry.get("tag"),
    }


def retain(controller_id: str) -> dict:
    previous = retained_translation(controller_id)
    library = G36Library()
    profile = previous["execution_profile"]
    parameters = dict(previous["parameters"])
    fresh = library.translate(controller_id, execution_profile=profile, parameters=parameters)
    template = library.job_template(controller_id, parameters=parameters, execution_profile=profile)
    lock = _lock_component("modelica-buildings")
    assessment = template["target_assessment"]
    return {
        "schema": SCHEMA,
        "controller_id": controller_id,
        "execution_profile": profile,
        "interface": fresh["interface"],
        "library": "g36",
        "niagara_target": {
            "complete": bool(assessment["complete"]),
            "generated_program_count": assessment.get("generated_program_count"),
        },
        "note": NOTE,
        "parameters": parameters,
        "points": template["points"],
        "source": {
            "relative_path": fresh["controller"]["relative_path"],
            "repository": lock["repository"],
            "revision": lock["revision"],
            "source_sha256": fresh["controller"]["source_sha256"],
            "tag": lock["tag"],
        },
        "translator": {
            "cxf_source_sha256": fresh["lowering"]["source_sha256"],
            "lowering_schema": fresh["lowering"]["schema"],
            "name": str(fresh["translator"]),
            "runtime": str(fresh["runtime"]),
        },
        "typed_ir": fresh["typed_ir"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="fail when a retained file is stale")
    args = parser.parse_args()
    stale = []
    for controller_id, filename in RETAINED.items():
        rendered = json.dumps(retain(controller_id), indent=1, sort_keys=True) + "\n"
        path = DESTINATION / filename
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if args.check:
            if current != rendered:
                stale.append(filename)
            continue
        path.write_text(rendered, encoding="utf-8")
        print(f"wrote {path}")
    if stale:
        print("stale retained translations: " + ", ".join(stale))
        return 1
    if args.check:
        print("retained translations are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
