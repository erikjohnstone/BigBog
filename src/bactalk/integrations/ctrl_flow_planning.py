from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from bactalk.capabilities import CapabilityRegistry
from bactalk.qualification import builtin_qualification_profile

AHU_TEMPLATE = "Buildings.Templates.AirHandlersFans.VAVMultiZone"
COOLING_ONLY_TEMPLATE = "Buildings.Templates.ZoneEquipment.VAVBoxCoolingOnly"
REHEAT_TEMPLATE = "Buildings.Templates.ZoneEquipment.VAVBoxReheat"


TEMPLATE_BINDINGS: dict[str, dict[str, str]] = {
    AHU_TEMPLATE: {
        "equipment_family": "ahu.multi-zone-vav",
        "sequence_family": "LBNL_G36_CONTROLLER",
        "bounded_sequence_family": "CUSTOM_AHU_SAFETY_COOLING",
        "controller_id": "AHUs.MultiZone.VAV.Controller",
    },
    COOLING_ONLY_TEMPLATE: {
        "equipment_family": "terminal.vav.cooling-only",
        "sequence_family": "LBNL_G36_CONTROLLER",
        "controller_id": "TerminalUnits.CoolingOnly.Controller",
    },
    REHEAT_TEMPLATE: {
        "equipment_family": "terminal.vav.reheat",
        "sequence_family": "LBNL_G36_CONTROLLER",
        "bounded_sequence_family": "G36_VAV_REHEAT",
        "controller_id": "TerminalUnits.Reheat.Controller",
    },
}


def _suffix(value: Any) -> str:
    return str(value).rsplit(".", 1)[-1]


def _enabled(value: Any) -> bool:
    return value is True or value == "true"


def _point(
    point_id: str,
    label: str,
    role: str,
    data_type: str,
    *,
    units: str | None = None,
    required: bool = True,
    condition: str = "always",
    reason: str,
    subsystem: str,
) -> dict[str, Any]:
    return {
        "id": point_id,
        "label": label,
        "role": role,
        "data_type": data_type,
        "units": units,
        "required": required,
        "condition": condition,
        "reason": reason,
        "subsystem": subsystem,
    }


def _scenario(
    scenario_id: str,
    title: str,
    level: str,
    *,
    reason: str,
    expected: Iterable[str],
) -> dict[str, Any]:
    return {
        "id": scenario_id,
        "title": title,
        "level": level,
        "reason": reason,
        "expected_evidence": list(expected),
        "status": "test-definition-required",
    }


def _values(configuration: dict[str, Any]) -> dict[str, Any]:
    values = {
        field["instance_path"]: field.get("value") for field in configuration.get("fields", [])
    }
    for selection_path, value in configuration.get("selections", {}).items():
        if "-" in selection_path:
            values[selection_path.split("-", 1)[1]] = value
    return values


