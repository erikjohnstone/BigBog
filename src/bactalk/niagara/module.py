"""The ``bactalkG36`` Niagara module as BACTalk knows it (GOAL-NATIVE-BOG.md N3).

One :class:`~bactalk.niagara.catalog.TypeSpec` per component, so the static
validator can accept ``bactalkG36:*`` types (``validate_bog(declared_types=
declared_types())``) and the native emitter (N4) knows each component's slots and
how a block's IR configuration maps onto its parameter properties.

The Java sources under ``niagara-module/bactalkG36`` are the source of truth for
slot names; ``tests/test_native_bog_kernels.py`` fails when this registry drifts
from them or from ``module-include.xml``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from bactalk.domain import BlockKind
from bactalk.niagara.catalog import DATA_KINDS, SlotSpec, TypeSpec
from bactalk.niagara.lowering import MODULE_NAME

MODULE_ORIGIN = "bactalkG36"

_STATUS_NUMERIC = "baja:StatusNumeric"
_STATUS_BOOLEAN = "baja:StatusBoolean"
_REL_TIME = "baja:RelTime"
_DOUBLE = "baja:Double"
_BOOLEAN = "baja:Boolean"
_STRING = "baja:String"

# Every component carries the base class's execution slots.
_BASE_SLOTS: tuple[tuple[str, str, str], ...] = (("executionPeriod", _REL_TIME, "parameter"),)


@dataclass(frozen=True)
class ParameterBinding:
    """How one component property is filled from a block's IR configuration."""

    property: str
    config_key: str | None
    encoding: str
    """``seconds`` (IR seconds to RelTime), ``double``, ``boolean``, ``string`` or ``const``."""

    default: object = None


@dataclass(frozen=True)
class ComponentSpec:
    name: str
    java_class: str
    kinds: tuple[BlockKind, ...]
    slots: tuple[tuple[str, str, str], ...]
    """(slot, value type, direction) with direction input, output or parameter."""

    bindings: tuple[ParameterBinding, ...]
    input_map: Mapping[str, str]
    """IR input slot -> component slot."""

    output_map: Mapping[str, str]
    """IR output slot -> component slot."""

    @property
    def type_key(self) -> str:
        return f"{MODULE_NAME}:{self.name}"

    def type_spec(self) -> TypeSpec:
        slots = {}
        for slot, value_type, direction in (*_BASE_SLOTS, *self.slots):
            slots[slot] = SlotSpec(
                name=slot,
                value_type=value_type,
                data_kind=DATA_KINDS.get(value_type),
                direction=direction if direction != "parameter" else "input",
                origins=(MODULE_ORIGIN,),
            )
        return TypeSpec(
            type=self.type_key,
            module=MODULE_NAME,
            name=self.name,
            origin=MODULE_ORIGIN,
            dynamic_slots=False,
            slots=MappingProxyType(slots),
            sources=(f"niagara-module/bactalkG36/bactalkG36-rt/src/{self.java_class}.java",),
        )


def _seconds(prop: str, key: str, default: float | None = None) -> ParameterBinding:
    return ParameterBinding(prop, key, "seconds", default)


def _double(prop: str, key: str, default: float | None = None) -> ParameterBinding:
    return ParameterBinding(prop, key, "double", default)


def _boolean(prop: str, key: str, default: bool | None = None) -> ParameterBinding:
    return ParameterBinding(prop, key, "boolean", default)


def _string(prop: str, key: str, default: str | None = None) -> ParameterBinding:
    return ParameterBinding(prop, key, "string", default)


def _map(**pairs: str) -> Mapping[str, str]:
    return MappingProxyType(dict(pairs))


_TIMER_SLOTS = (
    ("in", _STATUS_BOOLEAN, "input"),
    ("elapsed", _STATUS_NUMERIC, "output"),
    ("passed", _STATUS_BOOLEAN, "output"),
    ("threshold", _REL_TIME, "parameter"),
)
_RESET_TIMER_SLOTS = (
    ("in", _STATUS_BOOLEAN, "input"),
    ("reset", _STATUS_BOOLEAN, "input"),
    ("elapsed", _STATUS_NUMERIC, "output"),
    ("passed", _STATUS_BOOLEAN, "output"),
    ("threshold", _REL_TIME, "parameter"),
)

