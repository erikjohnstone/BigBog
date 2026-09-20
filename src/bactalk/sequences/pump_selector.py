from __future__ import annotations

from bactalk.domain import BlockKind, ControlGraph, JobSpec
from bactalk.sequences.g36_vav import GraphBuilder

REQUIRED_POINTS = {
    "SystemEnable",
    "Pump1LeadSelect",
    "Pump1Available",
    "Pump2Available",
    "Pump1Command",
    "Pump2Command",
    "NoPumpAvailableAlarm",
}


def build_two_pump_selector(job: JobSpec) -> ControlGraph:
    """Build a fail-closed duty/standby selector from explicit availability inputs."""

    points = {point.name: point for point in job.points}
    missing = sorted(REQUIRED_POINTS - set(points))
    if missing:
        raise ValueError("job is missing required two-pump selector points: " + ", ".join(missing))

    graph = GraphBuilder(job.equipment_name)
    for name in ("SystemEnable", "Pump1LeadSelect", "Pump1Available", "Pump2Available"):
        graph.add(
            name,
            BlockKind.BOOLEAN_INPUT,
            points[name].label,
            column=0,
            config={"default": points[name].default},
        )

    for name, label in (
        ("Pump2LeadSelect", "Pump 2 selected as lead"),
        ("Pump1Unavailable", "Pump 1 unavailable"),
        ("Pump2Unavailable", "Pump 2 unavailable"),
    ):
        graph.add(name, BlockKind.NOT, label, column=1)

    for index, (name, label) in enumerate(
        (
            ("Pump1LeadRequest", "Pump 1 lead request"),
            ("Pump2LeadRequest", "Pump 2 lead request"),
            ("Pump1Normal", "Pump 1 normal lead command"),
            ("Pump2Normal", "Pump 2 normal lead command"),
            ("Pump1FailoverRequest", "Pump 1 failover request"),
            ("Pump2FailoverRequest", "Pump 2 failover request"),
            ("Pump1Failover", "Pump 1 available for failover"),
            ("Pump2Failover", "Pump 2 available for failover"),
            ("NeitherPumpAvailable", "Neither pump available"),
            ("NoPumpAvailable", "Enabled with no pump available"),
        )
    ):
        graph.add(name, BlockKind.AND, label, column=2 + index // 4)

    graph.add("Pump1Final", BlockKind.OR, "Pump 1 final command", column=5)
    graph.add("Pump2Final", BlockKind.OR, "Pump 2 final command", column=5)
    for name in ("Pump1Command", "Pump2Command", "NoPumpAvailableAlarm"):
        graph.add(
            name,
            BlockKind.BOOLEAN_OUTPUT,
            points[name].label,
            column=6,
        )

    for source, target, slot in (
        ("Pump1LeadSelect", "Pump2LeadSelect", "in"),
        ("Pump1Available", "Pump1Unavailable", "in"),
        ("Pump2Available", "Pump2Unavailable", "in"),
        ("SystemEnable", "Pump1LeadRequest", "a"),
        ("Pump1LeadSelect", "Pump1LeadRequest", "b"),
        ("SystemEnable", "Pump2LeadRequest", "a"),
        ("Pump2LeadSelect", "Pump2LeadRequest", "b"),
        ("Pump1LeadRequest", "Pump1Normal", "a"),
        ("Pump1Available", "Pump1Normal", "b"),
        ("Pump2LeadRequest", "Pump2Normal", "a"),
        ("Pump2Available", "Pump2Normal", "b"),
        ("Pump2LeadRequest", "Pump1FailoverRequest", "a"),
        ("Pump2Unavailable", "Pump1FailoverRequest", "b"),
        ("Pump1LeadRequest", "Pump2FailoverRequest", "a"),
        ("Pump1Unavailable", "Pump2FailoverRequest", "b"),
        ("Pump1FailoverRequest", "Pump1Failover", "a"),
        ("Pump1Available", "Pump1Failover", "b"),
        ("Pump2FailoverRequest", "Pump2Failover", "a"),
        ("Pump2Available", "Pump2Failover", "b"),
        ("Pump1Unavailable", "NeitherPumpAvailable", "a"),
        ("Pump2Unavailable", "NeitherPumpAvailable", "b"),
        ("SystemEnable", "NoPumpAvailable", "a"),
        ("NeitherPumpAvailable", "NoPumpAvailable", "b"),
        ("Pump1Normal", "Pump1Final", "a"),
        ("Pump1Failover", "Pump1Final", "b"),
        ("Pump2Normal", "Pump2Final", "a"),
        ("Pump2Failover", "Pump2Final", "b"),
        ("Pump1Final", "Pump1Command", "in"),
        ("Pump2Final", "Pump2Command", "in"),
        ("NoPumpAvailable", "NoPumpAvailableAlarm", "in"),
    ):
        graph.wire(source, target, slot)
    return ControlGraph(
        name=graph.name,
        blocks=graph.blocks,
        links=graph.links,
        metadata={
            "sequence_family": job.sequence.family,
            "sequence_version": job.sequence.version,
            "source_pattern": "pybog two-pump rotator, rewritten as acyclic typed IR",
            "safety": "Human approval required; no live-write capability.",
        },
    )
