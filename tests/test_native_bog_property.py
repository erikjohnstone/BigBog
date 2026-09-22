"""N7 property test: random valid IR graphs, compiled to .bog and run in the Shadow
Runtime, agree with the IR interpreter scan for scan.

The generator builds feed-forward graphs from the supported block set (stock
exact kinds and the bactalkG36 components); the Shadow Runtime runs under the
coarse-module-tick policy so every module component steps once per scan like the
interpreter, which makes the comparison exact to floating-point noise.
"""

from __future__ import annotations

import math
import random

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bactalk.domain import Block, BlockKind, ControlGraph, Link
from bactalk.niagara.emit import emit_bog
from bactalk.niagara.module import declared_types
from bactalk.niagara.shadow import ShadowRuntime
from bactalk.niagara.shadow.policy import DEFAULT_POLICY
from bactalk.niagara.validate import validate_bog
from bactalk.simulator import GraphInterpreter

pytestmark = [pytest.mark.native_bog]

SCAN = 60.0
POLICY = DEFAULT_POLICY.variant("property", module_period_seconds=SCAN)

NUMERIC_BINARY = (
    BlockKind.ADD,
    BlockKind.SUBTRACT,
    BlockKind.MULTIPLY,
    BlockKind.MINIMUM,
    BlockKind.MAXIMUM,
    BlockKind.AVERAGE,
)
COMPARISONS = (
    BlockKind.GREATER_THAN,
    BlockKind.GREATER_THAN_OR_EQUAL,
    BlockKind.LESS_THAN,
    BlockKind.LESS_THAN_OR_EQUAL,
)
BOOLEAN_BINARY = (BlockKind.AND, BlockKind.OR, BlockKind.XOR)


class Generator:
    """Grow a typed, acyclic, fully-connected graph from a seed."""

    def __init__(self, seed: int, size: int) -> None:
        self.rng = random.Random(seed)
        self.size = size
        self.blocks: list[Block] = []
        self.links: list[Link] = []
        self.numeric: list[str] = []
        self.boolean: list[str] = []
        self.consumed: set[str] = set()

    def add(self, kind: BlockKind, config: dict | None = None, **inputs: str) -> str:
        block_id = f"b{len(self.blocks)}"
        self.blocks.append(Block(id=block_id, kind=kind, label=block_id, config=config or {}))
        for slot, source in inputs.items():
            self.links.append(Link(source=source, target=block_id, target_slot=slot))
            self.consumed.add(source)
        return block_id

    def pick(self, pool: list[str]) -> str:
        return self.rng.choice(pool)

    def build(self) -> ControlGraph:
        rng = self.rng
        for _ in range(rng.randint(2, 4)):
            self.numeric.append(
                self.add(BlockKind.NUMERIC_INPUT, {"default": round(rng.uniform(-5, 5), 2)})
            )
        for _ in range(rng.randint(1, 3)):
            self.boolean.append(self.add(BlockKind.BOOLEAN_INPUT, {"default": rng.random() < 0.5}))
        for _ in range(rng.randint(1, 2)):
            self.numeric.append(
                self.add(BlockKind.NUMERIC_CONST, {"value": round(rng.uniform(-3, 3), 2)})
            )
        for _ in range(self.size):
            choice = rng.random()
            if choice < 0.30:
                self.numeric.append(
                    self.add(
                        rng.choice(NUMERIC_BINARY),
                        a=self.pick(self.numeric),
                        b=self.pick(self.numeric),
                    )
                )
            elif choice < 0.42:
                self.boolean.append(
                    self.add(
                        rng.choice(COMPARISONS),
                        a=self.pick(self.numeric),
                        b=self.pick(self.numeric),
                    )
                )
            elif choice < 0.52:
                self.boolean.append(
                    self.add(
                        rng.choice(BOOLEAN_BINARY),
                        a=self.pick(self.boolean),
                        b=self.pick(self.boolean),
                    )
                )
            elif choice < 0.57:
                self.boolean.append(self.add(BlockKind.NOT, **{"in": self.pick(self.boolean)}))
            elif choice < 0.65:
                self.numeric.append(
                    self.add(
                        BlockKind.NUMERIC_SWITCH,
                        selector=self.pick(self.boolean),
                        when_true=self.pick(self.numeric),
                        when_false=self.pick(self.numeric),
                    )
                )
            elif choice < 0.70:
                self.boolean.append(
                    self.add(
                        BlockKind.BOOLEAN_SWITCH,
                        selector=self.pick(self.boolean),
                        when_true=self.pick(self.boolean),
                        when_false=self.pick(self.boolean),
                    )
                )
            elif choice < 0.74:
                self.boolean.append(
                    self.add(
                        BlockKind.ONE_SHOT, {"initial": False}, **{"in": self.pick(self.boolean)}
                    )
                )
            elif choice < 0.77:
                self.boolean.append(
                    self.add(
                        BlockKind.BOOLEAN_FALLING_EDGE,
                        {"pre_u_start": False},
                        **{"in": self.pick(self.boolean)},
                    )
                )
            elif choice < 0.80:
                self.boolean.append(
                    self.add(
                        BlockKind.BOOLEAN_SET_RESET,
                        set=self.pick(self.boolean),
                        clear=self.pick(self.boolean),
                    )
                )
            elif choice < 0.84:
                timer = self.add(
                    BlockKind.TIMER,
                    {"threshold_seconds": float(rng.choice([60, 120, 180]))},
                    **{"in": self.pick(self.boolean)},
                )
                self.observe(timer, "elapsed", BlockKind.NUMERIC_OUTPUT)
                self.observe(timer, "passed", BlockKind.BOOLEAN_OUTPUT)
            elif choice < 0.87:
                self.boolean.append(
                    self.add(
                        BlockKind.BOOLEAN_TRUE_FALSE_HOLD,
                        {
                            "true_hold_seconds": float(rng.choice([60, 120])),
                            "false_hold_seconds": float(rng.choice([0, 60])),
                        },
                        **{"in": self.pick(self.boolean)},
                    )
                )
            elif choice < 0.90:
                self.boolean.append(
                    self.add(
                        BlockKind.BOOLEAN_DELAY,
                        {"on_delay_seconds": float(rng.choice([60, 120])), "delay_on_init": False},
                        **{"in": self.pick(self.boolean)},
                    )
                )
            elif choice < 0.93:
                self.numeric.append(
                    self.add(
                        BlockKind.HYSTERESIS,
                        {"u_low": -1.0, "u_high": 1.0, "initial": False},
                        **{"in": self.pick(self.numeric)},
                    )
                )
                self.boolean.append(self.numeric.pop())
            elif choice < 0.96:
                self.numeric.append(
                    self.add(
                        BlockKind.NUMERIC_SAMPLER,
                        {"sample_period_seconds": float(rng.choice([120, 180]))},
                        **{"in": self.pick(self.numeric)},
                    )
                )
            else:
                self.numeric.append(
                    self.add(
                        BlockKind.PID_WITH_RESET,
                        {
                            "controller_type": "PI",
                            "k": round(rng.uniform(0.1, 1.0), 2),
                            "ti": float(rng.choice([120, 300, 600])),
                            "td": 0.1,
                            "r": 1.0,
                            "ni": 0.9,
                            "nd": 10.0,
                            "y_min": 0.0,
                            "y_max": 1.0,
                            "xi_start": 0.0,
                            "yd_start": 0.0,
                            "y_reset": 0.0,
                            "reverse_acting": rng.random() < 0.5,
                        },
                        setpoint=self.pick(self.numeric),
                        measurement=self.pick(self.numeric),
                        trigger=self.pick(self.boolean),
                    )
                )
        # Every value that nothing consumes becomes an output, so it is observable.
        for source in list(self.numeric):
            if source not in self.consumed:
                self.add(BlockKind.NUMERIC_OUTPUT, **{"in": source})
        for source in list(self.boolean):
            if source not in self.consumed:
                self.add(BlockKind.BOOLEAN_OUTPUT, **{"in": source})
        return ControlGraph(name="PROPERTY", blocks=self.blocks, links=self.links)

    def observe(self, source: str, slot: str, kind: BlockKind) -> None:
        block_id = f"b{len(self.blocks)}"
        self.blocks.append(Block(id=block_id, kind=kind, label=block_id, config={}))
        self.links.append(Link(source=source, source_slot=slot, target=block_id, target_slot="in"))
        self.consumed.add(source)


