from __future__ import annotations

from bactalk.domain import (
    AcceptanceCase,
    AlarmRequirement,
    BacnetDeviceSpec,
    BacnetObjectSpec,
    BacnetScan,
    Block,
    BlockKind,
    ComparisonOperator,
    ControlGraph,
    DataType,
    DeliverableRequirements,
    GraphicsViewRequirement,
    HistoryRequirement,
    JobSpec,
    Link,
    OutputExpectation,
    PointRole,
    PointSpec,
    ScheduleRequirement,
    SequenceSpec,
    ShopProfile,
    WeeklySchedulePeriod,
)


def demo_job() -> JobSpec:
    points = [
        PointSpec(
            name="ZoneTemp",
            label="Zone temperature",
            data_type=DataType.NUMERIC,
            role=PointRole.SENSOR,
            units="°F",
            default=76.0,
            bacnet_object="analog-input,1",
            brick_class="brick:Zone_Air_Temperature_Sensor",
        ),
        PointSpec(
            name="CoolingSetpoint",
            label="Effective cooling setpoint",
            data_type=DataType.NUMERIC,
            role=PointRole.SETPOINT,
            units="°F",
            default=74.0,
            brick_class="brick:Zone_Air_Cooling_Temperature_Setpoint",
        ),
        PointSpec(
            name="HeatingSetpoint",
            label="Effective heating setpoint",
            data_type=DataType.NUMERIC,
            role=PointRole.SETPOINT,
            units="°F",
            default=70.0,
            brick_class="brick:Zone_Air_Heating_Temperature_Setpoint",
        ),
        PointSpec(
            name="Occupied",
            label="Occupied mode",
            data_type=DataType.BOOLEAN,
            role=PointRole.STATUS,
            default=True,
            brick_class="brick:Occupancy_Status",
        ),
        PointSpec(
            name="DamperCommand",
            label="VAV damper command",
            data_type=DataType.NUMERIC,
            role=PointRole.COMMAND,
            units="%",
            default=0.0,
            bacnet_object="analog-output,1",
            brick_class="brick:Damper_Position_Command",
        ),
        PointSpec(
            name="ValveCommand",
            label="Reheat valve command",
            data_type=DataType.NUMERIC,
            role=PointRole.COMMAND,
            units="%",
            default=0.0,
            bacnet_object="analog-output,2",
            brick_class="brick:Valve_Command",
        ),
        PointSpec(
            name="CoolingDemand",
            label="Zone cooling demand",
            data_type=DataType.NUMERIC,
            role=PointRole.STATUS,
            units="%",
            default=0.0,
        ),
        PointSpec(
            name="HeatingDemand",
            label="Zone heating demand",
            data_type=DataType.NUMERIC,
            role=PointRole.STATUS,
            units="%",
            default=0.0,
        ),
        PointSpec(
            name="HighZoneTempAlarm",
            label="High zone temperature",
            data_type=DataType.BOOLEAN,
            role=PointRole.ALARM,
            default=False,
        ),
    ]
    return JobSpec(
        name="North Wing VAV-12 retrofit",
        site="Example Campus",
        equipment_name="VAV_12",
        equipment_brick_class="brick:VAV",
        sequence=SequenceSpec(
            parameters={
                "loop_span_f": 3.0,
                "minimum_damper_pct": 20.0,
                "high_zone_temp_f": 80.0,
            }
        ),
        points=points,
        deliverables=DeliverableRequirements(
            shop_profile=ShopProfile(
                name="Example Controls Standards",
                version="1.0",
                station_folder="Config/Drivers/BACnetNetwork/ExampleCampus",
                niagara_site_ord="station:|slot:/Config/Sites/ExampleCampus",
                graphics_theme="Example light equipment theme",
            ),
            alarms=[
                AlarmRequirement(
                    point="HighZoneTempAlarm",
                    alarm_class="HVAC-Critical",
                    priority=100,
                    delay_seconds=300,
                    offnormal_text="Zone temperature high",
                    normal_text="Zone temperature normal",
                    routing=["Facilities"],
                )
            ],
            schedules=[
                ScheduleRequirement(
                    id="OccupancySchedule",
                    output_point="Occupied",
                    timezone="America/New_York",
                    weekly_periods=[
                        WeeklySchedulePeriod(day=day, start="07:00", end="18:00")
                        for day in ("monday", "tuesday", "wednesday", "thursday", "friday")
                    ],
                )
            ],
            histories=[
                HistoryRequirement(
                    point="ZoneTemp",
                    mode="fixed_interval",
                    interval_seconds=300,
                    retention_days=365,
                )
            ],
            graphics=[
                GraphicsViewRequirement(
                    id="VavOverview",
                    title="VAV-12 Overview",
                    points=[point.name for point in points],
                    template="ExampleVavOverview",
                    navigation_parent="North Wing",
                )
            ],
        ),
        bacnet_scan=BacnetScan(
            source="synthetic demo scan",
            devices=[
                BacnetDeviceSpec(
                    device_instance=120012,
                    address="192.0.2.12/24:47808",
                    name="VAV-12 Controller",
                    vendor_id=999,
                    objects=[
                        BacnetObjectSpec(
                            object_id="analog-input,1",
                            name="Zone Temperature",
                            data_type=DataType.NUMERIC,
                            units="°F",
                            present_value=76.0,
                        ),
                        BacnetObjectSpec(
                            object_id="analog-output,1",
                            name="Damper Command",
                            data_type=DataType.NUMERIC,
                            writable=True,
                            units="%",
                            present_value=0.0,
                        ),
                        BacnetObjectSpec(
                            object_id="analog-output,2",
                            name="Reheat Valve Command",
                            data_type=DataType.NUMERIC,
                            writable=True,
                            units="%",
                            present_value=0.0,
                        ),
                    ],
                )
            ],
        ),
        notes="Synthetic demonstration job; no live building connection.",
    )


