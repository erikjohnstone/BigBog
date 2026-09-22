"""N6 / docs/decisions/007: the Python kernel ports equal the Java kernels.

The ports run against the OCE goldens and the IR interpreter on every install;
when a JDK is present they also run row by row against the Java kernels through
the sidecar, and any difference fails.
"""

from __future__ import annotations

import math
import random

import pytest

from bactalk.domain import Block, BlockKind, ControlGraph, Link
from bactalk.niagara.shadow.equivalence import KERNEL_CASES, check_kernel_equivalence, random_rows
from bactalk.niagara.shadow.kernels import KERNEL_NAMES, build_kernel, format_row
from bactalk.niagara.shadow.sidecar import KernelSidecar, sidecar_available
from bactalk.simulator import GraphInterpreter

pytestmark = [pytest.mark.native_bog]


def test_pid_with_reset_port_matches_the_oce_golden() -> None:
    rows = [
        (0.0, 0.2, 0.0, 0.0, 0.184),
        (0.1, 0.22, 0.0, 0.0, 0.19140000000000001),
        (0.2, 0.95, 0.0, 0.0, 0.45),
        (0.30000000000000004, 0.18, 0.0, 1.0, 0.3065913580246914),
        (0.4, 0.18, 0.0, 1.0, 0.275),
        (0.5, -1.38, 0.0, 0.0, -0.2799999999999999),
        (0.6000000000000001, 1.1, 0.0, 0.0, 0.45),
        (0.7000000000000001, -0.4, 0.0, 1.0, 0.041622222222222394),
        (0.8, -0.4, 0.0, 1.0, 0.275),
        (0.9, 0.025, 0.0, 0.0, 0.3829166666666667),
    ]
    kernel = build_kernel(
        "PidWithReset",
        {
            "controllerType": "PI",
            "reverseActing": True,
            "k": 0.37,
            "ti": 0.3,
            "td": 0.1,
            "r": 1.0,
            "ni": 0.9,
            "nd": 10.0,
            "yMin": -0.35,
            "yMax": 0.45,
            "xiStart": 0.11,
            "ydStart": 0.0,
            "yReset": 0.275,
        },
    )
    for t, sp, meas, trigger, expected in rows:
        (actual,) = kernel.step(t, sp, meas, bool(trigger))
        assert math.isclose(actual, expected, rel_tol=0.0, abs_tol=5e-16)


def test_trim_and_respond_port_matches_the_oce_golden() -> None:
    expected = [10.0] * 12 + [9.9, 9.9, 9.4, 9.4, 8.9, 8.9] + [10.0] * 5
    kernel = build_kernel(
        "TrimAndRespond",
        {
            "initialSetpoint": 10.0,
            "minimumSetpoint": 0.0,
            "maximumSetpoint": 20.0,
            "delaySeconds": 600.0,
            "samplePeriodSeconds": 120.0,
            "ignoredRequests": 2.0,
            "trimAmount": 0.1,
            "respondAmount": -0.2,
            "maximumResponse": -0.6,
        },
    )
    actual = []
    for timestamp in range(0, 1321, 60):
        requests = 6.0 if 840 <= timestamp < 1080 else 3.0 if 720 <= timestamp < 840 else 0.0
        device_on = not (1080 <= timestamp < 1260)
        actual.append(kernel.step(float(timestamp), requests, device_on)[0])
    assert actual == expected


def test_timer_and_discrete_ports_match_the_independent_goldens() -> None:
    timer = build_kernel("Timer", {"thresholdSeconds": 1.0})
    rows = [
        (0.0, True),
        (0.5, True),
        (1.0, True),
        (1.0, True),
        (1.5, False),
        (2.0, True),
        (2.5, True),
    ]
    assert [format_row(timer.step(t, v)) for t, v in rows] == [
        "0.0,false",
        "0.5,false",
        "1.0,true",
        "1.0,true",
        "0.0,false",
        "0.0,false",
        "0.5,false",
    ]
    unit = build_kernel("UnitDelay", {"samplePeriodSeconds": 2.0, "initial": -1.0})
    assert [unit.step(t, v)[0] for t, v in [(0, 10), (1, 11), (2, 20), (3, 30), (4, 40)]] == [
        -1.0,
        -1.0,
        10.0,
        10.0,
        20.0,
    ]
    hold = build_kernel("FirstOrderHold", {"samplePeriodSeconds": 2.0})
    assert [hold.step(t, v)[0] for t, v in [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4), (5, 5)]] == [
        0.0,
        0.0,
        0.0,
        1.0,
        2.0,
        3.0,
    ]


