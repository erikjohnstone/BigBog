"""Block library: every Niagara type the native emitter produces (N6 items 2, 4, 5).

Each class documents its behaviour by the assumption ids in
``docs/niagara-semantics.md`` (``S-*``); ``tests/test_native_bog_shadow_blocks.py``
has one test per cited id. Stock ``kitControl``/``control`` semantics come from
the kitControl and Niagara guides and are marked DOCUMENTED or ASSUMED in the
doc; ``bactalkG36`` semantics are our own Java wrappers (OWN).
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from bactalk.niagara.shadow.loader import ComponentNode, parse_number
from bactalk.niagara.shadow.policy import ExecutionPolicy
from bactalk.niagara.shadow.status import (
    BOOLEAN_NULL,
    NUMERIC_NULL,
    Status,
    StatusValue,
    parse_status,
)

NUMERIC = "n"
BOOLEAN = "b"


class KernelInstance(Protocol):
    def step(
        self, time_seconds: float, inputs: Sequence[float | bool]
    ) -> tuple[float | bool, ...]: ...


class KernelBackend(Protocol):
    name: str

    def open(self, kernel: str, params: Mapping[str, object]) -> KernelInstance: ...

    def close(self) -> None: ...


class Context(Protocol):
    """What a block may ask of the engine."""

    now: float
    policy: ExecutionPolicy
    kernels: KernelBackend

    def schedule(
        self, block: Block, delay_seconds: float, tag: str, *, late: bool = False
    ) -> int: ...

    def cancel(self, handle: int) -> None: ...

    def block_at(self, path: str) -> Block | None: ...


def _null_for(kind: str) -> StatusValue:
    return NUMERIC_NULL if kind == NUMERIC else BOOLEAN_NULL


_NUMERIC_ZERO = StatusValue(0.0, Status.OK)
_BOOLEAN_ZERO = StatusValue(False, Status.OK)


def _zero_for(kind: str) -> StatusValue:
    return _NUMERIC_ZERO if kind == NUMERIC else _BOOLEAN_ZERO


class Block:
    TYPE = ""
    INPUTS: Mapping[str, str] = {}
    OUTPUTS: Mapping[str, str] = {}
    DECISION = False
    """True for comparison blocks whose out is a typed decision (coverage)."""

    SOURCE_AT_START = False
    """True when the first output does not depend on the input (Pre, UnitDelay, …):
    the start-order pass treats the block as a source so feedback loops open there."""

    def __init__(self, node: ComponentNode, ctx: Context) -> None:
        self.node = node
        self.ctx = ctx
        self.path = node.path
        self.name = node.name
        self.inputs: dict[str, StatusValue] = {
            slot: _null_for(kind) for slot, kind in self.INPUTS.items()
        }
        # S-STATUS-6: outputs start at the type's zero value with ok status, as a saved
        # component's out slot does; the first execution replaces it.
        self.outputs: dict[str, StatusValue] = {
            slot: _zero_for(kind) for slot, kind in self.OUTPUTS.items()
        }
        self.changed: list[str] = []
        flags = node.prop("propagateFlags")
        self.propagate_flags = (
            parse_status(flags.value)
            if flags is not None and flags.value
            else ctx.policy.propagate_flags
        )
        self._read_slot_values()
        self.configure()

    # -- configuration --------------------------------------------------------

    def _read_slot_values(self) -> None:
        """Slots the file sets directly (constants, thresholds, initial outputs)."""

        for slot, kind in self.INPUTS.items():
            prop = self.node.prop(slot)
            if prop is None:
                continue
            value = prop.status_value(numeric=kind == NUMERIC)
            if value is not None:
                self.inputs[slot] = value
        for slot, kind in self.OUTPUTS.items():
            prop = self.node.prop(slot)
            if prop is None:
                continue
            value = prop.status_value(numeric=kind == NUMERIC)
            if value is not None:
                self.outputs[slot] = value

    def configure(self) -> None:
        pass

    def start(self) -> None:
        """Called once at station start, before links activate."""

    # -- execution ------------------------------------------------------------

    def set_input(self, slot: str, value: StatusValue) -> bool:
        if slot not in self.inputs:
            raise KeyError(f"{self.path} has no input slot {slot!r}")
        if self.inputs[slot] == value:
            return False
        self.inputs[slot] = value
        return True

    def execute(self) -> None:
        pass

    def on_timer(self, tag: str) -> None:
        pass

    def emit(self, slot: str, value: StatusValue) -> None:
        if self.outputs[slot] != value:
            self.outputs[slot] = value
            self.changed.append(slot)

    def emit_null(self, slot: str) -> None:
        """S-STATUS-5: a null output keeps its last value and gains the null flag."""

        current = self.outputs[slot]
        self.emit(slot, StatusValue(current.value, Status.NULL))

    def take_changes(self) -> list[str]:
        changed = self.changed
        self.changed = []
        return changed

    def executes_on_input_change(self) -> bool:
        return True

    # -- helpers --------------------------------------------------------------

    def _flags(self, *values: StatusValue) -> Status:
        """S-STATUS-4: only propagateFlags bits travel from inputs to out."""

        flags = Status.OK
        for value in values:
            flags |= value.status & self.propagate_flags
        return flags & ~Status.NULL


# --- constants and writable points ----------------------------------------------


class NumericConst(Block):
    """S-CONST-1: out holds the configured value with ok status."""

    TYPE = "kitControl:NumericConst"
    OUTPUTS = {"out": NUMERIC}


class BooleanConst(NumericConst):
    TYPE = "kitControl:BooleanConst"
    OUTPUTS = {"out": BOOLEAN}


class WritablePoint(Block):
    """control:NumericWritable / BooleanWritable (S-WRITABLE-1..6)."""

    KIND = NUMERIC
    INPUTS = {f"in{level}": NUMERIC for level in range(1, 17)}
    OUTPUTS = {"out": NUMERIC}

    def configure(self) -> None:
        fallback = self.node.prop("fallback")
        value = (
            fallback.status_value(numeric=self.KIND == NUMERIC) if fallback is not None else None
        )
        self.fallback = value if value is not None else _null_for(self.KIND)
        self._expiry: int | None = None
        self.min_active = self.node.seconds("minActiveTime", 0.0)
        self.min_inactive = self.node.seconds("minInactiveTime", 0.0)
        self._out_since = 0.0
        self._hold_timer: int | None = None

    def start(self) -> None:
        self._out_since = self.ctx.now
        self.execute()

    def active_level(self) -> int | None:
        for level in range(1, 17):
            if not self.inputs[f"in{level}"].is_null:
                return level
        return None

    def _desired(self) -> StatusValue:
        level = self.active_level()
        if level is None:
            return self.fallback
        chosen = self.inputs[f"in{level}"]
        status = chosen.status & ~Status.NULL
        if level in {1, 8}:
            status |= Status.OVERRIDDEN
        return StatusValue(chosen.value, status)

    def execute(self) -> None:
        desired = self._desired()
        current = self.outputs["out"]
        if (
            self.KIND == BOOLEAN
            and not desired.is_null
            and not current.is_null
            and desired.value != current.value
        ):
            # S-WRITABLE-4: the current state holds for at least its minimum time.
            required = self.min_active if current.value else self.min_inactive
            elapsed = self.ctx.now - self._out_since
            if required > 0.0 and elapsed < required - 1e-12:
                if self._hold_timer is None:
                    self._hold_timer = self.ctx.schedule(self, required - elapsed, "hold")
                return
        if self._hold_timer is not None:
            self.ctx.cancel(self._hold_timer)
            self._hold_timer = None
        if desired.value != current.value:
            self._out_since = self.ctx.now
        self.emit("out", desired)

    def on_timer(self, tag: str) -> None:
        if tag == "hold":
            self._hold_timer = None
            self.execute()
        elif tag == "override-expiry":
            self._expiry = None
            self.inputs["in8"] = _null_for(self.KIND)
            self.execute()

    # -- actions (S-WRITABLE-2, S-WRITABLE-3) -----------------------------------

    def override(self, value: float | bool, duration_seconds: float | None = None) -> None:
        if self._expiry is not None:
            self.ctx.cancel(self._expiry)
            self._expiry = None
        self.inputs["in8"] = StatusValue(
            float(value) if self.KIND == NUMERIC else bool(value), Status.OK
        )
        if duration_seconds is not None and duration_seconds > 0.0:
            self._expiry = self.ctx.schedule(self, duration_seconds, "override-expiry")

    def auto(self) -> None:
        if self._expiry is not None:
            self.ctx.cancel(self._expiry)
            self._expiry = None
        self.inputs["in8"] = _null_for(self.KIND)

    def emergency_override(self, value: float | bool) -> None:
        self.inputs["in1"] = StatusValue(
            float(value) if self.KIND == NUMERIC else bool(value), Status.OK
        )

    def emergency_auto(self) -> None:
        self.inputs["in1"] = _null_for(self.KIND)


class NumericWritable(WritablePoint):
    TYPE = "control:NumericWritable"


class BooleanWritable(WritablePoint):
    TYPE = "control:BooleanWritable"
    KIND = BOOLEAN
    INPUTS = {f"in{level}": BOOLEAN for level in range(1, 17)}
    OUTPUTS = {"out": BOOLEAN}


# --- kitControl math ---------------------------------------------------------------


class _FourInputMath(Block):
    INPUTS = {"inA": NUMERIC, "inB": NUMERIC, "inC": NUMERIC, "inD": NUMERIC}
    OUTPUTS = {"out": NUMERIC}

    def _valid(self) -> list[StatusValue]:
        return [value for value in self.inputs.values() if not value.is_null]

    def execute(self) -> None:
        present = self._valid()
        if not present:
            self.emit_null("out")
            return
        try:
            result, extra = self.combine([float(v.value) for v in present])
        except ZeroDivisionError:
            self.emit("out", StatusValue(math.nan, Status.FAULT | self._flags(*present)))
            return
        self.emit("out", StatusValue(result, self._flags(*present) | extra))

    def combine(self, values: list[float]) -> tuple[float, Status]:  # pragma: no cover - abstract
        raise NotImplementedError


class Add(_FourInputMath):
    """S-MATH-1: sum of the non-null inputs."""

    TYPE = "kitControl:Add"

    def combine(self, values: list[float]) -> tuple[float, Status]:
        return sum(values), Status.OK


class Multiply(_FourInputMath):
    TYPE = "kitControl:Multiply"

    def combine(self, values: list[float]) -> tuple[float, Status]:
        result = 1.0
        for value in values:
            result *= value
        return result, Status.OK


class Minimum(_FourInputMath):
    TYPE = "kitControl:Minimum"

    def combine(self, values: list[float]) -> tuple[float, Status]:
        return min(values), Status.OK


class Maximum(_FourInputMath):
    TYPE = "kitControl:Maximum"

    def combine(self, values: list[float]) -> tuple[float, Status]:
        return max(values), Status.OK


class Average(_FourInputMath):
    TYPE = "kitControl:Average"

    def combine(self, values: list[float]) -> tuple[float, Status]:
        return sum(values) / len(values), Status.OK


class _AnchoredMath(_FourInputMath):
    """S-MATH-2: inA is the anchor; a null inA gives a null out."""

    def execute(self) -> None:
        anchor = self.inputs["inA"]
        if anchor.is_null:
            self.emit_null("out")
            return
        others = [
            self.inputs[slot] for slot in ("inB", "inC", "inD") if not self.inputs[slot].is_null
        ]
        try:
            result, extra = self.fold(float(anchor.value), [float(v.value) for v in others])
        except ZeroDivisionError:
            self.emit("out", StatusValue(math.nan, Status.FAULT | self._flags(anchor, *others)))
            return
        self.emit("out", StatusValue(result, self._flags(anchor, *others) | extra))

    def fold(self, anchor: float, others: list[float]) -> tuple[float, Status]:  # pragma: no cover
        raise NotImplementedError


class Subtract(_AnchoredMath):
    TYPE = "kitControl:Subtract"

    def fold(self, anchor: float, others: list[float]) -> tuple[float, Status]:
        return anchor - sum(others), Status.OK


class Divide(_AnchoredMath):
    """S-MATH-3: a zero divisor gives the IEEE result with fault status."""

    TYPE = "kitControl:Divide"

    def fold(self, anchor: float, others: list[float]) -> tuple[float, Status]:
        result = anchor
        flags = Status.OK
        for value in others:
            if value == 0.0:
                flags |= Status.FAULT
                if result == 0.0 or math.isnan(result):
                    result = math.nan
                else:
                    result = math.copysign(math.inf, result)
            else:
                result = result / value
        return result, flags


# --- kitControl comparisons ---------------------------------------------------------


class _Comparison(Block):
    """S-CMP-1: both inputs must be non-null; S-CMP-2: operator as named."""

    INPUTS = {"inA": NUMERIC, "inB": NUMERIC}
    OUTPUTS = {"out": BOOLEAN}
    DECISION = True

    def execute(self) -> None:
        a = self.inputs["inA"]
        b = self.inputs["inB"]
        if a.is_null or b.is_null:
            self.emit_null("out")
            return
        self.emit(
            "out", StatusValue(self.compare(float(a.value), float(b.value)), self._flags(a, b))
        )

    def compare(self, a: float, b: float) -> bool:  # pragma: no cover - abstract
        raise NotImplementedError


class GreaterThan(_Comparison):
    TYPE = "kitControl:GreaterThan"

    def compare(self, a: float, b: float) -> bool:
        return a > b


class GreaterThanEqual(_Comparison):
    TYPE = "kitControl:GreaterThanEqual"

    def compare(self, a: float, b: float) -> bool:
        return a >= b


class LessThan(_Comparison):
    TYPE = "kitControl:LessThan"

    def compare(self, a: float, b: float) -> bool:
        return a < b


class LessThanEqual(_Comparison):
    TYPE = "kitControl:LessThanEqual"

    def compare(self, a: float, b: float) -> bool:
        return a <= b


class Equal(_Comparison):
    TYPE = "kitControl:Equal"

    def compare(self, a: float, b: float) -> bool:
        return a == b


class NotEqual(_Comparison):
    TYPE = "kitControl:NotEqual"

    def compare(self, a: float, b: float) -> bool:
        return a != b


# --- kitControl logic ----------------------------------------------------------------


class _FourInputLogic(Block):
    """S-LOGIC-1: null inputs are ignored; all null gives null."""

    INPUTS = {"inA": BOOLEAN, "inB": BOOLEAN, "inC": BOOLEAN, "inD": BOOLEAN}
    OUTPUTS = {"out": BOOLEAN}

    def execute(self) -> None:
        present = [value for value in self.inputs.values() if not value.is_null]
        if not present:
            self.emit_null("out")
            return
        self.emit(
            "out",
            StatusValue(self.combine([bool(v.value) for v in present]), self._flags(*present)),
        )

    def combine(self, values: list[bool]) -> bool:  # pragma: no cover - abstract
        raise NotImplementedError


class And(_FourInputLogic):
    TYPE = "kitControl:And"

    def combine(self, values: list[bool]) -> bool:
        return all(values)


class Or(_FourInputLogic):
    TYPE = "kitControl:Or"

    def combine(self, values: list[bool]) -> bool:
        return any(values)


class Xor(_FourInputLogic):
    """S-LOGIC-3: true when exactly one non-null input is true."""

    TYPE = "kitControl:Xor"

    def combine(self, values: list[bool]) -> bool:
        return sum(values) == 1


class Not(Block):
    """S-LOGIC-2: null in gives null out."""

    TYPE = "kitControl:Not"
    INPUTS = {"in": BOOLEAN}
    OUTPUTS = {"out": BOOLEAN}

    def execute(self) -> None:
        value = self.inputs["in"]
        if value.is_null:
            self.emit_null("out")
            return
        self.emit("out", StatusValue(not value.value, self._flags(value)))


# --- switches and latches -----------------------------------------------------------


class _Switch(Block):
    """S-SWITCH-1: inSwitch selects inTrue/inFalse; a null selector or selection is null."""

    INPUTS = {"inSwitch": BOOLEAN, "inTrue": NUMERIC, "inFalse": NUMERIC}
    OUTPUTS = {"out": NUMERIC}

    def execute(self) -> None:
        selector = self.inputs["inSwitch"]
        if selector.is_null:
            self.emit_null("out")
            return
        chosen = self.inputs["inTrue"] if selector.value else self.inputs["inFalse"]
        if chosen.is_null:
            self.emit_null("out")
            return
        self.emit("out", StatusValue(chosen.value, self._flags(selector, chosen)))


class NumericSwitch(_Switch):
    TYPE = "kitControl:NumericSwitch"


class BooleanSwitch(_Switch):
    TYPE = "kitControl:BooleanSwitch"
    INPUTS = {"inSwitch": BOOLEAN, "inTrue": BOOLEAN, "inFalse": BOOLEAN}
    OUTPUTS = {"out": BOOLEAN}


class _Latch(Block):
    """S-LATCH-1: out follows in on the rising edge of clock; S-LATCH-2: zero until then."""

    INPUTS = {"in": NUMERIC, "clock": BOOLEAN}
    OUTPUTS = {"out": NUMERIC}

    def configure(self) -> None:
        self._clock_high = False

    def execute(self) -> None:
        clock = self.inputs["clock"]
        high = (not clock.is_null) and bool(clock.value)
        rising = high and not self._clock_high
        self._clock_high = high
        if rising:
            value = self.inputs["in"]
            if value.is_null:
                self.emit_null("out")
            else:
                self.emit("out", StatusValue(value.value, self._flags(value, clock)))


class NumericLatch(_Latch):
    TYPE = "kitControl:NumericLatch"


class BooleanLatch(_Latch):
    TYPE = "kitControl:BooleanLatch"
    INPUTS = {"in": BOOLEAN, "clock": BOOLEAN}
    OUTPUTS = {"out": BOOLEAN}


# --- timed stock blocks -------------------------------------------------------------


class OneShot(Block):
    """S-ONESHOT-1..3: a pulse of pulseWidth on each rising edge of in."""

    TYPE = "kitControl:OneShot"
    INPUTS = {"in": BOOLEAN}
    OUTPUTS = {"out": BOOLEAN}

    def configure(self) -> None:
        width = self.node.seconds("pulseWidth", -1.0)
        self.pulse_width = width if width > 0.0 else self.ctx.policy.one_shot_pulse_seconds
        self._high = False
        self._timer: int | None = None
        self.outputs["out"] = StatusValue(False, Status.OK)

    def execute(self) -> None:
        value = self.inputs["in"]
        high = (not value.is_null) and bool(value.value)
        rising = high and not self._high
        self._high = high
        if rising:
            if self._timer is not None:
                self.ctx.cancel(self._timer)
            self._timer = self.ctx.schedule(self, self.pulse_width, "pulse")
            self.emit("out", StatusValue(True, Status.OK))

    def fire(self) -> None:
        """The ``fire`` action: a pulse without an input edge."""

        if self._timer is not None:
            self.ctx.cancel(self._timer)
        self._timer = self.ctx.schedule(self, self.pulse_width, "pulse")
        self.emit("out", StatusValue(True, Status.OK))

    def on_timer(self, tag: str) -> None:
        self._timer = None
        self.emit("out", StatusValue(False, Status.OK))


class BooleanDelay(Block):
    """S-DELAY-1: onDelay/offDelay before out follows in; S-DELAY-2: no pass-through at start."""

    TYPE = "kitControl:BooleanDelay"
    INPUTS = {"in": BOOLEAN}
    OUTPUTS = {"out": BOOLEAN}

    def configure(self) -> None:
        self.on_delay = self.node.seconds("onDelay", 0.0)
        self.off_delay = self.node.seconds("offDelay", 0.0)
        self._timer: int | None = None
        self._pending: bool | None = None
        self.outputs["out"] = StatusValue(False, Status.OK)

    def _cancel(self) -> None:
        if self._timer is not None:
            self.ctx.cancel(self._timer)
            self._timer = None
        self._pending = None

    def execute(self) -> None:
        value = self.inputs["in"]
        if value.is_null:
            self._cancel()
            self.emit_null("out")
            return
        desired = bool(value.value)
        current = self.outputs["out"]
        if not current.is_null and desired == current.value:
            self._cancel()
            return
        if self._pending == desired:
            return
        self._cancel()
        delay = self.on_delay if desired else self.off_delay
        if delay <= 0.0:
            self.emit("out", StatusValue(desired, Status.OK))
            return
        self._pending = desired
        self._timer = self.ctx.schedule(self, delay, "delay")

    def on_timer(self, tag: str) -> None:
        pending = self._pending
        self._timer = None
        self._pending = None
        if pending is not None:
            self.emit("out", StatusValue(pending, Status.OK))


class MultiVibrator(Block):
    """S-MV-1..3: a free-running clock of period and dutyCycle from station start."""

    TYPE = "kitControl:MultiVibrator"
    OUTPUTS = {"out": BOOLEAN}

    def configure(self) -> None:
        self.period = self.node.seconds("period", 0.0)
        self.duty = self.node.number("dutyCycle", 50.0)
        self.enabled = self.node.flag("enabled", True)
        self._timer: int | None = None

    def start(self) -> None:
        if not self.enabled or self.period <= 0.0:
            self.emit("out", StatusValue(False, Status.OK))
            return
        self.emit("out", StatusValue(self.ctx.policy.multivibrator_initial, Status.OK))
        self._reschedule()

    def _reschedule(self) -> None:
        high = bool(self.outputs["out"].value)
        fraction = min(max(self.duty, 0.0), 100.0) / 100.0
        delay = self.period * (fraction if high else 1.0 - fraction)
        if delay <= 0.0:
            delay = self.period
        self._timer = self.ctx.schedule(self, delay, "toggle")

    def on_timer(self, tag: str) -> None:
        self.emit("out", StatusValue(not bool(self.outputs["out"].value), Status.OK))
        self._reschedule()


class Tstat(Block):
    """S-TSTAT-1..3: hysteresis around sp with differential diff."""

    TYPE = "kitControl:Tstat"
    INPUTS = {"cv": NUMERIC, "sp": NUMERIC, "diff": NUMERIC}
    OUTPUTS = {"out": BOOLEAN}

    def configure(self) -> None:
        self.direct = self.node.text("action", "direct").strip().lower() != "reverse"
        if self.outputs["out"].is_null:
            self.outputs["out"] = StatusValue(False, Status.OK)

    def execute(self) -> None:
        cv = self.inputs["cv"]
        sp = self.inputs["sp"]
        diff = self.inputs["diff"]
        if cv.is_null or sp.is_null:
            self.emit_null("out")
            return
        half = (0.0 if diff.is_null else float(diff.value)) / 2.0
        value = float(cv.value)
        setpoint = float(sp.value)
        current = bool(self.outputs["out"].value)
        if self.direct:
            state = (
                True if value >= setpoint + half else False if value <= setpoint - half else current
            )
        else:
            state = (
                True if value <= setpoint - half else False if value >= setpoint + half else current
            )
        self.emit("out", StatusValue(state, self._flags(cv, sp, diff)))


class Reset(Block):
    """S-RESET-1: linear rescale of inA between the input and output limits, clamped."""

    TYPE = "kitControl:Reset"
    INPUTS = {
        "inA": NUMERIC,
        "inputLowLimit": NUMERIC,
        "inputHighLimit": NUMERIC,
        "outputLowLimit": NUMERIC,
        "outputHighLimit": NUMERIC,
    }
    OUTPUTS = {"out": NUMERIC}

    def execute(self) -> None:
        values = self.inputs
        if any(values[slot].is_null for slot in self.INPUTS):
            self.emit_null("out")
            return
        value = float(values["inA"].value)
        in_low = float(values["inputLowLimit"].value)
        in_high = float(values["inputHighLimit"].value)
        out_low = float(values["outputLowLimit"].value)
        out_high = float(values["outputHighLimit"].value)
        flags = self._flags(*values.values())
        if in_high == in_low:
            self.emit("out", StatusValue(out_low, flags | Status.FAULT))
            return
        ratio = min(1.0, max(0.0, (value - in_low) / (in_high - in_low)))
        self.emit("out", StatusValue(out_low + ratio * (out_high - out_low), flags))


class LoopPoint(Block):
    """kitControl:LoopPoint (S-LOOP-1..6): PID on its executeTime clock."""

    TYPE = "kitControl:LoopPoint"
    INPUTS = {"loopEnable": BOOLEAN, "controlledVariable": NUMERIC, "setpoint": NUMERIC}
    OUTPUTS = {"out": NUMERIC}

    def configure(self) -> None:
        node = self.node
        self.direct = node.text("loopAction", "direct").strip().lower() != "reverse"
        self.kp = node.number("proportionalConstant", 1.0)
        self.ki = node.number("integralConstant", 0.0)
        self.kd = node.number("derivativeConstant", 0.0)
        self.bias = node.number("bias", 0.0)
        self.maximum = node.number("maximumOutput", 100.0)
        self.minimum = node.number("minimumOutput", 0.0)
        period = node.seconds("executeTime", -1.0)
        self.period = period if period > 0.0 else self.ctx.policy.loop_execute_seconds
        self.integral = 0.0
        self.previous_error: float | None = None
        self.last_time: float | None = None
        if self.outputs["out"].is_null:
            self.outputs["out"] = StatusValue(0.0, Status.OK)

    def executes_on_input_change(self) -> bool:
        return False

    def start(self) -> None:
        self.ctx.schedule(self, self.period, "execute")

    def on_timer(self, tag: str) -> None:
        self.execute()
        self.ctx.schedule(self, self.period, "execute")

    def execute(self) -> None:
        now = self.ctx.now
        dt = 0.0 if self.last_time is None else now - self.last_time
        self.last_time = now
        enable = self.inputs["loopEnable"]
        cv = self.inputs["controlledVariable"]
        sp = self.inputs["setpoint"]
        if enable.is_null or cv.is_null or sp.is_null:
            self.emit_null("out")
            return
        flags = self._flags(enable, cv, sp)
        if not enable.value:
            self.integral = 0.0
            self.previous_error = None
            mode = self.ctx.policy.loop_disabled
            if mode == "minimum":
                self.emit("out", StatusValue(self.minimum, flags))
            elif mode == "bias":
                self.emit(
                    "out", StatusValue(min(self.maximum, max(self.minimum, self.bias)), flags)
                )
            else:
                self.emit("out", StatusValue(self.outputs["out"].value, flags))
            return
        error = (
            float(cv.value) - float(sp.value) if self.direct else float(sp.value) - float(cv.value)
        )
        proportional = self.kp * error
        minutes = dt / 60.0
        candidate = self.integral + self.kp * self.ki * error * minutes
        derivative = 0.0
        if self.kd != 0.0 and minutes > 0.0 and self.previous_error is not None:
            derivative = self.kp * self.kd * (error - self.previous_error) / minutes
        self.previous_error = error
        raw = self.bias + proportional + candidate + derivative
        output = min(self.maximum, max(self.minimum, raw))
        if not ((raw > self.maximum and error > 0.0) or (raw < self.minimum and error < 0.0)):
            self.integral = candidate
        self.emit("out", StatusValue(output, flags))


# --- schedules and histories ----------------------------------------------------------

_DAY_NAMES = ("sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday")


def _parse_clock(text: str) -> float:
    parts = text.strip().split(":")
    hours = float(parts[0])
    minutes = float(parts[1]) if len(parts) > 1 else 0.0
    seconds = float(parts[2]) if len(parts) > 2 else 0.0
    return hours * 3600.0 + minutes * 60.0 + seconds


@dataclass(frozen=True)
class SchedulePeriod:
    day: int
    """0 = Sunday … 6 = Saturday."""

    start: float
    finish: float
    value: float | bool


class _Schedule(Block):
    """schedule:BooleanSchedule / NumericSchedule (S-SCHED-1..3)."""

    KIND = BOOLEAN
    OUTPUTS = {"out": BOOLEAN}
    WEEK_SECONDS = 7 * 86400.0

    def configure(self) -> None:
        default = self.node.prop("defaultOutput")
        value = default.status_value(numeric=self.KIND == NUMERIC) if default is not None else None
        self.default = (
            value
            if value is not None
            else StatusValue(0.0 if self.KIND == NUMERIC else False, Status.OK)
        )
        self.periods: list[SchedulePeriod] = []
        schedule = self.node.prop("schedule")
        week = schedule.children.get("week") if schedule is not None else None
        if week is not None:
            for day_name, daily in week.children.items():
                days = self._days(daily, day_name)
                day = daily.children.get("day")
                if day is None:
                    continue
                for entry in day.children.values():
                    start = entry.child_value("start")
                    finish = entry.child_value("finish")
                    effective = entry.children.get("effectiveValue")
                    if start is None or finish is None or effective is None:
                        continue
                    effective_value = effective.status_value(numeric=self.KIND == NUMERIC)
                    if effective_value is None:
                        continue
                    for index in days:
                        self.periods.append(
                            SchedulePeriod(
                                index,
                                _parse_clock(start),
                                _parse_clock(finish),
                                effective_value.value,
                            )
                        )
        self.periods.sort(key=lambda item: (item.day, item.start))
        self.epoch_offset = 86400.0  # S-SCHED-3: simulated t=0 is Monday 00:00

    @staticmethod
    def _days(daily: Any, fallback_name: str) -> list[int]:
        days = daily.children.get("days")
        chosen = days.child_value("set") if days is not None else None
        if chosen:
            try:
                return sorted({int(token) % 7 for token in chosen.split(",") if token.strip()})
            except ValueError:
                pass
        return [_DAY_NAMES.index(fallback_name)] if fallback_name in _DAY_NAMES else []

    def value_at(self, time_seconds: float) -> tuple[StatusValue, float | None]:
        """Effective output at ``time_seconds`` and the next boundary (None when static)."""

        week_time = (time_seconds + self.epoch_offset) % self.WEEK_SECONDS
        day = int(week_time // 86400.0)
        clock = week_time - day * 86400.0
        next_boundary: float | None = None
        for period in self.periods:
            starts = period.day * 86400.0 + period.start
            ends = period.day * 86400.0 + period.finish
            for candidate in (starts, ends):
                delta = (candidate - week_time) % self.WEEK_SECONDS
                if delta <= 1e-9:
                    delta = self.WEEK_SECONDS
                if next_boundary is None or delta < next_boundary:
                    next_boundary = delta
            if period.day == day and period.start <= clock < period.finish:
                return StatusValue(period.value, Status.OK), next_boundary
        return self.default, next_boundary

    def start(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        value, delay = self.value_at(self.ctx.now)
        self.emit("out", value)
        if delay is not None:
            self.ctx.schedule(self, delay, "boundary")

    def on_timer(self, tag: str) -> None:
        self._refresh()


class BooleanSchedule(_Schedule):
    TYPE = "schedule:BooleanSchedule"


class NumericSchedule(_Schedule):
    TYPE = "schedule:NumericSchedule"
    KIND = NUMERIC
    OUTPUTS = {"out": NUMERIC}


class IntervalHistory(Block):
    """history:*IntervalHistoryExt (S-HIST-1): records the parent point's out every interval."""

    KIND = NUMERIC

    def configure(self) -> None:
        config = None
        for child in self.node.children:
            if child.name == "historyConfig":
                config = child
        interval_text = (
            config.text("interval", "") if config is not None else self.node.text("interval", "")
        )
        millis = interval_text.split(":")[-1] if interval_text else ""
        self.interval = parse_number(millis) / 1000.0 if millis else 0.0
        self.records: list[tuple[float, float | bool, int]] = []

    def start(self) -> None:
        if self.interval > 0.0:
            self._record()
            self.ctx.schedule(self, self.interval, "collect")

    def _record(self) -> None:
        parent = self.ctx.block_at(self.node.parent.path) if self.node.parent is not None else None
        if parent is None or "out" not in parent.outputs:
            return
        value = parent.outputs["out"]
        self.records.append((self.ctx.now, value.value, int(value.status)))

    def on_timer(self, tag: str) -> None:
        self._record()
        self.ctx.schedule(self, self.interval, "collect")


