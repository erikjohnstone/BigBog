from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bactalk.api import create_app
from bactalk.domain import Block, BlockKind, ControlGraph, Link
from bactalk.integrations.niagara_program_codegen import (
    NiagaraProgramPackageBuilder,
)

CONTROLLER = "AHUs.MultiZone.VAV.SetPoints.SupplySignals"
TRIM_CONTROLLER = "AHUs.MultiZone.VAV.SetPoints.SupplyTemperature"
HYSTERESIS_CONTROLLER = "ZoneGroups.ZoneStatus"
EXACTNESS_BLOCKED_CONTROLLER = "AHUs.MultiZone.VAV.Economizers.Subsequences.Enable"
LATCH_CONTROLLER = "AHUs.MultiZone.VAV.SetPoints.PlantRequests"
RELIEF_FAN_CONTROLLER = "AHUs.MultiZone.VAV.SetPoints.ReliefFan"
RELIEF_FAN_GROUP_CONTROLLER = "AHUs.MultiZone.VAV.SetPoints.ReliefFanGroup"
TIME_SUPPRESSION_CONTROLLER = "Generic.TimeSuppression"


def _plant_equipment_availability_graph() -> ControlGraph:
    return ControlGraph(
        name="PlantEquipmentAvailabilityGolden",
        blocks=[
            Block(id="Heating", kind=BlockKind.BOOLEAN_INPUT, label="Heating"),
            Block(id="Cooling", kind=BlockKind.BOOLEAN_INPUT, label="Cooling"),
            Block(id="Available", kind=BlockKind.BOOLEAN_INPUT, label="Available"),
            Block(
                id="Availability",
                kind=BlockKind.PLANT_EQUIPMENT_AVAILABILITY,
                label="Availability",
                config={
                    "off_time_seconds": 3.0,
                    "have_heating": True,
                    "have_cooling": True,
                    "semantic_contract": (
                        "Buildings.Templates.Plants.Controls.StagingRotation."
                        "EquipmentAvailability"
                    ),
                },
            ),
            Block(id="HeatingOut", kind=BlockKind.BOOLEAN_OUTPUT, label="HeatingOut"),
            Block(id="CoolingOut", kind=BlockKind.BOOLEAN_OUTPUT, label="CoolingOut"),
        ],
        links=[
            Link(source="Heating", target="Availability", target_slot="enableHeating"),
            Link(source="Cooling", target="Availability", target_slot="enableCooling"),
            Link(source="Available", target="Availability", target_slot="available"),
            Link(
                source="Availability",
                source_slot="heatingAvailable",
                target="HeatingOut",
                target_slot="in",
            ),
            Link(
                source="Availability",
                source_slot="coolingAvailable",
                target="CoolingOut",
                target_slot="in",
            ),
        ],
    )


def _plant_enable_graph() -> ControlGraph:
    return ControlGraph(
        name="PlantEnableGolden",
        blocks=[
            Block(id="Schedule", kind=BlockKind.BOOLEAN_INPUT, label="Schedule"),
            Block(id="Requests", kind=BlockKind.NUMERIC_INPUT, label="Requests"),
            Block(id="Outdoor", kind=BlockKind.NUMERIC_INPUT, label="Outdoor"),
            Block(
                id="Enable",
                kind=BlockKind.PLANT_ENABLE,
                label="Enable",
                config={
                    "application": "Heating",
                    "have_input_schedule": True,
                    "schedule": [[0.0, 1.0], [86400.0, 1.0]],
                    "outdoor_lockout": 290.0,
                    "outdoor_lockout_hysteresis": 1.0,
                    "ignored_requests": 0,
                    "minimum_state_time_seconds": 2.0,
                    "low_request_time_seconds": 2.0,
                    "semantic_contract": (
                        "Buildings.Templates.Plants.Controls.Enabling.Enable"
                    ),
                },
            ),
            Block(id="Out", kind=BlockKind.BOOLEAN_OUTPUT, label="Out"),
        ],
        links=[
            Link(source="Schedule", target="Enable", target_slot="scheduleEnabled"),
            Link(source="Requests", target="Enable", target_slot="requestCount"),
            Link(source="Outdoor", target="Enable", target_slot="outdoorTemperature"),
            Link(source="Enable", target="Out", target_slot="in"),
        ],
    )


def _plant_hrc_mode_graph() -> ControlGraph:
    return ControlGraph(
        name="PlantHrcModeGolden",
        blocks=[
            Block(id="Set", kind=BlockKind.BOOLEAN_INPUT, label="Set"),
            Block(id="CoolingLoad", kind=BlockKind.NUMERIC_INPUT, label="CoolingLoad"),
            Block(id="HeatingLoad", kind=BlockKind.NUMERIC_INPUT, label="HeatingLoad"),
            Block(id="ChilledSet", kind=BlockKind.NUMERIC_INPUT, label="ChilledSet"),
            Block(id="HeatingSet", kind=BlockKind.NUMERIC_INPUT, label="HeatingSet"),
            Block(
                id="Mode",
                kind=BlockKind.PLANT_HRC_MODE_CONTROL,
                label="Mode",
                config={
                    "heating_cop": 4.0,
                    "semantic_contract": (
                        "Buildings.Templates.Plants.Controls."
                        "HeatRecoveryChillers.ModeControl"
                    ),
                },
            ),
            Block(id="Cooling", kind=BlockKind.BOOLEAN_OUTPUT, label="Cooling"),
            Block(id="Setpoint", kind=BlockKind.NUMERIC_OUTPUT, label="Setpoint"),
        ],
        links=[
            Link(source="Set", target="Mode", target_slot="setMode"),
            Link(source="CoolingLoad", target="Mode", target_slot="coolingLoad"),
            Link(source="HeatingLoad", target="Mode", target_slot="heatingLoad"),
            Link(source="ChilledSet", target="Mode", target_slot="chilledSetpoint"),
            Link(source="HeatingSet", target="Mode", target_slot="heatingSetpoint"),
            Link(
                source="Mode",
                source_slot="coolingMode",
                target="Cooling",
                target_slot="in",
            ),
            Link(
                source="Mode",
                source_slot="supplySetpoint",
                target="Setpoint",
                target_slot="in",
            ),
        ],
    )


def _plant_hrc_enable_graph() -> ControlGraph:
    inputs = (
        ("CoolingPlant", BlockKind.BOOLEAN_INPUT, "coolingPlantEnable"),
        ("HeatingPlant", BlockKind.BOOLEAN_INPUT, "heatingPlantEnable"),
        ("HrcStatus", BlockKind.BOOLEAN_INPUT, "hrcStatus"),
        ("CoolingLoad", BlockKind.NUMERIC_INPUT, "coolingLoad"),
        ("HeatingLoad", BlockKind.NUMERIC_INPUT, "heatingLoad"),
        ("ChilledLeaving", BlockKind.NUMERIC_INPUT, "chilledLeavingTemperature"),
        ("HeatingLeaving", BlockKind.NUMERIC_INPUT, "heatingLeavingTemperature"),
        ("CoolingMode", BlockKind.BOOLEAN_INPUT, "coolingMode"),
    )
    return ControlGraph(
        name="PlantHrcEnableGolden",
        blocks=[
            *(Block(id=name, kind=kind, label=name) for name, kind, _ in inputs),
            Block(
                id="EnableController",
                kind=BlockKind.PLANT_HRC_ENABLE,
                label="EnableController",
                config={
                    "minimum_chilled_supply_temperature": 280.0,
                    "maximum_heating_supply_temperature": 330.0,
                    "minimum_cooling_capacity": 10.0,
                    "minimum_heating_capacity": 10.0,
                    "minimum_state_time_seconds": 2.0,
                    "sufficient_load_time_seconds": 2.0,
                    "temperature_limit_1_time_seconds": 2.0,
                    "temperature_limit_2_time_seconds": 1.0,
                    "semantic_contract": (
                        "Buildings.Templates.Plants.Controls."
                        "HeatRecoveryChillers.Enable"
                    ),
                },
            ),
            Block(id="Enable", kind=BlockKind.BOOLEAN_OUTPUT, label="Enable"),
            Block(id="SetMode", kind=BlockKind.BOOLEAN_OUTPUT, label="SetMode"),
        ],
        links=[
            *(
                Link(source=name, target="EnableController", target_slot=slot)
                for name, _, slot in inputs
            ),
            Link(
                source="EnableController",
                source_slot="enable",
                target="Enable",
                target_slot="in",
            ),
            Link(
                source="EnableController",
                source_slot="setMode",
                target="SetMode",
                target_slot="in",
            ),
        ],
    )


