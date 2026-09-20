from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from bactalk.domain import PointSpec
from bactalk.point_mapping import COMMON_ALIASES

POINT_ALIASES: dict[str, tuple[str, ...]] = {
    **COMMON_ALIASES,
    "OperationMode": ("operation mode", "system mode", "zone group mode", "g36 mode"),
    "PrimaryAirflow": ("primary airflow", "airflow", "air flow", "vav flow", "airflow sensor"),
    "PrimaryAirflowSetpoint": (
        "primary airflow setpoint",
        "airflow setpoint",
        "air flow sp",
        "vav flow sp",
    ),
    "DamperPosition": ("damper position", "damper feedback", "dpr pos"),
    "SupplyAirTemp": ("supply air temperature", "supply air temp", "sat"),
    "AirflowAlarm": ("airflow alarm", "air flow alarm", "flow alarm"),
    "DamperLeakAlarm": ("damper leak alarm", "leaking damper alarm"),
    "ZoneTempAlarm": ("zone temperature alarm", "zone temp alarm", "space temp alarm"),
    "ColdDuctRequest": ("static pressure request", "duct static request", "cold duct request"),
    "SATResetRequest": ("supply air temperature reset request", "sat reset request"),
    "DischargeAirTemp": (
        "discharge air temperature",
        "discharge air temp",
        "supply air temperature",
        "supply air temp",
        "dat",
        "sat",
    ),
    "ZoneCO2": ("zone co2", "space co2", "co2 sensor"),
    "ZoneCO2Setpoint": ("zone co2 setpoint", "co2 setpoint", "co2 sp"),
    "OccupancySensor": ("occupancy sensor", "occupancy detector", "occ sensor"),
    "WindowOpen": ("window open", "window status", "window contact"),
    "SupplyFanStatus": ("supply fan status", "supply fan proof", "sf status"),
    "SupplyFanSpeed": ("supply fan speed", "supply fan speed feedback", "sf speed"),
    "DuctHighPressure": ("duct high pressure", "high duct pressure", "duct high switch"),
    "OutdoorAirTemp": ("outdoor air temperature", "outside air temperature", "oat"),
    "ReturnAirTemp": ("return air temperature", "return air temp", "rat"),
    "MixedAirTemp": ("mixed air temperature", "mixed air temp", "mat"),
    "OutdoorDamperCommand": ("outdoor air damper command", "oa damper command", "oad cmd"),
    "OutdoorDamperPosition": ("outdoor air damper position", "oa damper position", "oad pos"),
    "MinimumOutdoorAirflow": ("minimum outdoor airflow", "outdoor airflow", "oa airflow"),
    "MinimumOutdoorAirflowSetpoint": (
        "minimum outdoor airflow setpoint",
        "outdoor airflow setpoint",
        "oa flow sp",
    ),
    "FireSmokeShutdown": ("fire smoke shutdown", "fire alarm shutdown", "smoke shutdown"),
    "EmergencyStop": ("emergency stop", "e stop", "estop"),
    "ReturnFanCommand": ("return fan command", "return fan start stop", "rf cmd"),
    "ReturnFanStatus": ("return fan status", "return fan proof", "rf status"),
    "ReturnFanSpeedCommand": ("return fan speed command", "return fan vfd command"),
    "ReliefFanCommand": ("relief fan command", "relief fan start stop"),
    "ReliefFanStatus": ("relief fan status", "relief fan proof"),
    "ReliefDamperCommand": ("relief damper command", "relief damper position command"),
    "SupplyAirflow": ("supply airflow", "supply air flow", "supply flow"),
    "ReturnAirflow": ("return airflow", "return air flow", "return flow"),
    "BuildingPressure": ("building pressure", "building static pressure"),
    "BuildingPressureSetpoint": ("building pressure setpoint", "building pressure sp"),
    "PreheatCommand": ("preheat command", "preheat valve command", "preheat output"),
    "FreezeStat": ("freeze stat", "freezestat", "low temperature cutout"),
    "ZoneTemp": ("zone temperature", "zone temp", "space temperature", "space temp", "znt"),
}


