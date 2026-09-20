from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict, deque
from datetime import UTC, datetime, time
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class DataType(StrEnum):
    NUMERIC = "numeric"
    BOOLEAN = "boolean"


class PointRole(StrEnum):
    SENSOR = "sensor"
    SETPOINT = "setpoint"
    COMMAND = "command"
    STATUS = "status"
    ALARM = "alarm"


class BacnetObjectSpec(BaseModel):
    object_id: str = Field(pattern=r"^[a-z-]+,[0-9]+$")
    name: str
    data_type: DataType
    writable: bool = False
    units: str | None = None
    present_value: float | bool | str | None = None


class BacnetDeviceSpec(BaseModel):
    device_instance: int = Field(ge=0, le=4_194_302)
    address: str
    name: str
    vendor_id: int | None = Field(default=None, ge=0)
    transport: Literal["bacnet_ip", "mstp"] = "bacnet_ip"
    network_number: int | None = Field(default=None, ge=1, le=65_534)
    mac_address: int | None = Field(default=None, ge=0, le=254)
    objects: list[BacnetObjectSpec]

    @model_validator(mode="after")
    def unique_objects(self) -> BacnetDeviceSpec:
        object_ids = [item.object_id for item in self.objects]
        if len(object_ids) != len(set(object_ids)):
            raise ValueError("BACnet object ids must be unique within a device")
        if self.transport == "mstp":
            if self.network_number is None or self.mac_address is None:
                raise ValueError("MS/TP devices require network_number and mac_address")
        elif self.network_number is not None or self.mac_address is not None:
            raise ValueError("network_number and mac_address are only valid for MS/TP devices")
        return self


class BacnetScan(BaseModel):
    source: str
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    devices: list[BacnetDeviceSpec]

    @model_validator(mode="after")
    def unique_devices(self) -> BacnetScan:
        instances = [item.device_instance for item in self.devices]
        if len(instances) != len(set(instances)):
            raise ValueError("BACnet device instances must be unique")
        return self


class PointSpec(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", max_length=120)
    source_name: str | None = Field(default=None, max_length=500)
    label: str
    data_type: DataType
    role: PointRole
    units: str | None = None
    default: float | bool = 0.0
    required: bool = True
    bacnet_device_instance: int | None = Field(default=None, ge=0, le=4_194_302)
    bacnet_object: str | None = Field(default=None, pattern=r"^[a-z-]+,[0-9]+$")
    niagara_ord: str | None = Field(default=None, max_length=1_000)
    niagara_write_priority: int | None = Field(default=None, ge=1, le=16)
    brick_class: str | None = None

    @model_validator(mode="after")
    def bacnet_object_instance_is_valid(self) -> PointSpec:
        if self.bacnet_object is not None:
            object_instance = int(self.bacnet_object.rsplit(",", 1)[1])
            if object_instance > 4_194_302:
                raise ValueError("BACnet object instance exceeds 4,194,302")
        if self.niagara_ord is not None:
            normalized = self.niagara_ord.strip()
            if not re.fullmatch(
                r"(?:station:\|)?slot:/[A-Za-z0-9_$./-]+",
                normalized,
            ):
                raise ValueError(
                    "niagara_ord must be an exact station slot ord without queries or escapes"
                )
            slot_path = normalized.removeprefix("station:|").removeprefix("slot:/")
            if any(part in {"", ".", ".."} for part in slot_path.split("/")):
                raise ValueError("niagara_ord contains an invalid component path segment")
            self.niagara_ord = (
                normalized if normalized.startswith("station:|") else f"station:|{normalized}"
            )
        if self.niagara_write_priority is not None:
            if self.niagara_ord is None:
                raise ValueError("niagara_write_priority requires niagara_ord")
            if self.role not in {PointRole.COMMAND, PointRole.ALARM}:
                raise ValueError(
                    "niagara_write_priority is only valid for command or alarm points"
                )
        return self


class SequenceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family: str = Field(default="G36_VAV_REHEAT", pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    version: str = "ASHRAE Guideline 36-2021 inspired MVP"
    parameters: dict[str, JsonValue] = Field(default_factory=dict, max_length=128)
    library: Literal["plant_controls", "g36"] | None = None
    controller_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z][A-Za-z0-9_.]*$",
        max_length=240,
    )
    execution_profile: Literal["modelica_exact", "host_tick_v1"] = "modelica_exact"
    source_filename: str | None = Field(default=None, max_length=255)
    source_media_type: str | None = Field(default=None, max_length=200)
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_text: str | None = Field(default=None, max_length=2_000_000)

    @model_validator(mode="after")
    def library_reference_is_complete(self) -> SequenceSpec:
        if (self.library is None) != (self.controller_id is None):
            raise ValueError("sequence library and controller_id must be supplied together")
        expected_family = {
            "plant_controls": "LBNL_PLANT_CONTROLLER",
            "g36": "LBNL_G36_CONTROLLER",
        }.get(self.library)
        if expected_family is not None and self.family != expected_family:
            raise ValueError(f"{self.library} jobs must use sequence family {expected_family}")
        return self


class ComparisonOperator(StrEnum):
    EQUAL = "eq"
    NOT_EQUAL = "ne"
    GREATER_THAN = "gt"
    GREATER_THAN_OR_EQUAL = "gte"
    LESS_THAN = "lt"
    LESS_THAN_OR_EQUAL = "lte"
    BETWEEN = "between"


class OutputExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    operator: ComparisonOperator = ComparisonOperator.EQUAL
    value: float | bool
    upper: float | None = None
    tolerance: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def validate_range(self) -> OutputExpectation:
        if self.operator == ComparisonOperator.BETWEEN:
            if isinstance(self.value, bool) or self.upper is None:
                raise ValueError("between expectations require numeric value and upper")
            if float(self.value) > self.upper:
                raise ValueError("between expectation value cannot exceed upper")
        elif self.upper is not None:
            raise ValueError("upper is only valid for a between expectation")
        return self


class FaultKind(StrEnum):
    """Deterministic input faults supported by the Tier-1 qualification harness."""

    FORCE = "force"
    BIAS = "bias"
    SCALE = "scale"
    DRIFT = "drift"
    STUCK = "stuck"
    STALE = "stale"
    DROPOUT = "dropout"
    INVERT = "invert"


class FaultInjection(BaseModel):
    """A reviewable fault applied to a graph input during an acceptance case.

    ``quality_target`` names an optional Boolean input that is forced false while
    the fault is active. This lets sequences prove explicit invalid/stale-sensor
    fallback behavior without pretending that a numeric value carries BACnet
    reliability metadata by itself.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", max_length=120)
    target: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", max_length=120)
    kind: FaultKind
    value: float | bool | None = None
    quality_target: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
        max_length=120,
    )

    @model_validator(mode="after")
    def parameters_match_kind(self) -> FaultInjection:
        value_required = self.kind in {
            FaultKind.FORCE,
            FaultKind.BIAS,
            FaultKind.SCALE,
            FaultKind.DRIFT,
            FaultKind.DROPOUT,
        }
        if value_required and self.value is None:
            raise ValueError(f"{self.kind.value} fault requires value")
        if not value_required and self.value is not None:
            raise ValueError(f"{self.kind.value} fault does not accept value")
        if self.kind in {FaultKind.BIAS, FaultKind.SCALE, FaultKind.DRIFT}:
            if (
                isinstance(self.value, bool)
                or not isinstance(self.value, (int, float))
                or not math.isfinite(float(self.value))
            ):
                raise ValueError(f"{self.kind.value} fault value must be finite numeric")
        if self.quality_target == self.target:
            raise ValueError("fault quality_target must differ from target")
        return self


class AcceptancePhase(BaseModel):
    """One input regime in a stateful acceptance-test timeline."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    inputs: dict[str, float | bool] = Field(default_factory=dict)
    repeat: int = Field(default=1, ge=1, le=1_000_000)
    step_seconds: float = Field(default=1.0, gt=0.0, le=86_400.0)
    faults: list[FaultInjection] = Field(default_factory=list, max_length=1_000)
    expectations: list[OutputExpectation] = Field(default_factory=list)

    @model_validator(mode="after")
    def fault_ids_are_unique(self) -> AcceptancePhase:
        ids = [fault.id for fault in self.faults]
        if len(ids) != len(set(ids)):
            raise ValueError("fault ids must be unique within an acceptance phase")
        return self


class AcceptanceCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    inputs: dict[str, float | bool] = Field(default_factory=dict)
    expectations: list[OutputExpectation] = Field(min_length=1)
    repeat: int = Field(default=1, ge=1, le=1_000_000)
    step_seconds: float = Field(default=1.0, gt=0.0, le=86_400.0)
    faults: list[FaultInjection] = Field(default_factory=list, max_length=1_000)
    timeline: list[AcceptancePhase] = Field(default_factory=list, max_length=10_000)

    @model_validator(mode="after")
    def validate_timeline_mode(self) -> AcceptanceCase:
        if self.timeline and self.inputs:
            raise ValueError("timeline acceptance cases cannot also declare top-level inputs")
        if self.timeline and self.faults:
            raise ValueError("timeline acceptance cases declare faults on individual phases")
        if self.timeline and (self.repeat != 1 or self.step_seconds != 1.0):
            raise ValueError("timeline acceptance cases set repeat and step_seconds on each phase")
        phase_names = [phase.name for phase in self.timeline]
        if len(phase_names) != len(set(phase_names)):
            raise ValueError("acceptance phase names must be unique within a case")
        fault_ids = [fault.id for fault in self.faults]
        if len(fault_ids) != len(set(fault_ids)):
            raise ValueError("fault ids must be unique within an acceptance case")
        return self


class AlarmRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    point: str = Field(min_length=1, max_length=500)
    alarm_class: str = Field(min_length=1, max_length=120)
    priority: int = Field(ge=1, le=255)
    delay_seconds: float = Field(default=0.0, ge=0.0, le=86_400.0)
    acknowledgement_required: bool = True
    offnormal_text: str = Field(default="Alarm", min_length=1, max_length=240)
    normal_text: str = Field(default="Normal", min_length=1, max_length=240)
    routing: list[str] = Field(default_factory=list, max_length=100)
    trigger: Literal["boolean_true", "boolean_false", "above", "below", "outside_range"] = (
        "boolean_true"
    )
    high_limit: float | None = None
    low_limit: float | None = None
    deadband: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def routing_is_unique(self) -> AlarmRequirement:
        if len(self.routing) != len(set(self.routing)):
            raise ValueError("alarm routing destinations must be unique")
        if self.trigger in {"boolean_true", "boolean_false"}:
            if self.high_limit is not None or self.low_limit is not None or self.deadband != 0:
                raise ValueError("boolean alarms cannot declare numeric limits or deadband")
        elif self.trigger == "above":
            if self.high_limit is None or self.low_limit is not None:
                raise ValueError("above alarms require high_limit only")
        elif self.trigger == "below":
            if self.low_limit is None or self.high_limit is not None:
                raise ValueError("below alarms require low_limit only")
        elif self.trigger == "outside_range":
            if self.low_limit is None or self.high_limit is None:
                raise ValueError("outside_range alarms require low_limit and high_limit")
            if self.low_limit >= self.high_limit:
                raise ValueError("alarm low_limit must be below high_limit")
        return self


class WeeklySchedulePeriod(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    start: str = Field(pattern=r"^[0-2][0-9]:[0-5][0-9]$")
    end: str = Field(pattern=r"^[0-2][0-9]:[0-5][0-9]$")
    value: float | bool = True

    @model_validator(mode="after")
    def period_is_forward(self) -> WeeklySchedulePeriod:
        try:
            start = time.fromisoformat(self.start)
            end = time.fromisoformat(self.end)
        except ValueError as exc:
            raise ValueError("schedule times must be valid 24-hour HH:MM values") from exc
        if start >= end:
            raise ValueError("schedule period end must be later than start")
        return self


class ScheduleRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    output_point: str = Field(min_length=1, max_length=500)
    timezone: str = Field(min_length=1, max_length=120)
    default_value: float | bool = False
    weekly_periods: list[WeeklySchedulePeriod] = Field(default_factory=list, max_length=500)
    holiday_calendar: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def timezone_exists(self) -> ScheduleRequirement:
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA timezone: {self.timezone}") from exc
        periods_by_day: dict[str, list[WeeklySchedulePeriod]] = defaultdict(list)
        for period in self.weekly_periods:
            if isinstance(self.default_value, bool) != isinstance(period.value, bool):
                raise ValueError("schedule period values must match the default value type")
            periods_by_day[period.day].append(period)
        for day, periods in periods_by_day.items():
            ordered = sorted(periods, key=lambda item: item.start)
            for previous, current in zip(ordered, ordered[1:], strict=False):
                if current.start < previous.end:
                    raise ValueError(f"schedule periods overlap on {day}")
        return self


class HistoryRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    point: str = Field(min_length=1, max_length=500)
    mode: Literal["fixed_interval", "cov"]
    interval_seconds: int | None = Field(default=None, ge=1, le=86_400)
    cov_tolerance: float | None = Field(default=None, gt=0)
    retention_days: int = Field(ge=1, le=36_500)

    @model_validator(mode="after")
    def mode_parameters_match(self) -> HistoryRequirement:
        if self.mode == "fixed_interval" and (
            self.interval_seconds is None or self.cov_tolerance is not None
        ):
            raise ValueError("fixed_interval history requires interval_seconds only")
        if self.mode == "cov" and (self.cov_tolerance is None or self.interval_seconds is not None):
            raise ValueError("cov history requires cov_tolerance only")
        return self


class GraphicsViewRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    title: str = Field(min_length=1, max_length=200)
    points: list[str] = Field(min_length=1, max_length=1_000)
    template: str | None = Field(default=None, max_length=240)
    navigation_parent: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def points_are_unique(self) -> GraphicsViewRequirement:
        if len(self.points) != len(set(self.points)):
            raise ValueError("graphics view points must be unique")
        return self


class ShopProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=120)
    station_folder: str | None = Field(default=None, max_length=500)
    niagara_site_ord: str | None = Field(default=None, max_length=1_000)
    niagara_equipment_ord: str | None = Field(default=None, max_length=1_000)
    station_template_mode: Literal["compare_only", "insert", "replace"] = "compare_only"
    graphics_theme: str | None = Field(default=None, max_length=240)
    tag_dictionary: Literal["brick", "haystack", "dual"] = "dual"

    @model_validator(mode="after")
    def station_folder_is_relative(self) -> ShopProfile:
        if self.station_folder:
            normalized_folder = self.station_folder.replace("\\", "/")
            parts = normalized_folder.split("/")
            if (
                ".." in parts
                or self.station_folder.startswith(("/", "\\"))
                or any(not re.fullmatch(r"[A-Za-z0-9_$.-]+", part) for part in parts)
            ):
                raise ValueError("station_folder must be a relative Niagara component path")
            self.station_folder = normalized_folder
        for field_name in ("niagara_site_ord", "niagara_equipment_ord"):
            value = getattr(self, field_name)
            if value is None:
                continue
            normalized = value.strip()
            if not re.fullmatch(r"(?:station:\|)?slot:/[A-Za-z0-9_$./-]+", normalized):
                raise ValueError(
                    f"{field_name} must be an exact station slot ord without queries or escapes"
                )
            slot_path = normalized.removeprefix("station:|").removeprefix("slot:/")
            if any(part in {"", ".", ".."} for part in slot_path.split("/")):
                raise ValueError(f"{field_name} contains an invalid component path segment")
            setattr(
                self,
                field_name,
                normalized if normalized.startswith("station:|") else f"station:|{normalized}",
            )
        return self


class DeliverableRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    shop_profile: ShopProfile | None = None
    alarms: list[AlarmRequirement] = Field(default_factory=list, max_length=10_000)
    schedules: list[ScheduleRequirement] = Field(default_factory=list, max_length=1_000)
    histories: list[HistoryRequirement] = Field(default_factory=list, max_length=10_000)
    graphics: list[GraphicsViewRequirement] = Field(default_factory=list, max_length=1_000)

    @model_validator(mode="after")
    def identifiers_are_unique(self) -> DeliverableRequirements:
        collections = {
            "alarm points": [item.point for item in self.alarms],
            "schedule ids": [item.id for item in self.schedules],
            "schedule output points": [item.output_point for item in self.schedules],
            "history points": [item.point for item in self.histories],
            "graphics ids": [item.id for item in self.graphics],
        }
        for label, values in collections.items():
            if len(values) != len(set(values)):
                raise ValueError(f"{label} must be unique")
        return self


class JobSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    site: str
    equipment_name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    equipment_brick_class: str = "brick:Equipment"
    sequence: SequenceSpec = Field(default_factory=SequenceSpec)
    points: list[PointSpec]
    control_graph: ControlGraph | None = None
    acceptance_tests: list[AcceptanceCase] = Field(default_factory=list)
    deliverables: DeliverableRequirements = Field(default_factory=DeliverableRequirements)
    bacnet_scan: BacnetScan | None = None
    template_bog: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def unique_points(self) -> JobSpec:
        names = [point.name for point in self.points]
        if len(names) != len(set(names)):
            raise ValueError("point names must be unique")
        points = {point.name: point for point in self.points}
        for alarm in self.deliverables.alarms:
            point = points.get(alarm.point)
            if point is None:
                raise ValueError(f"alarm requirement references unknown point {alarm.point}")
            if point.role != PointRole.ALARM:
                raise ValueError(f"alarm requirement point {alarm.point} must have alarm role")
            boolean_trigger = alarm.trigger in {"boolean_true", "boolean_false"}
            if point.data_type == DataType.BOOLEAN and not boolean_trigger:
                raise ValueError(f"boolean alarm point {alarm.point} requires a boolean trigger")
            if point.data_type == DataType.NUMERIC and boolean_trigger:
                raise ValueError(f"numeric alarm point {alarm.point} requires numeric limits")
        for schedule in self.deliverables.schedules:
            point = points.get(schedule.output_point)
            if point is None:
                raise ValueError(
                    f"schedule {schedule.id} references unknown point {schedule.output_point}"
                )
            if point.data_type == DataType.BOOLEAN and not isinstance(schedule.default_value, bool):
                raise ValueError(f"schedule {schedule.id} default must be boolean")
            if point.data_type == DataType.NUMERIC and isinstance(schedule.default_value, bool):
                raise ValueError(f"schedule {schedule.id} default must be numeric")
            for period in schedule.weekly_periods:
                if point.data_type == DataType.BOOLEAN and not isinstance(period.value, bool):
                    raise ValueError(f"schedule {schedule.id} period values must be boolean")
                if point.data_type == DataType.NUMERIC and isinstance(period.value, bool):
                    raise ValueError(f"schedule {schedule.id} period values must be numeric")
        for history in self.deliverables.histories:
            if history.point not in points:
                raise ValueError(f"history requirement references unknown point {history.point}")
        for view in self.deliverables.graphics:
            unknown = sorted(set(view.points) - set(points))
            if unknown:
                raise ValueError(
                    f"graphics view {view.id} references unknown points: {', '.join(unknown)}"
                )
        if self.bacnet_scan is not None:
            devices = {item.device_instance: item for item in self.bacnet_scan.devices}
            sole_device = next(iter(devices.values())) if len(devices) == 1 else None
            for point in self.points:
                if point.bacnet_object is None:
                    continue
                device = devices.get(point.bacnet_device_instance) or sole_device
                if device is None:
                    raise ValueError(f"point {point.name} has no matching BACnet device")
                if point.bacnet_device_instance is None:
                    point.bacnet_device_instance = device.device_instance
                objects = {item.object_id: item for item in device.objects}
                scanned_object = objects.get(point.bacnet_object)
                if scanned_object is None:
                    raise ValueError(
                        f"point {point.name} references missing BACnet object {point.bacnet_object}"
                    )
                if scanned_object.data_type != point.data_type:
                    raise ValueError(
                        f"point {point.name} type does not match BACnet object "
                        f"{point.bacnet_object}"
                    )
                if point.role == PointRole.COMMAND and not scanned_object.writable:
                    raise ValueError(f"command point {point.name} maps to a read-only object")
        return self


class BlockKind(StrEnum):
    NUMERIC_INPUT = "numeric_input"
    BOOLEAN_INPUT = "boolean_input"
    NUMERIC_OUTPUT = "numeric_output"
    BOOLEAN_OUTPUT = "boolean_output"
    NUMERIC_CONST = "numeric_const"
    BOOLEAN_CONST = "boolean_const"
    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"
    MINIMUM = "minimum"
    MAXIMUM = "maximum"
    AVERAGE = "average"
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    EQUAL = "equal"
    NOT_EQUAL = "not_equal"
    AND = "and"
    OR = "or"
    XOR = "xor"
    NOT = "not"
    NUMERIC_SWITCH = "numeric_switch"
    BOOLEAN_SWITCH = "boolean_switch"
    BOOLEAN_DELAY = "boolean_delay"
    ONE_SHOT = "one_shot"
    BOOLEAN_FALLING_EDGE = "boolean_falling_edge"
    MOVING_AVERAGE = "moving_average"
    NUMERIC_SAMPLER = "numeric_sampler"
    NUMERIC_UNIT_DELAY = "numeric_unit_delay"
    NUMERIC_CHANGED = "numeric_changed"
    NUMERIC_INCREASED = "numeric_increased"
    NUMERIC_DECREASED = "numeric_decreased"
    NUMERIC_LATCH = "numeric_latch"
    BOOLEAN_LATCH = "boolean_latch"
    BOOLEAN_PRE_HOST_TICK = "boolean_pre_host_tick"
    BOOLEAN_INITIALIZATION = "boolean_initialization"
    BOOLEAN_SET_RESET = "boolean_set_reset"
    BOOLEAN_TRUE_FALSE_HOLD = "boolean_true_false_hold"
    HYSTERESIS = "hysteresis"
    TIMER = "timer"
    TIMER_WITH_RESET = "timer_with_reset"
    TIMER_ACCUMULATING = "timer_accumulating"
    BOOLEAN_ASSERT_WARNING = "boolean_assert_warning"
    TRIM_AND_RESPOND = "trim_and_respond"
    TRIM_AND_RESPOND_HOLD = "trim_and_respond_hold"
    RESET = "reset"
    PI_LOOP = "pi_loop"
    PID_WITH_RESET = "pid_with_reset"
    PLANT_EQUIPMENT_AVAILABILITY = "plant_equipment_availability"
    PLANT_ENABLE = "plant_enable"
    PLANT_HRC_ENABLE = "plant_hrc_enable"
    PLANT_HRC_MODE_CONTROL = "plant_hrc_mode_control"
    PLANT_STAGE_COMPLETION = "plant_stage_completion"
    PLANT_STAGE_INDEX = "plant_stage_index"


