from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bactalk.domain import Block, BlockKind, ControlGraph, JobSpec, Link

REQUIRED_POINTS = {
    "ZoneTemp",
    "CoolingSetpoint",
    "HeatingSetpoint",
    "Occupied",
    "DamperCommand",
    "ValveCommand",
    "CoolingDemand",
    "HeatingDemand",
    "HighZoneTempAlarm",
}


@dataclass
class GraphBuilder:
    name: str
    blocks: list[Block] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    _column_rows: dict[int, int] = field(default_factory=dict)

    def add(
        self,
        block_id: str,
        kind: BlockKind,
        label: str,
        *,
        column: int,
        config: dict[str, Any] | None = None,
    ) -> str:
        row = self._column_rows.get(column, 0)
        self._column_rows[column] = row + 1
        self.blocks.append(
            Block(
                id=block_id,
                kind=kind,
                label=label,
                config=config or {},
                x=column * 230 + 40,
                y=row * 92 + 50,
            )
        )
        return block_id

    def wire(self, source: str, target: str, slot: str) -> None:
        self.links.append(Link(source=source, target=target, target_slot=slot))


def build_g36_vav_reheat(job: JobSpec) -> ControlGraph:
    """Compile the first supported sequence family to the typed BACTalk IR.

    This is intentionally a small, auditable subset: occupied heating/cooling
    demand, minimum airflow, reheat, and a high-zone-temperature alarm. It is
    not represented as full Guideline 36 compliance.
    """

    point_names = {point.name for point in job.points}
    missing = sorted(REQUIRED_POINTS - point_names)
    if missing:
        raise ValueError(f"job is missing required points: {', '.join(missing)}")

    parameters = {
        "loop_span_f": 3.0,
        "minimum_damper_pct": 20.0,
        "high_zone_temp_f": 80.0,
        **job.sequence.parameters,
    }
    span = float(parameters["loop_span_f"])
    if span <= 0:
        raise ValueError("loop_span_f must be greater than zero")
    minimum_damper = float(parameters["minimum_damper_pct"])
    if not 0.0 <= minimum_damper <= 100.0:
        raise ValueError("minimum_damper_pct must be between 0 and 100")

    graph = GraphBuilder(job.equipment_name)

    for point_id, kind, label, default in (
        ("ZoneTemp", BlockKind.NUMERIC_INPUT, "Zone temperature", 72.0),
        ("CoolingSetpoint", BlockKind.NUMERIC_INPUT, "Cooling setpoint", 74.0),
        ("HeatingSetpoint", BlockKind.NUMERIC_INPUT, "Heating setpoint", 70.0),
        ("Occupied", BlockKind.BOOLEAN_INPUT, "Occupancy command", True),
    ):
        point = next(point for point in job.points if point.name == point_id)
        graph.add(
            point_id,
            kind,
            label,
            column=0,
            config={"default": point.default if point.default is not None else default},
        )

    graph.add("Zero", BlockKind.NUMERIC_CONST, "0%", column=0, config={"value": 0.0})
    graph.add("Full", BlockKind.NUMERIC_CONST, "100%", column=0, config={"value": 100.0})
    graph.add(
        "DemandGain",
        BlockKind.NUMERIC_CONST,
        "Demand gain",
        column=0,
        config={"value": 100.0 / span},
    )
    graph.add(
        "MinimumDamper",
        BlockKind.NUMERIC_CONST,
        "Minimum occupied damper",
        column=0,
        config={"value": minimum_damper},
    )
    graph.add(
        "HighTempLimit",
        BlockKind.NUMERIC_CONST,
        "High zone temperature limit",
        column=0,
        config={"value": float(parameters["high_zone_temp_f"])},
    )

    graph.add("CoolingError", BlockKind.SUBTRACT, "Cooling error", column=1)
    graph.wire("ZoneTemp", "CoolingError", "a")
    graph.wire("CoolingSetpoint", "CoolingError", "b")
    graph.add("CoolingScaled", BlockKind.MULTIPLY, "Scale cooling demand", column=2)
    graph.wire("CoolingError", "CoolingScaled", "a")
    graph.wire("DemandGain", "CoolingScaled", "b")
    graph.add("CoolingNonNegative", BlockKind.MAXIMUM, "Clamp cooling low", column=3)
    graph.wire("CoolingScaled", "CoolingNonNegative", "a")
    graph.wire("Zero", "CoolingNonNegative", "b")
    graph.add("CoolingClamped", BlockKind.MINIMUM, "Clamp cooling high", column=4)
    graph.wire("CoolingNonNegative", "CoolingClamped", "a")
    graph.wire("Full", "CoolingClamped", "b")

    graph.add("HeatingError", BlockKind.SUBTRACT, "Heating error", column=1)
    graph.wire("HeatingSetpoint", "HeatingError", "a")
    graph.wire("ZoneTemp", "HeatingError", "b")
    graph.add("HeatingScaled", BlockKind.MULTIPLY, "Scale heating demand", column=2)
    graph.wire("HeatingError", "HeatingScaled", "a")
    graph.wire("DemandGain", "HeatingScaled", "b")
    graph.add("HeatingNonNegative", BlockKind.MAXIMUM, "Clamp heating low", column=3)
    graph.wire("HeatingScaled", "HeatingNonNegative", "a")
    graph.wire("Zero", "HeatingNonNegative", "b")
    graph.add("HeatingClamped", BlockKind.MINIMUM, "Clamp heating high", column=4)
    graph.wire("HeatingNonNegative", "HeatingClamped", "a")
    graph.wire("Full", "HeatingClamped", "b")

    graph.add("OccupiedCooling", BlockKind.NUMERIC_SWITCH, "Enable cooling demand", column=5)
    graph.wire("Occupied", "OccupiedCooling", "selector")
    graph.wire("CoolingClamped", "OccupiedCooling", "when_true")
    graph.wire("Zero", "OccupiedCooling", "when_false")
    graph.add("OccupiedHeating", BlockKind.NUMERIC_SWITCH, "Enable heating demand", column=5)
    graph.wire("Occupied", "OccupiedHeating", "selector")
    graph.wire("HeatingClamped", "OccupiedHeating", "when_true")
    graph.wire("Zero", "OccupiedHeating", "when_false")

    graph.add("OccupiedDamperMinimum", BlockKind.MAXIMUM, "Apply occupied minimum", column=5)
    graph.wire("CoolingClamped", "OccupiedDamperMinimum", "a")
    graph.wire("MinimumDamper", "OccupiedDamperMinimum", "b")
    graph.add("DamperEnable", BlockKind.NUMERIC_SWITCH, "Enable damper", column=6)
    graph.wire("Occupied", "DamperEnable", "selector")
    graph.wire("OccupiedDamperMinimum", "DamperEnable", "when_true")
    graph.wire("Zero", "DamperEnable", "when_false")

    graph.add("ZoneTempHigh", BlockKind.GREATER_THAN, "Zone temperature high", column=5)
    graph.wire("ZoneTemp", "ZoneTempHigh", "a")
    graph.wire("HighTempLimit", "ZoneTempHigh", "b")
    graph.add("OccupiedHighTemp", BlockKind.AND, "Occupied high temperature alarm", column=6)
    graph.wire("ZoneTempHigh", "OccupiedHighTemp", "a")
    graph.wire("Occupied", "OccupiedHighTemp", "b")

    for point_id, kind, label, source in (
        ("CoolingDemand", BlockKind.NUMERIC_OUTPUT, "Cooling demand", "OccupiedCooling"),
        ("HeatingDemand", BlockKind.NUMERIC_OUTPUT, "Heating demand", "OccupiedHeating"),
        ("DamperCommand", BlockKind.NUMERIC_OUTPUT, "Damper command", "DamperEnable"),
        ("ValveCommand", BlockKind.NUMERIC_OUTPUT, "Reheat valve command", "OccupiedHeating"),
        (
            "HighZoneTempAlarm",
            BlockKind.BOOLEAN_OUTPUT,
            "High zone temperature alarm",
            "OccupiedHighTemp",
        ),
    ):
        graph.add(point_id, kind, label, column=7)
        graph.wire(source, point_id, "in")

    return ControlGraph(
        name=job.equipment_name,
        blocks=graph.blocks,
        links=graph.links,
        metadata={
            "sequence_family": job.sequence.family,
            "sequence_version": job.sequence.version,
            "parameters": parameters,
            "safety": "Human approval required before export. No live-write capability.",
        },
    )
