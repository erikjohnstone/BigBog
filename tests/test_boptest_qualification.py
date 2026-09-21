from __future__ import annotations

import json
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
    BoptestQualificationCase,
    BoptestTrajectoryOracle,
)
from bactalk.qualification_jobs import (
    BoptestQualificationJobExecutor,
    BoptestQualificationPayload,
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
        self.scenario_state: dict[str, object] = {}
        self.scenario_history: list[dict[str, object]] = []

    def version(self) -> dict[str, str]:
        return {"version": "qualification-test"}

    def test_cases(self) -> list[dict[str, str]]:
        return [{"testcaseid": "bestest_air"}]

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

    def set_scenario(self, test_id: str, scenario: dict[str, object]) -> dict[str, object]:
        self.scenario_state = dict(scenario)
        self.scenario_history.append(dict(scenario))
        if "time_period" in scenario:
            self.time = float(len(self.scenario_history) * 1_000_000)
            return {
                "time_period": {
                    "time": self.time,
                    "zon_reaTRooAir_y": 293.15,
                }
            }
        return dict(scenario)

    def get_scenario(self, test_id: str) -> dict[str, object]:
        return self.scenario_state

    def advance(self, test_id: str, overrides: dict[str, float | int]) -> dict:
        self.time += self.step
        return {"time": self.time, "zon_reaTRooAir_y": 292.5}

    def kpis(self, test_id: str) -> dict[str, float]:
        return {"ener_tot": 1.0}

    def stop(self, test_id: str) -> str:
        self.stopped = True
        return "OK"


class _CapturingQualificationDispatcher:
    def __init__(self) -> None:
        self.enqueued: list[str] = []
        self.canceled: list[str] = []

    def enqueue(self, record: QualificationJobRecord) -> None:
        self.enqueued.append(record.id)

    def cancel(self, record: QualificationJobRecord) -> None:
        self.canceled.append(record.id)


def _qualification_payload() -> BoptestQualificationPayload:
    return BoptestQualificationPayload(
        mapping=_mapping(),
        oracles=[_oracle()],
        steps=2,
        step_seconds=300.0,
    )


def _suite_cases(*, second_expected: float = 1.0) -> list[BoptestQualificationCase]:
    return [
        BoptestQualificationCase(
            id="peak-cooling",
            oracles=[_oracle()],
            steps=2,
            step_seconds=300.0,
            scenario={
                "time_period": "peak_cool_day",
                "electricity_price": "dynamic",
                "temperature_uncertainty": "medium",
                "seed": 42,
            },
        ),
        BoptestQualificationCase(
            id="peak-heating",
            oracles=[_oracle(expected=second_expected)],
            steps=2,
            step_seconds=300.0,
            scenario={
                "time_period": "peak_heat_day",
                "electricity_price": "constant",
            },
        ),
    ]


def test_boptest_payload_requires_one_unambiguous_qualification_mode() -> None:
    with pytest.raises(ValueError, match="requires either cases or single-run"):
        BoptestQualificationPayload(mapping=_mapping())
    with pytest.raises(ValueError, match="cannot be combined"):
        BoptestQualificationPayload(
            mapping=_mapping(),
            cases=_suite_cases(),
            oracles=[_oracle()],
            steps=2,
            step_seconds=300.0,
        )
    with pytest.raises(ValueError, match="case ids must be unique"):
        BoptestQualificationPayload(
            mapping=_mapping(),
            cases=[_suite_cases()[0], _suite_cases()[0]],
        )


def test_multi_scenario_boptest_suite_is_one_signed_approval_boundary(
    tmp_path: Path,
) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    candidate = service.create_run(_job())
    fake = _FakeBoptest()
    progress: list[tuple[str, int, int]] = []

    qualified = service.qualify_with_boptest(
        candidate.id,
        client=fake,
        mapping=_mapping(),
        cases=_suite_cases(),
        progress_callback=lambda phase, completed, total: progress.append(
            (phase, completed, total)
        ),
    )

    assert qualified.status == RunStatus.READY_FOR_REVIEW
    evidence = json.loads(Path(qualified.boptest_verification_path or "").read_text())
    assert evidence["schema"] == "bactalk.boptest-qualification-suite/v1"
    assert evidence["status"] == "pass"
    assert evidence["approval_allowed"] is True
    assert evidence["case_count"] == 2
    assert evidence["total_steps"] == 4
    assert [case["id"] for case in evidence["cases"]] == [
        "peak-cooling",
        "peak-heating",
    ]
    assert [case["runtime"]["scenario_state"]["time_period"] for case in evidence["cases"]] == [
        "peak_cool_day",
        "peak_heat_day",
    ]
    assert [case["oracle_clock"]["runtime_time_origin"] for case in evidence["cases"]] == [
        1_000_000.0,
        2_000_000.0,
    ]
    assert progress[-1] == ("case_02:scoring_oracles", 4, 4)
    assert fake.scenario_history == [
        {
            "time_period": "peak_cool_day",
            "electricity_price": "dynamic",
            "temperature_uncertainty": "medium",
            "seed": 42,
        },
        {"time_period": "peak_heat_day", "electricity_price": "constant"},
    ]
    service.verify_integrity(candidate.id)


def test_one_failed_boptest_suite_case_blocks_the_whole_candidate(tmp_path: Path) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    candidate = service.create_run(_job())

    qualified = service.qualify_with_boptest(
        candidate.id,
        client=_FakeBoptest(),
        mapping=_mapping(),
        cases=_suite_cases(second_expected=0.0),
    )

    assert qualified.status == RunStatus.FAILED
    evidence = json.loads(Path(qualified.boptest_verification_path or "").read_text())
    assert evidence["status"] == "fail"
    assert [case["status"] for case in evidence["cases"]] == ["pass", "fail"]
    assert evidence["approval_allowed"] is False
    with pytest.raises(ApprovalRequiredError):
        service.approve(candidate.id, "Alex Engineer")


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


def test_boptest_accumulates_with_existing_alfalfa_tier_under_one_digest(
    tmp_path: Path,
) -> None:
    runs = RunRepository(tmp_path / "runs")
    service = WorkbenchService(runs)
    candidate = service.create_run(_job())
    prior = runs.run_directory(candidate.id) / "alfalfa-verification/evidence.json"
    prior.parent.mkdir()
    prior.write_text('{"schema":"test-prior-alfalfa","status":"pass"}', encoding="utf-8")
    with_prior = candidate.model_copy(
        update={
            "alfalfa_verification_path": str(prior),
            "verification_artifact_paths": [str(prior)],
        }
    )
    with_prior = with_prior.model_copy(
        update={
            "artifact_sha256": artifact_hash(*service._record_artifact_paths(with_prior))
        }
    )
    runs.save(with_prior)

    qualified = service.qualify_with_boptest(
        candidate.id,
        client=_FakeBoptest(),
        mapping=_mapping(),
        oracles=[_oracle()],
        steps=2,
        step_seconds=300.0,
    )

    assert qualified.status == RunStatus.READY_FOR_REVIEW
    assert qualified.alfalfa_verification_path == str(prior)
    assert qualified.boptest_verification_path is not None
    assert str(prior) in qualified.verification_artifact_paths
    assert len(qualified.verification_artifact_paths) == 7
    service.verify_integrity(candidate.id)


def test_boptest_oracle_clock_is_elapsed_for_nonzero_model_time(tmp_path: Path) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    candidate = service.create_run(_job())

    qualified = service.qualify_with_boptest(
        candidate.id,
        client=_FakeBoptest(),
        mapping=_mapping(),
        oracles=[_oracle()],
        steps=2,
        step_seconds=300.0,
        start_time=1_000_000.0,
    )

    evidence = json.loads(Path(qualified.boptest_verification_path or "").read_text())
    assert evidence["status"] == "pass"
    assert evidence["oracle_clock"] == {
        "basis": "elapsed_seconds_from_run_start",
        "runtime_time_origin": 1_000_000.0,
    }
    assert evidence["oracles"][0]["test_times"] == [300.0, 600.0]


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
    evidence = json.loads(Path(qualified.boptest_verification_path).read_text())
    counterexample = evidence["oracles"][0]["counterexample"]
    assert counterexample["schema"] == "bactalk.trajectory-counterexample/v1"
    assert counterexample["violation_count"] == 2
    assert counterexample["first_violation_time"] == 300.0
    assert counterexample["last_violation_time"] == 600.0
    assert counterexample["window"]["test_values"] == [1.0, 1.0]
    counterexample_paths = [
        Path(path)
        for path in qualified.verification_artifact_paths
        if path.endswith("counterexample.json")
    ]
    assert len(counterexample_paths) == 1
    counterexample_artifact = json.loads(counterexample_paths[0].read_text())
    assert counterexample_artifact["schema"] == "bactalk.oracle-counterexample/v1"
    assert counterexample_artifact["oracle"]["id"] == "fan-command"
    assert counterexample_artifact["counterexample"] == counterexample
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

    catalog = client.get("/api/integrations/boptest/catalog")
    assert catalog.status_code == 200
    assert catalog.json()["test_cases"] == ["bestest_air"]
    contract = client.get("/api/integrations/boptest/catalog/bestest_air")
    assert contract.status_code == 200
    assert contract.json()["measurement_count"] == 1
    assert contract.json()["input_count"] == 2
    assert contract.json()["clean_stop"] is True

    response = client.post(
        f"/api/runs/{run_id}/verify/boptest",
        json={
            "mapping": _mapping().model_dump(mode="json"),
            "oracles": [_oracle().model_dump(mode="json")],
            "steps": 2,
            "step_seconds": 300.0,
            "scenario": {"electricity_price": "dynamic"},
        },
    )

    assert response.status_code == 200
    assert response.json()["run"]["status"] == "ready_for_review"
    assert response.json()["evidence"]["status"] == "pass"
    retained = client.get(f"/api/runs/{run_id}/verify/boptest")
    assert retained.status_code == 200
    assert retained.json()["runtime"]["test_case"] == "bestest_air"
    assert retained.json()["runtime"]["scenario_state"] == {
        "electricity_price": "dynamic"
    }


def test_multi_scenario_boptest_suite_is_available_through_the_product_api(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(tmp_path / "runs", boptest_client_factory=_FakeBoptest)
    )
    run_id = client.post("/api/runs", json=_job().model_dump(mode="json")).json()["id"]

    response = client.post(
        f"/api/runs/{run_id}/verify/boptest",
        json={
            "mapping": _mapping().model_dump(mode="json"),
            "cases": [case.model_dump(mode="json") for case in _suite_cases()],
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["run"]["status"] == "ready_for_review"
    assert response.json()["evidence"]["schema"] == (
        "bactalk.boptest-qualification-suite/v1"
    )
    assert response.json()["evidence"]["case_count"] == 2
    retained = client.get(f"/api/runs/{run_id}/verify/boptest")
    assert [case["id"] for case in retained.json()["cases"]] == [
        "peak-cooling",
        "peak-heating",
    ]


def test_durable_boptest_executor_retains_progress_and_result(tmp_path: Path) -> None:
    runs = RunRepository(tmp_path / "runs")
    service = WorkbenchService(runs)
    candidate = service.create_run(_job())
    jobs = QualificationJobRepository(tmp_path / "qualification-jobs")
    job = jobs.create_boptest(
        run_id=candidate.id,
        candidate_artifact_sha256=candidate.artifact_sha256,
        payload=_qualification_payload(),
    )

    completed = BoptestQualificationJobExecutor(
        jobs,
        service,
        client_factory=_FakeBoptest,
        worker_id="boptest-worker",
    ).execute(job.id)

    assert completed.kind == "boptest"
    assert completed.status == QualificationJobStatus.SUCCEEDED
    assert completed.worker_id == "boptest-worker"
    assert completed.model_sha256 is None
    assert completed.progress.phase == "completed"
    assert completed.progress.percent == 100
    assert completed.qualification_passed is True
    assert completed.result_artifact_sha256 == runs.get(candidate.id).artifact_sha256


def test_durable_boptest_executor_runs_the_complete_scenario_matrix(
    tmp_path: Path,
) -> None:
    runs = RunRepository(tmp_path / "runs")
    service = WorkbenchService(runs)
    candidate = service.create_run(_job())
    jobs = QualificationJobRepository(tmp_path / "qualification-jobs")
    payload = BoptestQualificationPayload(mapping=_mapping(), cases=_suite_cases())
    job = jobs.create_boptest(
        run_id=candidate.id,
        candidate_artifact_sha256=candidate.artifact_sha256,
        payload=payload,
    )

    assert job.progress.total_steps == 4
    assert jobs.payload(job.id) == payload
    completed = BoptestQualificationJobExecutor(
        jobs,
        service,
        client_factory=_FakeBoptest,
        worker_id="matrix-worker",
    ).execute(job.id)

    assert completed.status == QualificationJobStatus.SUCCEEDED
    assert completed.qualification_passed is True
    assert completed.progress.completed_steps == 4
    assert completed.progress.total_steps == 4
    evidence = json.loads(service.boptest_verification_path(candidate.id).read_text())
    assert evidence["case_count"] == 2


def test_durable_boptest_refuses_a_candidate_changed_after_submission(
    tmp_path: Path,
) -> None:
    runs = RunRepository(tmp_path / "runs")
    service = WorkbenchService(runs)
    candidate = service.create_run(_job())
    jobs = QualificationJobRepository(tmp_path / "qualification-jobs")
    job = jobs.create_boptest(
        run_id=candidate.id,
        candidate_artifact_sha256=candidate.artifact_sha256,
        payload=_qualification_payload(),
    )
    runs.save(candidate.model_copy(update={"artifact_sha256": "f" * 64}))

    with pytest.raises(ArtifactChangedError, match="changed after BOPTEST"):
        BoptestQualificationJobExecutor(
            jobs,
            service,
            client_factory=_FakeBoptest,
            worker_id="digest-bound-worker",
        ).execute(job.id)

    failed = jobs.get(job.id)
    assert failed.status == QualificationJobStatus.FAILED
    assert "ArtifactChangedError" in (failed.error or "")
    assert runs.get(candidate.id).boptest_verification_path is None


def test_running_boptest_job_cancels_cooperatively_and_stops_model(
    tmp_path: Path,
) -> None:
    runs = RunRepository(tmp_path / "runs")
    service = WorkbenchService(runs)
    candidate = service.create_run(_job())
    jobs = QualificationJobRepository(tmp_path / "qualification-jobs")
    job = jobs.create_boptest(
        run_id=candidate.id,
        candidate_artifact_sha256=candidate.artifact_sha256,
        payload=_qualification_payload(),
    )
    fake = _FakeBoptest()
    original_advance = fake.advance

    def advance_and_cancel(test_id: str, overrides: dict[str, float | int]) -> dict:
        result = original_advance(test_id, overrides)
        jobs.request_cancel(job.id)
        return result

    fake.advance = advance_and_cancel  # type: ignore[method-assign]
    canceled = BoptestQualificationJobExecutor(
        jobs,
        service,
        client_factory=lambda: fake,
        worker_id="cancel-boptest-worker",
    ).execute(job.id)

    assert canceled.status == QualificationJobStatus.CANCELED
    assert canceled.cancellation_requested is True
    assert fake.stopped is True
    assert runs.get(candidate.id).boptest_verification_path is None


def test_boptest_qualification_queue_api_persists_polls_and_cancels_jobs(
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

    response = client.post(
        f"/api/runs/{run_id}/qualification-jobs/boptest",
        json=_qualification_payload().model_dump(mode="json"),
    )

    assert response.status_code == 202, response.text
    queued = response.json()
    assert queued["kind"] == "boptest"
    assert queued["status"] == "queued"
    assert queued["schema_version"] == "bactalk.qualification-job/v3"
    assert queued["candidate_artifact_sha256"]
    assert queued["model_sha256"] is None
    assert dispatcher.enqueued == [queued["id"]]
    latest = client.get(f"/api/runs/{run_id}/qualification-jobs/latest")
    assert latest.status_code == 200
    assert latest.json()["input_sha256"] == queued["input_sha256"]

    canceled = client.post(f"/api/qualification-jobs/{queued['id']}/cancel")
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "canceled"
    assert dispatcher.canceled == [queued["id"]]
