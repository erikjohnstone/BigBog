"""Machine-readable catalog of the typed control-graph block kinds.

The wiresheet renders ports from this catalog rather than inferring them
from links, so an unlinked input still shows as an open slot and a boolean
slot is never drawn as numeric. The catalog is derived from ``BLOCK_SLOTS``
so it can never drift from the interpreter.
"""

from __future__ import annotations

from bactalk.domain import BLOCK_SLOTS, BlockKind

SCHEMA = "bactalk.block-catalog/v1"

FAMILIES = (
    "io",
    "const",
    "math",
    "compare",
    "logic",
    "switch",
    "timing",
    "state",
    "filter",
    "loop",
    "plant",
    "assert",
)

_FAMILY: dict[BlockKind, str] = {
    BlockKind.NUMERIC_INPUT: "io",
    BlockKind.BOOLEAN_INPUT: "io",
    BlockKind.NUMERIC_OUTPUT: "io",
    BlockKind.BOOLEAN_OUTPUT: "io",
    BlockKind.NUMERIC_CONST: "const",
    BlockKind.BOOLEAN_CONST: "const",
    BlockKind.ADD: "math",
    BlockKind.SUBTRACT: "math",
    BlockKind.MULTIPLY: "math",
    BlockKind.DIVIDE: "math",
    BlockKind.MINIMUM: "math",
    BlockKind.MAXIMUM: "math",
    BlockKind.AVERAGE: "math",
    BlockKind.RESET: "math",
    BlockKind.NUMERIC_ROUND: "math",
    BlockKind.NUMERIC_LIMIT_SLEW_RATE: "filter",
    BlockKind.GREATER_THAN: "compare",
    BlockKind.GREATER_THAN_OR_EQUAL: "compare",
    BlockKind.LESS_THAN: "compare",
    BlockKind.LESS_THAN_OR_EQUAL: "compare",
    BlockKind.EQUAL: "compare",
    BlockKind.NOT_EQUAL: "compare",
    BlockKind.HYSTERESIS: "compare",
    BlockKind.NUMERIC_CHANGED: "compare",
    BlockKind.NUMERIC_INCREASED: "compare",
    BlockKind.NUMERIC_DECREASED: "compare",
    BlockKind.AND: "logic",
    BlockKind.OR: "logic",
    BlockKind.XOR: "logic",
    BlockKind.NOT: "logic",
    BlockKind.NUMERIC_SWITCH: "switch",
    BlockKind.BOOLEAN_SWITCH: "switch",
    BlockKind.BOOLEAN_DELAY: "timing",
    BlockKind.ONE_SHOT: "timing",
    BlockKind.BOOLEAN_FALLING_EDGE: "timing",
    BlockKind.BOOLEAN_SAMPLE_TRIGGER: "timing",
    BlockKind.BOOLEAN_PRE_HOST_TICK: "timing",
    BlockKind.BOOLEAN_INITIALIZATION: "timing",
    BlockKind.BOOLEAN_TRUE_FALSE_HOLD: "timing",
    BlockKind.TIMER: "timing",
    BlockKind.TIMER_WITH_RESET: "timing",
    BlockKind.TIMER_ACCUMULATING: "timing",
    BlockKind.NUMERIC_LATCH: "state",
    BlockKind.BOOLEAN_LATCH: "state",
    BlockKind.BOOLEAN_SET_RESET: "state",
    BlockKind.NUMERIC_UNIT_DELAY: "state",
    BlockKind.MOVING_AVERAGE: "filter",
    BlockKind.NUMERIC_SAMPLER: "filter",
    BlockKind.NUMERIC_FIRST_ORDER_HOLD: "filter",
    BlockKind.TRIM_AND_RESPOND: "loop",
    BlockKind.TRIM_AND_RESPOND_HOLD: "loop",
    BlockKind.PI_LOOP: "loop",
    BlockKind.PID_WITH_RESET: "loop",
    BlockKind.PLANT_EQUIPMENT_AVAILABILITY: "plant",
    BlockKind.PLANT_ENABLE: "plant",
    BlockKind.PLANT_HRC_ENABLE: "plant",
    BlockKind.PLANT_HRC_MODE_CONTROL: "plant",
    BlockKind.PLANT_STAGE_COMPLETION: "plant",
    BlockKind.PLANT_STAGE_INDEX: "plant",
    BlockKind.BOOLEAN_ASSERT_WARNING: "assert",
}

# Kinds whose output depends on earlier scans, so a value on the wire is a
# function of history and not only of the current inputs.
_STATEFUL: frozenset[BlockKind] = frozenset(
    {
        BlockKind.BOOLEAN_DELAY,
        BlockKind.ONE_SHOT,
        BlockKind.BOOLEAN_FALLING_EDGE,
        BlockKind.BOOLEAN_SAMPLE_TRIGGER,
        BlockKind.BOOLEAN_PRE_HOST_TICK,
        BlockKind.BOOLEAN_INITIALIZATION,
        BlockKind.BOOLEAN_TRUE_FALSE_HOLD,
        BlockKind.TIMER,
        BlockKind.TIMER_WITH_RESET,
        BlockKind.TIMER_ACCUMULATING,
        BlockKind.NUMERIC_LATCH,
        BlockKind.BOOLEAN_LATCH,
        BlockKind.BOOLEAN_SET_RESET,
        BlockKind.NUMERIC_UNIT_DELAY,
        BlockKind.MOVING_AVERAGE,
        BlockKind.NUMERIC_SAMPLER,
        BlockKind.NUMERIC_FIRST_ORDER_HOLD,
        BlockKind.HYSTERESIS,
        BlockKind.NUMERIC_CHANGED,
        BlockKind.NUMERIC_INCREASED,
        BlockKind.NUMERIC_DECREASED,
        BlockKind.TRIM_AND_RESPOND,
        BlockKind.TRIM_AND_RESPOND_HOLD,
        BlockKind.PI_LOOP,
        BlockKind.PID_WITH_RESET,
        BlockKind.PLANT_ENABLE,
        BlockKind.PLANT_HRC_ENABLE,
        BlockKind.PLANT_HRC_MODE_CONTROL,
        BlockKind.PLANT_STAGE_COMPLETION,
        BlockKind.PLANT_STAGE_INDEX,
    }
)

# Feedback kinds break a wiresheet cycle by reading the previous scan; the
# UI draws their incoming wire dashed so a loop reads as a loop.
_FEEDBACK: frozenset[BlockKind] = frozenset(
    {BlockKind.NUMERIC_UNIT_DELAY, BlockKind.BOOLEAN_PRE_HOST_TICK}
)


def family_of(kind: BlockKind) -> str:
    return _FAMILY[kind]


def catalog() -> dict:
    """Serialize every block kind with its declared, typed slots."""
    kinds = []
    for kind in BlockKind:
        slots = BLOCK_SLOTS[kind]
        kinds.append(
            {
                "kind": kind.value,
                "family": _FAMILY[kind],
                "stateful": kind in _STATEFUL,
                "feedback": kind in _FEEDBACK,
                "inputs": [
                    {"name": name, "type": data_type.value}
                    for name, data_type in slots.inputs.items()
                ],
                "outputs": [
                    {"name": name, "type": data_type.value}
                    for name, data_type in slots.outputs.items()
                ],
            }
        )
    return {"schema": SCHEMA, "families": list(FAMILIES), "kinds": kinds}
