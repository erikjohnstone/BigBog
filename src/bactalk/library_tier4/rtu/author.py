# ruff: noqa: E501
"""Author the packaged rooftop unit (single zone, constant volume) requirement sets,
one per configuration (with or without an airside economizer).

``python -m bactalk.library_tier4.rtu.author`` rewrites the JSON files, ``--check``
verifies them. BACTalk standard sequence (designer practice), never G36.
"""

from __future__ import annotations

import sys
from pathlib import Path

from bactalk.protocol.authoring import cite, cond, out, point, tolerate_one_scan, write_requirements

DOC = "BACTalk standard sequence: packaged rooftop unit"
STAGE_DELAY = 120.0
PROOF_DELAY = 60.0
DEADBAND = 0.5
ECO_LOCKOUT = 291.15  # 18 °C outdoor high limit for free cooling
MIN_OA = 0.2


def build(with_economizer: bool) -> dict:
    points = [
        point(
            "uOcc",
            "Occupied (schedule)",
            "boolean",
            "input",
            nominal=True,
            brick="brick:Occupancy_Status",
        ),
        point(
            "TZon",
            "Zone temperature",
            "numeric",
            "input",
            "K",
            283.15,
            313.15,
            295.15,
            0.1,
            "brick:Zone_Air_Temperature_Sensor",
        ),
        point(
            "TZonCooSet",
            "Zone cooling setpoint",
            "numeric",
            "input",
            "K",
            291.15,
            303.15,
            297.15,
            0.1,
            "brick:Zone_Air_Cooling_Temperature_Setpoint",
        ),
        point(
            "TZonHeaSet",
            "Zone heating setpoint",
            "numeric",
            "input",
            "K",
            285.15,
            297.15,
            293.15,
            0.1,
            "brick:Zone_Air_Heating_Temperature_Setpoint",
        ),
        point(
            "uFanSta",
            "Supply fan proof",
            "boolean",
            "input",
            nominal=True,
            brick="brick:Run_Status",
        ),
    ]
    if with_economizer:
        points.append(
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
            )
        )
    points += [
        point(
            "yFan",
            "Supply fan start command",
            "boolean",
            "output",
            nominal=False,
            brick="brick:Run_Enable_Command",
        ),
        point(
            "yCoo",
            "Cooling stage 1 (compressor) command",
            "boolean",
            "output",
            nominal=False,
            brick="brick:Cooling_Command",
        ),
        point(
            "yHea",
            "Heating stage 1 command",
            "boolean",
            "output",
            nominal=False,
            brick="brick:Heating_Command",
        ),
        point(
            "yOutDam",
            "Outdoor air damper position",
            "numeric",
            "output",
            "1",
            0.0,
            1.0,
            0.0,
            0.01,
            "brick:Damper_Position_Command",
        ),
        point(
            "yFanAla",
            "Supply fan proof alarm",
            "boolean",
            "output",
            nominal=False,
            brick="brick:Alarm",
        ),
    ]
    cool_on = round(297.15 + DEADBAND, 2)  # nominal cooling setpoint plus half the deadband
    heat_on = round(293.15 - DEADBAND, 2)
    requirements = [
        {
            "id": "R-01",
            "title": "Supply fan runs when occupied",
            "kind": "control",
            "text": "The supply fan is commanded on whenever the unit is occupied and off when unoccupied (no setback cycling in this sequence).",
            "citation": cite(DOC, "§1 fan", fidelity="designer"),
            "conditions": [cond("uOcc", "eq", True)],
            "outcomes": [out("yFan", "eq", True)],
            "otherwise": [out("yFan", "eq", False)],
        },
        {
            "id": "R-02",
            "title": "Fan proof alarm",
            "kind": "alarm",
            "assumes": ["R-01"],
            "text": "When the fan is commanded on and not proven for 60 seconds the fan proof alarm is raised; it clears when the fan proves or the command is removed.",
            "citation": cite(DOC, "§5 alarms", fidelity="designer"),
            "conditions": [cond("uFanSta", "eq", False)],
            "timing": {"delay_seconds": PROOF_DELAY},
            "outcomes": [out("yFanAla", "eq", True)],
            "otherwise": [out("yFanAla", "eq", False)],
            "parameters": {"proofDelay_s": PROOF_DELAY},
        },
        {
            "id": "R-03",
            "title": "Cooling stage on high zone temperature",
            "kind": "staging",
            "assumes": ["R-01"],
            "text": "With the fan proven and the cooling setpoint at its nominal 297.15 K, the cooling stage is commanded on when the zone temperature exceeds the cooling setpoint by more than 0.5 K for 2 minutes, and off when it falls 0.5 K below the setpoint (1 K deadband). The stage is compared with the live setpoint.",
            "citation": cite(DOC, "§2 cooling", fidelity="designer"),
            "conditions": [cond("uFanSta", "eq", True), cond("TZon", "gt", cool_on, 2 * DEADBAND)],
            "timing": {"delay_seconds": STAGE_DELAY},
            "outcomes": [out("yCoo", "eq", True), out("yHea", "eq", False)],
            "otherwise": [out("yCoo", "eq", False)],
            "parameters": {"stageDelay_s": STAGE_DELAY, "deadband_K": 2 * DEADBAND},
        },
        {
            "id": "R-04",
            "title": "Heating stage on low zone temperature",
            "kind": "staging",
            "assumes": ["R-01"],
            "text": "With the fan proven and the heating setpoint at its nominal 293.15 K, the heating stage is commanded on when the zone temperature falls more than 0.5 K below the heating setpoint for 2 minutes, and off when it rises 0.5 K above the setpoint (1 K deadband).",
            "citation": cite(DOC, "§3 heating", fidelity="designer"),
            "conditions": [cond("uFanSta", "eq", True), cond("TZon", "lt", heat_on, 2 * DEADBAND)],
            "timing": {"delay_seconds": STAGE_DELAY},
            "outcomes": [out("yHea", "eq", True), out("yCoo", "eq", False)],
            "otherwise": [out("yHea", "eq", False)],
        },
        {
            "id": "R-05",
            "title": "Unoccupied shuts the unit down",
            "kind": "safety",
            "text": "When unoccupied the fan, cooling and heating stages are off and the outdoor air damper is closed in the same scan; the fan proof alarm is off.",
            "citation": cite(DOC, "§1 fan", fidelity="designer"),
            "conditions": [cond("uOcc", "eq", False)],
            "outcomes": [
                out("yFan", "eq", False),
                out("yCoo", "eq", False),
                out("yHea", "eq", False),
                out("yOutDam", "eq", 0.0),
                out("yFanAla", "eq", False),
            ],
            "otherwise": [out("yFan", "eq", True)],
        },
        {
            "id": "R-06",
            "title": "Minimum outdoor air with the fan proven",
            "kind": "control",
            "assumes": ["R-01"],
            "text": "With the fan proven and no free cooling, the outdoor air damper holds its minimum ventilation position (20 %).",
            "citation": cite(DOC, "§4 outdoor air", fidelity="designer"),
            "conditions": [cond("uFanSta", "eq", True)]
            + ([cond("TOut", "gt", ECO_LOCKOUT, 1.0)] if with_economizer else []),
            "outcomes": [out("yOutDam", "eq", MIN_OA, 0.001)],
            "otherwise": [out("yOutDam", "between", 0.0, upper=1.0)],
            "parameters": {"minOutdoorAir": MIN_OA},
        },
    ]
    if with_economizer:
        requirements.append(
            {
                "id": "R-07",
                "title": "Economizer free cooling",
                "kind": "control",
                "assumes": ["R-01"],
                "text": "With the fan proven, the outdoor air below the 291.15 K (18 °C) high limit (1 K deadband) and a cooling demand (zone above the cooling setpoint by more than 0.5 K), the outdoor air damper opens fully; when the outdoor air is above the high limit the damper returns to minimum position, and mechanical cooling still stages per R-03.",
                "citation": cite(DOC, "§4 outdoor air", "economizer", fidelity="designer"),
                "conditions": [
                    cond("uFanSta", "eq", True),
                    cond("TOut", "lt", ECO_LOCKOUT, 1.0),
                    cond("TZon", "gt", cool_on, 2 * DEADBAND),
                ],
                "outcomes": [out("yOutDam", "eq", 1.0, 0.001)],
                "otherwise": [out("yOutDam", "lte", MIN_OA, 0.001)],
                "parameters": {"economizerHighLimit_K": ECO_LOCKOUT},
            }
        )
    tolerate_one_scan(requirements)
    invariants = [
        {
            "id": "I-01",
            "text": "Nothing runs while unoccupied",
            "citation": cite(DOC, "§1 fan", fidelity="designer"),
            "when": [cond("uOcc", "eq", False)],
            "then": [
                out("yFan", "eq", False),
                out("yCoo", "eq", False),
                out("yHea", "eq", False),
                out("yOutDam", "eq", 0.0),
            ],
        },
        {
            "id": "I-02",
            "text": "Heating and cooling never together",
            "citation": cite(DOC, "§2 cooling", fidelity="designer"),
            "when": [cond("yCoo", "eq", True)],
            "then": [out("yHea", "eq", False)],
        },
        {
            "id": "I-03",
            "text": "No stage without a proven fan",
            "citation": cite(DOC, "§2 cooling", fidelity="designer"),
            "when": [cond("uFanSta", "eq", False)],
            "then": [out("yCoo", "eq", False), out("yHea", "eq", False)],
        },
        {
            "id": "I-04",
            "text": "The damper position is a fraction",
            "citation": cite(DOC, "§4 outdoor air", fidelity="designer"),
            "then": [out("yOutDam", "between", 0.0, upper=1.0)],
        },
    ]
    return {
        "schema": "bactalk.protocol-requirements/v1",
        "sequence_id": "rtu-economizer" if with_economizer else "rtu",
        "title": "Packaged rooftop unit, single zone"
        + (" with economizer" if with_economizer else "")
        + " (BACTalk standard sequence)",
        "version": "1.0 (N10 draft, awaiting Gate G-ENG)",
        "tier": 4,
        "equipment_brick_class": "brick:RTU",
        "sources": [{"document": DOC, "edition": "designer practice; not a Guideline 36 sequence"}],
        "step_seconds": 10.0,
        "points": points,
        "requirements": requirements,
        "invariants": invariants,
        "notes": "BACTalk standard sequence (engineer-approved requirements), never labelled G36. Configuration option economizer="
        + str(with_economizer).lower()
        + ". Setpoints are inputs; the staging requirements are stated at the nominal setpoints so their thresholds are numbers.",
    }


DOCUMENTS = {"requirements.json": build(False), "requirements-economizer.json": build(True)}


def main(argv: list[str]) -> int:
    return write_requirements(DOCUMENTS, Path(__file__).parent, argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
