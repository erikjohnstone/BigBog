#!/usr/bin/env python3
"""Create the real contractor inputs used by the recorded whole-building demo."""

from __future__ import annotations

import argparse
import io
import json
import zipfile
from pathlib import Path

from bactalk.demo import demo_job, generalist_demo_job
from bactalk.domain import (
    AcceptanceCase,
    AcceptancePhase,
    ComparisonOperator,
    DataType,
    FaultInjection,
    FaultKind,
    JobSpec,
    OutputExpectation,
    PointRole,
    PointSpec,
    QualificationCategory,
    SequenceSpec,
)
from bactalk.projects import (
    EquipmentRelationship,
    ProjectAcceptanceCase,
    ProjectAcceptancePhase,
    ProjectOutputExpectation,
    ProjectSignalBinding,
    ProjectSpec,
)

SITE = "Riverview Medical Office"


def point(
    name: str,
    label: str,
    data_type: DataType,
    role: PointRole,
    default: float | bool,
    *,
    units: str | None = None,
) -> PointSpec:
    return PointSpec(
        name=name,
        label=label,
        data_type=data_type,
        role=role,
        default=default,
        units=units,
    )


def exhaust_job() -> JobSpec:
    return JobSpec(
        name="Garage exhaust command and proof",
        site=SITE,
        equipment_name="EF_1",
        equipment_brick_class="brick:Exhaust_Fan",
        sequence=SequenceSpec(
            family="EXHAUST_FAN_PROOF",
            version="BACTalk exhaust proof 0.1",
            parameters={"proof_delay_seconds": 3.0},
        ),
        points=[
            point("Enable", "AHU enable interlock", DataType.BOOLEAN, PointRole.STATUS, False),
            point("FanStatus", "Exhaust fan proof", DataType.BOOLEAN, PointRole.STATUS, False),
            point("FanCommand", "Exhaust fan command", DataType.BOOLEAN, PointRole.COMMAND, False),
            point(
                "FanProofAlarm", "Exhaust fan proof alarm", DataType.BOOLEAN, PointRole.ALARM, False
            ),
        ],
        acceptance_tests=[
            AcceptanceCase(
                name="command starts within proof grace period",
                qualifications=[QualificationCategory.NORMAL_OPERATION],
                inputs={"Enable": True, "FanStatus": False},
                expectations=[
                    OutputExpectation(target="FanCommand", value=True),
                    OutputExpectation(target="FanProofAlarm", value=False),
                ],
            ),
            AcceptanceCase(
                name="proof failure and recovery",
                qualifications=[
                    QualificationCategory.ACTUATOR_PROOF_FAILURE,
                    QualificationCategory.ALARM_BEHAVIOR,
                    QualificationCategory.RECOVERY,
                ],
                timeline=[
                    AcceptancePhase(
                        name="startup grace",
                        inputs={"Enable": True, "FanStatus": True},
                        repeat=2,
                        faults=[
                            FaultInjection(
                                id="lost_fan_proof",
                                target="FanStatus",
                                kind=FaultKind.FORCE,
                                value=False,
                            )
                        ],
                        expectations=[OutputExpectation(target="FanProofAlarm", value=False)],
                    ),
                    AcceptancePhase(
                        name="proof timeout",
                        repeat=1,
                        faults=[
                            FaultInjection(
                                id="lost_fan_proof",
                                target="FanStatus",
                                kind=FaultKind.FORCE,
                                value=False,
                            )
                        ],
                        expectations=[OutputExpectation(target="FanProofAlarm", value=True)],
                    ),
                    AcceptancePhase(
                        name="proof restored",
                        inputs={"FanStatus": True},
                        expectations=[OutputExpectation(target="FanProofAlarm", value=False)],
                    ),
                ],
                expectations=[
                    OutputExpectation(target="FanCommand", value=True),
                    OutputExpectation(target="FanProofAlarm", value=False),
                ],
            ),
        ],
        notes="Enable is driven by AHU_1.SupplyFanCommand in the whole-building project.",
    )


