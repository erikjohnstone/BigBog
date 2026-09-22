"""Native ``.bog`` emitter for typed control graphs (GOAL-NATIVE-BOG.md N4).

One graph becomes one ``bajaObjectGraph``: a root folder named after the graph
holding an ``Inputs`` folder, a ``Parameters`` folder (the controller-level
constants, as writable points a contractor can adjust), one folder per
originating CDL composite (or ``Logic`` when the graph carries no origins),
and an ``Outputs`` folder. Every block is lowered per the matrix
(``bactalk.niagara.lowering``): stock ``kitControl``/``control`` blocks, the
assert note composite, or ``bactalkG36`` components. Layout is deterministic and
byte-identical output follows from identical input.

The emitter writes the XML directly (docs/decisions/005): pybog 0.1.6 has no
custom-type or nested-folder API, and a typed emitter is smaller than working
around it.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from xml.etree import ElementTree

from bactalk.domain import Block, BlockKind, ControlGraph, PointSpec
from bactalk.niagara.layout import BLOCK_WIDTH, GRID_Y, Placement, layout_folder
from bactalk.niagara.lowering import (
    LoweringClass,
    LoweringDecision,
    LoweringPlan,
    classify_block,
    plan_lowering,
)
from bactalk.niagara.module import CHANGE_MODES, COMPONENTS_BY_KIND, ComponentSpec
from bactalk.niagara.units import units_facet

ORIGINS_KEY = "block_origins"
INPUTS_FOLDER = "Inputs"
OUTPUTS_FOLDER = "Outputs"
PARAMETERS_FOLDER = "Parameters"
LOGIC_FOLDER = "Logic"
ROOT_MODULES = "b=baja c=control kitControl=kitControl bactalkG36=bactalkG36"

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LINK_NAME = "Link"


class EmitError(ValueError):
    pass


@dataclass(frozen=True)
class EmitOptions:
    max_blocks_per_folder: int = 60
    precision: int = 2


@dataclass
class _Prop:
    name: str
    type_spec: str | None = None
    value: str | None = None
    flags: str | None = None
    children: list[_Prop] = field(default_factory=list)


@dataclass
class _Node:
    key: str
    name: str
    type_spec: str
    folder: str
    props: list[_Prop] = field(default_factory=list)
    block_id: str | None = None
    kind: str | None = None
    handle: int = 0
    placement: Placement | None = None


@dataclass
class _Wire:
    source: str  # node key
    source_slot: str
    target: str  # node key
    target_slot: str


@dataclass(frozen=True)
class FolderReport:
    path: str
    components: tuple[tuple[str, str, int, int, int], ...]
    """(name, type, x, y, width) per component."""

    links: tuple[tuple[str, str, str, str], ...]
    """(source name, source slot, target name, target slot); names may be in other folders."""


@dataclass(frozen=True)
class EmitReport:
    graph: str
    folders: tuple[FolderReport, ...]
    component_count: int
    link_count: int
    module_types: tuple[str, ...]
    lane: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "bactalk.native-bog-emit/v1",
            "graph": self.graph,
            "lane": self.lane,
            "component_count": self.component_count,
            "link_count": self.link_count,
            "module_types": list(self.module_types),
            "folders": [
                {
                    "path": folder.path,
                    "components": [
                        {"name": n, "type": t, "x": x, "y": y, "width": w}
                        for n, t, x, y, w in folder.components
                    ],
                    "links": [
                        {"source": s, "source_slot": ss, "target": t, "target_slot": ts}
                        for s, ss, t, ts in folder.links
                    ],
                }
                for folder in self.folders
            ],
        }


@dataclass(frozen=True)
class EmitResult:
    content: bytes
    report: EmitReport
    plan: LoweringPlan


# --- public entry -------------------------------------------------------------


def emit_bog(
    graph: ControlGraph,
    *,
    points: Iterable[PointSpec] = (),
    descriptions: Mapping[str, str] | None = None,
    options: EmitOptions | None = None,
    plan: LoweringPlan | None = None,
) -> EmitResult:
    """Lower ``graph`` to a native ``.bog`` archive."""

    options = options or EmitOptions()
    plan = plan or plan_lowering(graph)
    if not plan.native:
        raise EmitError(
            f"graph {graph.name} cannot take the native lane ({plan.lane}): "
            + "; ".join(plan.blockers)
        )
    emitter = _Emitter(graph, {point.name: point for point in points}, descriptions or {}, options)
    emitter.build(plan)
    return EmitResult(content=emitter.render(), report=emitter.report(plan), plan=plan)


# --- the emitter ----------------------------------------------------------------


class _Emitter:
    def __init__(
        self,
        graph: ControlGraph,
        points: Mapping[str, PointSpec],
        descriptions: Mapping[str, str],
        options: EmitOptions,
    ) -> None:
        self.graph = graph
        self.points = points
        self.descriptions = descriptions
        self.options = options
        self.nodes: dict[str, _Node] = {}
        self.wires: list[_Wire] = []
        self.folders: list[str] = []
        self.inputs: dict[str, dict[str, tuple[str, str]]] = {}
        self.outputs: dict[str, dict[str, tuple[str, str]]] = {}
        self.aliases: dict[tuple[str, str], tuple[str, str]] = {}
        self._names: dict[str, set[str]] = {}
        self._folder_of_block: dict[str, str] = {}

    # -- folders --------------------------------------------------------------

    def _assign_folders(self) -> None:
        origins = self.graph.metadata.get(ORIGINS_KEY)
        origins = origins if isinstance(origins, Mapping) else {}
        logical: dict[str, list[Block]] = {}
        logic_order: list[str] = []
        for block in self.graph.blocks:
            kind = block.kind
            if kind in {BlockKind.NUMERIC_INPUT, BlockKind.BOOLEAN_INPUT}:
                self._folder_of_block[block.id] = INPUTS_FOLDER
                continue
            if kind in {BlockKind.NUMERIC_OUTPUT, BlockKind.BOOLEAN_OUTPUT}:
                self._folder_of_block[block.id] = OUTPUTS_FOLDER
                continue
            origin = str(origins.get(block.id, "")) if origins else ""
            segments = [s for s in origin.split(".") if s]
            if kind in {BlockKind.NUMERIC_CONST, BlockKind.BOOLEAN_CONST} and (
                origins and len(segments) <= 1
            ):
                self._folder_of_block[block.id] = PARAMETERS_FOLDER
                continue
            if not origins:
                folder = LOGIC_FOLDER
            elif len(segments) <= 1:
                folder = _folder_name(self.graph.name)
            else:
                folder = _folder_name(segments[0])
            if folder not in logical:
                logical[folder] = []
                logic_order.append(folder)
            logical[folder].append(block)
        self.folders = [INPUTS_FOLDER, PARAMETERS_FOLDER]
        limit = self.options.max_blocks_per_folder
        for folder in logic_order:
            members = logical[folder]
            if sum(_component_weight(block) for block in members) <= limit:
                self.folders.append(folder)
                for block in members:
                    self._folder_of_block[block.id] = folder
                continue
            for chunk_index, chunk in enumerate(_chunks(members, limit), start=1):
                name = f"{folder}_{chunk_index}"
                self.folders.append(name)
                for block in chunk:
                    self._folder_of_block[block.id] = name
        self.folders.append(OUTPUTS_FOLDER)
        if not any(folder == PARAMETERS_FOLDER for folder in self._folder_of_block.values()):
            self.folders.remove(PARAMETERS_FOLDER)

    # -- nodes ----------------------------------------------------------------

    def _unique_name(self, folder: str, wanted: str) -> str:
        base = _identifier(wanted)
        used = self._names.setdefault(folder, set())
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        used.add(candidate)
        return candidate

    def _add_node(
        self,
        folder: str,
        wanted: str,
        type_spec: str,
        props: list[_Prop],
        *,
        block: Block | None = None,
    ) -> str:
        name = self._unique_name(folder, wanted)
        key = f"{folder}/{name}"
        self.nodes[key] = _Node(
            key=key,
            name=name,
            type_spec=type_spec,
            folder=folder,
            props=props,
            block_id=block.id if block else None,
            kind=block.kind.value if block else None,
        )
        return key

    def _wire(self, source: str, source_slot: str, target: str, target_slot: str) -> None:
        self.wires.append(_Wire(source, source_slot, target, target_slot))

    def build(self, plan: LoweringPlan) -> None:
        self._assign_folders()
        for block in self.graph.blocks:
            decision = plan.decisions[block.id]
            folder = self._folder_of_block[block.id]
            self._lower(block, decision, folder)
        for link in self.graph.links:
            source = self._resolve_output(link.source, link.source_slot)
            if source is None:
                raise EmitError(f"link source {link.source}.{link.source_slot} has no Niagara slot")
            targets = self.inputs.get(link.target, {}).get(link.target_slot)
            if targets is None:
                if (link.target, link.target_slot) in self.aliases:
                    continue  # pass-through consumer: its readers resolve through the alias
                raise EmitError(f"link target {link.target}.{link.target_slot} has no Niagara slot")
            self._wire(source[0], source[1], targets[0], targets[1])

    def _resolve_output(self, block_id: str, slot: str) -> tuple[str, str] | None:
        alias = self.aliases.get((block_id, slot))
        if alias is not None:
            for link in self.graph.links:
                if link.target == alias[0] and link.target_slot == alias[1]:
                    return self._resolve_output(link.source, link.source_slot)
            return None
        return self.outputs.get(block_id, {}).get(slot)

    # -- lowering per matrix row ----------------------------------------------

    def _lower(self, block: Block, decision: LoweringDecision, folder: str) -> None:
        kind = block.kind
        label = block.label or block.id
        if kind in {BlockKind.NUMERIC_INPUT, BlockKind.NUMERIC_OUTPUT}:
            self._writable(block, folder, numeric=True)
            return
        if kind in {BlockKind.BOOLEAN_INPUT, BlockKind.BOOLEAN_OUTPUT}:
            self._writable(block, folder, numeric=False)
            return
        if folder == PARAMETERS_FOLDER:
            self._parameter(block, folder)
            return
        if decision.lowering is LoweringClass.MODULE:
            self._module(block, decision, folder)
            return
        if decision.composite:
            self._composite(block, folder)
            return
        # Single stock block.
        props: list[_Prop] = []
        if kind == BlockKind.NUMERIC_CONST:
            props.append(_status(("out"), "b:StatusNumeric", _num(block.config["value"])))
        elif kind == BlockKind.BOOLEAN_CONST:
            props.append(_status("out", "b:StatusBoolean", _bool(block.config["value"])))
        elif kind == BlockKind.BOOLEAN_DELAY:
            props.append(
                _Prop(
                    "onDelay",
                    "b:RelTime",
                    _millis(block.config.get("on_delay_seconds", 0.0)),
                    "L",
                )
            )
            props.append(
                _Prop(
                    "offDelay",
                    "b:RelTime",
                    _millis(block.config.get("off_delay_seconds", 0.0)),
                    "L",
                )
            )
        elif kind == BlockKind.PI_LOOP:
            props.extend(
                [
                    _Prop(
                        "proportionalConstant",
                        "b:Double",
                        _num(block.config.get("proportional_constant", 1.0)),
                        "L",
                    ),
                    _Prop(
                        "integralConstant",
                        "b:Double",
                        _num(block.config.get("integral_constant", 0.0)),
                        "L",
                    ),
                    _Prop("derivativeConstant", "b:Double", "0.0", "L"),
                ]
            )
        key = self._add_node(folder, label, decision.target, props, block=block)
        self.inputs[block.id] = {
            ir_slot: (key, niagara_slot)
            for ir_slot, niagara_slot in decision.slot_map.items()
            if ir_slot != "out"
        }
        self.outputs[block.id] = {"out": (key, decision.slot_map.get("out", "out"))}

    def _writable(self, block: Block, folder: str, *, numeric: bool) -> None:
        point = self.points.get(block.id)
        default = block.config.get("default", 0.0 if numeric else False)
        if point is not None and point.default is not None:
            default = point.default
        type_spec = "c:NumericWritable" if numeric else "c:BooleanWritable"
        props: list[_Prop] = []
        if numeric:
            units = point.units if point is not None else None
            facets = (
                f"{units_facet(units)}|precision=i:{self.options.precision}|min=d:-inf|max=d:+inf"
            )
            props.append(_status("fallback", "b:StatusNumeric", _num(default)))
            props.append(_Prop("facets", "b:Facets", facets))
        else:
            props.append(_status("fallback", "b:StatusBoolean", _bool(default)))
        props.append(_Prop("in16", None, None, "tsL"))
        label = point.label if point is not None and _NAME.match(point.label or "") else block.id
        key = self._add_node(folder, block.id if block.id else label, type_spec, props, block=block)
        self.inputs[block.id] = {"in": (key, "in16")}
        self.outputs[block.id] = {"out": (key, "out")}

    def _parameter(self, block: Block, folder: str) -> None:
        numeric = block.kind is BlockKind.NUMERIC_CONST
        value = block.config["value"]
        type_spec = "c:NumericWritable" if numeric else "c:BooleanWritable"
        if numeric:
            props = [
                _status("fallback", "b:StatusNumeric", _num(value)),
                _Prop(
                    "facets",
                    "b:Facets",
                    f"{units_facet(None)}|precision=i:{self.options.precision}"
                    "|min=d:-inf|max=d:+inf",
                ),
            ]
        else:
            props = [_status("fallback", "b:StatusBoolean", _bool(value))]
        key = self._add_node(folder, block.label or block.id, type_spec, props, block=block)
        self.inputs[block.id] = {}
        self.outputs[block.id] = {"out": (key, "out")}

    def _module(self, block: Block, decision: LoweringDecision, folder: str) -> None:
        component: ComponentSpec = COMPONENTS_BY_KIND[block.kind]
        props: list[_Prop] = []
        for binding in component.bindings:
            if binding.encoding == "const":
                value = CHANGE_MODES.get(block.kind, binding.default)
                props.append(_Prop(binding.property, "b:String", str(value)))
                continue
            raw = block.config.get(binding.config_key or "", binding.default)
            if raw is None:
                raise EmitError(
                    f"block {block.id} ({block.kind.value}) lacks config.{binding.config_key} "
                    f"needed by {component.type_key}.{binding.property}"
                )
            if binding.encoding == "seconds":
                props.append(_Prop(binding.property, "b:RelTime", _millis(raw)))
            elif binding.encoding == "double":
                props.append(_Prop(binding.property, "b:Double", _num(raw)))
            elif binding.encoding == "boolean":
                props.append(_Prop(binding.property, "b:Boolean", _bool(raw)))
            else:
                props.append(_Prop(binding.property, "b:String", str(raw)))
        if block.kind is BlockKind.TRIM_AND_RESPOND_HOLD:
            props = [p for p in props if p.name != "holdEnabled"]
            props.append(_Prop("holdEnabled", "b:Boolean", "true"))
        key = self._add_node(
            folder, block.label or block.id, f"bactalkG36:{component.name}", props, block=block
        )
        self.inputs[block.id] = {
            ir_slot: (key, slot) for ir_slot, slot in component.input_map.items()
        }
        self.outputs[block.id] = {
            ir_slot: (key, slot) for ir_slot, slot in component.output_map.items()
        }

    def _composite(self, block: Block, folder: str) -> None:
        kind = block.kind
        base = block.label or block.id
        if kind is BlockKind.BOOLEAN_ASSERT_WARNING:
            message = str(block.config.get("message", ""))
            self._add_node(
                folder,
                f"{base}_note",
                "b:WsTextBlock",
                [_Prop("text", None, f"assert {base}: {message}")],
                block=block,
            )
            self.inputs[block.id] = {}
            self.outputs[block.id] = {}
            self.aliases[(block.id, "ok")] = (block.id, "condition")
            self.aliases[(block.id, "condition")] = (block.id, "condition")
        else:  # pragma: no cover - the matrix lists every composite above
            raise EmitError(f"no composite lowering for {kind.value}")

    # -- layout, handles, rendering ---------------------------------------------

    def _layout(self) -> None:
        by_folder: dict[str, list[str]] = {folder: [] for folder in self.folders}
        for node in self.nodes.values():
            by_folder[node.folder].append(node.key)
        internal: dict[str, list[tuple[str, str]]] = {folder: [] for folder in self.folders}
        for wire in self.wires:
            source = self.nodes[wire.source]
            target = self.nodes[wire.target]
            if source.folder == target.folder:
                internal[source.folder].append((source.key, target.key))
        handle = 1
        self.root_handle = handle
        self.folder_handles: dict[str, int] = {}
        for folder in self.folders:
            handle += 1
            self.folder_handles[folder] = handle
            placements = layout_folder(by_folder[folder], internal[folder])
            ordered = sorted(placements.values(), key=lambda p: (p.layer, p.row))
            for placement in ordered:
                handle += 1
                node = self.nodes[placement.name]
                node.placement = placement
                node.handle = handle

    def render(self) -> bytes:
        self._layout()
        root = ElementTree.Element(
            "bajaObjectGraph",
            {"version": "4.0", "reversibleEncodingKeySource": "none", "FIPSEnabled": "false"},
        )
        top = ElementTree.SubElement(root, "p", {"m": ROOT_MODULES, "t": "b:UnrestrictedFolder"})
        graph_folder = ElementTree.SubElement(
            top,
            "p",
            {"n": _identifier(self.graph.name), "h": _hex(self.root_handle), "t": "b:Folder"},
        )
        link_counters: dict[str, int] = {}
        wires_by_target: dict[str, list[_Wire]] = {}
        for wire in self.wires:
            wires_by_target.setdefault(wire.target, []).append(wire)
        for folder in self.folders:
            element = ElementTree.SubElement(
                graph_folder,
                "p",
                {"n": folder, "h": _hex(self.folder_handles[folder]), "t": "b:Folder"},
            )
            description = self.descriptions.get(folder)
            if description:
                ElementTree.SubElement(
                    element,
                    "p",
                    {"n": "Notes", "t": "b:WsTextBlock", "v": description},
                )
            nodes = sorted(
                (n for n in self.nodes.values() if n.folder == folder),
                key=lambda n: n.handle,
            )
            for node in nodes:
                component = ElementTree.SubElement(
                    element,
                    "p",
                    {"n": node.name, "h": _hex(node.handle), "t": node.type_spec},
                )
                for prop in node.props:
                    _render_prop(component, prop)
                placement = node.placement
                assert placement is not None
                ElementTree.SubElement(
                    component,
                    "p",
                    {
                        "n": "wsAnnotation",
                        "t": "b:WsAnnotation",
                        "v": f"{placement.x},{placement.y},{placement.width}",
                    },
                )
                for wire in wires_by_target.get(node.key, []):
                    count = link_counters.get(node.key, 0)
                    link_counters[node.key] = count + 1
                    link = ElementTree.SubElement(
                        component,
                        "p",
                        {"n": _LINK_NAME if count == 0 else f"{_LINK_NAME}{count}", "t": "b:Link"},
                    )
                    source = self.nodes[wire.source]
                    ElementTree.SubElement(
                        link, "p", {"n": "sourceOrd", "v": f"h:{_hex(source.handle)}"}
                    )
                    ElementTree.SubElement(link, "p", {"n": "relationTags", "v": ""})
                    ElementTree.SubElement(link, "p", {"n": "relationId", "v": "n:dataLink"})
                    ElementTree.SubElement(
                        link, "p", {"n": "sourceSlotName", "v": wire.source_slot}
                    )
                    ElementTree.SubElement(
                        link, "p", {"n": "targetSlotName", "v": wire.target_slot}
                    )
        ElementTree.indent(root, space=" ")
        xml = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ElementTree.tostring(
            root, encoding="utf-8", short_empty_elements=True
        )
        return _archive(xml)

    def report(self, plan: LoweringPlan) -> EmitReport:
        folders = []
        for folder in self.folders:
            nodes = sorted(
                (n for n in self.nodes.values() if n.folder == folder), key=lambda n: n.handle
            )
            components = tuple(
                (n.name, n.type_spec, n.placement.x, n.placement.y, n.placement.width)
                for n in nodes
                if n.placement is not None
            )
            links = tuple(
                (
                    self.nodes[w.source].name,
                    w.source_slot,
                    self.nodes[w.target].name,
                    w.target_slot,
                )
                for w in self.wires
                if self.nodes[w.target].folder == folder
            )
            folders.append(FolderReport(path=folder, components=components, links=links))
        return EmitReport(
            graph=self.graph.name,
            folders=tuple(folders),
            component_count=len(self.nodes),
            link_count=len(self.wires),
            module_types=plan.module_types,
            lane=plan.lane,
        )


# --- helpers -------------------------------------------------------------------


def _identifier(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", value).strip("_") or "block"
    if not (cleaned[0].isalpha() or cleaned[0] == "_"):
        cleaned = f"n_{cleaned}"
    return cleaned


def _folder_name(value: str) -> str:
    name = _identifier(value)
    return name[:1].upper() + name[1:]


_COMPOSITE_WEIGHT: dict[BlockKind, int] = {}
"""Composites that expand to more than one component (none since N7; the edge, latch
and sampler kinds are ``bactalkG36`` components with host-tick semantics)."""


def _component_weight(block: Block) -> int:
    """How many Niagara components the block becomes (composites expand)."""

    return _COMPOSITE_WEIGHT.get(block.kind, 1)


def _chunks(items: list[Block], size: int) -> Iterable[list[Block]]:
    """Split by emitted component count so no folder exceeds ``size`` components."""

    chunk: list[Block] = []
    weight = 0
    for block in items:
        step = _component_weight(block)
        if chunk and weight + step > size:
            yield chunk
            chunk, weight = [], 0
        chunk.append(block)
        weight += step
    if chunk:
        yield chunk


def _num(value: object) -> str:
    number = float(value)  # type: ignore[arg-type]
    if number.is_integer() and abs(number) < 1e15:
        return f"{number:.1f}"
    return repr(number)


def _bool(value: object) -> str:
    return "true" if bool(value) else "false"


def _millis(seconds: object) -> str:
    return str(round(float(seconds) * 1000))  # type: ignore[arg-type]


def _hex(handle: int) -> str:
    return format(handle, "x")


def _status(name: str, type_spec: str, value: str) -> _Prop:
    return _Prop(name, type_spec, None, None, [_Prop("value", None, value)])


def _render_prop(parent: ElementTree.Element, prop: _Prop) -> None:
    attributes = {"n": prop.name}
    if prop.flags:
        attributes["f"] = prop.flags
    if prop.type_spec:
        attributes["t"] = prop.type_spec
    if prop.value is not None:
        attributes["v"] = prop.value
    element = ElementTree.SubElement(parent, "p", attributes)
    for child in prop.children:
        _render_prop(element, child)


def _archive(xml: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo("file.xml", date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, xml)
    return buffer.getvalue()


__all__ = [
    "BLOCK_WIDTH",
    "GRID_Y",
    "EmitError",
    "EmitOptions",
    "EmitReport",
    "EmitResult",
    "FolderReport",
    "ORIGINS_KEY",
    "classify_block",
    "emit_bog",
]
