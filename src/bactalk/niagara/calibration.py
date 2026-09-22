"""Calibration kit for Gate G-WB (GOAL-NATIVE-BOG.md N7, item 6).

One small ``.bog`` per ASSUMED rule in ``docs/niagara-semantics.md``: writable
input points a human drives from Workbench (override at level 8, or auto to fall
back to a null fallback), the blocks under test, and output points with a
one-second interval history each. The Shadow Runtime runs the same script and its
history records are the expected trace. ``compare_evidence`` reads the histories
a human exported from a real station and marks each rule VERIFIED or
CONTRADICTED; ``annotate_document`` writes the verdicts into the semantics
document.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bactalk.niagara.shadow.blocks import IntervalHistory
from bactalk.niagara.shadow.builder import (
    BogBuilder,
    Prop,
    double,
    raw,
    rel_time,
    status_boolean,
    status_numeric,
)
from bactalk.niagara.shadow.engine import ShadowRuntime
from bactalk.niagara.shadow.policy import DEFAULT_POLICY, ExecutionPolicy
from bactalk.niagara.shadow.status import Status

HISTORY_INTERVAL_SECONDS = 1.0
"""Interval of every observation history; Niagara's interval extension minimum."""

TIME_TOLERANCE_SECONDS = 1.5
"""A Niagara history sample within this of an expected instant is compared with it."""


@dataclass(frozen=True)
class Step:
    time_seconds: float
    action: str
    """``override`` (level 8 with ``value``) or ``auto`` (remove the override)."""

    point: str
    value: float | bool | None = None

    def describe(self) -> str:
        if self.action == "override":
            return f"t={self.time_seconds:g}s: override Inputs/{self.point} to {self.value!r}"
        return f"t={self.time_seconds:g}s: auto Inputs/{self.point} (remove the override)"


@dataclass(frozen=True)
class Calibration:
    id: str
    title: str
    build: Callable[[], bytes]
    steps: tuple[Step, ...]
    observe: tuple[str, ...]
    """Output point names (under ``Outputs``) whose histories are compared."""

    duration_seconds: float
    what_to_look_for: str
    station_testable: bool = True
    """False for runtime conventions that no station can confirm or deny."""

    @property
    def folder(self) -> str:
        return self.id.lower()


# --- builders ---------------------------------------------------------------------------

_NUM = "c:NumericWritable"
_BOOL = "c:BooleanWritable"


class Kit:
    """A BogBuilder with the kit's conventions: Inputs, Logic, Outputs with histories."""

    def __init__(self, name: str) -> None:
        self.builder = BogBuilder(name)

    def numeric_input(self, name: str, fallback: float | None) -> str:
        props = [
            status_numeric(
                "fallback",
                0.0 if fallback is None else fallback,
                "{null}" if fallback is None else None,
            )
        ]
        return self.builder.add("Inputs", name, _NUM, props)

    def boolean_input(self, name: str, fallback: bool | None) -> str:
        props = [status_boolean("fallback", bool(fallback), "{null}" if fallback is None else None)]
        return self.builder.add("Inputs", name, _BOOL, props)

    def block(self, name: str, type_spec: str, props: list[Prop] | None = None) -> str:
        return self.builder.add("Logic", name, type_spec, props or [])

    def link(self, source: str, source_slot: str, target: str, target_slot: str) -> None:
        self.builder.link(source, source_slot, target, target_slot)

    def observe_numeric(
        self, name: str, source: str, source_slot: str = "out", fallback: float = 99.0
    ) -> str:
        key = self.builder.add("Outputs", name, _NUM, [status_numeric("fallback", fallback)])
        self.builder.link(source, source_slot, key, "in16")
        self._history(key, "history:NumericIntervalHistoryExt")
        return key

    def observe_boolean(
        self, name: str, source: str, source_slot: str = "out", fallback: bool = False
    ) -> str:
        key = self.builder.add("Outputs", name, _BOOL, [status_boolean("fallback", fallback)])
        self.builder.link(source, source_slot, key, "in16")
        self._history(key, "history:BooleanIntervalHistoryExt")
        return key

    def _history(self, point: str, type_spec: str) -> None:
        ext = self.builder.add(
            point.split("/")[0], f"{point.split('/')[1]}History", type_spec, parent=point
        )
        millis = int(HISTORY_INTERVAL_SECONDS * 1000)
        self.builder.add(
            point.split("/")[0],
            "historyConfig",
            "history:HistoryConfig",
            [raw("interval", f"false:{millis}", "history:CollectionInterval")],
            parent=ext,
        )

    def build(self) -> bytes:
        return self.builder.build()