def static_pressure_job() -> JobSpec:
    return JobSpec(
        name="AHU-1 duct static pressure loop",
        site=SITE,
        equipment_name="AHU_1_STATIC",
        equipment_brick_class="brick:AHU",
        sequence=SequenceSpec(
            family="AHU_DUCT_STATIC_PI",
            version="BACTalk PI prototype 0.1",
            parameters={"proportional_constant": 20.0, "integral_constant": 1.0},
        ),
        points=[
            point("Enable", "Supply fan enable", DataType.BOOLEAN, PointRole.STATUS, False),
            point(
                "DuctStatic",
                "Duct static pressure",
                DataType.NUMERIC,
                PointRole.SENSOR,
                0.0,
                units="inH2O",
            ),
            point(
                "DuctStaticSetpoint",
                "Duct static setpoint",
                DataType.NUMERIC,
                PointRole.SETPOINT,
                1.5,
                units="inH2O",
            ),
            point(
                "SupplyFanSpeedCommand",
                "Supply fan speed command",
                DataType.NUMERIC,
                PointRole.COMMAND,
                0.0,
                units="%",
            ),
        ],
        acceptance_tests=[
            AcceptanceCase(
                name="disabled loop fails to zero",
                qualifications=[QualificationCategory.DISABLED_SHUTDOWN],
                inputs={"Enable": False, "DuctStatic": 1.0, "DuctStaticSetpoint": 1.5},
                expectations=[OutputExpectation(target="SupplyFanSpeedCommand", value=0.0)],
            ),
            AcceptanceCase(
                name="reverse acting response",
                qualifications=[
                    QualificationCategory.NORMAL_OPERATION,
                    QualificationCategory.OUTPUT_BOUNDS,
                ],
                timeline=[
                    AcceptancePhase(
                        name="initialize disabled",
                        inputs={"Enable": False, "DuctStatic": 1.0, "DuctStaticSetpoint": 1.5},
                        expectations=[OutputExpectation(target="SupplyFanSpeedCommand", value=0.0)],
                    ),
                    AcceptancePhase(
                        name="enable below setpoint",
                        inputs={"Enable": True},
                        repeat=3,
                        expectations=[
                            OutputExpectation(
                                target="SupplyFanSpeedCommand",
                                operator=ComparisonOperator.GREATER_THAN,
                                value=10.0,
                            )
                        ],
                    ),
                ],
                expectations=[
                    OutputExpectation(
                        target="SupplyFanSpeedCommand",
                        operator=ComparisonOperator.BETWEEN,
                        value=0.0,
                        upper=100.0,
                    )
                ],
            ),
        ],
    )


def pump_job() -> JobSpec:
    common = {
        "SystemEnable": False,
        "Pump1LeadSelect": True,
        "Pump1Available": True,
        "Pump2Available": True,
    }

    def expected(first: bool, second: bool, alarm: bool) -> list[OutputExpectation]:
        return [
            OutputExpectation(target="Pump1Command", value=first),
            OutputExpectation(target="Pump2Command", value=second),
            OutputExpectation(target="NoPumpAvailableAlarm", value=alarm),
        ]

    return JobSpec(
        name="Heating-water duty standby pump pair",
        site=SITE,
        equipment_name="HWP_PAIR_1",
        equipment_brick_class="brick:Pump",
        sequence=SequenceSpec(
            family="TWO_PUMP_AVAILABILITY_SELECTOR",
            version="BACTalk selector 0.1",
        ),
        points=[
            point(
                "SystemEnable",
                "Heating water system enable",
                DataType.BOOLEAN,
                PointRole.STATUS,
                False,
            ),
            point(
                "Pump1LeadSelect", "Pump 1 lead selection", DataType.BOOLEAN, PointRole.STATUS, True
            ),
            point("Pump1Available", "Pump 1 available", DataType.BOOLEAN, PointRole.STATUS, True),
            point("Pump2Available", "Pump 2 available", DataType.BOOLEAN, PointRole.STATUS, True),
            point("Pump1Command", "Pump 1 command", DataType.BOOLEAN, PointRole.COMMAND, False),
            point("Pump2Command", "Pump 2 command", DataType.BOOLEAN, PointRole.COMMAND, False),
            point(
                "NoPumpAvailableAlarm",
                "No pump available alarm",
                DataType.BOOLEAN,
                PointRole.ALARM,
                False,
            ),
        ],
        acceptance_tests=[
            AcceptanceCase(
                name="disabled",
                inputs=common,
                qualifications=[QualificationCategory.DISABLED_SHUTDOWN],
                expectations=expected(False, False, False),
            ),
            AcceptanceCase(
                name="selected lead runs",
                inputs={**common, "SystemEnable": True},
                qualifications=[QualificationCategory.NORMAL_OPERATION],
                expectations=expected(True, False, False),
            ),
            AcceptanceCase(
                name="lead failure selects standby",
                inputs={**common, "SystemEnable": True},
                qualifications=[QualificationCategory.EQUIPMENT_UNAVAILABLE],
                faults=[
                    FaultInjection(
                        id="pump_1_unavailable",
                        target="Pump1Available",
                        kind=FaultKind.FORCE,
                        value=False,
                    )
                ],
                expectations=expected(False, True, False),
            ),
            AcceptanceCase(
                name="no available pump fails closed",
                inputs={**common, "SystemEnable": True},
                qualifications=[QualificationCategory.ALL_EQUIPMENT_UNAVAILABLE],
                faults=[
                    FaultInjection(
                        id="pump_1_unavailable",
                        target="Pump1Available",
                        kind=FaultKind.FORCE,
                        value=False,
                    ),
                    FaultInjection(
                        id="pump_2_unavailable",
                        target="Pump2Available",
                        kind=FaultKind.FORCE,
                        value=False,
                    ),
                ],
                expectations=expected(False, False, True),
            ),
        ],
    )


