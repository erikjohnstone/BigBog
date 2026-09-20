from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4


class SecurityConfigurationError(ValueError):
    """Raised when production authentication would start in an unsafe state."""


class Role(StrEnum):
    VIEWER = "viewer"
    PROGRAMMER = "programmer"
    APPROVER = "approver"
    ADMIN = "admin"


@dataclass(frozen=True)
class Principal:
    subject: str
    display_name: str
    tenant_id: str
    roles: frozenset[Role]
    credential_id: str

    def permits(self, required: Role) -> bool:
        if Role.ADMIN in self.roles or required in self.roles:
            return True
        # Operators and approvers necessarily need read access to do their jobs.
        return required == Role.VIEWER and bool(
            self.roles.intersection({Role.PROGRAMMER, Role.APPROVER})
        )


@dataclass(frozen=True)
class TokenCredential:
    credential_id: str
    token_sha256: str
    principal: Principal


@dataclass(frozen=True)
class SecurityConfig:
    enabled: bool
    credentials: tuple[TokenCredential, ...] = ()
    require_https: bool = True
    source: str = "local-development"

    @classmethod
    def local_development(cls) -> SecurityConfig:
        return cls(enabled=False, require_https=False)

    @classmethod
    def from_environment(cls) -> SecurityConfig:
        configured = os.getenv("BACTALK_AUTH_CONFIG")
        if not configured:
            return cls.local_development()
        path = Path(configured).expanduser().resolve()
        if not path.is_file():
            raise SecurityConfigurationError(f"BACTALK_AUTH_CONFIG is not a file: {path}")
        permissions = stat.S_IMODE(path.stat().st_mode)
        if permissions & 0o077:
            raise SecurityConfigurationError(
                "BACTALK_AUTH_CONFIG must not be readable or writable by group/other; "
                f"expected mode 0600, found {permissions:04o}"
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SecurityConfigurationError(f"cannot read authentication config: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("schema") != "bactalk.auth/v1":
            raise SecurityConfigurationError(
                "authentication config must use schema bactalk.auth/v1"
            )
        raw_tokens = payload.get("tokens")
        if not isinstance(raw_tokens, list) or not raw_tokens:
            raise SecurityConfigurationError("authentication config requires at least one token")

        credentials: list[TokenCredential] = []
        ids: set[str] = set()
        hashes: set[str] = set()
        for index, item in enumerate(raw_tokens):
            if not isinstance(item, dict):
                raise SecurityConfigurationError(f"tokens[{index}] must be an object")
            credential_id = _identifier(item.get("id"), f"tokens[{index}].id")
            subject = _identifier(item.get("subject"), f"tokens[{index}].subject")
            tenant_id = _identifier(item.get("tenant_id"), f"tokens[{index}].tenant_id")
            display_name = item.get("display_name")
            token_sha256 = item.get("token_sha256")
            raw_roles = item.get("roles")
            if not isinstance(display_name, str) or not (2 <= len(display_name) <= 120):
                raise SecurityConfigurationError(
                    f"tokens[{index}].display_name must contain 2-120 characters"
                )
            if not isinstance(token_sha256, str) or not re.fullmatch(
                r"[a-f0-9]{64}", token_sha256
            ):
                raise SecurityConfigurationError(
                    f"tokens[{index}].token_sha256 must be a lowercase SHA-256 digest"
                )
            if not isinstance(raw_roles, list) or not raw_roles:
                raise SecurityConfigurationError(f"tokens[{index}].roles cannot be empty")
            try:
                roles = frozenset(Role(value) for value in raw_roles)
            except (TypeError, ValueError) as exc:
                raise SecurityConfigurationError(f"tokens[{index}].roles are invalid") from exc
            if credential_id in ids or token_sha256 in hashes:
                raise SecurityConfigurationError("credential ids and token hashes must be unique")
            ids.add(credential_id)
            hashes.add(token_sha256)
            principal = Principal(
                subject=subject,
                display_name=display_name,
                tenant_id=tenant_id,
                roles=roles,
                credential_id=credential_id,
            )
            credentials.append(TokenCredential(credential_id, token_sha256, principal))

        require_https = not _truthy(os.getenv("BACTALK_ALLOW_INSECURE_AUTH"))
        return cls(
            enabled=True,
            credentials=tuple(credentials),
            require_https=require_https,
            source=str(path),
        )

    def authenticate(self, authorization: str | None) -> Principal | None:
        if not self.enabled:
            return None
        if not authorization or not authorization.startswith("Bearer "):
            return None
        token = authorization[7:]
        if not token or len(token) > 4_096:
            return None
        candidate = hashlib.sha256(token.encode("utf-8")).hexdigest()
        matched: Principal | None = None
        # Compare every configured digest so position does not become a useful timing signal.
        for credential in self.credentials:
            if hmac.compare_digest(candidate, credential.token_sha256):
                matched = credential.principal
        return matched

    def status(self) -> dict[str, Any]:
        return {
            "schema": "bactalk.security-status/v1",
            "authentication_enabled": self.enabled,
            "mode": "bearer-token" if self.enabled else "local-development",
            "https_required": self.require_https if self.enabled else False,
            "configured_credentials": len(self.credentials),
            "review_identity": "authenticated-principal" if self.enabled else "self-asserted-local",
            "live_writes_enabled": False,
        }


class AuditLog:
    """Append-only, hash-chained security event ledger.

    The chain makes edits and reordering detectable. Production retention still needs
    an external immutable/WORM sink because a local administrator can truncate a file.
    """

    _ZERO_HASH = "0" * 64

    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if self.path.exists():
            os.chmod(self.path, 0o600)
            self.verify()

    def append(
        self,
        *,
        action: str,
        outcome: str,
        principal: Principal | None,
        method: str,
        path: str,
        status_code: int,
        request_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            previous = self._last_hash()
            event: dict[str, Any] = {
                "schema": "bactalk.audit-event/v1",
                "event_id": uuid4().hex,
                "occurred_at": datetime.now(UTC).isoformat(),
                "request_id": request_id,
                "actor": principal.subject if principal else "anonymous",
                "actor_display_name": principal.display_name if principal else None,
                "tenant_id": principal.tenant_id if principal else None,
                "credential_id": principal.credential_id if principal else None,
                "action": action,
                "outcome": outcome,
                "method": method,
                "path": path,
                "status_code": status_code,
                "previous_hash": previous,
            }
            event["event_hash"] = _event_hash(event)
            descriptor = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
            try:
                os.write(
                    descriptor,
                    (json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n").encode(
                        "utf-8"
                    ),
                )
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            return event

    def verify(self) -> dict[str, Any]:
        previous = self._ZERO_HASH
        count = 0
        if not self.path.exists():
            return {"valid": True, "event_count": 0, "head_hash": previous}
        with self.path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise SecurityConfigurationError(
                        f"audit log is invalid JSON at line {line_number}"
                    ) from exc
                supplied = event.get("event_hash")
                if event.get("previous_hash") != previous or supplied != _event_hash(event):
                    raise SecurityConfigurationError(
                        f"audit hash chain verification failed at line {line_number}"
                    )
                previous = supplied
                count += 1
        return {"valid": True, "event_count": count, "head_hash": previous}

    def _last_hash(self) -> str:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return self._ZERO_HASH
        last = ""
        with self.path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    last = line
        if not last:
            return self._ZERO_HASH
        return str(json.loads(last)["event_hash"])


def required_role(method: str, path: str) -> Role | None:
    if not path.startswith("/api/") or path in {"/api/health", "/api/security/status"}:
        return None
    if path == "/api/security/audit/status":
        return Role.ADMIN
    if path.endswith("/approve") or path.endswith("/reject"):
        return Role.APPROVER
    if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        return Role.PROGRAMMER
    return Role.VIEWER


def hash_token(token: str) -> str:
    if len(token) < 32:
        raise ValueError("production bearer tokens must contain at least 32 characters")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _event_hash(event: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in event.items() if key != "event_hash"}
    encoded = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _identifier(value: Any, label: str) -> str:
    valid = isinstance(value, str) and re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}", value
    )
    if not valid:
        raise SecurityConfigurationError(f"{label} is invalid")
    return value


def _truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}
