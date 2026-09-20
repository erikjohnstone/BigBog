from __future__ import annotations

import zipfile
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
from bactalk.integrations.boptest_graph import (
    BoptestActuatorBinding,
    BoptestGraphMap,
    BoptestMeasurementBinding,
    BoptestTrajectoryOracle,
)
from bactalk.repository import RunRepository
from bactalk.service import ApprovalRequiredError, ArtifactChangedError, WorkbenchService


def _graph() -> ControlGraph:
    return ControlGraph(
        name="QualifiedFanController",
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
                config={"value": 1.0},
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
        name="Contractor fan qualification",
        site="BOPTEST lab",
        equipment_name="FCU_1",
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
                name="hot room starts fan",
                inputs={"room_temp": 293.15},
                expectations=[OutputExpectation(target="fan_command", value=1.0)],
            )
        ],
    )


def _mapping() -> BoptestGraphMap:
    return BoptestGraphMap(
        test_case="bestest_air",
        measurements=[
            BoptestMeasurementBinding(
                graph_input="room_temp",
                measurement="zon_reaTRooAir_y",
            )
        ],
        actuators=[
            BoptestActuatorBinding(
                graph_output="fan_command",
                actuator="fcu_oveFan_u",
                activation_actuator="fcu_oveFan_activate",
            )
        ],
    )


def _oracle(*, expected: float = 1.0) -> BoptestTrajectoryOracle:
    return BoptestTrajectoryOracle(
        id="fan-command",
        signal_kind="graph_output",
        signal="fan_command",
        reference_times=[300.0, 600.0],
        reference_values=[expected, expected],
    )


class _FakeBoptest:
    def __init__(self) -> None:
        self.time = 0.0
        self.step = 0.0
        self.stopped = False

    def version(self) -> dict[str, str]:
        return {"version": "qualification-test"}

    def select(self, test_case: str) -> str:
        assert test_case == "bestest_air"
        return "test-123"

    def initialize(self, test_id: str, *, start_time: float, warmup_period: float) -> dict:
        self.time = start_time
        return {"time": self.time, "zon_reaTRooAir_y": 293.15}

    def set_step(self, test_id: str, seconds: float) -> dict[str, float]:
        self.step = seconds
        return {"step": seconds}

    def measurements(self, test_id: str) -> dict[str, dict]:
        return {"zon_reaTRooAir_y": {"Unit": "K"}}

    def inputs(self, test_id: str) -> dict[str, dict]:
        return {
            "fcu_oveFan_u": {"Minimum": 0, "Maximum": 1},
            "fcu_oveFan_activate": {"Minimum": None, "Maximum": None},
        }

    def advance(self, test_id: str, overrides: dict[str, float | int]) -> dict:
        self.time += self.step
        return {"time": self.time, "zon_reaTRooAir_y": 292.5}

    def kpis(self, test_id: str) -> dict[str, float]:
        return {"ener_tot": 1.0}

    def stop(self, test_id: str) -> str:
        self.stopped = True
        return "OK"


def test_passing_boptest_qualification_is_signed_reviewable_and_tamper_evident(
    tmp_path: Path,
) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    candidate = service.create_run(_job())

    qualified = service.qualify_with_boptest(
        candidate.id,
        client=_FakeBoptest(),
        mapping=_mapping(),
        oracles=[_oracle()],
        steps=2,
        step_seconds=300.0,
    )

    assert qualified.status == RunStatus.READY_FOR_REVIEW
    assert qualified.artifact_sha256 != candidate.artifact_sha256
    assert qualified.boptest_verification_path is not None
    assert Path(qualified.boptest_verification_path).is_file()
    assert len(qualified.verification_artifact_paths) == 6
    service.verify_integrity(candidate.id)

    service.approve(candidate.id, "Alex Engineer")
    bundle = service.review_bundle_path(candidate.id)
    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()
        assert "boptest-verification/evidence.json" in names
        assert "boptest-verification/oracle-001-fan-command/errors.csv" in names

    errors = next(
        Path(path)
        for path in qualified.verification_artifact_paths
        if path.endswith("errors.csv")
    )
    with errors.open("a", encoding="utf-8") as stream:
        stream.write("tampered\n")
    with pytest.raises(ArtifactChangedError):
        service.export_path(candidate.id)


def test_failing_boptest_oracle_blocks_human_approval(tmp_path: Path) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    candidate = service.create_run(_job())

    qualified = service.qualify_with_boptest(
        candidate.id,
        client=_FakeBoptest(),
        mapping=_mapping(),
        oracles=[_oracle(expected=0.0)],
        steps=2,
        step_seconds=300.0,
    )

    assert qualified.status == RunStatus.FAILED
    assert qualified.boptest_verification_path is not None
    with pytest.raises(ApprovalRequiredError):
        service.approve(candidate.id, "Alex Engineer")
    with pytest.raises(ApprovalRequiredError):
        service.export_path(candidate.id)


def test_boptest_qualification_cannot_mutate_an_approved_run(tmp_path: Path) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    candidate = service.create_run(_job())
    service.approve(candidate.id, "Alex Engineer")

    with pytest.raises(ApprovalRequiredError, match="awaiting review"):
        service.qualify_with_boptest(
            candidate.id,
            client=_FakeBoptest(),
            mapping=_mapping(),
            oracles=[_oracle()],
            steps=2,
            step_seconds=300.0,
        )


def test_boptest_qualification_is_available_through_the_product_api(tmp_path: Path) -> None:
    app = create_app(
        tmp_path / "runs",
        boptest_client_factory=_FakeBoptest,
    )
    client = TestClient(app)
    created = client.post("/api/runs", json=_job().model_dump(mode="json"))
    assert created.status_code == 201
    run_id = created.json()["id"]

    response = client.post(
        f"/api/runs/{run_id}/verify/boptest",
        json={
            "mapping": _mapping().model_dump(mode="json"),
            "oracles": [_oracle().model_dump(mode="json")],
            "steps": 2,
            "step_seconds": 300.0,
        },
    )

    assert response.status_code == 200
    assert response.json()["run"]["status"] == "ready_for_review"
    assert response.json()["evidence"]["status"] == "pass"
    retained = client.get(f"/api/runs/{run_id}/verify/boptest")
    assert retained.status_code == 200
    assert retained.json()["runtime"]["test_case"] == "bestest_air"