def _plant_stage_completion_graph() -> ControlGraph:
    return ControlGraph(
        name="PlantStageCompletionGolden",
        blocks=[
            Block(id="CommandMask", kind=BlockKind.NUMERIC_INPUT, label="CommandMask"),
            Block(id="StatusMask", kind=BlockKind.NUMERIC_INPUT, label="StatusMask"),
            Block(id="Stage", kind=BlockKind.NUMERIC_INPUT, label="Stage"),
            Block(
                id="Completion",
                kind=BlockKind.PLANT_STAGE_COMPLETION,
                label="Completion",
                config={
                    "equipment_count": 3,
                    "semantic_contract": (
                        "Buildings.Templates.Plants.Controls.StagingRotation."
                        "StageCompletion"
                    ),
                },
            ),
            Block(id="Progress", kind=BlockKind.BOOLEAN_OUTPUT, label="Progress"),
            Block(id="End", kind=BlockKind.BOOLEAN_OUTPUT, label="End"),
        ],
        links=[
            Link(source="CommandMask", target="Completion", target_slot="commandMask"),
            Link(source="StatusMask", target="Completion", target_slot="statusMask"),
            Link(source="Stage", target="Completion", target_slot="stage"),
            Link(
                source="Completion",
                source_slot="inProgress",
                target="Progress",
                target_slot="in",
            ),
            Link(
                source="Completion",
                source_slot="completed",
                target="End",
                target_slot="in",
            ),
        ],
    )


def _plant_stage_index_graph() -> ControlGraph:
    return ControlGraph(
        name="PlantStageIndexGolden",
        blocks=[
            Block(id="Lead", kind=BlockKind.BOOLEAN_INPUT, label="Lead"),
            Block(id="Up", kind=BlockKind.BOOLEAN_INPUT, label="Up"),
            Block(id="Down", kind=BlockKind.BOOLEAN_INPUT, label="Down"),
            Block(id="Availability", kind=BlockKind.NUMERIC_INPUT, label="Availability"),
            Block(
                id="StageIndex",
                kind=BlockKind.PLANT_STAGE_INDEX,
                label="StageIndex",
                config={
                    "stage_count": 4,
                    "minimum_runtime_seconds": 3.0,
                    "semantic_contract": (
                        "Buildings.Templates.Plants.Controls.Utilities.StageIndex"
                    ),
                },
            ),
            Block(id="Stage", kind=BlockKind.NUMERIC_OUTPUT, label="Stage"),
        ],
        links=[
            Link(source="Lead", target="StageIndex", target_slot="leadEnable"),
            Link(source="Up", target="StageIndex", target_slot="stageUp"),
            Link(source="Down", target="StageIndex", target_slot="stageDown"),
            Link(
                source="Availability",
                target="StageIndex",
                target_slot="availabilityMask",
            ),
            Link(
                source="StageIndex",
                source_slot="stage",
                target="Stage",
                target_slot="in",
            ),
        ],
    )


def _golden_graph() -> ControlGraph:
    return ControlGraph(
        name="PID_Reset_Golden",
        blocks=[
            Block(id="Setpoint", kind=BlockKind.NUMERIC_INPUT, label="Setpoint"),
            Block(id="Measurement", kind=BlockKind.NUMERIC_INPUT, label="Measurement"),
            Block(id="Trigger", kind=BlockKind.BOOLEAN_INPUT, label="Trigger"),
            Block(
                id="Controller",
                kind=BlockKind.PID_WITH_RESET,
                label="PID with reset",
                config={
                    "controller_type": "PI",
                    "k": 0.37,
                    "ti": 0.3,
                    "td": 0.1,
                    "r": 1.0,
                    "ni": 0.9,
                    "nd": 10.0,
                    "y_min": -0.35,
                    "y_max": 0.45,
                    "xi_start": 0.11,
                    "yd_start": 0.0,
                    "y_reset": 0.275,
                    "reverse_acting": True,
                },
            ),
            Block(id="Output", kind=BlockKind.NUMERIC_OUTPUT, label="Output"),
        ],
        links=[
            Link(source="Setpoint", target="Controller", target_slot="setpoint"),
            Link(source="Measurement", target="Controller", target_slot="measurement"),
            Link(source="Trigger", target="Controller", target_slot="trigger"),
            Link(source="Controller", target="Output", target_slot="in"),
        ],
    )


def _trim_and_respond_graph() -> ControlGraph:
    return ControlGraph(
        name="Trim_Respond_Golden",
        blocks=[
            Block(id="Requests", kind=BlockKind.NUMERIC_INPUT, label="Requests"),
            Block(id="DeviceOn", kind=BlockKind.BOOLEAN_INPUT, label="Device on"),
            Block(
                id="Reset",
                kind=BlockKind.TRIM_AND_RESPOND,
                label="Trim and respond",
                config={
                    "initial_setpoint": 10.0,
                    "minimum_setpoint": 0.0,
                    "maximum_setpoint": 20.0,
                    "delay_seconds": 600.0,
                    "sample_period_seconds": 120.0,
                    "ignored_requests": 2.0,
                    "trim_amount": 0.1,
                    "respond_amount": -0.2,
                    "maximum_response": -0.6,
                    "hold_enabled": False,
                },
            ),
            Block(id="Output", kind=BlockKind.NUMERIC_OUTPUT, label="Output"),
        ],
        links=[
            Link(source="Requests", target="Reset", target_slot="request_count"),
            Link(source="DeviceOn", target="Reset", target_slot="device_on"),
            Link(source="Reset", target="Output", target_slot="in"),
        ],
    )


def _trim_and_respond_hold_graph() -> ControlGraph:
    return ControlGraph(
        name="Trim_Respond_Hold_Golden",
        blocks=[
            Block(id="Requests", kind=BlockKind.NUMERIC_INPUT, label="Requests"),
            Block(id="DeviceOn", kind=BlockKind.BOOLEAN_INPUT, label="Device on"),
            Block(id="Hold", kind=BlockKind.BOOLEAN_INPUT, label="Hold"),
            Block(
                id="Reset",
                kind=BlockKind.TRIM_AND_RESPOND_HOLD,
                label="Trim and respond with hold",
                config={
                    "initial_setpoint": 10.0,
                    "minimum_setpoint": 0.0,
                    "maximum_setpoint": 20.0,
                    "delay_seconds": 0.0,
                    "sample_period_seconds": 10.0,
                    "ignored_requests": 2.0,
                    "trim_amount": 0.1,
                    "respond_amount": -0.2,
                    "maximum_response": -0.6,
                    "hold_enabled": True,
                    "hold_duration_seconds": 25.0,
                },
            ),
            Block(id="Output", kind=BlockKind.NUMERIC_OUTPUT, label="Output"),
        ],
        links=[
            Link(source="Requests", target="Reset", target_slot="request_count"),
            Link(source="DeviceOn", target="Reset", target_slot="device_on"),
            Link(source="Hold", target="Reset", target_slot="hold"),
            Link(source="Reset", target="Output", target_slot="in"),
        ],
    )


def _hysteresis_graph() -> ControlGraph:
    return ControlGraph(
        name="Hysteresis_Golden",
        blocks=[
            Block(id="Input", kind=BlockKind.NUMERIC_INPUT, label="Input"),
            Block(
                id="Hysteresis",
                kind=BlockKind.HYSTERESIS,
                label="Hysteresis",
                config={"u_low": 1.5, "u_high": 3.5, "initial": False},
            ),
            Block(id="Output", kind=BlockKind.BOOLEAN_OUTPUT, label="Output"),
        ],
        links=[
            Link(source="Input", target="Hysteresis", target_slot="in"),
            Link(source="Hysteresis", target="Output", target_slot="in"),
        ],
    )


