# ruff: noqa: E501
"""Author the dedicated outdoor air system requirement sets, one per configuration
(with or without an energy recovery wheel and exhaust fan).

``python -m bactalk.library_tier4.doas.author`` rewrites the JSON files, ``--check``
verifies them. BACTalk standard sequence (designer practice), never G36.
"""

from __future__ import annotations

import sys
from pathlib import Path

from bactalk.protocol.authoring import cite, cond, out, point, tolerate_one_scan, write_requirements

DOC = "BACTalk standard sequence: dedicated outdoor air system"
PROOF_DELAY = 60.0
LOOP_DELAY = 60.0
DEADBAND = 1.0
SUP_SET = 291.15
ERV_COLD = 285.15
ERV_WARM = 297.15


def build(with_erv: bool) -> dict:
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
            "TOut",
            "Outdoor air temperature",
            "numeric",
            "input",
            "K",
            243.15,
            323.15,
            291.15,
            0.1,
            "brick:Outside_Air_Temperature_Sensor",
        ),
        point(
            "TSup",
            "Supply air temperature",
            "numeric",
            "input",
            "K",
            273.15,
            313.15,
            SUP_SET,
            0.1,
            "brick:Supply_Air_Temperature_Sensor",
        ),
        point(
            "TSupSet",
            "Supply air temperature setpoint",
            "numeric",
            "input",
            "K",
            285.15,
            299.15,
            SUP_SET,
            0.1,
            "brick:Supply_Air_Temperature_Setpoint",
        ),
        point(
            "uSupFanSta",
            "Supply fan proof",
            "boolean",
            "input",
            nominal=True,
            brick="brick:Run_Status",
        ),
    ]
    if with_erv:
        points.append(
            point(
                "uExhFanSta",
                "Exhaust fan proof",
                "boolean",
                "input",
                nominal=True,
                brick="brick:Run_Status",
            )
        )
    points += [
        point(
            "ySupFan",
            "Supply fan start command",
            "boolean",
            "output",
            nominal=False,
            brick="brick:Run_Enable_Command",
        ),
        point(
            "yHeaVal",
            "Heating coil valve position",
            "numeric",
            "output",
            "1",
            0.0,
            1.0,
            0.0,
            0.01,
            "brick:Heating_Valve_Command",
        ),
        point(
            "yCooVal",
            "Cooling coil valve position",
            "numeric",
            "output",
            "1",
            0.0,
            1.0,
            0.0,
            0.01,
            "brick:Cooling_Valve_Command",
        ),
        point(
            "yFanAla", "Fan proof alarm", "boolean", "output", nominal=False, brick="brick:Alarm"
        ),
    ]
    if with_erv:
        points += [
            point(
                "yExhFan",
                "Exhaust fan start command",
                "boolean",
                "output",
                nominal=False,
                brick="brick:Run_Enable_Command",
            ),
            point(
                "yWhe",
                "Energy recovery wheel enable",
                "boolean",
                "output",
                nominal=False,
                brick="brick:Enable_Command",
            ),
        ]
    heat_on = round(SUP_SET - DEADBAND / 2, 2)
    cool_on = round(SUP_SET + DEADBAND / 2, 2)
    requirements = [
        {
            "id": "R-01",
            "title": "Supply fan runs when occupied",
            "kind": "control",
            "text": "The supply fan is commanded on whenever the unit is occupied and off when unoccupied.",
            "citation": cite(DOC, "§1 fans", fidelity="designer"),
            "conditions": [cond("uOcc", "eq", True)],
            "outcomes": [out("ySupFan", "eq", True)],
            "otherwise": [out("ySupFan", "eq", False)],
        },
        {
            "id": "R-02",
            "title": "Supply fan proof alarm",
            "kind": "alarm",
            "assumes": ["R-01"],
            "text": "When the supply fan is commanded on and not proven for 60 seconds the fan proof alarm is raised; it clears when the fan proves or the command is removed.",
            "citation": cite(DOC, "§5 alarms", fidelity="designer"),
            "conditions": [cond("uSupFanSta", "eq", False)],
            "timing": {"delay_seconds": PROOF_DELAY},
            "outcomes": [out("yFanAla", "eq", True)],
            "otherwise": [out("yFanAla", "eq", False)],
            "parameters": {"proofDelay_s": PROOF_DELAY},
        },
        {
            "id": "R-03",
            "title": "Heating coil holds the supply setpoint",
            "kind": "loop",
            "assumes": ["R-01"],
            "text": "With the supply fan proven, the heating coil valve is modulated (proportional, 0.5 per K) to hold the supply air temperature at the setpoint less half the 1 K deadband; with the supply 3 K or more below the nominal 291.15 K setpoint for 60 seconds the valve is at least 90 % open, and it is closed whenever the supply is above the setpoint.",
            "citation": cite(DOC, "§2 supply temperature", "heating", fidelity="designer"),
            "conditions": [
                cond("uSupFanSta", "eq", True),
                cond("TSup", "lt", round(SUP_SET - 3.0, 2)),
            ],
            "timing": {"delay_seconds": LOOP_DELAY},
            "outcomes": [out("yHeaVal", "gte", 0.9), out("yCooVal", "eq", 0.0, 0.001)],
            "otherwise": [out("yHeaVal", "between", 0.0, upper=1.0)],
            "parameters": {"loopGain_perK": 0.5, "deadband_K": DEADBAND},
        },
        {
            "id": "R-04",
            "title": "Cooling coil holds the supply setpoint",
            "kind": "loop",
            "assumes": ["R-01"],
            "text": "With the supply fan proven, the cooling coil valve is modulated (proportional, 0.5 per K) to hold the supply air temperature at the setpoint plus half the deadband; with the supply 3 K or more above the nominal setpoint for 60 seconds the valve is at least 90 % open, and it is closed whenever the supply is below the setpoint.",
            "citation": cite(DOC, "§2 supply temperature", "cooling", fidelity="designer"),
            "conditions": [
                cond("uSupFanSta", "eq", True),
                cond("TSup", "gt", round(SUP_SET + 3.0, 2)),
            ],
            "timing": {"delay_seconds": LOOP_DELAY},
            "outcomes": [out("yCooVal", "gte", 0.9), out("yHeaVal", "eq", 0.0, 0.001)],
            "otherwise": [out("yCooVal", "between", 0.0, upper=1.0)],
        },
        {
            "id": "R-05",
            "title": "Both valves closed inside the deadband",
            "kind": "loop",
            "assumes": ["R-01"],
            "text": "With the supply fan proven and the supply air temperature inside the 1 K deadband around the nominal setpoint (290.65 K to 291.65 K), both coil valves are closed.",
            "citation": cite(DOC, "§2 supply temperature", "deadband", fidelity="designer"),
            "conditions": [cond("uSupFanSta", "eq", True), cond("TSup", "between", heat_on, 0.0)],
            "outcomes": [out("yHeaVal", "eq", 0.0, 0.001), out("yCooVal", "eq", 0.0, 0.001)],
            "otherwise": [out("yHeaVal", "between", 0.0, upper=1.0)],
        },
        {
            "id": "R-06",
            "title": "Unoccupied shuts the unit down",
            "kind": "safety",
            "text": "When unoccupied the supply fan"
            + (", the exhaust fan, the wheel" if with_erv else "")
            + " and both valves are off in the same scan, and the fan proof alarm is off.",
            "citation": cite(DOC, "§1 fans", fidelity="designer"),
            "conditions": [cond("uOcc", "eq", False)],
            "outcomes": [
                out("ySupFan", "eq", False),
                out("yHeaVal", "eq", 0.0, 0.001),
                out("yCooVal", "eq", 0.0, 0.001),
                out("yFanAla", "eq", False),
            ]
            + ([out("yExhFan", "eq", False), out("yWhe", "eq", False)] if with_erv else []),
            "otherwise": [out("ySupFan", "eq", True)],
        },
    ]
    requirements[4]["conditions"][1]["upper"] = cool_on
    if with_erv:
        requirements += [
            {
                "id": "R-07",
                "title": "Exhaust fan runs with the supply fan",
                "kind": "control",
                "text": "The exhaust fan is commanded on whenever the unit is occupied and off when unoccupied.",
                "citation": cite(DOC, "§1 fans", fidelity="designer"),
                "conditions": [cond("uOcc", "eq", True)],
                "outcomes": [out("yExhFan", "eq", True)],
                "otherwise": [out("yExhFan", "eq", False)],
            },
            {
                "id": "R-08",
                "title": "Energy recovery wheel in cold weather",
                "kind": "control",
                "assumes": ["R-01"],
                "text": "With both fans proven, the energy recovery wheel is enabled when the outdoor air is below 285.15 K (12 °C, 1 K deadband) and disabled inside the free-cooling window between the cold and warm limits.",
                "citation": cite(DOC, "§3 energy recovery", "cold", fidelity="designer"),
                "conditions": [
                    cond("uSupFanSta", "eq", True),
                    cond("uExhFanSta", "eq", True),
                    cond("TOut", "lt", ERV_COLD, DEADBAND),
                ],
                "outcomes": [out("yWhe", "eq", True)],
                "otherwise": [out("yWhe", "eq", False)],
                "parameters": {"ervColdLimit_K": ERV_COLD, "ervWarmLimit_K": ERV_WARM},
            },
            {
                "id": "R-09",
                "title": "Energy recovery wheel in warm weather",
                "kind": "control",
                "assumes": ["R-01"],
                "text": "With both fans proven, the energy recovery wheel is enabled when the outdoor air is above 297.15 K (24 °C, 1 K deadband) and disabled inside the free-cooling window.",
                "citation": cite(DOC, "§3 energy recovery", "warm", fidelity="designer"),
                "conditions": [
                    cond("uSupFanSta", "eq", True),
                    cond("uExhFanSta", "eq", True),
                    cond("TOut", "gt", ERV_WARM, DEADBAND),
                ],
                "outcomes": [out("yWhe", "eq", True)],
                "otherwise": [out("yWhe", "eq", False)],
            },
        ]
    tolerate_one_scan(requirements)
    invariants = [
        {
            "id": "I-01",
            "text": "Nothing runs while unoccupied",
            "citation": cite(DOC, "§1 fans", fidelity="designer"),
            "when": [cond("uOcc", "eq", False)],
            "then": [
                out("ySupFan", "eq", False),
                out("yHeaVal", "eq", 0.0),
                out("yCooVal", "eq", 0.0),
            ]
            + ([out("yExhFan", "eq", False), out("yWhe", "eq", False)] if with_erv else []),
        },
        {
            "id": "I-02",
            "text": "Heating and cooling valves never open together",
            "citation": cite(DOC, "§2 supply temperature", fidelity="designer"),
            "when": [cond("yHeaVal", "gt", 0.001)],
            "then": [out("yCooVal", "eq", 0.0, 0.001)],
        },
        {
            "id": "I-03",
            "text": "Valve positions are fractions",
            "citation": cite(DOC, "§2 supply temperature", fidelity="designer"),
            "then": [
                out("yHeaVal", "between", 0.0, upper=1.0),
                out("yCooVal", "between", 0.0, upper=1.0),
            ],
        },
    ]
    return {
        "schema": "bactalk.protocol-requirements/v1",
        "sequence_id": "doas-erv" if with_erv else "doas",
        "title": "Dedicated outdoor air system"
        + (" with energy recovery" if with_erv else "")
        + " (BACTalk standard sequence)",
        "version": "1.0 (N10 draft, awaiting Gate G-ENG)",
        "tier": 4,
        "equipment_brick_class": "brick:DOAS",
        "sources": [{"document": DOC, "edition": "designer practice; not a Guideline 36 sequence"}],
        "step_seconds": 10.0,
        "points": points,
        "requirements": requirements,
        "invariants": invariants,
        "notes": "BACTalk standard sequence (engineer-approved requirements), never labelled G36. Configuration option energy_recovery="
        + str(with_erv).lower()
        + ". The supply setpoint is an input; the loop requirements are stated at the nominal setpoint so their thresholds are numbers.",
    }


DOCUMENTS = {"requirements.json": build(False), "requirements-erv.json": build(True)}


def main(argv: list[str]) -> int:
    return write_requirements(DOCUMENTS, Path(__file__).parent, argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
