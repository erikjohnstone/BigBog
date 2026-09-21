from __future__ import annotations

import io
import math
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from bactalk.domain import BlockKind, ControlGraph, HistoryRequirement
from bactalk.niagara.units import numeric_facets, units_facet

_NUMERIC_WRITABLES = {BlockKind.NUMERIC_INPUT, BlockKind.NUMERIC_OUTPUT}
_BOOLEAN_WRITABLES = {BlockKind.BOOLEAN_INPUT, BlockKind.BOOLEAN_OUTPUT}
_MAX_NIAGARA_RECORD_CAPACITY = 2_147_483_647


def inject_fixed_interval_histories(
    archive_path: Path,
    graph: ControlGraph,
    histories: list[HistoryRequirement],
    *,
    program_root_ord: str | None = None,
    units: dict[str, str | None] | None = None,
) -> tuple[str, ...]:
    """Add qualified Niagara interval-history extensions to a generated ``.bog``.

    pybog does not currently expose history-extension builders.  This narrow
    post-processor is based on real Niagara 4 object graphs in the pinned MIT
    ``n4-hvac-optimization-blocks`` corpus.  COV histories remain review-only
    until their serialized collector properties are qualified from a real
    archive and licensed runtime.
    """

    selected = [item for item in histories if item.mode == "fixed_interval"]
    if not selected:
        return ()

    members, xml_index, root = _read_archive(archive_path)
    folder = _graph_folder(root, graph.name)
    point_elements = {child.attrib.get("n"): child for child in folder if child.tag == "p"}
    blocks = {block.id: block for block in graph.blocks}
    handles = [int(element.attrib["h"], 16) for element in root.iter("p") if "h" in element.attrib]
    next_handle = max(handles, default=0) + 1
    emitted: list[str] = []

    for requirement in selected:
        block = blocks.get(requirement.point)
        point = point_elements.get(requirement.point)
        if block is None or point is None:
            raise ValueError(
                f"history point is absent from the compiled Niagara graph: {requirement.point}"
            )
        if block.kind in _NUMERIC_WRITABLES:
            extension_name = "NumericInterval"
            extension_type = "h:NumericIntervalHistoryExt"
            record_type = "history:NumericTrendRecord"
            schema_value = (
                "timestamp,baja:AbsTime;trendFlags,history:TrendFlags;"
                "status,baja:Status;value,baja:Double"
            )
            value_facets = numeric_facets((units or {}).get(requirement.point), precision=1)
        elif block.kind in _BOOLEAN_WRITABLES:
            extension_name = "BooleanInterval"
            extension_type = "h:BooleanIntervalHistoryExt"
            record_type = "history:BooleanTrendRecord"
            schema_value = (
                "timestamp,baja:AbsTime;trendFlags,history:TrendFlags;"
                "status,baja:Status;value,baja:Boolean"
            )
            value_facets = "trueText=s:true|falseText=s:false"
        else:
            raise ValueError(
                f"fixed-interval history {requirement.point} requires a numeric or boolean "
                f"writable, not {block.kind.value}"
            )
        if any(child.attrib.get("n") == extension_name for child in point if child.tag == "p"):
            raise ValueError(
                f"history extension name collision on {requirement.point}: {extension_name}"
            )
        if requirement.interval_seconds is None:  # guarded by the domain model
            raise ValueError(f"fixed-interval history {requirement.point} has no interval")
        capacity = math.ceil(requirement.retention_days * 86_400 / requirement.interval_seconds)
        if capacity > _MAX_NIAGARA_RECORD_CAPACITY:
            raise ValueError(
                f"history {requirement.point} requires {capacity} records, above Niagara's "
                f"qualified integer capacity limit {_MAX_NIAGARA_RECORD_CAPACITY}"
            )

        extension_handle = format(next_handle, "x")
        config_handle = format(next_handle + 1, "x")
        next_handle += 2
        extension = ElementTree.SubElement(
            point,
            "p",
            {
                "n": extension_name,
                "h": extension_handle,
                "m": "h=history",
                "t": extension_type,
            },
        )
        config = ElementTree.SubElement(
            extension,
            "p",
            {"n": "historyConfig", "h": config_handle, "t": "h:HistoryConfig"},
        )
        root_ord = program_root_ord or f"station:|slot:/{graph.name}"
        source_path = f"{root_ord}/{requirement.point}/{extension_name}"
        _property(config, "source", "b:OrdList", source_path)
        _property(config, "sourceHandle", "b:Ord", f"h:{extension_handle}")
        _property(config, "recordType", "b:TypeSpec", record_type)
        _property(config, "schema", "h:HistorySchema", schema_value)
        _property(config, "capacity", "h:Capacity", f"1:{capacity}")
        _property(
            config,
            "interval",
            "h:CollectionInterval",
            f"false:{requirement.interval_seconds * 1000}",
        )
        if block.kind in _NUMERIC_WRITABLES:
            ElementTree.SubElement(
                config,
                "p",
                {"n": "minRolloverValue", "f": "r", "t": "h:RolloverValue"},
            )
            ElementTree.SubElement(
                config,
                "p",
                {"n": "maxRolloverValue", "f": "r", "t": "h:RolloverValue"},
            )
            ElementTree.SubElement(
                config,
                "p",
                {
                    "n": "precision",
                    "f": "r",
                    "x": "fieldEditor=s:history$3aPrecisionFE|"
                    "uxFieldEditor=s:history$3aPrecisionEditor",
                    "t": "b:Integer",
                    "v": "32",
                },
            )
        _property(config, "valueFacets", "b:Facets", value_facets)
        emitted.append(requirement.point)

    _write_archive(archive_path, members, xml_index, root)
    return tuple(emitted)


