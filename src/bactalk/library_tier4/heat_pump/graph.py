"""Logic author: air-source heat pump in the typed IR, configurable by ``aux_heat``."""

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
    with_aux = bool(options.get("aux_heat", False))
    parameters: dict[str, float] = {}
    for requirement in requirements.requirements:
        parameters.update(requirement.parameters)
    half = parameters["deadband_K"] / 2.0
    lockout = parameters["compressorLockout_K"]
    b = GraphBuilder()
    b.column(0)
    for point in points:
        if point.role in {"command", "alarm"}:
            continue
        kind = K.NUMERIC_INPUT if point.data_type == DataType.NUMERIC else K.BOOLEAN_INPUT
        b.add(point.name, kind, point.label, "boundary", default=point.default)

    b.column(1)
    b.add("yFan", K.BOOLEAN_OUTPUT, "Indoor fan start command", "R-01 R-05")
    b.link("uOcc", "yFan", "in")
    b.gate("fan_proven", K.AND, "uOcc", "uFanSta", "Fan commanded and proven", "R-03 R-04")
    b.negate("fan_not_proven", "uFanSta", "Fan not proven", "R-02")
    b.gate("fan_missing", K.AND, "uOcc", "fan_not_proven", "Commanded, not proven", "R-02")
    b.timer("proof_timer", "fan_missing", parameters["proofDelay_s"], "Proof delay", "R-02")
    b.add("yFanAla", K.BOOLEAN_OUTPUT, "Indoor fan proof alarm", "R-02 R-05")
    b.link("proof_timer", "yFanAla", "in", "passed")

    b.column(2)
    b.gate("cool_error", K.SUBTRACT, "TZon", "TZonCooSet", "Zone minus cooling setpoint", "R-03")
    b.add(
        "cool_demand",
        K.HYSTERESIS,
        "Cooling demand",
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
        "Heating demand",
        "R-04",
        u_low=-half,
        u_high=half,
        initial=False,
    )
    b.link("heat_error", "heat_demand", "in")
    b.add(
        "outdoor_ok",
        K.HYSTERESIS,
        "Outdoor above the compressor lockout",
        "R-04",
        u_low=round(lockout - parameters["deadband_K"], 4),
        u_high=lockout,
        initial=True,
    )
    b.link("TOut", "outdoor_ok", "in")

    b.column(3)
    b.gate("cool_cond", K.AND, "fan_proven", "cool_demand", "Cooling condition", "R-03")
    b.gate("heat_wanted", K.AND, "fan_proven", "heat_demand", "Heating wanted", "R-04")
    b.gate("heat_cond", K.AND, "heat_wanted", "outdoor_ok", "Compressor heating condition", "R-04")
    b.timer("cool_timer", "cool_cond", parameters["stageDelay_s"], "Cooling stage delay", "R-03")
    b.timer("heat_timer", "heat_cond", parameters["stageDelay_s"], "Heating stage delay", "R-04")
    b.add("cool_stage", K.AND, "Cooling stage", "R-03 R-05")
    b.link("cool_timer", "cool_stage", "a", "passed")
    b.link("cool_cond", "cool_stage", "b")
    b.add("heat_stage", K.AND, "Compressor heating stage", "R-04 R-05")
    b.link("heat_timer", "heat_stage", "a", "passed")
    b.link("heat_cond", "heat_stage", "b")
    b.negate("no_heat", "heat_stage", "Heating stage off", "R-03")
    b.gate("cool_cmd", K.AND, "cool_stage", "no_heat", "Cooling with heating off", "R-03")
    b.gate("compressor", K.OR, "cool_cmd", "heat_stage", "Compressor command", "R-03 R-04")
    b.add("yCom", K.BOOLEAN_OUTPUT, "Compressor command", "R-03 R-04 R-05")
    b.link("compressor", "yCom", "in")
    b.add("yRev", K.BOOLEAN_OUTPUT, "Reversing valve (true = cooling)", "R-03 R-04")
    b.link("cool_cmd", "yRev", "in")

    if with_aux:
        b.column(4)
        b.negate("outdoor_locked", "outdoor_ok", "Outdoor below the lockout", "R-06")
        b.gate(
            "aux_lockout_cond",
            K.AND,
            "heat_wanted",
            "outdoor_locked",
            "Heating wanted, compressor locked out",
            "R-06",
        )
        b.timer(
            "aux_lockout_timer",
            "aux_lockout_cond",
            parameters["stageDelay_s"],
            "Lockout heat delay",
            "R-06",
        )
        b.add("aux_lockout", K.AND, "Auxiliary heat (lockout)", "R-06")
        b.link("aux_lockout_timer", "aux_lockout", "a", "passed")
        b.link("aux_lockout_cond", "aux_lockout", "b")
        b.add(
            "deep_demand",
            K.HYSTERESIS,
            "Zone far below the heating setpoint",
            "R-07",
            u_low=parameters["auxDrop_K"] - parameters["deadband_K"],
            u_high=parameters["auxDrop_K"],
            initial=False,
        )
        b.link("heat_error", "deep_demand", "in")
        b.gate(
            "aux_supp_cond",
            K.AND,
            "heat_cond",
            "deep_demand",
            "Heating with the zone still far below",
            "R-07",
        )
        b.timer(
            "aux_supp_timer",
            "aux_supp_cond",
            parameters["auxDelay_s"],
            "Supplemental heat delay",
            "R-07",
        )
        b.add("aux_supp", K.AND, "Auxiliary heat (supplemental)", "R-07")
        b.link("aux_supp_timer", "aux_supp", "a", "passed")
        b.link("aux_supp_cond", "aux_supp", "b")
        b.gate(
            "aux_cmd", K.OR, "aux_lockout", "aux_supp", "Auxiliary heat command", "R-06 R-07 R-05"
        )
        b.add("yAux", K.BOOLEAN_OUTPUT, "Auxiliary electric heat command", "R-06 R-07 R-05")
        b.link("aux_cmd", "yAux", "in")
    return ControlGraph(
        name="HeatPump",
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
