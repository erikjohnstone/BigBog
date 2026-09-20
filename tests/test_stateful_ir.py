import zipfile
from pathlib import Path

import pytest

from bactalk.compiler import NiagaraCompiler
from bactalk.domain import (
    AcceptanceCase,
    Block,
    BlockKind,
    ComparisonOperator,
    ControlGraph,
    DataType,
    JobSpec,
    Link,
    OutputExpectation,
    PointRole,
    PointSpec,
    SequenceSpec,
)
from bactalk.simulator import GraphInterpreter, run_acceptance_suite


def _block(block_id: str, kind: BlockKind, **config) -> Block:
    return Block(id=block_id, kind=kind, label=block_id, config=config)


def test_boolean_delay_has_scan_cycle_semantics_and_compiles(tmp_path: Path) -> None:
    graph = ControlGraph(
        name="ProofTimer",
        blocks=[
            _block("Enable", BlockKind.BOOLEAN_INPUT, default=False),
            _block(
                "ProofDelay",
                BlockKind.BOOLEAN_DELAY,
                on_delay_seconds=3.0,
                off_delay_seconds=1.0,
            ),
            _block("Proven", BlockKind.BOOLEAN_OUTPUT),
        ],
        links=[
            Link(source="Enable", target="ProofDelay", target_slot="in"),
            Link(source="ProofDelay", target="Proven", target_slot="in"),
        ],
    )
    job = JobSpec(
        name="Proof timer",
        site="Test",
        equipment_name="EF_1",
        sequence=SequenceSpec(family="CUSTOM_PROOF"),
        points=[
            PointSpec(
                name="Enable",
                label="Enable",
                data_type=DataType.BOOLEAN,
                role=PointRole.SENSOR,
                default=False,
            ),
            PointSpec(
                name="Proven",
                label="Proven",
                data_type=DataType.BOOLEAN,
                role=PointRole.ALARM,
                default=False,
            ),
        ],
        control_graph=graph,
        acceptance_tests=[
            AcceptanceCase(
                name="three second proof",
                inputs={"Enable": True},
                repeat=3,
                step_seconds=1.0,
                expectations=[
                    OutputExpectation(
                        target="Proven",
                        operator=ComparisonOperator.EQUAL,
                        value=True,
                    )
                ],
            )
        ],
    )

    report = run_acceptance_suite(graph, job)
    destination = NiagaraCompiler().compile(graph, tmp_path / "proof.bog")

    assert report.passed
    assert [sample["Proven"] for sample in report.scenarios[0].samples] == [
        False,
        False,
        True,
    ]
    with zipfile.ZipFile(destination) as archive:
        xml = archive.read("file.xml")
    assert b"kitControl:BooleanDelay" in xml
    assert b'onDelay"' in xml and b'v="3000"' in xml


def test_boolean_delay_with_zero_off_delay_clears_on_transition_tick() -> None:
    graph = ControlGraph(
        name="ImmediateClear",
        blocks=[
            _block("Fault", BlockKind.BOOLEAN_INPUT, default=False),
            _block(
                "Delay",
                BlockKind.BOOLEAN_DELAY,
                on_delay_seconds=2.0,
                off_delay_seconds=0.0,
            ),
            _block("Alarm", BlockKind.BOOLEAN_OUTPUT),
        ],
        links=[
            Link(source="Fault", target="Delay", target_slot="in"),
            Link(source="Delay", target="Alarm", target_slot="in"),
        ],
    )
    interpreter = GraphInterpreter(graph)

    interpreter.evaluate({"Fault": True}, step_seconds=0.0)
    interpreter.evaluate({"Fault": True}, step_seconds=1.0)
    assert interpreter.evaluate({"Fault": True}, step_seconds=1.0)["Alarm"] is True
    assert interpreter.evaluate({"Fault": False}, step_seconds=0.0)["Alarm"] is False


