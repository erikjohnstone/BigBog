"""Deterministic SVG wiresheet previews from an emit report (N4).

One SVG per folder: a box per component at its ``wsAnnotation`` cell, a line
per link into the folder (links from other folders start at the left margin
with the source name), and nothing that depends on time, randomness or
platform, so the output can be snapshot-tested.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from bactalk.niagara.emit import EmitReport, FolderReport
from bactalk.niagara.layout import GRID_Y

CELL = 8  # pixels per grid cell
BOX_HEIGHT = (GRID_Y - 2) * CELL
FONT = "font-family='ui-monospace, Menlo, monospace' font-size='10'"


def render_folder_svg(folder: FolderReport) -> str:
    boxes = {name: (x * CELL, y * CELL, width * CELL) for name, _, x, y, width in folder.components}
    width = max((x + w for x, _, w in boxes.values()), default=0) + 3 * CELL
    height = max((y for _, y, _ in boxes.values()), default=0) + BOX_HEIGHT + 3 * CELL
    lines = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' "
        f"viewBox='0 0 {width} {height}' role='img' aria-label='{escape(folder.path)} wiresheet'>",
        f"<title>{escape(folder.path)}</title>",
        f"<rect width='{width}' height='{height}' fill='#fbfbfd'/>",
    ]
    external_row = 0
    for source, source_slot, target, target_slot in folder.links:
        if target not in boxes:
            continue
        tx, ty, _ = boxes[target]
        if source in boxes:
            sx, sy, sw = boxes[source]
            x1, y1 = sx + sw, sy + BOX_HEIGHT / 2
        else:
            external_row += 1
            x1, y1 = CELL, CELL * (external_row + 1)
            label = f"{escape(source)}.{escape(source_slot)}"
            lines.append(f"<text x='{x1}' y='{y1 - 2}' {FONT} fill='#666'>{label}</text>")
        x2, y2 = tx, ty + BOX_HEIGHT / 2
        title = f"{escape(source)}.{escape(source_slot)} → {escape(target)}.{escape(target_slot)}"
        lines.append(
            f"<path d='M{x1},{y1} L{x2},{y2}' stroke='#5b6b7a' stroke-width='1' fill='none'>"
            f"<title>{title}</title></path>"
        )
    for name, type_spec, _x, _y, _w in folder.components:
        x, y, w = boxes[name]
        lines.append(
            f"<g><rect x='{x}' y='{y}' width='{w}' height='{BOX_HEIGHT}' rx='3' fill='#ffffff' "
            f"stroke='#334' stroke-width='1'/>"
            f"<text x='{x + 3}' y='{y + 12}' {FONT} fill='#111'>{escape(name)}</text>"
            f"<text x='{x + 3}' y='{y + 24}' {FONT} fill='#667'>{escape(type_spec)}</text></g>"
        )
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def render_previews(report: EmitReport) -> dict[str, str]:
    """``{folder path: svg}`` for every folder of the report."""

    return {folder.path: render_folder_svg(folder) for folder in report.folders}
