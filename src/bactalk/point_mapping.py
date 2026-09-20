from __future__ import annotations

import re
from dataclasses import dataclass

from bactalk.domain import DeliverableRequirements, PointSpec


class PointMappingError(ValueError):
    pass


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


@dataclass(frozen=True)
class MappingResult:
    points: tuple[PointSpec, ...]
    mappings: tuple[dict[str, str], ...]
    missing_required: tuple[str, ...]


COMMON_ALIASES: dict[str, tuple[str, ...]] = {
    "ZoneTemp": ("zone temp", "zone temperature", "space temp", "space temperature", "znt"),
    "CoolingSetpoint": ("cooling setpoint", "cooling sp", "clg sp", "zn clg sp"),
    "HeatingSetpoint": ("heating setpoint", "heating sp", "htg sp", "zn htg sp"),
    "Occupied": ("occupied", "occupancy", "occupied mode", "occ"),
    "DamperCommand": (
        "damper command",
        "damper position command",
        "vav damper command",
        "dmpr cmd",
        "dpr c",
    ),
    "ValveCommand": (
        "valve command",
        "reheat valve command",
        "heating valve command",
        "rht vlv c",
    ),
    "CoolingDemand": ("cooling demand", "cooling loop", "clg demand", "clg dmd"),
    "HeatingDemand": ("heating demand", "heating loop", "htg demand", "htg dmd"),
    "HighZoneTempAlarm": (
        "high zone temperature alarm",
        "zone temp high alarm",
        "high space temp alarm",
        "hi zn t alm",
    ),
    "Enable": ("enable", "system enable", "fan enable", "run enable"),
    "DuctStatic": (
        "duct static",
        "duct static pressure",
        "supply duct static pressure",
        "dsp",
    ),
    "DuctHighLimit": (
        "duct high limit",
        "duct pressure high limit",
        "high duct pressure setpoint",
        "dsp high limit",
    ),
    "DuctStaticSetpoint": (
        "duct static setpoint",
        "duct static pressure setpoint",
        "dsp sp",
    ),
    "DischargeAirTemp": (
        "discharge air temp",
        "discharge air temperature",
        "supply air temp",
        "sat",
        "dat",
    ),
    "DischargeAirTempSetpoint": (
        "discharge air temp setpoint",
        "discharge air temperature setpoint",
        "supply air temp setpoint",
        "sat sp",
        "dat sp",
    ),
    "SupplyFanCommand": (
        "supply fan command",
        "supply fan start stop",
        "sf cmd",
        "sf c",
    ),
    "SupplyFanSpeedCommand": (
        "supply fan speed command",
        "supply fan vfd command",
        "sf speed cmd",
        "sf vfd cmd",
    ),
    "CoolingValveCommand": (
        "cooling valve command",
        "chilled water valve command",
        "clg vlv cmd",
        "chwv c",
    ),
    "DuctPressureAlarm": (
        "duct pressure alarm",
        "high duct pressure alarm",
        "dsp hi alm",
    ),
    "FanStatus": ("fan status", "fan proof", "fan run status", "fan sts"),
    "FanCommand": ("fan command", "fan start stop", "fan cmd"),
    "FanProofAlarm": (
        "fan proof alarm",
        "fan failure alarm",
        "fan fail alarm",
    ),
    "SystemEnable": ("system enable", "plant enable", "pump enable"),
    "Pump1LeadSelect": ("pump 1 lead select", "pump 1 lead", "p1 lead"),
    "Pump1Available": ("pump 1 available", "pump 1 availability", "p1 avail"),
    "Pump2Available": ("pump 2 available", "pump 2 availability", "p2 avail"),
    "Pump1Command": ("pump 1 command", "pump 1 start stop", "p1 cmd"),
    "Pump2Command": ("pump 2 command", "pump 2 start stop", "p2 cmd"),
    "NoPumpAvailableAlarm": (
        "no pump available alarm",
        "no pumps available",
        "pump unavailable alarm",
    ),
}


