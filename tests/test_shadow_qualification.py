"""N7 (D5): the Niagara Shadow Runtime as a qualification job and review evidence."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bactalk.api import create_app
from bactalk.domain import RunStatus
from bactalk.library_demo import lbnl_vav_reheat_demo_job, reference_trace
from bactalk.qualification_jobs import (
    QualificationJobRecord,
    QualificationJobRepository,
    QualificationJobStatus,
    ShadowQualificationJobExecutor,
    ShadowQualificationPayload,
)
from bactalk.repository import RunRepository
from bactalk.service import ApprovalRequiredError, WorkbenchService

pytestmark = [pytest.mark.native_bog]

CONTROLLER = "TerminalUnits.Reheat.Controller"


class _CapturingDispatcher:
    def __init__(self) -> None:
        self.enqueued: list[str] = []
        self.canceled: list[str] = []

    def enqueue(self, record: QualificationJobRecord) -> None:
        self.enqueued.append(record.id)

    def cancel(self, record: QualificationJobRecord) -> None:
        self.canceled.append(record.id)


@pytest.fixture(scope="module")
def candidate(tmp_path_factory: pytest.TempPathFactory) -> tuple[WorkbenchService, str]:
    runs = RunRepository(tmp_path_factory.mktemp("runs"))
    service = WorkbenchService(runs)
    record = service.create_run(lbnl_vav_reheat_demo_job())
    assert record.status == RunStatus.READY_FOR_REVIEW
    return service, record.id


def test_shadow_qualification_signs_bog_simulated_evidence_into_the_digest(
    tmp_path: Path,
) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    record = service.create_run(lbnl_vav_reheat_demo_job())
    before = record.artifact_sha256
    phases: list[tuple[str, int, int]] = []

    updated = service.qualify_with_shadow(
        record.id,
        kernel_backend="python",
        progress_callback=lambda phase, done, total: phases.append((phase, done, total)),
    )

    assert updated.status == RunStatus.READY_FOR_REVIEW
    assert updated.artifact_sha256 != before
    assert updated.shadow_verification_path is not None
    assert updated.shadow_verification_path in updated.verification_artifact_paths
    evidence = json.loads(Path(updated.shadow_verification_path).read_text(encoding="utf-8"))
    assert evidence["schema"] == "bactalk.shadow-qualification/v1"
    assert evidence["status"] == "pass"
    assert evidence["tier"] == "bog-simulated"
    assert evidence["engine"].startswith("Niagara Shadow Runtime (bog-simulated")
    assert evidence["approval_allowed"] is True
    assert evidence["live_building_writes"] is False
    assert evidence["artifact_sha256_before_qualification"] == before
    assert evidence["report"]["passed"] is True
    assert {s["name"] for s in evidence["report"]["scenarios"]} == {
        case.name for case in record.job.acceptance_tests
    }
    differential = evidence["differential"]
    assert differential["passed"] is True
    assert differential["reference_available"] is True
    assert differential["failing_cases"] == []
    assert set(evidence["reference"]) == {case.name for case in record.job.acceptance_tests}
    assert phases[0][0] == "shadow_runtime"
    assert phases[-1] == ("completed", phases[-1][2], phases[-1][2])
    # Append-once, like BOPTEST and Alfalfa evidence.
    with pytest.raises(ValueError, match="append-once"):
        service.qualify_with_shadow(record.id, kernel_backend="python")
    # The evidence is part of the digest a later approval signs.
    service.verify_integrity(record.id)
    Path(updated.shadow_verification_path).write_text("{}", encoding="utf-8")
    with pytest.raises(Exception, match="artifact changed"):
        service.verify_integrity(record.id)


def _doctored_reference() -> dict:
    """The retained reference with every yDam value pushed far outside its band."""

    reference = copy.deepcopy(reference_trace(CONTROLLER))  # the loader caches its copy
    assert reference is not None
    for case in reference["cases"]:
        outputs = case["outputs"]
        outputs["yDam"] = [value + 0.5 for value in outputs["yDam"]]
    return reference


def test_a_divergence_from_the_reference_fails_the_candidate_and_blocks_approval(
    tmp_path: Path,
) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    record = service.create_run(lbnl_vav_reheat_demo_job())

    updated = service.qualify_with_shadow(
        record.id, kernel_backend="python", reference=_doctored_reference()
    )

    assert updated.status == RunStatus.FAILED
    evidence = json.loads(Path(updated.shadow_verification_path).read_text(encoding="utf-8"))
    assert evidence["status"] == "fail"
    assert evidence["approval_allowed"] is False
    assert evidence["report"]["passed"] is True, "the suite itself still passes"
    assert evidence["differential"]["passed"] is False
    assert evidence["differential"]["failing_cases"]
    failing = next(c for c in evidence["differential"]["cases"] if not c["passed"])
    assert any(s["signal"] == "yDam" and not s["passed"] for s in failing["signals"])
    with pytest.raises(ApprovalRequiredError):
        service.approve(record.id, "Alex Engineer")
    with pytest.raises(ApprovalRequiredError):
        service.export_path(record.id)


def test_shadow_executor_runs_the_job_and_records_the_result(tmp_path: Path) -> None:
    runs = RunRepository(tmp_path / "runs")
    service = WorkbenchService(runs)
    candidate = service.create_run(lbnl_vav_reheat_demo_job())
    jobs = QualificationJobRepository(tmp_path / "qualification-jobs")
    job = jobs.create_shadow(
        run_id=candidate.id,
        candidate_artifact_sha256=candidate.artifact_sha256,
        payload=ShadowQualificationPayload(kernel_backend="python"),
        total_steps=271,
    )
    assert job.kind == "shadow" and job.transport == "shadow_runtime"

    completed = ShadowQualificationJobExecutor(jobs, service, worker_id="shadow-worker").execute(
        job.id
    )

    assert completed.status == QualificationJobStatus.SUCCEEDED
    assert completed.worker_id == "shadow-worker"
    evidence = json.loads(
        Path(runs.get(candidate.id).shadow_verification_path or "").read_text(encoding="utf-8")
    )
    assert completed.qualification_passed is True, {
        "failing_cases": evidence["differential"]["failing_cases"],
        "divergences": [
            c["first_divergence"] for c in evidence["differential"]["cases"] if not c["passed"]
        ],
        "scenarios": [
            (s["name"], [a for a in s["assertions"] if not a["passed"]][:3])
            for s in evidence["report"]["scenarios"]
            if not s["passed"]
        ],
    }
    assert completed.progress.phase == "completed"
    assert completed.progress.percent == 100
    assert completed.result_artifact_sha256 == runs.get(candidate.id).artifact_sha256
    assert jobs.payload(job.id) == ShadowQualificationPayload(kernel_backend="python")


def test_shadow_executor_refuses_a_candidate_changed_after_submission(tmp_path: Path) -> None:
    runs = RunRepository(tmp_path / "runs")
    service = WorkbenchService(runs)
    candidate = service.create_run(lbnl_vav_reheat_demo_job())
    jobs = QualificationJobRepository(tmp_path / "qualification-jobs")
    job = jobs.create_shadow(
        run_id=candidate.id,
        candidate_artifact_sha256="0" * 64,
        payload=ShadowQualificationPayload(kernel_backend="python"),
        total_steps=1,
    )
    with pytest.raises(Exception, match="candidate changed"):
        ShadowQualificationJobExecutor(jobs, service).execute(job.id)
    assert jobs.get(job.id).status == QualificationJobStatus.FAILED


def test_shadow_qualification_through_the_product_api(tmp_path: Path) -> None:
    dispatcher = _CapturingDispatcher()
    client = TestClient(create_app(tmp_path / "runs", qualification_dispatcher=dispatcher))
    run_id = client.post("/api/runs/demo").json()["id"]

    assert client.get(f"/api/runs/{run_id}/verify/shadow").status_code == 404
    previews = client.get(f"/api/runs/{run_id}/niagara-previews")
    assert previews.status_code == 200
    folders = previews.json()["folders"]
    assert {folder["name"] for folder in folders} >= {"Inputs", "Outputs"}
    assert all(folder["svg"].lstrip().startswith("<svg") for folder in folders)

    queued = client.post(
        f"/api/runs/{run_id}/qualification-jobs/shadow", json={"kernel_backend": "python"}
    )
    assert queued.status_code == 202, queued.text
    assert queued.json()["kind"] == "shadow"
    assert queued.json()["transport"] == "shadow_runtime"
    assert queued.json()["progress"]["total_steps"] == 6 * 45 + 1
    assert dispatcher.enqueued == [queued.json()["id"]]
    latest = client.get(f"/api/runs/{run_id}/qualification-jobs/latest")
    assert latest.json()["kind"] == "shadow"
    assert client.post(f"/api/qualification-jobs/{queued.json()['id']}/cancel").status_code == 200

    summary = client.get(f"/api/runs/{run_id}/release-summary").json()
    assert summary["shadow"] == {
        "available": False,
        "passed": None,
        "tier": "bog-simulated",
        "failing_cases": [],
    }

    verified = client.post(f"/api/runs/{run_id}/verify/shadow", json={"kernel_backend": "python"})
    assert verified.status_code == 200, verified.text
    assert verified.json()["evidence"]["status"] == "pass"
    assert verified.json()["run"]["shadow_verification_path"]
    fetched = client.get(f"/api/runs/{run_id}/verify/shadow")
    assert fetched.status_code == 200
    assert fetched.json()["tier"] == "bog-simulated"
    summary = client.get(f"/api/runs/{run_id}/release-summary").json()
    assert summary["shadow"]["available"] is True
    assert summary["shadow"]["passed"] is True
    assert summary["shadow"]["failing_cases"] == []
    again = client.post(
        f"/api/runs/{run_id}/qualification-jobs/shadow", json={"kernel_backend": "python"}
    )
    assert again.status_code == 409
    assert "append-once" in again.json()["detail"]


def test_shadow_payload_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError):
        ShadowQualificationPayload.model_validate({"policy": "default", "steps": 3})
    with pytest.raises(ValueError):
        ShadowQualificationPayload.model_validate({"kernel_backend": "rust"})
