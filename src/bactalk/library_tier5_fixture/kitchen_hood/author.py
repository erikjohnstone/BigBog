# ruff: noqa: E501
"""Author the fixture custom sequence "kitchen hood exhaust and makeup air interlock"
as a contractor's specification section would state it (Tier 5, job-specific).

``python -m bactalk.library_tier5_fixture.kitchen_hood.author`` rewrites the JSON,
``--check`` verifies it.
"""

from __future__ import annotations

import sys
from pathlib import Path

from bactalk.protocol.authoring import cite, cond, out, point, tolerate_one_scan, write_requirements

DOC = "Project specification 23 09 93, kitchen hood exhaust interlock (contractor upload)"
PROOF_DELAY = 45.0


def build() -> dict:
    points = [
        point(
            "uHooSw",
            "Hood exhaust switch (kitchen)",
            "boolean",
            "input",
            nominal=True,
            brick="brick:Enable_Command",
        ),
        point(
            "uAhuFan",
            "Building AHU supply fan status (bound from AHU_1.y1SupFan)",
            "boolean",
            "input",
            nominal=True,
            brick="brick:Run_Status",
        ),
        point(
            "uMakFanSta",
            "Makeup air fan proof",
            "boolean",
            "input",
            nominal=True,
            brick="brick:Run_Status",
        ),
        point(
            "yHooFan",
            "Hood exhaust fan start",
            "boolean",
            "output",
            nominal=False,
            brick="brick:Run_Enable_Command",
        ),
        point(
            "yMakFan",
            "Makeup air fan start",
            "boolean",
            "output",
            nominal=False,
            brick="brick:Run_Enable_Command",
        ),
        point(
            "yMakDam",
            "Makeup air damper open",
            "boolean",
            "output",
            nominal=False,
            brick="brick:Damper_Command",
        ),
        point(
            "yMakAla",
            "Makeup air fan failure alarm",
            "boolean",
            "output",
            nominal=False,
            brick="brick:Alarm",
        ),
    ]
    requirements = [
        {
            "id": "R-01",
            "title": "Hood exhaust fan follows the hood switch",
            "kind": "control",
            "text": "The hood exhaust fan shall start when the kitchen hood switch is on and stop when it is off.",
            "citation": cite(DOC, "3.4.A", "paragraph 1", fidelity="verbatim"),
            "conditions": [cond("uHooSw", "eq", True)],
            "outcomes": [out("yHooFan", "eq", True)],
            "otherwise": [out("yHooFan", "eq", False)],
        },
        {
            "id": "R-02",
            "title": "Makeup air runs with the hood while the AHU runs",
            "kind": "control",
            "assumes": ["R-01"],
            "text": "The makeup air fan shall run whenever the hood exhaust fan is running and the building air handling unit supply fan is in operation; the makeup air damper shall open with the makeup air fan.",
            "citation": cite(DOC, "3.4.B", "paragraph 2", fidelity="verbatim"),
            "conditions": [cond("uAhuFan", "eq", True)],
            "outcomes": [out("yMakFan", "eq", True), out("yMakDam", "eq", True)],
            "otherwise": [out("yMakFan", "eq", False), out("yMakDam", "eq", False)],
        },
        {
            "id": "R-03",
            "title": "Makeup air fan failure alarm",
            "kind": "alarm",
            "assumes": ["R-02"],
            "text": "If the makeup air fan is commanded on and its proof is not made within 45 seconds, a makeup air failure alarm shall be generated; the alarm shall clear when proof is made or the command is removed.",
            "citation": cite(DOC, "3.4.C", "paragraph 3", fidelity="verbatim"),
            "conditions": [cond("uMakFanSta", "eq", False)],
            "timing": {"delay_seconds": PROOF_DELAY},
            "outcomes": [out("yMakAla", "eq", True)],
            "otherwise": [out("yMakAla", "eq", False)],
            "parameters": {"proofDelay_s": PROOF_DELAY},
        },
        {
            "id": "R-04",
            "title": "Hood off stops the makeup air",
            "kind": "safety",
            "text": "When the hood switch is off, the hood exhaust fan, the makeup air fan and damper, and the failure alarm shall be off.",
            "citation": cite(DOC, "3.4.A", "paragraph 1", fidelity="paraphrase"),
            "conditions": [cond("uHooSw", "eq", False)],
            "outcomes": [
                out("yHooFan", "eq", False),
                out("yMakFan", "eq", False),
                out("yMakDam", "eq", False),
                out("yMakAla", "eq", False),
            ],
            "otherwise": [out("yHooFan", "eq", True)],
        },
    ]
    tolerate_one_scan(requirements)
    invariants = [
        {
            "id": "I-01",
            "text": "Makeup air never runs without the hood",
            "citation": cite(DOC, "3.4.B", fidelity="paraphrase"),
            "when": [cond("uHooSw", "eq", False)],
            "then": [
                out("yMakFan", "eq", False),
                out("yMakDam", "eq", False),
                out("yHooFan", "eq", False),
            ],
        },
        {
            "id": "I-02",
            "text": "The damper opens with the makeup fan",
            "citation": cite(DOC, "3.4.B", fidelity="paraphrase"),
            "when": [cond("yMakFan", "eq", True)],
            "then": [out("yMakDam", "eq", True)],
        },
    ]
    return {
        "schema": "bactalk.protocol-requirements/v1",
        "sequence_id": "custom-kitchen-hood-interlock",
        "title": "Kitchen hood exhaust and makeup air interlock (custom, job-specific)",
        "version": "1.0 (N11 fixture, contractor approval pending)",
        "tier": 5,
        "equipment_brick_class": "brick:Exhaust_Fan",
        "sources": [
            {
                "document": DOC,
                "edition": "fixture text in the style of a specification section; the contractor approves it",
            }
        ],
        "step_seconds": 5.0,
        "points": points,
        "requirements": requirements,
        "invariants": invariants,
        "notes": "Custom, job-specific sequence (Tier 5). Composed with the Tier 1 AHU through the project signal binding AHU_1.y1SupFan -> HOOD_1.uAhuFan.",
    }


DOCUMENTS = {"requirements.json": build()}


def main(argv: list[str]) -> int:
    return write_requirements(DOCUMENTS, Path(__file__).parent, argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
