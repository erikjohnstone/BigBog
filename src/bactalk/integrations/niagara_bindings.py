from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from bactalk.domain import BlockKind, ControlGraph, JobSpec, ShopProfile, canonical_json

AM8X_LINK_SOURCE = (
    ".vendor/am8x-control/am8xControl-rt/src/"
    "com/sitecVendor/am8xControl/modbus/ModbusPointFactory.java"
)
AM8X_REVISION = "4b3944a0f10c5f2772c52b20ce0211ff09255f3b"

_INPUT_KINDS = {BlockKind.NUMERIC_INPUT, BlockKind.BOOLEAN_INPUT}
_OUTPUT_KINDS = {BlockKind.NUMERIC_OUTPUT, BlockKind.BOOLEAN_OUTPUT}


@dataclass(frozen=True)
class NiagaraBindingArtifact:
    relative_path: str
    content: str


@dataclass(frozen=True)
class NiagaraBindingExport:
    artifacts: tuple[NiagaraBindingArtifact, ...]
    manifest: dict[str, Any]


def _java_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _java_identifier(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not cleaned or not (cleaned[0].isalpha() or cleaned[0] == "_"):
        cleaned = f"N_{cleaned}"
    return cleaned


def program_root_ord_for(graph_name: str, profile: ShopProfile | None) -> str:
    parent = ""
    if profile is not None and profile.station_folder:
        parent = profile.station_folder.replace("\\", "/").strip("/") + "/"
    return f"station:|slot:/{parent}{graph_name}"


def program_root_ord(job: JobSpec, graph: ControlGraph) -> str:
    return program_root_ord_for(graph.name, job.deliverables.shop_profile)


def _binding_rows(job: JobSpec, graph: ControlGraph) -> tuple[list[dict[str, Any]], list[str]]:
    blocks = {item.id: item for item in graph.blocks}
    root = program_root_ord(job, graph)
    bindings: list[dict[str, Any]] = []
    unbound: list[str] = []
    for point in sorted(job.points, key=lambda item: item.name):
        if point.bacnet_object is None and point.niagara_ord is None:
            continue
        block = blocks.get(point.name)
        if block is None:
            if point.niagara_ord is not None:
                raise ValueError(
                    f"point {point.name} declares niagara_ord but has no compiled graph block"
                )
            unbound.append(point.name)
            continue
        if point.niagara_ord is None:
            unbound.append(point.name)
            continue
        program_ord = f"{root}/{point.name}"
        if block.kind in _INPUT_KINDS:
            source_ord = point.niagara_ord
            source_slot = "out"
            target_ord = program_ord
            target_slot = "in16"
            direction = "proxy_to_program"
        elif block.kind in _OUTPUT_KINDS:
            source_ord = program_ord
            source_slot = "out"
            target_ord = point.niagara_ord
            target_slot = f"in{point.niagara_write_priority or 16}"
            direction = "program_to_proxy"
        else:
            raise ValueError(
                f"point {point.name} maps to internal block kind {block.kind.value}; "
                "Niagara bindings require an input or output boundary block"
            )
        bindings.append(
            {
                "point": point.name,
                "role": point.role.value,
                "data_type": point.data_type.value,
                "direction": direction,
                "source_ord": source_ord,
                "source_slot": source_slot,
                "target_ord": target_ord,
                "target_slot": target_slot,
                "bacnet_device_instance": point.bacnet_device_instance,
                "bacnet_object": point.bacnet_object,
                "write_priority": (
                    int(target_slot.removeprefix("in"))
                    if direction == "program_to_proxy"
                    else None
                ),
            }
        )
    return bindings, unbound


def _java_source(graph: ControlGraph, bindings: list[dict[str, Any]]) -> tuple[str, str]:
    class_name = f"BactalkPointBinder_{_java_identifier(graph.name)}"
    lines = [
        "package com.bactalk.generated;",
        "",
        "import javax.baja.naming.BOrd;",
        "import javax.baja.sys.BComponent;",
        "import javax.baja.sys.BLink;",
        "import javax.baja.sys.BValue;",
        "import javax.baja.sys.Slot;",
        "",
        "/** Generated review artifact. Compile and qualify against the shop's Niagara SDK. */",
        f"public final class {class_name} {{",
        f"  private {class_name}() {{}}",
        "",
        "  public static void apply(BComponent context) throws Exception {",
    ]
    for binding in bindings:
        lines.extend(
            [
                "    ensureLink(context,",
                f"      {_java_string(binding['source_ord'])},",
                f"      {_java_string(binding['source_slot'])},",
                f"      {_java_string(binding['target_ord'])},",
                f"      {_java_string(binding['target_slot'])});",
            ]
        )
    lines.extend(
        [
            "  }",
            "",
            "  private static void ensureLink(BComponent context, String sourceOrd,",
            "      String sourceSlot, String targetOrd, String targetSlot) throws Exception {",
            "    BComponent source = resolveComponent(context, sourceOrd);",
            "    BComponent target = resolveComponent(context, targetOrd);",
            "    Slot sourceSlotDef = source.getSlot(sourceSlot);",
            "    Slot targetSlotDef = target.getSlot(targetSlot);",
            "    if (sourceSlotDef == null)",
            "      throw new IllegalStateException(\"Missing source slot: \" + sourceOrd +",
            "        \"/\" + sourceSlot);",
            "    if (targetSlotDef == null)",
            "      throw new IllegalStateException(\"Missing target slot: \" + targetOrd +",
            "        \"/\" + targetSlot);",
            "    BLink[] existing = target.getLinks();",
            "    if (existing != null) for (BLink link : existing) {",
            "      if (!targetSlot.equals(link.getTargetSlotName())) continue;",
            "      if (source == link.getSourceComponent() &&",
            "          sourceSlot.equals(link.getSourceSlotName())) return;",
            "      throw new IllegalStateException(\"Target slot already linked: \" +",
            "        targetOrd + \"/\" + targetSlot);",
            "    }",
            "    BLink link = new BLink(BOrd.make(sourceOrd), sourceSlot, targetSlot, true);",
            "    link.setEnabled(true);",
            "    target.add(null, link);",
            "  }",
            "",
            "  private static BComponent resolveComponent(BComponent context, String ord)",
            "      throws Exception {",
            "    BValue value = BOrd.make(ord).get(context, null);",
            "    if (!(value instanceof BComponent))",
            "      throw new IllegalStateException(\"Not a component: \" + ord);",
            "    return (BComponent) value;",
            "  }",
            "}",
            "",
        ]
    )
    return class_name, "\n".join(lines)


def build_niagara_binding_export(job: JobSpec, graph: ControlGraph) -> NiagaraBindingExport:
    """Emit exact, fail-closed links between existing Niagara points and compiled logic.

    This does not create, discover, or modify a live station. It emits a deterministic
    installation plan and SDK source for execution only in the licensed review lane.
    """

    bindings, unbound = _binding_rows(job, graph)
    class_name, java = _java_source(graph, bindings)
    mapped_points = sorted(point.name for point in job.points if point.bacnet_object is not None)
    manifest = {
        "schema": "bactalk.niagara-point-bindings/v1",
        "equipment_name": job.equipment_name,
        "graph_name": graph.name,
        "program_root_ord": program_root_ord(job, graph),
        "bindings": bindings,
        "binding_count": len(bindings),
        "mapped_point_count": len(mapped_points),
        "unbound_mapped_points": sorted(set(mapped_points) & set(unbound)),
        "all_mapped_points_have_exact_ords": not (set(mapped_points) & set(unbound)),
        "source_reference": {
            "path": AM8X_LINK_SOURCE,
            "revision": AM8X_REVISION,
            "license": "Apache-2.0",
            "borrowed_pattern": (
                "resolve exact station components, validate slots, detect target collisions, "
                "and add an enabled BLink"
            ),
        },
        "safety": {
            "live_station_modified": False,
            "discovery_performed": False,
            "implicit_point_path_inference": False,
            "existing_target_link_overwrite_allowed": False,
            "licensed_runtime_qualified": False,
        },
        "runtime_gate": (
            "Import the logic fragment at program_root_ord, compile this source against the exact "
            "licensed Niagara SDK, run it only in a disposable station, and retain link/readback "
            "evidence before approving a target profile."
        ),
    }
    readback = {
        "schema": "bactalk.niagara-point-binding-readback/v1",
        "expected_links": bindings,
        "required_checks": [
            "every source and target ord resolves",
            "source and target slots exist with compatible types",
            "each target slot has exactly the declared source",
            "BACnet input values reach program inputs",
            "program outputs reach BACnet proxy command slots at the declared priority",
        ],
        "mutating_operations": [],
        "runtime_required": True,
    }
    artifacts = (
        NiagaraBindingArtifact("niagara-point-bindings.json", canonical_json(manifest)),
        NiagaraBindingArtifact(f"{class_name}.java", java),
        NiagaraBindingArtifact("niagara-point-binding-readback.json", canonical_json(readback)),
    )
    manifest["artifacts"] = [
        {
            "path": item.relative_path,
            "bytes": len(item.content.encode("utf-8")),
            "sha256": hashlib.sha256(item.content.encode("utf-8")).hexdigest(),
        }
        for item in artifacts
    ]
    return NiagaraBindingExport(artifacts=artifacts, manifest=manifest)
