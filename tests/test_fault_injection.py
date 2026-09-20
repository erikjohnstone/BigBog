import pytest
from pydantic import ValidationError

from bactalk.domain import (
    AcceptanceCase,
    AcceptancePhase,
    Block,
    BlockKind,
    ControlGraph,
    FaultInjection,
    FaultKind,
    Link,
    OutputExpectation,
)
from bactalk.simulator import run_generic_acceptance_suite


def _fallback_graph() -> ControlGraph:
    return ControlGraph(
        name="SensorFallback",
        blocks=[
            Block(
                id="Sensor",
                kind=BlockKind.NUMERIC_INPUT,
                label="Sensor",
                config={"default": 0.0},
            ),
            Block(
                id="SensorValid",
                kind=BlockKind.BOOLEAN_INPUT,
                label="Sensor valid",
                config={"default": True},
            ),
            Block(
                id="Fallback",
                kind=BlockKind.NUMERIC_CONST,
                label="Safe fallback",
                config={"value": 42.0},
            ),
            Block(id="Select", kind=BlockKind.NUMERIC_SWITCH, label="Valid value or fallback"),
            Block(id="Command", kind=BlockKind.NUMERIC_OUTPUT, label="Command"),
        ],
        links=[
            Link(source="SensorValid", target="Select", target_slot="selector"),
            Link(source="Sensor", target="Select", target_slot="when_true"),
            Link(source="Fallback", target="Select", target_slot="when_false"),
            Link(source="Select", target="Command", target_slot="in"),
        ],
    )


def test_fault_contract_proves_fallback_and_recovery_with_evidence() -> None:
    case = AcceptanceCase(
        name="sensor failure and recovery",
        expectations=[OutputExpectation(target="Command", value=60.0)],
        timeline=[
            AcceptancePhase(
                name="normal",
                inputs={"Sensor": 55.0, "SensorValid": True},
                expectations=[OutputExpectation(target="Command", value=55.0)],
            ),
            AcceptancePhase(
                name="biased and invalid",
                inputs={"Sensor": 55.0},
                faults=[
                    FaultInjection(
                        id="sensor_bias",
                        target="Sensor",
                        kind=FaultKind.BIAS,
                        value=10.0,
                        quality_target="SensorValid",
                    )
                ],
                expectations=[OutputExpectation(target="Command", value=42.0)],
            ),
            AcceptancePhase(
                name="recovered",
                inputs={"Sensor": 60.0, "SensorValid": True},
                expectations=[OutputExpectation(target="Command", value=60.0)],
            ),
        ],
    )

    report = run_generic_acceptance_suite(_fallback_graph(), [case])

    assert report.passed is True
    fault_sample = report.scenarios[0].samples[1]
    assert fault_sample["fault.sensor_bias.raw"] == 55.0
    assert fault_sample["fault.sensor_bias.applied"] == 65.0
    assert fault_sample["effective.SensorValid"] is False
    assert fault_sample["Command"] == 42.0
    coverage = report.coverage["fault_injection"]
    assert coverage["activation_count"] == 1
    assert coverage["kinds"] == ["bias"]
    assert coverage["quality_targets"] == ["SensorValid"]
    assert coverage["recovery_phases"] == ["sensor failure and recovery / recovered"]


def test_stale_fault_holds_first_value_across_contiguous_phases() -> None:
    case = AcceptanceCase(
        name="stale sensor",
        expectations=[OutputExpectation(target="Command", value=42.0)],
        timeline=[
            AcceptancePhase(
                name="stale starts",
                inputs={"Sensor": 51.0, "SensorValid": True},
                faults=[
                    FaultInjection(
                        id="stale_sensor",
                        target="Sensor",
                        kind=FaultKind.STALE,
                        quality_target="SensorValid",
                    )
                ],
                expectations=[OutputExpectation(target="Sensor", value=51.0)],
            ),
            AcceptancePhase(
                name="source changes but sample is stale",
                inputs={"Sensor": 79.0},
                faults=[
                    FaultInjection(
                        id="stale_sensor",
                        target="Sensor",
                        kind=FaultKind.STALE,
                        quality_target="SensorValid",
                    )
                ],
                expectations=[OutputExpectation(target="Sensor", value=51.0)],
            ),
        ],
    )

    report = run_generic_acceptance_suite(_fallback_graph(), [case])

    assert report.passed is True
    assert report.scenarios[0].samples[1]["fault.stale_sensor.raw"] == 79.0
    assert report.scenarios[0].samples[1]["fault.stale_sensor.applied"] == 51.0


@pytest.mark.parametrize(
    ("kind", "value", "expected"),
    [
        (FaultKind.FORCE, 7.0, 7.0),
        (FaultKind.SCALE, 2.0, 20.0),
        (FaultKind.DRIFT, 3.0, 16.0),
        (FaultKind.DROPOUT, -1.0, -1.0),
    ],
)
def test_numeric_fault_modes_are_deterministic(
    kind: FaultKind,
    value: float,
    expected: float,
) -> None:
    case = AcceptanceCase(
        name=kind.value,
        inputs={"Sensor": 10.0, "SensorValid": True},
        repeat=2,
        step_seconds=1.0,
        faults=[FaultInjection(id="fault", target="Sensor", kind=kind, value=value)],
        expectations=[OutputExpectation(target="Command", value=expected)],
    )

    report = run_generic_acceptance_suite(_fallback_graph(), [case])

    assert report.passed is True


def test_fault_target_type_is_enforced_against_graph() -> None:
    case = AcceptanceCase(
        name="invalid inversion",
        inputs={"Sensor": 10.0, "SensorValid": True},
        faults=[FaultInjection(id="bad", target="Sensor", kind=FaultKind.INVERT)],
        expectations=[OutputExpectation(target="Command", value=10.0)],
    )

    with pytest.raises(ValueError, match="requires a boolean target"):
        run_generic_acceptance_suite(_fallback_graph(), [case])


def test_fault_schema_rejects_ambiguous_parameters() -> None:
    with pytest.raises(ValidationError, match="bias fault requires value"):
        FaultInjection(id="bad", target="Sensor", kind=FaultKind.BIAS)
    with pytest.raises(ValidationError, match="stale fault does not accept value"):
        FaultInjection(id="bad", target="Sensor", kind=FaultKind.STALE, value=1.0)