def _true_false_hold_graph() -> ControlGraph:
    return ControlGraph(
        name="TrueFalseHold_Golden",
        blocks=[
            Block(id="Input", kind=BlockKind.BOOLEAN_INPUT, label="Input"),
            Block(
                id="Hold",
                kind=BlockKind.BOOLEAN_TRUE_FALSE_HOLD,
                label="Hold",
                config={
                    "true_hold_seconds": 300.0,
                    "false_hold_seconds": 300.0,
                },
            ),
            Block(id="Output", kind=BlockKind.BOOLEAN_OUTPUT, label="Output"),
        ],
        links=[
            Link(source="Input", target="Hold", target_slot="in"),
            Link(source="Hold", target="Output", target_slot="in"),
        ],
    )


def _true_delay_graph(*, delay_on_init: bool = True) -> ControlGraph:
    return ControlGraph(
        name="TrueDelay_Golden",
        blocks=[
            Block(id="Input", kind=BlockKind.BOOLEAN_INPUT, label="Input"),
            Block(
                id="Delay",
                kind=BlockKind.BOOLEAN_DELAY,
                label="True delay",
                config={
                    "on_delay_seconds": 75.0,
                    "off_delay_seconds": 0.0,
                    "initial": False,
                    "delay_on_init": delay_on_init,
                    "semantic_contract": "CDL.Logical.TrueDelay",
                },
            ),
            Block(id="Output", kind=BlockKind.BOOLEAN_OUTPUT, label="Output"),
        ],
        links=[
            Link(source="Input", target="Delay", target_slot="in"),
            Link(source="Delay", target="Output", target_slot="in"),
        ],
    )


def _logical_latch_graph() -> ControlGraph:
    return ControlGraph(
        name="LogicalLatch_Golden",
        blocks=[
            Block(id="Set", kind=BlockKind.BOOLEAN_INPUT, label="Set"),
            Block(id="Clear", kind=BlockKind.BOOLEAN_INPUT, label="Clear"),
            Block(
                id="Latch",
                kind=BlockKind.BOOLEAN_SET_RESET,
                label="Latch",
                config={"semantic_contract": "CDL.Logical.Latch"},
            ),
            Block(id="Output", kind=BlockKind.BOOLEAN_OUTPUT, label="Output"),
        ],
        links=[
            Link(source="Set", target="Latch", target_slot="set"),
            Link(source="Clear", target="Latch", target_slot="clear"),
            Link(source="Latch", target="Output", target_slot="in"),
        ],
    )


def _boolean_initialization_graph(*, initial: bool = False) -> ControlGraph:
    return ControlGraph(
        name="Plant_Initialization_Golden",
        blocks=[
            Block(id="Input", kind=BlockKind.BOOLEAN_INPUT, label="Input"),
            Block(
                id="Initialization",
                kind=BlockKind.BOOLEAN_INITIALIZATION,
                label="Plant initialization",
                config={
                    "initial": initial,
                    "semantic_contract": (
                        "Buildings.Templates.Plants.Controls.Utilities.Initialization"
                    ),
                },
            ),
            Block(id="Output", kind=BlockKind.BOOLEAN_OUTPUT, label="Output"),
        ],
        links=[
            Link(source="Input", target="Initialization", target_slot="in"),
            Link(source="Initialization", target="Output", target_slot="in"),
        ],
    )


def _timer_graph() -> ControlGraph:
    return ControlGraph(
        name="LogicalTimer_Golden",
        blocks=[
            Block(id="Input", kind=BlockKind.BOOLEAN_INPUT, label="Input"),
            Block(
                id="Timer",
                kind=BlockKind.TIMER,
                label="Timer",
                config={
                    "threshold_seconds": 1.0,
                    "semantic_contract": "CDL.Logical.Timer",
                },
            ),
            Block(id="Elapsed", kind=BlockKind.NUMERIC_OUTPUT, label="Elapsed"),
            Block(id="Passed", kind=BlockKind.BOOLEAN_OUTPUT, label="Passed"),
        ],
        links=[
            Link(source="Input", target="Timer", target_slot="in"),
            Link(source="Timer", source_slot="elapsed", target="Elapsed", target_slot="in"),
            Link(source="Timer", source_slot="passed", target="Passed", target_slot="in"),
        ],
    )


def _timer_with_reset_graph() -> ControlGraph:
    return ControlGraph(
        name="Plant_Timer_With_Reset_Golden",
        blocks=[
            Block(id="Input", kind=BlockKind.BOOLEAN_INPUT, label="Input"),
            Block(id="Reset", kind=BlockKind.BOOLEAN_INPUT, label="Reset"),
            Block(
                id="Timer",
                kind=BlockKind.TIMER_WITH_RESET,
                label="Timer with reset",
                config={
                    "threshold_seconds": 3.0,
                    "semantic_contract": (
                        "Buildings.Templates.Plants.Controls.Utilities.TimerWithReset"
                    ),
                },
            ),
            Block(id="Elapsed", kind=BlockKind.NUMERIC_OUTPUT, label="Elapsed"),
            Block(id="Passed", kind=BlockKind.BOOLEAN_OUTPUT, label="Passed"),
        ],
        links=[
            Link(source="Input", target="Timer", target_slot="in"),
            Link(source="Reset", target="Timer", target_slot="reset"),
            Link(source="Timer", source_slot="elapsed", target="Elapsed", target_slot="in"),
            Link(source="Timer", source_slot="passed", target="Passed", target_slot="in"),
        ],
    )


def _accumulating_timer_graph() -> ControlGraph:
    return ControlGraph(
        name="Accumulating_Timer_Golden",
        blocks=[
            Block(id="Input", kind=BlockKind.BOOLEAN_INPUT, label="Input"),
            Block(id="Reset", kind=BlockKind.BOOLEAN_INPUT, label="Reset"),
            Block(
                id="Timer",
                kind=BlockKind.TIMER_ACCUMULATING,
                label="Accumulating timer",
                config={
                    "threshold_seconds": 3.0,
                    "semantic_contract": (
                        "Buildings.Controls.OBC.CDL.Logical.TimerAccumulating"
                    ),
                },
            ),
            Block(id="Elapsed", kind=BlockKind.NUMERIC_OUTPUT, label="Elapsed"),
            Block(id="Passed", kind=BlockKind.BOOLEAN_OUTPUT, label="Passed"),
        ],
        links=[
            Link(source="Input", target="Timer", target_slot="in"),
            Link(source="Reset", target="Timer", target_slot="reset"),
            Link(source="Timer", source_slot="elapsed", target="Elapsed", target_slot="in"),
            Link(source="Timer", source_slot="passed", target="Passed", target_slot="in"),
        ],
    )


def _moving_average_graph() -> ControlGraph:
    return ControlGraph(
        name="MovingAverage_Golden",
        blocks=[
            Block(id="Input", kind=BlockKind.NUMERIC_INPUT, label="Input"),
            Block(
                id="Average",
                kind=BlockKind.MOVING_AVERAGE,
                label="Moving average",
                config={
                    "window_seconds": 1.0,
                    "semantic_contract": "CDL.Reals.MovingAverage",
                },
            ),
            Block(id="Output", kind=BlockKind.NUMERIC_OUTPUT, label="Output"),
        ],
        links=[
            Link(source="Input", target="Average", target_slot="in"),
            Link(source="Average", target="Output", target_slot="in"),
        ],
    )


