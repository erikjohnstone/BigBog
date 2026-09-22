# ruff: noqa: E501
"""Author the exhaust fan requirement sets (data), one per configuration.

``python -m bactalk.library_tier4.exhaust_fan.author`` rewrites the JSON files,
``--check`` verifies the committed files match. BACTalk standard sequence: the sources
are named designer practice, never Guideline 36.
"""

from __future__ import annotations

import sys
from pathlib import Path

from bactalk.protocol.authoring import cite, cond, out, point, tolerate_one_scan, write_requirements

DOC = "BACTalk standard sequence: exhaust fan"
PROOF_DELAY = 60.0
DAMPER_DELAY = 30.0


def build(with_damper: bool) -> dict:
    points = [
        point(
            "uEna",
            "Fan enable (schedule or request)",
            "boolean",
            "input",
            nominal=True,
            brick="brick:Enable_Command",
        ),
        point(
            "uFanSta",
            "Fan proof (current switch or status)",
            "boolean",
            "input",
            nominal=True,
            brick="brick:Run_Status",
        ),
    ]
    if with_damper:
        points.append(
            point(
                "uDamOpe",
                "Isolation damper open end switch",
                "boolean",
                "input",
                nominal=True,
                brick="brick:Damper_Position_Status",
            )
        )
    points += [
        point(
            "yFan",
            "Fan start command",
            "boolean",
            "output",
            nominal=False,
            brick="brick:Run_Enable_Command",
        ),
        point(
            "yFanAla", "Fan proof alarm", "boolean", "output", nominal=False, brick="brick:Alarm"
        ),
    ]
    if with_damper:
        points.append(
            point(
                "yDam",
                "Isolation damper open command",
                "boolean",
                "output",
                nominal=False,
                brick="brick:Damper_Command",
            )
        )

    requirements = []
    if not with_damper:
        requirements.append(
            {
                "id": "R-01",
                "title": "Fan runs when enabled",
                "kind": "control",
                "text": "The fan is commanded on whenever the enable input is true and off when it is false, with no delay.",
                "citation": cite(DOC, "§1 fan control", fidelity="designer"),
                "conditions": [cond("uEna", "eq", True)],
                "outcomes": [out("yFan", "eq", True)],
                "otherwise": [out("yFan", "eq", False)],
            }
        )
    else:
        requirements += [
            {
                "id": "R-01",
                "title": "Fan runs when enabled and the damper proves open",
                "kind": "control",
                "text": "With the enable input true, the fan is commanded on once the isolation damper's open end switch proves; it is commanded off when the enable input is false.",
                "citation": cite(
                    DOC, "§1 fan control", "isolation damper interlock", fidelity="designer"
                ),
                "conditions": [cond("uEna", "eq", True), cond("uDamOpe", "eq", True)],
                "outcomes": [out("yFan", "eq", True)],
                "otherwise": [out("yFan", "eq", False)],
            },
            {
                "id": "R-04",
                "title": "Fan starts after the damper timeout",
                "kind": "control",
                "assumes": ["R-01"],
                "text": "If the damper end switch has not proved open 30 seconds after the enable input became true, the fan starts anyway (a failed end switch must not keep the space unventilated).",
                "citation": cite(DOC, "§1 fan control", "end switch timeout", fidelity="designer"),
                "conditions": [cond("uDamOpe", "eq", False)],
                "timing": {"delay_seconds": DAMPER_DELAY},
                "outcomes": [out("yFan", "eq", True)],
                "before": [out("yFan", "eq", False)],
                "otherwise": [out("yFan", "eq", True)],
                "parameters": {"damperTimeout_s": DAMPER_DELAY},
            },
            {
                "id": "R-05",
                "title": "Damper opens when enabled",
                "kind": "control",
                "text": "The isolation damper is commanded open whenever the enable input is true and closed when it is false.",
                "citation": cite(DOC, "§2 isolation damper", fidelity="designer"),
                "conditions": [cond("uEna", "eq", True)],
                "outcomes": [out("yDam", "eq", True)],
                "otherwise": [out("yDam", "eq", False)],
            },
        ]
    requirements += [
        {
            "id": "R-02",
            "title": "Proof-of-flow alarm",
            "kind": "alarm",
            "assumes": ["R-01"],
            "text": "When the fan is commanded on and its proof input stays false for 60 seconds, the proof alarm is raised; it clears as soon as the fan proves or the command is removed.",
            "citation": cite(DOC, "§3 alarms", fidelity="designer"),
            "conditions": [cond("uFanSta", "eq", False)],
            "timing": {"delay_seconds": PROOF_DELAY},
            "outcomes": [out("yFanAla", "eq", True)],
            "otherwise": [out("yFanAla", "eq", False)],
            "parameters": {"proofDelay_s": PROOF_DELAY},
        },
        {
            "id": "R-03",
            "title": "Disable stops everything",
            "kind": "safety",
            "text": "When the enable input is false the fan command"
            + (", the damper command" if with_damper else "")
            + " and the proof alarm are all off in the same scan.",
            "citation": cite(DOC, "§1 fan control", fidelity="designer"),
            "conditions": [cond("uEna", "eq", False)],
            "outcomes": [out("yFan", "eq", False), out("yFanAla", "eq", False)]
            + ([out("yDam", "eq", False)] if with_damper else []),
            "otherwise": [out("yFan", "eq", True)],
        },
    ]
    requirements.sort(key=lambda item: item["id"])
    tolerate_one_scan(requirements)
    invariants = [
        {
            "id": "I-01",
            "text": "Nothing runs while disabled",
            "citation": cite(DOC, "§1 fan control", fidelity="designer"),
            "when": [cond("uEna", "eq", False)],
            "then": [out("yFan", "eq", False)]
            + ([out("yDam", "eq", False)] if with_damper else []),
        },
        {
            "id": "I-02",
            "text": "The proof alarm implies a fan command",
            "citation": cite(DOC, "§3 alarms", fidelity="designer"),
            "when": [cond("yFanAla", "eq", True)],
            "then": [out("yFan", "eq", True)],
        },
    ]
    return {
        "schema": "bactalk.protocol-requirements/v1",
        "sequence_id": "exhaust-fan-damper" if with_damper else "exhaust-fan",
        "title": "Exhaust fan"
        + (" with isolation damper" if with_damper else "")
        + " (BACTalk standard sequence)",
        "version": "1.0 (N10 draft, awaiting Gate G-ENG)",
        "tier": 4,
        "equipment_brick_class": "brick:Exhaust_Fan",
        "sources": [{"document": DOC, "edition": "designer practice; not a Guideline 36 sequence"}],
        "step_seconds": 5.0,
        "points": points,
        "requirements": requirements,
        "invariants": invariants,
        "notes": "BACTalk standard sequence (engineer-approved requirements), never labelled G36. Configuration option isolation_damper="
        + str(with_damper).lower()
        + ".",
    }


DOCUMENTS = {"requirements.json": build(False), "requirements-damper.json": build(True)}


def main(argv: list[str]) -> int:
    return write_requirements(DOCUMENTS, Path(__file__).parent, argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
