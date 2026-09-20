from __future__ import annotations

from bactalk.domain import BlockKind, ControlGraph, JobSpec
from bactalk.sequences.g36_vav import GraphBuilder

REQUIRED_POINTS = {
    "Enable",
    "DuctStatic",
    "DuctStaticSetpoint",
    "SupplyFanSpeedCommand",
}


def build_ahu_static_pressure_pi(job: JobSpec) -> ControlGraph:
    """Build a bounded reverse-acting duct-static PI loop."""

    points = {point.name: point for point in job.points}
    missing = sorted(REQUIRED_POINTS - set(points))
    if missing:
        raise ValueError(
            "job is missing required AHU static-pressure points: " + ", ".join(missing)
        )
    proportional = float(job.sequence.parameters.get("proportional_constant", 20.0))
    integral = float(job.sequence.parameters.get("integral_constant", 0.1))
    if proportional < 0 or integral < 0:
        raise ValueError("PI tuning constants must be non-negative")

    graph = GraphBuilder(job.equipment_name)
    graph.add(
        "Enable",
        BlockKind.BOOLEAN_INPUT,
        points["Enable"].label,
        column=0,
        config={"default": points["Enable"].default},
    )
    graph.add(
        "DuctStatic",
        BlockKind.NUMERIC_INPUT,
        points["DuctStatic"].label,
        column=0,
        config={"default": points["DuctStatic"].default},
    )
    graph.add(
        "DuctStaticSetpoint",
        BlockKind.NUMERIC_INPUT,
        points["DuctStaticSetpoint"].label,
        column=0,
        config={"default": points["DuctStaticSetpoint"].default},
    )
    graph.add(
        "ReverseAction",
        BlockKind.BOOLEAN_CONST,
        "Reverse-acting loop",
        column=0,
        config={"value": False},
    )
    graph.add(
        "DuctStaticLoop",
        BlockKind.PI_LOOP,
        "Duct static PI loop",
        column=1,
        config={
            "proportional_constant": proportional,
            "integral_constant": integral,
            "output_min": 0.0,
            "output_max": 100.0,
            "bias": 0.0,
            "disabled_output": 0.0,
        },
    )
    graph.add(
        "SupplyFanSpeedCommand",
        BlockKind.NUMERIC_OUTPUT,
        points["SupplyFanSpeedCommand"].label,
        column=2,
    )
    for source, target, slot in (
        ("Enable", "DuctStaticLoop", "enable"),
        ("DuctStatic", "DuctStaticLoop", "controlled_variable"),
        ("DuctStaticSetpoint", "DuctStaticLoop", "setpoint"),
        ("ReverseAction", "DuctStaticLoop", "direct"),
        ("DuctStaticLoop", "SupplyFanSpeedCommand", "in"),
    ):
        graph.wire(source, target, slot)
    return ControlGraph(
        name=graph.name,
        blocks=graph.blocks,
        links=graph.links,
        metadata={
            "sequence_family": job.sequence.family,
            "sequence_version": job.sequence.version,
            "parameters": {
                "proportional_constant": proportional,
                "integral_constant": integral,
            },
            "qualification": (
                "Tier-1 mathematical PI semantics; Niagara LoopPoint runtime parity pending."
            ),
            "safety": "Human approval required; no live-write capability.",
        },
    )