def test_same_instant_re_execution_samples_the_last_input() -> None:
    """A second step at a sample instant (an event-driven re-execution) samples the last value."""

    unit = build_kernel("UnitDelay", {"samplePeriodSeconds": 2.0, "initial": -1.0})
    unit.step(0.0, 5.0)
    unit.step(0.0, 7.0)  # same instant, fresher input
    assert unit.step(2.0, 9.0)[0] == 7.0
    hold = build_kernel("FirstOrderHold", {"samplePeriodSeconds": 2.0})
    hold.step(0.0, 1.0)
    hold.step(0.0, 3.0)
    assert hold.step(2.0, 4.0)[0] == 3.0
    average = build_kernel("MovingAverage", {"windowSeconds": 300.0})
    for t in range(0, 301):
        (value,) = average.step(float(t), 12.0)
    assert math.isclose(value, 12.0, rel_tol=1e-9), (
        "a window longer than 64 steps is no longer truncated"
    )


# --- differential against the IR interpreter (the same cases as the Java kernels) ------


def _graph(kind: BlockKind, config: dict, inputs: dict[str, BlockKind]) -> ControlGraph:
    blocks = [
        Block(
            id=f"in_{name}",
            kind=source_kind,
            label=name,
            config={"default": 0.0 if source_kind is BlockKind.NUMERIC_INPUT else False},
        )
        for name, source_kind in inputs.items()
    ]
    blocks.append(Block(id="k", kind=kind, label="kernel", config=config))
    links = [Link(source=f"in_{name}", target="k", target_slot=name) for name in inputs]
    return ControlGraph(name="KERNEL", blocks=blocks, links=links)


_IR_CASES = [
    (
        BlockKind.BOOLEAN_DELAY,
        {
            "on_delay_seconds": 7.0,
            "delay_on_init": False,
            "semantic_contract": "CDL.Logical.TrueDelay",
        },
        {"in": BlockKind.BOOLEAN_INPUT},
        "TrueDelay",
        {"delaySeconds": 7.0, "delayOnInit": False},
        ("out",),
    ),
    (
        BlockKind.TIMER,
        {"threshold_seconds": 9.0, "semantic_contract": "CDL.Logical.Timer"},
        {"in": BlockKind.BOOLEAN_INPUT},
        "Timer",
        {"thresholdSeconds": 9.0},
        ("elapsed", "passed"),
    ),
    (
        BlockKind.TIMER_WITH_RESET,
        {"threshold_seconds": 9.0},
        {"in": BlockKind.BOOLEAN_INPUT, "reset": BlockKind.BOOLEAN_INPUT},
        "TimerWithReset",
        {"thresholdSeconds": 9.0},
        ("elapsed", "passed"),
    ),
    (
        BlockKind.TIMER_ACCUMULATING,
        {"threshold_seconds": 9.0},
        {"in": BlockKind.BOOLEAN_INPUT, "reset": BlockKind.BOOLEAN_INPUT},
        "TimerAccumulating",
        {"thresholdSeconds": 9.0},
        ("elapsed", "passed"),
    ),
    (
        BlockKind.BOOLEAN_TRUE_FALSE_HOLD,
        {"true_hold_seconds": 6.0, "false_hold_seconds": 3.0},
        {"in": BlockKind.BOOLEAN_INPUT},
        "TrueFalseHold",
        {"trueHoldSeconds": 6.0, "falseHoldSeconds": 3.0},
        ("out",),
    ),
    (
        BlockKind.BOOLEAN_PRE_HOST_TICK,
        {
            "initial": False,
            "semantic_contract": "CDL.Logical.Pre",
            "execution_profile": "host_tick_v1",
        },
        {"in": BlockKind.BOOLEAN_INPUT},
        "Pre",
        {"initial": False},
        ("out",),
    ),
    (
        BlockKind.NUMERIC_UNIT_DELAY,
        {
            "sample_period_seconds": 4.0,
            "initial": 1.5,
            "semantic_contract": "CDL.Discrete.UnitDelay",
        },
        {"in": BlockKind.NUMERIC_INPUT},
        "UnitDelay",
        {"samplePeriodSeconds": 4.0, "initial": 1.5},
        ("out",),
    ),
    (
        BlockKind.NUMERIC_FIRST_ORDER_HOLD,
        {"sample_period_seconds": 4.0, "semantic_contract": "CDL.Discrete.FirstOrderHold"},
        {"in": BlockKind.NUMERIC_INPUT},
        "FirstOrderHold",
        {"samplePeriodSeconds": 4.0},
        ("out",),
    ),
    (
        BlockKind.MOVING_AVERAGE,
        {"window_seconds": 10.0, "semantic_contract": "CDL.Reals.MovingAverage"},
        {"in": BlockKind.NUMERIC_INPUT},
        "MovingAverage",
        {"windowSeconds": 10.0},
        ("out",),
    ),
    (
        BlockKind.BOOLEAN_INITIALIZATION,
        {
            "initial": True,
            "semantic_contract": "Buildings.Templates.Plants.Controls.Utilities.Initialization",
        },
        {"in": BlockKind.BOOLEAN_INPUT},
        "BooleanInitialization",
        {"initial": True},
        ("out",),
    ),
    (
        BlockKind.NUMERIC_CHANGED,
        {"initial": 0.0},
        {"in": BlockKind.NUMERIC_INPUT},
        "NumericChange",
        {"mode": "changed", "initial": 0.0},
        ("out",),
    ),
    (
        BlockKind.NUMERIC_INCREASED,
        {"initial": 0.0},
        {"in": BlockKind.NUMERIC_INPUT},
        "NumericChange",
        {"mode": "increased", "initial": 0.0},
        ("out",),
    ),
    (
        BlockKind.NUMERIC_DECREASED,
        {"initial": 0.0},
        {"in": BlockKind.NUMERIC_INPUT},
        "NumericChange",
        {"mode": "decreased", "initial": 0.0},
        ("out",),
    ),
]


