# ruff: noqa: E501
"""Author the fixture custom sequence "seasonal heating/cooling changeover" as a
contractor's specification section would state it (Tier 5, job-specific).

``python -m bactalk.library_tier5_fixture.seasonal_changeover.author`` rewrites the
JSON, ``--check`` verifies it.
"""

from __future__ import annotations

import sys
from pathlib import Path

from bactalk.protocol.authoring import cite, cond, out, point, tolerate_one_scan, write_requirements

DOC = "Project specification 23 09 93, seasonal changeover (contractor upload)"
HEAT_LIMIT = 288.15  # 15 °C
COOL_LIMIT = 292.15  # 19 °C
DEADBAND = 2.0
DELAY = 1800.0


def build() -> dict:
    points = [
        point(
            "TOut",
            "Outdoor air temperature",
            "numeric",
            "input",
            "K",
            243.15,
            323.15,
            283.15,
            0.1,
            "brick:Outside_Air_Temperature_Sensor",
        ),
        point("uHeaOvr", "Operator override: heating season", "boolean", "input", nominal=False),
        point("uCooOvr", "Operator override: cooling season", "boolean", "input", nominal=False),
        point(
            "yHeaSea",
            "Heating season (bound to VAV_21.u1HotPla)",
            "boolean",
            "output",
            nominal=False,
            brick="brick:Heating_Enable_Command",
        ),
        point(
            "yCooSea",
            "Cooling season",
            "boolean",
            "output",
            nominal=False,
            brick="brick:Cooling_Enable_Command",
        ),
    ]
    requirements = [
        {
            "id": "R-01",
            "title": "Heating season on sustained cold outdoor air",
            "kind": "control",
            "text": "The heating season shall be declared when the outdoor air temperature has been below 15 °C (288.15 K) for 30 minutes and shall end when it has risen above 17 °C (2 K deadband) for 30 minutes.",
            "citation": cite(DOC, "3.7.A", "paragraph 1", fidelity="verbatim"),
            "conditions": [cond("TOut", "lt", HEAT_LIMIT, DEADBAND)],
            "timing": {"delay_seconds": DELAY, "release_seconds": DELAY},
            "outcomes": [out("yHeaSea", "eq", True), out("yCooSea", "eq", False)],
            "otherwise": [out("yHeaSea", "eq", False)],
            "parameters": {
                "heatingLimit_K": HEAT_LIMIT,
                "deadband_K": DEADBAND,
                "changeoverDelay_s": DELAY,
            },
        },
        {
            "id": "R-02",
            "title": "Cooling season on sustained warm outdoor air",
            "kind": "control",
            "text": "The cooling season shall be declared when the outdoor air temperature has been above 19 °C (292.15 K) for 30 minutes and shall end when it has fallen below 17 °C for 30 minutes.",
            "citation": cite(DOC, "3.7.B", "paragraph 2", fidelity="verbatim"),
            "conditions": [cond("TOut", "gt", COOL_LIMIT, DEADBAND)],
            "timing": {"delay_seconds": DELAY, "release_seconds": DELAY},
            "outcomes": [out("yCooSea", "eq", True), out("yHeaSea", "eq", False)],
            "otherwise": [out("yCooSea", "eq", False)],
            "parameters": {"coolingLimit_K": COOL_LIMIT},
        },
        {
            "id": "R-03",
            "title": "Heating override",
            "kind": "control",
            "text": "An operator heating override shall force the heating season immediately regardless of outdoor temperature.",
            "citation": cite(DOC, "3.7.C", "paragraph 3", fidelity="verbatim"),
            "conditions": [cond("uHeaOvr", "eq", True)],
            "outcomes": [out("yHeaSea", "eq", True), out("yCooSea", "eq", False)],
            "otherwise": [out("yCooSea", "eq", False)],
        },
        {
            "id": "R-04",
            "title": "Cooling override",
            "kind": "control",
            "text": "An operator cooling override shall force the cooling season immediately regardless of outdoor temperature; when both overrides are set the heating override prevails.",
            "citation": cite(DOC, "3.7.C", "paragraph 3", fidelity="verbatim"),
            "conditions": [cond("uCooOvr", "eq", True), cond("uHeaOvr", "eq", False)],
            "outcomes": [out("yCooSea", "eq", True), out("yHeaSea", "eq", False)],
            "otherwise": [out("yCooSea", "eq", False)],
        },
    ]
    tolerate_one_scan(requirements)
    invariants = [
        {
            "id": "I-01",
            "text": "Never both seasons",
            "citation": cite(DOC, "3.7", fidelity="paraphrase"),
            "when": [cond("yHeaSea", "eq", True)],
            "then": [out("yCooSea", "eq", False)],
        },
        {
            "id": "I-02",
            "text": "The heating override always wins",
            "citation": cite(DOC, "3.7.C", fidelity="paraphrase"),
            "when": [cond("uHeaOvr", "eq", True)],
            "then": [out("yHeaSea", "eq", True), out("yCooSea", "eq", False)],
        },
    ]
    return {
        "schema": "bactalk.protocol-requirements/v1",
        "sequence_id": "custom-seasonal-changeover",
        "title": "Seasonal heating/cooling changeover (custom, job-specific)",
        "version": "1.0 (N11 fixture, contractor approval pending)",
        "tier": 5,
        "equipment_brick_class": "brick:Equipment",
        "sources": [
            {
                "document": DOC,
                "edition": "fixture text in the style of a specification section; the contractor approves it",
            }
        ],
        "step_seconds": 60.0,
        "points": points,
        "requirements": requirements,
        "invariants": invariants,
        "notes": "Custom, job-specific sequence (Tier 5). Its heating-season output feeds the Tier 1 VAV box's hot water plant status through the project signal binding CHG_1.yHeaSea -> VAV_21.u1HotPla.",
    }


DOCUMENTS = {"requirements.json": build()}


def main(argv: list[str]) -> int:
    return write_requirements(DOCUMENTS, Path(__file__).parent, argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