def _choice_labels(configuration: dict[str, Any]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for field in configuration.get("fields", []):
        value = field.get("value")
        labels[field["instance_path"]] = next(
            (
                choice["label"]
                for choice in field.get("choices", [])
                if choice.get("value") == value
            ),
            str(value),
        )
    return labels


def _base_scenarios() -> list[dict[str, Any]]:
    return [
        _scenario(
            "normal-operation",
            "Normal occupied operation",
            "required",
            reason="Prove the selected equipment reaches every normal control mode.",
            expected=("mode transitions", "bounded commands", "stable control response"),
        ),
        _scenario(
            "unoccupied-shutdown",
            "Unoccupied and disabled shutdown",
            "required",
            reason="Outputs must reach the approved safe state outside occupied operation.",
            expected=("commanded shutdown", "minimum ventilation policy", "alarm policy"),
        ),
        _scenario(
            "sensor-invalid",
            "Invalid sensor quality",
            "required",
            reason="Bad quality must not be silently interpreted as a valid process value.",
            expected=("fallback state", "alarm", "operator-visible cause"),
        ),
        _scenario(
            "sensor-stale",
            "Stale sensor value",
            "required",
            reason="A plausible but frozen value is a distinct and dangerous failure mode.",
            expected=("staleness timer", "fallback state", "recovery"),
        ),
        _scenario(
            "communications-loss",
            "BACnet or peer-controller communications loss",
            "required",
            reason="Dependencies must fail into a declared local state.",
            expected=("timeout", "safe local behavior", "alarm", "recovery"),
        ),
        _scenario(
            "manual-override",
            "Manual override arbitration",
            "required",
            reason=(
                "Operator, emergency, schedule, and automatic commands need explicit precedence."
            ),
            expected=("priority order", "override indication", "bumpless release"),
        ),
        _scenario(
            "power-cycle",
            "Power cycle and warm restart",
            "required",
            reason=(
                "Initialization must not briefly energize unsafe outputs or lose required state."
            ),
            expected=("safe initialization", "timer restoration policy", "controlled restart"),
        ),
        _scenario(
            "actuator-failure",
            "Actuator command/feedback disagreement",
            "required",
            reason="A valid command is not proof that the physical device moved.",
            expected=("proof timeout", "fallback", "alarm", "recovery"),
        ),
        _scenario(
            "recovery",
            "Fault recovery and reset",
            "required",
            reason="Every injected fault needs an intentional clear, latch, and restart policy.",
            expected=("clear criteria", "manual-reset policy", "no command bump"),
        ),
    ]


def _terminal_points(*, reheat: bool, values: dict[str, Any]) -> list[dict[str, Any]]:
    points = [
        _point(
            "ZoneTemp",
            "Zone temperature",
            "sensor",
            "numeric",
            units="degF",
            reason="Primary zone feedback.",
            subsystem="zone",
        ),
        _point(
            "CoolingSetpoint",
            "Occupied cooling setpoint",
            "setpoint",
            "numeric",
            units="degF",
            reason="Cooling-loop reference.",
            subsystem="zone",
        ),
        _point(
            "HeatingSetpoint",
            "Occupied heating setpoint",
            "setpoint",
            "numeric",
            units="degF",
            reason="Heating/deadband reference.",
            subsystem="zone",
        ),
        _point(
            "Occupied",
            "Effective occupancy mode",
            "status",
            "boolean",
            reason="Selects occupied and unoccupied behavior.",
            subsystem="mode",
        ),
        _point(
            "OperationMode",
            "Zone group operation mode",
            "status",
            "numeric",
            reason="Coordinates warm-up, cool-down, setup, setback, and occupied modes.",
            subsystem="mode",
        ),
        _point(
            "PrimaryAirflow",
            "Primary airflow",
            "sensor",
            "numeric",
            units="cfm",
            reason="Closed-loop airflow feedback and alarm proof.",
            subsystem="airflow",
        ),
        _point(
            "PrimaryAirflowSetpoint",
            "Primary airflow setpoint",
            "setpoint",
            "numeric",
            units="cfm",
            reason="Active ventilation and thermal airflow target.",
            subsystem="airflow",
        ),
        _point(
            "DamperCommand",
            "Damper command",
            "command",
            "numeric",
            units="%",
            reason="Primary-airflow actuator output.",
            subsystem="damper",
        ),
        _point(
            "DamperPosition",
            "Damper position feedback",
            "status",
            "numeric",
            units="%",
            reason="Actuator proof and diagnostics.",
            subsystem="damper",
        ),
        _point(
            "SupplyAirTemp",
            "AHU supply-air temperature",
            "sensor",
            "numeric",
            units="degF",
            reason="Heating/cooling availability and discharge-air protection.",
            subsystem="airflow",
        ),
        _point(
            "CoolingDemand",
            "Zone cooling loop",
            "status",
            "numeric",
            units="%",
            reason="Reviewable loop demand and system request input.",
            subsystem="zone",
        ),
        _point(
            "HeatingDemand",
            "Zone heating loop",
            "status",
            "numeric",
            units="%",
            reason="Reviewable loop demand and system request input.",
            subsystem="zone",
        ),
        _point(
            "AirflowAlarm",
            "Low/high airflow alarm",
            "alarm",
            "numeric",
            reason="Detects command-versus-flow failure.",
            subsystem="alarms",
        ),
        _point(
            "DamperLeakAlarm",
            "Leaking damper alarm",
            "alarm",
            "boolean",
            reason="Detects airflow while commanded closed.",
            subsystem="alarms",
        ),
        _point(
            "ZoneTempAlarm",
            "Zone temperature alarm",
            "alarm",
            "numeric",
            reason="Exposes persistent comfort deviation.",
            subsystem="alarms",
        ),
        _point(
            "OverrideDamper",
            "Damper override",
            "command",
            "numeric",
            units="%",
            required=False,
            condition="contractor enables functional-test override",
            reason="Commissioning override with explicit arbitration.",
            subsystem="overrides",
        ),
        _point(
            "ColdDuctRequest",
            "Static-pressure reset request",
            "status",
            "numeric",
            reason="Terminal-to-AHU reset request.",
            subsystem="system-requests",
        ),
        _point(
            "SATResetRequest",
            "Supply-temperature reset request",
            "status",
            "numeric",
            reason="Terminal-to-AHU temperature reset request.",
            subsystem="system-requests",
        ),
    ]
    if reheat:
        points.extend(
            [
                _point(
                    "ValveCommand",
                    "Reheat valve or electric heat command",
                    "command",
                    "numeric",
                    units="%",
                    reason="Heating actuator output.",
                    subsystem="reheat",
                ),
                _point(
                    "ValvePosition",
                    "Reheat actuator feedback",
                    "status",
                    "numeric",
                    units="%",
                    required=False,
                    condition="feedback is available",
                    reason="Heating actuator proof.",
                    subsystem="reheat",
                ),
                _point(
                    "DischargeAirTemp",
                    "Terminal discharge-air temperature",
                    "sensor",
                    "numeric",
                    units="degF",
                    reason="Discharge-temperature limit and reheat verification.",
                    subsystem="reheat",
                ),
                _point(
                    "HeatingPlantAvailable",
                    "Heating plant available",
                    "status",
                    "boolean",
                    required=False,
                    condition="water-based reheat coil",
                    reason="Prevents futile valve commands and qualifies alarms.",
                    subsystem="reheat",
                ),
                _point(
                    "HotWaterRequest",
                    "Hot-water plant request",
                    "status",
                    "numeric",
                    reason="Terminal-to-plant request for reheat availability.",
                    subsystem="system-requests",
                ),
            ]
        )
    if _enabled(values.get("ctl.have_CO2Sen")):
        points.extend(
            [
                _point(
                    "ZoneCO2",
                    "Zone carbon dioxide",
                    "sensor",
                    "numeric",
                    units="ppm",
                    reason="Selected demand-controlled ventilation input.",
                    subsystem="ventilation",
                ),
                _point(
                    "ZoneCO2Setpoint",
                    "Zone CO2 setpoint",
                    "setpoint",
                    "numeric",
                    units="ppm",
                    reason="Demand-controlled ventilation reference.",
                    subsystem="ventilation",
                ),
            ]
        )
    if _enabled(values.get("ctl.have_occSen")):
        points.append(
            _point(
                "OccupancySensor",
                "Zone occupancy sensor",
                "sensor",
                "boolean",
                reason="Selected local occupancy input.",
                subsystem="mode",
            )
        )
    if _enabled(values.get("ctl.have_winSen")):
        points.append(
            _point(
                "WindowOpen",
                "Window-open status",
                "sensor",
                "boolean",
                reason="Selected window interlock input.",
                subsystem="safeties",
            )
        )
    return points


def _terminal_scenarios(*, reheat: bool, values: dict[str, Any]) -> list[dict[str, Any]]:
    scenarios = _base_scenarios()
    scenarios.extend(
        [
            _scenario(
                "airflow-proof",
                "Airflow tracking and proof failure",
                "required",
                reason=(
                    "Prove minimum/maximum flow control, blockage, leakage, and loss of flow "
                    "sensing."
                ),
                expected=("bounded damper", "delayed alarm", "safe sensor fallback"),
            ),
            _scenario(
                "zone-mode-transitions",
                "Heating, deadband, and cooling transitions",
                "required",
                reason="Terminal sequencing depends on stable transitions without hunting.",
                expected=("deadband", "hysteresis", "bounded airflow", "system requests"),
            ),
            _scenario(
                "ahu-unavailable",
                "Upstream AHU unavailable",
                "required",
                reason="The terminal must not treat an unavailable air source as normal operation.",
                expected=("declared damper state", "alarm suppression policy", "recovery"),
            ),
        ]
    )
    if reheat:
        scenarios.extend(
            [
                _scenario(
                    "reheat-failure",
                    "Reheat valve/coil failure",
                    "required",
                    reason="Commanded heat needs discharge-temperature or actuator proof.",
                    expected=("proof timer", "alarm", "bounded discharge temperature"),
                ),
                _scenario(
                    "plant-unavailable",
                    "Heating plant unavailable",
                    "required",
                    reason="Water-based reheat depends on upstream plant availability.",
                    expected=("request", "fallback", "qualified alarm"),
                ),
                _scenario(
                    "discharge-high-limit",
                    "High discharge-air temperature limit",
                    "required",
                    reason="Reheat must not overheat the discharge stream.",
                    expected=("command limit", "alarm", "automatic recovery"),
                ),
            ]
        )
    for enabled, scenario_id, title in (
        (values.get("ctl.have_CO2Sen"), "co2-failure", "CO2 sensor failure"),
        (values.get("ctl.have_occSen"), "occupancy-sensor-failure", "Occupancy sensor failure"),
        (values.get("ctl.have_winSen"), "window-sensor-failure", "Window sensor failure"),
    ):
        if _enabled(enabled):
            scenarios.append(
                _scenario(
                    scenario_id,
                    title,
                    "required",
                    reason=(
                        "This optional sensor was selected and therefore needs an explicit "
                        "failed-input policy."
                    ),
                    expected=("invalid/stale detection", "default state", "alarm", "recovery"),
                )
            )
    return scenarios


def _ahu_points(values: dict[str, Any]) -> list[dict[str, Any]]:
    points = [
        _point(
            "Occupied",
            "Effective occupancy",
            "status",
            "boolean",
            reason="Coordinates enable and shutdown modes.",
            subsystem="mode",
        ),
        _point(
            "OperationMode",
            "AHU operation mode",
            "status",
            "numeric",
            reason="Coordinates occupied, warm-up, cool-down, setup, setback, and purge behavior.",
            subsystem="mode",
        ),
        _point(
            "SupplyFanCommand",
            "Supply fan command",
            "command",
            "boolean",
            reason="Primary air-system enable.",
            subsystem="supply-fan",
        ),
        _point(
            "SupplyFanStatus",
            "Supply fan proof",
            "status",
            "boolean",
            reason="Proves commanded fan operation.",
            subsystem="supply-fan",
        ),
        _point(
            "SupplyFanSpeedCommand",
            "Supply fan speed command",
            "command",
            "numeric",
            units="%",
            reason="Duct-static control output.",
            subsystem="supply-fan",
        ),
        _point(
            "SupplyFanSpeed",
            "Supply fan speed feedback",
            "status",
            "numeric",
            units="%",
            reason="VFD proof and diagnostics.",
            subsystem="supply-fan",
        ),
        _point(
            "DuctStatic",
            "Supply duct static pressure",
            "sensor",
            "numeric",
            units="inH2O",
            reason="Supply-fan loop feedback.",
            subsystem="supply-fan",
        ),
        _point(
            "DuctStaticSetpoint",
            "Supply duct static setpoint",
            "setpoint",
            "numeric",
            units="inH2O",
            reason="Resettable supply-fan control target.",
            subsystem="supply-fan",
        ),
        _point(
            "DuctHighLimit",
            "Duct high-pressure limit",
            "setpoint",
            "numeric",
            units="inH2O",
            reason="Independent fan shutdown threshold.",
            subsystem="safeties",
        ),
        _point(
            "DuctHighPressure",
            "Duct high-pressure safety",
            "sensor",
            "boolean",
            reason="Hardwired or software safety proof.",
            subsystem="safeties",
        ),
        _point(
            "DischargeAirTemp",
            "Discharge-air temperature",
            "sensor",
            "numeric",
            units="degF",
            reason="Temperature-control feedback and safety input.",
            subsystem="temperature",
        ),
        _point(
            "DischargeAirTempSetpoint",
            "Discharge-air temperature setpoint",
            "setpoint",
            "numeric",
            units="degF",
            reason="Resettable temperature target.",
            subsystem="temperature",
        ),
        _point(
            "OutdoorAirTemp",
            "Outdoor-air temperature",
            "sensor",
            "numeric",
            units="degF",
            reason="Economizer high limit and reset input.",
            subsystem="economizer",
        ),
        _point(
            "ReturnAirTemp",
            "Return-air temperature",
            "sensor",
            "numeric",
            units="degF",
            reason="Mixed-air diagnostics and differential economizer logic.",
            subsystem="economizer",
        ),
        _point(
            "MixedAirTemp",
            "Mixed-air temperature",
            "sensor",
            "numeric",
            units="degF",
            reason="Freeze prevention and economizer diagnostics.",
            subsystem="economizer",
        ),
        _point(
            "OutdoorDamperCommand",
            "Outdoor-air damper command",
            "command",
            "numeric",
            units="%",
            reason="Ventilation and economizer output.",
            subsystem="economizer",
        ),
        _point(
            "OutdoorDamperPosition",
            "Outdoor-air damper feedback",
            "status",
            "numeric",
            units="%",
            reason="Damper proof and diagnostics.",
            subsystem="economizer",
        ),
        _point(
            "MinimumOutdoorAirflow",
            "Minimum outdoor airflow",
            "sensor",
            "numeric",
            units="cfm",
            reason="Selected outdoor section includes measurement or derived proof.",
            subsystem="ventilation",
        ),
        _point(
            "MinimumOutdoorAirflowSetpoint",
            "Minimum outdoor-airflow setpoint",
            "setpoint",
            "numeric",
            units="cfm",
            reason="Ventilation control target.",
            subsystem="ventilation",
        ),
        _point(
            "FireSmokeShutdown",
            "Fire/smoke shutdown input",
            "sensor",
            "boolean",
            reason=(
                "Project life-safety interlock; exact behavior remains contractor-authoritative."
            ),
            subsystem="safeties",
        ),
        _point(
            "EmergencyStop",
            "Emergency stop input",
            "sensor",
            "boolean",
            reason="Highest-priority equipment shutdown.",
            subsystem="safeties",
        ),
        _point(
            "SupplyFanFailureAlarm",
            "Supply fan failure alarm",
            "alarm",
            "boolean",
            reason="Delayed command/proof failure indication.",
            subsystem="alarms",
        ),
        _point(
            "DuctPressureAlarm",
            "High duct-pressure alarm",
            "alarm",
            "boolean",
            reason="Operator evidence for high-pressure shutdown.",
            subsystem="alarms",
        ),
        _point(
            "LowDischargeTempAlarm",
            "Low discharge-temperature alarm",
            "alarm",
            "boolean",
            reason="Freeze-risk indication.",
            subsystem="alarms",
        ),
    ]

    outdoor = _suffix(values.get("secOutRel.secOut"))
    if outdoor.startswith("DedicatedDampers"):
        points.extend(
            [
                _point(
                    "VentilationDamperCommand",
                    "Minimum-ventilation damper command",
                    "command",
                    "numeric",
                    units="%",
                    reason="Selected dedicated ventilation damper.",
                    subsystem="ventilation",
                ),
                _point(
                    "EconomizerDamperCommand",
                    "Economizer damper command",
                    "command",
                    "numeric",
                    units="%",
                    reason="Selected dedicated economizer damper.",
                    subsystem="economizer",
                ),
            ]
        )
    if outdoor == "DedicatedDampersPressure":
        points.append(
            _point(
                "OutdoorAirDifferentialPressure",
                "Outdoor-air differential pressure",
                "sensor",
                "numeric",
                units="inH2O",
                reason="Selected pressure-based outdoor-air measurement section.",
                subsystem="ventilation",
            )
        )

    relief = _suffix(values.get("secOutRel.secRel"))
    if relief == "ReturnFan":
        points.extend(
            [
                _point(
                    "ReturnFanCommand",
                    "Return fan command",
                    "command",
                    "boolean",
                    reason="Selected return fan.",
                    subsystem="return-relief",
                ),
                _point(
                    "ReturnFanStatus",
                    "Return fan proof",
                    "status",
                    "boolean",
                    reason="Selected return fan proof.",
                    subsystem="return-relief",
                ),
                _point(
                    "ReturnFanSpeedCommand",
                    "Return fan speed command",
                    "command",
                    "numeric",
                    units="%",
                    reason="Selected variable-speed return fan.",
                    subsystem="return-relief",
                ),
                _point(
                    "ReliefDamperCommand",
                    "Relief damper command",
                    "command",
                    "numeric",
                    units="%",
                    reason="Return-fan section includes modulating relief damper.",
                    subsystem="return-relief",
                ),
            ]
        )
    elif relief == "ReliefFan":
        points.extend(
            [
                _point(
                    "ReliefFanCommand",
                    "Relief fan command",
                    "command",
                    "boolean",
                    reason="Selected relief fan.",
                    subsystem="return-relief",
                ),
                _point(
                    "ReliefFanStatus",
                    "Relief fan proof",
                    "status",
                    "boolean",
                    reason="Selected relief fan proof.",
                    subsystem="return-relief",
                ),
                _point(
                    "ReliefDamperCommand",
                    "Two-position relief damper command",
                    "command",
                    "boolean",
                    reason="Selected relief section damper.",
                    subsystem="return-relief",
                ),
            ]
        )
    else:
        points.append(
            _point(
                "ReliefDamperCommand",
                "Relief damper command",
                "command",
                "numeric",
                units="%",
                reason="Selected fanless modulating relief section.",
                subsystem="return-relief",
            )
        )

    if _suffix(values.get("ctl.typCtlFanRet")) == "AirflowMeasured":
        points.extend(
            [
                _point(
                    "SupplyAirflow",
                    "Supply airflow",
                    "sensor",
                    "numeric",
                    units="cfm",
                    reason="Selected return-fan airflow tracking.",
                    subsystem="return-relief",
                ),
                _point(
                    "ReturnAirflow",
                    "Return airflow",
                    "sensor",
                    "numeric",
                    units="cfm",
                    reason="Selected return-fan airflow tracking.",
                    subsystem="return-relief",
                ),
            ]
        )
    else:
        points.extend(
            [
                _point(
                    "BuildingPressure",
                    "Building static pressure",
                    "sensor",
                    "numeric",
                    units="inH2O",
                    reason="Selected building-pressure return/relief control.",
                    subsystem="return-relief",
                ),
                _point(
                    "BuildingPressureSetpoint",
                    "Building pressure setpoint",
                    "setpoint",
                    "numeric",
                    units="inH2O",
                    reason="Selected building-pressure control target.",
                    subsystem="return-relief",
                ),
            ]
        )

    heating = _suffix(values.get("coiHeaPre"))
    if heating != "None":
        points.append(
            _point(
                "PreheatCommand",
                "Preheat command",
                "command",
                "numeric",
                units="%",
                reason=f"Selected {heating} preheat coil.",
                subsystem="preheat",
            )
        )
        if heating == "WaterBasedHeating":
            points.append(
                _point(
                    "HotWaterPlantRequest",
                    "Hot-water plant request",
                    "status",
                    "numeric",
                    reason="Selected hot-water preheat coil.",
                    subsystem="plant-requests",
                )
            )
        else:
            points.append(
                _point(
                    "ElectricHeatProof",
                    "Electric preheat proof",
                    "status",
                    "boolean",
                    reason="Selected electric preheat coil.",
                    subsystem="preheat",
                )
            )
    if _suffix(values.get("coiCoo")) != "None":
        points.extend(
            [
                _point(
                    "CoolingValveCommand",
                    "Cooling valve command",
                    "command",
                    "numeric",
                    units="%",
                    reason="Selected chilled-water cooling coil.",
                    subsystem="cooling",
                ),
                _point(
                    "ChilledWaterPlantRequest",
                    "Chilled-water plant request",
                    "status",
                    "numeric",
                    reason="Selected chilled-water cooling coil.",
                    subsystem="plant-requests",
                ),
            ]
        )

    if _enabled(values.get("ctl.have_frePro")):
        points.append(
            _point(
                "FreezeProtectionStage",
                "Freeze-protection stage",
                "status",
                "numeric",
                reason="Selected software freeze-protection sequence.",
                subsystem="safeties",
            )
        )
        if _suffix(values.get("ctl.typFreSta")) == "Hardwired_to_BAS":
            points.append(
                _point(
                    "FreezeStat",
                    "Freeze-stat status",
                    "sensor",
                    "boolean",
                    reason="Selected freeze stat is wired to both equipment and BAS.",
                    subsystem="safeties",
                )
            )

    economizer = _suffix(values.get("ctl.typCtlEco"))
    if "DifferentialDryBulb" in economizer:
        points.append(
            _point(
                "ReturnAirTemp",
                "Return-air temperature",
                "sensor",
                "numeric",
                units="degF",
                reason="Selected differential dry-bulb economizer limit.",
                subsystem="economizer",
            )
        )
    if "Enthalpy" in economizer:
        points.extend(
            [
                _point(
                    "OutdoorAirEnthalpy",
                    "Outdoor-air enthalpy",
                    "sensor",
                    "numeric",
                    units="Btu/lb",
                    reason="Selected enthalpy economizer limit.",
                    subsystem="economizer",
                ),
                _point(
                    "ReturnAirEnthalpy",
                    "Return-air enthalpy",
                    "sensor",
                    "numeric",
                    units="Btu/lb",
                    required="DifferentialEnthalpy" in economizer,
                    condition="differential enthalpy selected"
                    if "DifferentialEnthalpy" in economizer
                    else "recommended diagnostic",
                    reason=(
                        "Return-air comparison for differential enthalpy or diagnostic visibility."
                    ),
                    subsystem="economizer",
                ),
            ]
        )
    return _deduplicate_points(points)


def _deduplicate_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for point in points:
        existing = unique.get(point["id"])
        if existing is None or (point["required"] and not existing["required"]):
            unique[point["id"]] = point
    return list(unique.values())


def _ahu_scenarios(values: dict[str, Any]) -> list[dict[str, Any]]:
    scenarios = _base_scenarios()
    scenarios.extend(
        [
            _scenario(
                "fire-smoke",
                "Fire/smoke shutdown and reset",
                "required",
                reason=(
                    "Life-safety input must override ordinary HVAC control while preserving "
                    "the approved smoke-control boundary."
                ),
                expected=("priority override", "declared damper/fan state", "manual reset policy"),
            ),
            _scenario(
                "duct-high-pressure",
                "Duct high-pressure shutdown",
                "required",
                reason="A failed damper network or pressure loop can damage ductwork.",
                expected=("immediate fan shutdown", "latched alarm policy", "safe restart"),
            ),
            _scenario(
                "supply-fan-proof",
                "Supply fan proof failure",
                "required",
                reason="Temperature and economizer outputs depend on proven airflow.",
                expected=("proof delay", "coil/damper fallback", "alarm", "recovery"),
            ),
            _scenario(
                "economizer-limits",
                "Economizer enable, disable, and high limits",
                "required",
                reason=(
                    "The selected economizer strategy must be proven on both sides of every limit."
                ),
                expected=("minimum ventilation", "integrated cooling", "sensor-failure fallback"),
            ),
            _scenario(
                "mixed-air-low-limit",
                "Mixed-air low-limit protection",
                "required",
                reason="Outdoor-air modulation can create coil freeze risk.",
                expected=("damper limit", "heating response", "escalation"),
            ),
            _scenario(
                "plant-unavailable",
                "Heating/cooling plant unavailable",
                "required",
                reason="Coil commands and alarms must be qualified by upstream plant state.",
                expected=("plant requests", "command policy", "alarm qualification", "recovery"),
            ),
            _scenario(
                "simultaneous-heat-cool",
                "Simultaneous heating/cooling prevention",
                "required",
                reason="Conflicting coil commands waste energy and can hide control errors.",
                expected=("sequencing/deadband", "bounded commands", "transition trace"),
            ),
        ]
    )
    if _enabled(values.get("ctl.have_frePro")):
        scenarios.append(
            _scenario(
                "freeze-protection",
                "All freeze-protection stages",
                "required",
                reason="Freeze protection was explicitly selected in the system design.",
                expected=(
                    "every stage threshold",
                    "fan/damper/coil actions",
                    "latch/reset",
                    "recovery",
                ),
            )
        )
    relief = _suffix(values.get("secOutRel.secRel"))
    scenarios.append(
        _scenario(
            "return-relief-failure",
            f"{relief} proof/control failure",
            "required",
            reason=(
                "The selected return/relief path controls building pressure and outdoor-air "
                "balance."
            ),
            expected=("proof/feedback failure", "pressure fallback", "alarm", "recovery"),
        )
    )
    if _suffix(values.get("ctl.typCtlFanRet")) == "AirflowMeasured":
        scenarios.append(
            _scenario(
                "airflow-station-failure",
                "Supply/return airflow station failure",
                "required",
                reason="Airflow tracking depends on valid measurement stations.",
                expected=("invalid/stale detection", "fallback speed/pressure strategy", "alarm"),
            )
        )
    else:
        scenarios.append(
            _scenario(
                "building-pressure-failure",
                "Building-pressure sensor failure",
                "required",
                reason="Return/relief control depends on building-pressure feedback.",
                expected=("fallback", "bounded fan/damper output", "alarm"),
            )
        )
    return scenarios


def _components(
    template_id: str, values: dict[str, Any], labels: dict[str, str]
) -> list[dict[str, Any]]:
    if template_id != AHU_TEMPLATE:
        components = [
            {"id": "primary-air-damper", "type": "damper", "quantity": 1},
            {"id": "airflow-sensor", "type": "sensor", "quantity": 1},
        ]
        if template_id == REHEAT_TEMPLATE:
            components.append(
                {
                    "id": "reheat-coil",
                    "type": _suffix(values.get("coiHea")),
                    "quantity": 1,
                    "selection": labels.get("coiHea"),
                }
            )
        for key, component_id in (
            ("ctl.have_CO2Sen", "co2-sensor"),
            ("ctl.have_occSen", "occupancy-sensor"),
            ("ctl.have_winSen", "window-sensor"),
        ):
            if _enabled(values.get(key)):
                components.append({"id": component_id, "type": "sensor", "quantity": 1})
        return components

    components = []
    for key, component_id, component_type in (
        ("secOutRel.secOut", "outdoor-air-section", "air-section"),
        ("secOutRel.secRel", "return-relief-section", "air-section"),
        ("fanSupDra", "draw-through-supply-fan", "fan"),
        ("fanSupBlo", "blow-through-supply-fan", "fan"),
        ("coiHeaPre", "preheat-coil", "coil"),
        ("coiCoo", "cooling-coil", "coil"),
    ):
        if key not in values or _suffix(values[key]) == "None":
            continue
        quantity = "array" if _suffix(values[key]).startswith("Array") else 1
        components.append(
            {
                "id": component_id,
                "type": component_type,
                "quantity": quantity,
                "selection": labels.get(key),
                "modelica_type": values[key],
            }
        )
    if "secOutRel.secRel.fanRet" in values:
        components.append(
            {
                "id": "return-fan",
                "type": "fan",
                "quantity": "array"
                if _suffix(values["secOutRel.secRel.fanRet"]).startswith("Array")
                else 1,
                "selection": labels.get("secOutRel.secRel.fanRet"),
                "modelica_type": values["secOutRel.secRel.fanRet"],
            }
        )
    return components


class CtrlFlowProgrammingPlanner:
    """Turn an evaluated ctrl-flow design into an honest BACTalk job-planning contract."""

    def __init__(self, capabilities: CapabilityRegistry | None = None):
        self.capabilities = capabilities or CapabilityRegistry()

    def build(self, configuration: dict[str, Any]) -> dict[str, Any]:
        template_id = configuration.get("template", {}).get("modelicaPath")
        binding = TEMPLATE_BINDINGS.get(template_id)
        if binding is None:
            raise ValueError(f"ctrl-flow template {template_id!r} has no BACTalk planning binding")
        values = _values(configuration)
        labels = _choice_labels(configuration)
        reheat = template_id == REHEAT_TEMPLATE
        points = (
            _ahu_points(values)
            if template_id == AHU_TEMPLATE
            else _terminal_points(reheat=reheat, values=values)
        )
        scenarios = (
            _ahu_scenarios(values)
            if template_id == AHU_TEMPLATE
            else _terminal_scenarios(reheat=reheat, values=values)
        )
        family = binding["equipment_family"]
        packs = [pack for pack in self.capabilities.packs if family in pack.equipment_families]
        bounded_family = binding.get("bounded_sequence_family")
        profile = builtin_qualification_profile(bounded_family)
        rejected = configuration.get("rejected_selections", [])
        blockers = []
        if rejected:
            blockers.append("Resolve every rejected or hidden ctrl-flow selection.")
        blockers.extend(
            [
                "Upload and approve the project sequence of operations; ctrl-flow defines "
                "system configuration, not the contractor's complete sequence.",
                "Map every required point to the points list/BACnet scan and resolve units, "
                "writable priority, quality, and ownership.",
                "Parameterize and qualify the selected LBNL controller or extend a bounded "
                "BACTalk pack for the approved sequence.",
                "Pass every required scenario against deterministic and dynamic-building or "
                "hardware evidence.",
                "Compile and run the generated station in the contractor's licensed "
                "Niagara/module environment before human release.",
            ]
        )
        required_points = [point for point in points if point["required"]]
        conditional_points = [point for point in points if not point["required"]]
        return {
            "schema": "bactalk.ctrl-flow-programming-brief/v1",
            "status": "blocked" if rejected else "engineering-brief-ready",
            "configuration_digest": configuration["configuration_digest"],
            "design_binding": {
                **binding,
                "source_template": template_id,
                "source_revision": configuration["source_evidence"]["revision"],
            },
            "components": _components(template_id, values, labels),
            "point_requirements": {
                "required_count": len(required_points),
                "conditional_count": len(conditional_points),
                "points": points,
                "policy": (
                    "Required points must map exactly; conditional points become required "
                    "when their stated condition is true in the approved project design."
                ),
            },
            "qualification_plan": {
                "scenario_count": len(scenarios),
                "required_count": sum(item["level"] == "required" for item in scenarios),
                "scenarios": scenarios,
                "bounded_profile": profile.model_dump(mode="json") if profile else None,
                "execution_status": "not-run",
            },
            "capability_alignment": {
                "candidate_packs": [
                    {
                        "id": pack.id,
                        "name": pack.name,
                        "stage": pack.stage,
                        "status": pack.status.value,
                        "production_ready": pack.production_ready,
                        "release_assessment": self.capabilities.release_assessment(pack.id),
                    }
                    for pack in packs
                ],
                "reference_controller_available": True,
                "complete_niagara_job_ready": False,
            },
            "planned_deliverables": [
                "typed control graph or configured LBNL source package",
                "Niagara logic and point bindings",
                "tags, alarms, schedules, histories, and graphics data",
                "virtual BACnet device model",
                "scenario traces, failures, repairs, and retest evidence",
                "review diff and human-gated station package",
            ],
            "release_blockers": blockers,
            "safety": {
                "live_writes_enabled": False,
                "human_approval_required": True,
                "life_safety_authority": "contractor project documents and licensed review",
            },
        }
