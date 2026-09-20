from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class GatewayMode(StrEnum):
    DISABLED = "disabled"
    SIMULATION = "simulation"
    ISOLATED_LAB = "isolated_lab"


class DenialCode(StrEnum):
    GATEWAY_DISABLED = "gateway_disabled"
    EMERGENCY_STOP = "emergency_stop"
    POINT_NOT_ALLOWLISTED = "point_not_allowlisted"
    ARTIFACT_MISMATCH = "artifact_mismatch"
    LEASE_INVALID = "lease_invalid"
    TELEMETRY_STALE = "telemetry_stale"
    OUT_OF_BOUNDS = "out_of_bounds"
    RATE_LIMIT = "rate_limit"


class NumericCommandPolicy(BaseModel):
    point: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    minimum: float = Field(allow_inf_nan=False)
    maximum: float = Field(allow_inf_nan=False)
    max_delta_per_second: float = Field(gt=0, allow_inf_nan=False)
    max_telemetry_age_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered_bounds(self) -> NumericCommandPolicy:
        if self.minimum >= self.maximum:
            raise ValueError("command policy minimum must be less than maximum")
        return self


class CommandLease(BaseModel):
    id: str = Field(min_length=8, max_length=128)
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    issued_by: str = Field(min_length=2, max_length=120)
    valid_from: datetime
    valid_until: datetime
    signature: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def ordered_window(self) -> CommandLease:
        if self.valid_from.tzinfo is None or self.valid_until.tzinfo is None:
            raise ValueError("command lease timestamps must be timezone-aware")
        if self.valid_until <= self.valid_from:
            raise ValueError("command lease must have a positive validity window")
        return self


class NumericCommandRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    point: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    value: float = Field(allow_inf_nan=False)
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    lease_id: str = Field(min_length=8, max_length=128)
    telemetry_at: datetime

    @model_validator(mode="after")
    def aware_telemetry_time(self) -> NumericCommandRequest:
        if self.telemetry_at.tzinfo is None:
            raise ValueError("telemetry timestamp must be timezone-aware")
        return self


class CommandDecision(BaseModel):
    allowed: bool
    code: str
    reason: str
    evaluated_at: datetime


@dataclass(frozen=True)
class AcceptedCommand:
    value: float
    accepted_at: datetime


def command_lease_signature(
    *,
    lease_id: str,
    artifact_sha256: str,
    issued_by: str,
    valid_from: datetime,
    valid_until: datetime,
    key: bytes,
) -> str:
    if len(key) < 32:
        raise ValueError("command lease signing key must contain at least 32 bytes")
    payload = "\n".join(
        [
            lease_id,
            artifact_sha256,
            issued_by,
            valid_from.isoformat(),
            valid_until.isoformat(),
        ]
    ).encode()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


class CommandPolicyGateway:
    """Pure authorization kernel; it deliberately contains no transport or write code."""

    def __init__(
        self,
        policies: list[NumericCommandPolicy],
        *,
        approved_artifact_sha256: str,
        lease_verification_key: bytes,
        mode: GatewayMode = GatewayMode.DISABLED,
    ):
        self.policies = {item.point: item for item in policies}
        if len(self.policies) != len(policies):
            raise ValueError("command policies must have unique point names")
        if not re.fullmatch(r"[a-f0-9]{64}", approved_artifact_sha256):
            raise ValueError("approved artifact hash must be a lowercase SHA-256 digest")
        if len(lease_verification_key) < 32:
            raise ValueError("command lease verification key must contain at least 32 bytes")
        self.approved_artifact_sha256 = approved_artifact_sha256
        self.lease_verification_key = lease_verification_key
        self.mode = mode
        self.emergency_stop = False
        self._accepted: dict[str, AcceptedCommand] = {}

    def authorize(
        self,
        request: NumericCommandRequest,
        lease: CommandLease,
        *,
        now: datetime | None = None,
    ) -> CommandDecision:
        evaluated_at = now or datetime.now(UTC)
        if evaluated_at.tzinfo is None:
            raise ValueError("evaluation time must be timezone-aware")

        denial = self._denial(request, lease, evaluated_at)
        if denial is not None:
            code, reason = denial
            return CommandDecision(
                allowed=False,
                code=code,
                reason=reason,
                evaluated_at=evaluated_at,
            )
        self._accepted[request.point] = AcceptedCommand(
            value=request.value,
            accepted_at=evaluated_at,
        )
        return CommandDecision(
            allowed=True,
            code="allowed",
            reason="request satisfies the isolated command policy",
            evaluated_at=evaluated_at,
        )

    def _denial(
        self,
        request: NumericCommandRequest,
        lease: CommandLease,
        now: datetime,
    ) -> tuple[DenialCode, str] | None:
        if self.mode == GatewayMode.DISABLED:
            return DenialCode.GATEWAY_DISABLED, "command gateway is disabled"
        if self.emergency_stop:
            return DenialCode.EMERGENCY_STOP, "emergency stop is active"
        policy = self.policies.get(request.point)
        if policy is None:
            return DenialCode.POINT_NOT_ALLOWLISTED, "point is not allowlisted"
        if (
            request.artifact_sha256 != self.approved_artifact_sha256
            or lease.artifact_sha256 != self.approved_artifact_sha256
        ):
            return DenialCode.ARTIFACT_MISMATCH, "request is not bound to the approved artifact"
        if request.lease_id != lease.id or not (lease.valid_from <= now <= lease.valid_until):
            return DenialCode.LEASE_INVALID, "command lease is missing, expired, or not active"
        expected_signature = command_lease_signature(
            lease_id=lease.id,
            artifact_sha256=lease.artifact_sha256,
            issued_by=lease.issued_by,
            valid_from=lease.valid_from,
            valid_until=lease.valid_until,
            key=self.lease_verification_key,
        )
        if not hmac.compare_digest(lease.signature, expected_signature):
            return DenialCode.LEASE_INVALID, "command lease signature is invalid"
        telemetry_age = (now - request.telemetry_at).total_seconds()
        if telemetry_age < 0 or telemetry_age > policy.max_telemetry_age_seconds:
            return DenialCode.TELEMETRY_STALE, "source telemetry is stale or from the future"
        if not policy.minimum <= request.value <= policy.maximum:
            return DenialCode.OUT_OF_BOUNDS, "requested value is outside engineering bounds"
        previous = self._accepted.get(request.point)
        if previous is not None:
            elapsed = (now - previous.accepted_at).total_seconds()
            allowed_delta = policy.max_delta_per_second * max(0.0, elapsed)
            if abs(request.value - previous.value) > allowed_delta:
                return DenialCode.RATE_LIMIT, "requested value exceeds rate-of-change limit"
        return None