COMPONENTS: tuple[ComponentSpec, ...] = (
    ComponentSpec(
        "TrueDelay",
        "com/bactalk/g36/BTrueDelay",
        (BlockKind.BOOLEAN_DELAY,),
        (
            ("in", _STATUS_BOOLEAN, "input"),
            ("out", _STATUS_BOOLEAN, "output"),
            ("delayTime", _REL_TIME, "parameter"),
            ("delayOnInit", _BOOLEAN, "parameter"),
        ),
        (
            _seconds("delayTime", "on_delay_seconds"),
            _boolean("delayOnInit", "delay_on_init", False),
        ),
        _map(**{"in": "in"}),
        _map(out="out"),
    ),
    ComponentSpec(
        "Timer",
        "com/bactalk/g36/BTimer",
        (BlockKind.TIMER,),
        _TIMER_SLOTS,
        (_seconds("threshold", "threshold_seconds", 0.0),),
        _map(**{"in": "in"}),
        _map(elapsed="elapsed", passed="passed"),
    ),
    ComponentSpec(
        "TimerWithReset",
        "com/bactalk/g36/BTimerWithReset",
        (BlockKind.TIMER_WITH_RESET,),
        _RESET_TIMER_SLOTS,
        (_seconds("threshold", "threshold_seconds", 0.0),),
        _map(**{"in": "in", "reset": "reset"}),
        _map(elapsed="elapsed", passed="passed"),
    ),
    ComponentSpec(
        "TimerAccumulating",
        "com/bactalk/g36/BTimerAccumulating",
        (BlockKind.TIMER_ACCUMULATING,),
        _RESET_TIMER_SLOTS,
        (_seconds("threshold", "threshold_seconds", 0.0),),
        _map(**{"in": "in", "reset": "reset"}),
        _map(elapsed="elapsed", passed="passed"),
    ),
    ComponentSpec(
        "TrueFalseHold",
        "com/bactalk/g36/BTrueFalseHold",
        (BlockKind.BOOLEAN_TRUE_FALSE_HOLD,),
        (
            ("in", _STATUS_BOOLEAN, "input"),
            ("out", _STATUS_BOOLEAN, "output"),
            ("trueHoldTime", _REL_TIME, "parameter"),
            ("falseHoldTime", _REL_TIME, "parameter"),
        ),
        (
            _seconds("trueHoldTime", "true_hold_seconds"),
            _seconds("falseHoldTime", "false_hold_seconds"),
        ),
        _map(**{"in": "in"}),
        _map(out="out"),
    ),
    ComponentSpec(
        "Pre",
        "com/bactalk/g36/BPre",
        (BlockKind.BOOLEAN_PRE_HOST_TICK,),
        (
            ("in", _STATUS_BOOLEAN, "input"),
            ("out", _STATUS_BOOLEAN, "output"),
            ("initialValue", _BOOLEAN, "parameter"),
        ),
        (_boolean("initialValue", "initial", False),),
        _map(**{"in": "in"}),
        _map(out="out"),
    ),
    ComponentSpec(
        "UnitDelay",
        "com/bactalk/g36/BUnitDelay",
        (BlockKind.NUMERIC_UNIT_DELAY,),
        (
            ("in", _STATUS_NUMERIC, "input"),
            ("out", _STATUS_NUMERIC, "output"),
            ("samplePeriod", _REL_TIME, "parameter"),
            ("initialValue", _DOUBLE, "parameter"),
        ),
        (
            _seconds("samplePeriod", "sample_period_seconds"),
            _double("initialValue", "initial", 0.0),
        ),
        _map(**{"in": "in"}),
        _map(out="out"),
    ),
    ComponentSpec(
        "FirstOrderHold",
        "com/bactalk/g36/BFirstOrderHold",
        (BlockKind.NUMERIC_FIRST_ORDER_HOLD,),
        (
            ("in", _STATUS_NUMERIC, "input"),
            ("out", _STATUS_NUMERIC, "output"),
            ("samplePeriod", _REL_TIME, "parameter"),
        ),
        (_seconds("samplePeriod", "sample_period_seconds"),),
        _map(**{"in": "in"}),
        _map(out="out"),
    ),
    ComponentSpec(
        "MovingAverage",
        "com/bactalk/g36/BMovingAverage",
        (BlockKind.MOVING_AVERAGE,),
        (
            ("in", _STATUS_NUMERIC, "input"),
            ("out", _STATUS_NUMERIC, "output"),
            ("window", _REL_TIME, "parameter"),
        ),
        (_seconds("window", "window_seconds"),),
        _map(**{"in": "in"}),
        _map(out="out"),
    ),
    ComponentSpec(
        "PIDWithReset",
        "com/bactalk/g36/BPidWithReset",
        (BlockKind.PID_WITH_RESET,),
        (
            ("setpoint", _STATUS_NUMERIC, "input"),
            ("measurement", _STATUS_NUMERIC, "input"),
            ("trigger", _STATUS_BOOLEAN, "input"),
            ("out", _STATUS_NUMERIC, "output"),
            ("controllerType", _STRING, "parameter"),
            ("reverseActing", _BOOLEAN, "parameter"),
            ("k", _DOUBLE, "parameter"),
            ("ti", _DOUBLE, "parameter"),
            ("td", _DOUBLE, "parameter"),
            ("r", _DOUBLE, "parameter"),
            ("ni", _DOUBLE, "parameter"),
            ("nd", _DOUBLE, "parameter"),
            ("yMin", _DOUBLE, "parameter"),
            ("yMax", _DOUBLE, "parameter"),
            ("xiStart", _DOUBLE, "parameter"),
            ("ydStart", _DOUBLE, "parameter"),
            ("yReset", _DOUBLE, "parameter"),
        ),
        (
            _string("controllerType", "controller_type", "PI"),
            _boolean("reverseActing", "reverse_acting", True),
            _double("k", "k", 1.0),
            _double("ti", "ti", 0.5),
            _double("td", "td", 0.1),
            _double("r", "r", 1.0),
            _double("ni", "ni", 0.9),
            _double("nd", "nd", 10.0),
            _double("yMin", "y_min", 0.0),
            _double("yMax", "y_max", 1.0),
            _double("xiStart", "xi_start", 0.0),
            _double("ydStart", "yd_start", 0.0),
            _double("yReset", "y_reset", 0.0),
        ),
        _map(setpoint="setpoint", measurement="measurement", trigger="trigger"),
        _map(out="out"),
    ),
    ComponentSpec(
        "TrimAndRespond",
        "com/bactalk/g36/BTrimAndRespond",
        (BlockKind.TRIM_AND_RESPOND, BlockKind.TRIM_AND_RESPOND_HOLD),
        (
            ("requestCount", _STATUS_NUMERIC, "input"),
            ("deviceOn", _STATUS_BOOLEAN, "input"),
            ("hold", _STATUS_BOOLEAN, "input"),
            ("out", _STATUS_NUMERIC, "output"),
            ("initialSetpoint", _DOUBLE, "parameter"),
            ("minimumSetpoint", _DOUBLE, "parameter"),
            ("maximumSetpoint", _DOUBLE, "parameter"),
            ("delayTime", _REL_TIME, "parameter"),
            ("samplePeriod", _REL_TIME, "parameter"),
            ("ignoredRequests", _DOUBLE, "parameter"),
            ("trimAmount", _DOUBLE, "parameter"),
            ("respondAmount", _DOUBLE, "parameter"),
            ("maximumResponse", _DOUBLE, "parameter"),
            ("holdEnabled", _BOOLEAN, "parameter"),
            ("holdDuration", _REL_TIME, "parameter"),
        ),
        (
            _double("initialSetpoint", "initial_setpoint"),
            _double("minimumSetpoint", "minimum_setpoint"),
            _double("maximumSetpoint", "maximum_setpoint"),
            _seconds("delayTime", "delay_seconds"),
            _seconds("samplePeriod", "sample_period_seconds"),
            _double("ignoredRequests", "ignored_requests"),
            _double("trimAmount", "trim_amount"),
            _double("respondAmount", "respond_amount"),
            _double("maximumResponse", "maximum_response"),
            _boolean("holdEnabled", "hold_enabled", False),
            _seconds("holdDuration", "hold_duration_seconds", 0.0),
        ),
        _map(request_count="requestCount", device_on="deviceOn", hold="hold"),
        _map(out="out"),
    ),
    ComponentSpec(
        "BooleanInitialization",
        "com/bactalk/g36/BBooleanInitialization",
        (BlockKind.BOOLEAN_INITIALIZATION,),
        (
            ("in", _STATUS_BOOLEAN, "input"),
            ("out", _STATUS_BOOLEAN, "output"),
            ("initialValue", _BOOLEAN, "parameter"),
        ),
        (_boolean("initialValue", "initial", False),),
        _map(**{"in": "in"}),
        _map(out="out"),
    ),
    ComponentSpec(
        "NumericChange",
        "com/bactalk/g36/BNumericChange",
        (BlockKind.NUMERIC_CHANGED, BlockKind.NUMERIC_INCREASED, BlockKind.NUMERIC_DECREASED),
        (
            ("in", _STATUS_NUMERIC, "input"),
            ("out", _STATUS_BOOLEAN, "output"),
            ("mode", _STRING, "parameter"),
            ("initialValue", _DOUBLE, "parameter"),
        ),
        (
            ParameterBinding("mode", None, "const", "changed"),
            _double("initialValue", "initial", 0.0),
        ),
        _map(**{"in": "in"}),
        _map(out="out"),
    ),
)

