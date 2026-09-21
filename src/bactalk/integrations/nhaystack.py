from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from phable import GridBuilder, Marker, Ref
from phable.io.ph_zinc import ph_from_zinc, ph_to_zinc

from bactalk.domain import ControlGraph, DataType, JobSpec, PointRole, canonical_json
from bactalk.integrations.niagara_bindings import program_root_ord
from bactalk.stack_lock import locked_revision

NHAYSTACK_REPOSITORY = "https://github.com/ci-richard-mcelhinney/nhaystack"
NHAYSTACK_REVISION = locked_revision("nhaystack")

_COLUMNS = (
    "id",
    "dis",
    "site",
    "equip",
    "point",
    "siteRef",
    "equipRef",
    "kind",
    "unit",
    "cur",
    "his",
    "n4SlotPath",
    "bacnetRef",
    "brickClass",
    "sensor",
    "sp",
    "cmd",
    "status",
    "alarm",
    "ahu",
    "boiler",
    "chiller",
    "coolingTower",
    "elecMeter",
    "heatExchanger",
    "pump",
    "vav",
    "vfd",
)

_EQUIPMENT_MARKERS = {
    "Air_Handling_Unit": "ahu",
    "AHU": "ahu",
    "Boiler": "boiler",
    "Chiller": "chiller",
    "Cooling_Tower": "coolingTower",
    "Electrical_Meter": "elecMeter",
    "Heat_Exchanger": "heatExchanger",
    "Pump": "pump",
    "VAV": "vav",
    "Variable_Frequency_Drive": "vfd",
}

_ROLE_MARKERS = {
    PointRole.SENSOR: "sensor",
    PointRole.SETPOINT: "sp",
    PointRole.COMMAND: "cmd",
    PointRole.STATUS: "status",
    PointRole.ALARM: "alarm",
}


@dataclass(frozen=True)
class NHaystackArtifact:
    relative_path: str
    content: str


@dataclass(frozen=True)
class NHaystackExport:
    artifacts: tuple[NHaystackArtifact, ...]
    manifest: dict[str, Any]


def _haystack_token(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_~-]+", "_", value).strip("_")
    return cleaned or "unnamed"


def _component_ref(path: str) -> Ref:
    # NHaystack's current Java implementation uses the component-space prefix C
    # followed by a Haystack-safe Niagara slot path: slash becomes a dot.
    return Ref(f"C.{path.replace('/', '.')}")


def _slot_path(ord_value: str) -> str:
    if not ord_value.startswith("station:|slot:/"):
        raise ValueError(f"expected an exact station slot ord, got {ord_value!r}")
    return ord_value.removeprefix("station:|")


def _component_ref_from_ord(ord_value: str) -> Ref:
    return _component_ref(_slot_path(ord_value).removeprefix("slot:/"))