def _assert_warning_graph() -> ControlGraph:
    return ControlGraph(
        name="Assert_Warning_Golden",
        blocks=[
            Block(id="Condition", kind=BlockKind.BOOLEAN_INPUT, label="Condition"),
            Block(
                id="Assertion",
                kind=BlockKind.BOOLEAN_ASSERT_WARNING,
                label="Assert warning",
                config={
                    "message": 'Warning: airflow is below 50%. "Check" sensor.',
                    "severity": "warning",
                    "repeat_while_false": True,
                    "semantic_contract": "CDL.Utilities.Assert",
                },
            ),
        ],
        links=[Link(source="Condition", target="Assertion", target_slot="condition")],
    )


def _falling_edge_graph(*, pre_u_start: bool = False) -> ControlGraph:
    return ControlGraph(
        name="Falling_Edge_Golden",
        blocks=[
            Block(id="Input", kind=BlockKind.BOOLEAN_INPUT, label="Input"),
            Block(
                id="Edge",
                kind=BlockKind.BOOLEAN_FALLING_EDGE,
                label="Falling edge",
                config={
                    "pre_u_start": pre_u_start,
                    "semantic_contract": "CDL.Logical.FallingEdge",
                },
            ),
            Block(id="Output", kind=BlockKind.BOOLEAN_OUTPUT, label="Output"),
        ],
        links=[
            Link(source="Input", target="Edge", target_slot="in"),
            Link(source="Edge", target="Output", target_slot="in"),
        ],
    )


def _boolean_pre_host_tick_graph(*, initial: bool = False) -> ControlGraph:
    return ControlGraph(
        name="Boolean_Pre_Host_Tick_Golden",
        blocks=[
            Block(id="Input", kind=BlockKind.BOOLEAN_INPUT, label="Input"),
            Block(
                id="Memory",
                kind=BlockKind.BOOLEAN_PRE_HOST_TICK,
                label="Previous scan input",
                config={
                    "initial": initial,
                    "semantic_contract": "CDL.Logical.Pre",
                    "execution_profile": "host_tick_v1",
                },
            ),
            Block(id="Output", kind=BlockKind.BOOLEAN_OUTPUT, label="Output"),
        ],
        links=[
            Link(source="Input", target="Memory", target_slot="in"),
            Link(source="Memory", target="Output", target_slot="in"),
        ],
    )


def _numeric_changed_graph(*, initial: float = 0.0) -> ControlGraph:
    return ControlGraph(
        name="Numeric_Changed_Golden",
        blocks=[
            Block(id="Input", kind=BlockKind.NUMERIC_INPUT, label="Input"),
            Block(
                id="Changed",
                kind=BlockKind.NUMERIC_CHANGED,
                label="Numeric changed",
                config={
                    "initial": initial,
                    "semantic_contract": "Buildings.Controls.OBC.CDL.Integers.Change",
                },
            ),
            Block(id="Output", kind=BlockKind.BOOLEAN_OUTPUT, label="Output"),
        ],
        links=[
            Link(source="Input", target="Changed", target_slot="in"),
            Link(source="Changed", target="Output", target_slot="in"),
        ],
    )


def _numeric_sampler_graph() -> ControlGraph:
    return ControlGraph(
        name="Numeric_Sampler_Golden",
        blocks=[
            Block(id="Input", kind=BlockKind.NUMERIC_INPUT, label="Input"),
            Block(
                id="Sampler",
                kind=BlockKind.NUMERIC_SAMPLER,
                label="Sampler",
                config={
                    "sample_period_seconds": 2.0,
                    "semantic_contract": "CDL.Discrete.Sampler",
                },
            ),
            Block(id="Output", kind=BlockKind.NUMERIC_OUTPUT, label="Output"),
        ],
        links=[
            Link(source="Input", target="Sampler", target_slot="in"),
            Link(source="Sampler", target="Output", target_slot="in"),
        ],
    )


def _triggered_sampler_graph() -> ControlGraph:
    return ControlGraph(
        name="Triggered_Sampler_Golden",
        blocks=[
            Block(id="Input", kind=BlockKind.NUMERIC_INPUT, label="Input"),
            Block(id="Trigger", kind=BlockKind.BOOLEAN_INPUT, label="Trigger"),
            Block(
                id="Sampler",
                kind=BlockKind.NUMERIC_LATCH,
                label="Triggered sampler",
                config={
                    "initial": -1.0,
                    "semantic_contract": "CDL.Discrete.TriggeredSampler",
                },
            ),
            Block(id="Output", kind=BlockKind.NUMERIC_OUTPUT, label="Output"),
        ],
        links=[
            Link(source="Input", target="Sampler", target_slot="in"),
            Link(source="Trigger", target="Sampler", target_slot="clock"),
            Link(source="Sampler", target="Output", target_slot="in"),
        ],
    )


def _numeric_unit_delay_graph() -> ControlGraph:
    return ControlGraph(
        name="Numeric_Unit_Delay_Golden",
        blocks=[
            Block(id="Input", kind=BlockKind.NUMERIC_INPUT, label="Input"),
            Block(
                id="Delay",
                kind=BlockKind.NUMERIC_UNIT_DELAY,
                label="Unit delay",
                config={
                    "sample_period_seconds": 2.0,
                    "initial": -1.0,
                    "semantic_contract": "CDL.Discrete.UnitDelay",
                },
            ),
            Block(id="Output", kind=BlockKind.NUMERIC_OUTPUT, label="Output"),
        ],
        links=[
            Link(source="Input", target="Delay", target_slot="in"),
            Link(source="Delay", target="Output", target_slot="in"),
        ],
    )