_Members = list[tuple[zipfile.ZipInfo, bytes]]


def _read_archive(archive_path: Path) -> tuple[_Members, int, ElementTree.Element]:
    with zipfile.ZipFile(archive_path) as source:
        members = [(info, source.read(info.filename)) for info in source.infolist()]
    try:
        xml_index = next(
            index for index, (info, _) in enumerate(members) if info.filename == "file.xml"
        )
    except StopIteration as exc:
        raise ValueError("generated Niagara archive does not contain file.xml") from exc
    return members, xml_index, ElementTree.fromstring(members[xml_index][1])


def _write_archive(
    archive_path: Path,
    members: _Members,
    xml_index: int,
    root: ElementTree.Element,
) -> None:
    ElementTree.indent(root, space="  ")
    rendered = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ElementTree.tostring(
        root, encoding="utf-8", short_empty_elements=True
    )
    members[xml_index] = (members[xml_index][0], rendered)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as destination:
        for info, content in members:
            destination.writestr(info, content)
    archive_path.write_bytes(output.getvalue())


def _graph_folder(root: ElementTree.Element, graph_name: str) -> ElementTree.Element:
    folders = [
        element
        for element in root.iter("p")
        if element.attrib.get("n") == graph_name and element.attrib.get("t") == "b:Folder"
    ]
    if len(folders) != 1:
        raise ValueError(f"cannot locate unique Niagara graph folder {graph_name!r}")
    return folders[0]


def _property(parent: ElementTree.Element, name: str, type_name: str, value: str) -> None:
    ElementTree.SubElement(parent, "p", {"n": name, "t": type_name, "v": value})


_POINT_KINDS = {
    BlockKind.NUMERIC_INPUT,
    BlockKind.NUMERIC_OUTPUT,
}


def apply_point_units(
    archive_path: Path,
    graph: ControlGraph,
    units: dict[str, str | None],
) -> tuple[str, ...]:
    """Rewrite the ``facets`` of every numeric point with a declared unit.

    pybog emits ``units=u:null`` for every writable point. Every numeric input or
    output block whose id has a declared unit gets the Niagara unit facet from
    :mod:`bactalk.niagara.units`; the precision, min and max facets pybog wrote are
    kept. Returns the ids of the points whose facets were rewritten.
    """

    if not units:
        return ()
    members, xml_index, root = _read_archive(archive_path)
    program = _graph_folder(root, graph.name)
    rewritten: list[str] = []
    for block in graph.blocks:
        if block.kind not in _POINT_KINDS:
            continue
        declared = units.get(block.id)
        if not declared:
            continue
        point = next(
            (child for child in program if child.tag == "p" and child.get("n") == block.id),
            None,
        )
        if point is None:
            continue
        facets = next(
            (child for child in point if child.tag == "p" and child.get("n") == "facets"),
            None,
        )
        if facets is None:
            continue
        current = facets.get("v") or ""
        tail = "|".join(part for part in current.split("|") if not part.startswith("units="))
        facets.set("v", units_facet(declared) + (f"|{tail}" if tail else ""))
        rewritten.append(block.id)
    if rewritten:
        _write_archive(archive_path, members, xml_index, root)
    return tuple(rewritten)
