"""Logic author: dedicated outdoor air system in the typed IR, configurable by
``energy_recovery``."""

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
    with_erv = bool(options.get("energy_recovery", False))
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

    b.column(1)
    b.add("ySupFan", K.BOOLEAN_OUTPUT, "Supply fan start command", "R-01 R-06")
    b.link("uOcc", "ySupFan", "in")
    b.gate(
        "fan_proven",
        K.AND,
        "uOcc",
        "uSupFanSta",
        "Supply fan commanded and proven",
        "R-03 R-04 R-05",
    )
    b.negate("fan_not_proven", "uSupFanSta", "Supply fan not proven", "R-02")
    b.gate("fan_missing", K.AND, "uOcc", "fan_not_proven", "Commanded, not proven", "R-02")
    b.timer("proof_timer", "fan_missing", parameters["proofDelay_s"], "Proof delay", "R-02")
    b.add("yFanAla", K.BOOLEAN_OUTPUT, "Fan proof alarm", "R-02 R-06")
    b.link("proof_timer", "yFanAla", "in", "passed")

    # --- supply temperature: two proportional loops around a deadband ---------------------
    b.column(2)
    b.const("half_deadband", half, "Half deadband", "R-03 R-04 R-05")
    b.gate("heat_setpoint", K.SUBTRACT, "TSupSet", "half_deadband", "Heating setpoint", "R-03 R-05")
    b.gate("cool_setpoint", K.ADD, "TSupSet", "half_deadband", "Cooling setpoint", "R-04 R-05")
    b.bconst("no_reset", False, "Loops never reset", "R-03 R-04")
    gain = parameters["loopGain_perK"]
    b.add(
        "heat_loop",
        K.PID_WITH_RESET,
        "Heating valve loop (P, reverse acting)",
        "R-03 R-05",
        controller_type="P",
        k=gain,
        r=1.0,
        y_min=0.0,
        y_max=1.0,
        reverse_acting=True,
    )
    b.link("heat_setpoint", "heat_loop", "setpoint")
    b.link("TSup", "heat_loop", "measurement")
    b.link("no_reset", "heat_loop", "trigger")
    b.add(
        "cool_loop",
        K.PID_WITH_RESET,
        "Cooling valve loop (P, direct acting)",
        "R-04 R-05",
        controller_type="P",
        k=gain,
        r=1.0,
        y_min=0.0,
        y_max=1.0,
        reverse_acting=False,
    )
    b.link("cool_setpoint", "cool_loop", "setpoint")
    b.link("TSup", "cool_loop", "measurement")
    b.link("no_reset", "cool_loop", "trigger")
    b.column(3)
    b.const("closed", 0.0, "Valve closed", "R-06")
    for name, loop, label, reqs in (
        ("yHeaVal", "heat_loop", "Heating coil valve position", "R-03 R-05 R-06"),
        ("yCooVal", "cool_loop", "Cooling coil valve position", "R-04 R-05 R-06"),
    ):
        b.add(f"{loop}_gated", K.NUMERIC_SWITCH, f"{label} with the fan proven", reqs)
        b.link("fan_proven", f"{loop}_gated", "selector")
        b.link(loop, f"{loop}_gated", "when_true")
        b.link("closed", f"{loop}_gated", "when_false")
        b.add(name, K.NUMERIC_OUTPUT, label, reqs)
        b.link(f"{loop}_gated", name, "in")

    if with_erv:
        b.column(4)
        b.add("yExhFan", K.BOOLEAN_OUTPUT, "Exhaust fan start command", "R-07 R-06")
        b.link("uOcc", "yExhFan", "in")
        b.gate(
            "both_fans_proven", K.AND, "fan_proven", "uExhFanSta", "Both fans proven", "R-08 R-09"
        )
        cold, warm = parameters["ervColdLimit_K"], parameters["ervWarmLimit_K"]
        deadband = parameters["deadband_K"]
        b.add(
            "outdoor_mild_low",
            K.HYSTERESIS,
            "Outdoor above the cold limit",
            "R-08",
            u_low=cold,
            u_high=round(cold + deadband, 4),
            initial=True,
        )
        b.link("TOut", "outdoor_mild_low", "in")
        b.negate("outdoor_cold", "outdoor_mild_low", "Outdoor below the cold limit", "R-08")
        b.add(
            "outdoor_warm",
            K.HYSTERESIS,
            "Outdoor above the warm limit",
            "R-09",
            u_low=round(warm - deadband, 4),
            u_high=warm,
            initial=False,
        )
        b.link("TOut", "outdoor_warm", "in")
        b.gate(
            "recovery_useful", K.OR, "outdoor_cold", "outdoor_warm", "Recovery useful", "R-08 R-09"
        )
        b.gate(
            "wheel_cmd",
            K.AND,
            "both_fans_proven",
            "recovery_useful",
            "Wheel enable",
            "R-08 R-09 R-06",
        )
        b.add("yWhe", K.BOOLEAN_OUTPUT, "Energy recovery wheel enable", "R-08 R-09 R-06")
        b.link("wheel_cmd", "yWhe", "in")
    return ControlGraph(
        name="DedicatedOutdoorAir",
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
