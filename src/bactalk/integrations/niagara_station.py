from __future__ import annotations

import hashlib
import io
import re
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from xml.etree import ElementTree

from bactalk.domain import ControlGraph, JobSpec
from bactalk.integrations.niagara_bindings import program_root_ord

_HANDLE = re.compile(r"^[0-9a-fA-F]+$")
_HANDLE_REF = re.compile(r"(?<![A-Za-z0-9])h:([0-9a-fA-F]+)(?![A-Za-z0-9_$])")
_FORBIDDEN_XML = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)


@dataclass(frozen=True)
class NiagaraStationAssembly:
    content: bytes
    manifest: dict[str, Any]


@dataclass(frozen=True)
class NiagaraProjectStationAssembly:
    content: bytes
    manifest: dict[str, Any]


@dataclass(frozen=True)
class NiagaraProgramLink:
    source_equipment: str
    source_point: str
    target_equipment: str
    target_point: str
    data_type: str


@dataclass(frozen=True)
class NiagaraProgramAggregation:
    """Several programs' outputs reduced into one program input through a chain of
    kitControl Add (numeric ``sum``), Maximum (``max``) or Or (boolean ``any``) blocks placed
    in a ``Requests`` folder of the target program."""

    target_equipment: str
    target_point: str
    sources: tuple[tuple[str, str], ...]
    reduce: str
    data_type: str