def test_numeric_latch_captures_only_on_rising_edge() -> None:
    graph = ControlGraph(
        name="SampleHold",
        blocks=[
            _block("Value", BlockKind.NUMERIC_INPUT, default=0.0),
            _block("Clock", BlockKind.BOOLEAN_INPUT, default=False),
            _block("Hold", BlockKind.NUMERIC_LATCH, initial=0.0),
            _block("Output", BlockKind.NUMERIC_OUTPUT),
        ],
        links=[
            Link(source="Value", target="Hold", target_slot="in"),
            Link(source="Clock", target="Hold", target_slot="clock"),
            Link(source="Hold", target="Output", target_slot="in"),
        ],
    )
    interpreter = GraphInterpreter(graph)

    assert interpreter.evaluate({"Value": 5.0, "Clock": False})["Output"] == 0.0
    assert interpreter.evaluate({"Value": 5.0, "Clock": True})["Output"] == 5.0
    assert interpreter.evaluate({"Value": 9.0, "Clock": True})["Output"] == 5.0
    interpreter.evaluate({"Value": 9.0, "Clock": False})
    assert interpreter.evaluate({"Value": 9.0, "Clock": True})["Output"] == 9.0


def test_boolean_pre_host_tick_is_explicit_one_call_memory() -> None:
    graph = ControlGraph(
        name="HostTickPre",
        blocks=[
            _block("Input", BlockKind.BOOLEAN_INPUT, default=False),
            _block("Pre", BlockKind.BOOLEAN_PRE_HOST_TICK, initial=False),
            _block("Output", BlockKind.BOOLEAN_OUTPUT),
        ],
        links=[
            Link(source="Input", target="Pre", target_slot="in"),
            Link(source="Pre", target="Output", target_slot="in"),
        ],
    )
    interpreter = GraphInterpreter(graph)

    assert interpreter.evaluate({"Input": True}, step_seconds=0.0)["Output"] is False
    # Repeated model time still advances the documented HostTick profile once.
    assert interpreter.evaluate({"Input": False}, step_seconds=0.0)["Output"] is True
    assert interpreter.evaluate({"Input": False}, step_seconds=0.0)["Output"] is False


def test_boolean_initialization_forces_first_scan_then_passes_through() -> None:
    graph = ControlGraph(
        name="PlantInitialization",
        blocks=[
            _block("Input", BlockKind.BOOLEAN_INPUT, default=False),
            _block(
                "Initialization",
                BlockKind.BOOLEAN_INITIALIZATION,
                initial=False,
                semantic_contract=(
                    "Buildings.Templates.Plants.Controls.Utilities.Initialization"
                ),
            ),
            _block("Output", BlockKind.BOOLEAN_OUTPUT),
        ],
        links=[
            Link(source="Input", target="Initialization", target_slot="in"),
            Link(source="Initialization", target="Output", target_slot="in"),
        ],
    )
    interpreter = GraphInterpreter(graph)

    assert interpreter.evaluate({"Input": True}, step_seconds=0.0)["Output"] is False
    assert interpreter.evaluate({"Input": True}, step_seconds=0.0)["Output"] is True
    assert interpreter.evaluate({"Input": False}, step_seconds=0.0)["Output"] is False


def test_timer_with_reset_restarts_and_reasserts_at_threshold() -> None:
    graph = ControlGraph(
        name="PlantTimerWithReset",
        blocks=[
            _block("Input", BlockKind.BOOLEAN_INPUT, default=False),
            _block("Reset", BlockKind.BOOLEAN_INPUT, default=False),
            _block(
                "Timer",
                BlockKind.TIMER_WITH_RESET,
                threshold_seconds=3.0,
                semantic_contract=(
                    "Buildings.Templates.Plants.Controls.Utilities.TimerWithReset"
                ),
            ),
            _block("Elapsed", BlockKind.NUMERIC_OUTPUT),
            _block("Passed", BlockKind.BOOLEAN_OUTPUT),
        ],
        links=[
            Link(source="Input", target="Timer", target_slot="in"),
            Link(source="Reset", target="Timer", target_slot="reset"),
            Link(source="Timer", source_slot="elapsed", target="Elapsed", target_slot="in"),
            Link(source="Timer", source_slot="passed", target="Passed", target_slot="in"),
        ],
    )
    interpreter = GraphInterpreter(graph)
    samples = [
        (0, True, False),
        (1, True, False),
        (3, True, False),
        (4, True, True),
        (5, True, True),
        (7, True, False),
        (8, False, False),
        (9, True, False),
    ]
    outputs = []
    previous = 0
    for timestamp, active, reset in samples:
        outputs.append(
            interpreter.evaluate(
                {"Input": active, "Reset": reset},
                step_seconds=timestamp - previous,
            )
        )
        previous = timestamp

    assert [(row["Elapsed"], row["Passed"]) for row in outputs] == [
        (0.0, False),
        (1.0, False),
        (3.0, True),
        (0.0, False),
        (1.0, False),
        (3.0, True),
        (0.0, False),
        (0.0, False),
    ]