def _inputs(graph: ControlGraph, rng: random.Random, scans: int) -> list[dict[str, float | bool]]:
    numeric = [b.id for b in graph.blocks if b.kind is BlockKind.NUMERIC_INPUT]
    boolean = [b.id for b in graph.blocks if b.kind is BlockKind.BOOLEAN_INPUT]
    values: dict[str, float | bool] = {name: float(rng.uniform(-5, 5)) for name in numeric}
    values.update({name: rng.random() < 0.5 for name in boolean})
    rows = []
    for _ in range(scans):
        for name in numeric:
            if rng.random() < 0.5:
                values[name] = round(float(values[name]) + rng.uniform(-1.0, 1.0), 3)
        for name in boolean:
            if rng.random() < 0.25:
                values[name] = not values[name]
        rows.append(dict(values))
    return rows


def _same(a: float | bool, b: float | bool) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    if math.isnan(float(a)) and math.isnan(float(b)):
        return True
    return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-9)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(seed=st.integers(min_value=0, max_value=10_000), size=st.integers(min_value=3, max_value=14))
def test_random_graphs_agree_between_the_interpreter_and_the_shadow_runtime(
    seed: int, size: int
) -> None:
    graph = Generator(seed, size).build()
    result = emit_bog(graph)
    report = validate_bog(result.content, declared_types=declared_types())
    assert report.ok, [str(issue) for issue in report.errors]
    rng = random.Random(seed ^ 0x5EED)
    rows = _inputs(graph, rng, scans=12)
    outputs = [b.id for b in graph.blocks if b.kind.value.endswith("_output")]
    interpreter = GraphInterpreter(graph)
    runtime = ShadowRuntime(result.content, policy=POLICY, kernel_backend="python")
    free = runtime.free_inputs()
    try:
        first = rows[0]
        interpreter.evaluate(dict(first), step_seconds=0.0)
        for name, value in first.items():
            runtime.write_point(free[name].path, value)
        runtime.start()
        keys = runtime.signal_keys()
        for scan, row in enumerate(rows, start=1):
            expected = interpreter.evaluate(dict(row), step_seconds=SCAN)
            for name, value in row.items():
                runtime.write_point(free[name].path, value)
            runtime.advance(SCAN)
            actual = runtime.snapshot(keys=keys)
            for output in outputs:
                assert _same(expected[output], actual[output]), (
                    f"seed {seed} size {size} scan {scan}: {output} "
                    f"interpreter={expected[output]!r} "
                    f"shadow={actual[output]!r}"
                )
    finally:
        runtime.close()