FAMILY_REQUIRED_POINTS: dict[str, tuple[str, ...]] = {
    "G36_VAV_REHEAT": (
        "ZoneTemp",
        "CoolingSetpoint",
        "HeatingSetpoint",
        "Occupied",
        "DamperCommand",
        "ValveCommand",
        "CoolingDemand",
        "HeatingDemand",
        "HighZoneTempAlarm",
    ),
    "CUSTOM_AHU_SAFETY_COOLING": (
        "Occupied",
        "DuctStatic",
        "DuctHighLimit",
        "DischargeAirTemp",
        "DischargeAirTempSetpoint",
        "SupplyFanCommand",
        "CoolingValveCommand",
        "DuctPressureAlarm",
    ),
    "AHU_DUCT_STATIC_PI": (
        "Enable",
        "DuctStatic",
        "DuctStaticSetpoint",
        "SupplyFanSpeedCommand",
    ),
    "EXHAUST_FAN_PROOF": ("Enable", "FanStatus", "FanCommand", "FanProofAlarm"),
    "TWO_PUMP_AVAILABILITY_SELECTOR": (
        "SystemEnable",
        "Pump1LeadSelect",
        "Pump1Available",
        "Pump2Available",
        "Pump1Command",
        "Pump2Command",
        "NoPumpAvailableAlarm",
    ),
}


def canonicalize_points(points: list[PointSpec], sequence_family: str) -> MappingResult:
    """Map exact, audited contractor aliases to a pack's logical point names.

    This intentionally does not use fuzzy matching. Ambiguous or unknown names remain visible for
    review instead of being silently wired to the wrong physical point.
    """

    required = FAMILY_REQUIRED_POINTS.get(sequence_family)
    if required is None:
        return MappingResult(points=tuple(points), mappings=(), missing_required=())
    alias_index: dict[str, set[str]] = {}
    for canonical in required:
        for alias in (canonical, *COMMON_ALIASES.get(canonical, ())):
            alias_index.setdefault(_key(alias), set()).add(canonical)

    assigned: dict[str, str] = {}
    mapped_points: list[PointSpec] = []
    mappings: list[dict[str, str]] = []
    for point in points:
        evidence = [point.name, point.source_name or "", point.label]
        candidates: set[str] = set()
        for value in evidence:
            candidates.update(alias_index.get(_key(value), set()))
        if len(candidates) > 1:
            raise PointMappingError(
                f"point {point.source_name or point.name!r} ambiguously matches: "
                + ", ".join(sorted(candidates))
            )
        if not candidates:
            mapped_points.append(point)
            continue
        canonical = next(iter(candidates))
        if canonical in assigned:
            raise PointMappingError(
                f"multiple contractor points map to {canonical}: "
                f"{assigned[canonical]!r} and {point.source_name or point.name!r}"
            )
        assigned[canonical] = point.source_name or point.name
        if point.name == canonical:
            mapped_points.append(point)
            continue
        source_name = point.source_name or point.name
        mapped_points.append(
            point.model_copy(update={"name": canonical, "source_name": source_name})
        )
        mappings.append(
            {
                "source_name": source_name,
                "canonical_name": canonical,
                "method": "exact_alias",
            }
        )

    names = [point.name for point in mapped_points]
    if len(names) != len(set(names)):
        raise PointMappingError("point mapping produced duplicate canonical identifiers")
    missing = tuple(sorted(set(required) - set(names)))
    return MappingResult(
        points=tuple(mapped_points),
        mappings=tuple(mappings),
        missing_required=missing,
    )


def canonicalize_deliverable_requirements(
    requirements: DeliverableRequirements,
    points: list[PointSpec],
) -> DeliverableRequirements:
    """Resolve requirement references through the reviewed contractor-to-canonical point map."""

    lookup: dict[str, str] = {}
    for point in points:
        lookup[_key(point.name)] = point.name
        if point.source_name:
            lookup[_key(point.source_name)] = point.name

    def resolve(value: str) -> str:
        return lookup.get(_key(value), value)

    payload = requirements.model_dump(mode="json")
    for item in payload["alarms"]:
        item["point"] = resolve(item["point"])
    for item in payload["schedules"]:
        item["output_point"] = resolve(item["output_point"])
    for item in payload["histories"]:
        item["point"] = resolve(item["point"])
    for item in payload["graphics"]:
        item["points"] = [resolve(point) for point in item["points"]]
    return DeliverableRequirements.model_validate(payload)
