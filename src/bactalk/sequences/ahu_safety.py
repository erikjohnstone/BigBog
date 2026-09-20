from __future__ import annotations

from bactalk.domain import BlockKind, ControlGraph, JobSpec
from bactalk.sequences.g36_vav import GraphBuilder

REQUIRED_POINTS = {
    "Occupied",
    "DuctStatic",
    "DuctHighLimit",
    "DischargeAirTemp",
    "DischargeAirTempSetpoint",
    "SupplyFanCommand",
    "CoolingValveCommand",
    "DuctPressureAlarm",
}


def build_ahu_safety_cooling(job: JobSpec) -> ControlGraph:
    """Build a bounded AHU fan-safety and discharge-cooling sequence."""

    points = {point.name: point for point in job.points}
    missing = sorted(REQUIRED_POINTS - set(points))
    if missing:
        raise ValueError(f"job is missing required AHU points: {', '.join(missing)}")
    gain = float(job.sequence.parameters.get("cooling_gain", 20.0))
    if gain <= 0:
        raise ValueError("cooling_gain must be greater than zero")

    graph = GraphBuilder(job.equipment_name)
    for point_id in (
        "Occupied",
        "DuctStatic",
        "DuctHighLimit",
        "DischargeAirTemp",
        "DischargeAirTempSetpoint",
    ):
        point = points[point_id]
        kind = (
            BlockKind.BOOLEAN_INPUT
            if point.data_type.value == "boolean"
            else BlockKind.NUMERIC_INPUT
        )
        graph.add(
            point_id,
            kind,
            point.label,
            column=0,
            config={"default": point.default},
        )
    graph.add("Zero", BlockKind.NUMERIC_CONST, "Zero percent", column=0, config={"value": 0.0})
    graph.add(
        "Hundred",
        BlockKind.NUMERIC_CONST,
        "One hundred percent",
        column=0,
        config={"value": 100.0},
    )
    graph.add(
        "CoolingGain",
        BlockKind.NUMERIC_CONST,
        "Cooling gain",
        column=0,
        config={"value": gain},
    )
    graph.add("PressureSafe", BlockKind.LESS_THAN, "Pressure below limit", column=1)
    graph.add(
        "PressureHigh",
        BlockKind.GREATER_THAN_OR_EQUAL,
        "Pressure at high limit",
        column=1,
    )
    graph.add("CoolingError", BlockKind.SUBTRACT, "Discharge cooling error", column=1)
    graph.add("FanEnable", BlockKind.AND, "Occupied and pressure safe", column=2)
    graph.add("OccupiedPressureAlarm", BlockKind.AND, "Occupied pressure alarm", column=2)
    graph.add("CoolingRaw", BlockKind.MULTIPLY, "Scale cooling command", column=2)
    graph.add("CoolingLowClamp", BlockKind.MAXIMUM, "Clamp cooling low", column=3)
    graph.add("CoolingClamped", BlockKind.MINIMUM, "Clamp cooling high", column=4)
    graph.add("CoolingEnabled", BlockKind.NUMERIC_SWITCH, "Occupancy enable", column=5)
    graph.add(
        "SupplyFanCommand",
        BlockKind.BOOLEAN_OUTPUT,
        points["SupplyFanCommand"].label,
        column=6,
    )
    graph.add(
        "DuctPressureAlarm",
        BlockKind.BOOLEAN_OUTPUT,
        points["DuctPressureAlarm"].label,
        column=6,
    )
    graph.add(
        "CoolingValveCommand",
        BlockKind.NUMERIC_OUTPUT,
        points["CoolingValveCommand"].label,
        column=6,
    )

    for source, target, slot in (
        ("DuctStatic", "PressureSafe", "a"),
        ("DuctHighLimit", "PressureSafe", "b"),
        ("DuctStatic", "PressureHigh", "a"),
        ("DuctHighLimit", "PressureHigh", "b"),
        ("Occupied", "FanEnable", "a"),
        ("PressureSafe", "FanEnable", "b"),
        ("Occupied", "OccupiedPressureAlarm", "a"),
        ("PressureHigh", "OccupiedPressureAlarm", "b"),
        ("DischargeAirTemp", "CoolingError", "a"),
        ("DischargeAirTempSetpoint", "CoolingError", "b"),
        ("CoolingError", "CoolingRaw", "a"),
        ("CoolingGain", "CoolingRaw", "b"),
        ("CoolingRaw", "CoolingLowClamp", "a"),
        ("Zero", "CoolingLowClamp", "b"),
        ("CoolingLowClamp", "CoolingClamped", "a"),
        ("Hundred", "CoolingClamped", "b"),
        ("Occupied", "CoolingEnabled", "selector"),
        ("CoolingClamped", "CoolingEnabled", "when_true"),
        ("Zero", "CoolingEnabled", "when_false"),
        ("FanEnable", "SupplyFanCommand", "in"),
        ("OccupiedPressureAlarm", "DuctPressureAlarm", "in"),
        ("CoolingEnabled", "CoolingValveCommand", "in"),
    ):
        graph.wire(source, target, slot)
    return ControlGraph(
        name=graph.name,
        blocks=graph.blocks,
        links=graph.links,
        metadata={
            "sequence_family": job.sequence.family,
            "sequence_version": job.sequence.version,
            "parameters": {"cooling_gain": gain},
            "safety": "Human approval required; no live-write capability.",
        },
    )