def test_trim_and_respond_matches_independent_oce_golden_trace() -> None:
    graph = ControlGraph(
        name="TrimAndRespond",
        blocks=[
            _block("Requests", BlockKind.NUMERIC_INPUT, default=0.0),
            _block("DeviceOn", BlockKind.BOOLEAN_INPUT, default=False),
            _block(
                "Reset",
                BlockKind.TRIM_AND_RESPOND,
                initial_setpoint=10.0,
                minimum_setpoint=0.0,
                maximum_setpoint=20.0,
                delay_seconds=600.0,
                sample_period_seconds=120.0,
                ignored_requests=2.0,
                trim_amount=0.1,
                respond_amount=-0.2,
                maximum_response=-0.6,
                hold_enabled=False,
            ),
            _block("Setpoint", BlockKind.NUMERIC_OUTPUT),
        ],
        links=[
            Link(source="Requests", target="Reset", target_slot="request_count"),
            Link(source="DeviceOn", target="Reset", target_slot="device_on"),
            Link(source="Reset", target="Setpoint", target_slot="in"),
        ],
    )
    interpreter = GraphInterpreter(graph)
    actual = []
    for index, timestamp in enumerate(range(0, 1321, 60)):
        requests = 6.0 if 840 <= timestamp < 1080 else 3.0 if 720 <= timestamp < 840 else 0.0
        device_on = not (1080 <= timestamp < 1260)
        values = interpreter.evaluate(
            {"Requests": requests, "DeviceOn": device_on},
            step_seconds=0.0 if index == 0 else 60.0,
        )
        actual.append(values["Setpoint"])

    # Pinned Open Control Engine golden-generator fixture:
    # G36/trim_and_respond_have_hol_false/setpoint.csv.
    assert actual == [
        10.0,
        10.0,
        10.0,
        10.0,
        10.0,
        10.0,
        10.0,
        10.0,
        10.0,
        10.0,
        10.0,
        10.0,
        9.9,
        9.9,
        9.4,
        9.4,
        8.9,
        8.9,
        10.0,
        10.0,
        10.0,
        10.0,
        10.0,
    ]


def test_trim_and_respond_hold_matches_expanded_oce_source_trace() -> None:
    graph = ControlGraph(
        name="TrimAndRespondHold",
        blocks=[
            _block("Requests", BlockKind.NUMERIC_INPUT, default=0.0),
            _block("DeviceOn", BlockKind.BOOLEAN_INPUT, default=False),
            _block("Hold", BlockKind.BOOLEAN_INPUT, default=False),
            _block(
                "Reset",
                BlockKind.TRIM_AND_RESPOND_HOLD,
                initial_setpoint=10.0,
                minimum_setpoint=0.0,
                maximum_setpoint=20.0,
                delay_seconds=0.0,
                sample_period_seconds=10.0,
                ignored_requests=2.0,
                trim_amount=0.1,
                respond_amount=-0.2,
                maximum_response=-0.6,
                hold_enabled=True,
                hold_duration_seconds=25.0,
            ),
            _block("Setpoint", BlockKind.NUMERIC_OUTPUT),
        ],
        links=[
            Link(source="Requests", target="Reset", target_slot="request_count"),
            Link(source="DeviceOn", target="Reset", target_slot="device_on"),
            Link(source="Hold", target="Reset", target_slot="hold"),
            Link(source="Reset", target="Setpoint", target_slot="in"),
        ],
    )
    interpreter = GraphInterpreter(graph)
    actual = []
    for index, timestamp in enumerate(range(0, 81, 5)):
        values = interpreter.evaluate(
            {
                "Requests": 0.0,
                "DeviceOn": True,
                "Hold": 25 <= timestamp < 35,
            },
            step_seconds=0.0 if index == 0 else 5.0,
        )
        actual.append(values["Setpoint"])

    # Independently generated by executing the expanded, parameter-bound pinned
    # TrimAndRespond.mo CXF through Open Control Engine (44 primitive blocks).
    assert actual == [
        10.0,
        10.0,
        10.1,
        10.1,
        10.2,
        10.2,
        10.2,
        10.2,
        10.2,
        10.2,
        10.299999999999999,
        10.299999999999999,
        10.399999999999999,
        10.399999999999999,
        10.499999999999998,
        10.499999999999998,
        10.599999999999998,
    ]