class NumericIntervalHistory(IntervalHistory):
    TYPE = "history:NumericIntervalHistoryExt"


class BooleanIntervalHistory(IntervalHistory):
    TYPE = "history:BooleanIntervalHistoryExt"
    KIND = BOOLEAN


class Inert(Block):
    """Components that carry no runtime behaviour (notes, history configs)."""


class WsTextBlock(Inert):
    TYPE = "baja:WsTextBlock"


class HistoryConfig(Inert):
    TYPE = "history:HistoryConfig"


# --- bactalkG36 module components (S-MODULE-1..5) -------------------------------------


@dataclass(frozen=True)
class KernelBinding:
    component: str
    kernel: str
    inputs: tuple[tuple[str, str], ...]
    """(slot, kind) in kernel argument order."""

    outputs: tuple[tuple[str, str], ...]
    params: tuple[tuple[str, str, str, object], ...]
    """(harness parameter, component property, encoding, default or None when required)."""

    period_only: bool = True
    """Kept for the record: since N7 every component steps only on the tick (S-MODULE-1)."""

    source_at_start: bool = False
    """The first output is the configured initial value, independent of the input."""

    resample: bool = False
    """Re-steps at the end of each tick's instant so a boundary sample is the settled value."""


_S = "seconds"
_D = "double"
_B = "boolean"
_T = "string"

