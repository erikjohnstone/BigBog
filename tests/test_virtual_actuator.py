from __future__ import annotations

import pytest
from pydantic import ValidationError

from bactalk.domain import VirtualActuatorKind, VirtualActuatorSpec
from bactalk.integrations.virtual_actuator import VirtualActuator, VirtualActuatorFault


def _spec(**overrides: object) -> VirtualActuatorSpec:
    payload: dict[str, object] = {
        "id": "HeatingValve",
        "kind": VirtualActuatorKind.VALVE,
        "command_point": "HeatingValveCommand",
        "position_point": "HeatingValvePosition",
        "stroke_open_seconds": 100.0,
        "stroke_close_seconds": 50.0,
        "proof_timeout_seconds": 5.0,
        "leakage_percent": 2.0,
        "flow_exponent": 2.0,
    }
    payload.update(overrides)
    return VirtualActuatorSpec.model_validate(payload)


def test_virtual_actuator_models_stroke_proof_leakage_and_recovery() -> None:
    actuator = VirtualActuator(_spec(), initial_position=0.0)

    halfway = actuator.step(100.0, step_seconds=50.0)
    assert halfway.physical_position == pytest.approx(50.0)
    assert halfway.feedback_position == pytest.approx(50.0)
    assert halfway.flow_percent == pytest.approx(26.5)
    assert halfway.open_proof is False
    assert halfway.closed_proof is False
    assert halfway.traveling is True
    assert halfway.proof_alarm is True

    open_sample = actuator.step(100.0, step_seconds=50.0)
    assert open_sample.physical_position == 100.0
    assert open_sample.open_proof is True
    assert open_sample.command_feedback_mismatch is False
    assert open_sample.mismatch_seconds == 0.0
    assert open_sample.proof_alarm is False

    closed_sample = actuator.step(0.0, step_seconds=50.0)
    assert closed_sample.physical_position == 0.0
    assert closed_sample.closed_proof is True
    assert closed_sample.flow_percent == 2.0


def test_virtual_actuator_exposes_physical_feedback_and_proof_faults() -> None:
    actuator = VirtualActuator(_spec(), initial_position=20.0)
    fault = VirtualActuatorFault(
        stuck_position=35.0,
        feedback_bias=7.0,
        open_proof_failed=True,
    )

    failed = actuator.step(100.0, step_seconds=6.0, fault=fault)
    assert failed.physical_position == 35.0
    assert failed.feedback_position == 42.0
    assert failed.command_feedback_mismatch is True
    assert failed.proof_alarm is True
    assert failed.open_proof is False

    recovered = actuator.step(100.0, step_seconds=65.0)
    assert recovered.physical_position == 100.0
    assert recovered.feedback_position == 100.0
    assert recovered.open_proof is True
    assert recovered.proof_alarm is False


def test_virtual_actuator_command_loss_drives_fail_position_and_travel_limits() -> None:
    actuator = VirtualActuator(_spec(fail_position=10.0), initial_position=80.0)
    failed = actuator.step(
        100.0,
        step_seconds=50.0,
        fault=VirtualActuatorFault(command_available=False, minimum_travel=20.0),
    )

    assert failed.effective_target == 20.0
    assert failed.physical_position == 20.0
    assert failed.command_available is False


def test_virtual_actuator_rejects_incoherent_physical_contracts() -> None:
    with pytest.raises(ValidationError, match="minimum_position"):
        _spec(minimum_position=80.0, maximum_position=20.0)
    with pytest.raises(ValidationError, match="threshold"):
        _spec(closed_proof_threshold=90.0, open_proof_threshold=10.0)
    with pytest.raises(ValidationError, match="minimum_travel"):
        VirtualActuatorFault(minimum_travel=80.0, maximum_travel=20.0)
