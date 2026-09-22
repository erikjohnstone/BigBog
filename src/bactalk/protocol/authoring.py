"""Helpers for the two protocol authors.

``GraphBuilder`` is for the logic author: blocks, links and a traceability map
(block id → requirement ids) that lands in ``graph.metadata``. The small functions
below are for requirement authors writing a set as data (``cite``, ``cond``, ``out``,
``point``, ``write_requirements``). Neither side imports the other's output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bactalk.domain import Block, BlockKind, Link

K = BlockKind


class GraphBuilder:
    def __init__(self) -> None:
        self.blocks: list[Block] = []
        self.links: list[Link] = []
        self.trace: dict[str, list[str]] = {}
        self._column = 0
        self._rows: dict[int, int] = {}

    def column(self, index: int) -> None:
        self._column = index

    def add(self, block_id: str, kind: K, label: str, requirement: str, **config: Any) -> str:
        row = self._rows.get(self._column, 0)
        self._rows[self._column] = row + 1
        self.blocks.append(
            Block(
                id=block_id,
                kind=kind,
                label=label,
                config=config,
                x=40 + 220 * self._column,
                y=40 + 90 * row,
            )
        )
        self.trace.setdefault(block_id, []).extend(requirement.split())
        return block_id

    def link(self, source: str, target: str, target_slot: str, source_slot: str = "out") -> None:
        self.links.append(
            Link(source=source, source_slot=source_slot, target=target, target_slot=target_slot)
        )

    # small idioms ------------------------------------------------------------------

    def const(self, block_id: str, value: float, label: str, requirement: str) -> str:
        return self.add(block_id, K.NUMERIC_CONST, label, requirement, value=value)

    def bconst(self, block_id: str, value: bool, label: str, requirement: str) -> str:
        return self.add(block_id, K.BOOLEAN_CONST, label, requirement, value=value)

    def gate(self, block_id: str, kind: K, a: str, b: str, label: str, requirement: str) -> str:
        self.add(block_id, kind, label, requirement)
        self.link(a, block_id, "a")
        self.link(b, block_id, "b")
        return block_id

    def gate_slots(
        self,
        block_id: str,
        kind: K,
        a: tuple[str, str],
        b: tuple[str, str],
        label: str,
        requirement: str,
    ) -> str:
        self.add(block_id, kind, label, requirement)
        self.link(a[0], block_id, "a", a[1])
        self.link(b[0], block_id, "b", b[1])
        return block_id

    def negate(self, block_id: str, source: str, label: str, requirement: str) -> str:
        self.add(block_id, K.NOT, label, requirement)
        self.link(source, block_id, "in")
        return block_id

    def timer(
        self, block_id: str, source: str, seconds: float, label: str, requirement: str
    ) -> str:
        self.add(block_id, K.TIMER, label, requirement, threshold_seconds=seconds)
        self.link(source, block_id, "in")
        return block_id


# --- requirement authoring ----------------------------------------------------------------


def cite(
    document: str,
    section: str,
    paragraph: str | None = None,
    fidelity: str = "paraphrase",
    note: str | None = None,
) -> dict[str, Any]:
    citation: dict[str, Any] = {"document": document, "section": section, "fidelity": fidelity}
    if paragraph:
        citation["paragraph"] = paragraph
    if note:
        citation["note"] = note
    return citation


def cond(point: str, operator: str, value: float | bool, deadband: float = 0.0) -> dict[str, Any]:
    condition: dict[str, Any] = {"point": point, "operator": operator, "value": value}
    if deadband:
        condition["deadband"] = deadband
    return condition


def out(
    point: str,
    operator: str,
    value: float | bool,
    tolerance: float = 0.0,
    upper: float | None = None,
) -> dict[str, Any]:
    outcome: dict[str, Any] = {"point": point, "operator": operator, "value": value}
    if tolerance:
        outcome["tolerance"] = tolerance
    if upper is not None:
        outcome["upper"] = upper
    return outcome


def point(
    name: str,
    label: str,
    data_type: str,
    direction: str,
    unit: str | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
    nominal: float | bool = 0.0,
    resolution: float | None = None,
    brick: str | None = None,
) -> dict[str, Any]:
    declaration: dict[str, Any] = {
        "name": name,
        "label": label,
        "data_type": data_type,
        "direction": direction,
        "nominal": nominal,
    }
    if unit:
        declaration["unit"] = unit
    if minimum is not None:
        declaration["minimum"] = minimum
    if maximum is not None:
        declaration["maximum"] = maximum
    if resolution:
        declaration["resolution"] = resolution
    if brick:
        declaration["brick_class"] = brick
    return declaration


def tolerate_one_scan(requirements: list[dict[str, Any]]) -> None:
    """Every timed requirement tolerates one scan: a per-second runtime (the Shadow
    Runtime, a Niagara station) sees a delay elapse up to one scan after a per-scan
    interpreter."""

    for requirement in requirements:
        timing = requirement.get("timing", {})
        if timing.get("delay_seconds") and not timing.get("tolerance_scans"):
            timing["tolerance_scans"] = 1


def write_requirements(
    documents: dict[str, dict[str, Any]], directory: Path, argv: list[str]
) -> int:
    """Write (or with ``--check`` verify) one JSON file per configuration."""

    status = 0
    for filename, document in documents.items():
        path = directory / filename
        text = json.dumps(document, indent=1, ensure_ascii=False) + "\n"
        if "--check" in argv:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                print(f"{path} differs from the author; run without --check")
                status = 1
            else:
                print(f"{path} matches")
            continue
        path.write_text(text, encoding="utf-8")
        print("wrote", path)
    return status


__all__ = [
    "GraphBuilder",
    "cite",
    "cond",
    "out",
    "point",
    "tolerate_one_scan",
    "write_requirements",
]