def _status_4() -> bytes:
    kit = Kit("S_STATUS_4")
    kit.numeric_input("a", None)  # fallback null: auto leaves the point null
    kit.numeric_input("b", 2.0)
    add = kit.block("add", "kitControl:Add")
    kit.link("Inputs/a", "out", add, "inA")
    kit.link("Inputs/b", "out", add, "inB")
    kit.observe_numeric("sum", add)
    return kit.build()


def _status_5_logic_2() -> bytes:
    kit = Kit("S_STATUS_5")
    kit.boolean_input("b", None)
    inverter = kit.block("not", "kitControl:Not")
    kit.link("Inputs/b", "out", inverter, "in")
    kit.observe_boolean("notOut", inverter, fallback=True)
    return kit.build()


def _status_6_link_2() -> bytes:
    kit = Kit("S_STATUS_6")
    one = kit.block("one", "kitControl:NumericConst", [status_numeric("out", 1.0)])
    two = kit.block("two", "kitControl:NumericConst", [status_numeric("out", 2.0)])
    add = kit.block("add", "kitControl:Add")
    kit.link(one, "out", add, "inA")
    kit.link(two, "out", add, "inB")
    clock = kit.block("clock", "kitControl:BooleanConst", [status_boolean("out", True)])
    latch = kit.block("latch", "kitControl:NumericLatch")
    kit.link(add, "out", latch, "in")
    kit.link(clock, "out", latch, "clock")
    kit.observe_numeric("latched", latch)
    return kit.build()


def _math_2() -> bytes:
    kit = Kit("S_MATH_2")
    kit.numeric_input("a", None)
    kit.numeric_input("b", None)
    sub = kit.block("sub", "kitControl:Subtract")
    kit.link("Inputs/a", "out", sub, "inA")
    kit.link("Inputs/b", "out", sub, "inB")
    kit.observe_numeric("difference", sub)
    return kit.build()


def _math_3_writable_5() -> bytes:
    kit = Kit("S_MATH_3")
    kit.numeric_input("a", 10.0)
    kit.numeric_input("b", 2.0)
    div = kit.block("div", "kitControl:Divide")
    kit.link("Inputs/a", "out", div, "inA")
    kit.link("Inputs/b", "out", div, "inB")
    big = kit.block("big", "kitControl:NumericConst", [status_numeric("out", 1.0e6)])
    clamp = kit.block("clamp", "kitControl:Minimum")
    kit.link(div, "out", clamp, "inA")
    kit.link(big, "out", clamp, "inB")
    kit.observe_numeric("quotient", clamp)
    kit.observe_numeric("quotientStatus", div)
    return kit.build()


def _cmp_1() -> bytes:
    kit = Kit("S_CMP_1")
    kit.numeric_input("a", 5.0)
    kit.numeric_input("b", None)
    gt = kit.block("gt", "kitControl:GreaterThan")
    kit.link("Inputs/a", "out", gt, "inA")
    kit.link("Inputs/b", "out", gt, "inB")
    kit.observe_boolean("greater", gt, fallback=True)
    return kit.build()


def _latch_2() -> bytes:
    kit = Kit("S_LATCH_2")
    kit.numeric_input("a", 7.0)
    kit.boolean_input("clock", False)
    latch = kit.block("latch", "kitControl:NumericLatch")
    kit.link("Inputs/a", "out", latch, "in")
    kit.link("Inputs/clock", "out", latch, "clock")
    kit.observe_numeric("latched", latch)
    return kit.build()


def _oneshot_2() -> bytes:
    kit = Kit("S_ONESHOT_2")
    kit.boolean_input("trigger", False)
    pulse = kit.block("pulse", "kitControl:OneShot")  # pulseWidth deliberately unset
    kit.link("Inputs/trigger", "out", pulse, "in")
    kit.observe_boolean("pulse", pulse)
    return kit.build()


def _oneshot_3() -> bytes:
    kit = Kit("S_ONESHOT_3")
    clock = kit.block("clock", "kitControl:MultiVibrator", [rel_time("period", 0.6)])
    pulse = kit.block("pulse", "kitControl:OneShot", [rel_time("pulseWidth", 2.0)])
    kit.link(clock, "out", pulse, "in")
    kit.observe_boolean("retriggered", pulse)
    return kit.build()


