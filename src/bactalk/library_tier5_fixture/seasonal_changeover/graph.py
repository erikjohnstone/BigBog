"""Logic author (fixture stand-in for the AI draft): seasonal changeover."""

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
    heat, cool, deadband = (
        parameters["heatingLimit_K"],
        parameters["coolingLimit_K"],
        parameters["deadband_K"],
    )
    delay = parameters["changeoverDelay_s"]
    b = GraphBuilder()
    b.column(0)
    for point in points:
        if point.role in {"command", "alarm"}:
            continue
        kind = K.NUMERIC_INPUT if point.data_type == DataType.NUMERIC else K.BOOLEAN_INPUT
        b.add(point.name, kind, point.label, "boundary", default=point.default)
    b.column(1)
    b.add(
        "outdoor_mild_low",
        K.HYSTERESIS,
        "Outdoor above the heating limit",
        "R-01",
        u_low=heat,
        u_high=round(heat + deadband, 4),
        initial=False,
    )
    b.link("TOut", "outdoor_mild_low", "in")
    b.negate("outdoor_cold", "outdoor_mild_low", "Outdoor below the heating limit", "R-01")
    b.add(
        "outdoor_warm",
        K.HYSTERESIS,
        "Outdoor above the cooling limit",
        "R-02",
        u_low=round(cool - deadband, 4),
        u_high=cool,
        initial=False,
    )
    b.link("TOut", "outdoor_warm", "in")
    b.add(
        "heat_auto",
        K.BOOLEAN_DELAY,
        "Heating season (30 min on and off)",
        "R-01",
        on_delay_seconds=delay,
        off_delay_seconds=delay,
    )
    b.link("outdoor_cold", "heat_auto", "in")
    b.add(
        "cool_auto",
        K.BOOLEAN_DELAY,
        "Cooling season (30 min on and off)",
        "R-02",
        on_delay_seconds=delay,
        off_delay_seconds=delay,
    )
    b.link("outdoor_warm", "cool_auto", "in")
    b.column(2)
    b.negate("no_cool_override", "uCooOvr", "No cooling override", "R-03 R-04")
    b.negate("no_heat_override", "uHeaOvr", "No heating override", "R-04")
    b.negate("not_heating_auto", "heat_auto", "Not in automatic heating", "R-02")
    b.gate(
        "heat_auto_allowed",
        K.AND,
        "heat_auto",
        "no_cool_override",
        "Automatic heating, no cooling override",
        "R-01 R-04",
    )
    b.gate("heating", K.OR, "uHeaOvr", "heat_auto_allowed", "Heating season", "R-01 R-03")
    b.gate(
        "cool_auto_allowed",
        K.AND,
        "cool_auto",
        "not_heating_auto",
        "Automatic cooling, no automatic heating",
        "R-02",
    )
    b.gate("cool_wanted", K.OR, "uCooOvr", "cool_auto_allowed", "Cooling wanted", "R-02 R-04")
    b.gate("cooling", K.AND, "cool_wanted", "no_heat_override", "Cooling season", "R-02 R-04")
    b.add("yHeaSea", K.BOOLEAN_OUTPUT, "Heating season", "R-01 R-03")
    b.add("yCooSea", K.BOOLEAN_OUTPUT, "Cooling season", "R-02 R-04")
    b.link("heating", "yHeaSea", "in")
    b.link("cooling", "yCooSea", "in")
    return ControlGraph(
        name="SeasonalChangeover",
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
