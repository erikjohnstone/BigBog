"""Logic author: the exhaust fan in the typed IR, configurable by ``isolation_damper``."""

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
    with_damper = bool(options.get("isolation_damper", False))
    parameters: dict[str, float] = {}
    for requirement in requirements.requirements:
        parameters.update(requirement.parameters)
    b = GraphBuilder()
    b.column(0)
    for point in points:
        if point.role in {"command", "alarm"}:
            continue
        kind = K.NUMERIC_INPUT if point.data_type == DataType.NUMERIC else K.BOOLEAN_INPUT
        b.add(point.name, kind, point.label, "boundary", default=point.default)
    b.column(1)
    if with_damper:
        b.add("yDam", K.BOOLEAN_OUTPUT, "Isolation damper open command", "R-05 R-03")
        b.link("uEna", "yDam", "in")
        b.negate("damper_not_proven", "uDamOpe", "Damper not proven open", "R-04")
        b.gate(
            "waiting_for_damper",
            K.AND,
            "uEna",
            "damper_not_proven",
            "Enabled, damper not proven",
            "R-04",
        )
        b.timer(
            "damper_timeout",
            "waiting_for_damper",
            parameters["damperTimeout_s"],
            "Damper timeout",
            "R-04",
        )
        b.add("start_permitted", K.OR, "Damper proven or timed out", "R-01 R-04")
        b.link("uDamOpe", "start_permitted", "a")
        b.link("damper_timeout", "start_permitted", "b", "passed")
        b.gate("fan_cmd", K.AND, "uEna", "start_permitted", "Fan command", "R-01 R-03")
        command = "fan_cmd"
    else:
        command = "uEna"
    b.add("yFan", K.BOOLEAN_OUTPUT, "Fan start command", "R-01 R-03")
    b.link(command, "yFan", "in")
    b.column(2)
    b.negate("fan_not_proven", "uFanSta", "Fan not proven", "R-02")
    b.gate("fan_missing", K.AND, command, "fan_not_proven", "Commanded, not proven", "R-02")
    b.timer("proof_timer", "fan_missing", parameters["proofDelay_s"], "Proof delay", "R-02")
    b.add("yFanAla", K.BOOLEAN_OUTPUT, "Fan proof alarm", "R-02 R-03")
    b.link("proof_timer", "yFanAla", "in", "passed")
    return ControlGraph(
        name="ExhaustFan",
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
