from __future__ import annotations

import asyncio
import io
import json
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bactalk.api import create_app
from bactalk.domain import (
    AcceptanceCase,
    BacnetDeviceSpec,
    BacnetObjectSpec,
    BacnetScan,
    Block,
    BlockKind,
    ControlGraph,
    DataType,
    JobSpec,
    Link,
    OutputExpectation,
    PointRole,
    PointSpec,
    RunStatus,
    SequenceSpec,
)
from bactalk.integrations.alfalfa_graph import (
    AlfalfaGraphMap,
    AlfalfaInputBinding,
    AlfalfaOutputBinding,
    AlfalfaTrajectoryOracle,
)
from bactalk.qualification_jobs import (
    AlfalfaQualificationJobExecutor,
    AlfalfaQualificationPayload,
    QualificationJobIntegrityError,
    QualificationJobRecord,
    QualificationJobRepository,
    QualificationJobStatus,
)
from bactalk.repository import RunRepository
from bactalk.service import (
    ApprovalRequiredError,
    ArtifactChangedError,
    WorkbenchService,
    artifact_hash,
)


def _graph() -> ControlGraph:
    return ControlGraph(
        name="QualifiedAlfalfaFanController",
        blocks=[
            Block(
                id="room_temp",
                kind=BlockKind.NUMERIC_INPUT,
                label="Room temperature",
                config={"default": 293.15},
            ),
            Block(
                id="threshold",
                kind=BlockKind.NUMERIC_CONST,
                label="Cooling threshold",
                config={"value": 292.0},
            ),
            Block(id="is_hot", kind=BlockKind.GREATER_THAN, label="Cooling request"),
            Block(
                id="fan_on",
                kind=BlockKind.NUMERIC_CONST,
                label="Fan on",
                config={"value": 0.37},
            ),
            Block(
                id="fan_off",
                kind=BlockKind.NUMERIC_CONST,
                label="Fan off",
                config={"value": 0.0},
            ),
            Block(id="select_fan", kind=BlockKind.NUMERIC_SWITCH, label="Fan selector"),
            Block(id="fan_command", kind=BlockKind.NUMERIC_OUTPUT, label="Fan command"),
        ],
        links=[
            Link(source="room_temp", target="is_hot", target_slot="a"),
            Link(source="threshold", target="is_hot", target_slot="b"),
            Link(source="is_hot", target="select_fan", target_slot="selector"),
            Link(source="fan_on", target="select_fan", target_slot="when_true"),
            Link(source="fan_off", target="select_fan", target_slot="when_false"),
            Link(source="select_fan", target="fan_command", target_slot="in"),
        ],
    )


def _job() -> JobSpec:
    return JobSpec(
        name="Contractor Alfalfa qualification",
        site="Alfalfa lab",
        equipment_name="AHU_1",
        sequence=SequenceSpec(family="CUSTOM_FAN", version="Contractor authored v1"),
        points=[
            PointSpec(
                name="room_temp",
                label="Room temperature",
                data_type=DataType.NUMERIC,
                role=PointRole.SENSOR,
                units="K",
                default=293.15,
            ),
            PointSpec(
                name="fan_command",
                label="Fan command",
                data_type=DataType.NUMERIC,
                role=PointRole.COMMAND,
                units="%",
                default=0.0,
            ),
        ],
        control_graph=_graph(),
        acceptance_tests=[
            AcceptanceCase(
                name="hot room commands fan",
                inputs={"room_temp": 293.15},
                expectations=[OutputExpectation(target="fan_command", value=0.37)],
            )
        ],
    )


def _mapping() -> AlfalfaGraphMap:
    return AlfalfaGraphMap(
        outputs=[
            AlfalfaOutputBinding(
                graph_input="room_temp",
                output="hvac_reaZonCor_TZon_y",
            )
        ],
        inputs=[
            AlfalfaInputBinding(
                graph_output="fan_command",
                input="hvac_oveAhu_yFan_u",
                minimum=0.0,
                maximum=1.0,
            )
        ],
        observed_outputs=["hvac_oveAhu_yFan_y"],
        command_echoes={"hvac_oveAhu_yFan_u": "hvac_oveAhu_yFan_y"},
    )


def _oracle(*, expected: float = 0.37) -> AlfalfaTrajectoryOracle:
    return AlfalfaTrajectoryOracle(
        id="fan-command",
        signal_kind="graph_output",
        signal="fan_command",
        reference_times=[60.0, 120.0],
        reference_values=[expected, expected],
        absolute_value_tolerance=1e-6,
    )