@pytest.mark.parametrize("case", _IR_CASES, ids=[f"{c[0].value}-{c[3]}" for c in _IR_CASES])
@pytest.mark.parametrize("seed", [1, 2])
def test_python_port_matches_the_ir_interpreter(case, seed: int) -> None:
    kind, config, inputs, kernel_name, params, outputs = case
    rng = random.Random(seed * 1000 + hash(kind.value) % 1000)
    length = 60
    series: dict[str, list[float | bool]] = {}
    for name, source_kind in inputs.items():
        if source_kind is BlockKind.BOOLEAN_INPUT:
            value = rng.random() < 0.5
            walk = []
            for _ in range(length):
                if rng.random() < 0.2:
                    value = not value
                walk.append(value)
            series[name] = walk
        else:
            value = rng.uniform(-5, 5)
            walk = []
            for _ in range(length):
                value += rng.uniform(-1.0, 1.0)
                walk.append(round(value, 3))
            series[name] = walk
    steps = [rng.choice([0.5, 1.0, 1.0, 2.0, 3.0]) for _ in range(length)]
    interpreter = GraphInterpreter(_graph(kind, config, inputs))
    kernel = build_kernel(kernel_name, params)
    for index in range(length):
        values = interpreter.evaluate(
            {f"in_{name}": series[name][index] for name in inputs}, step_seconds=steps[index]
        )
        actual = kernel.step(interpreter.time, *(series[name][index] for name in inputs))
        for slot, got in zip(outputs, actual, strict=True):
            wanted = values[f"k.{slot}"]
            if isinstance(wanted, bool):
                assert got == wanted, (kernel_name, slot, index)
            else:
                assert math.isclose(float(got), float(wanted), rel_tol=1e-9, abs_tol=1e-9), (
                    kernel_name,
                    slot,
                    index,
                )


def test_every_kernel_has_a_port_and_an_equivalence_case() -> None:
    assert set(KERNEL_NAMES) == {case[0] for case in KERNEL_CASES}
    for name in KERNEL_NAMES:
        params = next(case[1] for case in KERNEL_CASES if case[0] == name)
        assert build_kernel(name, dict(params)) is not None
    with pytest.raises(ValueError, match="unknown kernel"):
        build_kernel("Nope", {})


# --- Java kernels versus Python ports (needs a JDK; CI has one) ------------------------


def test_python_ports_equal_the_java_kernels_row_by_row() -> None:
    """S-MODULE-5."""

    outcome = check_kernel_equivalence(seeds=(1, 2))
    assert outcome.skipped is None, outcome.skipped
    assert outcome.mismatches == [], outcome.summary()
    assert outcome.checked >= len(KERNEL_CASES) * 2 * 80


def test_sidecar_session_serves_many_kernels_at_once() -> None:
    assert sidecar_available()
    with KernelSidecar() as sidecar:
        timer = sidecar.open("Timer", {"thresholdSeconds": 1.0})
        pre = sidecar.open("Pre", {"initial": False})
        assert sidecar.step(timer, 0.0, [True]) == (0.0, False)
        assert sidecar.step(pre, 0.0, [True]) == (False,)
        assert sidecar.step(timer, 1.0, [True]) == (1.0, True)
        assert sidecar.step(pre, 1.0, [False]) == (True,)
        sidecar.close_kernel(timer)
        rows = random_rows(("n",), seed=7, length=5)
        port = build_kernel("MovingAverage", {"windowSeconds": 4.0})
        ident = sidecar.open("MovingAverage", {"windowSeconds": 4.0})
        for t, inputs in rows:
            assert sidecar.step(ident, t, inputs) == port.step(t, *inputs)