def _java_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _java_identifier(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not cleaned or not (cleaned[0].isalpha() or cleaned[0] == "_"):
        cleaned = f"N_{cleaned}"
    return cleaned


def _tag_dict(markers: list[str], refs: dict[str, Ref]) -> str:
    tokens = [*markers, *(f"{name}:@{ref.val}" for name, ref in sorted(refs.items()))]
    return " ".join(tokens)


def _annotation_rows(
    job: JobSpec,
    graph: ControlGraph,
) -> tuple[list[dict[str, str]], str | None, str]:
    profile = job.deliverables.shop_profile
    root_ord = program_root_ord(job, graph)
    site_ord = profile.niagara_site_ord if profile is not None else None
    equipment_ord = (
        profile.niagara_equipment_ord
        if profile is not None and profile.niagara_equipment_ord is not None
        else root_ord
    )
    equipment_ref = _component_ref_from_ord(equipment_ord)
    site_ref = _component_ref_from_ord(site_ord) if site_ord is not None else None
    brick_local = job.equipment_brick_class.rsplit(":", 1)[-1]
    equipment_marker = _EQUIPMENT_MARKERS.get(brick_local)

    rows: list[dict[str, str]] = []
    if site_ord is not None:
        rows.append(
            {
                "kind": "site",
                "name": job.site,
                "ord": site_ord,
                "zinc": _tag_dict(["site"], {}),
            }
        )
    equipment_markers = ["equip"]
    if equipment_marker is not None:
        equipment_markers.append(equipment_marker)
    equipment_refs = {"siteRef": site_ref} if site_ref is not None else {}
    rows.append(
        {
            "kind": "equipment",
            "name": job.equipment_name,
            "ord": equipment_ord,
            "zinc": _tag_dict(equipment_markers, equipment_refs),
        }
    )
    for point in sorted(job.points, key=lambda item: item.name):
        rows.append(
            {
                "kind": "point",
                "name": point.name,
                "ord": f"{root_ord}/{point.name}",
                "zinc": _tag_dict(
                    ["point", _ROLE_MARKERS[point.role]],
                    {"equipRef": equipment_ref},
                ),
            }
        )
    return rows, site_ord, equipment_ord


def _tag_installer_source(graph: ControlGraph, rows: list[dict[str, str]]) -> tuple[str, str]:
    class_name = f"BactalkHaystackTagInstaller_{_java_identifier(graph.name)}"
    lines = [
        "package com.bactalk.generated;",
        "",
        "import javax.baja.naming.BOrd;",
        "import javax.baja.sys.BComponent;",
        "import javax.baja.sys.BValue;",
        "import nhaystack.BHDict;",
        "",
        "/** Generated review artifact. Compile and qualify against the shop's Niagara SDK. */",
        f"public final class {class_name} {{",
        f"  private {class_name}() {{}}",
        "",
        "  public static void apply(BComponent context) throws Exception {",
    ]
    for row in rows:
        lines.extend(
            [
                "    ensureTags(context,",
                f"      {_java_string(row['ord'])},",
                f"      {_java_string(row['zinc'])});",
            ]
        )
    lines.extend(
        [
            "  }",
            "",
            "  private static void ensureTags(BComponent context, String ord, String zinc)",
            "      throws Exception {",
            "    BComponent component = resolveComponent(context, ord);",
            "    BHDict desired = BHDict.make(zinc);",
            "    BValue existing = component.get(BHDict.HAYSTACK_IDENTIFIER);",
            "    if (existing == null) {",
            "      component.add(BHDict.HAYSTACK_IDENTIFIER, desired);",
            "      return;",
            "    }",
            "    if (desired.equals(existing)) return;",
            "    throw new IllegalStateException(\"Existing haystack tags differ: \" + ord);",
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


def _zinc(grid: Any) -> str:
    # phable 0.1.29 emits three-digit escapes for U+00xx characters. Zinc
    # requires four hexadecimal digits. Normalizing the degree sign keeps real
    # contractor units (for example °F) lossless and round-trippable.
    return ph_to_zinc(grid).replace(r"\ub0", r"\u00b0")


def _bacnet_ref(job: JobSpec, point_name: str) -> str | None:
    point = next(item for item in job.points if item.name == point_name)
    if point.bacnet_object is None:
        return None
    device = point.bacnet_device_instance
    if device is None and job.bacnet_scan is not None and len(job.bacnet_scan.devices) == 1:
        device = job.bacnet_scan.devices[0].device_instance
    if device is None:
        return None
    return f"bacnet://device/{device}/object/{point.bacnet_object}"


def build_readonly_nhaystack_export(job: JobSpec, graph: ControlGraph) -> NHaystackExport:
    """Build the expected nHaystack readback model for a compiled Niagara graph.

    This adapter never connects to a station and never emits credentials or a
    Haystack write request. It gives the reviewer an exact, parser-validated
    contract for what BACTalk will read back after the nHaystack service cache
    is rebuilt in the licensed Niagara runtime.
    """

    graph_points = {block.id for block in graph.blocks}
    missing = sorted(point.name for point in job.points if point.name not in graph_points)
    if missing:
        raise ValueError(
            "nHaystack export requires every declared point in the compiled graph: "
            + ", ".join(missing)
        )

    annotation_rows, site_ord, equipment_ord = _annotation_rows(job, graph)
    root_ord = program_root_ord(job, graph)
    site_ref = _component_ref_from_ord(site_ord) if site_ord is not None else None
    equip_ref = _component_ref_from_ord(equipment_ord)
    builder = GridBuilder().set_meta(
        {
            "dis": "BACTalk nHaystack readback projection",
            "bactalkMode": "read-only",
        }
    )
    for column in _COLUMNS:
        builder.add_col(column)

    if site_ref is not None:
        builder.add_row({"id": site_ref, "dis": job.site, "site": Marker()})
    equipment_row: dict[str, Any] = {
        "id": equip_ref,
        "dis": job.equipment_name,
        "equip": Marker(),
        "brickClass": job.equipment_brick_class,
    }
    if site_ref is not None:
        equipment_row["siteRef"] = site_ref
    brick_local = job.equipment_brick_class.rsplit(":", 1)[-1]
    equipment_marker = _EQUIPMENT_MARKERS.get(brick_local)
    if equipment_marker in _COLUMNS:
        equipment_row[equipment_marker] = Marker()
    builder.add_row(equipment_row)

    compiled_histories = {
        item.point for item in job.deliverables.histories if item.mode == "fixed_interval"
    }
    expected_points: list[dict[str, Any]] = []
    for point in sorted(job.points, key=lambda item: item.name):
        point_ord = f"{root_ord}/{point.name}"
        slot_path = _slot_path(point_ord)
        point_ref = _component_ref_from_ord(point_ord)
        role_marker = _ROLE_MARKERS[point.role]
        row: dict[str, Any] = {
            "id": point_ref,
            "dis": point.label,
            "point": Marker(),
            "equipRef": equip_ref,
            "kind": "Number" if point.data_type == DataType.NUMERIC else "Bool",
            "cur": Marker(),
            "n4SlotPath": slot_path,
            role_marker: Marker(),
        }
        if site_ref is not None:
            row["siteRef"] = site_ref
        if point.units:
            row["unit"] = point.units
        if point.name in compiled_histories:
            row["his"] = Marker()
        if point.brick_class:
            row["brickClass"] = point.brick_class
        bacnet_ref = _bacnet_ref(job, point.name)
        if bacnet_ref:
            row["bacnetRef"] = bacnet_ref
        builder.add_row(row)
        expected_points.append(
            {
                "point": point.name,
                "id": point_ref.val,
                "n4_slot_path": slot_path,
                "kind": row["kind"],
                "expects_cur": True,
                "expects_his": point.name in compiled_histories,
                "bacnet_ref": bacnet_ref,
            }
        )

    zinc = _zinc(builder.build())
    decoded = ph_from_zinc(zinc)
    expected_record_count = len(job.points) + 1 + int(site_ref is not None)
    if len(decoded.rows) != expected_record_count:
        raise ValueError("nHaystack Zinc projection did not round-trip every expected record")
    if any("write" in row or "writeVal" in row for row in decoded.rows):
        raise ValueError("nHaystack readback projection unexpectedly contains a write capability")

    verification = {
        "schema": "bactalk.nhaystack-readback/v1",
        "filter": "point and equipRef",
        "expected_site_ref": site_ref.val if site_ref is not None else None,
        "expected_equipment_ref": equip_ref.val,
        "expected_points": expected_points,
        "checks": [
            "exact point record count",
            "id and n4SlotPath match the compiled Niagara graph",
            "equipRef resolves and siteRef resolves when an exact site ord was declared",
            "kind matches the typed point",
            "cur is present",
            "his is present only for target-compiled histories",
            "no BACTalk write operation is permitted",
        ],
    }
    install_plan = {
        "schema": "bactalk.nhaystack-install-plan/v1",
        "mode": "human-executed licensed-runtime integration",
        "module_distribution_included": False,
        "module_source": {
            "repository": NHAYSTACK_REPOSITORY,
            "revision": NHAYSTACK_REVISION,
            "license": "AFL-3.0",
        },
        "steps": [
            "Have the controls shop approve the AFL-3.0 distribution and Niagara compatibility.",
            "Install compatible nhaystack-rt and, only if needed, nhaystack-wb modules.",
            "Add and enable NHaystackService under the station Services folder.",
            "Compile the generated tag installer against the exact approved Niagara SDK.",
            "Run it in a disposable station; it refuses any differing existing haystack slot.",
            "Review site/equipment/point tags and rebuild the nHaystack cache.",
            "Use a Niagara account restricted to read/query/history operations for verification.",
            "Run the expected-readback contract and retain the result with the station review.",
        ],
        "required_safety_controls": [
            "No credential or live endpoint is present in this package.",
            "The BACTalk verifier does not invoke pointWrite, alarmAck, or history upload.",
            "Niagara role permissions must deny commands and alarm acknowledgement.",
            "Installation and cache rebuild require a human in the licensed Niagara runtime.",
            "The generated installer never replaces a differing existing haystack dictionary.",
        ],
    }
    class_name, installer_source = _tag_installer_source(graph, annotation_rows)
    artifacts = (
        NHaystackArtifact("expected-readback.zinc", zinc),
        NHaystackArtifact("verification.json", canonical_json(verification)),
        NHaystackArtifact("install-plan.json", canonical_json(install_plan)),
        NHaystackArtifact(f"{class_name}.java", installer_source),
    )
    manifest = {
        "schema": "bactalk.nhaystack-export/v1",
        "mode": "read-only-verification",
        "writes_enabled": False,
        "generated_station_mutation_source_included": True,
        "generated_source_executed_by_bactalk": False,
        "source_revision": NHAYSTACK_REVISION,
        "record_count": len(decoded.rows),
        "point_count": len(job.points),
        "historized_point_count": len(compiled_histories),
        "site_ord": site_ord,
        "equipment_ord": equipment_ord,
        "program_root_ord": root_ord,
        "tag_annotations": annotation_rows,
        "tag_annotation_count": len(annotation_rows),
        "existing_tag_overwrite_allowed": False,
        "artifacts": [
            {
                "path": artifact.relative_path,
                "bytes": len(artifact.content.encode("utf-8")),
                "sha256": hashlib.sha256(artifact.content.encode("utf-8")).hexdigest(),
            }
            for artifact in artifacts
        ],
        "runtime_gate": (
            "The package is parser-validated offline. A shop-approved nHaystack module, "
            "licensed Niagara runtime, read-only role, cache rebuild, and captured readback "
            "are required before runtime conformance is claimed."
        ),
    }
    return NHaystackExport(artifacts=artifacts, manifest=manifest)
