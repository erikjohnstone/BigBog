from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from typing import Any

from bactalk.domain import ControlGraph, JobSpec, PointRole, TestReport, canonical_json
from bactalk.integrations.environment_pack import EnvironmentPackExport
from bactalk.integrations.niagara_alarms import build_niagara_alarm_export
from bactalk.integrations.niagara_bindings import build_niagara_binding_export
from bactalk.integrations.niagara_graphics import (
    NiagaraGraphicsExport,
    build_niagara_graphics_export,
)


@dataclass(frozen=True)
class DeliverableArtifact:
    relative_path: str
    content: bytes


@dataclass(frozen=True)
class DeliverablePackage:
    manifest: dict[str, Any]
    artifacts: tuple[DeliverableArtifact, ...]


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return canonical_json(payload).encode("utf-8")


def _point_map(job: JobSpec) -> bytes:
    stream = io.StringIO(newline="")
    fieldnames = [
        "name",
        "source_name",
        "label",
        "role",
        "data_type",
        "units",
        "required",
        "bacnet_device_instance",
        "bacnet_object",
        "niagara_ord",
        "niagara_write_priority",
        "brick_class",
    ]
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for point in job.points:
        writer.writerow(
            {
                "name": point.name,
                "source_name": point.source_name or "",
                "label": point.label,
                "role": point.role.value,
                "data_type": point.data_type.value,
                "units": point.units or "",
                "required": str(point.required).lower(),
                "bacnet_device_instance": (
                    point.bacnet_device_instance if point.bacnet_device_instance is not None else ""
                ),
                "bacnet_object": point.bacnet_object or "",
                "niagara_ord": point.niagara_ord or "",
                "niagara_write_priority": point.niagara_write_priority or "",
                "brick_class": point.brick_class or "",
            }
        )
    return stream.getvalue().encode("utf-8")


def _alarm_manifest(job: JobSpec, graph: ControlGraph) -> dict[str, Any]:
    blocks = {block.id: block for block in graph.blocks}
    requirements = {item.point: item for item in job.deliverables.alarms}
    alarms: list[dict[str, Any]] = []
    for point in job.points:
        if point.role != PointRole.ALARM:
            continue
        block = blocks.get(point.name)
        requirement = requirements.get(point.name)
        alarms.append(
            {
                "point": point.name,
                "label": point.label,
                "data_type": point.data_type.value,
                "source_block": block.id if block else None,
                "source_kind": block.kind.value if block else None,
                "niagara_alarm_extension": (
                    "alarm:BAlarmSourceExt" if requirement is not None else None
                ),
                "alarm_class": requirement.alarm_class if requirement else None,
                "priority": requirement.priority if requirement else None,
                "acknowledgement_required": (
                    requirement.acknowledgement_required if requirement else None
                ),
                "delay_seconds": requirement.delay_seconds if requirement else None,
                "offnormal_text": requirement.offnormal_text if requirement else None,
                "normal_text": requirement.normal_text if requirement else None,
                "routing": requirement.routing if requirement else [],
                "requirements_complete": requirement is not None,
            }
        )
    complete = bool(alarms) and all(item["requirements_complete"] for item in alarms)
    return {
        "schema": "bactalk-alarm-manifest/v1",
        "equipment_name": job.equipment_name,
        "alarms": alarms,
        "status": "requirements_complete"
        if complete
        else ("requirements_missing" if alarms else "not_specified"),
        "blocker": (
            "A Niagara SDK source-extension plan is emitted. Licensed-SDK compilation, "
            "AlarmService policy binding, runtime transition tests, acknowledgement, and "
            "routing qualification are still required."
            if complete
            else (
                "Alarm class, priority, acknowledgement, delay, routing, and Niagara extension "
                "requirements require engineer/shop policy."
                if alarms
                else "No alarm points were declared in the contractor job."
            )
        ),
    }