def _bacnet_job() -> JobSpec:
    job = _job()
    points = [
        point.model_copy(
            update={
                "bacnet_device_instance": 120_001,
                "bacnet_object": (
                    "analog-input,1" if point.name == "room_temp" else "analog-output,1"
                ),
            }
        )
        for point in job.points
    ]
    return job.model_copy(
        update={
            "points": points,
            "bacnet_scan": BacnetScan(
                source="isolated Alfalfa BACnet qualification fixture",
                devices=[
                    BacnetDeviceSpec(
                        device_instance=120_001,
                        address="192.0.2.101/24:47808",
                        name="AHU-1 virtual controller",
                        vendor_id=999,
                        objects=[
                            BacnetObjectSpec(
                                object_id="analog-input,1",
                                name="Room Temperature",
                                data_type=DataType.NUMERIC,
                                units="K",
                                present_value=293.15,
                            ),
                            BacnetObjectSpec(
                                object_id="analog-output,1",
                                name="Fan Command",
                                data_type=DataType.NUMERIC,
                                writable=True,
                                units="percent",
                                present_value=0.0,
                            ),
                        ],
                    )
                ],
            ),
        }
    )


def _fmu_bytes() -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "modelDescription.xml",
            """<fmiModelDescription fmiVersion="2.0" modelName="TestBuilding" guid="test-guid">
  <CoSimulation modelIdentifier="test_building" />
  <ModelVariables>
    <ScalarVariable name="hvac_oveAhu_yFan_u" valueReference="1"
      causality="input" variability="continuous">
      <Real min="0" max="1" start="0" />
    </ScalarVariable>
    <ScalarVariable name="hvac_reaZonCor_TZon_y" valueReference="2"
      causality="output" variability="continuous">
      <Real unit="K" start="293.15" />
    </ScalarVariable>
    <ScalarVariable name="hvac_oveAhu_yFan_y" valueReference="3"
      causality="output" variability="continuous">
      <Real min="0" max="1" />
    </ScalarVariable>
  </ModelVariables>
</fmiModelDescription>""",
        )
    return stream.getvalue()


