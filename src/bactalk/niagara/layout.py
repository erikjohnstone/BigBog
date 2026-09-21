"""Deterministic left-to-right layered layout for a wiresheet folder (N4).

Blocks are layered by longest path from the folder's sources over the links
inside the folder; within a layer they are ordered by the barycentre of their
predecessors' rows, ties broken by name, so the same graph always lays out the
same way. Positions are Niagara ``wsAnnotation`` grid cells.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

GRID_X = 14
GRID_Y = 8
MARGIN = 2
BLOCK_WIDTH = 10


@dataclass(frozen=True)
class Placement:
    name: str
    layer: int
    row: int
    x: int
    y: int
    width: int = BLOCK_WIDTH


def layer_nodes(nodes: Iterable[str], edges: Iterable[tuple[str, str]]) -> dict[str, int]:
    """Longest-path layering; cycles (feedback links) are cut at the back edge."""

    order = list(nodes)
    index = {name: position for position, name in enumerate(order)}
    successors: dict[str, list[str]] = {name: [] for name in order}
    indegree = {name: 0 for name in order}
    for source, target in edges:
        if source not in index or target not in index or source == target:
            continue
        successors[source].append(target)
        indegree[target] += 1
    layers = {name: 0 for name in order}
    ready = sorted((name for name in order if indegree[name] == 0), key=lambda n: index[n])
    seen: set[str] = set()
    while ready:
        current = ready.pop(0)
        seen.add(current)
        for target in successors[current]:
            layers[target] = max(layers[target], layers[current] + 1)
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort(key=lambda n: index[n])
    # Anything left is on a cycle: keep it after its longest acyclic predecessor.
    for name in order:
        if name not in seen:
            predecessors = [s for s, t in edges if t == name and s in seen]
            layers[name] = max((layers[p] + 1 for p in predecessors), default=0)
            seen.add(name)
    return layers


def layout_folder(
    nodes: Iterable[str],
    edges: Iterable[tuple[str, str]],
    *,
    grid_x: int = GRID_X,
    grid_y: int = GRID_Y,
) -> Mapping[str, Placement]:
    order = list(nodes)
    edge_list = [(s, t) for s, t in edges if s in order and t in order]
    layers = layer_nodes(order, edge_list)
    by_layer: dict[int, list[str]] = {}
    for name in order:
        by_layer.setdefault(layers[name], []).append(name)
    rows: dict[str, int] = {}
    placements: dict[str, Placement] = {}
    predecessors: dict[str, list[str]] = {name: [] for name in order}
    for source, target in edge_list:
        if layers[source] < layers[target]:
            predecessors[target].append(source)
    for layer in sorted(by_layer):
        members = by_layer[layer]

        def key(name: str) -> tuple[float, str]:
            rows_of = [rows[p] for p in predecessors[name] if p in rows]
            centre = sum(rows_of) / len(rows_of) if rows_of else float("inf")
            return (centre, name)

        for row, name in enumerate(sorted(members, key=key)):
            rows[name] = row
            placements[name] = Placement(
                name=name,
                layer=layer,
                row=row,
                x=MARGIN + layer * grid_x,
                y=MARGIN + row * grid_y,
            )
    return placements


def overlaps(placements: Iterable[Placement], *, height: int = GRID_Y - 1) -> list[tuple[str, str]]:
    """Pairs of placements whose cells intersect; empty for a valid layout."""

    items = list(placements)
    found = []
    for i, a in enumerate(items):
        for b in items[i + 1 :]:
            if (
                a.x < b.x + b.width
                and b.x < a.x + a.width
                and a.y < b.y + height
                and b.y < a.y + height
            ):
                found.append((a.name, b.name))
    return found