UNIT_FAMILIES: dict[str, dict[str, str]] = {
    "temperature": {
        "degf": "degF",
        "fahrenheit": "degF",
        "f": "degF",
        "degc": "degC",
        "celsius": "degC",
        "c": "degC",
        "k": "K",
        "kelvin": "K",
    },
    "airflow": {
        "cfm": "cfm",
        "ft3min": "cfm",
        "m3s": "m3/s",
        "m3sec": "m3/s",
        "ls": "L/s",
        "lsec": "L/s",
    },
    "pressure": {
        "inh2o": "inH2O",
        "inwc": "inH2O",
        "inwg": "inH2O",
        "pa": "Pa",
        "kpa": "kPa",
    },
    "fraction": {"%": "%", "percent": "%", "pct": "%", "01": "0..1"},
    "concentration": {"ppm": "ppm"},
    "enthalpy": {"btulb": "Btu/lb", "kjkg": "kJ/kg", "jkg": "J/kg"},
}


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9%]+", "", value.lower().replace("°", "deg"))


def _unit(value: str | None) -> tuple[str | None, str | None]:
    if value is None or not value.strip():
        return None, None
    key = _key(value)
    for family, members in UNIT_FAMILIES.items():
        if key in members:
            return family, members[key]
    return "unknown", value.strip()


def _aliases(requirement: dict[str, Any]) -> set[str]:
    point_id = requirement["id"]
    return {
        _key(value)
        for value in (
            point_id,
            requirement["label"],
            *POINT_ALIASES.get(point_id, ()),
        )
        if value
    }


