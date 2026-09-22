"""N9: Gate G-ENG through the API and the service: a Tier 3 candidate cannot be approved
or exported until the exact requirement digest is approved."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bactalk.api import create_app
from bactalk.library_tier3 import requirement_set, tier3_job
from bactalk.protocol import generate_test_plan
from bactalk.protocol.approvals import RequirementApprovalRepository
from bactalk.service import ApprovalRequiredError, WorkbenchService


@pytest.fixture(scope="module")
def plant():
    rs = requirement_set("hw-plant-boiler")
    plan = generate_test_plan(rs)
    return rs, tier3_job("hw-plant-boiler", plan=plan)


def test_protocol_sequences_are_listed_with_their_gate_status(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))
    listing = client.get("/api/protocol/sequences").json()
    assert listing["schema"] == "bactalk.protocol-sequence-list/v1"
    item = next(i for i in listing["items"] if i["sequence_id"] == "hw-plant-boiler")
    assert item["tier"] == 3 and item["gate_g_eng"] == "unapproved"
    assert item["requirements"] >= 17 and item["scenarios"] >= 150
    detail = client.get("/api/protocol/sequences/hw-plant-boiler").json()
    assert detail["requirements"]["schema"] == "bactalk.protocol-requirements/v1"
    assert detail["plan"]["per_requirement"]["R-01"] >= 5
    assert detail["test_plan_markdown"].startswith("# Test plan:")
    plan_text = client.get("/api/protocol/sequences/hw-plant-boiler/test-plan")
    assert plan_text.status_code == 200 and "### R-01" in plan_text.text
    assert client.get("/api/protocol/sequences/nope").status_code == 404


def test_requirement_approval_is_bound_to_the_exact_digest(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))
    digest = client.get("/api/protocol/sequences/hw-plant-boiler").json()["requirements_digest"]
    stale = client.post(
        "/api/protocol/sequences/hw-plant-boiler/approve",
        json={"reviewer": "Engineer", "requirements_digest": "0" * 64},
    )
    assert stale.status_code == 409 and "not the current requirement set" in stale.json()["detail"]
    approved = client.post(
        "/api/protocol/sequences/hw-plant-boiler/approve",
        json={"reviewer": "Engineer", "requirements_digest": digest, "note": "reviewed §5.21"},
    )
    assert approved.status_code == 201
    body = approved.json()
    assert body["schema"] == "bactalk.protocol-requirement-approval/v1"
    assert body["reviewer"] == "Engineer" and body["requirements_digest"] == digest
    assert client.get("/api/protocol/sequences/hw-plant-boiler").json()["gate_g_eng"] == "approved"
    again = client.post(
        "/api/protocol/sequences/hw-plant-boiler/approve",
        json={"reviewer": "Engineer", "requirements_digest": digest},
    )
    assert again.status_code == 409
    retained = RequirementApprovalRepository(tmp_path / "requirement-approvals")
    assert retained.is_approved("hw-plant-boiler", digest)


def test_unapproved_requirements_block_candidate_approval_and_export(tmp_path: Path, plant) -> None:
    rs, job = plant
    from bactalk.repository import RunRepository

    approvals = RequirementApprovalRepository(tmp_path / "requirement-approvals")
    service = WorkbenchService(RunRepository(tmp_path / "runs"), requirement_approvals=approvals)
    record = service.create_run(job)
    assert record.status == "ready_for_review", record.status
    with pytest.raises(ApprovalRequiredError, match="Gate G-ENG"):
        service.approve(record.id, "Reviewer", expected_artifact_sha256=record.artifact_sha256)
    from bactalk.protocol import RequirementApproval

    approvals.save(
        RequirementApproval(
            sequence_id=rs.sequence_id, requirements_digest=rs.digest(), reviewer="Engineer"
        )
    )
    approved = service.approve(
        record.id, "Reviewer", expected_artifact_sha256=record.artifact_sha256
    )
    assert approved.status == "approved"
    assert service.export_path(record.id).is_file()


def test_gate_through_the_api(tmp_path: Path, plant) -> None:
    rs, job = plant
    client = TestClient(create_app(tmp_path / "runs"))
    created = client.post("/api/runs", json=job.model_dump(mode="json"))
    assert created.status_code in {200, 201}, created.text
    run_id = created.json()["id"]
    digest = created.json()["artifact_sha256"]
    refused = client.post(
        f"/api/runs/{run_id}/approve", json={"reviewer": "Reviewer", "artifact_sha256": digest}
    )
    assert refused.status_code == 409 and "Gate G-ENG" in refused.json()["detail"]
    client.post(
        "/api/protocol/sequences/hw-plant-boiler/approve",
        json={"reviewer": "Engineer", "requirements_digest": rs.digest()},
    )
    accepted = client.post(
        f"/api/runs/{run_id}/approve", json={"reviewer": "Reviewer", "artifact_sha256": digest}
    )
    assert accepted.status_code == 200, accepted.text