def _mv_2() -> bytes:
    kit = Kit("S_MV_2")
    clock = kit.block("clock", "kitControl:MultiVibrator", [rel_time("period", 20.0)])
    kit.observe_boolean("clock", clock)
    return kit.build()


def _tstat_2_3() -> bytes:
    kit = Kit("S_TSTAT_2")
    kit.numeric_input("cv", None)
    tstat = kit.block(
        "tstat", "kitControl:Tstat", [status_numeric("sp", 20.0), status_numeric("diff", 2.0)]
    )
    kit.link("Inputs/cv", "out", tstat, "cv")
    kit.observe_boolean("call", tstat, fallback=True)
    return kit.build()


def _reset_2() -> bytes:
    kit = Kit("S_RESET_2")
    kit.numeric_input("a", 5.0)
    reset = kit.block(
        "reset",
        "kitControl:Reset",
        [
            status_numeric("inputLowLimit", 1.0),
            status_numeric("inputHighLimit", 1.0),
            status_numeric("outputLowLimit", 30.0),
            status_numeric("outputHighLimit", 40.0),
        ],
    )
    kit.link("Inputs/a", "out", reset, "inA")
    kit.observe_numeric("rescaled", reset)
    return kit.build()


def _loop() -> bytes:
    kit = Kit("S_LOOP")
    kit.boolean_input("enable", True)
    kit.numeric_input("cv", None)
    kit.numeric_input("sp", 20.0)
    loop = kit.block(
        "loop",
        "kitControl:LoopPoint",
        [
            double("proportionalConstant", 2.0),
            double("integralConstant", 1.0),
            double("bias", 10.0),
            double("maximumOutput", 100.0),
            double("minimumOutput", 0.0),
            rel_time("executeTime", 10.0),
        ],
    )
    kit.link("Inputs/enable", "out", loop, "loopEnable")
    kit.link("Inputs/cv", "out", loop, "controlledVariable")
    kit.link("Inputs/sp", "out", loop, "setpoint")
    kit.observe_numeric("loopOut", loop, fallback=-1.0)
    return kit.build()


def _link_4() -> bytes:
    kit = Kit("S_LINK_4")
    kit.numeric_input("a", 1.0)
    via = kit.block("viaAdd", "kitControl:Add", [status_numeric("inB", 0.0)])
    diff = kit.block("diff", "kitControl:Subtract")
    edge = kit.block("edge", "kitControl:NotEqual", [status_numeric("inB", 0.0)])
    pulse = kit.block("pulse", "kitControl:OneShot", [rel_time("pulseWidth", 1.0)])
    any_set = kit.block("any", "kitControl:Or")
    hold = kit.block("hold", "kitControl:And", [status_boolean("inB", True)])
    kit.link("Inputs/a", "out", diff, "inA")
    kit.link("Inputs/a", "out", via, "inA")
    kit.link(via, "out", diff, "inB")
    kit.link(diff, "out", edge, "inA")
    kit.link(edge, "out", pulse, "in")
    kit.link(pulse, "out", any_set, "inA")
    kit.link(hold, "out", any_set, "inB")
    kit.link(any_set, "out", hold, "inA")
    kit.observe_boolean("glitchLatched", hold)
    return kit.build()


def _link_3() -> bytes:
    kit = Kit("S_LINK_3")
    kit.boolean_input("set", False)
    kit.boolean_input("notClear", True)
    any_set = kit.block("any", "kitControl:Or")
    hold = kit.block("hold", "kitControl:And")
    kit.link("Inputs/set", "out", any_set, "inA")
    kit.link(hold, "out", any_set, "inB")
    kit.link(any_set, "out", hold, "inA")
    kit.link("Inputs/notClear", "out", hold, "inB")
    kit.observe_boolean("latched", hold)
    return kit.build()


def _clock_1() -> bytes:
    kit = Kit("S_CLOCK_1")
    kit.boolean_input("a", False)
    feed = kit.block("feed", "kitControl:BooleanDelay", [rel_time("onDelay", 5.0)])
    clock = kit.block("clock", "kitControl:BooleanDelay", [rel_time("onDelay", 5.0)])
    latch = kit.block("latch", "kitControl:BooleanLatch")
    kit.link("Inputs/a", "out", feed, "in")
    kit.link("Inputs/a", "out", clock, "in")
    kit.link(feed, "out", latch, "in")
    kit.link(clock, "out", latch, "clock")
    kit.observe_boolean("tieOrder", latch)
    return kit.build()


