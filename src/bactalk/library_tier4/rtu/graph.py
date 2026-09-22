"""Logic author: packaged rooftop unit in the typed IR, configurable by ``economizer``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from bactalk.domain import BlockKind, ControlGraph, DataType, PointSpec
from bactalk.protocol.authoring import GraphBuilder
from bactalk.protocol.requirements import RequirementSet

K = BlockKind


def build_graph(
    requirements: RequirementSet, points: list[PointSpec], options: Mapping[str, Any]
) -> ControlGraph:
    with_economizer = bool(options.get("economizer", False))
    parameters: dict[str, float] = {}
    for requirement in requirements.requirements:
        parameters.update(requirement.parameters)
    half = parameters["deadband_K"] / 2.0
    b = GraphBuilder()
    b.column(0)
    for point in points:
        if point.role in {"command", "alarm"}:
            continue
        kind = K.NUMERIC_INPUT if point.data_type == DataType.NUMERIC else K.BOOLEAN_INPUT
        b.add(point.name, kind, point.label, "boundary", default=point.default)

    # --- fan ---------------------------------------------------------------------------
    b.column(1)
    b.add("yFan", K.BOOLEAN_OUTPUT, "Supply fan start command", "R-01 R-05")
    b.link("uOcc", "yFan", "in")
    b.gate("fan_proven", K.AND, "uOcc", "uFanSta", "Fan commanded and proven", "R-03 R-04 R-06")
    b.negate("fan_not_proven", "uFanSta", "Fan not proven", "R-02")
    b.gate("fan_missing", K.AND, "uOcc", "fan_not_proven", "Commanded, not proven", "R-02")
    b.timer("proof_timer", "fan_missing", parameters["proofDelay_s"], "Proof delay", "R-02")
    b.add("yFanAla", K.BOOLEAN_OUTPUT, "Supply fan proof alarm", "R-02 R-05")
    b.link("proof_timer", "yFanAla", "in", "passed")

    # --- cooling and heating stages (hysteresis around the live setpoints) -------------
    b.column(2)
    b.const("half_deadband", half, "Half deadband", "R-03 R-04")
    b.gate("cool_error", K.SUBTRACT, "TZon", "TZonCooSet", "Zone minus cooling setpoint", "R-03")
    b.add(
        "cool_demand",
        K.HYSTERESIS,
        "Cooling demand (on above +½ deadband, off below −½)",
        "R-03",
        u_low=-half,
        u_high=half,
        initial=False,
    )
    b.link("cool_error", "cool_demand", "in")
    b.gate("heat_error", K.SUBTRACT, "TZonHeaSet", "TZon", "Heating setpoint minus zone", "R-04")
    b.add(
        "heat_demand",
        K.HYSTERESIS,
        "Heating demand (on above +½ deadband, off below −½)",
        "R-04",
        u_low=-half,
        u_high=half,
        initial=False,
    )
    b.link("heat_error", "heat_demand", "in")
    b.column(3)
    b.gate("cool_cond", K.AND, "fan_proven", "cool_demand", "Cooling stage condition", "R-03")
    b.gate("heat_cond", K.AND, "fan_proven", "heat_demand", "Heating stage condition", "R-04")
    b.timer("cool_timer", "cool_cond", parameters["stageDelay_s"], "Cooling stage delay", "R-03")
    b.timer("heat_timer", "heat_cond", parameters["stageDelay_s"], "Heating stage delay", "R-04")
    # the stage stays on while its demand holds (hysteresis), drops with the demand or the fan
    b.add("cool_stage", K.AND, "Cooling stage", "R-03 R-05")
    b.link("cool_timer", "cool_stage", "a", "passed")
    b.link("cool_cond", "cool_stage", "b")
    b.add("heat_stage", K.AND, "Heating stage", "R-04 R-05")
    b.link("heat_timer", "heat_stage", "a", "passed")
    b.link("heat_cond", "heat_stage", "b")
    b.negate("no_heat", "heat_stage", "Heating stage off", "R-03")
    b.gate("cool_cmd", K.AND, "cool_stage", "no_heat", "Cooling with heating off", "R-03")
    b.add("yCoo", K.BOOLEAN_OUTPUT, "Cooling stage 1 command", "R-03 R-05")
    b.add("yHea", K.BOOLEAN_OUTPUT, "Heating stage 1 command", "R-04 R-05")
    b.link("cool_cmd", "yCoo", "in")
    b.link("heat_stage", "yHea", "in")

    # --- outdoor air damper --------------------------------------------------------------
    b.column(4)
    b.const("damper_closed", 0.0, "Damper closed", "R-05")
    b.const("damper_minimum", parameters["minOutdoorAir"], "Minimum outdoor air", "R-06")
    if with_economizer:
        limit = parameters["economizerHighLimit_K"]
        b.add(
            "outdoor_warm",
            K.HYSTERESIS,
            "Outdoor above the economizer high limit",
            "R-06 R-07",
            u_low=limit,
            u_high=round(limit + 1.0, 4),
            initial=False,
        )
        b.link("TOut", "outdoor_warm", "in")
        b.negate("outdoor_cool", "outdoor_warm", "Outdoor below the high limit", "R-07")
        b.gate(
            "free_cooling", K.AND, "outdoor_cool", "cool_demand", "Free cooling available", "R-07"
        )
        b.const("damper_open", 1.0, "Damper fully open", "R-07")
        b.add(
            "economizer_position",
            K.NUMERIC_SWITCH,
            "Full open on free cooling, else minimum",
            "R-06 R-07",
        )
        b.link("free_cooling", "economizer_position", "selector")
        b.link("damper_open", "economizer_position", "when_true")
        b.link("damper_minimum", "economizer_position", "when_false")
        running_position = "economizer_position"
    else:
        running_position = "damper_minimum"
    b.add("damper_position", K.NUMERIC_SWITCH, "Damper position with the fan proven", "R-05 R-06")
    b.link("fan_proven", "damper_position", "selector")
    b.link(running_position, "damper_position", "when_true")
    b.link("damper_closed", "damper_position", "when_false")
    b.add("yOutDam", K.NUMERIC_OUTPUT, "Outdoor air damper position", "R-05 R-06")
    b.link("damper_position", "yOutDam", "in")
    return ControlGraph(
        name="RooftopUnit",
        blocks=b.blocks,
        links=b.links,
        metadata={
            "sequence_id": requirements.sequence_id,
            "requirements_digest": requirements.digest(),
            "options": dict(options),
            "traceability": {key: sorted(set(value)) for key, value in b.trace.items()},
            "source": "docs/library-authoring.md (Tier 4, logic author)",
        },
    )


__all__ = ["build_graph"]
