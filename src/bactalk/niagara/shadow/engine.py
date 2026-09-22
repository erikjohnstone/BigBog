"""The Shadow Runtime engine: clock, links and event-driven propagation (N6 items 2, 3).

- **Links propagate on change** (S-LINK-1): a component executes when one of its
  inputs receives a different value, and its changed outputs fire their links.
- **Station start** (S-LINK-2): every component starts, every link pushes its
  source value, then every component executes once and the changes propagate.
- **Loops** (S-LINK-3): a combinational loop is fine while values converge; a
  component that executes more than ``policy.loop_limit`` times inside one
  propagation raises :class:`PropagationLoopError` naming it.
- **Clock** (S-CLOCK-1): simulated seconds; timers fire in due order, ties in
  policy order, and each timer's effects propagate before the next fires.
"""

from __future__ import annotations

import heapq
import random
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from bactalk.niagara.shadow.blocks import (
    REGISTRY,
    Block,
    KernelBackend,
    WritablePoint,
    make_kernel_backend,
)
from bactalk.niagara.shadow.loader import (
    CONTAINER_TYPES,
    ComponentNode,
    Program,
    ShadowLoadError,
    load_program,
)
from bactalk.niagara.shadow.policy import DEFAULT_POLICY, ExecutionPolicy
from bactalk.niagara.shadow.status import Status, StatusValue


class PropagationLoopError(RuntimeError):
    def __init__(self, path: str, count: int) -> None:
        super().__init__(
            f"{path} executed {count} times inside one propagation: unstable link loop"
        )
        self.path = path
        self.count = count


@dataclass(frozen=True)
class Wire:
    source: Block
    source_slot: str
    target: Block
    target_slot: str
    order: int