def generalist_demo_job() -> JobSpec:
    """An equipment-neutral AHU job exercised through its installed pack."""

    # Retained as an inspectable reference fixture; the deterministic planner
    # independently rebuilds this program from the job contract.
    _reference_graph = ControlGraph(
        name="AHU_3_Safety_And_Cooling",
        blocks=[
            Block(
                id="Occupied",
                kind=BlockKind.BOOLEAN_INPUT,
                label="Occupied mode",
                config={"default": False},
                x=40,
                y=60,
            ),
            Block(
                id="DuctStatic",
                kind=BlockKind.NUMERIC_INPUT,
                label="Duct static pressure",
                config={"default": 0.0},
                x=40,
                y=150,
            ),
            Block(
                id="DuctHighLimit",
                kind=BlockKind.NUMERIC_INPUT,
                label="Duct pressure high limit",
                config={"default": 2.5},
                x=40,
                y=240,
            ),
            Block(
                id="DischargeAirTemp",
                kind=BlockKind.NUMERIC_INPUT,
                label="Discharge air temperature",
                config={"default": 55.0},
                x=40,
                y=330,
            ),
            Block(
                id="DischargeAirTempSetpoint",
                kind=BlockKind.NUMERIC_INPUT,
                label="Discharge air setpoint",
                config={"default": 55.0},
                x=40,
                y=420,
            ),
            Block(
                id="Zero",
                kind=BlockKind.NUMERIC_CONST,
                label="Zero percent",
                config={"value": 0.0},
                x=40,
                y=510,
            ),
            Block(
                id="Hundred",
                kind=BlockKind.NUMERIC_CONST,
                label="One hundred percent",
                config={"value": 100.0},
                x=40,
                y=600,
            ),
            Block(
                id="CoolingGain",
                kind=BlockKind.NUMERIC_CONST,
                label="Cooling gain",
                config={"value": 20.0},
                x=40,
                y=690,
            ),
            Block(
                id="PressureSafe",
                kind=BlockKind.LESS_THAN,
                label="Pressure below limit",
                x=300,
                y=150,
            ),
            Block(
                id="PressureHigh",
                kind=BlockKind.GREATER_THAN_OR_EQUAL,
                label="Pressure at high limit",
                x=300,
                y=240,
            ),
            Block(
                id="FanEnable",
                kind=BlockKind.AND,
                label="Occupied and pressure safe",
                x=560,
                y=105,
            ),
            Block(
                id="OccupiedPressureAlarm",
                kind=BlockKind.AND,
                label="Occupied pressure alarm",
                x=560,
                y=240,
            ),
            Block(
                id="CoolingError",
                kind=BlockKind.SUBTRACT,
                label="Discharge cooling error",
                x=300,
                y=390,
            ),
            Block(
                id="CoolingRaw",
                kind=BlockKind.MULTIPLY,
                label="Scale cooling command",
                x=560,
                y=390,
            ),
            Block(
                id="CoolingLowClamp",
                kind=BlockKind.MAXIMUM,
                label="Clamp cooling low",
                x=820,
                y=390,
            ),
            Block(
                id="CoolingClamped",
                kind=BlockKind.MINIMUM,
                label="Clamp cooling high",
                x=1080,
                y=390,
            ),
            Block(
                id="CoolingEnabled",
                kind=BlockKind.NUMERIC_SWITCH,
                label="Occupancy enable",
                x=1340,
                y=390,
            ),
            Block(
                id="SupplyFanCommand",
                kind=BlockKind.BOOLEAN_OUTPUT,
                label="Supply fan command",
                x=1340,
                y=105,
            ),
            Block(
                id="DuctPressureAlarm",
                kind=BlockKind.BOOLEAN_OUTPUT,
                label="Duct pressure alarm",
                x=1340,
                y=240,
            ),
            Block(
                id="CoolingValveCommand",
                kind=BlockKind.NUMERIC_OUTPUT,
                label="Cooling valve command",
                x=1600,
                y=390,
            ),
        ],
        links=[
            Link(source="DuctStatic", target="PressureSafe", target_slot="a"),
            Link(source="DuctHighLimit", target="PressureSafe", target_slot="b"),
            Link(source="DuctStatic", target="PressureHigh", target_slot="a"),
            Link(source="DuctHighLimit", target="PressureHigh", target_slot="b"),
            Link(source="Occupied", target="FanEnable", target_slot="a"),
            Link(source="PressureSafe", target="FanEnable", target_slot="b"),
            Link(source="Occupied", target="OccupiedPressureAlarm", target_slot="a"),
            Link(source="PressureHigh", target="OccupiedPressureAlarm", target_slot="b"),
            Link(source="DischargeAirTemp", target="CoolingError", target_slot="a"),
            Link(
                source="DischargeAirTempSetpoint",
                target="CoolingError",
                target_slot="b",
            ),
            Link(source="CoolingError", target="CoolingRaw", target_slot="a"),
            Link(source="CoolingGain", target="CoolingRaw", target_slot="b"),
            Link(source="CoolingRaw", target="CoolingLowClamp", target_slot="a"),
            Link(source="Zero", target="CoolingLowClamp", target_slot="b"),
            Link(source="CoolingLowClamp", target="CoolingClamped", target_slot="a"),
            Link(source="Hundred", target="CoolingClamped", target_slot="b"),
            Link(source="Occupied", target="CoolingEnabled", target_slot="selector"),
            Link(source="CoolingClamped", target="CoolingEnabled", target_slot="when_true"),
            Link(source="Zero", target="CoolingEnabled", target_slot="when_false"),
            Link(source="FanEnable", target="SupplyFanCommand", target_slot="in"),
            Link(
                source="OccupiedPressureAlarm",
                target="DuctPressureAlarm",
                target_slot="in",
            ),
            Link(source="CoolingEnabled", target="CoolingValveCommand", target_slot="in"),
        ],
        metadata={
            "sequence_family": "CUSTOM_AHU_SAFETY_COOLING",
            "source": "equipment-neutral BACTalk demo",
        },
    )
    points = [
        PointSpec(
            name="Occupied",
            label="Occupied mode",
            data_type=DataType.BOOLEAN,
            role=PointRole.STATUS,
            default=False,
            brick_class="brick:Occupancy_Status",
        ),
        PointSpec(
            name="DuctStatic",
            label="Supply duct static pressure",
            data_type=DataType.NUMERIC,
            role=PointRole.SENSOR,
            units="inH2O",
            default=0.0,
            brick_class="brick:Supply_Air_Static_Pressure_Sensor",
        ),
        PointSpec(
            name="DuctHighLimit",
            label="Duct pressure high limit",
            data_type=DataType.NUMERIC,
            role=PointRole.SETPOINT,
            units="inH2O",
            default=2.5,
        ),
        PointSpec(
            name="DischargeAirTemp",
            label="Discharge air temperature",
            data_type=DataType.NUMERIC,
            role=PointRole.SENSOR,
            units="°F",
            default=55.0,
            brick_class="brick:Discharge_Air_Temperature_Sensor",
        ),
        PointSpec(
            name="DischargeAirTempSetpoint",
            label="Discharge air temperature setpoint",
            data_type=DataType.NUMERIC,
            role=PointRole.SETPOINT,
            units="°F",
            default=55.0,
            brick_class="brick:Discharge_Air_Temperature_Setpoint",
        ),
        PointSpec(
            name="SupplyFanCommand",
            label="Supply fan command",
            data_type=DataType.BOOLEAN,
            role=PointRole.COMMAND,
            default=False,
            brick_class="brick:Fan_Command",
        ),
        PointSpec(
            name="CoolingValveCommand",
            label="Cooling valve command",
            data_type=DataType.NUMERIC,
            role=PointRole.COMMAND,
            units="%",
            default=0.0,
            brick_class="brick:Valve_Command",
        ),
        PointSpec(
            name="DuctPressureAlarm",
            label="Duct high-pressure alarm",
            data_type=DataType.BOOLEAN,
            role=PointRole.ALARM,
            default=False,
        ),
    ]
    cases = [
        AcceptanceCase(
            name="occupied cooling",
            inputs={
                "Occupied": True,
                "DuctStatic": 1.5,
                "DuctHighLimit": 2.5,
                "DischargeAirTemp": 60.0,
                "DischargeAirTempSetpoint": 55.0,
            },
            expectations=[
                OutputExpectation(target="SupplyFanCommand", value=True),
                OutputExpectation(
                    target="CoolingValveCommand",
                    value=100.0,
                    tolerance=0.01,
                ),
                OutputExpectation(target="DuctPressureAlarm", value=False),
            ],
        ),
        AcceptanceCase(
            name="unoccupied shutdown",
            inputs={
                "Occupied": False,
                "DuctStatic": 1.5,
                "DuctHighLimit": 2.5,
                "DischargeAirTemp": 65.0,
                "DischargeAirTempSetpoint": 55.0,
            },
            expectations=[
                OutputExpectation(target="SupplyFanCommand", value=False),
                OutputExpectation(target="CoolingValveCommand", value=0.0),
                OutputExpectation(target="DuctPressureAlarm", value=False),
            ],
        ),
        AcceptanceCase(
            name="duct high-pressure interlock",
            inputs={
                "Occupied": True,
                "DuctStatic": 2.7,
                "DuctHighLimit": 2.5,
                "DischargeAirTemp": 55.0,
                "DischargeAirTempSetpoint": 55.0,
            },
            expectations=[
                OutputExpectation(target="SupplyFanCommand", value=False),
                OutputExpectation(target="DuctPressureAlarm", value=True),
                OutputExpectation(
                    target="CoolingValveCommand",
                    operator=ComparisonOperator.LESS_THAN_OR_EQUAL,
                    value=0.0,
                ),
            ],
        ),
    ]
    return JobSpec(
        name="AHU-3 equipment-neutral controls proof",
        site="Example Campus",
        equipment_name="AHU_3",
        equipment_brick_class="brick:AHU",
        sequence=SequenceSpec(
            family="CUSTOM_AHU_SAFETY_COOLING",
            version="BACTalk generalist demonstration 1",
        ),
        points=points,
        control_graph=None,
        acceptance_tests=cases,
        notes="Synthetic AHU demonstration; no live building connection.",
    )