def test_true_false_hold_matches_independent_oce_golden_trace() -> None:
    graph = ControlGraph(
        name="TrueFalseHold",
        blocks=[
            _block("Input", BlockKind.BOOLEAN_INPUT, default=False),
            _block(
                "Hold",
                BlockKind.BOOLEAN_TRUE_FALSE_HOLD,
                true_hold_seconds=300.0,
                false_hold_seconds=300.0,
            ),
            _block("Output", BlockKind.BOOLEAN_OUTPUT),
        ],
        links=[
            Link(source="Input", target="Hold", target_slot="in"),
            Link(source="Hold", target="Output", target_slot="in"),
        ],
    )
    interpreter = GraphInterpreter(graph)
    times = [0.0, 100.0, 250.0, 400.0, 700.0]
    inputs = [True, False, True, False, True]
    actual = []
    for index, (timestamp, active) in enumerate(zip(times, inputs, strict=True)):
        actual.append(
            interpreter.evaluate(
                {"Input": active},
                step_seconds=0.0 if index == 0 else timestamp - times[index - 1],
            )["Output"]
        )

    # Pinned Open Control Engine CDL.Logical.TrueFalseHold golden vector.
    assert actual == [True, True, True, False, True]


def test_clear_dominant_set_reset_latch_matches_cdl_edges() -> None:
    graph = ControlGraph(
        name="SetResetLatch",
        blocks=[
            _block("Set", BlockKind.BOOLEAN_INPUT, default=False),
            _block("Clear", BlockKind.BOOLEAN_INPUT, default=False),
            _block("Latch", BlockKind.BOOLEAN_SET_RESET),
            _block("Output", BlockKind.BOOLEAN_OUTPUT),
        ],
        links=[
            Link(source="Set", target="Latch", target_slot="set"),
            Link(source="Clear", target="Latch", target_slot="clear"),
            Link(source="Latch", target="Output", target_slot="in"),
        ],
    )
    interpreter = GraphInterpreter(graph)

    assert interpreter.evaluate({"Set": False, "Clear": False})["Output"] is False
    assert interpreter.evaluate({"Set": True, "Clear": False})["Output"] is True
    assert interpreter.evaluate({"Set": False, "Clear": False})["Output"] is True
    assert interpreter.evaluate({"Set": True, "Clear": True})["Output"] is False
    assert interpreter.evaluate({"Set": True, "Clear": False})["Output"] is False
    interpreter.evaluate({"Set": False, "Clear": False})
    assert interpreter.evaluate({"Set": True, "Clear": False})["Output"] is True


def test_hysteresis_uses_strict_high_and_inclusive_low_thresholds() -> None:
    graph = ControlGraph(
        name="Hysteresis",
        blocks=[
            _block("Input", BlockKind.NUMERIC_INPUT, default=0.0),
            _block(
                "Hysteresis",
                BlockKind.HYSTERESIS,
                u_low=1.0,
                u_high=2.0,
                initial=False,
            ),
            _block("Output", BlockKind.BOOLEAN_OUTPUT),
        ],
        links=[
            Link(source="Input", target="Hysteresis", target_slot="in"),
            Link(source="Hysteresis", target="Output", target_slot="in"),
        ],
    )
    interpreter = GraphInterpreter(graph)

    assert interpreter.evaluate({"Input": 2.0})["Output"] is False
    assert interpreter.evaluate({"Input": 2.01})["Output"] is True
    assert interpreter.evaluate({"Input": 1.0})["Output"] is True
    assert interpreter.evaluate({"Input": 0.99})["Output"] is False


def test_timer_exposes_elapsed_and_passed_outputs() -> None:
    graph = ControlGraph(
        name="MultiOutputTimer",
        blocks=[
            _block("Enable", BlockKind.BOOLEAN_INPUT, default=False),
            _block("Timer", BlockKind.TIMER, threshold_seconds=2.0),
            _block("Elapsed", BlockKind.NUMERIC_OUTPUT),
            _block("Passed", BlockKind.BOOLEAN_OUTPUT),
        ],
        links=[
            Link(source="Enable", target="Timer", target_slot="in"),
            Link(source="Timer", source_slot="elapsed", target="Elapsed", target_slot="in"),
            Link(source="Timer", source_slot="passed", target="Passed", target_slot="in"),
        ],
    )
    interpreter = GraphInterpreter(graph)

    rising = interpreter.evaluate({"Enable": True}, step_seconds=0.0)
    one_second = interpreter.evaluate({"Enable": True}, step_seconds=1.0)
    two_seconds = interpreter.evaluate({"Enable": True}, step_seconds=1.0)
    falling = interpreter.evaluate({"Enable": False}, step_seconds=0.0)

    assert (rising["Elapsed"], rising["Passed"]) == (0.0, False)
    assert (one_second["Elapsed"], one_second["Passed"]) == (1.0, False)
    assert (two_seconds["Elapsed"], two_seconds["Passed"]) == (2.0, True)
    assert (falling["Elapsed"], falling["Passed"]) == (0.0, False)


