import zipfile
from pathlib import Path

from bactalk.agent import ProgrammingAgent, SequencePackPlanner
from bactalk.capabilities import CapabilityRegistry
from bactalk.compiler import NiagaraCompiler
from bactalk.domain import (
    AcceptanceCase,
    DataType,
    JobSpec,
    OutputExpectation,
    PointRole,
    PointSpec,
    SequenceSpec,
)


def _expectations(pump_1: bool, pump_2: bool, alarm: bool) -> list[OutputExpectation]:
    return [
        OutputExpectation(target="Pump1Command", value=pump_1),
        OutputExpectation(target="Pump2Command", value=pump_2),
        OutputExpectation(target="NoPumpAvailableAlarm", value=alarm),
    ]


def _job() -> JobSpec:
    inputs = (
        ("SystemEnable", "System enable", False),
        ("Pump1LeadSelect", "Pump 1 lead selection", True),
        ("Pump1Available", "Pump 1 available", True),
        ("Pump2Available", "Pump 2 available", True),
    )
    outputs = (
        ("Pump1Command", "Pump 1 command", PointRole.COMMAND),
        ("Pump2Command", "Pump 2 command", PointRole.COMMAND),
        ("NoPumpAvailableAlarm", "No pump available alarm", PointRole.ALARM),
    )
    return JobSpec(
        name="Heating-water duty standby pumps",
        site="Test Campus",
        equipment_name="HWP_PAIR_1",
        equipment_brick_class="brick:Pump",
        sequence=SequenceSpec(
            family="TWO_PUMP_AVAILABILITY_SELECTOR",
            version="BACTalk selector 0.1",
        ),
        points=[
            *[
                PointSpec(
                    name=name,
                    label=label,
                    data_type=DataType.BOOLEAN,
                    role=PointRole.STATUS,
                    default=default,
                )
                for name, label, default in inputs
            ],
            *[
                PointSpec(
                    name=name,
                    label=label,
                    data_type=DataType.BOOLEAN,
                    role=role,
                    default=False,
                )
                for name, label, role in outputs
            ],
        ],
        acceptance_tests=[
            AcceptanceCase(
                name="disabled",
                inputs={
                    "SystemEnable": False,
                    "Pump1LeadSelect": True,
                    "Pump1Available": True,
                    "Pump2Available": True,
                },
                expectations=_expectations(False, False, False),
            ),
            AcceptanceCase(
                name="selected lead runs",
                inputs={
                    "SystemEnable": True,
                    "Pump1LeadSelect": True,
                    "Pump1Available": True,
                    "Pump2Available": True,
                },
                expectations=_expectations(True, False, False),
            ),
            AcceptanceCase(
                name="lead unavailable fails over",
                inputs={
                    "SystemEnable": True,
                    "Pump1LeadSelect": True,
                    "Pump1Available": False,
                    "Pump2Available": True,
                },
                expectations=_expectations(False, True, False),
            ),
            AcceptanceCase(
                name="neither pump available fails closed",
                inputs={
                    "SystemEnable": True,
                    "Pump1LeadSelect": False,
                    "Pump1Available": False,
                    "Pump2Available": False,
                },
                expectations=_expectations(False, False, True),
            ),
        ],
    )


def test_two_pump_selector_is_fail_closed_and_compiles(tmp_path: Path) -> None:
    job = _job()
    result = ProgrammingAgent(SequencePackPlanner()).run(job)

    assert result.report.passed
    assert CapabilityRegistry().match_job(job).id == "two-pump-selector-v1"
    destination = NiagaraCompiler().compile(result.graph, tmp_path / "pump-selector.bog")
    with zipfile.ZipFile(destination) as archive:
        xml = archive.read("file.xml")
    assert b"kitControl:And" in xml
    assert b"kitControl:Or" in xml
    assert b"kitControl:Not" in xml
