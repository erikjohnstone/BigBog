"""Scan-by-scan comparison of the Shadow Runtime against the IR interpreter.

The comparison is a development and N7 tool: it maps every IR block to the
Niagara component the emitter produced for it (through the emitter's own
node table, never by guessing names) and, for each scan of a scenario, lists
the blocks whose primary output differs, earliest in topological order first.
The Shadow Runtime itself never sees the IR; only this comparison does.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from bactalk.domain import AcceptanceCase, ControlGraph, JobSpec, PointSpec
from bactalk.niagara.emit import (
    INPUTS_FOLDER,
    OUTPUTS_FOLDER,
    EmitOptions,
    _Emitter,
)
from bactalk.niagara.lowering import plan_lowering
from bactalk.niagara.shadow.engine import ShadowRuntime
from bactalk.niagara.shadow.policy import DEFAULT_POLICY, ExecutionPolicy
from bactalk.simulator import GraphInterpreter


@dataclass(frozen=True)
class Divergence:
    scan: int
    block_id: str
    kind: str
    slot: str
    interpreter: float | bool
    shadow: float | bool
    shadow_key: str


def block_keys(graph: ControlGraph, points: Iterable[PointSpec] = ()) -> dict[tuple[str, str], str]:
    """``(block id, IR output slot) -> shadow sample key`` for every emitted block output."""

    emitter = _Emitter(graph, {p.name: p for p in points}, {}, EmitOptions())
    emitter.build(plan_lowering(graph))
    keys: dict[tuple[str, str], str] = {}
    for block_id, outputs in emitter.outputs.items():
        for ir_slot, (node_key, niagara_slot) in outputs.items():
            node = emitter.nodes[node_key]
            if node.folder in {INPUTS_FOLDER, OUTPUTS_FOLDER}:
                keys[(block_id, ir_slot)] = node.name
            else:
                keys[(block_id, ir_slot)] = f"{node.folder}/{node.name}.{niagara_slot}"
    return keys


def _close(a: float | bool, b: float | bool, tolerance: float) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    fa, fb = float(a), float(b)
    if math.isnan(fa) and math.isnan(fb):
        return True
    return math.isclose(fa, fb, rel_tol=tolerance, abs_tol=tolerance)


def compare_case(
    job: JobSpec,
    case: AcceptanceCase,
    *,
    policy: ExecutionPolicy = DEFAULT_POLICY,
    kernel_backend: str = "python",
    tolerance: float = 1e-6,
    content: bytes | None = None,
) -> list[Divergence]:
    """Run one acceptance case in both engines and return every divergence."""

    from bactalk.niagara.emit import emit_bog

    graph = job.control_graph
    content = content if content is not None else emit_bog(graph, points=job.points).content
    keys = block_keys(graph, job.points)
    order = {block.id: index for index, block in enumerate(graph.topological_order())}
    kinds = {block.id: block.kind.value for block in graph.blocks}
    runtime = ShadowRuntime(content, policy=policy, kernel_backend=kernel_backend)
    free = runtime.free_inputs()
    sample_keys = runtime.signal_keys()
    interpreter = GraphInterpreter(graph)
    divergences: list[Divergence] = []
    phases = case.timeline or [case]
    current: dict[str, float | bool] = {}
    scan = 0
    try:
        for phase in phases:
            current.update(phase.inputs)
            interpreter.evaluate(dict(current), step_seconds=0.0)
            if scan == 0:
                # The station starts with its proxies already reading the first inputs.
                for name, value in current.items():
                    runtime.write_point(free[name].path, value)
                runtime.start()
            for _ in range(phase.repeat):
                scan += 1
                values = interpreter.evaluate(dict(current), step_seconds=phase.step_seconds)
                if policy.inputs_before_timers:
                    for name, value in current.items():
                        runtime.write_point(free[name].path, value)
                    runtime.advance(phase.step_seconds)
                else:
                    runtime.advance(phase.step_seconds)
                    for name, value in current.items():
                        runtime.write_point(free[name].path, value)
                snapshot = runtime.snapshot(keys=sample_keys)
                found: list[Divergence] = []
                for (block_id, ir_slot), key in keys.items():
                    ir_key = f"{block_id}.{ir_slot}"
                    if ir_key not in values or key not in snapshot:
                        continue
                    if not _close(values[ir_key], snapshot[key], tolerance):
                        found.append(
                            Divergence(
                                scan,
                                block_id,
                                kinds[block_id],
                                ir_slot,
                                values[ir_key],
                                snapshot[key],
                                key,
                            )
                        )
                found.sort(key=lambda item: order.get(item.block_id, 1 << 30))
                divergences.extend(found)
    finally:
        runtime.close()
    return divergences


def summarize(divergences: Iterable[Divergence], *, limit: int = 12) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for item in divergences:
        if item.block_id in seen:
            continue
        seen.add(item.block_id)
        lines.append(
            f"scan {item.scan}: {item.block_id} ({item.kind}).{item.slot} "
            f"interpreter={item.interpreter!r} shadow={item.shadow!r} [{item.shadow_key}]"
        )
        if len(lines) >= limit:
            break
    return lines


__all__ = ["Divergence", "block_keys", "compare_case", "summarize"]