def _schedule_manifest(job: JobSpec) -> dict[str, Any]:
    consumers = [
        point.name
        for point in job.points
        if any(token in point.name.lower() for token in ("occup", "schedule", "enable"))
        and point.role in {PointRole.SENSOR, PointRole.STATUS, PointRole.SETPOINT}
    ]
    return {
        "schema": "bactalk-schedule-manifest/v1",
        "equipment_name": job.equipment_name,
        "schedule_consumers": consumers,
        "definitions": [item.model_dump(mode="json") for item in job.deliverables.schedules],
        "status": (
            "requirements_complete"
            if job.deliverables.schedules
            else ("requirements_missing" if consumers else "not_specified")
        ),
        "blocker": (
            "Weekly schedule objects are emitted; station-timezone parity, holiday calendars, "
            "and licensed-runtime behavior still require qualification."
            if job.deliverables.schedules
            else (
                "Calendar, weekly schedule, holiday, optimum-start, and override policies were "
                "not provided."
                if consumers
                else "No schedule consumer was inferred from the declared points."
            )
        ),
    }


def _history_manifest(job: JobSpec) -> dict[str, Any]:
    definitions = [
        {
            **item.model_dump(mode="json"),
            "target_compiled": item.mode == "fixed_interval",
            "niagara_extension": (
                "NumericIntervalHistoryExt"
                if item.mode == "fixed_interval"
                and next(point for point in job.points if point.name == item.point).data_type.value
                == "numeric"
                else ("BooleanIntervalHistoryExt" if item.mode == "fixed_interval" else None)
            ),
            "retention_encoding": (
                "rolling_record_capacity" if item.mode == "fixed_interval" else None
            ),
        }
        for item in job.deliverables.histories
    ]
    compiled_count = sum(item["target_compiled"] for item in definitions)
    all_compiled = bool(definitions) and compiled_count == len(definitions)
    return {
        "schema": "bactalk-history-manifest/v1",
        "equipment_name": job.equipment_name,
        "definitions": definitions,
        "status": ("requirements_complete" if job.deliverables.histories else "not_specified"),
        "niagara_history_extensions_emitted": compiled_count > 0,
        "target_compiled": all_compiled,
        "blocker": (
            "Fixed-interval extensions and rolling record capacities are emitted; licensed "
            "runtime behavior and wall-clock retention must still be qualified."
            if all_compiled
            else (
                "COV histories remain review-only until their Niagara collector serialization "
                "is qualified."
                if job.deliverables.histories
                else "No history sampling or retention requirements were provided."
            )
        ),
    }


def _graphics_model(
    job: JobSpec,
    graph: ControlGraph,
    graphics_export: NiagaraGraphicsExport,
) -> dict[str, Any]:
    blocks = {block.id: block for block in graph.blocks}
    widgets = []
    for point in job.points:
        block = blocks.get(point.name)
        widgets.append(
            {
                "id": point.name,
                "source_name": point.source_name,
                "label": point.label,
                "kind": point.role.value,
                "data_type": point.data_type.value,
                "units": point.units,
                "brick_class": point.brick_class,
                "bacnet": (
                    {
                        "device_instance": point.bacnet_device_instance,
                        "object_id": point.bacnet_object,
                    }
                    if point.bacnet_object
                    else None
                ),
                "layout_hint": ({"x": block.x, "y": block.y} if block is not None else None),
            }
        )
    widgets_by_id = {item["id"]: item for item in widgets}
    views = (
        [
            {
                **view.model_dump(mode="json", exclude={"points"}),
                "widgets": [widgets_by_id[name] for name in view.points],
            }
            for view in job.deliverables.graphics
        ]
        if job.deliverables.graphics
        else [{"id": "equipment-summary", "title": job.equipment_name, "widgets": widgets}]
    )
    return {
        "schema": "bactalk-graphics-model/v1",
        "site": job.site,
        "equipment_name": job.equipment_name,
        "equipment_brick_class": job.equipment_brick_class,
        "views": views,
        "requirements_status": (
            "requirements_complete" if job.deliverables.graphics else "default_review_view"
        ),
        "shop_profile": (
            job.deliverables.shop_profile.model_dump(mode="json")
            if job.deliverables.shop_profile
            else None
        ),
        "target": (
            "Niagara PX plus review data"
            if graphics_export.manifest["emitted_px_count"]
            else "review-data"
        ),
        "niagara_px_emitted": graphics_export.manifest["emitted_px_count"] > 0,
        "niagara_px_count": graphics_export.manifest["emitted_px_count"],
        "all_declared_views_target_compiled": graphics_export.manifest[
            "all_declared_views_target_compiled"
        ],
        "blocker": (
            graphics_export.manifest["runtime_gate"]
            if graphics_export.manifest["all_declared_views_target_compiled"]
            else (
                "One or more views lack a supplied, valid contractor PX template contract."
                if job.deliverables.graphics
                else "A shop graphics theme and qualified Niagara PX target are required."
            )
        ),
    }


