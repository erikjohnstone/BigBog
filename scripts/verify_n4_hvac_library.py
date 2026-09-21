from __future__ import annotations

import json
import subprocess
from pathlib import Path

from bactalk.integrations.niagara_program_library import NiagaraProgramLibrary
from bactalk.stack_lock import locked_revision

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / ".vendor/n4-hvac-optimization-blocks"
EXPECTED_REVISION = locked_revision("n4-hvac-optimization-blocks")


def main() -> int:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=LIBRARY,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if revision != EXPECTED_REVISION:
        raise RuntimeError("Niagara ProgramObject library does not match the pinned revision")
    license_text = (LIBRARY / "LICENSE").read_text(encoding="utf-8")
    if not license_text.startswith("MIT License"):
        raise RuntimeError("Niagara ProgramObject library MIT license is missing")

    catalog = NiagaraProgramLibrary(LIBRARY).catalog()
    if catalog["count"] != 20 or catalog["program_object_count"] != 36:
        raise RuntimeError(
            "expected 20 Niagara archives containing 36 ProgramObjects, found "
            f"{catalog['count']} archives and {catalog['program_object_count']} objects"
        )
    if not any(item["id"] == "GL36_VAV_AHU_SYSTEM" for item in catalog["templates"]):
        raise RuntimeError("Guideline 36 VAV/AHU ProgramObject template is missing")
    if any(item["runtime_qualified"] for item in catalog["templates"]):
        raise RuntimeError("source inspection must not imply licensed runtime qualification")
    if catalog["declared_slot_count"] != 498:
        raise RuntimeError("Niagara ProgramObject slot inventory changed")
    if catalog["control_template_candidate_count"] != 31:
        raise RuntimeError("Niagara control-template candidate inventory changed")
    if catalog["source_capability_blocked_count"] != 5:
        raise RuntimeError("Niagara source capability risk inventory changed")
    web_weather = next(item for item in catalog["templates"] if item["id"] == "Web_Weather")
    if web_weather["programs"][0]["eligible_for_control_template_lane"]:
        raise RuntimeError("network-capable ProgramObject entered the control-template lane")
    g36 = next(item for item in catalog["templates"] if item["id"] == "GL36_VAV_AHU_SYSTEM")
    if not all(program["source_slot_contract_complete"] for program in g36["programs"]):
        raise RuntimeError("G36 ProgramObject source references undeclared dynamic slots")

    print(
        json.dumps(
            {
                "passed": True,
                "revision": revision,
                "archives": catalog["count"],
                "program_objects": catalog["program_object_count"],
                "declared_slots": catalog["declared_slot_count"],
                "control_template_candidates": catalog["control_template_candidate_count"],
                "source_capability_blocked": catalog["source_capability_blocked_count"],
                "checks": [
                    "mit-license",
                    "archive-integrity",
                    "program-source-and-bytecode-presence",
                    "dependency-inventory",
                    "typed-slot-interface-inventory",
                    "source-accessor-slot-closure",
                    "external-capability-exclusion",
                    "runtime-qualification-remains-false",
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