def _sched_3() -> bytes:
    kit = Kit("S_SCHED_3")
    kit.boolean_input("a", False)
    kit.observe_boolean("echo", "Inputs/a")
    return kit.build()


CALIBRATIONS: tuple[Calibration, ...] = (
    Calibration(
        "S-STATUS-4",
        "propagateFlags default: a null input is ignored, no bit propagates",
        _status_4,
        (Step(0.0, "override", "a", 3.0), Step(10.0, "auto", "a")),
        ("sum",),
        20.0,
        "sum reads 5 with ok status, then 2 (b alone) with ok status after a goes null at t=10.",
    ),
    Calibration(
        "S-STATUS-5",
        "a null input gives a null output; the fed point falls back (also S-LOGIC-2)",
        _status_5_logic_2,
        (Step(0.0, "override", "b", False), Step(10.0, "auto", "b")),
        ("notOut",),
        20.0,
        "notOut is true (not false), then after t=10 the writable shows its own fallback true "
        "with the in16 null.",
    ),
    Calibration(
        "S-STATUS-6",
        "start-up: outputs start at zero/ok, links push before the first execution (also S-LINK-2)",
        _status_6_link_2,
        (),
        ("latched",),
        10.0,
        "latched reads 3 from the first history record: the latch clocked at start saw the "
        "settled sum.",
    ),
    Calibration(
        "S-MATH-2",
        "Subtract anchors on inA; a null inB is ignored, a null inA gives null",
        _math_2,
        (
            Step(0.0, "override", "a", 10.0),
            Step(0.0, "override", "b", 4.0),
            Step(10.0, "auto", "b"),
            Step(20.0, "auto", "a"),
        ),
        ("difference",),
        30.0,
        "difference reads 6, then 10 (b null ignored), then the fallback 99 when a is null.",
    ),
    Calibration(
        "S-MATH-3",
        "division by zero gives an IEEE result with the fault bit (also S-WRITABLE-5)",
        _math_3_writable_5,
        (Step(10.0, "override", "b", 0.0),),
        ("quotient", "quotientStatus"),
        20.0,
        "quotient reads 5 then 1e6 (infinity clamped); quotientStatus's history status shows "
        "fault after t=10.",
    ),
    Calibration(
        "S-CMP-1",
        "a comparison with a null input is null",
        _cmp_1,
        (Step(0.0, "override", "b", 1.0), Step(10.0, "auto", "b")),
        ("greater",),
        20.0,
        "greater is true, then after t=10 the writable shows its fallback true with in16 null.",
    ),
    Calibration(
        "S-LATCH-2",
        "a latch holds the type's zero with ok status before its first clock edge",
        _latch_2,
        (Step(10.0, "override", "clock", True),),
        ("latched",),
        20.0,
        "latched reads 0 with ok status until t=10, then 7.",
    ),
    Calibration(
        "S-ONESHOT-2",
        "default OneShot pulse width",
        _oneshot_2,
        (Step(5.0, "override", "trigger", True), Step(15.0, "override", "trigger", False)),
        ("pulse",),
        20.0,
        "The runtime assumes 0.5 s: no one-second history sample should catch the pulse true.",
    ),
    Calibration(
        "S-ONESHOT-3",
        "a rising edge during a pulse restarts it",
        _oneshot_3,
        (),
        ("retriggered",),
        20.0,
        "retriggered stays true throughout: the 0.6 s clock keeps restarting the 2 s pulse.",
    ),
    Calibration(
        "S-MV-2",
        "MultiVibrator starts true at station start",
        _mv_2,
        (),
        ("clock",),
        40.0,
        "clock is true for the first 10 s, false for the next 10 s, and so on.",
    ),
    Calibration(
        "S-TSTAT-2",
        "Tstat with a null cv is null; it starts false (also S-TSTAT-3)",
        _tstat_2_3,
        (Step(0.0, "override", "cv", 25.0), Step(10.0, "auto", "cv")),
        ("call",),
        20.0,
        "call starts true (cv above the band), then after t=10 shows the fallback true with "
        "in16 null.",
    ),
    Calibration(
        "S-RESET-2",
        "Reset with equal input limits gives outputLowLimit with the fault bit",
        _reset_2,
        (),
        ("rescaled",),
        10.0,
        "rescaled reads 30 and its history status shows fault.",
    ),
    Calibration(
        "S-LOOP-2",
        "LoopPoint executes on its executeTime clock only (also S-LOOP-4, S-LOOP-5, S-LOOP-6)",
        _loop,
        (
            Step(0.0, "override", "cv", 20.0),
            Step(13.0, "override", "cv", 25.0),
            Step(43.0, "override", "cv", 200.0),
            Step(73.0, "override", "cv", 20.0),
            Step(93.0, "override", "enable", False),
            Step(113.0, "auto", "cv"),
        ),
        ("loopOut",),
        130.0,
        "loopOut changes only at multiples of 10 s (S-LOOP-2), clamps at 100 without winding up "
        "(S-LOOP-4), holds when enable drops at t=93 (S-LOOP-5) and shows the fallback -1 once "
        "cv is "
        "null at t=113 (S-LOOP-6).",
    ),
    Calibration(
        "S-LINK-4",
        "synchronous depth-first propagation makes intermediate values visible",
        _link_4,
        (Step(10.0, "override", "a", 5.0),),
        ("glitchLatched",),
        20.0,
        "glitchLatched becomes true at t=10 if the station propagates each link to completion "
        "before "
        "the next; it stays false if both links settle before anything downstream runs.",
    ),
    Calibration(
        "S-LINK-3",
        "a converging feedback loop settles without error",
        _link_3,
        (
            Step(10.0, "override", "set", True),
            Step(15.0, "override", "set", False),
            Step(25.0, "override", "notClear", False),
        ),
        ("latched",),
        30.0,
        "latched rises at t=10, holds through t=15 and clears at t=25; the station log shows "
        "no error.",
    ),
    Calibration(
        "S-CLOCK-1",
        "order of two timers due at the same instant",
        _clock_1,
        (Step(5.0, "override", "a", True),),
        ("tieOrder",),
        20.0,
        "Both delays expire at t=10. tieOrder true means the feed delay fired before the clock "
        "delay.",
    ),
    Calibration(
        "S-SCHED-3",
        "runtime convention: simulated time zero is Monday 00:00",
        _sched_3,
        (),
        ("echo",),
        5.0,
        "A convention of the runtime, not a Niagara behaviour: no station test.",
        station_testable=False,
    ),
)