def _engineering_summary(
    job: JobSpec,
    graph: ControlGraph,
    report: TestReport,
    graphics_export: NiagaraGraphicsExport,
    target_artifact_kind: str,
) -> bytes:
    mapped = sum(point.bacnet_object is not None for point in job.points)
    alarm_count = sum(point.role == PointRole.ALARM for point in job.points)
    lines = [
        f"# {job.name}",
        "",
        f"- Site: {job.site}",
        f"- Equipment: {job.equipment_name}",
        f"- Sequence: {job.sequence.family} ({job.sequence.version})",
        f"- Typed graph: {len(graph.blocks)} blocks / {len(graph.links)} links",
        f"- Point mapping: {mapped}/{len(job.points)} points include BACnet objects",
        f"- Alarm points: {alarm_count}",
        f"- Deterministic scenarios: {sum(item.passed for item in report.scenarios)}/"
        f"{len(report.scenarios)} passed",
        "",
        "## Deployment boundary",
        "",
        "This package is an engineering review artifact. "
        + (
            "Weekly schedules and fixed-interval histories are target-compiled when declared. "
            if target_artifact_kind == "niagara_bog"
            else "The logic target is ProgramObject source; schedules and histories remain "
            "review plans until the licensed Workbench build. "
        )
        + "Alarm extension Java and an execution "
        "plan plus nHaystack semantic-tag installer source are emitted, but still require "
        "licensed-SDK compilation and disposable-station qualification. "
        + (
            "Contractor-template PX files are generated with complete exact-ORD bindings, but "
            "still require exact-version render/navigation/value-readback testing. "
            if graphics_export.manifest["all_declared_views_target_compiled"]
            else "One or more graphics remain review-only because a valid PX template is missing. "
        )
        + "COV histories, complete station assembly, licensed-runtime execution, and field "
        "qualification are not implied by review artifacts.",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_deliverable_package(
    job: JobSpec,
    graph: ControlGraph,
    report: TestReport,
    *,
    environment: EnvironmentPackExport | None = None,
    target_artifact_kind: str = "niagara_bog",
) -> DeliverablePackage:
    """Build deterministic review artifacts without overstating Niagara target coverage."""

    tag_manifest = {
        "schema": "bactalk-tag-manifest/v1",
        "equipment": {
            "name": job.equipment_name,
            "brick_class": job.equipment_brick_class,
        },
        "points": [
            {
                "name": point.name,
                "source_name": point.source_name,
                "brick_class": point.brick_class,
                "tagged": point.brick_class is not None,
            }
            for point in job.points
        ],
        "target": "Brick review model",
        "niagara_tags_embedded": False,
        "niagara_tag_installer_source_emitted": True,
        "shop_profile": (
            job.deliverables.shop_profile.model_dump(mode="json")
            if job.deliverables.shop_profile
            else None
        ),
    }
    alarm_manifest = _alarm_manifest(job, graph)
    alarm_export = build_niagara_alarm_export(job, graph)
    binding_export = build_niagara_binding_export(job, graph)
    graphics_export = build_niagara_graphics_export(job, graph, environment)
    schedule_manifest = _schedule_manifest(job)
    history_manifest = _history_manifest(job)
    graphics_model = _graphics_model(job, graph, graphics_export)
    profile = job.deliverables.shop_profile
    station_assembly_mode = (
        profile.station_template_mode if profile is not None else "compare_only"
    )
    station_assembly_requested = station_assembly_mode != "compare_only"
    artifacts = (
        DeliverableArtifact("point-map.csv", _point_map(job)),
        DeliverableArtifact("tags.json", _json_bytes(tag_manifest)),
        DeliverableArtifact("alarms.json", _json_bytes(alarm_manifest)),
        *(
            DeliverableArtifact(item.relative_path, item.content.encode("utf-8"))
            for item in alarm_export.artifacts
        ),
        DeliverableArtifact(
            "niagara-alarm-export.json",
            _json_bytes(alarm_export.manifest),
        ),
        *(
            DeliverableArtifact(item.relative_path, item.content.encode("utf-8"))
            for item in binding_export.artifacts
            # GOAL-NATIVE-BOG.md N5: the generated Java binder leaves the default
            # path; the JSON binding plan stays. The Java is emitted only for
            # jobs that opted into the expert ProgramObject lane.
            if job.sequence.expert_program_objects or not item.relative_path.endswith(".java")
        ),
        DeliverableArtifact("schedules.json", _json_bytes(schedule_manifest)),
        DeliverableArtifact("histories.json", _json_bytes(history_manifest)),
        *(
            DeliverableArtifact(item.relative_path, item.content)
            for item in graphics_export.artifacts
        ),
        DeliverableArtifact("graphics-model.json", _json_bytes(graphics_model)),
        DeliverableArtifact(
            "engineering-summary.md",
            _engineering_summary(
                job,
                graph,
                report,
                graphics_export,
                target_artifact_kind,
            ),
        ),
    )
    artifact_entries = [
        {
            "path": artifact.relative_path,
            "sha256": hashlib.sha256(artifact.content).hexdigest(),
            "bytes": len(artifact.content),
        }
        for artifact in artifacts
    ]
    manifest = {
        "schema": "bactalk-deliverables/v1",
        "equipment_name": job.equipment_name,
        "deployment_ready": False,
        "artifacts": artifact_entries,
        "coverage": {
            "logic": {
                "emitted": True,
                "artifact_kind": target_artifact_kind,
                "target": (
                    "Niagara .bog"
                    if target_artifact_kind == "niagara_bog"
                    else "Niagara ProgramObject source package"
                ),
                "licensed_workbench_compile_required": (
                    target_artifact_kind == "niagara_program_source_package"
                ),
            },
            "logic_bog": {
                "emitted": target_artifact_kind == "niagara_bog",
                "target": "Niagara .bog",
            },
            "point_mapping": {
                "emitted": True,
                "target": "Niagara SDK exact-ord binding plan and installer source",
                "binding_count": binding_export.manifest["binding_count"],
                "all_mapped_points_have_exact_ords": binding_export.manifest[
                    "all_mapped_points_have_exact_ords"
                ],
                "licensed_runtime_qualified": False,
            },
            "tags": {
                "emitted": True,
                "target": "Brick review model plus nHaystack BHDict installer source",
                "installer_source_emitted": True,
                "licensed_runtime_qualified": False,
            },
            "alarms": {
                "emitted": True,
                "target": "Niagara SDK alarm-extension source and execution plan",
                "source_extension_plan_compiled": alarm_export.manifest[
                    "source_extension_plan_compiled"
                ],
                "bog_extension_emitted": False,
                "alarm_class_policy_compiled": False,
                "licensed_runtime_qualified": False,
            },
            "schedules": {
                "emitted": True,
                "target": (
                    "Niagara .bog schedule objects"
                    if job.deliverables.schedules
                    and target_artifact_kind == "niagara_bog"
                    else "requirements manifest"
                ),
                "target_compiled": bool(job.deliverables.schedules)
                and target_artifact_kind == "niagara_bog",
            },
            "graphics": {
                "emitted": True,
                "target": (
                    "contractor-template Niagara PX"
                    if graphics_export.manifest["emitted_px_count"]
                    else "vendor-neutral review data"
                ),
                "px_count": graphics_export.manifest["emitted_px_count"],
                "target_compiled": graphics_export.manifest[
                    "all_declared_views_target_compiled"
                ],
                "licensed_runtime_qualified": False,
            },
            "histories": {
                "emitted": True,
                "target": (
                    "Niagara .bog fixed-interval extensions"
                    if history_manifest["niagara_history_extensions_emitted"]
                    and target_artifact_kind == "niagara_bog"
                    else "requirements manifest"
                ),
                "target_compiled": history_manifest["target_compiled"]
                and target_artifact_kind == "niagara_bog",
            },
            "station_assembly": {
                "emitted": station_assembly_requested,
                "target": (
                    "collision-safe assembled Niagara BOG"
                    if station_assembly_requested
                    else None
                ),
                "mode": station_assembly_mode,
                "licensed_runtime_qualified": False,
            },
        },
        "blocking_gates": [
            *(
                ["Alarm requirements are incomplete."]
                if alarm_manifest["status"] == "requirements_missing"
                else []
            ),
            *(
                [
                    "Mapped points without exact niagara_ord values are not automatically bound: "
                    + ", ".join(binding_export.manifest["unbound_mapped_points"])
                    + "."
                ]
                if binding_export.manifest["unbound_mapped_points"]
                else [
                    "Exact point-link installer source is emitted, but licensed-runtime link, "
                    "type, value-flow, and command-priority readback are not qualified."
                ]
            ),
            *(
                ["Schedule requirements are incomplete."]
                if schedule_manifest["status"] == "requirements_missing"
                else []
            ),
            "Niagara semantic-tag installer source is emitted, but exact nHaystack/Niagara "
            "runtime execution and cache readback are not qualified.",
            "Alarm extension source is emitted, but AlarmService priority, acknowledgement, "
            "recipient/routing policy and licensed-runtime execution are not target-qualified.",
            *(
                [
                    "Schedule objects are target-compiled but station-timezone parity and "
                    "licensed-runtime behavior are not qualified."
                ]
                if job.deliverables.schedules
                and target_artifact_kind == "niagara_bog"
                else ["Schedule and calendar objects are not target-compiled."]
            ),
            *(
                [
                    "Niagara PX files are generated, but exact-version render, navigation, "
                    "and live value-binding readback are not qualified."
                ]
                if graphics_export.manifest["all_declared_views_target_compiled"]
                else ["One or more Niagara PX graphics are not target-compiled."]
            ),
            *(
                [
                    "Fixed-interval history extensions are target-compiled, but licensed-runtime "
                    "behavior and wall-clock retention are not qualified."
                ]
                if history_manifest["target_compiled"]
                and target_artifact_kind == "niagara_bog"
                else ["COV history extensions and retention policies are not target-compiled."]
            ),
            *(
                [
                    "An offline assembled Niagara BOG is emitted, but licensed Workbench "
                    "import, module resolution, compile, restart, and retained readback are "
                    "not qualified."
                ]
                if station_assembly_requested
                else ["A contractor station BOG was not selected for offline assembly."]
            ),
            "Licensed Niagara runtime and field qualification have not passed.",
        ],
    }
    return DeliverablePackage(manifest=manifest, artifacts=artifacts)