def project_spec() -> ProjectSpec:
    ahu = generalist_demo_job().model_copy(
        update={
            "name": "AHU-1 safety and discharge cooling",
            "site": SITE,
            "equipment_name": "AHU_1",
        }
    )
    vav_101 = demo_job().model_copy(
        update={"name": "East wing VAV-101", "site": SITE, "equipment_name": "VAV_101"}
    )
    vav_102 = demo_job().model_copy(
        update={"name": "East wing VAV-102", "site": SITE, "equipment_name": "VAV_102"}
    )
    return ProjectSpec(
        name="Riverview integrated air and hydronic systems",
        site=SITE,
        equipment=[ahu, static_pressure_job(), vav_101, vav_102, pump_job(), exhaust_job()],
        relationships=[
            EquipmentRelationship(source="AHU_1", relation="feeds", target="VAV_101"),
            EquipmentRelationship(source="AHU_1", relation="feeds", target="VAV_102"),
            EquipmentRelationship(source="AHU_1_STATIC", relation="controls", target="AHU_1"),
            EquipmentRelationship(source="HWP_PAIR_1", relation="serves", target="AHU_1"),
            EquipmentRelationship(source="AHU_1", relation="enables", target="EF_1"),
        ],
        signal_bindings=[
            ProjectSignalBinding(
                source_equipment="AHU_1",
                source_point="SupplyFanCommand",
                target_equipment="EF_1",
                target_point="Enable",
            )
        ],
        acceptance_tests=[
            ProjectAcceptanceCase(
                name="AHU occupancy request propagates through exhaust proof sequence",
                phases=[
                    ProjectAcceptancePhase(
                        name="unoccupied shutdown",
                        inputs={
                            "AHU_1.Occupied": False,
                            "AHU_1.DuctStatic": 1.0,
                            "AHU_1.DuctHighLimit": 2.5,
                            "AHU_1.DischargeAirTemp": 55.0,
                            "AHU_1.DischargeAirTempSetpoint": 55.0,
                            "EF_1.FanStatus": False,
                        },
                        expectations=[
                            ProjectOutputExpectation(
                                equipment="EF_1", point="FanCommand", value=False
                            ),
                            ProjectOutputExpectation(
                                equipment="EF_1", point="FanProofAlarm", value=False
                            ),
                        ],
                    ),
                    ProjectAcceptancePhase(
                        name="occupied and proof arrives",
                        inputs={"AHU_1.Occupied": True, "EF_1.FanStatus": True},
                        repeat=2,
                        expectations=[
                            ProjectOutputExpectation(
                                equipment="EF_1", point="FanCommand", value=True
                            ),
                            ProjectOutputExpectation(
                                equipment="EF_1", point="FanProofAlarm", value=False
                            ),
                        ],
                    ),
                    ProjectAcceptancePhase(
                        name="proof lost beyond delay",
                        inputs={"EF_1.FanStatus": False},
                        repeat=3,
                        expectations=[
                            ProjectOutputExpectation(
                                equipment="EF_1", point="FanCommand", value=True
                            ),
                            ProjectOutputExpectation(
                                equipment="EF_1", point="FanProofAlarm", value=True
                            ),
                        ],
                    ),
                    ProjectAcceptancePhase(
                        name="proof recovery clears alarm",
                        inputs={"EF_1.FanStatus": True},
                        expectations=[
                            ProjectOutputExpectation(
                                equipment="EF_1", point="FanCommand", value=True
                            ),
                            ProjectOutputExpectation(
                                equipment="EF_1", point="FanProofAlarm", value=False
                            ),
                        ],
                    ),
                ],
            )
        ],
        station_assembly_mode="insert",
    )


def station_template() -> bytes:
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<bajaObjectGraph version="4.0">
  <p t="b:UnrestrictedFolder" m="b=baja">
    <p n="Config" t="b:Folder" h="1">
      <p n="Drivers" t="b:Folder">
        <p n="BACnetNetwork" t="b:Folder">
          <p n="ExampleCampus" t="b:Folder" h="2"/>
        </p>
      </p>
    </p>
    <p n="Services" t="b:Folder" h="3"/>
  </p>
</bajaObjectGraph>"""
    destination = io.BytesIO()
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("file.xml", xml)
    return destination.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/demo-inputs"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    project_path = args.output / "riverview-complex-building-project.json"
    station_path = args.output / "riverview-contractor-station.bog"
    project_path.write_text(
        json.dumps(project_spec().model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    station_path.write_bytes(station_template())
    print(project_path.resolve())
    print(station_path.resolve())


if __name__ == "__main__":
    main()