def test_reset_block_interpolates_and_clamps() -> None:
    graph = ControlGraph(
        name="LinearReset",
        blocks=[
            _block("Input", BlockKind.NUMERIC_INPUT, default=0.0),
            _block("InLow", BlockKind.NUMERIC_CONST, value=0.0),
            _block("InHigh", BlockKind.NUMERIC_CONST, value=10.0),
            _block("OutLow", BlockKind.NUMERIC_CONST, value=55.0),
            _block("OutHigh", BlockKind.NUMERIC_CONST, value=65.0),
            _block("Reset", BlockKind.RESET),
            _block("Output", BlockKind.NUMERIC_OUTPUT),
        ],
        links=[
            Link(source="Input", target="Reset", target_slot="in"),
            Link(source="InLow", target="Reset", target_slot="input_low"),
            Link(source="InHigh", target="Reset", target_slot="input_high"),
            Link(source="OutLow", target="Reset", target_slot="output_low"),
            Link(source="OutHigh", target="Reset", target_slot="output_high"),
            Link(source="Reset", target="Output", target_slot="in"),
        ],
    )
    interpreter = GraphInterpreter(graph)

    assert interpreter.evaluate({"Input": 5.0})["Output"] == 60.0
    assert interpreter.evaluate({"Input": 20.0})["Output"] == 65.0


def test_pi_loop_is_stateful_bounded_and_lowers_to_loop_point(tmp_path: Path) -> None:
    graph = ControlGraph(
        name="DuctStaticPiLoop",
        blocks=[
            _block("Enable", BlockKind.BOOLEAN_INPUT, default=False),
            _block("Pressure", BlockKind.NUMERIC_INPUT, default=0.0),
            _block("PressureSetpoint", BlockKind.NUMERIC_INPUT, default=1.5),
            _block("DirectAction", BlockKind.BOOLEAN_CONST, value=False),
            _block(
                "PressureLoop",
                BlockKind.PI_LOOP,
                proportional_constant=20.0,
                integral_constant=1.0,
                output_min=0.0,
                output_max=100.0,
                bias=0.0,
            ),
            _block("SpeedCommand", BlockKind.NUMERIC_OUTPUT),
        ],
        links=[
            Link(source="Enable", target="PressureLoop", target_slot="enable"),
            Link(
                source="Pressure",
                target="PressureLoop",
                target_slot="controlled_variable",
            ),
            Link(
                source="PressureSetpoint",
                target="PressureLoop",
                target_slot="setpoint",
            ),
            Link(source="DirectAction", target="PressureLoop", target_slot="direct"),
            Link(source="PressureLoop", target="SpeedCommand", target_slot="in"),
        ],
    )
    interpreter = GraphInterpreter(graph)

    assert (
        interpreter.evaluate({"Enable": False, "Pressure": 1.0, "PressureSetpoint": 1.5})[
            "SpeedCommand"
        ]
        == 0.0
    )
    assert (
        interpreter.evaluate({"Enable": True, "Pressure": 1.0, "PressureSetpoint": 1.5})[
            "SpeedCommand"
        ]
        == 10.5
    )
    assert (
        interpreter.evaluate({"Enable": True, "Pressure": 1.0, "PressureSetpoint": 1.5})[
            "SpeedCommand"
        ]
        == 11.0
    )

    destination = NiagaraCompiler().compile(graph, tmp_path / "pi-loop.bog")
    with zipfile.ZipFile(destination) as archive:
        xml = archive.read("file.xml")
    assert b"kitControl:LoopPoint" in xml
    assert b'proportionalConstant" f="L" t="b:Double" v="20.0"' in xml
    assert b'integralConstant" f="L" t="b:Double" v="1.0"' in xml
    assert b"conv:StatusBooleanToFrozenEnum" in xml


