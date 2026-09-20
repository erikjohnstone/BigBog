from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from bactalk.api import create_app
from bactalk.integrations.use_audit import IntegrationUseAudit


def test_every_stack_lock_component_has_a_product_boundary_and_proof() -> None:
    report = IntegrationUseAudit().assert_complete()
    lock = json.loads(Path("ops/stack.lock.json").read_text(encoding="utf-8"))

    assert report["passed"] is True
    assert report["pinned_component_count"] == len(lock["components"])
    assert report["bound_component_count"] == report["pinned_component_count"]
    assert report["missing_bindings"] == []
    assert report["stale_bindings"] == []
    assert all(item["product_path"] and item["proof"] for item in report["components"])


def test_integration_audit_api_exposes_no_presence_only_pins(tmp_path: Path) -> None:
    response = TestClient(create_app(tmp_path / "runs")).get("/api/system/integration-audit")

    assert response.status_code == 200
    assert response.json()["passed"] is True
