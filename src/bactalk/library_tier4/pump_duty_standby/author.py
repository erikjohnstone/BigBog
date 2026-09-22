# ruff: noqa: E501
"""Author the duty/standby pump pair requirement set (data).

``python -m bactalk.library_tier4.pump_duty_standby.author`` rewrites the JSON,
``--check`` verifies it. BACTalk standard sequence (designer practice), never G36.
"""

from __future__ import annotations

import sys
from pathlib import Path

from bactalk.protocol.authoring import cite, cond, out, point, tolerate_one_scan, write_requirements

DOC = "BACTalk standard sequence: duty/standby pump pair"
PROOF_DELAY = 30.0


def build() -> dict:
    points = [
        point(
            "uEna", "System enable", "boolean", "input", nominal=True, brick="brick:Enable_Command"
        ),
        point("uLead2", "Pump 2 selected as lead", "boolean", "input", nominal=False),
        point(
            "uPum1Ava",
            "Pump 1 available (not in hand/off or faulted)",
            "boolean",
            "input",
            nominal=True,
            brick="brick:Availability_Status",
        ),
        point(
            "uPum2Ava",
            "Pump 2 available",
            "boolean",
            "input",
            nominal=True,
            brick="brick:Availability_Status",
        ),
        point(
            "uPum1Sta", "Pump 1 proof", "boolean", "input", nominal=True, brick="brick:Run_Status"
        ),
        point(
            "uPum2Sta", "Pump 2 proof", "boolean", "input", nominal=True, brick="brick:Run_Status"
        ),
        point(
            "yPum1",
            "Pump 1 start command",
            "boolean",
            "output",
            nominal=False,
            brick="brick:Run_Enable_Command",
        ),
        point(
            "yPum2",
            "Pump 2 start command",
            "boolean",
            "output",
            nominal=False,
            brick="brick:Run_Enable_Command",
        ),
        point(
            "yNoPumAla",
            "No pump available alarm",
            "boolean",
            "output",
            nominal=False,
            brick="brick:Alarm",
        ),
        point(
            "yPumFaiAla",
            "Pump failure alarm",
            "boolean",
            "output",
            nominal=False,
            brick="brick:Alarm",
        ),
    ]
    requirements = [
        {
            "id": "R-01",
            "title": "Lead pump runs when enabled",
            "kind": "control",
            "text": "With the system enabled, the selected lead pump (pump 1 unless pump 2 is selected) is commanded on when it is available; the standby pump stays off.",
            "citation": cite(DOC, "§1 duty selection", fidelity="designer"),
            "conditions": [
                cond("uEna", "eq", True),
                cond("uLead2", "eq", False),
                cond("uPum1Ava", "eq", True),
            ],
            "outcomes": [out("yPum1", "eq", True)],
            "otherwise": [out("yPum1", "eq", False)],
        },
        {
            "id": "R-02",
            "title": "Pump 2 leads when selected",
            "kind": "control",
            "text": "With the system enabled and pump 2 selected as lead and available, pump 2 is commanded on and pump 1 stays off.",
            "citation": cite(DOC, "§1 duty selection", fidelity="designer"),
            "conditions": [
                cond("uEna", "eq", True),
                cond("uLead2", "eq", True),
                cond("uPum2Ava", "eq", True),
            ],
            "outcomes": [out("yPum2", "eq", True), out("yPum1", "eq", False)],
            "otherwise": [out("yPum2", "eq", False)],
        },
        {
            "id": "R-03",
            "title": "Standby takes over an unavailable lead",
            "kind": "control",
            "assumes": ["R-01"],
            "text": "With pump 1 leading, when pump 1 becomes unavailable the standby pump 2 is commanded on immediately and pump 1 is commanded off.",
            "citation": cite(DOC, "§2 failover", fidelity="designer"),
            "conditions": [cond("uPum1Ava", "eq", False)],
            "outcomes": [out("yPum2", "eq", True), out("yPum1", "eq", False)],
            "otherwise": [out("yPum1", "eq", True), out("yPum2", "eq", False)],
        },
        {
            "id": "R-04",
            "title": "No pump available alarm",
            "kind": "alarm",
            "text": "When the system is enabled and neither pump is available, both pumps are commanded off and the no-pump-available alarm is raised; it clears when a pump becomes available or the system is disabled.",
            "citation": cite(DOC, "§3 alarms", fidelity="designer"),
            "conditions": [
                cond("uEna", "eq", True),
                cond("uPum1Ava", "eq", False),
                cond("uPum2Ava", "eq", False),
            ],
            "outcomes": [
                out("yNoPumAla", "eq", True),
                out("yPum1", "eq", False),
                out("yPum2", "eq", False),
            ],
            "otherwise": [out("yNoPumAla", "eq", False)],
        },
        {
            "id": "R-05",
            "title": "Pump failure alarm",
            "kind": "alarm",
            "assumes": ["R-01"],
            "text": "When a commanded pump is not proven for 30 seconds the pump failure alarm is raised; it clears when the pump proves or its command is removed.",
            "citation": cite(DOC, "§3 alarms", fidelity="designer"),
            "conditions": [cond("uPum1Sta", "eq", False)],
            "timing": {"delay_seconds": PROOF_DELAY},
            "outcomes": [out("yPumFaiAla", "eq", True)],
            "otherwise": [out("yPumFaiAla", "eq", False)],
            "parameters": {"proofDelay_s": PROOF_DELAY},
        },
        {
            "id": "R-07",
            "title": "Standby pump failure alarm",
            "kind": "alarm",
            "assumes": ["R-02"],
            "text": "With pump 2 leading, when pump 2 is commanded and not proven for 30 seconds the pump failure alarm is raised; it clears when the pump proves or its command is removed.",
            "citation": cite(DOC, "§3 alarms", fidelity="designer"),
            "conditions": [cond("uPum2Sta", "eq", False)],
            "timing": {"delay_seconds": PROOF_DELAY},
            "outcomes": [out("yPumFaiAla", "eq", True)],
            "otherwise": [out("yPumFaiAla", "eq", False)],
        },
        {
            "id": "R-06",
            "title": "Disable stops both pumps",
            "kind": "safety",
            "text": "When the system is disabled both pumps and both alarms are off in the same scan.",
            "citation": cite(DOC, "§1 duty selection", fidelity="designer"),
            "conditions": [cond("uEna", "eq", False)],
            "outcomes": [
                out("yPum1", "eq", False),
                out("yPum2", "eq", False),
                out("yNoPumAla", "eq", False),
                out("yPumFaiAla", "eq", False),
            ],
            "otherwise": [out("yPum1", "eq", True)],
        },
    ]
    requirements.sort(key=lambda item: item["id"])
    tolerate_one_scan(requirements)
    invariants = [
        {
            "id": "I-01",
            "text": "Nothing runs while disabled",
            "citation": cite(DOC, "§1 duty selection", fidelity="designer"),
            "when": [cond("uEna", "eq", False)],
            "then": [
                out("yPum1", "eq", False),
                out("yPum2", "eq", False),
                out("yNoPumAla", "eq", False),
            ],
        },
        {
            "id": "I-02",
            "text": "An unavailable pump is never commanded",
            "citation": cite(DOC, "§2 failover", fidelity="designer"),
            "when": [cond("uPum1Ava", "eq", False)],
            "then": [out("yPum1", "eq", False)],
        },
        {
            "id": "I-03",
            "text": "An unavailable pump is never commanded",
            "citation": cite(DOC, "§2 failover", fidelity="designer"),
            "when": [cond("uPum2Ava", "eq", False)],
            "then": [out("yPum2", "eq", False)],
        },
        {
            "id": "I-04",
            "text": "The no-pump alarm implies both pumps off",
            "citation": cite(DOC, "§3 alarms", fidelity="designer"),
            "when": [cond("yNoPumAla", "eq", True)],
            "then": [out("yPum1", "eq", False), out("yPum2", "eq", False)],
        },
    ]
    return {
        "schema": "bactalk.protocol-requirements/v1",
        "sequence_id": "pump-duty-standby",
        "title": "Duty/standby pump pair (BACTalk standard sequence)",
        "version": "1.0 (N10 draft, awaiting Gate G-ENG)",
        "tier": 4,
        "equipment_brick_class": "brick:Pump",
        "sources": [{"document": DOC, "edition": "designer practice; not a Guideline 36 sequence"}],
        "step_seconds": 5.0,
        "points": points,
        "requirements": requirements,
        "invariants": invariants,
        "notes": "BACTalk standard sequence (engineer-approved requirements), never labelled G36. Availability is an explicit input (hand/off/auto and fault status resolved upstream); the sequence is fail-closed: with nothing available nothing runs.",
    }


DOCUMENTS = {"requirements.json": build()}


def main(argv: list[str]) -> int:
    return write_requirements(DOCUMENTS, Path(__file__).parent, argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
