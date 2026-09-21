"""Approval is bound to the exact artifact the reviewer inspected.

The product claim is that a named human approves one exact content hash. The
server has always re-verified the retained files at approval time, but it
previously ignored the digest the reviewer named, so an artifact that changed
between review and approval could be approved unseen. These tests pin the
stronger contract: when the reviewer states which digest they reviewed, a
mismatch is refused.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bactalk.api import create_app
from bactalk.repository import RunRepository
from bactalk.service import ArtifactChangedError, WorkbenchService

pytestmark = pytest.mark.minimal


def _ready_run(client: TestClient) -> dict:
    response = client.post("/api/runs/demo")
    assert response.status_code == 201
    record = response.json()
    assert record["status"] == "ready_for_review"
    return record


def test_approval_accepts_the_reviewed_digest(tmp_path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))
    record = _ready_run(client)
    response = client.post(
        f"/api/runs/{record['id']}/approve",
        json={"reviewer": "Review Engineer", "artifact_sha256": record["artifact_sha256"]},
    )
    assert response.status_code == 200
    approved = response.json()
    assert approved["status"] == "approved"
    assert approved["approval"]["artifact_sha256"] == record["artifact_sha256"]


def test_approval_refuses_a_digest_that_does_not_match(tmp_path) -> None:
    """A stale or wrong digest is refused with 412, not silently accepted."""
    client = TestClient(create_app(tmp_path / "runs"))
    record = _ready_run(client)
    response = client.post(
        f"/api/runs/{record['id']}/approve",
        json={"reviewer": "Review Engineer", "artifact_sha256": "0" * 64},
    )
    assert response.status_code == 412
    assert "changed since it was reviewed" in response.json()["detail"]

    # The run must remain reviewable rather than being left half-approved.
    after = client.get(f"/api/runs/{record['id']}").json()
    assert after["status"] == "ready_for_review"
    assert after["approval"] is None


def test_approval_rejects_a_malformed_digest(tmp_path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))
    record = _ready_run(client)
    response = client.post(
        f"/api/runs/{record['id']}/approve",
        json={"reviewer": "Review Engineer", "artifact_sha256": "not-a-digest"},
    )
    assert response.status_code == 422


def test_approval_without_a_digest_still_works(tmp_path) -> None:
    """Naming the digest is optional, so existing clients keep working."""
    client = TestClient(create_app(tmp_path / "runs"))
    record = _ready_run(client)
    response = client.post(
        f"/api/runs/{record['id']}/approve", json={"reviewer": "Review Engineer"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "approved"


def test_service_layer_raises_artifact_changed(tmp_path) -> None:
    """The service enforces the gate directly, not only through the API."""
    runs = tmp_path / "runs"
    client = TestClient(create_app(runs))
    record = _ready_run(client)

    service = WorkbenchService(RunRepository(runs))
    with pytest.raises(ArtifactChangedError):
        service.approve(
            record["id"],
            "Review Engineer",
            expected_artifact_sha256="1" * 64,
        )
    # Approving the digest that is actually current succeeds.
    approved = service.approve(
        record["id"],
        "Review Engineer",
        expected_artifact_sha256=record["artifact_sha256"],
    )
    assert approved.status.value == "approved"


def test_export_remains_refused_until_approval(tmp_path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))
    record = _ready_run(client)
    assert client.get(f"/api/runs/{record['id']}/export").status_code == 403
    assert client.get(f"/api/runs/{record['id']}/review-bundle").status_code == 403
    client.post(
        f"/api/runs/{record['id']}/approve",
        json={"reviewer": "Review Engineer", "artifact_sha256": record["artifact_sha256"]},
    )
    assert client.get(f"/api/runs/{record['id']}/export").status_code == 200
    assert client.get(f"/api/runs/{record['id']}/review-bundle").status_code == 200