_TICK_NOTE = "steps only on the execution period (host-tick semantics)"

COMPONENTS = (
    *COMPONENTS,
    ComponentSpec(
        "RisingEdge",
        "com/bactalk/g36/BRisingEdge",
        (BlockKind.ONE_SHOT,),
        (
            ("in", _STATUS_BOOLEAN, "input"),
            ("out", _STATUS_BOOLEAN, "output"),
            ("initialValue", _BOOLEAN, "parameter"),
        ),
        (_boolean("initialValue", "initial", False),),
        _map(**{"in": "in"}),
        _map(out="out"),
    ),
    ComponentSpec(
        "FallingEdge",
        "com/bactalk/g36/BFallingEdge",
        (BlockKind.BOOLEAN_FALLING_EDGE,),
        (
            ("in", _STATUS_BOOLEAN, "input"),
            ("out", _STATUS_BOOLEAN, "output"),
            ("initialValue", _BOOLEAN, "parameter"),
        ),
        (_boolean("initialValue", "pre_u_start", False),),
        _map(**{"in": "in"}),
        _map(out="out"),
    ),
    ComponentSpec(
        "SetReset",
        "com/bactalk/g36/BSetReset",
        (BlockKind.BOOLEAN_SET_RESET,),
        (
            ("set", _STATUS_BOOLEAN, "input"),
            ("clear", _STATUS_BOOLEAN, "input"),
            ("out", _STATUS_BOOLEAN, "output"),
        ),
        (),
        _map(set="set", clear="clear"),
        _map(out="out"),
    ),
    ComponentSpec(
        "Sampler",
        "com/bactalk/g36/BSampler",
        (BlockKind.NUMERIC_SAMPLER,),
        (
            ("in", _STATUS_NUMERIC, "input"),
            ("out", _STATUS_NUMERIC, "output"),
            ("samplePeriod", _REL_TIME, "parameter"),
        ),
        (_seconds("samplePeriod", "sample_period_seconds"),),
        _map(**{"in": "in"}),
        _map(out="out"),
    ),
    ComponentSpec(
        "SampleTrigger",
        "com/bactalk/g36/BSampleTrigger",
        (BlockKind.BOOLEAN_SAMPLE_TRIGGER,),
        (
            ("out", _STATUS_BOOLEAN, "output"),
            ("period", _REL_TIME, "parameter"),
            ("shift", _REL_TIME, "parameter"),
        ),
        (_seconds("period", "period_seconds"), _seconds("shift", "shift_seconds", 0.0)),
        _map(),
        _map(out="out"),
    ),
    ComponentSpec(
        "Hysteresis",
        "com/bactalk/g36/BHysteresis",
        (BlockKind.HYSTERESIS,),
        (
            ("in", _STATUS_NUMERIC, "input"),
            ("out", _STATUS_BOOLEAN, "output"),
            ("uLow", _DOUBLE, "parameter"),
            ("uHigh", _DOUBLE, "parameter"),
            ("initialValue", _BOOLEAN, "parameter"),
        ),
        (
            _double("uLow", "u_low"),
            _double("uHigh", "u_high"),
            _boolean("initialValue", "initial", False),
        ),
        _map(**{"in": "in"}),
        _map(out="out"),
    ),
)

COMPONENTS_BY_NAME: Mapping[str, ComponentSpec] = MappingProxyType(
    {component.name: component for component in COMPONENTS}
)
COMPONENTS_BY_KIND: Mapping[BlockKind, ComponentSpec] = MappingProxyType(
    {kind: component for component in COMPONENTS for kind in component.kinds}
)

# The change detector's mode is fixed by the IR kind, not by configuration.
CHANGE_MODES: Mapping[BlockKind, str] = MappingProxyType(
    {
        BlockKind.NUMERIC_CHANGED: "changed",
        BlockKind.NUMERIC_INCREASED: "increased",
        BlockKind.NUMERIC_DECREASED: "decreased",
    }
)


def declared_types() -> tuple[TypeSpec, ...]:
    """Every ``bactalkG36`` type, for ``validate_bog(declared_types=...)``."""

    return tuple(component.type_spec() for component in COMPONENTS)