class SlotSpec(BaseModel):
    inputs: dict[str, DataType] = Field(default_factory=dict)
    outputs: dict[str, DataType] = Field(default_factory=dict)


BLOCK_SLOTS: dict[BlockKind, SlotSpec] = {
    BlockKind.NUMERIC_INPUT: SlotSpec(outputs={"out": DataType.NUMERIC}),
    BlockKind.BOOLEAN_INPUT: SlotSpec(outputs={"out": DataType.BOOLEAN}),
    BlockKind.NUMERIC_OUTPUT: SlotSpec(
        inputs={"in": DataType.NUMERIC}, outputs={"out": DataType.NUMERIC}
    ),
    BlockKind.BOOLEAN_OUTPUT: SlotSpec(
        inputs={"in": DataType.BOOLEAN}, outputs={"out": DataType.BOOLEAN}
    ),
    BlockKind.NUMERIC_CONST: SlotSpec(outputs={"out": DataType.NUMERIC}),
    BlockKind.BOOLEAN_CONST: SlotSpec(outputs={"out": DataType.BOOLEAN}),
    BlockKind.ADD: SlotSpec(
        inputs={"a": DataType.NUMERIC, "b": DataType.NUMERIC}, outputs={"out": DataType.NUMERIC}
    ),
    BlockKind.SUBTRACT: SlotSpec(
        inputs={"a": DataType.NUMERIC, "b": DataType.NUMERIC}, outputs={"out": DataType.NUMERIC}
    ),
    BlockKind.MULTIPLY: SlotSpec(
        inputs={"a": DataType.NUMERIC, "b": DataType.NUMERIC}, outputs={"out": DataType.NUMERIC}
    ),
    BlockKind.DIVIDE: SlotSpec(
        inputs={"a": DataType.NUMERIC, "b": DataType.NUMERIC}, outputs={"out": DataType.NUMERIC}
    ),
    BlockKind.MINIMUM: SlotSpec(
        inputs={"a": DataType.NUMERIC, "b": DataType.NUMERIC}, outputs={"out": DataType.NUMERIC}
    ),
    BlockKind.MAXIMUM: SlotSpec(
        inputs={"a": DataType.NUMERIC, "b": DataType.NUMERIC}, outputs={"out": DataType.NUMERIC}
    ),
    BlockKind.AVERAGE: SlotSpec(
        inputs={"a": DataType.NUMERIC, "b": DataType.NUMERIC}, outputs={"out": DataType.NUMERIC}
    ),
    BlockKind.GREATER_THAN: SlotSpec(
        inputs={"a": DataType.NUMERIC, "b": DataType.NUMERIC}, outputs={"out": DataType.BOOLEAN}
    ),
    BlockKind.GREATER_THAN_OR_EQUAL: SlotSpec(
        inputs={"a": DataType.NUMERIC, "b": DataType.NUMERIC}, outputs={"out": DataType.BOOLEAN}
    ),
    BlockKind.LESS_THAN: SlotSpec(
        inputs={"a": DataType.NUMERIC, "b": DataType.NUMERIC}, outputs={"out": DataType.BOOLEAN}
    ),
    BlockKind.LESS_THAN_OR_EQUAL: SlotSpec(
        inputs={"a": DataType.NUMERIC, "b": DataType.NUMERIC}, outputs={"out": DataType.BOOLEAN}
    ),
    BlockKind.EQUAL: SlotSpec(
        inputs={"a": DataType.NUMERIC, "b": DataType.NUMERIC}, outputs={"out": DataType.BOOLEAN}
    ),
    BlockKind.NOT_EQUAL: SlotSpec(
        inputs={"a": DataType.NUMERIC, "b": DataType.NUMERIC}, outputs={"out": DataType.BOOLEAN}
    ),
    BlockKind.AND: SlotSpec(
        inputs={"a": DataType.BOOLEAN, "b": DataType.BOOLEAN}, outputs={"out": DataType.BOOLEAN}
    ),
    BlockKind.OR: SlotSpec(
        inputs={"a": DataType.BOOLEAN, "b": DataType.BOOLEAN}, outputs={"out": DataType.BOOLEAN}
    ),
    BlockKind.XOR: SlotSpec(
        inputs={"a": DataType.BOOLEAN, "b": DataType.BOOLEAN}, outputs={"out": DataType.BOOLEAN}
    ),
    BlockKind.NOT: SlotSpec(inputs={"in": DataType.BOOLEAN}, outputs={"out": DataType.BOOLEAN}),
    BlockKind.NUMERIC_SWITCH: SlotSpec(
        inputs={
            "selector": DataType.BOOLEAN,
            "when_true": DataType.NUMERIC,
            "when_false": DataType.NUMERIC,
        },
        outputs={"out": DataType.NUMERIC},
    ),
    BlockKind.BOOLEAN_SWITCH: SlotSpec(
        inputs={
            "selector": DataType.BOOLEAN,
            "when_true": DataType.BOOLEAN,
            "when_false": DataType.BOOLEAN,
        },
        outputs={"out": DataType.BOOLEAN},
    ),
    BlockKind.BOOLEAN_DELAY: SlotSpec(
        inputs={"in": DataType.BOOLEAN}, outputs={"out": DataType.BOOLEAN}
    ),
    BlockKind.ONE_SHOT: SlotSpec(
        inputs={"in": DataType.BOOLEAN}, outputs={"out": DataType.BOOLEAN}
    ),
    BlockKind.BOOLEAN_FALLING_EDGE: SlotSpec(
        inputs={"in": DataType.BOOLEAN}, outputs={"out": DataType.BOOLEAN}
    ),
    BlockKind.MOVING_AVERAGE: SlotSpec(
        inputs={"in": DataType.NUMERIC}, outputs={"out": DataType.NUMERIC}
    ),
    BlockKind.NUMERIC_SAMPLER: SlotSpec(
        inputs={"in": DataType.NUMERIC}, outputs={"out": DataType.NUMERIC}
    ),
    BlockKind.NUMERIC_UNIT_DELAY: SlotSpec(
        inputs={"in": DataType.NUMERIC}, outputs={"out": DataType.NUMERIC}
    ),
    BlockKind.NUMERIC_CHANGED: SlotSpec(
        inputs={"in": DataType.NUMERIC}, outputs={"out": DataType.BOOLEAN}
    ),
    BlockKind.NUMERIC_INCREASED: SlotSpec(
        inputs={"in": DataType.NUMERIC}, outputs={"out": DataType.BOOLEAN}
    ),
    BlockKind.NUMERIC_DECREASED: SlotSpec(
        inputs={"in": DataType.NUMERIC}, outputs={"out": DataType.BOOLEAN}
    ),
    BlockKind.NUMERIC_LATCH: SlotSpec(
        inputs={"in": DataType.NUMERIC, "clock": DataType.BOOLEAN},
        outputs={"out": DataType.NUMERIC},
    ),
    BlockKind.BOOLEAN_LATCH: SlotSpec(
        inputs={"in": DataType.BOOLEAN, "clock": DataType.BOOLEAN},
        outputs={"out": DataType.BOOLEAN},
    ),
    BlockKind.BOOLEAN_PRE_HOST_TICK: SlotSpec(
        inputs={"in": DataType.BOOLEAN}, outputs={"out": DataType.BOOLEAN}
    ),
    BlockKind.BOOLEAN_INITIALIZATION: SlotSpec(
        inputs={"in": DataType.BOOLEAN}, outputs={"out": DataType.BOOLEAN}
    ),
    BlockKind.BOOLEAN_SET_RESET: SlotSpec(
        inputs={"set": DataType.BOOLEAN, "clear": DataType.BOOLEAN},
        outputs={"out": DataType.BOOLEAN},
    ),
    BlockKind.BOOLEAN_TRUE_FALSE_HOLD: SlotSpec(
        inputs={"in": DataType.BOOLEAN}, outputs={"out": DataType.BOOLEAN}
    ),
    BlockKind.HYSTERESIS: SlotSpec(
        inputs={"in": DataType.NUMERIC}, outputs={"out": DataType.BOOLEAN}
    ),
    BlockKind.TIMER: SlotSpec(
        inputs={"in": DataType.BOOLEAN},
        outputs={"elapsed": DataType.NUMERIC, "passed": DataType.BOOLEAN},
    ),
    BlockKind.TIMER_WITH_RESET: SlotSpec(
        inputs={"in": DataType.BOOLEAN, "reset": DataType.BOOLEAN},
        outputs={"elapsed": DataType.NUMERIC, "passed": DataType.BOOLEAN},
    ),
    BlockKind.TIMER_ACCUMULATING: SlotSpec(
        inputs={"in": DataType.BOOLEAN, "reset": DataType.BOOLEAN},
        outputs={"elapsed": DataType.NUMERIC, "passed": DataType.BOOLEAN},
    ),
    BlockKind.BOOLEAN_ASSERT_WARNING: SlotSpec(
        inputs={"condition": DataType.BOOLEAN}, outputs={"ok": DataType.BOOLEAN}
    ),
    BlockKind.TRIM_AND_RESPOND: SlotSpec(
        inputs={
            "request_count": DataType.NUMERIC,
            "device_on": DataType.BOOLEAN,
        },
        outputs={"out": DataType.NUMERIC},
    ),
    BlockKind.TRIM_AND_RESPOND_HOLD: SlotSpec(
        inputs={
            "request_count": DataType.NUMERIC,
            "device_on": DataType.BOOLEAN,
            "hold": DataType.BOOLEAN,
        },
        outputs={"out": DataType.NUMERIC},
    ),
    BlockKind.RESET: SlotSpec(
        inputs={
            "in": DataType.NUMERIC,
            "input_low": DataType.NUMERIC,
            "input_high": DataType.NUMERIC,
            "output_low": DataType.NUMERIC,
            "output_high": DataType.NUMERIC,
        },
        outputs={"out": DataType.NUMERIC},
    ),
    BlockKind.PI_LOOP: SlotSpec(
        inputs={
            "enable": DataType.BOOLEAN,
            "controlled_variable": DataType.NUMERIC,
            "setpoint": DataType.NUMERIC,
            "direct": DataType.BOOLEAN,
        },
        outputs={"out": DataType.NUMERIC},
    ),
    BlockKind.PID_WITH_RESET: SlotSpec(
        inputs={
            "setpoint": DataType.NUMERIC,
            "measurement": DataType.NUMERIC,
            "trigger": DataType.BOOLEAN,
        },
        outputs={"out": DataType.NUMERIC},
    ),
    BlockKind.PLANT_EQUIPMENT_AVAILABILITY: SlotSpec(
        inputs={
            "enableHeating": DataType.BOOLEAN,
            "enableCooling": DataType.BOOLEAN,
            "available": DataType.BOOLEAN,
        },
        outputs={
            "heatingAvailable": DataType.BOOLEAN,
            "coolingAvailable": DataType.BOOLEAN,
        },
    ),
    BlockKind.PLANT_ENABLE: SlotSpec(
        inputs={
            "scheduleEnabled": DataType.BOOLEAN,
            "requestCount": DataType.NUMERIC,
            "outdoorTemperature": DataType.NUMERIC,
        },
        outputs={"out": DataType.BOOLEAN},
    ),
    BlockKind.PLANT_HRC_ENABLE: SlotSpec(
        inputs={
            "coolingPlantEnable": DataType.BOOLEAN,
            "heatingPlantEnable": DataType.BOOLEAN,
            "hrcStatus": DataType.BOOLEAN,
            "coolingLoad": DataType.NUMERIC,
            "heatingLoad": DataType.NUMERIC,
            "chilledLeavingTemperature": DataType.NUMERIC,
            "heatingLeavingTemperature": DataType.NUMERIC,
            "coolingMode": DataType.BOOLEAN,
        },
        outputs={
            "enable": DataType.BOOLEAN,
            "setMode": DataType.BOOLEAN,
        },
    ),
    BlockKind.PLANT_HRC_MODE_CONTROL: SlotSpec(
        inputs={
            "setMode": DataType.BOOLEAN,
            "coolingLoad": DataType.NUMERIC,
            "heatingLoad": DataType.NUMERIC,
            "chilledSetpoint": DataType.NUMERIC,
            "heatingSetpoint": DataType.NUMERIC,
        },
        outputs={
            "coolingMode": DataType.BOOLEAN,
            "supplySetpoint": DataType.NUMERIC,
        },
    ),
    BlockKind.PLANT_STAGE_COMPLETION: SlotSpec(
        inputs={
            "commandMask": DataType.NUMERIC,
            "statusMask": DataType.NUMERIC,
            "stage": DataType.NUMERIC,
        },
        outputs={
            "inProgress": DataType.BOOLEAN,
            "completed": DataType.BOOLEAN,
        },
    ),
    BlockKind.PLANT_STAGE_INDEX: SlotSpec(
        inputs={
            "leadEnable": DataType.BOOLEAN,
            "stageUp": DataType.BOOLEAN,
            "stageDown": DataType.BOOLEAN,
            "availabilityMask": DataType.NUMERIC,
        },
        outputs={"stage": DataType.NUMERIC},
    ),
}


