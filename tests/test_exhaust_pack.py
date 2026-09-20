import zipfile
from pathlib import Path

from bactalk.agent import ProgrammingAgent, SequencePackPlanner
from bactalk.compiler import NiagaraCompiler
from bactalk.domain import (
    AcceptanceCase,
    AcceptancePhase,
    DataType,
    JobSpec,
    OutputExpectation,
    PointRole,
    PointSpec,
    SequenceSpec,
)


def _job() -> JobSpec:
    return JobSpec(
        name="Garage exhaust proof",
        site="Test Campus",
        equipment_name="EF_1",
        equipment_brick_class="brick:Exhaust_Fan",
        sequence=SequenceSpec(
            family="EXHAUST_FAN_PROOF",
            version="BACTalk exhaust proof 0.1",
            parameters={"proof_delay_seconds": 3.0},
        ),
        points=[
            PointSpec(
                name="Enable",
                label="Exhaust enable",
                data_type=DataType.BOOLEAN,
                role=PointRole.STATUS,
                default=False,
            ),
            PointSpec(
                name="FanStatus",
                label="Fan status",
                data_type=DataType.BOOLEAN,
                role=PointRole.STATUS,
                default=False,
            ),
            PointSpec(
                name="FanCommand",
                label="Fan command",
                data_type=DataType.BOOLEAN,
                role=PointRole.COMMAND,
                default=False,
            ),
            PointSpec(
                name="FanProofAlarm",
                label="Fan proof alarm",
                data_type=DataType.BOOLEAN,
                role=PointRole.ALARM,
                default=False,
            ),
        ],
        acceptance_tests=[
            AcceptanceCase(
                name="command starts before proof timeout",
                inputs={"Enable": True, "FanStatus": False},
                repeat=1,
                expectations=[
                    OutputExpectation(target="FanCommand", value=True),
                    OutputExpectation(target="FanProofAlarm", value=False),
                ],
            ),
            AcceptanceCase(
                name="missing proof alarms after timeout",
                inputs={"Enable": True, "FanStatus": False},
                repeat=3,
                expectations=[
                    OutputExpectation(target="FanCommand", value=True),
                    OutputExpectation(target="FanProofAlarm", value=True),
                ],
            ),
            AcceptanceCase(
                name="proven fan does not alarm",
                inputs={"Enable": True, "FanStatus": True},
                repeat=4,
                expectations=[
                    OutputExpectation(target="FanCommand", value=True),
                    OutputExpectation(target="FanProofAlarm", value=False),
                ],
            ),
            AcceptanceCase(
                name="proof failure and recovery timeline",
                timeline=[
                    AcceptancePhase(
                        name="startup grace period",
                        inputs={"Enable": True, "FanStatus": False},
                        repeat=2,
                        expectations=[OutputExpectation(target="FanProofAlarm", value=False)],
                    ),
                    AcceptancePhase(
                        name="proof timeout",
                        repeat=1,
                        expectations=[OutputExpectation(target="FanProofAlarm", value=True)],
                    ),
                    AcceptancePhase(
                        name="proof arrives",
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
    )


def test_exhaust_fan_pack_builds_tests_and_compiles(tmp_path: Path) -> None:
    result = ProgrammingAgent(SequencePackPlanner()).run(_job())

    assert result.report.passed
    destination = NiagaraCompiler().compile(result.graph, tmp_path / "exhaust.bog")
    with zipfile.ZipFile(destination) as archive:
        xml = archive.read("file.xml")
    assert b"kitControl:BooleanDelay" in xml
    assert b'v="3000"' in xml
    timeline = next(
        scenario
        for scenario in result.report.scenarios
        if scenario.name == "proof failure and recovery timeline"
    )
    assert [sample["FanProofAlarm"] for sample in timeline.samples] == [
        False,
        False,
        True,
        False,
    ]