CALIBRATIONS_BY_ID = {item.id: item for item in CALIBRATIONS}

# Rules covered by a file other than their own (the README lists both).
COVERED_BY: dict[str, str] = {
    "S-LOGIC-2": "S-STATUS-5",
    "S-LINK-2": "S-STATUS-6",
    "S-WRITABLE-5": "S-MATH-3",
    "S-TSTAT-3": "S-TSTAT-2",
    "S-LOOP-4": "S-LOOP-2",
    "S-LOOP-5": "S-LOOP-2",
    "S-LOOP-6": "S-LOOP-2",
}


# --- expected traces --------------------------------------------------------------------


@dataclass
class ExpectedTrace:
    calibration: str
    point: str
    records: list[tuple[float, float | bool, int]]

    def to_csv(self) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["time_seconds", "value", "status_bits", "status"])
        for time_seconds, value, status in self.records:
            writer.writerow(
                [f"{time_seconds:g}", _render_value(value), status, Status(status).render()]
            )
        return buffer.getvalue()

    @classmethod
    def from_csv(cls, calibration: str, point: str, text: str) -> ExpectedTrace:
        records = []
        for row in csv.DictReader(io.StringIO(text)):
            records.append(
                (float(row["time_seconds"]), _parse_value(row["value"]), int(row["status_bits"]))
            )
        return cls(calibration, point, records)