@dataclass(frozen=True)
class PointBinding:
    """A confirmed link between a station proxy point and a program boundary point.

    ``direction`` is ``proxy_to_program`` (the proxy's ``out`` drives the program
    input's ``in16``) or ``program_to_proxy`` (the program output's ``out`` drives
    the proxy's ``in<write_priority>``; priority 1 and an implicit priority are
    refused, GOAL-NATIVE-BOG.md N5).
    """

    point: str
    proxy_ord: str
    direction: Literal["proxy_to_program", "program_to_proxy"]
    write_priority: int | None = None
    data_type: str | None = None


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _read_bog(content: bytes, label: str) -> tuple[ElementTree.Element, bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if archive.namelist() != ["file.xml"]:
                raise ValueError(f"{label} must contain exactly one file.xml entry")
            xml = archive.read("file.xml")
    except zipfile.BadZipFile as exc:
        raise ValueError(f"{label} is not a valid BOG archive") from exc
    if _FORBIDDEN_XML.search(xml):
        raise ValueError(f"{label} contains a DTD or entity declaration")
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise ValueError(f"{label} file.xml is not well-formed XML") from exc
    if root.tag != "bajaObjectGraph":
        raise ValueError(f"{label} root must be bajaObjectGraph")
    return root, xml


def _root_component(root: ElementTree.Element, label: str) -> ElementTree.Element:
    components = [child for child in root if child.tag == "p" and child.get("n") is None]
    if len(components) != 1:
        raise ValueError(f"{label} must contain exactly one unnamed root component")
    return components[0]


def _named_child(parent: ElementTree.Element, name: str) -> ElementTree.Element | None:
    matches = [child for child in parent if child.tag == "p" and child.get("n") == name]
    if len(matches) > 1:
        raise ValueError(f"station template has duplicate child component {name!r}")
    return matches[0] if matches else None


def _target_parent(
    station_root: ElementTree.Element,
    station_folder: str | None,
) -> ElementTree.Element:
    current = station_root
    for segment in station_folder.split("/") if station_folder else []:
        child = _named_child(current, segment)
        if child is None:
            raise ValueError(
                "station template does not contain exact target parent path: "
                + (station_folder or "/")
            )
        current = child
    return current


def _module_declarations(value: str | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for token in (value or "").split():
        if "=" not in token:
            raise ValueError(f"invalid Niagara module declaration {token!r}")
        symbol, module = token.split("=", 1)
        if not symbol or not module or (symbol in result and result[symbol] != module):
            raise ValueError(f"conflicting Niagara module declaration {token!r}")
        result[symbol] = module
    return result


def _carry_root_modules(
    program: ElementTree.Element,
    generated_root: ElementTree.Element,
) -> dict[str, str]:
    inherited = _module_declarations(generated_root.get("m"))
    local = _module_declarations(program.get("m"))
    conflicts = {
        symbol: (local[symbol], module)
        for symbol, module in inherited.items()
        if symbol in local and local[symbol] != module
    }
    if conflicts:
        raise ValueError(f"generated program contains module-symbol conflicts: {conflicts}")
    merged = {**inherited, **local}
    if merged:
        declarations = " ".join(f"{symbol}={module}" for symbol, module in sorted(merged.items()))
        program.set("m", declarations)
    return merged


def _collect_handles(element: ElementTree.Element) -> list[str]:
    handles = [item.get("h") for item in element.iter() if item.get("h") is not None]
    invalid = [value for value in handles if value is None or not _HANDLE.fullmatch(value)]
    if invalid:
        raise ValueError(f"invalid Niagara handle values: {invalid[:5]}")
    if len(handles) != len(set(handles)):
        raise ValueError("Niagara object graph contains duplicate handles")
    return [value.lower() for value in handles if value is not None]


def _collect_handle_refs(
    element: ElementTree.Element,
    *,
    exclude: ElementTree.Element | None = None,
) -> set[str]:
    excluded = set(exclude.iter()) if exclude is not None else set()
    return {
        match.group(1).lower()
        for item in element.iter()
        if item not in excluded
        for name, value in item.attrib.items()
        if name != "h"
        for match in _HANDLE_REF.finditer(value)
    }


def _rebase_program_handles(
    station_root: ElementTree.Element,
    program: ElementTree.Element,
) -> dict[str, str]:
    station_handles = _collect_handles(station_root)
    program_handles = _collect_handles(program)
    next_handle = max((int(value, 16) for value in station_handles), default=0) + 1
    mapping: dict[str, str] = {}
    for old in sorted(program_handles, key=lambda value: int(value, 16)):
        mapping[old] = format(next_handle, "x")
        next_handle += 1

    for element in program.iter():
        handle = element.get("h")
        if handle is not None:
            element.set("h", mapping[handle.lower()])
        for name, value in list(element.attrib.items()):
            if name == "h":
                continue

            def replace(match: re.Match[str]) -> str:
                old = match.group(1).lower()
                if old not in mapping:
                    raise ValueError(
                        f"generated program references handle h:{old} outside its fragment"
                    )
                return f"h:{mapping[old]}"

            element.set(name, _HANDLE_REF.sub(replace, value))

    combined = _collect_handles(station_root) + _collect_handles(program)
    if len(combined) != len(set(combined)):
        raise ValueError("handle rebasing did not produce a collision-free object graph")
    return mapping


def _deterministic_bog(xml: bytes) -> bytes:
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo("file.xml", date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, xml)
    return target.getvalue()


def assemble_station_bog(
    template_bog: bytes,
    program_bog: bytes,
    job: JobSpec,
    graph: ControlGraph,
    *,
    mode: Literal["insert", "replace"],
    bindings: Sequence[PointBinding] = (),
) -> NiagaraStationAssembly:
    """Insert or replace one generated program in an offline contractor station graph.

    ``bindings`` adds proper Niagara links between the station's proxy points and
    the program's boundary points (N5); every ORD must resolve inside the station,
    no target slot may already be driven, and command links need an explicit
    write priority between 2 and 16.
    """

    station_graph, _ = _read_bog(template_bog, "station template")
    generated_graph, _ = _read_bog(program_bog, "generated program")
    station_root = _root_component(station_graph, "station template")
    generated_root = _root_component(generated_graph, "generated program")
    generated_children = [child for child in generated_root if child.tag == "p"]
    if len(generated_children) != 1:
        raise ValueError("generated BOG must contain exactly one top-level program component")
    program = generated_children[0]
    if program.get("n") != graph.name:
        raise ValueError("generated BOG program name does not match the typed graph")

    profile = job.deliverables.shop_profile
    station_folder = profile.station_folder if profile is not None else None
    parent = _target_parent(station_root, station_folder)
    existing = _named_child(parent, graph.name)
    if mode == "insert" and existing is not None:
        raise ValueError(f"station target already contains component {graph.name!r}")
    if mode == "replace" and existing is None:
        raise ValueError(f"station target has no component {graph.name!r} to replace")
    if existing is not None:
        replaced_handles = set(_collect_handles(existing))
        external_refs = _collect_handle_refs(station_root, exclude=existing) & replaced_handles
        if external_refs:
            refs = ", ".join(f"h:{value}" for value in sorted(external_refs))
            raise ValueError(
                "station components outside the replacement target reference its handles: " + refs
            )

    module_declarations = _carry_root_modules(program, generated_root)
    handle_mapping = _rebase_program_handles(station_root, program)
    action: str
    replaced_sha256: str | None = None
    if existing is not None:
        index = list(parent).index(existing)
        replaced_sha256 = _sha256(ElementTree.tostring(existing, encoding="utf-8"))
        parent.remove(existing)
        parent.insert(index, program)
        action = "replaced"
    else:
        parent.append(program)
        action = "inserted"

    point_links = _bind_points(station_root, program, bindings)

    ElementTree.indent(station_graph, space="  ")
    xml = ElementTree.tostring(station_graph, encoding="utf-8", xml_declaration=True)
    reparsed = ElementTree.fromstring(xml)
    all_handles = _collect_handles(reparsed)
    unresolved_handles = _collect_handle_refs(reparsed) - set(all_handles)
    if unresolved_handles:
        refs = ", ".join(f"h:{value}" for value in sorted(unresolved_handles))
        raise ValueError(f"assembled station contains unresolved handle references: {refs}")
    content = _deterministic_bog(xml)
    target_ord = program_root_ord(job, graph)
    manifest = {
        "schema": "bactalk.niagara-station-assembly/v1",
        "mode": mode,
        "action": action,
        "point_link_count": len(point_links),
        "point_links": point_links,
        "target_parent_ord": target_ord.rsplit("/", 1)[0],
        "target_program_ord": target_ord,
        "template_sha256": _sha256(template_bog),
        "program_fragment_sha256": _sha256(program_bog),
        "assembled_bog_sha256": _sha256(content),
        "replaced_component_sha256": replaced_sha256,
        "handle_rebase_count": len(handle_mapping),
        "handle_mapping": dict(sorted(handle_mapping.items(), key=lambda item: int(item[0], 16))),
        "assembled_handle_count": len(all_handles),
        "module_declarations_carried": module_declarations,
        "safety": {
            "live_station_modified": False,
            "unrelated_station_components_preserved": True,
            "implicit_target_path_created": False,
            "insert_collision_overwrite_allowed": False,
            "replace_requires_existing_exact_target": True,
            "replace_with_external_handle_references_allowed": False,
            "handles_rebased_and_references_rewritten": True,
            "licensed_runtime_qualified": False,
        },
        "runtime_gate": (
            "The assembled BOG is structurally validated offline. Import, module resolution, "
            "station compile/restart, installer execution, PX installation, and retained "
            "readback must pass in the exact licensed Niagara target before deployment."
        ),
    }
    return NiagaraStationAssembly(content=content, manifest=manifest)


def _resolve_slot_ord(station_root: ElementTree.Element, ord_value: str) -> ElementTree.Element:
    prefix = "station:|slot:/"
    if not ord_value.startswith(prefix):
        raise ValueError(f"binding ORD must start with {prefix}: {ord_value}")
    current = station_root
    for segment in ord_value[len(prefix) :].split("/"):
        if not segment:
            continue
        child = _named_child(current, segment)
        if child is None:
            raise ValueError(f"binding ORD does not resolve in the station: {ord_value}")
        current = child
    return current


def _optional_program_point(program: ElementTree.Element, name: str) -> ElementTree.Element | None:
    try:
        return _find_program_point(program, name)
    except ValueError:
        return None


def _find_program_point(program: ElementTree.Element, name: str) -> ElementTree.Element:
    matches = [
        element
        for element in program.iter("p")
        if element.get("n") == name
        and (element.get("t") or "").endswith(("Writable", "Point"))
        and element.get("h") is not None
    ]
    if len(matches) != 1:
        raise ValueError(
            f"program has {len(matches)} boundary points named {name!r}; expected exactly one"
        )
    return matches[0]


def _driven_slots(component: ElementTree.Element) -> set[str]:
    driven: set[str] = set()
    for child in component:
        if child.tag != "p" or not (child.get("t") or "").endswith(":Link"):
            continue
        for prop in child:
            if prop.get("n") == "targetSlotName" and prop.get("v"):
                driven.add(str(prop.get("v")))
    return driven


def _append_link(
    target: ElementTree.Element,
    source: ElementTree.Element,
    source_slot: str,
    target_slot: str,
    prefix: str,
) -> str:
    source_handle = source.get("h")
    if source_handle is None or not _HANDLE.fullmatch(source_handle):
        raise ValueError("link source has no valid Niagara handle")
    name = prefix
    suffix = 1
    while _named_child(target, name) is not None:
        name = f"{prefix}{suffix}"
        suffix += 1
    link = ElementTree.SubElement(target, "p", {"n": name, "t": "b:Link"})
    for field_name, value in (
        ("sourceOrd", f"h:{source_handle.lower()}"),
        ("relationTags", ""),
        ("relationId", "n:dataLink"),
        ("sourceSlotName", source_slot),
        ("targetSlotName", target_slot),
    ):
        ElementTree.SubElement(link, "p", {"n": field_name, "v": value})
    return name


def _bind_points(
    station_root: ElementTree.Element,
    program: ElementTree.Element,
    bindings: Sequence[PointBinding],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for binding in sorted(bindings, key=lambda item: (item.point, item.proxy_ord)):
        proxy = _resolve_slot_ord(station_root, binding.proxy_ord)
        if proxy.get("h") is None:
            raise ValueError(f"station point has no handle: {binding.proxy_ord}")
        point = _find_program_point(program, binding.point)
        if binding.direction == "proxy_to_program":
            target, source, source_slot, target_slot = point, proxy, "out", "in16"
        else:
            priority = binding.write_priority
            if priority is None or priority < 2 or priority > 16:
                raise ValueError(
                    f"command binding {binding.point}: write priority must be explicit and "
                    f"between 2 and 16, not {priority!r}"
                )
            target, source, source_slot, target_slot = proxy, point, "out", f"in{priority}"
        if target_slot in _driven_slots(target):
            raise ValueError(
                f"binding {binding.point}: target slot {target_slot} of "
                f"{target.get('n')} is already driven"
            )
        link_name = _append_link(target, source, source_slot, target_slot, "BactalkPointLink")
        rows.append(
            {
                "point": binding.point,
                "direction": binding.direction,
                "proxy_ord": binding.proxy_ord,
                "source_slot": source_slot,
                "target_slot": target_slot,
                "write_priority": binding.write_priority,
                "data_type": binding.data_type,
                "link_component": link_name,
            }
        )
    return rows


def point_bindings(job: JobSpec, graph: ControlGraph) -> tuple[PointBinding, ...]:
    """The confirmed bindings a job carries: every point with a ``niagara_ord``."""

    blocks = {block.id: block for block in graph.blocks}
    result: list[PointBinding] = []
    for point in job.points:
        if point.niagara_ord is None:
            continue
        block = blocks.get(point.name)
        if block is None:
            raise ValueError(f"point {point.name} declares niagara_ord but has no graph block")
        if block.kind.value.endswith("_input"):
            direction: Literal["proxy_to_program", "program_to_proxy"] = "proxy_to_program"
        elif block.kind.value.endswith("_output"):
            direction = "program_to_proxy"
        else:
            raise ValueError(
                f"point {point.name} maps to internal block kind {block.kind.value}; "
                "bindings need an input or output boundary block"
            )
        result.append(
            PointBinding(
                point=point.name,
                proxy_ord=point.niagara_ord,
                direction=direction,
                write_priority=point.niagara_write_priority,
                data_type=point.data_type.value,
            )
        )
    return tuple(result)


def assemble_project_station_bog(
    template_bog: bytes,
    programs: list[tuple[bytes, JobSpec, ControlGraph]],
    *,
    mode: Literal["insert", "replace"],
    program_links: list[NiagaraProgramLink] | None = None,
    bindings_by_equipment: Mapping[str, Sequence[PointBinding]] | None = None,
    program_aggregations: list[NiagaraProgramAggregation] | None = None,
) -> NiagaraProjectStationAssembly:
    """Atomically assemble multiple independently compiled programs into one station BOG."""

    if not programs:
        raise ValueError("project station assembly requires at least one program")
    ordered = sorted(programs, key=lambda item: program_root_ord(item[1], item[2]))
    targets = [program_root_ord(job, graph) for _, job, graph in ordered]
    if len(targets) != len(set(targets)):
        raise ValueError("project station programs must have unique target ORDs")

    current = template_bog
    steps: list[dict[str, Any]] = []
    for program_bog, job, graph in ordered:
        assembly = assemble_station_bog(
            current,
            program_bog,
            job,
            graph,
            mode=mode,
            bindings=(bindings_by_equipment or {}).get(job.equipment_name, ()),
        )
        current = assembly.content
        steps.append(
            {
                "equipment_name": job.equipment_name,
                "graph_name": graph.name,
                "target_program_ord": assembly.manifest["target_program_ord"],
                "action": assembly.manifest["action"],
                "handle_rebase_count": assembly.manifest["handle_rebase_count"],
                "program_fragment_sha256": assembly.manifest["program_fragment_sha256"],
                "result_sha256": assembly.manifest["assembled_bog_sha256"],
                "point_link_count": assembly.manifest["point_link_count"],
            }
        )

    link_rows: list[dict[str, Any]] = []
    if program_links:
        current, link_rows = _add_project_program_links(current, ordered, program_links)
    aggregation_rows: list[dict[str, Any]] = []
    if program_aggregations:
        current, aggregation_rows = _add_project_program_aggregations(
            current, ordered, program_aggregations
        )

    root, _ = _read_bog(current, "assembled project station")
    handles = _collect_handles(root)
    unresolved = _collect_handle_refs(root) - set(handles)
    if unresolved:
        raise ValueError("assembled project station contains unresolved handle references")
    manifest = {
        "schema": "bactalk.niagara-project-station-assembly/v1",
        "mode": mode,
        "program_count": len(steps),
        "target_program_ords": targets,
        "cross_program_link_count": len(link_rows),
        "cross_program_links": link_rows,
        "cross_program_aggregation_count": len(aggregation_rows),
        "cross_program_aggregations": aggregation_rows,
        "steps": steps,
        "template_sha256": _sha256(template_bog),
        "assembled_bog_sha256": _sha256(current),
        "assembled_handle_count": len(handles),
        "total_handles_rebased": sum(item["handle_rebase_count"] for item in steps),
        "safety": {
            "atomic_artifact_generation": True,
            "partial_output_on_failure": False,
            "live_station_modified": False,
            "duplicate_target_ords_allowed": False,
            "cross_program_target_collision_overwrite_allowed": False,
            "cross_program_links_are_typed_by_project_contract": True,
            "unrelated_station_components_preserved": True,
            "licensed_runtime_qualified": False,
        },
        "runtime_gate": (
            "The multi-program BOG is structurally validated offline. Whole-station import, "
            "module resolution, compile/restart, installer execution, cross-equipment value "
            "flow, PX navigation, and retained readback require exact licensed-runtime evidence."
        ),
    }
    return NiagaraProjectStationAssembly(content=current, manifest=manifest)


_REDUCERS = {"sum": "kitControl:Add", "max": "kitControl:Maximum", "any": "kitControl:Or"}
_REDUCER_INPUTS = ("inA", "inB", "inC", "inD")


def _index_programs(
    document: ElementTree.Element,
    programs: list[tuple[bytes, JobSpec, ControlGraph]],
) -> dict[str, tuple[JobSpec, ControlGraph, ElementTree.Element]]:
    station_root = _root_component(document, "assembled project station")
    indexed: dict[str, tuple[JobSpec, ControlGraph, ElementTree.Element]] = {}
    for _, job, graph in programs:
        profile = job.deliverables.shop_profile
        parent = _target_parent(
            station_root, profile.station_folder if profile is not None else None
        )
        program = _named_child(parent, graph.name)
        if program is None:
            raise ValueError(f"assembled station is missing program {graph.name!r}")
        indexed[job.equipment_name] = (job, graph, program)
    return indexed


def _add_project_program_aggregations(
    assembled_bog: bytes,
    programs: list[tuple[bytes, JobSpec, ControlGraph]],
    aggregations: list[NiagaraProgramAggregation],
) -> tuple[bytes, list[dict[str, Any]]]:
    """Reduce several programs' outputs into one input with a chain of kitControl blocks.

    Each reducer takes up to four inputs; the chain feeds the previous stage's ``out``
    into the next stage's ``inA``, so ``n`` sources need ``ceil((n - 1) / 3)`` blocks.
    The blocks live in a ``Requests`` folder of the target program and every link is an
    ordinary ``b:Link``, so nothing needs Java or a station-side installer.
    """

    document, _ = _read_bog(assembled_bog, "assembled project station")
    indexed = _index_programs(document, programs)
    station_root = _root_component(document, "assembled project station")
    modules = _module_declarations(station_root.get("m"))
    if modules.get("kitControl", "kitControl") != "kitControl":
        raise ValueError("station declares a conflicting kitControl module symbol")
    modules.setdefault("kitControl", "kitControl")
    station_root.set(
        "m", " ".join(f"{symbol}={module}" for symbol, module in sorted(modules.items()))
    )
    next_handle = max((int(value, 16) for value in _collect_handles(document)), default=0) + 1
    rows: list[dict[str, Any]] = []
    for ordinal, aggregation in enumerate(
        sorted(aggregations, key=lambda item: (item.target_equipment, item.target_point)),
        start=1,
    ):
        block_type = _REDUCERS.get(aggregation.reduce)
        if block_type is None:
            raise ValueError(f"unknown aggregation reduce {aggregation.reduce!r}")
        target_entry = indexed.get(aggregation.target_equipment)
        if target_entry is None:
            raise ValueError("cross-program aggregation references unassembled equipment")
        target_job, target_graph, target_program = target_entry
        target = _find_program_point(target_program, aggregation.target_point)
        if "in16" in _driven_slots(target):
            raise ValueError(
                f"cross-program target already has a driver: "
                f"{aggregation.target_equipment}.{aggregation.target_point}"
            )
        sources: list[ElementTree.Element] = []
        for source_equipment, source_point in aggregation.sources:
            source_entry = indexed.get(source_equipment)
            if source_entry is None:
                raise ValueError("cross-program aggregation references unassembled equipment")
            source = _find_program_point(source_entry[2], source_point)
            if source.get("h") is None:
                raise ValueError("cross-program aggregation source has no valid Niagara handle")
            sources.append(source)
        folder = _named_child(target_program, "Requests")
        if folder is None:
            folder = ElementTree.SubElement(
                target_program,
                "p",
                {"n": "Requests", "h": format(next_handle, "x"), "t": "b:Folder"},
            )
            next_handle += 1
        stage_names: list[str] = []
        previous: ElementTree.Element | None = None
        pending = list(sources)
        stage = 0
        while pending or previous is None:
            stage += 1
            name = f"{aggregation.target_point}_{aggregation.reduce}{stage}"
            block = ElementTree.SubElement(
                folder, "p", {"n": name, "h": format(next_handle, "x"), "t": block_type}
            )
            next_handle += 1
            stage_names.append(name)
            slots = list(_REDUCER_INPUTS)
            if previous is not None:
                _append_link(block, previous, "out", slots.pop(0), "Link")
            for slot in slots:
                if not pending:
                    break
                _append_link(block, pending.pop(0), "out", slot, "Link")
            previous = block
        assert previous is not None
        _append_link(target, previous, "out", "in16", "BactalkProjectRequest")
        rows.append(
            {
                "target_equipment": aggregation.target_equipment,
                "target_point": aggregation.target_point,
                "target_ord": (
                    f"{program_root_ord(target_job, target_graph)}/{aggregation.target_point}"
                ),
                "reduce": aggregation.reduce,
                "block_type": block_type,
                "stages": stage_names,
                "source_count": len(sources),
                "sources": [f"{e}.{p}" for e, p in aggregation.sources],
                "data_type": aggregation.data_type,
                "ordinal": ordinal,
            }
        )
    ElementTree.indent(document, space="  ")
    xml = ElementTree.tostring(document, encoding="utf-8", xml_declaration=True)
    reparsed = ElementTree.fromstring(xml)
    handles = set(_collect_handles(reparsed))
    unresolved = _collect_handle_refs(reparsed) - handles
    if unresolved:
        raise ValueError("cross-program aggregations introduced unresolved handle references")
    return _deterministic_bog(xml), rows


def _add_project_program_links(
    assembled_bog: bytes,
    programs: list[tuple[bytes, JobSpec, ControlGraph]],
    links: list[NiagaraProgramLink],
) -> tuple[bytes, list[dict[str, Any]]]:
    document, _ = _read_bog(assembled_bog, "assembled project station")
    station_root = _root_component(document, "assembled project station")
    indexed: dict[str, tuple[JobSpec, ControlGraph, ElementTree.Element]] = {}
    for _, job, graph in programs:
        profile = job.deliverables.shop_profile
        parent = _target_parent(
            station_root,
            profile.station_folder if profile is not None else None,
        )
        program = _named_child(parent, graph.name)
        if program is None:
            raise ValueError(f"assembled station is missing program {graph.name!r}")
        indexed[job.equipment_name] = (job, graph, program)

    rows: list[dict[str, Any]] = []
    for index, link in enumerate(
        sorted(
            links,
            key=lambda item: (
                item.target_equipment,
                item.target_point,
                item.source_equipment,
                item.source_point,
            ),
        ),
        start=1,
    ):
        source_entry = indexed.get(link.source_equipment)
        target_entry = indexed.get(link.target_equipment)
        if source_entry is None or target_entry is None:
            raise ValueError("cross-program link references unassembled equipment")
        source_job, source_graph, source_program = source_entry
        target_job, target_graph, target_program = target_entry
        # The legacy compiler keeps boundary points as direct children of the program;
        # the native emitter (N4) files them under Inputs/Outputs folders.
        source = _named_child(source_program, link.source_point) or _optional_program_point(
            source_program, link.source_point
        )
        target = _named_child(target_program, link.target_point) or _optional_program_point(
            target_program, link.target_point
        )
        if source is None or target is None:
            raise ValueError("cross-program link references a missing boundary component")
        source_handle = source.get("h")
        if source_handle is None or not _HANDLE.fullmatch(source_handle):
            raise ValueError("cross-program source has no valid Niagara handle")
        for child in target:
            if child.get("t") != "b:Link":
                continue
            target_slot = next(
                (
                    prop.get("v")
                    for prop in child
                    if prop.tag == "p" and prop.get("n") == "targetSlotName"
                ),
                None,
            )
            if target_slot == "in16":
                raise ValueError(
                    f"cross-program target already has a driver: "
                    f"{link.target_equipment}.{link.target_point}"
                )
        component_name = "BactalkProjectLink"
        suffix = 1
        while _named_child(target, component_name) is not None:
            component_name = f"BactalkProjectLink{suffix}"
            suffix += 1
        link_element = ElementTree.SubElement(
            target,
            "p",
            {"n": component_name, "t": "b:Link"},
        )
        for name, value in (
            ("sourceOrd", f"h:{source_handle.lower()}"),
            ("relationTags", ""),
            ("relationId", "n:dataLink"),
            ("sourceSlotName", "out"),
            ("targetSlotName", "in16"),
        ):
            ElementTree.SubElement(link_element, "p", {"n": name, "v": value})
        rows.append(
            {
                "source_equipment": link.source_equipment,
                "source_point": link.source_point,
                "source_ord": f"{program_root_ord(source_job, source_graph)}/{link.source_point}",
                "source_slot": "out",
                "target_equipment": link.target_equipment,
                "target_point": link.target_point,
                "target_ord": f"{program_root_ord(target_job, target_graph)}/{link.target_point}",
                "target_slot": "in16",
                "data_type": link.data_type,
                "source_handle": f"h:{source_handle.lower()}",
                "link_component": component_name,
                "ordinal": index,
            }
        )

    ElementTree.indent(document, space="  ")
    xml = ElementTree.tostring(document, encoding="utf-8", xml_declaration=True)
    reparsed = ElementTree.fromstring(xml)
    handles = set(_collect_handles(reparsed))
    unresolved = _collect_handle_refs(reparsed) - handles
    if unresolved:
        raise ValueError("cross-program links introduced unresolved handle references")
    return _deterministic_bog(xml), rows
