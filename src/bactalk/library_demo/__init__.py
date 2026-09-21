"""LBNL-sourced demonstration jobs (GOAL-NATIVE-BOG.md, N0).

The demo candidates are exact translations of pinned LBNL Modelica Buildings
Guideline 36 controllers. The translation (modelica-json → CXF → Open Control
Engine → typed IR) needs the vendored toolchain, so the result is retained here as
package data with full provenance: the LBNL revision, the controller source
digest, the CXF digest, the execution profile and every parameter value. A base
install builds the demo from the retained typed IR; the integration tier
re-translates and fails if the retained copy drifts from the pinned source.

Acceptance tests here were authored against the translated program's observed
behaviour and cite the Guideline 36 section they exercise. They are the demo's
oracle, not a proof of the LBNL logic: that proof is the OCE golden traces.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any

from bactalk.domain import (
    AcceptanceCase,
    ControlGraph,
    DataType,
    JobSpec,
    OutputExpectation,
    PointRole,
    PointSpec,
    SequenceSpec,
)

RETAINED = {
    "TerminalUnits.Reheat.Controller": "terminal_unit_reheat.json",
    "AHUs.MultiZone.VAV.Controller": "ahu_multizone_vav.json",
}

# Guideline 36 operation modes (Buildings.Controls.OBC.ASHRAE.G36.Types.OperationModes).
OCCUPIED = 1
UNOCCUPIED = 7

_UNITS: dict[str, str] = {
    # LBNL controllers work in SI; the point units say so honestly.
    "T": "K",
    "V": "m3/s",
    "dp": "Pa",
    "ppm": "ppm",
    "h": "J/kg",
}


@cache
def retained_translation(controller_id: str) -> dict[str, Any]:
    """The retained translation for a demo controller, parsed once."""
    filename = RETAINED[controller_id]
    text = resources.files(__package__).joinpath(filename).read_text(encoding="utf-8")
    return json.loads(text)


def _unit_for(name: str, data_type: str) -> str | None:
    if data_type == "boolean":
        return None
    if name.startswith("ppm"):
        return "ppm"
    if name.startswith(("T", "TAir", "TOut")) and name[1:2].isupper():
        return "K"
    if name.startswith(("V", "VSum", "VEff", "VAdj", "VMin", "VSet", "VDis")):
        return "m3/s"
    if name.startswith(("dp", "yDp")):
        return "Pa"
    if name.startswith("h"):
        return "J/kg"
    if name.startswith(("y", "u")) and not name.startswith(("y1", "u1")):
        return None
    return None


def _points(controller_id: str, defaults: dict[str, float | bool]) -> list[PointSpec]:
    retained = retained_translation(controller_id)
    points: list[PointSpec] = []
    for point in retained["points"]:
        name = point["name"]
        data_type = point["data_type"]
        is_input = point["source_interface_direction"] == "input"
        default = defaults.get(name, point["default"]) if is_input else point["default"]
        points.append(
            PointSpec(
                name=name,
                label=point["label"],
                data_type=DataType(data_type),
                role=PointRole.SENSOR if is_input else PointRole.COMMAND,
                units=_unit_for(name, data_type),
                default=default,
                required=True,
            )
        )
    return points


def _graph(controller_id: str, points: list[PointSpec]) -> ControlGraph:
    retained = retained_translation(controller_id)
    graph = ControlGraph.model_validate(retained["typed_ir"])
    defaults = {point.name: point.default for point in points}
    blocks = []
    for block in graph.blocks:
        if block.id in defaults and block.kind.value.endswith("_input"):
            block = block.model_copy(
                update={"config": {**block.config, "default": defaults[block.id]}}
            )
        blocks.append(block)
    return graph.model_copy(update={"blocks": blocks})


def _sequence(controller_id: str) -> SequenceSpec:
    retained = retained_translation(controller_id)
    return SequenceSpec(
        family="LBNL_G36_CONTROLLER",
        version=(
            "LBNL Modelica Buildings v13.0.0 "
            f"({retained['source']['revision'][:12]}) · retained translation "
            f"cxf {retained['translator']['cxf_source_sha256'][:12]}"
        ),
        library="g36",
        controller_id=controller_id,
        execution_profile=retained["execution_profile"],
        parameters=dict(retained["parameters"]),
    )


def _case(
    name: str, inputs: dict[str, float | bool], expectations: list[OutputExpectation]
) -> AcceptanceCase:
    # 45 minutes at one-minute scans: long enough for the G36 timers (alarm delays,
    # trim-and-respond periods) to settle.
    return AcceptanceCase(
        name=name, inputs=inputs, repeat=45, step_seconds=60.0, expectations=expectations
    )


def _eq(target: str, value: float | bool, *, tolerance: float = 0.0) -> OutputExpectation:
    return OutputExpectation(target=target, value=value, tolerance=tolerance)


# Airflow setpoints are computed through m³/s parameters; compare them to a
# tenth of a litre per second rather than bit-for-bit.
_FLOW_TOLERANCE = 1e-4
# PID valve positions settle to within floating-point noise of their limits.
_POSITION_TOLERANCE = 1e-6


def _op(target: str, operator: str, value: float) -> OutputExpectation:
    return OutputExpectation(target=target, operator=operator, value=value)


def lbnl_vav_reheat_demo_job() -> JobSpec:
    """A single-duct VAV box with hot-water reheat, exactly as LBNL publishes it."""

    controller_id = "TerminalUnits.Reheat.Controller"
    occupied = {
        "TCooSet": 297.15,
        "THeaSet": 293.15,
        "TZon": 295.15,
        "TSup": 286.15,
        "TSupSet": 286.15,
        "TDis": 288.15,
        "VDis_flow": 0.094,
        "oveDamPos": 0,
        "oveFloSet": 0,
        "ppmCO2": 600.0,
        "ppmCO2Set": 900.0,
        "u1Fan": True,
        "u1HotPla": True,
        "u1Occ": True,
        "u1Win": True,
        "uHeaOff": False,
        "uOpeMod": OCCUPIED,
    }
    points = _points(controller_id, occupied)
    cases = [
        # G36 §5.6.5: in the deadband the airflow setpoint is the zone minimum.
        _case(
            "occupied deadband holds minimum airflow",
            {**occupied, "TZon": 295.15, "VDis_flow": 0.094},
            [
                _eq("VSet_flow", 0.094, tolerance=_FLOW_TOLERANCE),
                _eq("yVal", 0.0),
                _eq("yZonTemResReq", 0.0),
                _eq("yHotWatPlaReq", 0.0),
                _eq("yLowFloAla", 0.0),
                _eq("yLeaDamAla", 0.0),
            ],
        ),
        # G36 §5.6.5.1: cooling loop drives the setpoint to cooling maximum and
        # §5.6.8.1 raises a supply-air-temperature reset request.
        # The box is starved (measured airflow 64 % of setpoint), so the damper
        # loop saturates open; §5.6.8.2 then counts two pressure-reset requests
        # (airflow below 70 % of setpoint with the damper above 95 %) and §5.6.9.1
        # raises the level-3 low-airflow alarm after the 5-minute delay.
        _case(
            "occupied cooling ramps to cooling maximum",
            {**occupied, "TZon": 299.15, "VDis_flow": 0.30},
            [
                _eq("VSet_flow", 0.472, tolerance=_FLOW_TOLERANCE),
                _op("yDam", "gt", 0.95),
                _eq("yVal", 0.0),
                _op("yZonTemResReq", "gte", 1.0),
                _eq("yZonPreResReq", 2.0),
                _eq("yLowFloAla", 3.0),
                _eq("yHeaValResReq", 0.0),
            ],
        ),
        # G36 §5.6.5.2 and §5.6.8.2: heating opens the reheat valve and requests
        # the hot-water plant; §5.6.9: a low discharge temperature alarms.
        _case(
            "occupied heating opens the reheat valve",
            {**occupied, "TZon": 291.15, "VDis_flow": 0.094},
            [
                _op("yVal", "gt", 0.5),
                _op("yHotWatPlaReq", "gte", 1.0),
                _op("yHeaValResReq", "gte", 1.0),
                _eq("VSet_flow", 0.094, tolerance=_FLOW_TOLERANCE),
                _eq("yZonTemResReq", 0.0),
                _op("yLowTemAla", "gte", 1.0),
            ],
        ),
        # G36 §5.6.5.3: unoccupied closes the damper and zeroes the setpoints.
        _case(
            "unoccupied closes the box",
            {**occupied, "uOpeMod": UNOCCUPIED, "u1Occ": False, "VDis_flow": 0.0},
            [
                _eq("VSet_flow", 0.0),
                _op("yDam", "lte", 0.05),
                _eq("yVal", 0.0),
                _eq("VMinOA_flow", 0.0),
                _eq("VAdjAreBreZon_flow", 0.0),
                _eq("VAdjPopBreZon_flow", 0.0),
            ],
        ),
        # G36 §5.6.5.3: an open window shuts the airflow setpoint off.
        _case(
            "open window shuts airflow",
            {**occupied, "u1Win": False, "VDis_flow": 0.0},
            [_eq("VSet_flow", 0.0), _op("yDam", "lte", 0.05)],
        ),
        # G36 §5.6.9: no airflow, sensor or leak alarms while the AHU fan is off.
        # Reset requests are not suppressed by fan status (the AHU ignores them
        # while its fan is off), so they are asserted in the cooling case instead.
        _case(
            "fan off suppresses alarms",
            {**occupied, "u1Fan": False, "VDis_flow": 0.0},
            [
                _eq("yLowFloAla", 0.0),
                _eq("yFloSenAla", 0.0),
                _eq("yLeaValAla", 0.0),
                _eq("yLeaDamAla", 0.0),
            ],
        ),
    ]
    return JobSpec(
        name="Conference wing VAV-21 reheat (LBNL G36)",
        site="Example Campus",
        equipment_name="VAV_21",
        equipment_brick_class="brick:VAV",
        sequence=_sequence(controller_id),
        points=points,
        control_graph=_graph(controller_id, points),
        acceptance_tests=cases,
        notes=(
            "Demonstration job built from the retained LBNL Guideline 36 terminal-unit "
            "reheat controller. Values are SI as LBNL publishes them. No live building "
            "connection."
        ),
    )


def lbnl_multizone_ahu_demo_job() -> JobSpec:
    """A multizone VAV air handler, exactly as LBNL publishes it (ASHRAE 90.1, 62.1)."""

    controller_id = "AHUs.MultiZone.VAV.Controller"
    occupied = {
        "uAhuOpeMod": OCCUPIED,
        "uZonPreResReq": 0,
        "uZonTemResReq": 0,
        "uOutAirFra_max": 0.4,
        "VSumAdjPopBreZon_flow": 0.3,
        "VSumAdjAreBreZon_flow": 0.2,
        "VSumZonPri_flow": 3.0,
        "TOut": 300.15,
        "dpDuc": 250.0,
        "TAirSup": 291.15,
        "u1SupFan": True,
        "VAirOut_flow": 0.6,
        "TAirMix": 296.15,
        "u1SofSwiRes": True,
        "dpBui": 12.0,
    }
    points = _points(controller_id, occupied)
    cases = [
        # G36 §5.16.2 (supply air temperature reset) and §5.16.1 (static pressure
        # reset): zone requests drive the setpoint down and the fan up; §5.16.3
        # opens the cooling coil; §5.16.14 requests the chilled-water plant.
        _case(
            "zone requests pull the supply temperature down and open cooling",
            {**occupied, "uZonTemResReq": 3, "uZonPreResReq": 3, "dpDuc": 100.0, "TAirSup": 293.15},
            [
                _op("TAirSupSet", "lt", 287.15),
                _op("yCooCoi", "gt", 0.5),
                _op("yChiPlaReq", "gte", 1.0),
                _op("yChiWatResReq", "gte", 1.0),
                _op("ySupFan", "gt", 0.15),
                _eq("y1SupFan", True),
                _eq("yHeaCoi", 0.0, tolerance=_POSITION_TOLERANCE),
                _eq("yHotWatPlaReq", 0.0),
                _op("yOutDam", "gte", 0.0),
                _op("yRetDam", "gte", 0.0),
                _op("VEffAirOut_flow_min", "gte", 0.0),
                _eq("yAla", 0.0),
            ],
        ),
        # G36 §5.16.3: cold outdoor and mixed air opens the heating coil and
        # §5.16.14 requests the hot-water plant; no cooling.
        _case(
            "cold supply air opens heating",
            {**occupied, "TOut": 270.15, "TAirMix": 282.15, "TAirSup": 284.15},
            [
                _op("yHeaCoi", "gt", 0.5),
                _op("yHotWatPlaReq", "gte", 1.0),
                _op("yHotWatResReq", "gte", 1.0),
                _eq("yCooCoi", 0.0, tolerance=_POSITION_TOLERANCE),
                _eq("yChiPlaReq", 0.0),
                _eq("yAla", 0.0),
            ],
        ),
        # G36 §5.16.1 and §5.16.12: unoccupied stops the fan and relief; the
        # building pressure passes straight through.
        _case(
            "unoccupied stops the fan",
            {**occupied, "uAhuOpeMod": UNOCCUPIED, "u1SupFan": False, "TOut": 283.15},
            [
                _eq("y1SupFan", False),
                _eq("ySupFan", 0.0),
                _eq("y1RelFan", False),
                _eq("yRelFan", 0.0),
                _eq("y1RelDam", False),
                _eq("y1EneCHWPum", False),
                _eq("yMinOutDam", 0.0),
                _eq("yDpBui", 12.0),
            ],
        ),
        # G36 §5.16.12: freezing mixed air raises the freeze-protection alarm,
        # drives the heating coil fully open and escalates the plant request.
        _case(
            "freezing mixed air trips freeze protection",
            {**occupied, "TOut": 268.15, "TAirMix": 274.15, "TAirSup": 275.15},
            [
                _op("yAla", "gte", 1.0),
                _eq("yHeaCoi", 1.0, tolerance=_POSITION_TOLERANCE),
                _op("yHotWatPlaReq", "gte", 1.0),
                _eq("yCooCoi", 0.0, tolerance=_POSITION_TOLERANCE),
            ],
        ),
    ]
    return JobSpec(
        name="Central plant AHU-1 multizone VAV (LBNL G36)",
        site="Example Campus",
        equipment_name="AHU_1",
        equipment_brick_class="brick:Air_Handling_Unit",
        sequence=_sequence(controller_id),
        points=points,
        control_graph=_graph(controller_id, points),
        acceptance_tests=cases,
        notes=(
            "Demonstration job built from the retained LBNL Guideline 36 multizone VAV "
            "air-handler controller (ASHRAE 90.1 energy standard, ASHRAE 62.1 ventilation). "
            "Values are SI as LBNL publishes them. No live building connection."
        ),
    )
