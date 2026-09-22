# ruff: noqa: E501
"""Author the air-source heat pump (single zone) requirement sets, one per configuration
(with or without auxiliary electric heat).

``python -m bactalk.library_tier4.heat_pump.author`` rewrites the JSON files, ``--check``
verifies them. BACTalk standard sequence (designer practice), never G36.
"""

from __future__ import annotations

import sys
from pathlib import Path

from bactalk.protocol.authoring import cite, cond, out, point, tolerate_one_scan, write_requirements

DOC = "BACTalk standard sequence: air-source heat pump"
STAGE_DELAY = 120.0
AUX_DELAY = 600.0
PROOF_DELAY = 60.0
DEADBAND = 1.0
COOL_SET = 297.15
HEAT_SET = 293.15
LOCKOUT = 268.15  # compressor heating lockout, −5 °C
AUX_DROP = 2.0


def build(with_aux: bool) -> dict:
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
            COOL_SET,
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
            HEAT_SET,
            0.1,
            "brick:Zone_Air_Heating_Temperature_Setpoint",
        ),
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
        point(
            "uFanSta",
            "Indoor fan proof",
            "boolean",
            "input",
            nominal=True,
            brick="brick:Run_Status",
        ),
        point(
            "yFan",
            "Indoor fan start command",
            "boolean",
            "output",
            nominal=False,
            brick="brick:Run_Enable_Command",
        ),
        point(
            "yCom",
            "Compressor command",
            "boolean",
            "output",
            nominal=False,
            brick="brick:Compressor_Command",
        ),
        point(
            "yRev",
            "Reversing valve (true = cooling)",
            "boolean",
            "output",
            nominal=False,
            brick="brick:Reversing_Valve_Command",
        ),
        point(
            "yFanAla",
            "Indoor fan proof alarm",
            "boolean",
            "output",
            nominal=False,
            brick="brick:Alarm",
        ),
    ]
    if with_aux:
        points.append(
            point(
                "yAux",
                "Auxiliary electric heat command",
                "boolean",
                "output",
                nominal=False,
                brick="brick:Heating_Command",
            )
        )
    cool_on = round(COOL_SET + DEADBAND / 2, 2)
    heat_on = round(HEAT_SET - DEADBAND / 2, 2)
    requirements = [
        {
            "id": "R-01",
            "title": "Indoor fan runs when occupied",
            "kind": "control",
            "text": "The indoor fan is commanded on whenever the unit is occupied and off when unoccupied.",
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
            "citation": cite(DOC, "§6 alarms", fidelity="designer"),
            "conditions": [cond("uFanSta", "eq", False)],
            "timing": {"delay_seconds": PROOF_DELAY},
            "outcomes": [out("yFanAla", "eq", True)],
            "otherwise": [out("yFanAla", "eq", False)],
            "parameters": {"proofDelay_s": PROOF_DELAY},
        },
        {
            "id": "R-03",
            "title": "Cooling: compressor with the reversing valve in cooling",
            "kind": "staging",
            "assumes": ["R-01"],
            "text": "With the fan proven and the cooling setpoint at its nominal 297.15 K, the compressor runs in cooling (reversing valve energised) when the zone temperature exceeds the cooling setpoint by more than 0.5 K for 2 minutes, and stops when it falls 0.5 K below the setpoint (1 K deadband). The stage is compared with the live setpoint.",
            "citation": cite(DOC, "§2 cooling", fidelity="designer"),
            "conditions": [cond("uFanSta", "eq", True), cond("TZon", "gt", cool_on, DEADBAND)],
            "timing": {"delay_seconds": STAGE_DELAY},
            "outcomes": [out("yCom", "eq", True), out("yRev", "eq", True)],
            "otherwise": [out("yCom", "eq", False)],
            "parameters": {"stageDelay_s": STAGE_DELAY, "deadband_K": DEADBAND},
        },
        {
            "id": "R-04",
            "title": "Heating: compressor with the reversing valve in heating",
            "kind": "staging",
            "assumes": ["R-01"],
            "text": "With the fan proven, the outdoor air above the 268.15 K (−5 °C) compressor lockout (locked again below 267.15 K, a 1 K deadband) and the heating setpoint at its nominal 293.15 K, the compressor runs in heating (reversing valve de-energised) when the zone temperature falls more than 0.5 K below the heating setpoint for 2 minutes, and stops when it rises 0.5 K above the setpoint.",
            "citation": cite(DOC, "§3 heating", fidelity="designer"),
            "conditions": [
                cond("uFanSta", "eq", True),
                cond("TOut", "gt", LOCKOUT, DEADBAND),
                cond("TZon", "lt", heat_on, DEADBAND),
            ],
            "timing": {"delay_seconds": STAGE_DELAY},
            "outcomes": [out("yCom", "eq", True), out("yRev", "eq", False)]
            + ([out("yAux", "eq", False)] if with_aux else []),
            "otherwise": [out("yCom", "eq", False)],
            "parameters": {"compressorLockout_K": LOCKOUT},
        },
        {
            "id": "R-05",
            "title": "Unoccupied shuts the unit down",
            "kind": "safety",
            "text": "When unoccupied the fan, the compressor"
            + (", the auxiliary heat" if with_aux else "")
            + " and the fan proof alarm are off in the same scan.",
            "citation": cite(DOC, "§1 fan", fidelity="designer"),
            "conditions": [cond("uOcc", "eq", False)],
            "outcomes": [
                out("yFan", "eq", False),
                out("yCom", "eq", False),
                out("yFanAla", "eq", False),
            ]
            + ([out("yAux", "eq", False)] if with_aux else []),
            "otherwise": [out("yFan", "eq", True)],
        },
    ]
    if with_aux:
        requirements += [
            {
                "id": "R-06",
                "title": "Auxiliary heat below the compressor lockout",
                "kind": "staging",
                "assumes": ["R-01"],
                "text": "With the fan proven, the outdoor air below 267.15 K (the compressor lockout less its 1 K deadband; the compressor is allowed again above 268.15 K) and a heating demand (zone more than 0.5 K below the heating setpoint) for 2 minutes, the auxiliary electric heat runs alone: the compressor stays off.",
                "citation": cite(DOC, "§4 auxiliary heat", "lockout", fidelity="designer"),
                "conditions": [
                    cond("uFanSta", "eq", True),
                    cond("TOut", "lt", round(LOCKOUT - DEADBAND, 2), DEADBAND),
                    cond("TZon", "lt", heat_on, DEADBAND),
                ],
                "timing": {"delay_seconds": STAGE_DELAY},
                "outcomes": [out("yAux", "eq", True), out("yCom", "eq", False)],
                "otherwise": [out("yAux", "eq", False)],
            },
            {
                "id": "R-07",
                "title": "Supplemental heat when the compressor cannot hold",
                "kind": "staging",
                "assumes": ["R-04"],
                "text": "When a heating demand persists with the zone more than 2 K below the heating setpoint (1 K deadband) for 10 minutes from the start of the demand, the auxiliary heat is added to the compressor; it drops out when the zone is within 1 K of the setpoint.",
                "citation": cite(DOC, "§4 auxiliary heat", "supplemental", fidelity="designer"),
                "conditions": [cond("TZon", "lt", round(HEAT_SET - AUX_DROP, 2), DEADBAND)],
                "timing": {"delay_seconds": AUX_DELAY},
                "outcomes": [out("yAux", "eq", True), out("yCom", "eq", True)],
                "before": [out("yAux", "eq", False), out("yCom", "eq", True)],
                "otherwise": [out("yAux", "eq", False)],
                "parameters": {"auxDelay_s": AUX_DELAY, "auxDrop_K": AUX_DROP},
            },
        ]
    tolerate_one_scan(requirements)
    invariants = [
        {
            "id": "I-01",
            "text": "Nothing runs while unoccupied",
            "citation": cite(DOC, "§1 fan", fidelity="designer"),
            "when": [cond("uOcc", "eq", False)],
            "then": [out("yFan", "eq", False), out("yCom", "eq", False)]
            + ([out("yAux", "eq", False)] if with_aux else []),
        },
        {
            "id": "I-02",
            "text": "No compressor heating below the lockout",
            "citation": cite(DOC, "§3 heating", fidelity="designer"),
            "when": [cond("TOut", "lt", round(LOCKOUT - DEADBAND, 2)), cond("yRev", "eq", False)],
            "then": [out("yCom", "eq", False)],
        },
        {
            "id": "I-03",
            "text": "No compressor without a proven fan",
            "citation": cite(DOC, "§2 cooling", fidelity="designer"),
            "when": [cond("uFanSta", "eq", False)],
            "then": [out("yCom", "eq", False)] + ([out("yAux", "eq", False)] if with_aux else []),
        },
    ]
    if with_aux:
        invariants.append(
            {
                "id": "I-04",
                "text": "Auxiliary heat only in heating mode",
                "citation": cite(DOC, "§4 auxiliary heat", fidelity="designer"),
                "when": [cond("yAux", "eq", True)],
                "then": [out("yRev", "eq", False)],
            }
        )
    return {
        "schema": "bactalk.protocol-requirements/v1",
        "sequence_id": "heat-pump-aux" if with_aux else "heat-pump",
        "title": "Air-source heat pump, single zone"
        + (" with auxiliary heat" if with_aux else "")
        + " (BACTalk standard sequence)",
        "version": "1.0 (N10 draft, awaiting Gate G-ENG)",
        "tier": 4,
        "equipment_brick_class": "brick:Heat_Pump",
        "sources": [{"document": DOC, "edition": "designer practice; not a Guideline 36 sequence"}],
        "step_seconds": 10.0,
        "points": points,
        "requirements": requirements,
        "invariants": invariants,
        "notes": "BACTalk standard sequence (engineer-approved requirements), never labelled G36. Configuration option aux_heat="
        + str(with_aux).lower()
        + ". Setpoints are inputs; staging requirements are stated at the nominal setpoints so their thresholds are numbers. Minimum compressor off time and defrost are out of scope of this draft.",
    }


DOCUMENTS = {"requirements.json": build(False), "requirements-aux.json": build(True)}


def main(argv: list[str]) -> int:
    return write_requirements(DOCUMENTS, Path(__file__).parent, argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
