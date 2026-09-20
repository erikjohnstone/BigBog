from __future__ import annotations

from bactalk.domain import BlockKind, ControlGraph, JobSpec
from bactalk.sequences.g36_vav import GraphBuilder

REQUIRED_POINTS = {"Enable", "FanStatus", "FanCommand", "FanProofAlarm"}


def build_exhaust_fan_proof(job: JobSpec) -> ControlGraph:
    """Build an exhaust fan command with delayed proof-of-flow alarm."""

    points = {point.name: point for point in job.points}
    missing = sorted(REQUIRED_POINTS - set(points))
    if missing:
        raise ValueError(f"job is missing required exhaust fan points: {', '.join(missing)}")
    delay = float(job.sequence.parameters.get("proof_delay_seconds", 60.0))
    if delay < 0:
        raise ValueError("proof_delay_seconds must be non-negative")

    graph = GraphBuilder(job.equipment_name)
    graph.add(
        "Enable",
        BlockKind.BOOLEAN_INPUT,
        points["Enable"].label,
        column=0,
        config={"default": points["Enable"].default},
    )
    graph.add(
        "FanStatus",
        BlockKind.BOOLEAN_INPUT,
        points["FanStatus"].label,
        column=0,
        config={"default": points["FanStatus"].default},
    )
    graph.add("StatusNotProven", BlockKind.NOT, "Fan status not proven", column=1)
    graph.add("ProofFailure", BlockKind.AND, "Enabled without proof", column=2)
    graph.add(
        "ProofDelay",
        BlockKind.BOOLEAN_DELAY,
        "Proof alarm delay",
        column=3,
        config={"on_delay_seconds": delay, "off_delay_seconds": 0.0},
    )
    graph.add(
        "FanCommand",
        BlockKind.BOOLEAN_OUTPUT,
        points["FanCommand"].label,
        column=4,
    )
    graph.add(
        "FanProofAlarm",
        BlockKind.BOOLEAN_OUTPUT,
        points["FanProofAlarm"].label,
        column=4,
    )
    for source, target, slot in (
        ("FanStatus", "StatusNotProven", "in"),
        ("Enable", "ProofFailure", "a"),
        ("StatusNotProven", "ProofFailure", "b"),
        ("ProofFailure", "ProofDelay", "in"),
        ("Enable", "FanCommand", "in"),
        ("ProofDelay", "FanProofAlarm", "in"),
    ):
        graph.wire(source, target, slot)
    return ControlGraph(
        name=graph.name,
        blocks=graph.blocks,
        links=graph.links,
        metadata={
            "sequence_family": job.sequence.family,
            "sequence_version": job.sequence.version,
            "parameters": {"proof_delay_seconds": delay},
            "safety": "Human approval required; no live-write capability.",
        },
    )
