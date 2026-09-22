"""Logic author: duty/standby pump pair in the typed IR (fail-closed)."""

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
    b.negate("lead_is_1", "uLead2", "Pump 1 selected as lead", "R-01 R-02")
    b.negate("pum1_unavailable", "uPum1Ava", "Pump 1 unavailable", "R-03 R-04")
    b.negate("pum2_unavailable", "uPum2Ava", "Pump 2 unavailable", "R-04")
    # a pump is wanted when it leads, or when the other pump (the lead) is unavailable
    b.gate("pum1_lead", K.AND, "lead_is_1", "uPum1Ava", "Pump 1 leads and is available", "R-01")
    b.gate("pum2_lead", K.AND, "uLead2", "uPum2Ava", "Pump 2 leads and is available", "R-02")
    b.gate("pum2_failover", K.AND, "lead_is_1", "pum1_unavailable", "Lead 1 unavailable", "R-03")
    b.gate("pum1_failover", K.AND, "uLead2", "pum2_unavailable", "Lead 2 unavailable", "R-03")
    b.column(2)
    b.gate("pum2_standby", K.AND, "pum2_failover", "uPum2Ava", "Standby 2 available", "R-03")
    b.gate("pum1_standby", K.AND, "pum1_failover", "uPum1Ava", "Standby 1 available", "R-03")
    b.gate("pum1_wanted", K.OR, "pum1_lead", "pum1_standby", "Pump 1 wanted", "R-01 R-03")
    b.gate("pum2_wanted", K.OR, "pum2_lead", "pum2_standby", "Pump 2 wanted", "R-02 R-03")
    b.gate("pum1_cmd", K.AND, "uEna", "pum1_wanted", "Pump 1 command", "R-01 R-06")
    b.gate("pum2_cmd", K.AND, "uEna", "pum2_wanted", "Pump 2 command", "R-02 R-06")
    b.add("yPum1", K.BOOLEAN_OUTPUT, "Pump 1 start command", "R-01")
    b.add("yPum2", K.BOOLEAN_OUTPUT, "Pump 2 start command", "R-02")
    b.link("pum1_cmd", "yPum1", "in")
    b.link("pum2_cmd", "yPum2", "in")
    b.column(3)
    b.gate(
        "none_available", K.AND, "pum1_unavailable", "pum2_unavailable", "Neither available", "R-04"
    )
    b.gate("no_pump_alarm", K.AND, "uEna", "none_available", "Enabled, no pump", "R-04 R-06")
    b.add("yNoPumAla", K.BOOLEAN_OUTPUT, "No pump available alarm", "R-04")
    b.link("no_pump_alarm", "yNoPumAla", "in")
    b.negate("pum1_not_proven", "uPum1Sta", "Pump 1 not proven", "R-05")
    b.negate("pum2_not_proven", "uPum2Sta", "Pump 2 not proven", "R-07")
    b.gate(
        "pum1_missing", K.AND, "pum1_cmd", "pum1_not_proven", "Pump 1 commanded, not proven", "R-05"
    )
    b.gate(
        "pum2_missing", K.AND, "pum2_cmd", "pum2_not_proven", "Pump 2 commanded, not proven", "R-05"
    )
    b.timer("pum1_fail", "pum1_missing", parameters["proofDelay_s"], "Pump 1 proof delay", "R-05")
    b.timer("pum2_fail", "pum2_missing", parameters["proofDelay_s"], "Pump 2 proof delay", "R-07")
    b.add("pump_failure", K.OR, "Any pump failed", "R-05 R-06 R-07")
    b.link("pum1_fail", "pump_failure", "a", "passed")
    b.link("pum2_fail", "pump_failure", "b", "passed")
    b.add("yPumFaiAla", K.BOOLEAN_OUTPUT, "Pump failure alarm", "R-05")
    b.link("pump_failure", "yPumFaiAla", "in")
    return ControlGraph(
        name="PumpDutyStandby",
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