KERNEL_BINDINGS: tuple[KernelBinding, ...] = (
    KernelBinding(
        "TrueDelay",
        "TrueDelay",
        (("in", BOOLEAN),),
        (("out", BOOLEAN),),
        (("delaySeconds", "delayTime", _S, 0.0), ("delayOnInit", "delayOnInit", _B, False)),
    ),
    KernelBinding(
        "Timer",
        "Timer",
        (("in", BOOLEAN),),
        (("elapsed", NUMERIC), ("passed", BOOLEAN)),
        (("thresholdSeconds", "threshold", _S, 0.0),),
    ),
    KernelBinding(
        "TimerWithReset",
        "TimerWithReset",
        (("in", BOOLEAN), ("reset", BOOLEAN)),
        (("elapsed", NUMERIC), ("passed", BOOLEAN)),
        (("thresholdSeconds", "threshold", _S, 0.0),),
    ),
    KernelBinding(
        "TimerAccumulating",
        "TimerAccumulating",
        (("in", BOOLEAN), ("reset", BOOLEAN)),
        (("elapsed", NUMERIC), ("passed", BOOLEAN)),
        (("thresholdSeconds", "threshold", _S, 0.0),),
    ),
    KernelBinding(
        "TrueFalseHold",
        "TrueFalseHold",
        (("in", BOOLEAN),),
        (("out", BOOLEAN),),
        (
            ("trueHoldSeconds", "trueHoldTime", _S, 0.0),
            ("falseHoldSeconds", "falseHoldTime", _S, 0.0),
        ),
    ),
    KernelBinding(
        "Pre",
        "Pre",
        (("in", BOOLEAN),),
        (("out", BOOLEAN),),
        (("initial", "initialValue", _B, False),),
        period_only=True,
        source_at_start=True,
    ),
    KernelBinding(
        "LimitSlewRate",
        "LimitSlewRate",
        (("in", NUMERIC),),
        (("out", NUMERIC),),
        (
            ("raisingSlewRate", "raisingSlewRate", _D, None),
            ("fallingSlewRate", "fallingSlewRate", _D, None),
            ("tdSeconds", "derivativeTime", _S, None),
            ("enable", "enable", _B, True),
        ),
    ),
    KernelBinding(
        "Round",
        "Round",
        (("in", NUMERIC),),
        (("out", NUMERIC),),
        (),
    ),
    KernelBinding(
        "UnitDelay",
        "UnitDelay",
        (("in", NUMERIC),),
        (("out", NUMERIC),),
        (("samplePeriodSeconds", "samplePeriod", _S, None), ("initial", "initialValue", _D, 0.0)),
        source_at_start=True,
        resample=True,
    ),
    KernelBinding(
        "FirstOrderHold",
        "FirstOrderHold",
        (("in", NUMERIC),),
        (("out", NUMERIC),),
        (("samplePeriodSeconds", "samplePeriod", _S, None),),
        resample=True,
    ),
    KernelBinding(
        "MovingAverage",
        "MovingAverage",
        (("in", NUMERIC),),
        (("out", NUMERIC),),
        (("windowSeconds", "window", _S, None),),
    ),
    KernelBinding(
        "PIDWithReset",
        "PidWithReset",
        (("setpoint", NUMERIC), ("measurement", NUMERIC), ("trigger", BOOLEAN)),
        (("out", NUMERIC),),
        (
            ("controllerType", "controllerType", _T, "PI"),
            ("reverseActing", "reverseActing", _B, False),
            ("k", "k", _D, 1.0),
            ("ti", "ti", _D, 0.5),
            ("td", "td", _D, 0.1),
            ("r", "r", _D, 1.0),
            ("ni", "ni", _D, 0.9),
            ("nd", "nd", _D, 10.0),
            ("yMin", "yMin", _D, 0.0),
            ("yMax", "yMax", _D, 1.0),
            ("xiStart", "xiStart", _D, 0.0),
            ("ydStart", "ydStart", _D, 0.0),
            ("yReset", "yReset", _D, 0.0),
        ),
    ),
    KernelBinding(
        "TrimAndRespond",
        "TrimAndRespond",
        (("requestCount", NUMERIC), ("deviceOn", BOOLEAN), ("hold", BOOLEAN)),
        (("out", NUMERIC),),
        (
            ("initialSetpoint", "initialSetpoint", _D, None),
            ("minimumSetpoint", "minimumSetpoint", _D, None),
            ("maximumSetpoint", "maximumSetpoint", _D, None),
            ("delaySeconds", "delayTime", _S, None),
            ("samplePeriodSeconds", "samplePeriod", _S, None),
            ("ignoredRequests", "ignoredRequests", _D, None),
            ("trimAmount", "trimAmount", _D, None),
            ("respondAmount", "respondAmount", _D, None),
            ("maximumResponse", "maximumResponse", _D, None),
            ("holdEnabled", "holdEnabled", _B, False),
            ("holdDurationSeconds", "holdDuration", _S, 0.0),
        ),
        resample=True,
    ),
    KernelBinding(
        "BooleanInitialization",
        "BooleanInitialization",
        (("in", BOOLEAN),),
        (("out", BOOLEAN),),
        (("initial", "initialValue", _B, False),),
        source_at_start=True,
    ),
    KernelBinding(
        "NumericChange",
        "NumericChange",
        (("in", NUMERIC),),
        (("out", BOOLEAN),),
        (("mode", "mode", _T, "changed"), ("initial", "initialValue", _D, 0.0)),
        period_only=True,
    ),
    KernelBinding(
        "RisingEdge",
        "RisingEdge",
        (("in", BOOLEAN),),
        (("out", BOOLEAN),),
        (("initial", "initialValue", _B, False),),
        period_only=True,
    ),
    KernelBinding(
        "FallingEdge",
        "FallingEdge",
        (("in", BOOLEAN),),
        (("out", BOOLEAN),),
        (("initial", "initialValue", _B, False),),
        period_only=True,
    ),
    KernelBinding(
        "SetReset",
        "SetReset",
        (("set", BOOLEAN), ("clear", BOOLEAN)),
        (("out", BOOLEAN),),
        (),
        period_only=True,
    ),
    KernelBinding(
        "Sampler",
        "Sampler",
        (("in", NUMERIC),),
        (("out", NUMERIC),),
        (("samplePeriodSeconds", "samplePeriod", _S, None),),
        period_only=True,
        resample=True,
    ),
    KernelBinding(
        "SampleTrigger",
        "SampleTrigger",
        (),
        (("out", BOOLEAN),),
        (("periodSeconds", "period", _S, None), ("shiftSeconds", "shift", _S, 0.0)),
        period_only=True,
        source_at_start=True,
    ),
    KernelBinding(
        "Hysteresis",
        "Hysteresis",
        (("in", NUMERIC),),
        (("out", BOOLEAN),),
        (
            ("uLow", "uLow", _D, None),
            ("uHigh", "uHigh", _D, None),
            ("initial", "initialValue", _B, False),
        ),
        period_only=True,
    ),
)

