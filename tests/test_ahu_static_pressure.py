import zipfile
from pathlib import Path

from bactalk.agent import ProgrammingAgent, SequencePackPlanner
from bactalk.compiler import NiagaraCompiler
from bactalk.domain import (
    AcceptanceCase,
    AcceptancePhase,
    ComparisonOperator,
    DataType,
    JobSpec,
    OutputExpectation,
    PointRole,
    PointSpec,
    SequenceSpec,
)


def _job() -> JobSpec:
    return JobSpec(
        name="AHU duct static control",
        site="Test Campus",
        equipment_name="AHU_4",
        equipment_brick_class="brick:AHU",
        sequence=SequenceSpec(
            family="AHU_DUCT_STATIC_PI",
            version="BACTalk PI prototype 0.1",
            parameters={
                "proportional_constant": 20.0,
                "integral_constant": 1.0,
            },
        ),
        points=[
            PointSpec(
                name="Enable",
                label="Supply fan enable",
                data_type=DataType.BOOLEAN,
                role=PointRole.STATUS,
                default=False,
            ),
            PointSpec(
                name="DuctStatic",
                label="Duct static pressure",
                data_type=DataType.NUMERIC,
                role=PointRole.SENSOR,
                units="inH2O",
                default=0.0,
            ),
            PointSpec(
                name="DuctStaticSetpoint",
                label="Duct static pressure setpoint",
                data_type=DataType.NUMERIC,
                role=PointRole.SETPOINT,
                units="inH2O",
                default=1.5,
            ),
            PointSpec(
                name="SupplyFanSpeedCommand",
                label="Supply fan speed command",
                data_type=DataType.NUMERIC,
                role=PointRole.COMMAND,
                units="%",
                default=0.0,
            ),
        ],
        acceptance_tests=[
            AcceptanceCase(
                name="disabled output",
                inputs={"Enable": False, "DuctStatic": 1.0, "DuctStaticSetpoint": 1.5},
                expectations=[OutputExpectation(target="SupplyFanSpeedCommand", value=0.0)],
            ),
            AcceptanceCase(
                name="reverse acting response",
                timeline=[
                    AcceptancePhase(
                        name="disabled",
                        inputs={
                            "Enable": False,
                            "DuctStatic": 1.0,
                            "DuctStaticSetpoint": 1.5,
                        },
                        expectations=[OutputExpectation(target="SupplyFanSpeedCommand", value=0.0)],
                    ),
                    AcceptancePhase(
                        name="enabled below setpoint",
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
            AcceptanceCase(
                name="high pressure drives minimum",
                inputs={"Enable": True, "DuctStatic": 2.0, "DuctStaticSetpoint": 1.5},
                expectations=[OutputExpectation(target="SupplyFanSpeedCommand", value=0.0)],
            ),
        ],
    )


def test_ahu_static_pressure_pack_tests_and_compiles(tmp_path: Path) -> None:
    result = ProgrammingAgent(SequencePackPlanner()).run(_job())

    assert result.report.passed
    assert result.graph.metadata["sequence_family"] == "AHU_DUCT_STATIC_PI"
    destination = NiagaraCompiler().compile(result.graph, tmp_path / "ahu-static.bog")
    with zipfile.ZipFile(destination) as archive:
        xml = archive.read("file.xml")
    assert b"kitControl:LoopPoint" in xml
    assert b"conv:StatusBooleanToFrozenEnum" in xml