class Block(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    kind: BlockKind
    label: str
    config: dict[str, Any] = Field(default_factory=dict)
    x: int = 0
    y: int = 0

    @model_validator(mode="after")
    def validate_config(self) -> Block:
        override = self.config.get("niagara_override")
        if override is not None:
            if not isinstance(override, dict) or set(override) != {"type_spec"}:
                raise ValueError("niagara_override requires exactly one type_spec field")
            type_spec = override["type_spec"]
            if not isinstance(type_spec, str) or not re.fullmatch(
                r"[A-Za-z][A-Za-z0-9_.-]*:[A-Za-z][A-Za-z0-9_$.-]*",
                type_spec,
            ):
                raise ValueError("niagara_override.type_spec is invalid")
        if self.kind == BlockKind.NUMERIC_CONST:
            value = self.config.get("value")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("numeric_const requires a numeric config.value")
        if self.kind == BlockKind.BOOLEAN_CONST and not isinstance(self.config.get("value"), bool):
            raise ValueError("boolean_const requires a boolean config.value")
        if self.kind == BlockKind.NUMERIC_INPUT and "default" in self.config:
            default = self.config["default"]
            if isinstance(default, bool) or not isinstance(default, (int, float)):
                raise ValueError("numeric_input config.default must be numeric")
        if self.kind == BlockKind.BOOLEAN_INPUT and "default" in self.config:
            if not isinstance(self.config["default"], bool):
                raise ValueError("boolean_input config.default must be boolean")
        if self.kind == BlockKind.BOOLEAN_DELAY:
            for key in ("on_delay_seconds", "off_delay_seconds"):
                value = self.config.get(key, 0.0)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                    raise ValueError(f"boolean_delay config.{key} must be non-negative numeric")
            if not isinstance(self.config.get("delay_on_init", True), bool):
                raise ValueError("boolean_delay config.delay_on_init must be boolean")
        if self.kind == BlockKind.BOOLEAN_FALLING_EDGE and not isinstance(
            self.config.get("pre_u_start", False), bool
        ):
            raise ValueError("boolean_falling_edge config.pre_u_start must be boolean")
        if self.kind == BlockKind.NUMERIC_LATCH:
            initial = self.config.get("initial", 0.0)
            if isinstance(initial, bool) or not isinstance(initial, (int, float)):
                raise ValueError("numeric_latch config.initial must be numeric")
        if self.kind == BlockKind.BOOLEAN_LATCH and not isinstance(
            self.config.get("initial", False), bool
        ):
            raise ValueError("boolean_latch config.initial must be boolean")
        if self.kind == BlockKind.BOOLEAN_INITIALIZATION and not isinstance(
            self.config.get("initial", False), bool
        ):
            raise ValueError("boolean_initialization config.initial must be boolean")
        if self.kind == BlockKind.HYSTERESIS:
            low = self.config.get("u_low")
            high = self.config.get("u_high")
            for key, value in (("u_low", low), ("u_high", high)):
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                ):
                    raise ValueError(f"hysteresis config.{key} must be finite numeric")
            if float(high) <= float(low):
                raise ValueError("hysteresis u_high must be greater than u_low")
            if not isinstance(self.config.get("initial", False), bool):
                raise ValueError("hysteresis config.initial must be boolean")
        if self.kind in {
            BlockKind.TIMER,
            BlockKind.TIMER_WITH_RESET,
            BlockKind.TIMER_ACCUMULATING,
        }:
            threshold = self.config.get("threshold_seconds", 0.0)
            if (
                isinstance(threshold, bool)
                or not isinstance(threshold, (int, float))
                or not math.isfinite(float(threshold))
            ):
                raise ValueError("timer config.threshold_seconds must be finite numeric")
        if self.kind == BlockKind.BOOLEAN_ASSERT_WARNING:
            message = self.config.get("message")
            if not isinstance(message, str) or not 1 <= len(message) <= 2_000:
                raise ValueError(
                    "boolean_assert_warning config.message must be 1 through 2000 characters"
                )
        if self.kind == BlockKind.BOOLEAN_TRUE_FALSE_HOLD:
            for key in ("true_hold_seconds", "false_hold_seconds"):
                value = self.config.get(key)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                ):
                    raise ValueError(
                        f"boolean_true_false_hold config.{key} must be finite numeric"
                    )
        if self.kind in {
            BlockKind.TRIM_AND_RESPOND,
            BlockKind.TRIM_AND_RESPOND_HOLD,
        }:
            required = {
                "initial_setpoint",
                "minimum_setpoint",
                "maximum_setpoint",
                "delay_seconds",
                "sample_period_seconds",
                "ignored_requests",
                "trim_amount",
                "respond_amount",
                "maximum_response",
            }
            missing = sorted(required - set(self.config))
            if missing:
                raise ValueError(
                    "trim_and_respond missing config: " + ", ".join(missing)
                )
            values: dict[str, float] = {}
            for key in sorted(required):
                value = self.config[key]
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                ):
                    raise ValueError(f"trim_and_respond config.{key} must be finite numeric")
                values[key] = float(value)
            if values["sample_period_seconds"] < 0.001:
                raise ValueError(
                    "trim_and_respond sample_period_seconds must be at least 0.001"
                )
            if values["delay_seconds"] < 0:
                raise ValueError("trim_and_respond delay_seconds must be non-negative")
            if values["ignored_requests"] < 0:
                raise ValueError("trim_and_respond ignored_requests must be non-negative")
            if not (
                values["minimum_setpoint"]
                <= values["initial_setpoint"]
                <= values["maximum_setpoint"]
            ):
                raise ValueError(
                    "trim_and_respond setpoints must satisfy minimum <= initial <= maximum"
                )
            if values["trim_amount"] * values["respond_amount"] >= 0:
                raise ValueError(
                    "trim_and_respond trim_amount and respond_amount must have opposite signs"
                )
            if values["respond_amount"] * values["maximum_response"] <= 0:
                raise ValueError(
                    "trim_and_respond respond_amount and maximum_response must have the same sign"
                )
            hold_enabled = self.config.get("hold_enabled", False)
            expected_hold = self.kind == BlockKind.TRIM_AND_RESPOND_HOLD
            if hold_enabled is not expected_hold:
                raise ValueError(
                    "trim_and_respond hold_enabled must match its typed block kind"
                )
            if expected_hold:
                duration = self.config.get("hold_duration_seconds")
                if (
                    isinstance(duration, bool)
                    or not isinstance(duration, (int, float))
                    or not math.isfinite(float(duration))
                    or float(duration) < 0
                ):
                    raise ValueError(
                        "trim_and_respond_hold config.hold_duration_seconds must be "
                        "finite and non-negative"
                    )
        if self.kind == BlockKind.PI_LOOP:
            for key in (
                "proportional_constant",
                "integral_constant",
                "output_min",
                "output_max",
                "bias",
            ):
                value = self.config.get(key, 0.0)
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"pi_loop config.{key} must be numeric")
            if float(self.config.get("proportional_constant", 0.0)) < 0:
                raise ValueError("pi_loop proportional_constant must be non-negative")
            if float(self.config.get("integral_constant", 0.0)) < 0:
                raise ValueError("pi_loop integral_constant must be non-negative")
            if float(self.config.get("output_min", 0.0)) >= float(
                self.config.get("output_max", 100.0)
            ):
                raise ValueError("pi_loop output_min must be below output_max")
        if self.kind == BlockKind.PID_WITH_RESET:
            controller_type = self.config.get("controller_type", "PI")
            if controller_type not in {"P", "PI", "PD", "PID"}:
                raise ValueError("pid_with_reset controller_type must be P, PI, PD, or PID")
            for key, default in {
                "k": 1.0,
                "ti": 0.5,
                "td": 0.1,
                "r": 1.0,
                "ni": 0.9,
                "nd": 10.0,
            }.items():
                value = self.config.get(key, default)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                    or float(value) < 1e-13
                ):
                    raise ValueError(f"pid_with_reset config.{key} must be finite and >= 1e-13")
            for key, default in {
                "y_min": 0.0,
                "y_max": 1.0,
                "xi_start": 0.0,
                "yd_start": 0.0,
                "y_reset": self.config.get("xi_start", 0.0),
            }.items():
                value = self.config.get(key, default)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                ):
                    raise ValueError(f"pid_with_reset config.{key} must be finite numeric")
            if float(self.config.get("y_min", 0.0)) >= float(
                self.config.get("y_max", 1.0)
            ):
                raise ValueError("pid_with_reset y_min must be below y_max")
            if not isinstance(self.config.get("reverse_acting", True), bool):
                raise ValueError("pid_with_reset reverse_acting must be boolean")
        if self.kind == BlockKind.PLANT_EQUIPMENT_AVAILABILITY:
            semantic_contract = (
                "Buildings.Templates.Plants.Controls.StagingRotation."
                "EquipmentAvailability"
            )
            if self.config.get("semantic_contract") != semantic_contract:
                raise ValueError(
                    "plant_equipment_availability requires its pinned semantic contract"
                )
            duration = self.config.get("off_time_seconds")
            if (
                isinstance(duration, bool)
                or not isinstance(duration, (int, float))
                or not math.isfinite(float(duration))
                or duration < 0
            ):
                raise ValueError(
                    "plant_equipment_availability config.off_time_seconds must be "
                    "non-negative finite numeric"
                )
            for name in ("have_heating", "have_cooling"):
                if not isinstance(self.config.get(name), bool):
                    raise ValueError(
                        f"plant_equipment_availability config.{name} must be Boolean"
                    )
            if not (self.config["have_heating"] or self.config["have_cooling"]):
                raise ValueError(
                    "plant_equipment_availability requires at least one active loop"
                )
        if self.kind == BlockKind.PLANT_ENABLE:
            semantic_contract = (
                "Buildings.Templates.Plants.Controls.Enabling.Enable"
            )
            if self.config.get("semantic_contract") != semantic_contract:
                raise ValueError("plant_enable requires its pinned semantic contract")
            if self.config.get("application") not in {"Heating", "Cooling"}:
                raise ValueError("plant_enable config.application must be Heating or Cooling")
            if not isinstance(self.config.get("have_input_schedule"), bool):
                raise ValueError("plant_enable config.have_input_schedule must be Boolean")
            for name in (
                "outdoor_lockout",
                "outdoor_lockout_hysteresis",
                "minimum_state_time_seconds",
                "low_request_time_seconds",
            ):
                value = self.config.get(name)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                    or float(value) < 0
                ):
                    raise ValueError(f"plant_enable config.{name} must be non-negative finite")
            ignored = self.config.get("ignored_requests")
            if isinstance(ignored, bool) or not isinstance(ignored, int) or ignored < 0:
                raise ValueError(
                    "plant_enable config.ignored_requests must be non-negative Integer"
                )
            schedule = self.config.get("schedule")
            if not isinstance(schedule, list) or len(schedule) < 2:
                raise ValueError("plant_enable config.schedule requires at least two rows")
            previous = -math.inf
            for row in schedule:
                if (
                    not isinstance(row, list)
                    or len(row) != 2
                    or any(
                        isinstance(item, bool)
                        or not isinstance(item, (int, float))
                        or not math.isfinite(float(item))
                        for item in row
                    )
                    or float(row[0]) < previous
                    or float(row[1]) not in {0.0, 1.0}
                ):
                    raise ValueError(
                        "plant_enable config.schedule requires monotonic [time, 0|1] rows"
                    )
                previous = float(row[0])
        if self.kind == BlockKind.PLANT_HRC_MODE_CONTROL:
            contract = (
                "Buildings.Templates.Plants.Controls.HeatRecoveryChillers."
                "ModeControl"
            )
            if self.config.get("semantic_contract") != contract:
                raise ValueError("plant_hrc_mode_control requires its pinned contract")
            cop = self.config.get("heating_cop")
            if (
                isinstance(cop, bool)
                or not isinstance(cop, (int, float))
                or not math.isfinite(float(cop))
                or float(cop) < 1.1
            ):
                raise ValueError("plant_hrc_mode_control heating_cop must be >= 1.1")
        if self.kind == BlockKind.PLANT_HRC_ENABLE:
            contract = (
                "Buildings.Templates.Plants.Controls.HeatRecoveryChillers."
                "Enable"
            )
            if self.config.get("semantic_contract") != contract:
                raise ValueError("plant_hrc_enable requires its pinned contract")
            for name in (
                "minimum_chilled_supply_temperature",
                "maximum_heating_supply_temperature",
                "minimum_cooling_capacity",
                "minimum_heating_capacity",
                "minimum_state_time_seconds",
                "sufficient_load_time_seconds",
                "temperature_limit_1_time_seconds",
                "temperature_limit_2_time_seconds",
            ):
                value = self.config.get(name)
                minimum = 273.15 if "supply_temperature" in name else 0.0
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                    or float(value) < minimum
                ):
                    raise ValueError(
                        f"plant_hrc_enable config.{name} must be finite and >= {minimum}"
                    )
        if self.kind == BlockKind.PLANT_STAGE_COMPLETION:
            contract = (
                "Buildings.Templates.Plants.Controls.StagingRotation."
                "StageCompletion"
            )
            if self.config.get("semantic_contract") != contract:
                raise ValueError("plant_stage_completion requires its pinned contract")
            count = self.config.get("equipment_count")
            if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 52:
                raise ValueError(
                    "plant_stage_completion config.equipment_count must be 1 through 52"
                )
        if self.kind == BlockKind.PLANT_STAGE_INDEX:
            contract = (
                "Buildings.Templates.Plants.Controls.Utilities.StageIndex"
            )
            if self.config.get("semantic_contract") != contract:
                raise ValueError("plant_stage_index requires its pinned contract")
            count = self.config.get("stage_count")
            if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 52:
                raise ValueError("plant_stage_index config.stage_count must be 1 through 52")
            runtime = self.config.get("minimum_runtime_seconds")
            if (
                isinstance(runtime, bool)
                or not isinstance(runtime, (int, float))
                or not math.isfinite(float(runtime))
                or float(runtime) < 0
            ):
                raise ValueError(
                    "plant_stage_index config.minimum_runtime_seconds must be "
                    "non-negative finite"
                )
        if self.kind == BlockKind.MOVING_AVERAGE:
            window = self.config.get("window_seconds")
            if isinstance(window, bool) or not isinstance(window, (int, float)) or window <= 0:
                raise ValueError("moving_average config.window_seconds must be positive numeric")
        if self.kind in {BlockKind.NUMERIC_SAMPLER, BlockKind.NUMERIC_UNIT_DELAY}:
            period = self.config.get("sample_period_seconds")
            if isinstance(period, bool) or not isinstance(period, (int, float)) or period < 0.001:
                raise ValueError(
                    f"{self.kind.value} config.sample_period_seconds must be at least 0.001"
                )
        if self.kind in {
            BlockKind.NUMERIC_UNIT_DELAY,
            BlockKind.NUMERIC_CHANGED,
            BlockKind.NUMERIC_INCREASED,
            BlockKind.NUMERIC_DECREASED,
        }:
            initial = self.config.get("initial", 0.0)
            if isinstance(initial, bool) or not isinstance(initial, (int, float)):
                raise ValueError(f"{self.kind.value} config.initial must be numeric")
        return self