KERNEL_BINDINGS_BY_COMPONENT: Mapping[str, KernelBinding] = {
    item.component: item for item in KERNEL_BINDINGS
}


class ModuleBlock(Block):
    """One ``bactalkG36`` component: a kernel stepped every executionPeriod (tick only)."""

    BINDING: KernelBinding

    def configure(self) -> None:
        binding = self.BINDING
        params: dict[str, object] = {}
        for harness_name, prop_name, encoding, default in binding.params:
            prop = self.node.prop(prop_name)
            if prop is None or prop.value is None:
                if default is None:
                    raise ValueError(
                        f"{self.path} ({self.node.type}) lacks the required property {prop_name}"
                    )
                params[harness_name] = default
                continue
            raw = prop.value
            if encoding == _S:
                params[harness_name] = parse_number(raw) / 1000.0
            elif encoding == _D:
                params[harness_name] = parse_number(raw)
            elif encoding == _B:
                params[harness_name] = raw.strip().lower() == "true"
            else:
                params[harness_name] = raw
        self.params = params
        self.kernel = self.ctx.kernels.open(binding.kernel, params)
        period = self.node.seconds("executionPeriod", 1.0)
        override = self.ctx.policy.module_period_seconds
        self.period = override if override is not None else period
        self.started_at = 0.0
        self._valid_inputs = [slot for slot, _ in binding.inputs]
        if binding.component == "TrimAndRespond" and not bool(params.get("holdEnabled")):
            self._valid_inputs = [slot for slot in self._valid_inputs if slot != "hold"]
        for slot, kind in binding.outputs:
            # The wrapper's outputs start ok with the type's zero value.
            self.outputs[slot] = StatusValue(0.0 if kind == NUMERIC else False, Status.OK)

    def executes_on_input_change(self) -> bool:
        return False  # S-MODULE-1: every module component samples its inputs on the tick only

    def start(self) -> None:
        self.started_at = self.ctx.now
        if self.period > 0.0:
            self.ctx.schedule(self, self.period, "tick")
        if self.BINDING.resample:
            self.ctx.schedule(self, 0.0, "resample", late=True)

    def on_timer(self, tag: str) -> None:
        self.execute()
        if tag == "resample":
            return
        if self.period > 0.0:
            self.ctx.schedule(self, self.period, "tick")
        if self.BINDING.resample:
            # S-MODULE-6: sample again once everything due at this instant has run.
            self.ctx.schedule(self, 0.0, "resample", late=True)

    def execute(self) -> None:
        if any(not self.inputs[slot].valid for slot in self._valid_inputs):
            for slot, _ in self.BINDING.outputs:  # S-MODULE-3
                self.emit_null(slot)
            return
        args = [self.inputs[slot].value for slot, _ in self.BINDING.inputs]
        time_seconds = max(0.0, self.ctx.now - self.started_at)
        results = self.kernel.step(time_seconds, args)
        for (slot, kind), value in zip(self.BINDING.outputs, results, strict=True):
            self.emit(
                slot, StatusValue(float(value) if kind == NUMERIC else bool(value), Status.OK)
            )