class ShadowRuntime:
    """Loads a ``.bog`` and runs it with Niagara-like semantics."""

    def __init__(
        self,
        source: Path | bytes | Program,
        *,
        policy: ExecutionPolicy = DEFAULT_POLICY,
        kernel_backend: str | KernelBackend = "auto",
        registry: Mapping[str, type[Block]] = REGISTRY,
        external_links: str = "error",
    ) -> None:
        self.policy = policy
        self.registry = registry
        self.program = (
            source
            if isinstance(source, Program)
            else load_program(source, known_types=tuple(registry), external_links=external_links)
        )
        self.kernels: KernelBackend = (
            kernel_backend
            if not isinstance(kernel_backend, str)
            else make_kernel_backend(kernel_backend)
        )
        self.now = 0.0
        self._timers: list[tuple[float, float, int, Block, str]] = []
        self._timer_seq = 0
        self._cancelled: set[int] = set()
        self._rng = random.Random(policy.seed)
        self.blocks: dict[str, Block] = {}
        self.ordered: list[Block] = []
        self.wires: list[Wire] = []
        self.out_links: dict[tuple[str, str], list[Wire]] = {}
        self.in_links: dict[tuple[str, str], Wire] = {}
        self.started = False
        self.execution_count = 0
        self.trace_hook: Callable[[float, Block], None] | None = None
        """Called after every execution with the clock and the block (development tracing)."""

        self._build()

    # -- construction -----------------------------------------------------------

    def _build(self) -> None:
        for node in self.program.components:
            if node.type in CONTAINER_TYPES:
                continue
            cls = self.registry.get(node.type)
            if cls is None:
                raise ShadowLoadError(f"no block implementation for {node.type} at {node.path}")
            block = cls(node, self)
            self.blocks[node.path] = block
            self.ordered.append(block)
        for link in self.program.links:
            source = self.blocks.get(link.source.path)
            target = self.blocks.get(link.target.path)
            if source is None or target is None:
                raise ShadowLoadError(
                    f"link {link.source.path}.{link.source_slot} -> "
                    f"{link.target.path}.{link.target_slot} joins a non-executable component"
                )
            if link.source_slot not in source.outputs:
                raise ShadowLoadError(f"{link.source.path} has no output slot {link.source_slot!r}")
            if link.target_slot not in target.inputs:
                raise ShadowLoadError(f"{link.target.path} has no input slot {link.target_slot!r}")
            key = (target.path, link.target_slot)
            if key in self.in_links:
                raise ShadowLoadError(
                    f"{link.target.path}.{link.target_slot} is driven by two links"
                )
            wire = Wire(source, link.source_slot, target, link.target_slot, link.order)
            self.wires.append(wire)
            self.in_links[key] = wire
            self.out_links.setdefault((source.path, link.source_slot), []).append(wire)
        for wires in self.out_links.values():
            self._order(wires, self.policy.link_order)

    def _order(self, items: list, mode: str) -> None:
        if mode == "reverse":
            items.reverse()
        elif mode == "shuffle":
            self._rng.shuffle(items)
        elif mode != "document":
            raise ValueError(f"unknown order {mode!r}")

    # -- context API for blocks -------------------------------------------------------

    def schedule(self, block: Block, delay_seconds: float, tag: str) -> int:
        self._timer_seq += 1
        due = self.now + max(0.0, delay_seconds)
        if self.policy.tick_order == "document":
            tie = float(block.node.order)
        elif self.policy.tick_order == "reverse":
            tie = -float(block.node.order)
        elif self.policy.tick_order == "shuffle":
            tie = self._rng.random()
        else:
            raise ValueError(f"unknown tick order {self.policy.tick_order!r}")
        heapq.heappush(self._timers, (due, tie, self._timer_seq, block, tag))
        return self._timer_seq

    def cancel(self, handle: int) -> None:
        self._cancelled.add(handle)

    def block_at(self, path: str) -> Block | None:
        return self.blocks.get(path)

    # -- lifecycle ---------------------------------------------------------------------

    def start(self) -> None:
        """S-LINK-2: start components, activate links, execute everything once."""

        if self.started:
            raise RuntimeError("runtime already started")
        self.started = True
        for block in self.ordered:
            block.start()
        for block in self.ordered:
            block.take_changes()
        for wire in sorted(self.wires, key=lambda item: item.order):
            wire.target.set_input(wire.target_slot, wire.source.outputs[wire.source_slot])
        # One synchronous pass in start order: each block executes once with the
        # inputs pushed so far; its changed outputs are pushed on without cascading.
        order = self._start_order()
        counts: dict[str, int] = {}
        dirty: dict[str, Block] = {}
        for block in order:
            dirty.pop(block.path, None)
            self._execute(block, counts)
            for slot in block.take_changes():
                for wire in self.out_links.get((block.path, slot), ()):
                    if (
                        wire.target.set_input(wire.target_slot, block.outputs[slot])
                        and wire.target.executes_on_input_change()
                    ):
                        dirty[wire.target.path] = wire.target
        # Then the ordinary on-change propagation settles whatever changed late.
        while dirty:
            _, block = next(iter(dirty.items()))
            del dirty[block.path]
            self._run(block, counts)
        self._drain_zero_timers()

    def _start_order(self) -> list[Block]:
        """Start order: a topological order over the wires that opens loops at delays.

        Depth-first search from the delay blocks first (their first output ignores
        their input), then from the sources, then from everything else in document
        order; back edges are ignored, so a feedback wire never orders a block
        before the block that feeds it.
        """

        mode = self.policy.start_order
        if mode != "topological":
            order = list(self.ordered)
            self._order(order, mode)
            return order
        successors: dict[str, list[Block]] = {block.path: [] for block in self.ordered}
        indegree = {block.path: 0 for block in self.ordered}
        for wire in self.wires:
            successors[wire.source.path].append(wire.target)
            indegree[wire.target.path] += 1
        roots = [block for block in self.ordered if block.SOURCE_AT_START]
        roots += [
            block
            for block in self.ordered
            if not block.SOURCE_AT_START and indegree[block.path] == 0
        ]
        roots += [
            block
            for block in self.ordered
            if not block.SOURCE_AT_START and indegree[block.path] != 0
        ]
        state: dict[str, int] = {}  # 1 = on the stack, 2 = finished
        postorder: list[Block] = []
        for root in roots:
            if state.get(root.path):
                continue
            stack: list[tuple[Block, int]] = [(root, 0)]
            state[root.path] = 1
            while stack:
                block, index = stack[-1]
                children = successors[block.path]
                if index < len(children):
                    stack[-1] = (block, index + 1)
                    child = children[index]
                    if not state.get(child.path):
                        state[child.path] = 1
                        stack.append((child, 0))
                    continue
                state[block.path] = 2
                postorder.append(block)
                stack.pop()
        postorder.reverse()
        return postorder

    def close(self) -> None:
        self.kernels.close()

    def __enter__(self) -> ShadowRuntime:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- stimulus ------------------------------------------------------------------------

    def set_input(self, path: str, slot: str, value: StatusValue) -> None:
        """Set an input slot; before ``start`` the value simply waits for station start."""

        block = self._require(path)
        if block.set_input(slot, value) and self.started:
            self._propagate_from(block)

    def write_point(
        self, path: str, value: float | bool, *, level: int = 16, status: Status = Status.OK
    ) -> None:
        """Write a writable point's priority level (default in16) as a proxy would."""

        block = self._require(path)
        if not isinstance(block, WritablePoint):
            raise TypeError(f"{path} is not a writable point")
        if not 1 <= level <= 16:
            raise ValueError("priority level must be 1..16")
        typed: float | bool = bool(value) if block.KIND == "b" else float(value)
        self.set_input(path, f"in{level}", StatusValue(typed, status))

    def override(
        self, path: str, value: float | bool, duration_seconds: float | None = None
    ) -> None:
        """Operator override at level 8 (S-WRITABLE-2/3)."""

        block = self._require(path)
        if not isinstance(block, WritablePoint):
            raise TypeError(f"{path} is not a writable point")
        block.override(value, duration_seconds)
        self._propagate_from(block)

    def auto(self, path: str) -> None:
        block = self._require(path)
        if not isinstance(block, WritablePoint):
            raise TypeError(f"{path} is not a writable point")
        block.auto()
        self._propagate_from(block)

    def emergency_override(self, path: str, value: float | bool) -> None:
        block = self._require(path)
        if not isinstance(block, WritablePoint):
            raise TypeError(f"{path} is not a writable point")
        block.emergency_override(value)
        self._propagate_from(block)

    def emergency_auto(self, path: str) -> None:
        block = self._require(path)
        if not isinstance(block, WritablePoint):
            raise TypeError(f"{path} is not a writable point")
        block.emergency_auto()
        self._propagate_from(block)

    def read(self, path: str, slot: str = "out") -> StatusValue:
        return self._require(path).outputs[slot]

    def _require(self, path: str) -> Block:
        block = self.blocks.get(path)
        if block is None:
            raise KeyError(f"no component at {path}")
        return block

    # -- clock --------------------------------------------------------------------------

    def advance(self, seconds: float) -> None:
        """Run the clock forward, firing every timer due on the way (S-CLOCK-1)."""

        if seconds < 0.0:
            raise ValueError("cannot run the clock backwards")
        target = self.now + seconds
        while self._timers and self._timers[0][0] <= target + 1e-9:
            due, _, seq, block, tag = heapq.heappop(self._timers)
            if seq in self._cancelled:
                self._cancelled.discard(seq)
                continue
            self.now = max(self.now, due)
            block.on_timer(tag)
            # The timer callback already executed the block; only propagate its changes.
            self._run(block, {}, execute_first=False)
        self.now = target

    def _drain_zero_timers(self) -> None:
        self.advance(0.0)

    def pending_timers(self) -> int:
        return sum(1 for timer in self._timers if timer[2] not in self._cancelled)

    # -- propagation -----------------------------------------------------------------------

    def _propagate_from(self, block: Block) -> None:
        counts: dict[str, int] = {}
        self._run(block, counts)

    def _run(self, first: Block, counts: dict[str, int], *, execute_first: bool = True) -> None:
        """Execute ``first`` (optionally) and propagate its changes through the links."""

        depth_first = self.policy.propagation == "depth"
        work: deque[tuple[Block, str, Block, str]] = deque()

        def fire(block: Block) -> None:
            for slot in block.take_changes():
                wires = self.out_links.get((block.path, slot), ())
                if depth_first:
                    for wire in reversed(wires):
                        work.appendleft(
                            (wire.source, wire.source_slot, wire.target, wire.target_slot)
                        )
                else:
                    for wire in wires:
                        work.append((wire.source, wire.source_slot, wire.target, wire.target_slot))

        if execute_first:
            self._execute(first, counts)
        fire(first)
        while work:
            source, source_slot, target, target_slot = work.popleft()
            if not target.set_input(target_slot, source.outputs[source_slot]):
                continue
            if not target.executes_on_input_change():
                continue
            self._execute(target, counts)
            fire(target)

    def _execute(self, block: Block, counts: dict[str, int]) -> None:
        count = counts.get(block.path, 0) + 1
        counts[block.path] = count
        if count > self.policy.loop_limit:
            raise PropagationLoopError(block.path, count)
        self.execution_count += 1
        block.execute()
        if self.trace_hook is not None:
            self.trace_hook(self.now, block)

    # -- inspection ---------------------------------------------------------------------------

    def writable_points(self) -> list[WritablePoint]:
        return [block for block in self.ordered if isinstance(block, WritablePoint)]

    def free_inputs(self) -> dict[str, WritablePoint]:
        """Writable points whose in16 is not driven by a link: the program's inputs, by name."""

        result: dict[str, WritablePoint] = {}
        for block in self.writable_points():
            if (block.path, "in16") not in self.in_links and all(
                (block.path, f"in{n}") not in self.in_links for n in range(1, 17)
            ):
                result.setdefault(block.name, block)
        return result

    def driven_points(self) -> dict[str, WritablePoint]:
        """Writable points driven by a link: the program's outputs, by name."""

        return {
            block.name: block
            for block in self.writable_points()
            if any((block.path, f"in{n}") in self.in_links for n in range(1, 17))
        }

    def snapshot(
        self, *, keys: Mapping[str, tuple[Block, str]] | None = None
    ) -> dict[str, float | bool]:
        """Every output as ``{key: value}`` plus sparse ``key.status`` bits when not ok."""

        keys = keys if keys is not None else self.signal_keys()
        sample: dict[str, float | bool] = {}
        for key, (block, slot) in keys.items():
            value = block.outputs[slot]
            sample[key] = value.value
            if value.status != Status.OK:
                sample[f"{key}.status"] = float(int(value.status))
        return sample

    def signal_keys(self) -> dict[str, tuple[Block, str]]:
        """Sample keys: point names for writable points, ``Folder/name[.slot]`` for the rest."""

        keys: dict[str, tuple[Block, str]] = {}
        for block in self.ordered:
            if not block.outputs:
                continue
            if isinstance(block, WritablePoint):
                keys.setdefault(block.name, (block, "out"))
                keys.setdefault(f"{block.name}.out", (block, "out"))
                continue
            folder = (
                block.node.parent.name
                if block.node.parent is not None and block.node.parent.parent is not None
                else ""
            )
            base = f"{folder}/{block.name}" if folder else block.name
            first = next(iter(block.outputs))
            keys.setdefault(base, (block, first))
            for slot in block.outputs:
                keys.setdefault(f"{base}.{slot}", (block, slot))
        return keys

    def component_paths(self) -> Iterable[str]:
        return (block.path for block in self.ordered)

    def blocks_of(self, cls: type[Block]) -> list[Block]:
        return [block for block in self.ordered if isinstance(block, cls)]

    def node_of(self, path: str) -> ComponentNode:
        return self._require(path).node


__all__ = ["PropagationLoopError", "ShadowRuntime", "Wire"]
