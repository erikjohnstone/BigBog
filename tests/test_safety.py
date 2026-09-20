from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from bactalk.safety import (
    CommandLease,
    CommandPolicyGateway,
    DenialCode,
    GatewayMode,
    NumericCommandPolicy,
    NumericCommandRequest,
    command_lease_signature,
)

NOW = datetime(2026, 9, 19, 16, 0, tzinfo=UTC)
HASH = "a" * 64
KEY = b"bactalk-test-command-lease-key-32-bytes"


def policy() -> NumericCommandPolicy:
    return NumericCommandPolicy(
        point="DamperCommand",
        minimum=0,
        maximum=100,
        max_delta_per_second=5,
        max_telemetry_age_seconds=15,
    )


def lease(**updates) -> CommandLease:
    values = {
        "id": "lease-0001",
        "artifact_sha256": HASH,
        "issued_by": "Alex Engineer",
        "valid_from": NOW - timedelta(minutes=1),
        "valid_until": NOW + timedelta(minutes=1),
    }
    values.update(updates)
    values["signature"] = command_lease_signature(
        lease_id=values["id"],
        artifact_sha256=values["artifact_sha256"],
        issued_by=values["issued_by"],
        valid_from=values["valid_from"],
        valid_until=values["valid_until"],
        key=KEY,
    )
    return CommandLease(**values)


def request(**updates) -> NumericCommandRequest:
    values = {
        "request_id": "request-0001",
        "point": "DamperCommand",
        "value": 25.0,
        "artifact_sha256": HASH,
        "lease_id": "lease-0001",
        "telemetry_at": NOW - timedelta(seconds=1),
    }
    values.update(updates)
    return NumericCommandRequest(**values)


def test_gateway_is_default_deny_and_has_no_live_mode() -> None:
    gateway = CommandPolicyGateway(
        [policy()],
        approved_artifact_sha256=HASH,
        lease_verification_key=KEY,
    )

    decision = gateway.authorize(request(), lease(), now=NOW)

    assert decision.allowed is False
    assert decision.code == DenialCode.GATEWAY_DISABLED
    assert set(GatewayMode) == {
        GatewayMode.DISABLED,
        GatewayMode.SIMULATION,
        GatewayMode.ISOLATED_LAB,
    }


def test_isolated_request_requires_every_guard_and_records_rate_state() -> None:
    gateway = CommandPolicyGateway(
        [policy()],
        approved_artifact_sha256=HASH,
        lease_verification_key=KEY,
        mode=GatewayMode.ISOLATED_LAB,
    )

    first = gateway.authorize(request(), lease(), now=NOW)
    second = gateway.authorize(
        request(request_id="request-0002", value=35),
        lease(),
        now=NOW + timedelta(seconds=1),
    )
    third = gateway.authorize(
        request(
            request_id="request-0003",
            value=30,
            telemetry_at=NOW + timedelta(seconds=1),
        ),
        lease(),
        now=NOW + timedelta(seconds=1),
    )

    assert first.allowed is True
    assert second.code == DenialCode.RATE_LIMIT
    assert third.allowed is True


def test_tampered_command_lease_is_rejected() -> None:
    gateway = CommandPolicyGateway(
        [policy()],
        approved_artifact_sha256=HASH,
        lease_verification_key=KEY,
        mode=GatewayMode.ISOLATED_LAB,
    )
    tampered = lease().model_copy(update={"issued_by": "Mallory"})

    decision = gateway.authorize(request(), tampered, now=NOW)

    assert decision.allowed is False
    assert decision.code == DenialCode.LEASE_INVALID


@pytest.mark.parametrize(
    ("request_updates", "lease_updates", "gateway_change", "expected"),
    [
        ({"point": "ValveCommand"}, {}, None, DenialCode.POINT_NOT_ALLOWLISTED),
        ({"artifact_sha256": "b" * 64}, {}, None, DenialCode.ARTIFACT_MISMATCH),
        ({"lease_id": "other-lease"}, {}, None, DenialCode.LEASE_INVALID),
        ({}, {"valid_until": NOW - timedelta(seconds=1)}, None, DenialCode.LEASE_INVALID),
        (
            {"telemetry_at": NOW - timedelta(seconds=16)},
            {},
            None,
            DenialCode.TELEMETRY_STALE,
        ),
        ({"value": 101}, {}, None, DenialCode.OUT_OF_BOUNDS),
        ({}, {}, "emergency_stop", DenialCode.EMERGENCY_STOP),
    ],
)
def test_gateway_denies_each_unsafe_condition(
    request_updates: dict,
    lease_updates: dict,
    gateway_change: str | None,
    expected: DenialCode,
) -> None:
    gateway = CommandPolicyGateway(
        [policy()],
        approved_artifact_sha256=HASH,
        lease_verification_key=KEY,
        mode=GatewayMode.SIMULATION,
    )
    if gateway_change == "emergency_stop":
        gateway.emergency_stop = True

    decision = gateway.authorize(
        request(**request_updates),
        lease(**lease_updates),
        now=NOW,
    )

    assert decision.allowed is False
    assert decision.code == expected
