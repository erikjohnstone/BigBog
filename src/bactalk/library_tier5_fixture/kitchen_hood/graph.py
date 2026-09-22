"""Logic author (fixture stand-in for the AI draft): kitchen hood interlock, every block
traced to the specification paragraph through its requirement."""

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
    b.add("yHooFan", K.BOOLEAN_OUTPUT, "Hood exhaust fan start", "R-01 R-04")
    b.link("uHooSw", "yHooFan", "in")
    b.gate("makeup_cmd", K.AND, "uHooSw", "uAhuFan", "Hood on and AHU running", "R-02 R-04")
    b.add("yMakFan", K.BOOLEAN_OUTPUT, "Makeup air fan start", "R-02 R-04")
    b.add("yMakDam", K.BOOLEAN_OUTPUT, "Makeup air damper open", "R-02 R-04")
    b.link("makeup_cmd", "yMakFan", "in")
    b.link("makeup_cmd", "yMakDam", "in")
    b.column(2)
    b.negate("makeup_not_proven", "uMakFanSta", "Makeup fan not proven", "R-03")
    b.gate(
        "makeup_missing", K.AND, "makeup_cmd", "makeup_not_proven", "Commanded, not proven", "R-03"
    )
    b.timer("proof_timer", "makeup_missing", parameters["proofDelay_s"], "Proof delay", "R-03")
    b.add("yMakAla", K.BOOLEAN_OUTPUT, "Makeup air fan failure alarm", "R-03 R-04")
    b.link("proof_timer", "yMakAla", "in", "passed")
    return ControlGraph(
        name="KitchenHoodInterlock",
        blocks=b.blocks,
        links=b.links,
        metadata={
            "sequence_id": requirements.sequence_id,
            "requirements_digest": requirements.digest(),
            "options": dict(options),
            "traceability": {key: sorted(set(value)) for key, value in b.trace.items()},
            "citations": {
                requirement.id: (
                    f"{requirement.citation.section} {requirement.citation.paragraph or ''}"
                ).strip()
                for requirement in requirements.requirements
            },
            "source": "Tier 5 fixture (custom, job-specific)",
        },
    )


__all__ = ["build_graph"]
