from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bactalk.api import create_app
from bactalk.security import (
    Principal,
    Role,
    SecurityConfig,
    SecurityConfigurationError,
    TokenCredential,
    hash_token,
)

PROGRAMMER_TOKEN = "programmer-token-000000000000000000000000"
APPROVER_TOKEN = "approver-token-00000000000000000000000000"
ADMIN_TOKEN = "admin-token-0000000000000000000000000000"


def _credential(token: str, subject: str, role: Role, display_name: str) -> TokenCredential:
    principal = Principal(
        subject=subject,
        display_name=display_name,
        tenant_id="acme-controls",
        roles=frozenset({role}),
        credential_id=f"{subject}-token",
    )
    return TokenCredential(principal.credential_id, hash_token(token), principal)


def _security() -> SecurityConfig:
    return SecurityConfig(
        enabled=True,
        require_https=False,
        source="test",
        credentials=(
            _credential(PROGRAMMER_TOKEN, "operator@example.com", Role.PROGRAMMER, "Pat Operator"),
            _credential(APPROVER_TOKEN, "engineer@example.com", Role.APPROVER, "Alex Engineer"),
            _credential(ADMIN_TOKEN, "admin@example.com", Role.ADMIN, "Casey Admin"),
        ),
    )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_authenticated_roles_separate_programming_from_approval(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs", security_config=_security()))

    assert client.get("/api/health").status_code == 200
    assert client.get("/api/security/status").json()["authentication_enabled"] is True
    assert client.get("/api/runs").status_code == 401

    created = client.post("/api/runs/demo", headers=_bearer(PROGRAMMER_TOKEN))
    assert created.status_code == 201
    run_id = created.json()["id"]

    wrong_role = client.post(
        f"/api/runs/{run_id}/approve",
        headers=_bearer(PROGRAMMER_TOKEN),
        json={"reviewer": "Spoofed Reviewer"},
    )
    assert wrong_role.status_code == 403

    approved = client.post(
        f"/api/runs/{run_id}/approve",
        headers=_bearer(APPROVER_TOKEN),
        json={"reviewer": "Spoofed Reviewer"},
    )
    assert approved.status_code == 200
    approval = approved.json()["approval"]
    assert approval["reviewer"] == "Alex Engineer"
    assert approval["actor_id"] == "engineer@example.com"
    assert approval["tenant_id"] == "acme-controls"
    assert approval["authentication"] == "bearer-token"

    export = client.get(f"/api/runs/{run_id}/export", headers=_bearer(APPROVER_TOKEN))
    assert export.status_code == 200


def test_security_audit_is_hash_chained_and_admin_only(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs", security_config=_security()))
    client.get("/api/runs")
    client.get("/api/runs", headers=_bearer(PROGRAMMER_TOKEN))

    denied = client.get("/api/security/audit/status", headers=_bearer(PROGRAMMER_TOKEN))
    assert denied.status_code == 403
    status = client.get("/api/security/audit/status", headers=_bearer(ADMIN_TOKEN))
    assert status.status_code == 200
    assert status.json()["valid"] is True
    assert status.json()["event_count"] >= 3

    events = [
        json.loads(line)
        for line in (tmp_path / "audit" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[0]["previous_hash"] == "0" * 64
    assert all("authorization" not in event for event in events)
    assert all(
        current["previous_hash"] == previous["event_hash"]
        for previous, current in zip(events, events[1:], strict=False)
    )


def test_environment_auth_config_requires_hashes_and_private_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "auth.json"
    config_path.write_text(
        json.dumps(
            {
                "schema": "bactalk.auth/v1",
                "tokens": [
                    {
                        "id": "operator-token",
                        "subject": "operator@example.com",
                        "display_name": "Pat Operator",
                        "tenant_id": "acme-controls",
                        "roles": ["programmer"],
                        "token_sha256": hash_token(PROGRAMMER_TOKEN),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BACTALK_AUTH_CONFIG", str(config_path))
    os.chmod(config_path, 0o644)
    with pytest.raises(SecurityConfigurationError, match="mode 0600"):
        SecurityConfig.from_environment()

    os.chmod(config_path, 0o600)
    config = SecurityConfig.from_environment()
    principal = config.authenticate(f"Bearer {PROGRAMMER_TOKEN}")
    assert principal is not None
    assert principal.subject == "operator@example.com"
    assert config.authenticate("Bearer wrong-token") is None


def test_authentication_requires_https_by_default(tmp_path: Path) -> None:
    security = _security()
    security = SecurityConfig(
        enabled=True,
        credentials=security.credentials,
        require_https=True,
        source="test",
    )
    client = TestClient(create_app(tmp_path / "runs", security_config=security))
    response = client.get("/api/runs", headers=_bearer(PROGRAMMER_TOKEN))
    assert response.status_code == 400
    assert "HTTPS" in response.json()["detail"]