def _module_class(binding: KernelBinding) -> type[ModuleBlock]:
    return type(
        f"Module{binding.component}",
        (ModuleBlock,),
        {
            "TYPE": f"bactalkG36:{binding.component}",
            "INPUTS": dict(binding.inputs),
            "OUTPUTS": dict(binding.outputs),
            "BINDING": binding,
            "SOURCE_AT_START": binding.source_at_start,
            "__doc__": (
                f"bactalkG36:{binding.component} through the {binding.kernel} kernel "
                "(S-MODULE-1..5)."
            ),
        },
    )


MODULE_BLOCKS: tuple[type[ModuleBlock], ...] = tuple(
    _module_class(binding) for binding in KERNEL_BINDINGS
)


# --- registry ---------------------------------------------------------------------------

STOCK_BLOCKS: tuple[type[Block], ...] = (
    NumericConst,
    BooleanConst,
    NumericWritable,
    BooleanWritable,
    Add,
    Subtract,
    Multiply,
    Divide,
    Minimum,
    Maximum,
    Average,
    GreaterThan,
    GreaterThanEqual,
    LessThan,
    LessThanEqual,
    Equal,
    NotEqual,
    And,
    Or,
    Xor,
    Not,
    NumericSwitch,
    BooleanSwitch,
    NumericLatch,
    BooleanLatch,
    OneShot,
    BooleanDelay,
    MultiVibrator,
    Tstat,
    Reset,
    LoopPoint,
    BooleanSchedule,
    NumericSchedule,
    NumericIntervalHistory,
    BooleanIntervalHistory,
    WsTextBlock,
    HistoryConfig,
)