def _render_value(value: float | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return repr(float(value))


def _parse_value(text: str) -> float | bool:
    lowered = text.strip().lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    return float(text)


def expected_traces(
    calibration: Calibration,
    *,
    policy: ExecutionPolicy = DEFAULT_POLICY,
    content: bytes | None = None,
) -> list[ExpectedTrace]:
    """Run the kit file in the Shadow Runtime with its script; return the history records."""

    content = content if content is not None else calibration.build()
    runtime = ShadowRuntime(content, policy=policy, kernel_backend="python")
    name = runtime.program.root.children[0].name if runtime.program.root.children else ""
    try:
        for step in calibration.steps:
            if step.time_seconds == 0.0:
                _apply(runtime, name, step)
        runtime.start()
        now = 0.0
        for step in sorted(
            (s for s in calibration.steps if s.time_seconds > 0.0), key=lambda s: s.time_seconds
        ):
            runtime.advance(step.time_seconds - now)
            now = step.time_seconds
            _apply(runtime, name, step)
        runtime.advance(calibration.duration_seconds - now)
        traces = []
        for point in calibration.observe:
            history = next(
                block
                for block in runtime.blocks_of(IntervalHistory)
                if block.node.parent is not None and block.node.parent.name == point
            )
            # The t=0 record is taken during start-up, before the operator's clock exists
            # in a station; only records after start are comparable.
            records = [r for r in history.records if r[0] > 0.0]
            traces.append(ExpectedTrace(calibration.id, point, records))  # type: ignore[arg-type]
        return traces
    finally:
        runtime.close()


def _apply(runtime: ShadowRuntime, program: str, step: Step) -> None:
    path = f"/{program}/Inputs/{step.point}"
    if step.action == "override":
        assert step.value is not None
        runtime.override(path, step.value)
    elif step.action == "auto":
        runtime.auto(path)
    else:
        raise ValueError(f"unknown step action {step.action!r}")


# --- writing the kit ------------------------------------------------------------------------


def write_kit(destination: Path) -> list[Path]:
    """Write every calibration folder: program.bog, steps.json, expected-<point>.csv, README."""

    written: list[Path] = []
    destination.mkdir(parents=True, exist_ok=True)
    for calibration in CALIBRATIONS:
        folder = destination / calibration.folder
        folder.mkdir(parents=True, exist_ok=True)
        content = calibration.build()
        (folder / "program.bog").write_bytes(content)
        written.append(folder / "program.bog")
        steps = {
            "schema": "bactalk.calibration-steps/v1",
            "assumption": calibration.id,
            "title": calibration.title,
            "station_testable": calibration.station_testable,
            "duration_seconds": calibration.duration_seconds,
            "history_interval_seconds": HISTORY_INTERVAL_SECONDS,
            "steps": [
                {
                    "time_seconds": s.time_seconds,
                    "action": s.action,
                    "point": s.point,
                    "value": s.value,
                }
                for s in calibration.steps
            ],
            "observe": list(calibration.observe),
            "what_to_look_for": calibration.what_to_look_for,
        }
        (folder / "steps.json").write_text(json.dumps(steps, indent=2) + "\n", encoding="utf-8")
        written.append(folder / "steps.json")
        for trace in expected_traces(calibration, content=content):
            path = folder / f"expected-{trace.point}.csv"
            path.write_text(trace.to_csv(), encoding="utf-8")
            written.append(path)
    (destination / "README.md").write_text(render_readme(), encoding="utf-8")
    written.append(destination / "README.md")
    return written


def render_readme() -> str:
    lines = [
        "# Shadow Runtime calibration kit (Gate G-WB)",
        "",
        "Generated by `scripts/build_calibration_kit.py` from `bactalk.niagara.calibration`;",
        "do not edit by hand. One folder per ASSUMED rule of `docs/niagara-semantics.md`.",
        "Each holds `program.bog` (import it into a station), `steps.json` (what to do and",
        "when) and one `expected-<point>.csv` per observed history: the trace the Shadow",
        "Runtime produced for the same script.",
        "",
        "## Procedure (once, about two hours)",
        "",
        "1. Start a clean localhost station with the signed `bactalkG36` module installed",
        "   (Gate G-SDK).",
        "2. For each folder below, in order: import `program.bog` under the station's root folder,",
        "   note the wall-clock time you start the station or enable the folder (this is t=0),",
        "   then perform the steps at the listed times using the point actions in Workbench:",
        "   `override` at level 8 with the listed value, `auto` to remove the override.",
        "3. After `duration_seconds`, export each history under `Outputs/<point>/<point>History`",
        "   as CSV to `gates/evidence/G-WB/<folder>/<point>.csv` (any export with a timestamp",
        "   column",
        "   and a value column is accepted; a status column is used when present).",
        "4. Run `python scripts/calibrate_shadow_runtime.py gates/evidence/G-WB`. It compares the",
        "   exports with the expected traces, prints a verdict per rule and writes VERIFIED or",
        "   CONTRADICTED next to the rule in `docs/niagara-semantics.md`.",
        "",
        "The export's clock is aligned to the expected trace (its first record is taken as the",
        "first expected record, then shifted by up to two intervals to the best fit); within that,",
        "a record must lie within 1.5 s of its expected instant and numeric values are compared",
        "to 0.1 % of their range (never below 1e-6). A rule whose observation depends on",
        "an ordering the station does not guarantee (S-LINK-4, S-CLOCK-1) is recorded as the",
        "station's observed behaviour; either outcome is evidence.",
        "",
        "## Files",
        "",
        "| Folder | Rule | Also covers | Duration | What to look for |",
        "|---|---|---|---|---|",
    ]
    for calibration in CALIBRATIONS:
        also = (
            ", ".join(sorted(rule for rule, by in COVERED_BY.items() if by == calibration.id))
            or "—"
        )
        note = (
            calibration.what_to_look_for
            if calibration.station_testable
            else "Not station-testable: " + calibration.what_to_look_for
        )
        lines.append(
            f"| `{calibration.folder}/` | {calibration.id} | {also} "
            f"| {calibration.duration_seconds:g} s | {note} |"
        )
    lines.append("")
    lines.append("## Steps per file")
    lines.append("")
    for calibration in CALIBRATIONS:
        lines.append(f"### `{calibration.folder}/` — {calibration.title}")
        lines.append("")
        if not calibration.steps:
            lines.append("- No operator steps: start the station and let the histories fill.")
        for step in calibration.steps:
            lines.append(f"- {step.describe()}")
        lines.append(
            "- Export: "
            + ", ".join(f"`Outputs/{p}`" for p in calibration.observe)
            + f" after {calibration.duration_seconds:g} s."
        )
        lines.append("")
    return "\n".join(lines)


# --- comparing evidence --------------------------------------------------------------------


@dataclass
class Verdict:
    assumption: str
    status: str
    """VERIFIED, CONTRADICTED, MISSING or NOT_TESTABLE."""

    detail: str = ""
    mismatches: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption": self.assumption,
            "status": self.status,
            "detail": self.detail,
            "mismatches": self.mismatches[:10],
        }