class Link(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    source_slot: str = "out"
    target: str
    target_slot: str


class ControlGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    blocks: list[Block]
    links: list[Link]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_graph(self) -> ControlGraph:
        by_id = {block.id: block for block in self.blocks}
        if len(by_id) != len(self.blocks):
            raise ValueError("block ids must be unique")
        connected_inputs: set[tuple[str, str]] = set()
        adjacency: dict[str, list[str]] = defaultdict(list)
        indegree = {block.id: 0 for block in self.blocks}
        for link in self.links:
            if link.source not in by_id or link.target not in by_id:
                raise ValueError(f"link references unknown block: {link.source} -> {link.target}")
            source_spec = BLOCK_SLOTS[by_id[link.source].kind]
            target_spec = BLOCK_SLOTS[by_id[link.target].kind]
            if link.source_slot not in source_spec.outputs:
                raise ValueError(f"unknown output {link.source}.{link.source_slot}")
            if link.target_slot not in target_spec.inputs:
                raise ValueError(f"unknown input {link.target}.{link.target_slot}")
            if source_spec.outputs[link.source_slot] != target_spec.inputs[link.target_slot]:
                source_ref = f"{link.source}.{link.source_slot}"
                target_ref = f"{link.target}.{link.target_slot}"
                raise ValueError(f"type mismatch on {source_ref} -> {target_ref}")
            input_key = (link.target, link.target_slot)
            if input_key in connected_inputs:
                raise ValueError(f"input has multiple drivers: {link.target}.{link.target_slot}")
            connected_inputs.add(input_key)
            if by_id[link.target].kind not in {
                BlockKind.NUMERIC_UNIT_DELAY,
                BlockKind.BOOLEAN_PRE_HOST_TICK,
            }:
                adjacency[link.source].append(link.target)
                indegree[link.target] += 1
        for block in self.blocks:
            for slot in BLOCK_SLOTS[block.kind].inputs:
                if (block.id, slot) not in connected_inputs:
                    raise ValueError(f"required input is not connected: {block.id}.{slot}")
        queue = deque(key for key, degree in indegree.items() if degree == 0)
        seen = 0
        while queue:
            current = queue.popleft()
            seen += 1
            for target in adjacency[current]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    queue.append(target)
        if seen != len(self.blocks):
            raise ValueError("control graph contains a cycle")
        return self

    def topological_order(self) -> list[Block]:
        by_id = {block.id: block for block in self.blocks}
        adjacency: dict[str, list[str]] = defaultdict(list)
        indegree = {block.id: 0 for block in self.blocks}
        for link in self.links:
            if by_id[link.target].kind not in {
                BlockKind.NUMERIC_UNIT_DELAY,
                BlockKind.BOOLEAN_PRE_HOST_TICK,
            }:
                adjacency[link.source].append(link.target)
                indegree[link.target] += 1
        queue = deque(block.id for block in self.blocks if indegree[block.id] == 0)
        ordered: list[Block] = []
        while queue:
            current = queue.popleft()
            ordered.append(by_id[current])
            for target in adjacency[current]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    queue.append(target)
        return ordered


def graph_changes(before: ControlGraph, after: ControlGraph) -> dict[str, list[str]]:
    """Return a stable, review-oriented structural diff between typed graphs."""

    previous_blocks = {block.id: block for block in before.blocks}
    current_blocks = {block.id: block for block in after.blocks}
    added = [f"block:{name}" for name in sorted(current_blocks.keys() - previous_blocks.keys())]
    removed = [f"block:{name}" for name in sorted(previous_blocks.keys() - current_blocks.keys())]
    modified = [
        f"block:{name}"
        for name in sorted(previous_blocks.keys() & current_blocks.keys())
        if previous_blocks[name].model_dump(mode="json")
        != current_blocks[name].model_dump(mode="json")
    ]

    def link_key(link: Link) -> str:
        return f"link:{link.source}.{link.source_slot}->{link.target}.{link.target_slot}"

    previous_links = {link_key(link) for link in before.links}
    current_links = {link_key(link) for link in after.links}
    added.extend(sorted(current_links - previous_links))
    removed.extend(sorted(previous_links - current_links))
    if before.metadata != after.metadata:
        modified.append("graph:metadata")
    if before.name != after.name:
        modified.append("graph:name")
    return {"added": added, "modified": modified, "removed": removed}


# JobSpec appears before ControlGraph so incoming job JSON can embed a graph
# without splitting the public schema into separate request types.
JobSpec.model_rebuild()


class AssertionResult(BaseModel):
    name: str
    passed: bool
    observed: str
    expected: str


class ScenarioResult(BaseModel):
    name: str
    passed: bool
    assertions: list[AssertionResult]
    samples: list[dict[str, float | bool]] = Field(default_factory=list)


class TestReport(BaseModel):
    passed: bool
    scenarios: list[ScenarioResult]
    engine: str
    coverage: dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Approval(BaseModel):
    reviewer: str
    actor_id: str | None = None
    tenant_id: str | None = None
    authentication: str = "self-asserted-local"
    approved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    artifact_sha256: str


class Rejection(BaseModel):
    reviewer: str = Field(min_length=2, max_length=120)
    actor_id: str | None = None
    tenant_id: str | None = None
    authentication: str = "self-asserted-local"
    reason: str | None = Field(default=None, max_length=2_000)
    rejected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    artifact_sha256: str


class RunStatus(StrEnum):
    FAILED = "failed"
    READY_FOR_REVIEW = "ready_for_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class RunOrigin(StrEnum):
    CONTRACTOR = "contractor"
    AI_PROPOSAL = "ai_proposal"


class TargetArtifactKind(StrEnum):
    NIAGARA_BOG = "niagara_bog"
    NIAGARA_PROGRAM_SOURCE_PACKAGE = "niagara_program_source_package"


class RunRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    origin: RunOrigin = RunOrigin.CONTRACTOR
    parent_run_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{12}$")
    job: JobSpec
    status: RunStatus
    graph_path: str
    target_artifact_kind: TargetArtifactKind = TargetArtifactKind.NIAGARA_BOG
    target_artifact_path: str | None = None
    bog_path: str | None = None
    program_package_path: str | None = None
    report_path: str
    manifest_path: str
    job_path: str | None = None
    template_bog_path: str | None = None
    template_analysis_path: str | None = None
    assembled_bog_path: str | None = None
    station_assembly_manifest_path: str | None = None
    semantic_model_path: str | None = None
    semantic_validation_path: str | None = None
    deliverable_manifest_path: str | None = None
    deliverable_artifact_paths: list[str] = Field(default_factory=list)
    volttron_manifest_path: str | None = None
    volttron_artifact_paths: list[str] = Field(default_factory=list)
    nhaystack_manifest_path: str | None = None
    nhaystack_artifact_paths: list[str] = Field(default_factory=list)
    bacnet_lab_manifest_path: str | None = None
    bacnet_lab_artifact_paths: list[str] = Field(default_factory=list)
    environment_pack_path: str | None = None
    environment_manifest_path: str | None = None
    environment_artifact_paths: list[str] = Field(default_factory=list)
    source_artifact_paths: list[str] = Field(default_factory=list)
    boptest_verification_path: str | None = None
    verification_artifact_paths: list[str] = Field(default_factory=list)
    artifact_sha256: str
    approval: Approval | None = None
    rejection: Rejection | None = None
    changes: dict[str, list[str]] = Field(default_factory=dict)
    agent_attempts: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def review_state_is_consistent(self) -> RunRecord:
        if self.status == RunStatus.APPROVED:
            if self.approval is None or self.rejection is not None:
                raise ValueError("approved runs require approval and cannot contain rejection")
        elif self.status == RunStatus.REJECTED:
            if self.rejection is None or self.approval is not None:
                raise ValueError("rejected runs require rejection and cannot contain approval")
        elif self.approval is not None or self.rejection is not None:
            raise ValueError("undecided runs cannot contain approval or rejection")
        return self


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(data: BaseModel | dict[str, Any]) -> str:
    value = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def safe_component_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not cleaned or not re.match(r"^[A-Za-z_]", cleaned):
        cleaned = f"N_{cleaned}"
    return cleaned