def _archive_bytes(entries: dict[str, str]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return stream.getvalue()


class _FakeAlfalfa:
    def __init__(self) -> None:
        self.time = datetime(2019, 1, 1)
        self.command = 0.0
        self.stopped = False

    def submit(self, model_path: str, wait_for_status: bool = True) -> str:
        assert zipfile.is_zipfile(model_path)
        return "alfalfa-run-123"

    def start(
        self,
        _run_id: str,
        start_datetime: datetime,
        end_datetime: datetime,
        timescale: int = 5,
        external_clock: bool = False,
        realtime: bool = False,
        wait_for_status: bool = True,
    ) -> None:
        assert external_clock is True
        assert end_datetime > start_datetime
        self.time = start_datetime

    def status(self, _run_id: str) -> str:
        return "COMPLETE" if self.stopped else "RUNNING"

    def get_inputs(self, _run_id: str) -> list[str]:
        return ["hvac_oveAhu_yFan_u"]

    def set_inputs(self, _run_id: str, inputs: dict[str, float]) -> None:
        self.command = inputs["hvac_oveAhu_yFan_u"]

    def get_outputs(self, _run_id: str) -> dict[str, float]:
        return {
            "hvac_reaZonCor_TZon_y": 293.15,
            "hvac_oveAhu_yFan_y": self.command,
        }

    def get_sim_time(self, _run_id: str) -> datetime:
        return self.time

    def advance(self, _run_id: str) -> None:
        self.time += timedelta(seconds=60)

    def stop(self, _run_id: str, wait_for_status: bool = True) -> None:
        self.stopped = True


class _CapturingQualificationDispatcher:
    def __init__(self) -> None:
        self.enqueued: list[str] = []
        self.canceled: list[str] = []

    def enqueue(self, record: QualificationJobRecord) -> None:
        self.enqueued.append(record.id)

    def cancel(self, record: QualificationJobRecord) -> None:
        self.canceled.append(record.id)


class _FakeBooleanAlfalfa(_FakeAlfalfa):
    def get_inputs(self, _run_id: str) -> list[str]:
        return ["run_u"]

    def set_inputs(self, _run_id: str, inputs: dict[str, float]) -> None:
        self.command = inputs["run_u"]

    def get_outputs(self, _run_id: str) -> dict[str, float | bool]:
        return {"enable_status": True, "run_y": self.command}


class _FakeModeAlfalfa(_FakeAlfalfa):
    def get_inputs(self, _run_id: str) -> list[str]:
        return ["mode_u"]

    def set_inputs(self, _run_id: str, inputs: dict[str, float]) -> None:
        self.command = inputs["mode_u"]

    def get_outputs(self, _run_id: str) -> dict[str, float]:
        return {"mode_status": 2.0, "mode_y": self.command}


def _boolean_job() -> JobSpec:
    graph = ControlGraph(
        name="BooleanBacnetController",
        blocks=[
            Block(
                id="enable_status",
                kind=BlockKind.BOOLEAN_INPUT,
                label="Enable status",
                config={"default": True},
            ),
            Block(
                id="run_command",
                kind=BlockKind.BOOLEAN_OUTPUT,
                label="Run command",
            ),
        ],
        links=[Link(source="enable_status", target="run_command", target_slot="in")],
    )
    return JobSpec(
        name="Boolean BACnet Alfalfa qualification",
        site="Alfalfa lab",
        equipment_name="EF_1",
        sequence=SequenceSpec(family="CUSTOM_BOOLEAN", version="1"),
        points=[
            PointSpec(
                name="enable_status",
                label="Enable status",
                data_type=DataType.BOOLEAN,
                role=PointRole.STATUS,
                default=True,
                bacnet_device_instance=120_002,
                bacnet_object="binary-input,1",
            ),
            PointSpec(
                name="run_command",
                label="Run command",
                data_type=DataType.BOOLEAN,
                role=PointRole.COMMAND,
                default=False,
                bacnet_device_instance=120_002,
                bacnet_object="binary-output,1",
            ),
        ],
        control_graph=graph,
        acceptance_tests=[
            AcceptanceCase(
                name="enable drives run command",
                inputs={"enable_status": True},
                expectations=[OutputExpectation(target="run_command", value=True)],
            )
        ],
        bacnet_scan=BacnetScan(
            source="isolated Boolean qualification fixture",
            devices=[
                BacnetDeviceSpec(
                    device_instance=120_002,
                    address="192.0.2.102/24:47808",
                    name="EF-1 virtual controller",
                    objects=[
                        BacnetObjectSpec(
                            object_id="binary-input,1",
                            name="Enable Status",
                            data_type=DataType.BOOLEAN,
                            present_value=True,
                        ),
                        BacnetObjectSpec(
                            object_id="binary-output,1",
                            name="Run Command",
                            data_type=DataType.BOOLEAN,
                            writable=True,
                            present_value=False,
                        ),
                    ],
                )
            ],
        ),
    )


def _boolean_mapping() -> AlfalfaGraphMap:
    return AlfalfaGraphMap(
        outputs=[
            AlfalfaOutputBinding(
                graph_input="enable_status",
                output="enable_status",
            )
        ],
        inputs=[
            AlfalfaInputBinding(
                graph_output="run_command",
                input="run_u",
                minimum=0.0,
                maximum=1.0,
            )
        ],
        observed_outputs=["run_y"],
        command_echoes={"run_u": "run_y"},
    )


def _mode_job() -> JobSpec:
    graph = ControlGraph(
        name="MultiStateBacnetController",
        blocks=[
            Block(
                id="mode_status",
                kind=BlockKind.NUMERIC_INPUT,
                label="Operating mode status",
                config={"default": 2.0},
            ),
            Block(
                id="mode_command",
                kind=BlockKind.NUMERIC_OUTPUT,
                label="Operating mode command",
            ),
        ],
        links=[Link(source="mode_status", target="mode_command", target_slot="in")],
    )
    return JobSpec(
        name="Multi-state BACnet Alfalfa qualification",
        site="Alfalfa lab",
        equipment_name="AHU_MODE_1",
        sequence=SequenceSpec(family="CUSTOM_MODE", version="1"),
        points=[
            PointSpec(
                name="mode_status",
                label="Operating mode status",
                data_type=DataType.NUMERIC,
                role=PointRole.STATUS,
                default=2.0,
                bacnet_device_instance=120_003,
                bacnet_object="multi-state-input,1",
            ),
            PointSpec(
                name="mode_command",
                label="Operating mode command",
                data_type=DataType.NUMERIC,
                role=PointRole.COMMAND,
                default=1.0,
                bacnet_device_instance=120_003,
                bacnet_object="multi-state-output,1",
            ),
        ],
        control_graph=graph,
        acceptance_tests=[
            AcceptanceCase(
                name="mode passes through",
                inputs={"mode_status": 2.0},
                expectations=[OutputExpectation(target="mode_command", value=2.0)],
            )
        ],
        bacnet_scan=BacnetScan(
            source="isolated multi-state qualification fixture",
            devices=[
                BacnetDeviceSpec(
                    device_instance=120_003,
                    address="192.0.2.103/24:47808",
                    name="AHU mode virtual controller",
                    objects=[
                        BacnetObjectSpec(
                            object_id="multi-state-input,1",
                            name="Mode Status",
                            data_type=DataType.NUMERIC,
                            present_value=2.0,
                        ),
                        BacnetObjectSpec(
                            object_id="multi-state-output,1",
                            name="Mode Command",
                            data_type=DataType.NUMERIC,
                            writable=True,
                            present_value=1.0,
                        ),
                    ],
                )
            ],
        ),
    )


def _mode_mapping() -> AlfalfaGraphMap:
    return AlfalfaGraphMap(
        outputs=[
            AlfalfaOutputBinding(
                graph_input="mode_status",
                output="mode_status",
            )
        ],
        inputs=[
            AlfalfaInputBinding(
                graph_output="mode_command",
                input="mode_u",
                minimum=1.0,
                maximum=16.0,
            )
        ],
        observed_outputs=["mode_y"],
        command_echoes={"mode_u": "mode_y"},
    )


def _qualify(service: WorkbenchService, run_id: str) -> object:
    return service.qualify_with_alfalfa(
        run_id,
        client=_FakeAlfalfa(),
        mapping=_mapping(),
        oracles=[_oracle()],
        model_bytes=_fmu_bytes(),
        model_filename="contractor-building.fmu",
        steps=2,
        step_seconds=60.0,
        start=datetime(2019, 1, 1),
        server_version={"version": "test"},
        client_version="1.0.0",
    )


def test_alfalfa_qualification_is_signed_reviewable_and_tamper_evident(
    tmp_path: Path,
) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    candidate = service.create_run(_job())

    qualified = _qualify(service, candidate.id)

    assert qualified.status == RunStatus.READY_FOR_REVIEW
    assert qualified.artifact_sha256 != candidate.artifact_sha256
    assert qualified.alfalfa_verification_path is not None
    assert len(qualified.verification_artifact_paths) >= 7
    evidence = json.loads(Path(qualified.alfalfa_verification_path).read_text())
    assert evidence["schema"] == "bactalk.alfalfa-graph-run/v1"
    assert evidence["approval_allowed"] is True
    service.verify_integrity(candidate.id)

    service.approve(candidate.id, "Alex Engineer")
    bundle = service.review_bundle_path(candidate.id)
    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()
        assert "alfalfa-verification/evidence.json" in names
        assert "alfalfa-verification/contractor-building.fmu" in names
        assert "alfalfa-verification/oracle-001-fan-command/errors.csv" in names

    model_path = next(
        Path(path)
        for path in qualified.verification_artifact_paths
        if path.endswith(".fmu")
    )
    with model_path.open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(ArtifactChangedError):
        service.export_path(candidate.id)


def test_alfalfa_accumulates_with_existing_boptest_tier_under_one_digest(
    tmp_path: Path,
) -> None:
    runs = RunRepository(tmp_path / "runs")
    service = WorkbenchService(runs)
    candidate = service.create_run(_job())
    prior = runs.run_directory(candidate.id) / "boptest-verification/evidence.json"
    prior.parent.mkdir()
    prior.write_text('{"schema":"test-prior-boptest","status":"pass"}', encoding="utf-8")
    with_prior = candidate.model_copy(
        update={
            "boptest_verification_path": str(prior),
            "verification_artifact_paths": [str(prior)],
        }
    )
    with_prior = with_prior.model_copy(
        update={
            "artifact_sha256": artifact_hash(*service._record_artifact_paths(with_prior))
        }
    )
    runs.save(with_prior)

    qualified = _qualify(service, candidate.id)

    assert qualified.status == RunStatus.READY_FOR_REVIEW
    assert qualified.boptest_verification_path == str(prior)
    assert qualified.alfalfa_verification_path is not None
    assert str(prior) in qualified.verification_artifact_paths
    assert len(qualified.verification_artifact_paths) >= 8
    service.verify_integrity(candidate.id)


def test_alfalfa_qualification_rejects_invalid_fmu_without_mutating_run(
    tmp_path: Path,
) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    candidate = service.create_run(_job())

    with pytest.raises(ValueError, match="not a valid FMU"):
        service.qualify_with_alfalfa(
            candidate.id,
            client=_FakeAlfalfa(),
            mapping=_mapping(),
            oracles=[_oracle()],
            model_bytes=b"not-a-zip",
            model_filename="building.fmu",
            steps=1,
            step_seconds=60.0,
            start=datetime(2019, 1, 1),
        )

    retained = service.verify_integrity(candidate.id)
    assert retained.alfalfa_verification_path is None
    assert not (tmp_path / "runs" / candidate.id / "alfalfa-verification").exists()


@pytest.mark.parametrize(
    ("model_bytes", "message"),
    [
        (_archive_bytes({"resources/data.txt": "not an FMU"}), "modelDescription.xml"),
        (
            _archive_bytes(
                {
                    "modelDescription.xml": "<fmiModelDescription/>",
                    "../escape.txt": "nope",
                }
            ),
            "unsafe archive path",
        ),
        (
            _archive_bytes(
                {
                    "modelDescription.xml": (
                        '<!DOCTYPE fmiModelDescription [<!ENTITY xxe "bad">]>'
                        "<fmiModelDescription/>"
                    )
                }
            ),
            "forbidden declarations",
        ),
    ],
)
def test_alfalfa_qualification_rejects_unsafe_fmu_archives(
    tmp_path: Path,
    model_bytes: bytes,
    message: str,
) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    candidate = service.create_run(_job())

    with pytest.raises(ValueError, match=message):
        service.qualify_with_alfalfa(
            candidate.id,
            client=_FakeAlfalfa(),
            mapping=_mapping(),
            oracles=[_oracle()],
            model_bytes=model_bytes,
            model_filename="building.fmu",
            steps=1,
            step_seconds=60.0,
            start=datetime(2019, 1, 1),
        )

    retained = service.verify_integrity(candidate.id)
    assert retained.alfalfa_verification_path is None


def test_alfalfa_qualification_cannot_mutate_an_approved_run(tmp_path: Path) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    candidate = service.create_run(_job())
    service.approve(candidate.id, "Alex Engineer")

    with pytest.raises(ApprovalRequiredError, match="awaiting review"):
        _qualify(service, candidate.id)


def test_alfalfa_qualification_is_available_through_product_api(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            tmp_path / "runs",
            alfalfa_client_factory=_FakeAlfalfa,
        )
    )
    created = client.post("/api/runs", json=_job().model_dump(mode="json"))
    assert created.status_code == 201
    run_id = created.json()["id"]
    qualification = {
        "mapping": _mapping().model_dump(mode="json"),
        "oracles": [_oracle().model_dump(mode="json")],
        "steps": 2,
        "step_seconds": 60.0,
        "start": "2019-01-01T00:00:00",
    }

    response = client.post(
        f"/api/runs/{run_id}/verify/alfalfa",
        data={"qualification": json.dumps(qualification)},
        files={
            "model_file": (
                "contractor-building.fmu",
                _fmu_bytes(),
                "application/zip",
            )
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["run"]["status"] == "ready_for_review"
    assert response.json()["evidence"]["status"] == "pass"
    retained = client.get(f"/api/runs/{run_id}/verify/alfalfa")
    assert retained.status_code == 200
    assert retained.json()["steps"] == 2


def test_alfalfa_qualification_closes_loop_through_real_bacnet_udp(
    tmp_path: Path,
) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    candidate = service.create_run(_bacnet_job())

    qualified = asyncio.run(
        service.qualify_with_alfalfa_bacnet(
            candidate.id,
            client=_FakeAlfalfa(),
            mapping=_mapping(),
            oracles=[_oracle()],
            model_bytes=_fmu_bytes(),
            model_filename="contractor-building.fmu",
            steps=2,
            step_seconds=60.0,
            start=datetime(2019, 1, 1),
            server_version={"version": "test"},
            client_version="1.0.0",
        )
    )

    evidence = json.loads(Path(qualified.alfalfa_verification_path or "").read_text())
    transport = evidence["control_transport"]
    assert transport["kind"] == "bacnet_ip_loopback"
    assert transport["read_transaction_count"] == 2
    assert transport["write_transaction_count"] == 2
    assert transport["readbacks_matched"] is True
    assert transport["live_network_routes_allowed"] is False
    assert transport["licensed_niagara_runtime"] is False
    assert evidence["trajectory"][0]["bacnet_reads"]["room_temp"]["matched"] is True
    write = evidence["trajectory"][0]["bacnet_writes"]["fan_command"]
    assert write["priority"] == 8
    assert write["command"] == pytest.approx(0.37)
    assert write["readback"] == pytest.approx(0.37)
    assert write["matched"] is True
    service.verify_integrity(candidate.id)


def test_failing_alfalfa_oracle_blocks_human_approval(tmp_path: Path) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    candidate = service.create_run(_job())

    qualified = service.qualify_with_alfalfa(
        candidate.id,
        client=_FakeAlfalfa(),
        mapping=_mapping(),
        oracles=[_oracle(expected=0.0)],
        model_bytes=_fmu_bytes(),
        model_filename="contractor-building.fmu",
        steps=2,
        step_seconds=60.0,
        start=datetime(2019, 1, 1),
    )

    assert qualified.status == RunStatus.FAILED
    evidence = json.loads(Path(qualified.alfalfa_verification_path or "").read_text())
    assert evidence["status"] == "fail"
    assert evidence["approval_allowed"] is False
    assert evidence["oracles"][0]["passed"] is False
    counterexample = evidence["oracles"][0]["counterexample"]
    assert counterexample["schema"] == "bactalk.trajectory-counterexample/v1"
    assert counterexample["violation_count"] == 2
    assert counterexample["window"]["test_values"] == [0.37, 0.37]
    assert any(
        path.endswith("counterexample.json")
        for path in qualified.verification_artifact_paths
    )
    with pytest.raises(ApprovalRequiredError):
        service.approve(candidate.id, "Alex Engineer")
    with pytest.raises(ApprovalRequiredError):
        service.export_path(candidate.id)


def test_bacnet_coupled_alfalfa_qualification_is_available_through_product_api(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(
            tmp_path / "runs",
            alfalfa_client_factory=_FakeAlfalfa,
        )
    )
    created = client.post("/api/runs", json=_bacnet_job().model_dump(mode="json"))
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    qualification = {
        "mapping": _mapping().model_dump(mode="json"),
        "oracles": [_oracle().model_dump(mode="json")],
        "steps": 2,
        "step_seconds": 60.0,
        "start": "2019-01-01T00:00:00",
        "transport": "bacnet_ip_loopback",
    }

    response = client.post(
        f"/api/runs/{run_id}/verify/alfalfa",
        data={"qualification": json.dumps(qualification)},
        files={
            "model_file": (
                "contractor-building.fmu",
                _fmu_bytes(),
                "application/zip",
            )
        },
    )

    assert response.status_code == 200, response.text
    evidence = response.json()["evidence"]
    assert evidence["status"] == "pass"
    assert evidence["control_transport"]["kind"] == "bacnet_ip_loopback"
    assert evidence["control_transport"]["read_transaction_count"] == 2
    assert evidence["control_transport"]["write_transaction_count"] == 2


def test_bacnet_coupled_alfalfa_supports_boolean_input_and_command_objects(
    tmp_path: Path,
) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    candidate = service.create_run(_boolean_job())

    qualified = asyncio.run(
        service.qualify_with_alfalfa_bacnet(
            candidate.id,
            client=_FakeBooleanAlfalfa(),
            mapping=_boolean_mapping(),
            oracles=[
                AlfalfaTrajectoryOracle(
                    id="run-command",
                    signal_kind="graph_output",
                    signal="run_command",
                    reference_times=[60.0],
                    reference_values=[1.0],
                )
            ],
            model_bytes=_fmu_bytes(),
            model_filename="boolean-building.fmu",
            steps=1,
            step_seconds=60.0,
            start=datetime(2019, 1, 1),
        )
    )

    evidence = json.loads(Path(qualified.alfalfa_verification_path or "").read_text())
    sample = evidence["trajectory"][0]
    assert sample["graph_inputs"] == {"enable_status": True}
    assert sample["controller_outputs"] == {"run_command": True}
    assert sample["fmu_inputs"] == {"run_u": 1.0}
    assert sample["bacnet_reads"]["enable_status"]["matched"] is True
    write = sample["bacnet_writes"]["run_command"]
    assert write["command"] is True
    assert write["readback"] is True
    assert write["priority"] == 8
    assert write["matched"] is True


def test_bacnet_coupled_alfalfa_supports_multistate_modes(tmp_path: Path) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    candidate = service.create_run(_mode_job())

    qualified = asyncio.run(
        service.qualify_with_alfalfa_bacnet(
            candidate.id,
            client=_FakeModeAlfalfa(),
            mapping=_mode_mapping(),
            oracles=[
                AlfalfaTrajectoryOracle(
                    id="mode-command",
                    signal_kind="graph_output",
                    signal="mode_command",
                    reference_times=[60.0],
                    reference_values=[2.0],
                )
            ],
            model_bytes=_fmu_bytes(),
            model_filename="mode-building.fmu",
            steps=1,
            step_seconds=60.0,
            start=datetime(2019, 1, 1),
        )
    )

    evidence = json.loads(Path(qualified.alfalfa_verification_path or "").read_text())
    sample = evidence["trajectory"][0]
    assert sample["graph_inputs"] == {"mode_status": 2.0}
    assert sample["controller_outputs"] == {"mode_command": 2.0}
    assert sample["fmu_inputs"] == {"mode_u": 2.0}
    write = sample["bacnet_writes"]["mode_command"]
    assert write["command"] == 2.0
    assert write["readback"] == 2.0
    assert write["priority"] == 8
    assert write["matched"] is True


def test_bacnet_coupled_alfalfa_requires_a_complete_exact_protocol_boundary(
    tmp_path: Path,
) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    job = _bacnet_job()
    job = job.model_copy(
        update={
            "points": [
                point.model_copy(
                    update={"bacnet_device_instance": None, "bacnet_object": None}
                )
                if point.name == "fan_command"
                else point
                for point in job.points
            ]
        }
    )
    candidate = service.create_run(job)

    with pytest.raises(ValueError, match="graph output 'fan_command' has no BACnet object"):
        asyncio.run(
            service.qualify_with_alfalfa_bacnet(
                candidate.id,
                client=_FakeAlfalfa(),
                mapping=_mapping(),
                oracles=[_oracle()],
                model_bytes=_fmu_bytes(),
                model_filename="contractor-building.fmu",
                steps=1,
                step_seconds=60.0,
                start=datetime(2019, 1, 1),
            )
        )

    retained = service.verify_integrity(candidate.id)
    assert retained.alfalfa_verification_path is None
    assert not (tmp_path / "runs" / candidate.id / "alfalfa-verification").exists()


def test_bacnet_coupled_alfalfa_rejects_a_job_without_a_bacnet_scan(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(
            tmp_path / "runs",
            alfalfa_client_factory=_FakeAlfalfa,
        )
    )
    created = client.post("/api/runs", json=_job().model_dump(mode="json"))
    run_id = created.json()["id"]
    response = client.post(
        f"/api/runs/{run_id}/verify/alfalfa",
        data={
            "qualification": json.dumps(
                {
                    "mapping": _mapping().model_dump(mode="json"),
                    "oracles": [_oracle().model_dump(mode="json")],
                    "steps": 1,
                    "step_seconds": 60.0,
                    "start": "2019-01-01T00:00:00",
                    "transport": "bacnet_ip_loopback",
                }
            )
        },
        files={"model_file": ("building.fmu", _fmu_bytes(), "application/zip")},
    )

    assert response.status_code == 422
    assert "requires a mapped BACnet scan" in response.json()["detail"]


def test_fmu_inspection_is_available_through_product_api(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))

    response = client.post(
        "/api/integrations/alfalfa/inspect-fmu",
        files={"model_file": ("building.fmu", _fmu_bytes(), "application/zip")},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema"] == "bactalk.fmi-model-description/v1"
    assert payload["filename"] == "building.fmu"
    assert payload["fmi_version"] == "2.0"
    assert payload["model_name"] == "TestBuilding"
    assert payload["model_identifiers"] == ["test_building"]
    assert payload["variable_count"] == 3
    assert [item["name"] for item in payload["inputs"]] == [
        "hvac_oveAhu_yFan_u"
    ]
    assert [item["name"] for item in payload["outputs"]] == [
        "hvac_reaZonCor_TZon_y",
        "hvac_oveAhu_yFan_y",
    ]
    assert payload["live_building_writes"] is False


def _qualification_payload() -> AlfalfaQualificationPayload:
    return AlfalfaQualificationPayload(
        mapping=_mapping(),
        oracles=[_oracle()],
        steps=2,
        step_seconds=60.0,
        start=datetime(2019, 1, 1),
    )


def test_durable_qualification_job_inputs_are_unique_and_tamper_evident(
    tmp_path: Path,
) -> None:
    jobs = QualificationJobRepository(tmp_path / "qualification-jobs")
    record = jobs.create(
        run_id="abc123",
        candidate_artifact_sha256="0" * 64,
        payload=_qualification_payload(),
        model_bytes=_fmu_bytes(),
        model_filename="building.fmu",
    )

    assert jobs.get(record.id).status == QualificationJobStatus.QUEUED
    with pytest.raises(ValueError, match="already has active qualification job"):
        jobs.create(
            run_id="abc123",
            candidate_artifact_sha256="0" * 64,
            payload=_qualification_payload(),
            model_bytes=_fmu_bytes(),
            model_filename="building.fmu",
        )

    jobs.request_cancel(record.id)
    jobs.request_path(record.id).write_text("{}", encoding="utf-8")
    with pytest.raises(QualificationJobIntegrityError, match="request digest changed"):
        jobs.get(record.id)


def test_durable_qualification_executor_retains_progress_and_result(tmp_path: Path) -> None:
    runs = RunRepository(tmp_path / "runs")
    service = WorkbenchService(runs)
    candidate = service.create_run(_job())
    jobs = QualificationJobRepository(tmp_path / "qualification-jobs")
    job = jobs.create(
        run_id=candidate.id,
        candidate_artifact_sha256=candidate.artifact_sha256,
        payload=_qualification_payload(),
        model_bytes=_fmu_bytes(),
        model_filename="contractor-building.fmu",
    )

    completed = AlfalfaQualificationJobExecutor(
        jobs,
        service,
        client_factory=_FakeAlfalfa,
        client_version="test-client",
        worker_id="test-worker",
    ).execute(job.id)

    assert completed.status == QualificationJobStatus.SUCCEEDED
    assert completed.worker_id == "test-worker"
    assert completed.progress.phase == "completed"
    assert completed.progress.percent == 100
    assert completed.qualification_passed is True
    assert completed.result_artifact_sha256 == runs.get(candidate.id).artifact_sha256


def test_running_qualification_job_renews_and_expires_its_worker_lease(
    tmp_path: Path,
) -> None:
    jobs = QualificationJobRepository(tmp_path / "qualification-jobs")
    job = jobs.create(
        run_id="abc123",
        candidate_artifact_sha256="0" * 64,
        payload=_qualification_payload(),
        model_bytes=_fmu_bytes(),
        model_filename="building.fmu",
    )
    running = jobs.mark_running(job.id, "lease-test-worker")

    assert running.heartbeat_at is not None
    assert running.lease_expires_at is not None
    renewed = jobs.heartbeat(job.id)
    assert renewed.lease_expires_at is not None
    assert renewed.lease_expires_at >= running.lease_expires_at
    assert jobs.expire_stale(job.id, now=renewed.lease_expires_at).status == "running"

    expired = jobs.expire_stale(
        job.id,
        now=renewed.lease_expires_at + timedelta(microseconds=1),
    )

    assert expired.status == QualificationJobStatus.FAILED
    assert expired.progress.phase == "worker_lost"
    assert expired.lease_expires_at is None
    assert "lease expired" in (expired.error or "")


def test_running_qualification_job_cancels_cooperatively_and_stops_fmu(
    tmp_path: Path,
) -> None:
    runs = RunRepository(tmp_path / "runs")
    service = WorkbenchService(runs)
    candidate = service.create_run(_job())
    jobs = QualificationJobRepository(tmp_path / "qualification-jobs")
    job = jobs.create(
        run_id=candidate.id,
        candidate_artifact_sha256=candidate.artifact_sha256,
        payload=_qualification_payload(),
        model_bytes=_fmu_bytes(),
        model_filename="contractor-building.fmu",
    )
    fake = _FakeAlfalfa()
    original_advance = fake.advance

    def advance_and_cancel(run_id: str) -> None:
        original_advance(run_id)
        jobs.request_cancel(job.id)

    fake.advance = advance_and_cancel  # type: ignore[method-assign]
    canceled = AlfalfaQualificationJobExecutor(
        jobs,
        service,
        client_factory=lambda: fake,
        worker_id="cancel-test-worker",
    ).execute(job.id)

    assert canceled.status == QualificationJobStatus.CANCELED
    assert canceled.cancellation_requested is True
    assert fake.stopped is True
    assert runs.get(candidate.id).alfalfa_verification_path is None


def test_qualification_queue_api_persists_polls_and_cancels_jobs(tmp_path: Path) -> None:
    dispatcher = _CapturingQualificationDispatcher()
    client = TestClient(
        create_app(
            tmp_path / "runs",
            qualification_dispatcher=dispatcher,
        )
    )
    created = client.post("/api/runs", json=_job().model_dump(mode="json"))
    run_id = created.json()["id"]
    response = client.post(
        f"/api/runs/{run_id}/qualification-jobs/alfalfa",
        data={"qualification": _qualification_payload().model_dump_json()},
        files={"model_file": ("building.fmu", _fmu_bytes(), "application/zip")},
    )

    assert response.status_code == 202, response.text
    queued = response.json()
    assert queued["status"] == "queued"
    assert dispatcher.enqueued == [queued["id"]]
    latest = client.get(f"/api/runs/{run_id}/qualification-jobs/latest")
    assert latest.status_code == 200
    assert latest.json()["input_sha256"] == queued["input_sha256"]

    canceled = client.post(f"/api/qualification-jobs/{queued['id']}/cancel")
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "canceled"
    assert dispatcher.canceled == [queued["id"]]


def test_latest_qualification_job_exposes_changed_input_as_precondition_failure(
    tmp_path: Path,
) -> None:
    dispatcher = _CapturingQualificationDispatcher()
    client = TestClient(
        create_app(
            tmp_path / "runs",
            qualification_dispatcher=dispatcher,
        )
    )
    run_id = client.post("/api/runs", json=_job().model_dump(mode="json")).json()["id"]
    queued = client.post(
        f"/api/runs/{run_id}/qualification-jobs/alfalfa",
        data={"qualification": _qualification_payload().model_dump_json()},
        files={"model_file": ("building.fmu", _fmu_bytes(), "application/zip")},
    ).json()

    request_path = tmp_path / "qualification-jobs" / queued["id"] / "request.json"
    request_path.write_text("{}", encoding="utf-8")

    response = client.get(f"/api/runs/{run_id}/qualification-jobs/latest")

    assert response.status_code == 412
    assert "request digest changed" in response.json()["detail"]


def test_qualification_job_events_stream_reports_progress_until_terminal(
    tmp_path: Path,
) -> None:
    dispatcher = _CapturingQualificationDispatcher()
    client = TestClient(
        create_app(
            tmp_path / "runs",
            qualification_dispatcher=dispatcher,
        )
    )
    created = client.post("/api/runs", json=_job().model_dump(mode="json"))
    run_id = created.json()["id"]
    queued = client.post(
        f"/api/runs/{run_id}/qualification-jobs/alfalfa",
        data={"qualification": _qualification_payload().model_dump_json()},
        files={"model_file": ("building.fmu", _fmu_bytes(), "application/zip")},
    ).json()

    first = client.get(f"/api/qualification-jobs/{queued['id']}/events?limit=1")
    assert first.status_code == 200
    assert first.headers["content-type"].startswith("text/event-stream")
    events = [chunk for chunk in first.text.split("\n\n") if chunk]
    assert len(events) == 1
    kind, _, data = events[0].partition("\ndata: ")
    assert kind == "event: progress"
    payload = json.loads(data)
    assert payload["id"] == queued["id"]
    assert payload["status"] == "queued"
    assert payload["progress"]["phase"] == queued["progress"]["phase"]

    client.post(f"/api/qualification-jobs/{queued['id']}/cancel")
    # A terminal record ends the stream on its own, without a limit.
    ended = client.get(f"/api/qualification-jobs/{queued['id']}/events")
    events = [chunk for chunk in ended.text.split("\n\n") if chunk]
    assert len(events) == 1
    assert json.loads(events[0].partition("\ndata: ")[2])["status"] == "canceled"

    missing = client.get("/api/qualification-jobs/nope/events")
    assert missing.status_code == 200
    assert missing.text.startswith("event: gone\n")