def parse_history_export(text: str) -> list[tuple[float, float | bool, str | None]]:
    """Read a Niagara history CSV export: (seconds since the first record, value, status text)."""

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return []
    lower = {name.lower().strip(): name for name in reader.fieldnames}
    time_key = next((lower[k] for k in ("timestamp", "time", "time_seconds") if k in lower), None)
    value_key = next((lower[k] for k in ("value", "out") if k in lower), None)
    status_key = next((lower[k] for k in ("status",) if k in lower), None)
    if time_key is None or value_key is None:
        raise ValueError("history export needs a timestamp column and a value column")
    rows: list[tuple[float, float | bool, str | None]] = []
    origin: float | None = None
    for row in reader:
        stamp = _parse_timestamp(row[time_key])
        if origin is None:
            origin = stamp
        rows.append(
            (
                stamp - origin,
                _parse_value(row[value_key]),
                row.get(status_key) if status_key else None,
            )
        )
    return rows


def _parse_timestamp(text: str) -> float:
    value = text.strip()
    try:
        return float(value)
    except ValueError:
        pass
    cleaned = re.sub(r"\s+[A-Za-z_/]+$", "", value)  # drop a trailing zone name
    for fmt in (
        "%d-%b-%y %I:%M:%S %p",
        "%d-%b-%y %I:%M:%S.%f %p",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(cleaned, fmt).timestamp()
        except ValueError:
            continue
    raise ValueError(f"unrecognised history timestamp {text!r}")


def compare_trace(
    expected: ExpectedTrace, observed: Sequence[tuple[float, float | bool, str | None]]
) -> list[str]:
    """Mismatches between an expected trace and a station export; empty means agreement."""

    if not observed:
        return ["no records exported"]
    if not expected.records:
        return []
    values = [v for _, v, _ in expected.records if not isinstance(v, bool)]
    span = (max(values) - min(values)) if values else 0.0
    tolerance = max(1e-6, 1e-3 * span)
    # The operator's t=0 and the station's first history record are not the same
    # instant; the export is aligned to the expected trace by the shift (within two
    # intervals of "first record = first expected record") that explains it best.
    base = expected.records[0][0] - observed[0][0]
    best: list[str] | None = None
    for k in range(-2, 3):
        shift = base + k * HISTORY_INTERVAL_SECONDS
        shifted = [(t + shift, v, s) for t, v, s in observed]
        mismatches = _mismatches(expected, shifted, tolerance)
        if best is None or len(mismatches) < len(best):
            best = mismatches
        if not mismatches:
            break
    return best or []


def _mismatches(
    expected: ExpectedTrace,
    observed: Sequence[tuple[float, float | bool, str | None]],
    tolerance: float,
) -> list[str]:
    mismatches: list[str] = []
    for time_seconds, value, status in expected.records:
        nearest = min(observed, key=lambda item: abs(item[0] - time_seconds))
        if abs(nearest[0] - time_seconds) > TIME_TOLERANCE_SECONDS:
            mismatches.append(
                f"t={time_seconds:g}: no station record within {TIME_TOLERANCE_SECONDS:g} s"
            )
            continue
        expected_null = bool(Status(status) & Status.NULL)
        observed_null = nearest[2] is not None and "null" in nearest[2].lower()
        if nearest[2] is not None and expected_null != observed_null:
            mismatches.append(
                f"t={time_seconds:g}: status {nearest[2]} vs expected {Status(status).render()}"
            )
            continue
        if isinstance(value, bool):
            if bool(nearest[1]) != value:
                mismatches.append(f"t={time_seconds:g}: {nearest[1]!r} vs expected {value!r}")
        elif not (math.isfinite(float(value)) and math.isfinite(float(nearest[1]))):
            if repr(float(value)) != repr(float(nearest[1])):
                mismatches.append(f"t={time_seconds:g}: {nearest[1]!r} vs expected {value!r}")
        elif abs(float(nearest[1]) - float(value)) > tolerance:
            mismatches.append(
                f"t={time_seconds:g}: {nearest[1]!r} vs expected {value!r} "
                f"(tolerance {tolerance:g})"
            )
    return mismatches


def compare_evidence(evidence_root: Path, kit_root: Path) -> list[Verdict]:
    verdicts: list[Verdict] = []
    for calibration in CALIBRATIONS:
        if not calibration.station_testable:
            verdicts.append(Verdict(calibration.id, "NOT_TESTABLE", calibration.what_to_look_for))
            continue
        folder = evidence_root / calibration.folder
        mismatches: list[str] = []
        missing: list[str] = []
        for point in calibration.observe:
            expected_path = kit_root / calibration.folder / f"expected-{point}.csv"
            observed_path = folder / f"{point}.csv"
            if not observed_path.is_file():
                missing.append(point)
                continue
            expected = ExpectedTrace.from_csv(
                calibration.id, point, expected_path.read_text(encoding="utf-8")
            )
            observed = parse_history_export(observed_path.read_text(encoding="utf-8"))
            mismatches.extend(f"{point}: {item}" for item in compare_trace(expected, observed))
        if missing and len(missing) == len(calibration.observe):
            verdicts.append(Verdict(calibration.id, "MISSING", f"no export under {folder}"))
        elif mismatches or missing:
            verdicts.append(
                Verdict(
                    calibration.id,
                    "CONTRADICTED",
                    f"{len(mismatches)} mismatches",
                    mismatches + [f"{p}: missing" for p in missing],
                )
            )
        else:
            verdicts.append(Verdict(calibration.id, "VERIFIED", "every record within tolerance"))
    return verdicts


def annotate_document(
    document: Path, verdicts: Iterable[Verdict], *, today: str | None = None
) -> int:
    """Write ``→ VERIFIED (G-WB date)`` / ``→ CONTRADICTED`` into each rule's status cell."""

    today = today or datetime.now(UTC).date().isoformat()
    text = document.read_text(encoding="utf-8")
    changed = 0
    verdict_by_rule: dict[str, Verdict] = {}
    for verdict in verdicts:
        verdict_by_rule[verdict.assumption] = verdict
        for rule, covered_by in COVERED_BY.items():
            if covered_by == verdict.assumption:
                verdict_by_rule.setdefault(rule, verdict)
    for rule, verdict in verdict_by_rule.items():
        if verdict.status not in {"VERIFIED", "CONTRADICTED"}:
            continue
        pattern = re.compile(rf"^(\| {re.escape(rule)} \| .*? \| )(ASSUMED[^|]*?)( \|)", re.M)
        match = pattern.search(text)
        if match is None:
            continue
        cell = re.sub(r" → (VERIFIED|CONTRADICTED) \(G-WB [0-9-]+\)", "", match.group(2)).rstrip()
        replacement = f"{match.group(1)}{cell} → {verdict.status} (G-WB {today}){match.group(3)}"
        text = text[: match.start()] + replacement + text[match.end() :]
        changed += 1
    document.write_text(text, encoding="utf-8")
    return changed


__all__ = [
    "CALIBRATIONS",
    "CALIBRATIONS_BY_ID",
    "COVERED_BY",
    "HISTORY_INTERVAL_SECONDS",
    "Calibration",
    "ExpectedTrace",
    "Step",
    "Verdict",
    "annotate_document",
    "compare_evidence",
    "compare_trace",
    "expected_traces",
    "parse_history_export",
    "render_readme",
    "write_kit",
]
