"""The Niagara lowering matrix and equivalence policy (GOAL-NATIVE-BOG.md N2).

Every :class:`~bactalk.domain.BlockKind` is classified once, here, in code:

``STOCK_EXACT``        a stock Niagara block with identical behaviour
``STOCK_WITHIN_BANDS`` a stock block or a small fixed composite of stock blocks
                       with a documented deviation, expected to pass every
                       scenario within tolerance; provisional until N7 proves it
                       in the Shadow Runtime
``MODULE``             needs a ``bactalkG36`` component (N3)
``UNSUPPORTED``        no native lowering yet; the item is blocked in the native
                       lane and only the expert ProgramObject lane can carry it

Policy: stock first, then module, then fail closed. ``docs/niagara-lowering-
matrix.md`` is rendered from this module (``python -m bactalk.niagara.lowering
--write``) and a stale copy fails ``make test-native-bog``.

Nothing here claims runtime qualification. A row describes the lowering the
native emitter (N4) will use and the equivalence the Shadow Runtime (N6/N7)
has to prove; Gate G-WB decides what Niagara actually accepts.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

from bactalk.domain import Block, BlockKind, ControlGraph

MODULE_NAME = "bactalkG36"
MATRIX_DOC = Path(__file__).resolve().parents[3] / "docs" / "niagara-lowering-matrix.md"


class LoweringClass(StrEnum):
    STOCK_EXACT = "STOCK_EXACT"
    STOCK_WITHIN_BANDS = "STOCK_WITHIN_BANDS"
    MODULE = "MODULE"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class LoweringDecision:
    kind: BlockKind
    lowering: LoweringClass
    target: str
    """The Niagara type (``module:Name``), a composite description, or ``""``."""

    slot_map: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    """IR slot name to Niagara slot name for single-block stock lowerings."""

    deviation: str = ""
    """For ``STOCK_WITHIN_BANDS``: the exact behavioural difference."""

    bounding_scenarios: tuple[str, ...] = ()
    """For ``STOCK_WITHIN_BANDS``: the scenarios that bound the deviation."""

    note: str = ""

    @property
    def composite(self) -> bool:
        return self.target.startswith("composite:")

    @property
    def module_type(self) -> str | None:
        return self.target if self.target.startswith(f"{MODULE_NAME}:") else None


def _slots(**pairs: str) -> Mapping[str, str]:
    return MappingProxyType(dict(pairs))


def _exact(kind: BlockKind, target: str, note: str = "", **slots: str) -> LoweringDecision:
    return LoweringDecision(kind, LoweringClass.STOCK_EXACT, target, _slots(**slots), note=note)


def _bands(
    kind: BlockKind,
    target: str,
    deviation: str,
    scenarios: tuple[str, ...],
    note: str = "",
    **slots: str,
) -> LoweringDecision:
    return LoweringDecision(
        kind,
        LoweringClass.STOCK_WITHIN_BANDS,
        target,
        _slots(**slots),
        deviation=deviation,
        bounding_scenarios=scenarios,
        note=note,
    )


def _module(kind: BlockKind, name: str, note: str = "") -> LoweringDecision:
    return LoweringDecision(kind, LoweringClass.MODULE, f"{MODULE_NAME}:{name}", note=note)


def _unsupported(kind: BlockKind, note: str) -> LoweringDecision:
    return LoweringDecision(kind, LoweringClass.UNSUPPORTED, "", note=note)


_AB = {"a": "inA", "b": "inB", "out": "out"}
_ROWS: tuple[LoweringDecision, ...] = (
    # --- boundary points --------------------------------------------------
    _exact(BlockKind.NUMERIC_INPUT, "control:NumericWritable", out="out"),
    _exact(BlockKind.BOOLEAN_INPUT, "control:BooleanWritable", out="out"),
    _exact(
        BlockKind.NUMERIC_OUTPUT,
        "control:NumericWritable",
        "Driven at priority 16; the point's units come from the job (N0).",
        **{"in": "in16", "out": "out"},
    ),
    _exact(BlockKind.BOOLEAN_OUTPUT, "control:BooleanWritable", **{"in": "in16", "out": "out"}),
    _exact(BlockKind.NUMERIC_CONST, "kitControl:NumericConst", out="out"),
    _exact(BlockKind.BOOLEAN_CONST, "kitControl:BooleanConst", out="out"),
    # --- arithmetic -------------------------------------------------------
    _exact(BlockKind.ADD, "kitControl:Add", **_AB),
    _exact(BlockKind.SUBTRACT, "kitControl:Subtract", **_AB),
    _exact(BlockKind.MULTIPLY, "kitControl:Multiply", **_AB),
    _exact(
        BlockKind.DIVIDE,
        "kitControl:Divide",
        "Division by zero yields a fault status in Niagara and NaN in the IR; both "
        "propagate as non-numeric.",
        **_AB,
    ),
    _exact(BlockKind.MINIMUM, "kitControl:Minimum", **_AB),
    _exact(BlockKind.MAXIMUM, "kitControl:Maximum", **_AB),
    _exact(BlockKind.AVERAGE, "kitControl:Average", **_AB),
    # --- comparison -------------------------------------------------------
    _exact(BlockKind.GREATER_THAN, "kitControl:GreaterThan", **_AB),
    _exact(BlockKind.GREATER_THAN_OR_EQUAL, "kitControl:GreaterThanEqual", **_AB),
    _exact(BlockKind.LESS_THAN, "kitControl:LessThan", **_AB),
    _exact(BlockKind.LESS_THAN_OR_EQUAL, "kitControl:LessThanEqual", **_AB),
    _exact(BlockKind.EQUAL, "kitControl:Equal", **_AB),
    _exact(BlockKind.NOT_EQUAL, "kitControl:NotEqual", **_AB),
    # --- logic ------------------------------------------------------------
    _exact(BlockKind.AND, "kitControl:And", **_AB),
    _exact(BlockKind.OR, "kitControl:Or", **_AB),
    _exact(BlockKind.XOR, "kitControl:Xor", **_AB),
    _exact(BlockKind.NOT, "kitControl:Not", **{"in": "in", "out": "out"}),
    _exact(
        BlockKind.NUMERIC_SWITCH,
        "kitControl:NumericSwitch",
        selector="inSwitch",
        when_true="inTrue",
        when_false="inFalse",
        out="out",
    ),
    _exact(
        BlockKind.BOOLEAN_SWITCH,
        "kitControl:BooleanSwitch",
        selector="inSwitch",
        when_true="inTrue",
        when_false="inFalse",
        out="out",
    ),
    # --- latches ----------------------------------------------------------
    _exact(
        BlockKind.NUMERIC_LATCH,
        "kitControl:NumericLatch",
        "Samples in on the rising edge of clock, as the IR does.",
        **{"in": "in", "clock": "clock", "out": "out"},
    ),
    _exact(
        BlockKind.BOOLEAN_LATCH,
        "kitControl:BooleanLatch",
        **{"in": "in", "clock": "clock", "out": "out"},
    ),
    _module(
        BlockKind.BOOLEAN_SET_RESET,
        "SetReset",
        "Clear-dominant latch with host-tick semantics; the stock OneShot/Or/And composite "
        "latched on transient values inside one link propagation (N7, D3).",
    ),
    # --- edges and delays -------------------------------------------------
    _module(
        BlockKind.ONE_SHOT,
        "RisingEdge",
        "One execution true per rising edge, judged between execution periods; "
        "kitControl:OneShot fires on transient values inside one link propagation (N7, D3).",
    ),
    _module(
        BlockKind.BOOLEAN_FALLING_EDGE,
        "FallingEdge",
        "One execution true per falling edge, judged between execution periods.",
    ),
    _bands(
        BlockKind.BOOLEAN_DELAY,
        "kitControl:BooleanDelay",
        "BooleanDelay always delays a true input from start-up; the IR passes an "
        "initially true input through when delay_on_init is false. This row applies "
        "only when delay_on_init is true; otherwise the block is lowered to "
        f"{MODULE_NAME}:TrueDelay (see classify_block).",
        (
            "input true at start-up",
            "input pulse shorter than the delay",
            "input held true past the delay",
            "input dropping exactly at the delay",
        ),
        **{"in": "in", "out": "out"},
    ),
    _module(
        BlockKind.BOOLEAN_TRUE_FALSE_HOLD,
        "TrueFalseHold",
        "No stock block holds both states for a minimum time.",
    ),
    _module(BlockKind.BOOLEAN_PRE_HOST_TICK, "Pre", "One-tick delay with host-tick semantics."),
    _module(
        BlockKind.BOOLEAN_INITIALIZATION,
        "BooleanInitialization",
        "True (or the configured value) on the first execution cycle only.",
    ),
    # --- sampling ---------------------------------------------------------
    _module(
        BlockKind.NUMERIC_SAMPLER,
        "Sampler",
        "Period-aligned sampling with host-tick semantics; the stock MultiVibrator/Latch "
        "composite captured whatever value its input held mid-propagation (N7, D3).",
    ),
    _module(
        BlockKind.BOOLEAN_SAMPLE_TRIGGER,
        "SampleTrigger",
        "One execution true per period boundary, aligned to time zero plus shift.",
    ),
    _module(
        BlockKind.NUMERIC_FIRST_ORDER_HOLD,
        "FirstOrderHold",
        "Linear extrapolation between samples has no stock equivalent.",
    ),
    _module(
        BlockKind.NUMERIC_UNIT_DELAY,
        "UnitDelay",
        "kitControl:NumericDelay is a rate limiter, not a one-period delay.",
    ),
    _module(BlockKind.MOVING_AVERAGE, "MovingAverage", "Time-window average over a ring buffer."),
    _module(BlockKind.NUMERIC_CHANGED, "NumericChange", "mode=changed."),
    _module(BlockKind.NUMERIC_INCREASED, "NumericChange", "mode=increased."),
    _module(BlockKind.NUMERIC_DECREASED, "NumericChange", "mode=decreased."),
    # --- thresholds and timers --------------------------------------------
    _module(
        BlockKind.HYSTERESIS,
        "Hysteresis",
        "CDL thresholds (on above u_high, off below u_low) with host-tick semantics; "
        "kitControl:Tstat executes on change and can latch on a transient value (N7, D3).",
    ),
    _module(BlockKind.TIMER, "Timer", "Elapsed time and passed flag while in is true."),
    _module(BlockKind.TIMER_WITH_RESET, "TimerWithReset"),
    _module(BlockKind.TIMER_ACCUMULATING, "TimerAccumulating"),
    _bands(
        BlockKind.BOOLEAN_ASSERT_WARNING,
        "composite: pass-through link for ok, baja:WsTextBlock carrying the message",
        "The station raises no warning when the condition is false; the message is "
        "kept as a wiresheet note beside the condition wire.",
        ("condition false for one cycle", "condition false at start-up"),
    ),
    # --- loops and resets -------------------------------------------------
    _exact(
        BlockKind.RESET,
        "kitControl:Reset",
        "Linear interpolation clamped to the input range, as the IR does.",
        **{
            "in": "inA",
            "input_low": "inputLowLimit",
            "input_high": "inputHighLimit",
            "output_low": "outputLowLimit",
            "output_high": "outputHighLimit",
            "out": "out",
        },
    ),
    _bands(
        BlockKind.PI_LOOP,
        "kitControl:LoopPoint",
        "LoopPoint integrates in its own bias form and clamps to its output limits; "
        "the IR resets its integral when enable drops and returns disabled_output.",
        (
            "output saturated high and low",
            "enable dropping then returning (integral reset)",
            "sustained error (windup) with the output clamped",
            "start-up with a non-zero error",
        ),
        enable="loopEnable",
        controlled_variable="controlledVariable",
        setpoint="setpoint",
        direct="loopAction",
        out="out",
    ),
    _module(
        BlockKind.PID_WITH_RESET,
        "PIDWithReset",
        "CDL-exact form with a reset trigger; kitControl:LoopPoint has no reset input "
        "and a different anti-windup form, so it is not used.",
    ),
    _module(
        BlockKind.TRIM_AND_RESPOND,
        "TrimAndRespond",
        "Kernel harvested from the ProgramObject generator.",
    ),
    _module(
        BlockKind.TRIM_AND_RESPOND_HOLD,
        "TrimAndRespond",
        "The same component with holdEnabled=true (the CDL have_hol variant).",
    ),
    # --- plant composites (Tier 2, N8) -------------------------------------
    _unsupported(
        BlockKind.PLANT_EQUIPMENT_AVAILABILITY,
        "Buildings.Templates plant composite; native lowering is decided in N8.",
    ),
    _unsupported(
        BlockKind.PLANT_ENABLE,
        "Buildings.Templates plant composite; native lowering is decided in N8.",
    ),
    _unsupported(
        BlockKind.PLANT_HRC_ENABLE,
        "Buildings.Templates plant composite; native lowering is decided in N8.",
    ),
    _unsupported(
        BlockKind.PLANT_HRC_MODE_CONTROL,
        "Buildings.Templates plant composite; native lowering is decided in N8.",
    ),
    _unsupported(
        BlockKind.PLANT_STAGE_COMPLETION,
        "Buildings.Templates plant composite; native lowering is decided in N8.",
    ),
    _unsupported(
        BlockKind.PLANT_STAGE_INDEX,
        "Buildings.Templates plant composite; native lowering is decided in N8.",
    ),
)

LOWERING_MATRIX: Mapping[BlockKind, LoweringDecision] = MappingProxyType(
    {row.kind: row for row in _ROWS}
)

# Rows that depend on block configuration rather than kind alone.
TRUE_DELAY_MODULE = LoweringDecision(
    BlockKind.BOOLEAN_DELAY,
    LoweringClass.MODULE,
    f"{MODULE_NAME}:TrueDelay",
    note="delay_on_init is false: the stock BooleanDelay would delay the initial true.",
)


def classify(kind: BlockKind) -> LoweringDecision:
    """The matrix row for ``kind`` (configuration-independent)."""

    return LOWERING_MATRIX[kind]


def classify_block(block: Block) -> LoweringDecision:
    """The row for one block, honouring configuration-dependent choices."""

    if block.kind == BlockKind.BOOLEAN_DELAY and not bool(block.config.get("delay_on_init", True)):
        return TRUE_DELAY_MODULE
    return classify(block.kind)


@dataclass(frozen=True)
class LoweringPolicy:
    """Stock first, then module, then fail closed.

    ``expert_program_objects`` keeps the ProgramObject generator reachable for a
    graph the native lane cannot carry. It is never the default.
    """

    expert_program_objects: bool = False


@dataclass(frozen=True)
class LoweringPlan:
    decisions: Mapping[str, LoweringDecision]
    counts: Mapping[str, int]
    module_types: tuple[str, ...]
    unsupported: tuple[tuple[str, BlockKind], ...]
    lane: str
    """``native_stock``, ``native_with_module``, ``program_objects`` or ``blocked``."""

    blockers: tuple[str, ...]

    @property
    def native(self) -> bool:
        return self.lane.startswith("native")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "bactalk.niagara-lowering-plan/v1",
            "lane": self.lane,
            "counts": dict(self.counts),
            "module_types": list(self.module_types),
            "unsupported": [
                {"block": block_id, "kind": kind.value} for block_id, kind in self.unsupported
            ],
            "blockers": list(self.blockers),
            "blocks": {
                block_id: {
                    "kind": decision.kind.value,
                    "lowering": decision.lowering.value,
                    "target": decision.target,
                }
                for block_id, decision in self.decisions.items()
            },
        }


def plan_lowering(graph: ControlGraph, policy: LoweringPolicy | None = None) -> LoweringPlan:
    """Classify every block of ``graph`` and decide which lane can carry it."""

    policy = policy or LoweringPolicy()
    decisions = {block.id: classify_block(block) for block in graph.blocks}
    counts = {item.value: 0 for item in LoweringClass}
    module_types: set[str] = set()
    unsupported: list[tuple[str, BlockKind]] = []
    for block_id, decision in decisions.items():
        counts[decision.lowering.value] += 1
        if decision.module_type:
            module_types.add(decision.module_type)
        if decision.lowering is LoweringClass.UNSUPPORTED:
            unsupported.append((block_id, decision.kind))
    blockers: list[str] = []
    if unsupported:
        kinds = sorted({kind.value for _, kind in unsupported})
        if policy.expert_program_objects:
            lane = "program_objects"
        else:
            lane = "blocked"
            blockers.append(
                "no native Niagara lowering for block kinds: "
                + ", ".join(kinds)
                + " (expert ProgramObject lane only)"
            )
    elif module_types:
        lane = "native_with_module"
    else:
        lane = "native_stock"
    return LoweringPlan(
        decisions=MappingProxyType(decisions),
        counts=MappingProxyType(counts),
        module_types=tuple(sorted(module_types)),
        unsupported=tuple(unsupported),
        lane=lane,
        blockers=tuple(blockers),
    )


# --- documentation ------------------------------------------------------------


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_matrix_markdown(rows: Iterable[LoweringDecision] = _ROWS) -> str:
    rows = list(rows)
    counts = {item: sum(1 for row in rows if row.lowering is item) for item in LoweringClass}
    lines = [
        "# Niagara lowering matrix",
        "",
        "Generated by `python -m bactalk.niagara.lowering --write` from",
        "`src/bactalk/niagara/lowering.py`. Do not edit by hand; `make test-native-bog`",
        "fails when this file is stale.",
        "",
        "Policy: stock first, then module, then fail closed. ProgramObjects survive only",
        "behind the expert flag (`LoweringPolicy(expert_program_objects=True)`). Every",
        "row is provisional until N7 proves it in the Shadow Runtime; nothing here is a",
        "claim of runtime qualification.",
        "",
        "| Class | Kinds |",
        "|---|---|",
        *(f"| `{item.value}` | {counts[item]} |" for item in LoweringClass),
        "",
        "## Matrix",
        "",
        "| IR kind | Class | Niagara target | IR slot → Niagara slot | Note |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        slots = ", ".join(f"{k}→{v}" for k, v in row.slot_map.items()) or "—"
        target = f"`{row.target}`" if row.target and not row.composite else (row.target or "—")
        lines.append(
            f"| `{row.kind.value}` | `{row.lowering.value}` | {_cell(target)} | "
            f"{_cell(slots)} | {_cell(row.note) or '—'} |"
        )
    lines += [
        "",
        f"Configuration-dependent: `{BlockKind.BOOLEAN_DELAY.value}` with `delay_on_init` "
        f"false lowers to `{TRUE_DELAY_MODULE.target}` (`{TRUE_DELAY_MODULE.lowering.value}`).",
        "",
        "## STOCK_WITHIN_BANDS deviations",
        "",
        "Each deviation is bounded by the scenarios listed; the Shadow Runtime (N6) and",
        "the three-way differential (N7) must pass every one of them within tolerance",
        "before the row is anything more than provisional.",
        "",
    ]
    for row in rows:
        if row.lowering is not LoweringClass.STOCK_WITHIN_BANDS:
            continue
        lines += [
            f"### `{row.kind.value}` → {row.target}",
            "",
            f"Deviation: {row.deviation}",
            "",
            "Bounding scenarios:",
            "",
            *(f"- {scenario}" for scenario in row.bounding_scenarios),
            "",
        ]
    lines += [
        "## MODULE components required (N3)",
        "",
        *(
            f"- `{name}`: " + ", ".join(f"`{row.kind.value}`" for row in rows if row.target == name)
            for name in sorted({row.target for row in rows if row.module_type})
        ),
        f"- `{TRUE_DELAY_MODULE.target}`: `{BlockKind.BOOLEAN_DELAY.value}` (delay_on_init false)",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render or check the lowering matrix doc.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true", help="write docs/niagara-lowering-matrix.md")
    group.add_argument("--check", action="store_true", help="fail if the committed doc is stale")
    args = parser.parse_args(argv)
    rendered = render_matrix_markdown()
    if args.write:
        MATRIX_DOC.write_text(rendered, encoding="utf-8")
        print(f"wrote {MATRIX_DOC}")
        return 0
    current = MATRIX_DOC.read_text(encoding="utf-8") if MATRIX_DOC.exists() else ""
    if current != rendered:
        print(f"{MATRIX_DOC} is stale; run python -m bactalk.niagara.lowering --write")
        return 1
    print(f"{MATRIX_DOC} is current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