REGISTRY: Mapping[str, type[Block]] = {cls.TYPE: cls for cls in (*STOCK_BLOCKS, *MODULE_BLOCKS)}


def known_types() -> tuple[str, ...]:
    return tuple(REGISTRY)


# --- kernel backends ------------------------------------------------------------------------


class PythonKernels:
    """Kernel backend over the Python ports (docs/decisions/007)."""

    name = "python"

    def open(self, kernel: str, params: Mapping[str, object]) -> KernelInstance:
        from bactalk.niagara.shadow.kernels import build_kernel

        instance = build_kernel(kernel, dict(params))

        class _Instance:
            def step(
                self, time_seconds: float, inputs: Sequence[float | bool]
            ) -> tuple[float | bool, ...]:
                return instance.step(time_seconds, *inputs)

        return _Instance()

    def close(self) -> None:
        pass


class JvmKernels:
    """Kernel backend over the Java kernels in a sidecar process."""

    name = "jvm"

    def __init__(self) -> None:
        from bactalk.niagara.shadow.sidecar import KernelSidecar

        self.sidecar = KernelSidecar()

    def open(self, kernel: str, params: Mapping[str, object]) -> KernelInstance:
        ident = self.sidecar.open(kernel, params)
        sidecar = self.sidecar

        class _Instance:
            def step(
                self, time_seconds: float, inputs: Sequence[float | bool]
            ) -> tuple[float | bool, ...]:
                return sidecar.step(ident, time_seconds, inputs)

        return _Instance()

    def close(self) -> None:
        self.sidecar.close()


def make_kernel_backend(name: str = "auto") -> KernelBackend:
    if name == "python":
        return PythonKernels()
    if name == "jvm":
        return JvmKernels()
    if name == "auto":
        from bactalk.niagara.shadow.sidecar import sidecar_available

        return JvmKernels() if sidecar_available() else PythonKernels()
    raise ValueError(f"unknown kernel backend {name!r} (python, jvm or auto)")


def shuffled(items: list[Any], seed: int) -> list[Any]:
    copy = list(items)
    random.Random(seed).shuffle(copy)
    return copy


__all__ = [
    "BOOLEAN",
    "KERNEL_BINDINGS",
    "KERNEL_BINDINGS_BY_COMPONENT",
    "MODULE_BLOCKS",
    "NUMERIC",
    "REGISTRY",
    "STOCK_BLOCKS",
    "Block",
    "Context",
    "JvmKernels",
    "KernelBackend",
    "KernelBinding",
    "ModuleBlock",
    "PythonKernels",
    "WritablePoint",
    "known_types",
    "make_kernel_backend",
]
