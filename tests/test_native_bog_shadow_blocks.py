"""N6 contract: every stock block behaves as docs/niagara-semantics.md says.

Each test's docstring cites the assumption ids it exercises; a test at the end
checks that the document and the tests cite exactly the same set of ids.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from bactalk.niagara.shadow import (
    DEFAULT_POLICY,
    PropagationLoopError,
    ShadowRuntime,
    Status,
    StatusValue,
)
from bactalk.niagara.shadow.blocks import REGISTRY, ModuleBlock
from bactalk.niagara.shadow.builder import (
    BogBuilder,
    boolean,
    double,
    raw,
    rel_time,
    status_boolean,
    status_numeric,
    string,
)
from bactalk.niagara.shadow.loader import ShadowLoadError

pytestmark = [pytest.mark.minimal, pytest.mark.native_bog]

NUM = "c:NumericWritable"
BOOL = "c:BooleanWritable"


def _runtime(builder: BogBuilder, policy=DEFAULT_POLICY, *, start: bool = True) -> ShadowRuntime:
    runtime = ShadowRuntime(builder.build(), policy=policy, kernel_backend="python")
    if start:
        runtime.start()
    return runtime


def _inputs(builder: BogBuilder, **points: float | bool) -> None:
    for name, value in points.items():
        if isinstance(value, bool):
            builder.add("Inputs", name, BOOL, [status_boolean("fallback", value)])
        else:
            builder.add("Inputs", name, NUM, [status_numeric("fallback", value)])


def _value(runtime: ShadowRuntime, path: str, slot: str = "out") -> float | bool:
    return runtime.read(path, slot).value


def _status(runtime: ShadowRuntime, path: str, slot: str = "out") -> Status:
    return runtime.read(path, slot).status


# --- status ---------------------------------------------------------------------------


def test_status_flags_and_validity() -> None:
    """S-STATUS-1, S-STATUS-2."""

    assert [flag.value for flag in Status if flag] == [1, 2, 4, 8, 16, 32, 64, 128]
    assert Status.OK.valid and Status.ALARM.valid and Status.OVERRIDDEN.valid
    for flag in (Status.DISABLED, Status.FAULT, Status.DOWN, Status.STALE, Status.NULL):
        assert not flag.valid
    assert (Status.NULL | Status.ALARM).render() == "{alarm,null}"


def test_unlinked_inputs_are_null_and_ignored() -> None:
    """S-STATUS-3."""

    builder = BogBuilder("P")
    _inputs(builder, a=2.5)
    builder.add("Logic", "add", "kitControl:Add")
    builder.link("Inputs/a", "out", "Logic/add", "inA")
    runtime = _runtime(builder)
    assert runtime.read("/P/Logic/add") == StatusValue(2.5, Status.OK)
    assert runtime.blocks["/P/Logic/add"].inputs["inB"].is_null


def test_propagate_flags_default_none_and_policy_override() -> None:
    """S-STATUS-4."""

    builder = BogBuilder("P")
    _inputs(builder, a=1.0, b=2.0)
    builder.add("Logic", "add", "kitControl:Add")
    builder.link("Inputs/a", "out", "Logic/add", "inA")
    builder.link("Inputs/b", "out", "Logic/add", "inB")
    runtime = _runtime(builder)
    runtime.write_point("/P/Inputs/a", 1.0, status=Status.FAULT)
    assert runtime.read("/P/Logic/add") == StatusValue(3.0, Status.OK)
    runtime = _runtime(
        builder, DEFAULT_POLICY.variant("flags", propagate_flags=Status.FAULT | Status.DOWN)
    )
    runtime.write_point("/P/Inputs/a", 1.0, status=Status.FAULT | Status.ALARM)
    assert runtime.read("/P/Logic/add") == StatusValue(3.0, Status.FAULT)


def test_null_output_keeps_its_last_value() -> None:
    """S-STATUS-5."""

    builder = BogBuilder("P")
    _inputs(builder, a=True)
    builder.add("Logic", "not", "kitControl:Not")
    builder.link("Inputs/a", "out", "Logic/not", "in")
    runtime = _runtime(builder)
    assert runtime.read("/P/Logic/not") == StatusValue(False, Status.OK)
    runtime.set_input("/P/Logic/not", "in", StatusValue(True, Status.NULL))
    assert runtime.read("/P/Logic/not") == StatusValue(False, Status.NULL)


def test_outputs_start_at_the_type_zero_with_ok_status() -> None:
    """S-STATUS-6."""

    builder = BogBuilder("P")
    builder.add("Logic", "gt", "kitControl:GreaterThan")
    builder.add("Logic", "add", "kitControl:Add")
    runtime = _runtime(builder, start=False)
    assert runtime.read("/P/Logic/gt") == StatusValue(False, Status.OK)
    assert runtime.read("/P/Logic/add") == StatusValue(0.0, Status.OK)
    runtime.start()
    assert runtime.read("/P/Logic/gt").is_null and runtime.read("/P/Logic/add").is_null


# --- math, comparison, logic -----------------------------------------------------------


@pytest.mark.parametrize(
    ("type_name", "values", "expected"),
    [
        ("kitControl:Add", (1.0, 2.0, 4.0), 7.0),
        ("kitControl:Multiply", (2.0, 3.0, 4.0), 24.0),
        ("kitControl:Minimum", (5.0, -1.0, 3.0), -1.0),
        ("kitControl:Maximum", (5.0, -1.0, 3.0), 5.0),
        ("kitControl:Average", (1.0, 2.0, 6.0), 3.0),
    ],
)
def test_math_combines_the_non_null_inputs(
    type_name: str, values: tuple[float, ...], expected: float
) -> None:
    """S-MATH-1."""

    builder = BogBuilder("P")
    _inputs(builder, a=values[0], b=values[1], c=values[2])
    builder.add("Logic", "m", type_name)
    for slot, name in zip(("inA", "inB", "inD"), ("a", "b", "c"), strict=True):  # inC left null
        builder.link(f"Inputs/{name}", "out", "Logic/m", slot)
    runtime = _runtime(builder)
    assert runtime.read("/P/Logic/m") == StatusValue(expected, Status.OK)
    builder = BogBuilder("P")
    builder.add("Logic", "m", type_name)
    assert _runtime(builder).read("/P/Logic/m").is_null


def test_subtract_and_divide_anchor_on_in_a() -> None:
    """S-MATH-2, S-MATH-3."""

    builder = BogBuilder("P")
    _inputs(builder, a=20.0, b=2.0, c=5.0)
    builder.add("Logic", "sub", "kitControl:Subtract")
    builder.add("Logic", "div", "kitControl:Divide")
    builder.add("Logic", "noAnchor", "kitControl:Subtract")
    builder.add("Logic", "byZero", "kitControl:Divide")
    _inputs(builder, zero=0.0)
    for target in ("sub", "div"):
        builder.link("Inputs/a", "out", f"Logic/{target}", "inA")
        builder.link("Inputs/b", "out", f"Logic/{target}", "inB")
        builder.link("Inputs/c", "out", f"Logic/{target}", "inC")
    builder.link("Inputs/b", "out", "Logic/noAnchor", "inB")
    builder.link("Inputs/a", "out", "Logic/byZero", "inA")
    builder.link("Inputs/zero", "out", "Logic/byZero", "inB")
    runtime = _runtime(builder)
    assert runtime.read("/P/Logic/sub") == StatusValue(13.0, Status.OK)
    assert runtime.read("/P/Logic/div") == StatusValue(2.0, Status.OK)
    assert runtime.read("/P/Logic/noAnchor").is_null
    by_zero = runtime.read("/P/Logic/byZero")
    assert math.isinf(by_zero.value) and by_zero.status == Status.FAULT


@pytest.mark.parametrize(
    ("type_name", "pairs"),
    [
        ("kitControl:GreaterThan", [((2.0, 1.0), True), ((1.0, 1.0), False)]),
        ("kitControl:GreaterThanEqual", [((1.0, 1.0), True), ((0.5, 1.0), False)]),
        ("kitControl:LessThan", [((0.5, 1.0), True), ((1.0, 1.0), False)]),
        ("kitControl:LessThanEqual", [((1.0, 1.0), True), ((2.0, 1.0), False)]),
        ("kitControl:Equal", [((1.0, 1.0), True), ((1.0, 1.0000001), False)]),
        ("kitControl:NotEqual", [((1.0, 2.0), True), ((1.0, 1.0), False)]),
    ],
)
def test_comparisons(type_name: str, pairs) -> None:
    """S-CMP-1, S-CMP-2."""

    builder = BogBuilder("P")
    _inputs(builder, a=0.0, b=0.0)
    builder.add("Logic", "cmp", type_name)
    builder.link("Inputs/a", "out", "Logic/cmp", "inA")
    builder.link("Inputs/b", "out", "Logic/cmp", "inB")
    runtime = _runtime(builder)
    for (a, b), expected in pairs:
        runtime.write_point("/P/Inputs/a", a)
        runtime.write_point("/P/Inputs/b", b)
        assert runtime.read("/P/Logic/cmp") == StatusValue(expected, Status.OK), (a, b)
    runtime.set_input("/P/Logic/cmp", "inB", StatusValue(0.0, Status.NULL))
    assert runtime.read("/P/Logic/cmp").is_null


def test_logic_ignores_null_inputs_and_not_propagates_null() -> None:
    """S-LOGIC-1, S-LOGIC-2, S-LOGIC-3."""

    builder = BogBuilder("P")
    _inputs(builder, a=True, b=False)
    for name in ("and", "or", "xor"):
        builder.add("Logic", name, f"kitControl:{name.capitalize()}")
        builder.link("Inputs/a", "out", f"Logic/{name}", "inA")
        builder.link("Inputs/b", "out", f"Logic/{name}", "inC")
    builder.add("Logic", "not", "kitControl:Not")
    builder.add("Logic", "empty", "kitControl:And")
    runtime = _runtime(builder)
    assert _value(runtime, "/P/Logic/and") is False
    assert _value(runtime, "/P/Logic/or") is True
    assert _value(runtime, "/P/Logic/xor") is True
    runtime.write_point("/P/Inputs/b", True)
    assert _value(runtime, "/P/Logic/and") is True and _value(runtime, "/P/Logic/xor") is False
    assert runtime.read("/P/Logic/not").is_null and runtime.read("/P/Logic/empty").is_null


def test_switches_select_and_null_selector_is_null() -> None:
    """S-SWITCH-1."""

    builder = BogBuilder("P")
    _inputs(builder, sel=True, t=10.0, f=20.0, bt=True, bf=False)
    builder.add("Logic", "ns", "kitControl:NumericSwitch")
    builder.add("Logic", "bs", "kitControl:BooleanSwitch")
    builder.link("Inputs/sel", "out", "Logic/ns", "inSwitch")
    builder.link("Inputs/t", "out", "Logic/ns", "inTrue")
    builder.link("Inputs/f", "out", "Logic/ns", "inFalse")
    builder.link("Inputs/sel", "out", "Logic/bs", "inSwitch")
    builder.link("Inputs/bt", "out", "Logic/bs", "inTrue")
    builder.link("Inputs/bf", "out", "Logic/bs", "inFalse")
    runtime = _runtime(builder)
    assert _value(runtime, "/P/Logic/ns") == 10.0 and _value(runtime, "/P/Logic/bs") is True
    runtime.write_point("/P/Inputs/sel", False)
    assert _value(runtime, "/P/Logic/ns") == 20.0 and _value(runtime, "/P/Logic/bs") is False
    runtime.set_input("/P/Logic/ns", "inSwitch", StatusValue(False, Status.NULL))
    assert runtime.read("/P/Logic/ns").is_null
    runtime.set_input("/P/Logic/bs", "inFalse", StatusValue(False, Status.NULL))
    assert runtime.read("/P/Logic/bs").is_null


def test_latches_copy_on_the_rising_clock_edge() -> None:
    """S-LATCH-1, S-LATCH-2."""

    builder = BogBuilder("P")
    _inputs(builder, v=1.5, clk=False)
    builder.add("Logic", "latch", "kitControl:NumericLatch")
    builder.add("Logic", "blatch", "kitControl:BooleanLatch")
    builder.link("Inputs/v", "out", "Logic/latch", "in")
    builder.link("Inputs/clk", "out", "Logic/latch", "clock")
    builder.link("Inputs/clk", "out", "Logic/blatch", "clock")
    runtime = _runtime(builder)
    assert runtime.read("/P/Logic/latch") == StatusValue(0.0, Status.OK)
    runtime.write_point("/P/Inputs/v", 2.5)
    assert _value(runtime, "/P/Logic/latch") == 0.0
    runtime.write_point("/P/Inputs/clk", True)
    assert _value(runtime, "/P/Logic/latch") == 2.5
    runtime.write_point("/P/Inputs/v", 9.0)
    assert _value(runtime, "/P/Logic/latch") == 2.5, "held while the clock stays high"
    runtime.write_point("/P/Inputs/clk", False)
    runtime.write_point("/P/Inputs/clk", True)
    assert _value(runtime, "/P/Logic/latch") == 9.0
    assert runtime.read("/P/Logic/blatch").is_null, "a null in is copied as null"


# --- timed stock blocks -----------------------------------------------------------------


def test_one_shot_pulses_for_pulse_width_and_retriggers() -> None:
    """S-ONESHOT-1, S-ONESHOT-2, S-ONESHOT-3."""

    builder = BogBuilder("P")
    _inputs(builder, a=False)
    builder.add("Logic", "os", "kitControl:OneShot", [rel_time("pulseWidth", 2.0)])
    builder.add("Logic", "policy", "kitControl:OneShot")
    builder.link("Inputs/a", "out", "Logic/os", "in")
    builder.link("Inputs/a", "out", "Logic/policy", "in")
    runtime = _runtime(builder, DEFAULT_POLICY.variant("p", one_shot_pulse_seconds=0.25))
    runtime.write_point("/P/Inputs/a", True)
    assert _value(runtime, "/P/Logic/os") is True and _value(runtime, "/P/Logic/policy") is True
    runtime.advance(0.25)
    assert _value(runtime, "/P/Logic/policy") is False and _value(runtime, "/P/Logic/os") is True
    runtime.advance(1.0)
    runtime.write_point("/P/Inputs/a", False)
    runtime.write_point("/P/Inputs/a", True)  # retrigger at t=1.25
    runtime.advance(1.0)  # t=2.25: the original pulse would have ended at 2.0
    assert _value(runtime, "/P/Logic/os") is True
    runtime.advance(1.0)  # t=3.25 > 1.25 + 2.0
    assert _value(runtime, "/P/Logic/os") is False


def test_boolean_delay_on_off_delays_cancel_and_no_start_pass_through() -> None:
    """S-DELAY-1, S-DELAY-2."""

    builder = BogBuilder("P")
    _inputs(builder, a=True)
    builder.add(
        "Logic",
        "d",
        "kitControl:BooleanDelay",
        [rel_time("onDelay", 10.0), rel_time("offDelay", 4.0)],
    )
    builder.link("Inputs/a", "out", "Logic/d", "in")
    runtime = _runtime(builder)
    assert _value(runtime, "/P/Logic/d") is False, "true at start is delayed, not passed through"
    runtime.advance(9.0)
    assert _value(runtime, "/P/Logic/d") is False
    runtime.advance(1.0)
    assert _value(runtime, "/P/Logic/d") is True
    runtime.write_point("/P/Inputs/a", False)
    runtime.advance(2.0)
    runtime.write_point("/P/Inputs/a", True)  # back before the off delay elapsed: cancelled
    runtime.advance(5.0)
    assert _value(runtime, "/P/Logic/d") is True
    runtime.write_point("/P/Inputs/a", False)
    runtime.advance(4.0)
    assert _value(runtime, "/P/Logic/d") is False


def test_multivibrator_clock_duty_cycle_and_enable() -> None:
    """S-MV-1, S-MV-2, S-MV-3."""

    builder = BogBuilder("P")
    builder.add(
        "Logic",
        "mv",
        "kitControl:MultiVibrator",
        [rel_time("period", 10.0), double("dutyCycle", 30.0)],
    )
    builder.add(
        "Logic",
        "off",
        "kitControl:MultiVibrator",
        [rel_time("period", 10.0), boolean("enabled", False)],
    )
    runtime = _runtime(builder)
    assert _value(runtime, "/P/Logic/mv") is True and _value(runtime, "/P/Logic/off") is False
    runtime.advance(3.0)
    assert _value(runtime, "/P/Logic/mv") is False
    runtime.advance(7.0)
    assert _value(runtime, "/P/Logic/mv") is True
    runtime.advance(5.0)
    assert _value(runtime, "/P/Logic/off") is False
    low = _runtime(builder, DEFAULT_POLICY.variant("low", multivibrator_initial=False))
    assert _value(low, "/P/Logic/mv") is False
    low.advance(7.0)
    assert _value(low, "/P/Logic/mv") is True


def test_tstat_hysteresis_actions_and_null() -> None:
    """S-TSTAT-1, S-TSTAT-2, S-TSTAT-3."""

    builder = BogBuilder("P")
    _inputs(builder, cv=20.0)
    builder.add(
        "Logic",
        "direct",
        "kitControl:Tstat",
        [status_numeric("sp", 21.0), status_numeric("diff", 2.0)],
    )
    builder.add(
        "Logic",
        "reverse",
        "kitControl:Tstat",
        [
            status_numeric("sp", 21.0),
            status_numeric("diff", 2.0),
            raw("action", "reverse", "kitControl:LoopAction"),
        ],
    )
    builder.add(
        "Logic",
        "preset",
        "kitControl:Tstat",
        [status_numeric("sp", 21.0), status_numeric("diff", 2.0), status_boolean("out", True)],
    )
    for name in ("direct", "reverse", "preset"):
        builder.link("Inputs/cv", "out", f"Logic/{name}", "cv")
    runtime = _runtime(builder)
    assert (
        _value(runtime, "/P/Logic/direct") is False and _value(runtime, "/P/Logic/reverse") is True
    )
    assert _value(runtime, "/P/Logic/preset") is False, "20 is at the lower threshold: off"
    runtime.write_point("/P/Inputs/cv", 21.9)
    assert _value(runtime, "/P/Logic/direct") is False, "inside the band it holds"
    runtime.write_point("/P/Inputs/cv", 22.0)
    assert (
        _value(runtime, "/P/Logic/direct") is True and _value(runtime, "/P/Logic/reverse") is False
    )
    runtime.write_point("/P/Inputs/cv", 20.5)
    assert _value(runtime, "/P/Logic/direct") is True
    runtime.set_input("/P/Logic/direct", "cv", StatusValue(20.0, Status.NULL))
    assert runtime.read("/P/Logic/direct").is_null


def test_reset_rescales_and_clamps() -> None:
    """S-RESET-1, S-RESET-2."""

    builder = BogBuilder("P")
    _inputs(builder, a=15.0)
    limits = [
        status_numeric("inputLowLimit", 10.0),
        status_numeric("inputHighLimit", 20.0),
        status_numeric("outputLowLimit", 100.0),
        status_numeric("outputHighLimit", 200.0),
    ]
    builder.add("Logic", "r", "kitControl:Reset", limits)
    builder.add(
        "Logic",
        "flat",
        "kitControl:Reset",
        [
            status_numeric("inputLowLimit", 1.0),
            status_numeric("inputHighLimit", 1.0),
            status_numeric("outputLowLimit", 3.0),
            status_numeric("outputHighLimit", 4.0),
        ],
    )
    builder.add("Logic", "unlinked", "kitControl:Reset", limits)
    builder.link("Inputs/a", "out", "Logic/r", "inA")
    builder.link("Inputs/a", "out", "Logic/flat", "inA")
    runtime = _runtime(builder)
    assert _value(runtime, "/P/Logic/r") == 150.0
    runtime.write_point("/P/Inputs/a", 99.0)
    assert _value(runtime, "/P/Logic/r") == 200.0
    runtime.write_point("/P/Inputs/a", -5.0)
    assert _value(runtime, "/P/Logic/r") == 100.0
    assert runtime.read("/P/Logic/flat") == StatusValue(3.0, Status.FAULT)
    assert runtime.read("/P/Logic/unlinked").is_null


def test_loop_point_pid_on_its_execute_clock() -> None:
    """S-LOOP-1, S-LOOP-2, S-LOOP-3, S-LOOP-4, S-LOOP-5, S-LOOP-6."""

    builder = BogBuilder("P")
    _inputs(builder, en=True, cv=22.0, sp=20.0)
    props = [
        double("proportionalConstant", 2.0),
        double("integralConstant", 1.0),
        double("bias", 10.0),
        double("maximumOutput", 100.0),
        double("minimumOutput", 0.0),
        rel_time("executeTime", 30.0),
    ]
    builder.add("Logic", "direct", "kitControl:LoopPoint", props)
    builder.add(
        "Logic",
        "reverse",
        "kitControl:LoopPoint",
        [*props, raw("loopAction", "reverse", "kitControl:LoopAction")],
    )
    for name in ("direct", "reverse"):
        builder.link("Inputs/en", "out", f"Logic/{name}", "loopEnable")
        builder.link("Inputs/cv", "out", f"Logic/{name}", "controlledVariable")
        builder.link("Inputs/sp", "out", f"Logic/{name}", "setpoint")
    runtime = _runtime(builder)
    # Start: one execution with dt = 0 -> bias + P.
    assert _value(runtime, "/P/Logic/direct") == 14.0
    assert _value(runtime, "/P/Logic/reverse") == 6.0
    runtime.write_point("/P/Inputs/cv", 25.0)
    assert _value(runtime, "/P/Logic/direct") == 14.0, "input changes wait for the execute clock"
    runtime.advance(30.0)
    # e = 5: P = 10, I += Kp*Ki*e*dt/60 = 2*1*5*0.5 = 5 -> 25
    assert math.isclose(_value(runtime, "/P/Logic/direct"), 25.0)
    runtime.write_point("/P/Inputs/cv", 200.0)
    runtime.advance(30.0)
    assert _value(runtime, "/P/Logic/direct") == 100.0, "clamped"
    integral_before = runtime.blocks["/P/Logic/direct"].integral
    runtime.advance(30.0)
    assert runtime.blocks["/P/Logic/direct"].integral == integral_before, "no windup while clamped"
    runtime.write_point("/P/Inputs/en", False)
    runtime.advance(30.0)
    assert (
        _value(runtime, "/P/Logic/direct") == 100.0
        and runtime.blocks["/P/Logic/direct"].integral == 0.0
    )
    minimum = _runtime(builder, DEFAULT_POLICY.variant("m", loop_disabled="minimum"))
    minimum.write_point("/P/Inputs/en", False)
    minimum.advance(30.0)
    assert _value(minimum, "/P/Logic/direct") == 0.0
    runtime.set_input("/P/Logic/direct", "setpoint", StatusValue(0.0, Status.NULL))
    runtime.advance(30.0)
    assert runtime.read("/P/Logic/direct").is_null


def test_constants_hold_the_file_value() -> None:
    """S-CONST-1."""

    builder = BogBuilder("P")
    builder.add("Params", "k", "kitControl:NumericConst", [status_numeric("out", 4.5)])
    builder.add("Params", "b", "kitControl:BooleanConst", [status_boolean("out", True)])
    runtime = _runtime(builder)
    assert runtime.read("/P/Params/k") == StatusValue(4.5, Status.OK)
    assert runtime.read("/P/Params/b") == StatusValue(True, Status.OK)


# --- writable points ----------------------------------------------------------------------


def test_writable_priority_array_overrides_and_fallback() -> None:
    """S-WRITABLE-1, S-WRITABLE-2, S-WRITABLE-3, S-WRITABLE-5, S-WRITABLE-6."""

    builder = BogBuilder("P")
    builder.add("Pts", "n", NUM, [status_numeric("fallback", 7.0)])
    builder.add("Pts", "bare", NUM)
    runtime = _runtime(builder)
    assert runtime.read("/P/Pts/n") == StatusValue(7.0, Status.OK)
    assert runtime.read("/P/Pts/bare").is_null
    runtime.write_point("/P/Pts/n", 1.0, level=16)
    runtime.write_point("/P/Pts/n", 2.0, level=10, status=Status.ALARM)
    assert runtime.read("/P/Pts/n") == StatusValue(2.0, Status.ALARM), (
        "lowest non-null level wins with its status"
    )
    runtime.override("/P/Pts/n", 3.0, duration_seconds=60.0)
    assert runtime.read("/P/Pts/n") == StatusValue(3.0, Status.OVERRIDDEN)
    runtime.emergency_override("/P/Pts/n", 4.0)
    assert runtime.read("/P/Pts/n") == StatusValue(4.0, Status.OVERRIDDEN)
    runtime.emergency_auto("/P/Pts/n")
    assert _value(runtime, "/P/Pts/n") == 3.0
    runtime.advance(60.0)
    assert runtime.read("/P/Pts/n") == StatusValue(2.0, Status.ALARM), "the override expired"
    runtime.override("/P/Pts/n", 9.0)
    runtime.auto("/P/Pts/n")
    assert _value(runtime, "/P/Pts/n") == 2.0
    runtime.set_input("/P/Pts/n", "in10", StatusValue(0.0, Status.NULL))
    runtime.set_input("/P/Pts/n", "in16", StatusValue(0.0, Status.NULL))
    assert runtime.read("/P/Pts/n") == StatusValue(7.0, Status.OK)


def test_boolean_writable_minimum_active_and_inactive_times() -> None:
    """S-WRITABLE-4."""

    builder = BogBuilder("P")
    builder.add(
        "Pts",
        "b",
        BOOL,
        [
            status_boolean("fallback", False),
            rel_time("minActiveTime", 10.0),
            rel_time("minInactiveTime", 5.0),
        ],
    )
    runtime = _runtime(builder)
    runtime.advance(5.0)
    runtime.write_point("/P/Pts/b", True)
    assert _value(runtime, "/P/Pts/b") is True
    runtime.advance(4.0)
    runtime.write_point("/P/Pts/b", False)
    assert _value(runtime, "/P/Pts/b") is True, "held for the minimum active time"
    runtime.advance(6.0)
    assert _value(runtime, "/P/Pts/b") is False
    runtime.write_point("/P/Pts/b", True)
    assert _value(runtime, "/P/Pts/b") is False, "held for the minimum inactive time"
    runtime.advance(5.0)
    assert _value(runtime, "/P/Pts/b") is True


# --- links, clock, propagation ------------------------------------------------------------


def test_links_propagate_on_change_only_and_start_activates_links() -> None:
    """S-LINK-1, S-LINK-2."""

    builder = BogBuilder("P")
    _inputs(builder, a=1.0)
    builder.add("Logic", "add", "kitControl:Add", [status_numeric("inB", 2.0)])
    builder.link("Inputs/a", "out", "Logic/add", "inA")
    runtime = _runtime(builder)
    assert _value(runtime, "/P/Logic/add") == 3.0, (
        "link activation pushed the input before the first execution"
    )
    runtime.write_point(
        "/P/Inputs/a", 1.0
    )  # in16 goes from null to 1.0: the point executes, out is unchanged
    before = runtime.execution_count
    runtime.write_point("/P/Inputs/a", 1.0)
    assert runtime.execution_count == before, "an unchanged value fires nothing"
    runtime.write_point("/P/Inputs/a", 5.0)
    assert runtime.execution_count == before + 2 and _value(runtime, "/P/Logic/add") == 7.0


def test_unstable_link_loops_are_reported() -> None:
    """S-LINK-3."""

    builder = BogBuilder("P")
    _inputs(builder, a=False)
    builder.add("Logic", "n1", "kitControl:Not")
    builder.add("Logic", "n2", "kitControl:Or")
    builder.link("Inputs/a", "out", "Logic/n2", "inA")
    builder.link("Logic/n2", "out", "Logic/n1", "in")
    builder.link("Logic/n1", "out", "Logic/n2", "inB")  # Or(a, Not(Or)) oscillates when a is false
    with pytest.raises(PropagationLoopError, match="/P/Logic/n"):
        _runtime(builder, DEFAULT_POLICY.variant("tight", loop_limit=50))
    # A converging feedback (a latch) is fine.
    builder = BogBuilder("P")
    _inputs(builder, s=False, notClear=True)
    builder.add("Logic", "any", "kitControl:Or")
    builder.add("Logic", "hold", "kitControl:And")
    builder.link("Inputs/s", "out", "Logic/any", "inA")
    builder.link("Logic/hold", "out", "Logic/any", "inB")
    builder.link("Logic/any", "out", "Logic/hold", "inA")
    builder.link("Inputs/notClear", "out", "Logic/hold", "inB")
    runtime = _runtime(builder)
    assert _value(runtime, "/P/Logic/hold") is False
    runtime.write_point("/P/Inputs/s", True)
    runtime.write_point("/P/Inputs/s", False)
    assert _value(runtime, "/P/Logic/hold") is True, "latched through the feedback"
    runtime.write_point("/P/Inputs/notClear", False)
    assert _value(runtime, "/P/Logic/hold") is False


def test_propagation_is_synchronous_and_intermediate_values_are_visible() -> None:
    """S-LINK-4."""

    # a feeds both inputs of a Subtract, one side through Add(a, 0): under
    # depth-first propagation the Subtract briefly sees one new and one old value.
    builder = BogBuilder("P")
    _inputs(builder, a=1.0)
    builder.add("Logic", "viaAdd", "kitControl:Add", [status_numeric("inB", 0.0)])
    builder.add("Logic", "diff", "kitControl:Subtract")
    builder.add("Logic", "edge", "kitControl:NotEqual", [status_numeric("inB", 0.0)])
    builder.add("Logic", "os", "kitControl:OneShot")
    builder.add("Logic", "any", "kitControl:Or")
    builder.add("Logic", "hold", "kitControl:And", [status_boolean("inB", True)])
    builder.link("Inputs/a", "out", "Logic/diff", "inA")
    builder.link("Inputs/a", "out", "Logic/viaAdd", "inA")
    builder.link("Logic/viaAdd", "out", "Logic/diff", "inB")
    builder.link("Logic/diff", "out", "Logic/edge", "inA")
    builder.link("Logic/edge", "out", "Logic/os", "in")
    builder.link("Logic/os", "out", "Logic/any", "inA")
    builder.link("Logic/hold", "out", "Logic/any", "inB")
    builder.link("Logic/any", "out", "Logic/hold", "inA")
    depth = _runtime(builder)
    depth.write_point("/P/Inputs/a", 5.0)
    assert _value(depth, "/P/Logic/diff") == 0.0, "settled"
    assert _value(depth, "/P/Logic/hold") is True, "but the glitch set the latch"
    reverse = _runtime(builder, DEFAULT_POLICY.variant("reverse", link_order="reverse"))
    reverse.write_point("/P/Inputs/a", 5.0)
    assert _value(reverse, "/P/Logic/hold") is True, (
        "depth-first glitches whichever link fires first"
    )
    breadth = _runtime(builder, DEFAULT_POLICY.variant("breadth", propagation="breadth"))
    breadth.write_point("/P/Inputs/a", 5.0)
    assert _value(breadth, "/P/Logic/diff") == 0.0
    assert _value(breadth, "/P/Logic/hold") is False, (
        "breadth-first reads settled values and never shows it"
    )


def test_timers_fire_in_due_order_with_policy_ties() -> None:
    """S-CLOCK-1."""

    builder = BogBuilder("P")
    _inputs(builder, a=False)
    builder.add("Logic", "d1", "kitControl:BooleanDelay", [rel_time("onDelay", 5.0)])
    builder.add("Logic", "d2", "kitControl:BooleanDelay", [rel_time("onDelay", 3.0)])
    builder.add("Logic", "latch", "kitControl:BooleanLatch")
    builder.link("Inputs/a", "out", "Logic/d1", "in")
    builder.link("Inputs/a", "out", "Logic/d2", "in")
    builder.link("Logic/d1", "out", "Logic/latch", "in")
    builder.link("Logic/d2", "out", "Logic/latch", "clock")
    runtime = _runtime(builder)
    runtime.write_point("/P/Inputs/a", True)
    runtime.advance(4.0)
    assert _value(runtime, "/P/Logic/d2") is True and _value(runtime, "/P/Logic/d1") is False
    assert _value(runtime, "/P/Logic/latch") is False, "clocked at t=3 with in still false"
    assert runtime.pending_timers() == 1
    runtime.advance(1.0)
    assert _value(runtime, "/P/Logic/d1") is True and runtime.now == 5.0
    # Ties: two delays due together, the latch clocked by one and fed by the other.
    builder = BogBuilder("P")
    _inputs(builder, a=False)
    builder.add("Logic", "feed", "kitControl:BooleanDelay", [rel_time("onDelay", 2.0)])
    builder.add("Logic", "clock", "kitControl:BooleanDelay", [rel_time("onDelay", 2.0)])
    builder.add("Logic", "latch", "kitControl:BooleanLatch")
    builder.link("Inputs/a", "out", "Logic/feed", "in")
    builder.link("Inputs/a", "out", "Logic/clock", "in")
    builder.link("Logic/feed", "out", "Logic/latch", "in")
    builder.link("Logic/clock", "out", "Logic/latch", "clock")
    document = _runtime(builder)
    document.write_point("/P/Inputs/a", True)
    document.advance(2.0)
    assert _value(document, "/P/Logic/latch") is True, "feed fired first in document order"
    reverse = _runtime(builder, DEFAULT_POLICY.variant("rev", tick_order="reverse"))
    reverse.write_point("/P/Inputs/a", True)
    reverse.advance(2.0)
    assert _value(reverse, "/P/Logic/latch") is False, "clock fired first in reverse order"


# --- module components -------------------------------------------------------------------


def test_module_components_step_on_period_and_on_input_change() -> None:
    """S-MODULE-1, S-MODULE-4."""

    builder = BogBuilder("P")
    _inputs(builder, a=False)
    builder.add(
        "Logic",
        "delay",
        "bactalkG36:TrueDelay",
        [rel_time("delayTime", 10.0), rel_time("executionPeriod", 2.0)],
    )
    builder.link("Inputs/a", "out", "Logic/delay", "in")
    runtime = _runtime(builder)
    block = runtime.blocks["/P/Logic/delay"]
    assert isinstance(block, ModuleBlock) and block.period == 2.0
    runtime.advance(3.0)
    runtime.write_point("/P/Inputs/a", True)  # t=3: steps at once
    assert _value(runtime, "/P/Logic/delay") is False
    runtime.advance(9.0)  # t=12: ticks at 4,6,8,10,12
    assert _value(runtime, "/P/Logic/delay") is False
    runtime.advance(2.0)  # t=14 >= 3 + 10
    assert _value(runtime, "/P/Logic/delay") is True
    override = _runtime(builder, DEFAULT_POLICY.variant("coarse", module_period_seconds=5.0))
    assert override.blocks["/P/Logic/delay"].period == 5.0


def test_pre_and_numeric_change_step_only_on_the_tick() -> None:
    """S-MODULE-2."""

    builder = BogBuilder("P")
    _inputs(builder, a=False, n=0.0)
    builder.add("Logic", "pre", "bactalkG36:Pre", [rel_time("executionPeriod", 10.0)])
    builder.add(
        "Logic",
        "chg",
        "bactalkG36:NumericChange",
        [string("mode", "increased"), rel_time("executionPeriod", 10.0)],
    )
    builder.link("Inputs/a", "out", "Logic/pre", "in")
    builder.link("Inputs/n", "out", "Logic/chg", "in")
    runtime = _runtime(builder)
    runtime.write_point("/P/Inputs/a", True)
    runtime.write_point("/P/Inputs/n", 5.0)
    assert _value(runtime, "/P/Logic/pre") is False and _value(runtime, "/P/Logic/chg") is False, (
        "no step on change"
    )
    runtime.advance(10.0)
    assert _value(runtime, "/P/Logic/pre") is False, "Pre gives the input as of the previous tick"
    assert _value(runtime, "/P/Logic/chg") is True, "5 is above the 0 seen at the previous tick"
    runtime.advance(10.0)
    assert _value(runtime, "/P/Logic/pre") is True
    assert _value(runtime, "/P/Logic/chg") is False, "one tick later the value is unchanged"


def test_invalid_inputs_null_the_outputs_without_stepping() -> None:
    """S-MODULE-3."""

    builder = BogBuilder("P")
    _inputs(builder, a=True)
    builder.add(
        "Logic",
        "timer",
        "bactalkG36:Timer",
        [rel_time("threshold", 5.0), rel_time("executionPeriod", 1.0)],
    )
    builder.link("Inputs/a", "out", "Logic/timer", "in")
    runtime = _runtime(builder)
    runtime.advance(3.0)
    assert _value(runtime, "/P/Logic/timer", "elapsed") == 3.0
    runtime.write_point("/P/Inputs/a", True, status=Status.STALE)
    runtime.advance(3.0)
    assert runtime.read("/P/Logic/timer", "elapsed") == StatusValue(3.0, Status.NULL), (
        "not stepped, last value kept"
    )
    assert runtime.read("/P/Logic/timer", "passed").is_null
    runtime.write_point("/P/Inputs/a", True, status=Status.OK)
    assert (
        _value(runtime, "/P/Logic/timer", "elapsed") == 6.0
        and _value(runtime, "/P/Logic/timer", "passed") is True
    )


def test_module_component_missing_required_property_is_a_load_error() -> None:
    builder = BogBuilder("P")
    builder.add("Logic", "ud", "bactalkG36:UnitDelay")
    with pytest.raises(ValueError, match="samplePeriod"):
        _runtime(builder)
    for type_name, cls in REGISTRY.items():
        if type_name.startswith("bactalkG36:"):
            assert issubclass(cls, ModuleBlock)


def test_unknown_type_is_refused_by_the_runtime() -> None:
    builder = BogBuilder("P")
    builder.add("Logic", "x", "kitControl:Ramp")
    with pytest.raises(ShadowLoadError, match="kitControl:Ramp"):
        _runtime(builder)


# --- schedules and histories ---------------------------------------------------------------


def test_weekly_schedule_periods_default_and_epoch() -> None:
    """S-SCHED-1, S-SCHED-2, S-SCHED-3."""

    from bactalk.niagara.shadow.builder import Prop

    def time_entry(name: str, start: str, finish: str, value: bool) -> Prop:
        return Prop(
            name,
            "sch:TimeSchedule",
            None,
            None,
            (
                Prop("start", "b:Time", start),
                Prop("finish", "b:Time", finish),
                status_boolean("effectiveValue", value),
            ),
        )

    monday = Prop(
        "monday",
        "sch:DailySchedule",
        None,
        None,
        (
            Prop(
                "day",
                "sch:DaySchedule",
                None,
                None,
                (time_entry("time", "08:00:00.000", "17:00:00.000", True),),
            ),
            Prop("days", "sch:WeekdaySchedule", None, None, (Prop("set", "b:EnumSet", "1"),)),
        ),
    )
    schedule = Prop(
        "schedule",
        "sch:CompositeSchedule",
        None,
        None,
        (Prop("week", "sch:WeekSchedule", None, None, (monday,)),),
    )
    builder = BogBuilder("P")
    builder.add(
        "Sch", "occ", "sch:BooleanSchedule", [status_boolean("defaultOutput", False), schedule]
    )
    runtime = _runtime(builder)
    assert _value(runtime, "/P/Sch/occ") is False, "Monday 00:00 is outside the period"
    runtime.advance(8 * 3600.0)
    assert _value(runtime, "/P/Sch/occ") is True
    runtime.advance(9 * 3600.0 - 1.0)
    assert _value(runtime, "/P/Sch/occ") is True
    runtime.advance(1.0)
    assert _value(runtime, "/P/Sch/occ") is False, "finish is exclusive"
    runtime.advance(6 * 86400.0)
    assert _value(runtime, "/P/Sch/occ") is False and runtime.now == 17 * 3600.0 + 6 * 86400.0, (
        "Sunday 17:00"
    )
    runtime.advance(15 * 3600.0)
    assert _value(runtime, "/P/Sch/occ") is True, "the next Monday 08:00"


def test_interval_history_records_the_parent_out() -> None:
    """S-HIST-1."""

    builder = BogBuilder("P")
    builder.add("Pts", "t", NUM, [status_numeric("fallback", 1.0)])
    builder.add("Pts", "NumericInterval", "history:NumericIntervalHistoryExt", parent="Pts/t")
    builder.add(
        "Pts",
        "historyConfig",
        "history:HistoryConfig",
        [raw("interval", "false:60000", "history:CollectionInterval")],
        parent="Pts/NumericInterval",
    )
    runtime = _runtime(builder)
    runtime.advance(60.0)
    runtime.write_point("/P/Pts/t", 2.0)
    runtime.advance(60.0)
    history = runtime.blocks["/P/Pts/t/NumericInterval"]
    assert history.records == [(0.0, 1.0, 0), (60.0, 1.0, 0), (120.0, 2.0, 0)]


# --- the document and the tests agree -------------------------------------------------------


def test_semantics_document_and_tests_cite_the_same_assumptions() -> None:
    root = Path(__file__).resolve().parents[1]
    documented = set(
        re.findall(
            r"^\| (S-[A-Z]+-\d+) \|",
            (root / "docs" / "niagara-semantics.md").read_text("utf-8"),
            re.MULTILINE,
        )
    )
    cited: set[str] = set()
    for path in (root / "tests").glob("test_native_bog_shadow_*.py"):
        cited |= set(re.findall(r"S-[A-Z]+-\d+", path.read_text("utf-8")))
    source_cited: set[str] = set()
    for path in (root / "src" / "bactalk" / "niagara" / "shadow").glob("*.py"):
        source_cited |= set(re.findall(r"S-[A-Z]+-\d+", path.read_text("utf-8")))
    assert documented, "the document lists no assumptions"
    assert documented - cited == set(), f"documented but untested: {sorted(documented - cited)}"
    assert cited - documented == set(), f"tested but undocumented: {sorted(cited - documented)}"
    assert source_cited - documented == set(), (
        f"cited in code but undocumented: {sorted(source_cited - documented)}"
    )
    types_in_doc = (root / "docs" / "niagara-semantics.md").read_text("utf-8")
    for type_name in REGISTRY:
        short = type_name.split(":")[1]
        assert short in types_in_doc, f"{type_name} has no entry in docs/niagara-semantics.md"