class CtrlFlowPointReconciler:
    """Exact, reviewable reconciliation of contractor points to a ctrl-flow brief."""

    def reconcile(
        self,
        brief: dict[str, Any],
        points: list[PointSpec],
    ) -> dict[str, Any]:
        requirements = brief["point_requirements"]["points"]
        requirements_by_id = {item["id"]: item for item in requirements}
        alias_index: dict[str, set[str]] = defaultdict(set)
        for requirement in requirements:
            for alias in _aliases(requirement):
                alias_index[alias].add(requirement["id"])

        matches: list[dict[str, Any]] = []
        ambiguous: list[dict[str, Any]] = []
        unmatched: list[dict[str, Any]] = []
        duplicates: list[dict[str, Any]] = []
        matched_requirements: dict[str, str] = {}
        canonical_points: list[PointSpec] = []
        blocking_issues: list[dict[str, Any]] = []
        conversions: list[dict[str, Any]] = []

        for point in points:
            source_name = point.source_name or point.name
            evidence = {point.name, point.label}
            if point.source_name:
                evidence.add(point.source_name)
            if point.name in requirements_by_id:
                candidates = {point.name}
            elif point.source_name in requirements_by_id:
                candidates = {point.source_name}
            else:
                candidates = set()
                for value in evidence:
                    candidates.update(alias_index.get(_key(value), set()))
            if not candidates:
                unmatched.append(
                    {
                        "source_name": source_name,
                        "name": point.name,
                        "label": point.label,
                        "reason": "no exact canonical name or audited alias matched",
                    }
                )
                canonical_points.append(point)
                continue
            if len(candidates) > 1:
                ambiguous.append(
                    {
                        "source_name": source_name,
                        "candidates": sorted(candidates),
                        "reason": "point evidence matches more than one required point",
                    }
                )
                canonical_points.append(point)
                continue

            requirement_id = next(iter(candidates))
            if requirement_id in matched_requirements:
                duplicate = {
                    "requirement_id": requirement_id,
                    "first_source_name": matched_requirements[requirement_id],
                    "duplicate_source_name": source_name,
                }
                duplicates.append(duplicate)
                blocking_issues.append({"kind": "duplicate", **duplicate})
                canonical_points.append(point)
                continue

            requirement = requirements_by_id[requirement_id]
            matched_requirements[requirement_id] = source_name
            issues: list[dict[str, Any]] = []
            if point.role.value != requirement["role"]:
                issues.append(
                    {
                        "kind": "role_mismatch",
                        "expected": requirement["role"],
                        "actual": point.role.value,
                    }
                )
            if point.data_type.value != requirement["data_type"]:
                issues.append(
                    {
                        "kind": "data_type_mismatch",
                        "expected": requirement["data_type"],
                        "actual": point.data_type.value,
                    }
                )

            expected_family, expected_unit = _unit(requirement.get("units"))
            actual_family, actual_unit = _unit(point.units)
            unit_status = "not-applicable"
            if expected_unit is not None:
                if actual_unit is None:
                    unit_status = "missing"
                    issues.append(
                        {
                            "kind": "units_missing",
                            "expected": expected_unit,
                            "actual": None,
                        }
                    )
                elif expected_family == actual_family and expected_unit == actual_unit:
                    unit_status = "exact"
                elif expected_family == actual_family and expected_family != "unknown":
                    unit_status = "conversion-required"
                    conversions.append(
                        {
                            "requirement_id": requirement_id,
                            "source_name": source_name,
                            "from": actual_unit,
                            "to": expected_unit,
                            "status": "explicit-converter-required",
                        }
                    )
                else:
                    unit_status = "incompatible"
                    issues.append(
                        {
                            "kind": "units_incompatible",
                            "expected": expected_unit,
                            "actual": actual_unit,
                        }
                    )

            mapping = {
                "source_name": source_name,
                "original_name": point.name,
                "requirement_id": requirement_id,
                "method": "exact-name" if point.name == requirement_id else "audited-alias",
                "role": point.role.value,
                "data_type": point.data_type.value,
                "unit_status": unit_status,
                "issues": issues,
            }
            matches.append(mapping)
            blocking_issues.extend(
                {
                    "requirement_id": requirement_id,
                    "source_name": source_name,
                    **issue,
                }
                for issue in issues
            )
            canonical_points.append(
                point.model_copy(
                    update={
                        "name": requirement_id,
                        "source_name": source_name
                        if point.name != requirement_id
                        else point.source_name,
                    }
                )
            )

        required_ids = {item["id"] for item in requirements if item.get("required") is True}
        missing_required = sorted(required_ids - set(matched_requirements))
        for requirement_id in missing_required:
            blocking_issues.append(
                {
                    "kind": "missing_required_point",
                    "requirement_id": requirement_id,
                    "source_name": None,
                }
            )
        for item in ambiguous:
            blocking_issues.append({"kind": "ambiguous", **item})

        ready = not blocking_issues
        return {
            "schema": "bactalk.ctrl-flow-point-reconciliation/v1",
            "configuration_digest": brief["configuration_digest"],
            "equipment_family": brief["design_binding"]["equipment_family"],
            "provided_point_count": len(points),
            "requirement_count": len(requirements),
            "required_point_count": len(required_ids),
            "matched_requirement_count": len(matched_requirements),
            "missing_required_count": len(missing_required),
            "missing_required": missing_required,
            "matches": matches,
            "ambiguous": ambiguous,
            "duplicates": duplicates,
            "unmatched_provided": unmatched,
            "unit_conversions": conversions,
            "blocking_issues": blocking_issues,
            "canonical_points": [point.model_dump(mode="json") for point in canonical_points],
            "ready_for_sequence_reconciliation": ready,
            "complete_niagara_job_ready": False,
            "policy": (
                "Only exact canonical names and audited aliases are auto-mapped. Missing, "
                "ambiguous, duplicate, role/type-invalid, or unit-invalid requirements block "
                "the next compiler stage; convertible units require an explicit converter."
            ),
        }