def test_program_package_is_deterministic_and_explicitly_unqualified() -> None:
    builder = NiagaraProgramPackageBuilder()

    first = builder.build(_golden_graph(), controller_id="golden")
    second = builder.build(_golden_graph(), controller_id="golden")

    assert first == second
    with zipfile.ZipFile(BytesIO(first)) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
        source = archive.read("programs/Controller/ProgramObject.java").decode()
        slots = json.loads(archive.read("programs/Controller/slots.json"))
        graph = json.loads(archive.read("control-graph.json"))
        wiring = json.loads(archive.read("wiring-plan.json"))
    assert manifest["schema"] == "bactalk-niagara-program-package/v4"
    assert manifest["control_graph_path"] == "control-graph.json"
    assert manifest["wiring_plan_path"] == "wiring-plan.json"
    assert manifest["licensed_workbench_compile_required"] is True
    assert manifest["runtime_qualified"] is False
    assert manifest["live_deployment_allowed"] is False
    assert manifest["programs"][0]["config"]["ni"] == 0.9
    assert "programs/Controller/G36PidWithReset_" in "\n".join(names)
    assert "double antiWindup = (unlimited - output) / (K * NI);" in source
    assert "integral = Y_RESET - proportionalDerivative;" in source
    assert [slot["name"] for slot in slots["slots"]] == [
        "setpoint",
        "measurement",
        "trigger",
        "out",
    ]
    assert graph == _golden_graph().model_dump(mode="json")
    assert wiring["component_count"] == len(graph["blocks"])
    assert wiring["link_count"] == len(graph["links"])
    assert wiring["generated_program_count"] == 1
    assert (
        next(item for item in wiring["components"] if item["block_id"] == "Controller")[
            "implementation"
        ]
        == "generated_program_object"
    )
    assert {
        (
            item["source"]["block_id"],
            item["source"]["slot"],
            item["target"]["block_id"],
            item["target"]["slot"],
        )
        for item in wiring["links"]
    } == {
        (
            item["source"],
            item["source_slot"],
            item["target"],
            item["target_slot"],
        )
        for item in graph["links"]
    }


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac is not installed")
def test_generated_java_kernel_matches_independent_oce_golden(tmp_path: Path) -> None:
    content = NiagaraProgramPackageBuilder().build(_golden_graph())
    with zipfile.ZipFile(BytesIO(content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        program = manifest["programs"][0]
        class_name = program["class_name"]
        source = archive.read(program["paths"]["standalone_kernel"])
    source_path = tmp_path / f"{class_name}.java"
    source_path.write_bytes(source)

    subprocess.run(
        ["javac", source_path.name],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    rows = [
        (0.0, 0.2, 0.0, 0.0, 0.184),
        (0.1, 0.22, 0.0, 0.0, 0.19140000000000001),
        (0.2, 0.95, 0.0, 0.0, 0.45),
        (0.30000000000000004, 0.18, 0.0, 1.0, 0.3065913580246914),
        (0.4, 0.18, 0.0, 1.0, 0.275),
        (0.5, -1.38, 0.0, 0.0, -0.2799999999999999),
        (0.6000000000000001, 1.1, 0.0, 0.0, 0.45),
        (0.7000000000000001, -0.4, 0.0, 1.0, 0.041622222222222394),
        (0.8, -0.4, 0.0, 1.0, 0.275),
        (0.9, 0.025, 0.0, 0.0, 0.3829166666666667),
    ]
    arguments = [
        value
        for time, setpoint, measurement, trigger, _ in rows
        for value in map(str, (time, setpoint, measurement, trigger))
    ]
    result = subprocess.run(
        ["java", "-cp", str(tmp_path), class_name, *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    actual = [float(value) for value in result.stdout.splitlines()]

    assert len(actual) == len(rows)
    for value, row in zip(actual, rows, strict=True):
        assert math.isclose(value, row[-1], rel_tol=0.0, abs_tol=5e-16)


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac is not installed")
def test_equipment_availability_java_kernel_matches_stategraph_trajectory(
    tmp_path: Path,
) -> None:
    content = NiagaraProgramPackageBuilder().build(
        _plant_equipment_availability_graph()
    )
    with zipfile.ZipFile(BytesIO(content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        program = manifest["programs"][0]
        class_name = program["class_name"]
        source = archive.read(program["paths"]["standalone_kernel"])
        slots = json.loads(archive.read(program["paths"]["slots"]))
    source_path = tmp_path / f"{class_name}.java"
    source_path.write_bytes(source)
    subprocess.run(
        ["javac", source_path.name],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    rows = [
        (0, 0, 0, 1),
        (1, 1, 0, 1),
        (2, 1, 0, 1),
        (3, 0, 0, 1),
        (4, 0, 1, 1),
        (5, 0, 1, 1),
        (6, 0, 1, 1),
        (7, 0, 1, 1),
        (8, 0, 1, 0),
        (9, 0, 1, 1),
    ]
    result = subprocess.run(
        [
            "java",
            "-cp",
            str(tmp_path),
            class_name,
            *(str(value) for row in rows for value in row),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == [
        "true,true",
        "true,false",
        "true,false",
        "false,false",
        "false,false",
        "false,false",
        "false,true",
        "false,true",
        "false,false",
        "false,true",
    ]
    assert [slot["name"] for slot in slots["slots"]] == [
        "enableHeating",
        "enableCooling",
        "available",
        "heatingAvailable",
        "coolingAvailable",
    ]
    assert program["source_contract"]["standard"].endswith(
        "StagingRotation.EquipmentAvailability"
    )


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac is not installed")
def test_plant_enable_java_kernel_matches_dwell_and_lockout_trajectory(
    tmp_path: Path,
) -> None:
    content = NiagaraProgramPackageBuilder().build(_plant_enable_graph())
    with zipfile.ZipFile(BytesIO(content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        program = manifest["programs"][0]
        class_name = program["class_name"]
        source = archive.read(program["paths"]["standalone_kernel"])
    source_path = tmp_path / f"{class_name}.java"
    source_path.write_bytes(source)
    subprocess.run(
        ["javac", source_path.name],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    regimes = [
        (1, 1, 285),
        (1, 1, 285),
        (1, 1, 285),
        (1, 0, 285),
        (1, 0, 285),
        (1, 0, 285),
        (1, 1, 285),
        (1, 1, 285),
        (1, 1, 285),
        (1, 1, 292),
        (1, 1, 292),
        (1, 1, 292),
    ]
    result = subprocess.run(
        [
            "java",
            "-cp",
            str(tmp_path),
            class_name,
            *(
                str(value)
                for timestamp, (schedule, requests, oat) in enumerate(regimes)
                for value in (timestamp, timestamp, schedule, requests, oat)
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == [
        "false",
        "false",
        "true",
        "true",
        "true",
        "false",
        "false",
        "true",
        "true",
        "false",
        "false",
        "false",
    ]
    assert program["behavior_kind"] == "plant_enable"
    assert program["source_contract"]["standard"].endswith("Enabling.Enable")


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac is not installed")
def test_stage_completion_java_kernel_matches_change_latch_trajectory(
    tmp_path: Path,
) -> None:
    content = NiagaraProgramPackageBuilder().build(_plant_stage_completion_graph())
    with zipfile.ZipFile(BytesIO(content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        program = manifest["programs"][0]
        class_name = program["class_name"]
        source = archive.read(program["paths"]["standalone_kernel"])
    source_path = tmp_path / f"{class_name}.java"
    source_path.write_bytes(source)
    subprocess.run(
        ["javac", source_path.name],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    rows = [
        (0, 0, 0),
        (3, 0, 1),
        (3, 0, 1),
        (3, 1, 1),
        (3, 3, 1),
        (3, 3, 1),
        (7, 3, 2),
        (7, 3, 2),
        (7, 7, 2),
    ]
    result = subprocess.run(
        [
            "java",
            "-cp",
            str(tmp_path),
            class_name,
            *(str(value) for row in rows for value in row),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.splitlines() == [
        "false,false",
        "true,false",
        "true,false",
        "true,false",
        "false,true",
        "false,false",
        "true,false",
        "true,false",
        "false,true",
    ]
    assert program["behavior_kind"] == "plant_stage_completion"
    assert program["source_contract"]["vector_encoding"] == (
        "lossless integer bitmask"
    )


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac is not installed")
def test_stage_index_java_kernel_matches_stategraph_trajectory(tmp_path: Path) -> None:
    content = NiagaraProgramPackageBuilder().build(_plant_stage_index_graph())
    with zipfile.ZipFile(BytesIO(content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        program = manifest["programs"][0]
        class_name = program["class_name"]
        source = archive.read(program["paths"]["standalone_kernel"])
        slots = json.loads(archive.read(program["paths"]["slots"]))
    source_path = tmp_path / f"{class_name}.java"
    source_path.write_bytes(source)
    subprocess.run(
        ["javac", source_path.name],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    rows = [
        (0, 0, 0, 0, 13),
        (1, 1, 0, 0, 13),
        (2, 1, 1, 0, 13),
        (4, 1, 1, 0, 13),
        (5, 1, 0, 0, 9),
        (6, 1, 0, 1, 9),
        (8, 1, 0, 1, 9),
        (9, 0, 0, 0, 9),
        (11, 0, 0, 0, 9),
    ]
    result = subprocess.run(
        [
            "java",
            "-cp",
            str(tmp_path),
            class_name,
            *(str(value) for row in rows for value in row),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == ["0", "1", "1", "3", "4", "4", "1", "1", "0"]
    assert [slot["name"] for slot in slots["slots"]] == [
        "leadEnable",
        "stageUp",
        "stageDown",
        "availabilityMask",
        "stage",
    ]
    assert program["source_contract"]["standard"].endswith("Utilities.StageIndex")


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac is not installed")
def test_numeric_changed_java_kernel_matches_pinned_change_recurrence(
    tmp_path: Path,
) -> None:
    content = NiagaraProgramPackageBuilder().build(_numeric_changed_graph())
    with zipfile.ZipFile(BytesIO(content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        program = manifest["programs"][0]
        class_name = program["class_name"]
        source = archive.read(program["paths"]["standalone_kernel"])
        slots = json.loads(archive.read(program["paths"]["slots"]))
    source_path = tmp_path / f"{class_name}.java"
    source_path.write_bytes(source)
    subprocess.run(
        ["javac", source_path.name],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        ["java", "-cp", str(tmp_path), class_name, "0", "0", "1", "1", "-1"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == ["false", "false", "true", "false", "true"]
    assert [slot["name"] for slot in slots["slots"]] == ["in", "out"]
    assert program["source_contract"]["standard"].endswith("Integers.Change")


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac is not installed")
def test_hrc_enable_java_kernel_matches_timer_latch_and_delay_trajectory(
    tmp_path: Path,
) -> None:
    content = NiagaraProgramPackageBuilder().build(_plant_hrc_enable_graph())
    with zipfile.ZipFile(BytesIO(content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        program = manifest["programs"][0]
        class_name = program["class_name"]
        source = archive.read(program["paths"]["standalone_kernel"])
        slots = json.loads(archive.read(program["paths"]["slots"]))
    source_path = tmp_path / f"{class_name}.java"
    source_path.write_bytes(source)
    subprocess.run(
        ["javac", source_path.name],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    rows = [
        (time, 1, 1, 0, 20, 20, 285, 320, 0)
        for time in range(12)
    ]
    result = subprocess.run(
        [
            "java",
            "-cp",
            str(tmp_path),
            class_name,
            *(str(value) for row in rows for value in row),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == [
        "false,false",
        "false,false",
        "false,true",
        "false,false",
        "false,false",
        "false,false",
        "false,false",
        "true,false",
        "true,false",
        "true,false",
        "true,false",
        "true,false",
    ]
    assert program["behavior_kind"] == "plant_hrc_enable"
    assert program["source_contract"]["standard"].endswith(
        "HeatRecoveryChillers.Enable"
    )
    assert [slot["name"] for slot in slots["slots"]] == [
        "coolingPlantEnable",
        "heatingPlantEnable",
        "hrcStatus",
        "coolingLoad",
        "heatingLoad",
        "chilledLeavingTemperature",
        "heatingLeavingTemperature",
        "coolingMode",
        "enable",
        "setMode",
    ]


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac is not installed")
def test_hrc_mode_java_kernel_matches_hysteresis_and_mode_hold(tmp_path: Path) -> None:
    content = NiagaraProgramPackageBuilder().build(_plant_hrc_mode_graph())
    with zipfile.ZipFile(BytesIO(content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        program = manifest["programs"][0]
        class_name = program["class_name"]
        source = archive.read(program["paths"]["standalone_kernel"])
    source_path = tmp_path / f"{class_name}.java"
    source_path.write_bytes(source)
    subprocess.run(
        ["javac", source_path.name],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    rows = [
        (0, 10, 100, 280, 320),
        (1, 10, 100, 280, 320),
        (0, 100, 100, 280, 320),
        (1, 100, 100, 280, 320),
        (0, 74.5, 100, 281, 321),
        (1, 75.5, 100, 281, 321),
        (1, 76, 100, 281, 321),
    ]
    result = subprocess.run(
        [
            "java",
            "-cp",
            str(tmp_path),
            class_name,
            *(str(value) for row in rows for value in row),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == [
        "false,320.0",
        "true,280.0",
        "true,280.0",
        "false,320.0",
        "false,321.0",
        "true,281.0",
        "false,321.0",
    ]
    assert program["behavior_kind"] == "plant_hrc_mode_control"


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac is not installed")
def test_trim_and_respond_java_kernel_matches_independent_oce_golden(
    tmp_path: Path,
) -> None:
    content = NiagaraProgramPackageBuilder().build(_trim_and_respond_graph())
    with zipfile.ZipFile(BytesIO(content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        program = manifest["programs"][0]
        class_name = program["class_name"]
        source = archive.read(program["paths"]["standalone_kernel"])
        slots = json.loads(archive.read(program["paths"]["slots"]))
    source_path = tmp_path / f"{class_name}.java"
    source_path.write_bytes(source)

    subprocess.run(
        ["javac", source_path.name],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    rows = []
    expected = [
        10.0,
        10.0,
        10.0,
        10.0,
        10.0,
        10.0,
        10.0,
        10.0,
        10.0,
        10.0,
        10.0,
        10.0,
        9.9,
        9.9,
        9.4,
        9.4,
        8.9,
        8.9,
        10.0,
        10.0,
        10.0,
        10.0,
        10.0,
    ]
    for timestamp, wanted in zip(range(0, 1321, 60), expected, strict=True):
        requests = 6.0 if 840 <= timestamp < 1080 else 3.0 if 720 <= timestamp < 840 else 0.0
        device_on = not (1080 <= timestamp < 1260)
        rows.append((float(timestamp), requests, float(device_on), wanted))
    arguments = [
        value
        for time, requests, device_on, _ in rows
        for value in map(str, (time, requests, device_on))
    ]
    result = subprocess.run(
        ["java", "-cp", str(tmp_path), class_name, *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    actual = [float(value) for value in result.stdout.splitlines()]

    assert actual == expected
    assert program["behavior_kind"] == "trim_and_respond"
    assert program["source_contract"]["variant"] == "have_hol=false"
    assert [slot["name"] for slot in slots["slots"]] == [
        "request_count",
        "device_on",
        "out",
    ]


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac is not installed")
def test_trim_and_respond_hold_java_kernel_matches_expanded_oce_source_trace(
    tmp_path: Path,
) -> None:
    content = NiagaraProgramPackageBuilder().build(_trim_and_respond_hold_graph())
    with zipfile.ZipFile(BytesIO(content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        program = manifest["programs"][0]
        class_name = program["class_name"]
        source_path = tmp_path / f"{class_name}.java"
        source_path.write_bytes(archive.read(program["paths"]["standalone_kernel"]))
        slots = json.loads(archive.read(program["paths"]["slots"]))

    subprocess.run(
        ["javac", source_path.name],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    expected = [
        10.0,
        10.0,
        10.1,
        10.1,
        10.2,
        10.2,
        10.2,
        10.2,
        10.2,
        10.2,
        10.299999999999999,
        10.299999999999999,
        10.399999999999999,
        10.399999999999999,
        10.499999999999998,
        10.499999999999998,
        10.599999999999998,
    ]
    arguments = []
    for timestamp in range(0, 81, 5):
        arguments.extend(
            [
                str(timestamp),
                "0",
                "1",
                "1" if 25 <= timestamp < 35 else "0",
            ]
        )
    result = subprocess.run(
        ["java", "-cp", str(tmp_path), class_name, *arguments],
        check=True,
        capture_output=True,
        text=True,
    )

    assert [float(value) for value in result.stdout.splitlines()] == expected
    assert program["behavior_kind"] == "trim_and_respond_hold"
    assert program["source_contract"]["variant"] == "have_hol=true"
    assert [slot["name"] for slot in slots["slots"]] == [
        "request_count",
        "device_on",
        "hold",
        "out",
    ]


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac is not installed")
@pytest.mark.parametrize(
    ("graph", "arguments", "expected"),
    [
        (
            _hysteresis_graph(),
            ["2.5", "3.6", "2.5", "3.5", "1.5", "1.4", "2.5", "3.5"],
            ["false", "true", "true", "true", "true", "false", "false", "false"],
        ),
        (
            _true_false_hold_graph(),
            ["0", "1", "100", "0", "250", "1", "400", "0", "700", "1"],
            ["true", "true", "true", "false", "true"],
        ),
        (
            _true_delay_graph(),
            ["0", "0", "30", "1", "100", "1", "130", "1", "160", "0"],
            ["false", "false", "false", "true", "false"],
        ),
        (
            _true_delay_graph(delay_on_init=False),
            ["0", "1", "10", "0", "20", "1", "94", "1", "95", "1"],
            ["true", "false", "false", "false", "true"],
        ),
        (
            _logical_latch_graph(),
            [
                "0",
                "0",
                "1",
                "0",
                "0",
                "0",
                "1",
                "1",
                "1",
                "0",
                "0",
                "0",
                "1",
                "0",
            ],
            ["false", "true", "true", "false", "false", "false", "true"],
        ),
        (
            _falling_edge_graph(),
            ["0", "1", "1", "0", "0", "1", "0"],
            ["false", "false", "false", "true", "false", "false", "true"],
        ),
        (
            _falling_edge_graph(pre_u_start=True),
            ["0", "0", "1", "0"],
            ["true", "false", "false", "true"],
        ),
        (
            _boolean_pre_host_tick_graph(initial=True),
            ["0", "1", "1", "0", "1"],
            ["true", "false", "true", "true", "false"],
        ),
        (
            _boolean_initialization_graph(initial=False),
            ["1", "1", "0"],
            ["false", "true", "false"],
        ),
    ],
)
def test_boolean_java_kernels_match_independent_oce_goldens(
    tmp_path: Path,
    graph: ControlGraph,
    arguments: list[str],
    expected: list[str],
) -> None:
    content = NiagaraProgramPackageBuilder().build(graph)
    with zipfile.ZipFile(BytesIO(content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        program = manifest["programs"][0]
        class_name = program["class_name"]
        source = archive.read(program["paths"]["standalone_kernel"])
        slots = json.loads(archive.read(program["paths"]["slots"]))
    source_path = tmp_path / f"{class_name}.java"
    source_path.write_bytes(source)
    subprocess.run(
        ["javac", source_path.name],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        ["java", "-cp", str(tmp_path), class_name, *arguments],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == expected
    assert slots["slots"][-1]["type_spec"] == "b:StatusBoolean"


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac is not installed")
@pytest.mark.parametrize(
    ("graph", "arguments", "expected", "expected_slots", "standard"),
    [
        (
            _numeric_sampler_graph(),
            ["0", "1", "1", "2", "2", "3", "3.9", "4", "4", "5"],
            ["1.0", "1.0", "3.0", "3.0", "5.0"],
            ["in", "out"],
            "Buildings.Controls.OBC.CDL.Discrete.Sampler",
        ),
        (
            _triggered_sampler_graph(),
            ["10", "0", "11", "1", "12", "1", "13", "0", "14", "1"],
            ["-1.0", "11.0", "11.0", "11.0", "14.0"],
            ["in", "clock", "out"],
            "Buildings.Controls.OBC.CDL.Discrete.TriggeredSampler",
        ),
        (
            _numeric_unit_delay_graph(),
            ["0", "10", "1", "11", "2", "20", "3", "30", "4", "40"],
            ["-1.0", "-1.0", "10.0", "10.0", "20.0"],
            ["in", "out"],
            "Buildings.Controls.OBC.CDL.Discrete.UnitDelay",
        ),
    ],
)
def test_discrete_numeric_java_kernels_match_independent_goldens(
    tmp_path: Path,
    graph: ControlGraph,
    arguments: list[str],
    expected: list[str],
    expected_slots: list[str],
    standard: str,
) -> None:
    content = NiagaraProgramPackageBuilder().build(graph)
    with zipfile.ZipFile(BytesIO(content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        program = manifest["programs"][0]
        class_name = program["class_name"]
        source = archive.read(program["paths"]["standalone_kernel"])
        slots = json.loads(archive.read(program["paths"]["slots"]))
    source_path = tmp_path / f"{class_name}.java"
    source_path.write_bytes(source)
    subprocess.run(
        ["javac", source_path.name],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        ["java", "-cp", str(tmp_path), class_name, *arguments],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == expected
    assert [slot["name"] for slot in slots["slots"]] == expected_slots
    assert program["source_contract"]["standard"] == standard


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac is not installed")
def test_timer_java_kernel_matches_independent_oce_golden(tmp_path: Path) -> None:
    content = NiagaraProgramPackageBuilder().build(_timer_graph())
    with zipfile.ZipFile(BytesIO(content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        program = manifest["programs"][0]
        class_name = program["class_name"]
        source = archive.read(program["paths"]["standalone_kernel"])
        slots = json.loads(archive.read(program["paths"]["slots"]))
    source_path = tmp_path / f"{class_name}.java"
    source_path.write_bytes(source)
    subprocess.run(
        ["javac", source_path.name],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    arguments = [
        "0.0",
        "1",
        "0.5",
        "1",
        "1.0",
        "1",
        "1.0",
        "1",
        "1.5",
        "0",
        "2.0",
        "1",
        "2.5",
        "1",
    ]
    result = subprocess.run(
        ["java", "-cp", str(tmp_path), class_name, *arguments],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == [
        "0.0,false",
        "0.5,false",
        "1.0,true",
        "1.0,true",
        "0.0,false",
        "0.0,false",
        "0.5,false",
    ]
    assert [(item["name"], item["type_spec"]) for item in slots["slots"]] == [
        ("in", "b:StatusBoolean"),
        ("elapsed", "b:StatusNumeric"),
        ("passed", "b:StatusBoolean"),
    ]


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac is not installed")
def test_timer_with_reset_java_kernel_matches_source_recurrence(tmp_path: Path) -> None:
    content = NiagaraProgramPackageBuilder().build(_timer_with_reset_graph())
    with zipfile.ZipFile(BytesIO(content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        program = manifest["programs"][0]
        class_name = program["class_name"]
        source = archive.read(program["paths"]["standalone_kernel"])
        slots = json.loads(archive.read(program["paths"]["slots"]))
    source_path = tmp_path / f"{class_name}.java"
    source_path.write_bytes(source)
    subprocess.run(
        ["javac", source_path.name],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        [
            "java",
            "-cp",
            str(tmp_path),
            class_name,
            "0", "1", "0",
            "1", "1", "0",
            "3", "1", "0",
            "4", "1", "1",
            "5", "1", "1",
            "7", "1", "0",
            "8", "0", "0",
            "9", "1", "0",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == [
        "0.0,false",
        "1.0,false",
        "3.0,true",
        "0.0,false",
        "1.0,false",
        "3.0,true",
        "0.0,false",
        "0.0,false",
    ]
    assert [(item["name"], item["type_spec"]) for item in slots["slots"]] == [
        ("in", "b:StatusBoolean"),
        ("reset", "b:StatusBoolean"),
        ("elapsed", "b:StatusNumeric"),
        ("passed", "b:StatusBoolean"),
    ]
    assert program["behavior_kind"] == "timer_with_reset"


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac is not installed")
def test_accumulating_timer_java_kernel_matches_pinned_limiting_case(
    tmp_path: Path,
) -> None:
    content = NiagaraProgramPackageBuilder().build(_accumulating_timer_graph())
    with zipfile.ZipFile(BytesIO(content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        program = manifest["programs"][0]
        class_name = program["class_name"]
        source = archive.read(program["paths"]["standalone_kernel"])
        slots = json.loads(archive.read(program["paths"]["slots"]))
    source_path = tmp_path / f"{class_name}.java"
    source_path.write_bytes(source)
    subprocess.run(
        ["javac", source_path.name],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        [
            "java",
            "-cp",
            str(tmp_path),
            class_name,
            "0", "0", "0",
            "1", "1", "0",
            "3", "1", "0",
            "4", "0", "0",
            "5", "1", "0",
            "6", "1", "1",
            "7", "1", "1",
            "8", "0", "1",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == [
        "0.0,false",
        "0.0,false",
        "2.0,false",
        "3.0,false",
        "3.0,true",
        "0.0,false",
        "1.0,false",
        "2.0,false",
    ]
    assert [slot["name"] for slot in slots["slots"]] == [
        "in",
        "reset",
        "elapsed",
        "passed",
    ]
    assert program["behavior_kind"] == "timer_accumulating"


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac is not installed")
def test_moving_average_java_kernel_matches_oce_bits(tmp_path: Path) -> None:
    content = NiagaraProgramPackageBuilder().build(_moving_average_graph())
    with zipfile.ZipFile(BytesIO(content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        program = manifest["programs"][0]
        class_name = program["class_name"]
        source = archive.read(program["paths"]["standalone_kernel"])
    source_path = tmp_path / f"{class_name}.java"
    source_path.write_bytes(source)
    subprocess.run(
        ["javac", source_path.name],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    arguments = ["0", "2", "0.5", "2", "1", "4", "1.5", "4", "2.25", "1"]
    result = subprocess.run(
        ["java", "-cp", str(tmp_path), class_name, *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    actual_bits = [
        struct.unpack(">Q", struct.pack(">d", float(value)))[0]
        for value in result.stdout.splitlines()
    ]

    assert actual_bits == [
        0x0000000000000000,
        0x3FFFEFA6115F8D8A,
        0x4008000000000000,
        0x4010000000000000,
        0x3FFC000000000000,
    ]


@pytest.mark.skipif(shutil.which("javac") is None, reason="javac is not installed")
def test_assert_warning_java_kernel_and_zero_output_program_contract(tmp_path: Path) -> None:
    content = NiagaraProgramPackageBuilder().build(_assert_warning_graph())
    with zipfile.ZipFile(BytesIO(content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        program = manifest["programs"][0]
        class_name = program["class_name"]
        source = archive.read(program["paths"]["standalone_kernel"])
        slots = json.loads(archive.read(program["paths"]["slots"]))
        program_source = archive.read(program["paths"]["program_source"]).decode()
    source_path = tmp_path / f"{class_name}.java"
    source_path.write_bytes(source)
    subprocess.run(
        ["javac", source_path.name],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        ["java", "-cp", str(tmp_path), class_name, "1", "0", "0", "1"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == [
        'Warning: airflow is below 50%. "Check" sensor.',
        'Warning: airflow is below 50%. "Check" sensor.',
    ]
    assert slots["slots"] == [
        {
            "direction": "input",
            "flags": "sL",
            "name": "condition",
            "type_spec": "b:StatusBoolean",
        }
    ]
    assert "java.util.logging.Logger" in program_source
    assert program["source_contract"]["signal_outputs"] == 0


def test_g36_api_downloads_reviewable_program_package(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))

    response = client.post(f"/api/library/g36/controllers/{CONTROLLER}/niagara-program-package")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert "SupplySignals-niagara-programs.zip" in response.headers["content-disposition"]
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["controller_id"] == CONTROLLER
    assert manifest["programs"][0]["behavior_kind"] == "pid_with_reset"
    assert manifest["runtime_qualified"] is False


def test_g36_api_downloads_trim_and_respond_program_package(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))

    response = client.post(
        f"/api/library/g36/controllers/{TRIM_CONTROLLER}/niagara-program-package"
    )

    assert response.status_code == 200, response.text
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        program = manifest["programs"][0]
        source = archive.read(program["paths"]["program_source"]).decode()
    assert manifest["controller_id"] == TRIM_CONTROLLER
    assert program["behavior_kind"] == "trim_and_respond"
    assert "double trueDelay = DELAY_SECONDS + SAMPLE_PERIOD_SECONDS;" in source
    assert manifest["licensed_workbench_compile_required"] is True
    assert manifest["runtime_qualified"] is False


def test_g36_api_packages_all_exact_temporal_programs(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(tmp_path / "runs"))

    response = client.post(
        f"/api/library/g36/controllers/{HYSTERESIS_CONTROLLER}/niagara-program-package"
    )
    temporal = client.post(
        f"/api/library/g36/controllers/{EXACTNESS_BLOCKED_CONTROLLER}/niagara-program-package"
    )

    assert response.status_code == 200, response.text
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["programs"]
    assert {item["behavior_kind"] for item in manifest["programs"]} == {"hysteresis"}
    assert temporal.status_code == 200, temporal.text
    with zipfile.ZipFile(BytesIO(temporal.content)) as archive:
        temporal_manifest = json.loads(archive.read("manifest.json"))
    assert {item["behavior_kind"] for item in temporal_manifest["programs"]} == {
        "boolean_delay",
        "boolean_true_false_hold",
        "hysteresis",
    }


def test_generic_boolean_delay_cannot_claim_cdl_true_delay_contract() -> None:
    graph = _true_delay_graph()
    graph.blocks[1].config.pop("semantic_contract")

    with pytest.raises(ValueError, match="explicit CDL.Logical.TrueDelay"):
        NiagaraProgramPackageBuilder().build(graph)


def test_boolean_pre_requires_explicit_sampled_scan_contract() -> None:
    graph = _boolean_pre_host_tick_graph()
    graph.blocks[1].config["execution_profile"] = "modelica_exact"

    with pytest.raises(ValueError, match="host_tick_v1 semantic contract"):
        NiagaraProgramPackageBuilder().build(graph)


def test_plant_initialization_requires_explicit_source_contract() -> None:
    graph = _boolean_initialization_graph()
    graph.blocks[1].config["semantic_contract"] = "invented.Initialization"

    with pytest.raises(ValueError, match="Utilities.Initialization semantic contract"):
        NiagaraProgramPackageBuilder().build(graph)


def test_plant_timer_with_reset_requires_explicit_source_contract() -> None:
    graph = _timer_with_reset_graph()
    graph.blocks[2].config["semantic_contract"] = "invented.TimerWithReset"

    with pytest.raises(ValueError, match="Utilities.TimerWithReset semantic contract"):
        NiagaraProgramPackageBuilder().build(graph)


@pytest.mark.parametrize(
    "graph",
    [_numeric_sampler_graph(), _triggered_sampler_graph(), _numeric_unit_delay_graph()],
)
def test_discrete_numeric_programs_require_explicit_cdl_contract(
    graph: ControlGraph,
) -> None:
    stateful = next(
        block
        for block in graph.blocks
        if block.kind
        in {
            BlockKind.NUMERIC_SAMPLER,
            BlockKind.NUMERIC_LATCH,
            BlockKind.NUMERIC_UNIT_DELAY,
        }
    )
    stateful.config.pop("semantic_contract")

    with pytest.raises(ValueError, match="explicit CDL.Discrete"):
        NiagaraProgramPackageBuilder().build(graph)


def test_g36_api_packages_clear_dominant_latch(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))

    response = client.post(
        f"/api/library/g36/controllers/{LATCH_CONTROLLER}/niagara-program-package"
    )

    assert response.status_code == 200, response.text
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert {item["behavior_kind"] for item in manifest["programs"]} == {
        "boolean_delay",
        "boolean_set_reset",
    }


def test_g36_api_packages_relief_fan_temporal_stack(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))

    response = client.post(
        f"/api/library/g36/controllers/{RELIEF_FAN_CONTROLLER}/niagara-program-package"
    )

    assert response.status_code == 200, response.text
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    behaviors = {item["behavior_kind"] for item in manifest["programs"]}
    assert {"boolean_set_reset", "timer", "moving_average"} <= behaviors


def test_g36_api_packages_array_relief_group_under_explicit_host_tick_profile(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(tmp_path / "runs"))

    response = client.post(
        f"/api/library/g36/controllers/{RELIEF_FAN_GROUP_CONTROLLER}/"
        "niagara-program-package?execution_profile=host_tick_v1"
    )

    assert response.status_code == 200, response.text
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    pre_programs = [
        item for item in manifest["programs"] if item["behavior_kind"] == "boolean_pre_host_tick"
    ]
    assert len(pre_programs) == 2
    assert all(
        item["source_contract"]["execution_profile"] == "host_tick_v1" for item in pre_programs
    )
    assert all(
        item["source_contract"]["limitation"] == "not Modelica same-time event iteration"
        for item in pre_programs
    )


def test_g36_api_packages_complete_time_suppression_temporal_stack(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(tmp_path / "runs"))

    response = client.post(
        f"/api/library/g36/controllers/{TIME_SUPPRESSION_CONTROLLER}/"
        "niagara-program-package?execution_profile=host_tick_v1"
    )

    assert response.status_code == 200, response.text
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        graph = json.loads(archive.read(manifest["control_graph_path"]))
        wiring = json.loads(archive.read(manifest["wiring_plan_path"]))
    behaviors = {item["behavior_kind"] for item in manifest["programs"]}
    assert {
        "boolean_pre_host_tick",
        "numeric_sampler",
        "numeric_latch",
        "numeric_unit_delay",
    } <= behaviors
    assert wiring["component_count"] == len(graph["blocks"]) == 35
    assert wiring["link_count"] == len(graph["links"]) == 47
    assert wiring["generated_program_count"] == len(manifest["programs"]) == 9
