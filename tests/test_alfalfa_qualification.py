from __future__ import annotations

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
)
from bactalk.repository import RunRepository
from bactalk.service import ApprovalRequiredError, ArtifactChangedError, WorkbenchService


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


def _qualify(service: WorkbenchService, run_id: str) -> object:
    return service.qualify_with_alfalfa(
        run_id,
        client=_FakeAlfalfa(),
        mapping=_mapping(),
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
    assert len(qualified.verification_artifact_paths) == 2
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

    model_path = next(
        Path(path)
        for path in qualified.verification_artifact_paths
        if path.endswith(".fmu")
    )
    with model_path.open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(ArtifactChangedError):
        service.export_path(candidate.id)


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