def test_pid_with_reset_matches_pinned_oce_recurrence_and_fails_closed_for_niagara(
    tmp_path: Path,
) -> None:
    graph = ControlGraph(
        name="PidWithResetOracle",
        blocks=[
            _block("Setpoint", BlockKind.NUMERIC_INPUT, default=0.0),
            _block("Measurement", BlockKind.NUMERIC_INPUT, default=0.0),
            _block("Trigger", BlockKind.BOOLEAN_INPUT, default=False),
            _block(
                "Controller",
                BlockKind.PID_WITH_RESET,
                controller_type="PI",
                k=0.37,
                ti=0.3,
                ni=0.9,
                xi_start=0.11,
                y_reset=0.275,
                y_min=-0.35,
                y_max=0.45,
            ),
            _block("Output", BlockKind.NUMERIC_OUTPUT),
        ],
        links=[
            Link(source="Setpoint", target="Controller", target_slot="setpoint"),
            Link(source="Measurement", target="Controller", target_slot="measurement"),
            Link(source="Trigger", target="Controller", target_slot="trigger"),
            Link(source="Controller", target="Output", target_slot="in"),
        ],
    )
    setpoints = [0.2, 0.22, 0.95, 0.18, 0.18, -1.38, 1.1, -0.4, -0.4, 0.025]
    triggers = [False, False, False, True, True, False, False, True, True, False]
    expected = [
        0.184,
        0.19140000000000001,
        0.45,
        0.3065913580246914,
        0.275,
        -0.2799999999999999,
        0.45,
        0.041622222222222394,
        0.275,
        0.3829166666666667,
    ]
    interpreter = GraphInterpreter(graph)

    observed = [
        interpreter.evaluate(
            {"Setpoint": setpoint, "Measurement": 0.0, "Trigger": trigger},
            step_seconds=0.0 if index == 0 else 0.1,
        )["Output"]
        for index, (setpoint, trigger) in enumerate(zip(setpoints, triggers, strict=True))
    ]

    assert observed == pytest.approx(expected, rel=0.0, abs=5e-16)
    with pytest.raises(ValueError, match="pid_with_reset"):
        NiagaraCompiler().compile(graph, tmp_path / "not-qualified.bog")


def test_boolean_assert_warning_emits_every_false_evaluation_and_clears_per_step() -> None:
    graph = ControlGraph(
        name="AssertWarning",
        blocks=[
            _block("Condition", BlockKind.BOOLEAN_INPUT, default=True),
            _block(
                "Assertion",
                BlockKind.BOOLEAN_ASSERT_WARNING,
                message="Airflow sensor should be calibrated.",
                severity="warning",
                repeat_while_false=True,
                semantic_contract="CDL.Utilities.Assert",
            ),
        ],
        links=[Link(source="Condition", target="Assertion", target_slot="condition")],
    )
    interpreter = GraphInterpreter(graph)

    assert interpreter.evaluate({"Condition": True})["Assertion"] is True
    assert interpreter.assert_events == []
    assert interpreter.evaluate({"Condition": False})["Assertion"] is False
    assert interpreter.assert_events == [
        {
            "block_id": "Assertion",
            "message": "Airflow sensor should be calibrated.",
            "level": "warning",
            "time_seconds": 2.0,
        }
    ]
    interpreter.evaluate({"Condition": False})
    assert len(interpreter.assert_events) == 1
    assert interpreter.assert_events[0]["time_seconds"] == 3.0
    interpreter.evaluate({"Condition": True})
    assert interpreter.assert_events == []


@pytest.mark.parametrize(
    ("pre_u_start", "inputs", "expected"),
    [
        (
            False,
            [False, True, True, False, False, True, False],
            [False, False, False, True, False, False, True],
        ),
        (True, [False, False, True, False], [True, False, False, True]),
    ],
)
def test_boolean_falling_edge_preserves_initial_pre_u_seed(
    pre_u_start: bool,
    inputs: list[bool],
    expected: list[bool],
) -> None:
    graph = ControlGraph(
        name="FallingEdge",
        blocks=[
            _block("Input", BlockKind.BOOLEAN_INPUT, default=False),
            _block(
                "Edge",
                BlockKind.BOOLEAN_FALLING_EDGE,
                pre_u_start=pre_u_start,
                semantic_contract="CDL.Logical.FallingEdge",
            ),
        ],
        links=[Link(source="Input", target="Edge", target_slot="in")],
    )
    interpreter = GraphInterpreter(graph)

    assert [interpreter.evaluate({"Input": value})["Edge"] for value in inputs] == expected
