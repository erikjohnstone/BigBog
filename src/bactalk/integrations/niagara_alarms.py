from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from bactalk.domain import AlarmRequirement, ControlGraph, DataType, JobSpec, canonical_json
from bactalk.integrations.niagara_bindings import program_root_ord

AM8X_REPOSITORY = "https://github.com/zEhmsy/am8xControl"
AM8X_REVISION = "4b3944a0f10c5f2772c52b20ce0211ff09255f3b"


@dataclass(frozen=True)
class NiagaraAlarmArtifact:
    relative_path: str
    content: str


@dataclass(frozen=True)
class NiagaraAlarmExport:
    artifacts: tuple[NiagaraAlarmArtifact, ...]
    manifest: dict[str, Any]


def _java_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _java_identifier(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not cleaned or not (cleaned[0].isalpha() or cleaned[0] == "_"):
        cleaned = f"N_{cleaned}"
    return cleaned


def _alarm_class_slot(value: str) -> str:
    return _java_identifier(value)


def _installer_class_name(graph_name: str) -> str:
    return f"BactalkAlarmInstaller_{_java_identifier(graph_name)}"


def _algorithm(requirement: AlarmRequirement, data_type: DataType) -> dict[str, Any]:
    if data_type == DataType.BOOLEAN:
        return {
            "type": "boolean_change_of_state",
            "niagara_class": (
                "javax.baja.alarm.ext.offnormal.BBooleanChangeOfStateAlgorithm"
            ),
            "alarm_value": requirement.trigger == "boolean_true",
        }
    return {
        "type": "out_of_range",
        "niagara_class": "javax.baja.alarm.ext.offnormal.BOutOfRangeAlgorithm",
        "high_limit_enabled": requirement.trigger in {"above", "outside_range"},
        "high_limit": requirement.high_limit,
        "low_limit_enabled": requirement.trigger in {"below", "outside_range"},
        "low_limit": requirement.low_limit,
        "deadband": requirement.deadband,
    }


def _java_algorithm(requirement: AlarmRequirement, data_type: DataType, suffix: str) -> list[str]:
    if data_type == DataType.BOOLEAN:
        alarm_value = "true" if requirement.trigger == "boolean_true" else "false"
        return [
            f"    BBooleanChangeOfStateAlgorithm alg{suffix} = "
            "new BBooleanChangeOfStateAlgorithm();",
            f"    alg{suffix}.setAlarmValue({alarm_value});",
            f"    ext{suffix}.setOffnormalAlgorithm(alg{suffix});",
        ]
    high_enabled = requirement.trigger in {"above", "outside_range"}
    low_enabled = requirement.trigger in {"below", "outside_range"}
    lines = [
        f"    BOutOfRangeAlgorithm alg{suffix} = new BOutOfRangeAlgorithm();",
        f"    BLimitEnable limits{suffix} = new BLimitEnable();",
        f"    limits{suffix}.setHighLimitEnable({str(high_enabled).lower()});",
        f"    limits{suffix}.setLowLimitEnable({str(low_enabled).lower()});",
        f"    alg{suffix}.setLimitEnable(limits{suffix});",
    ]
    if high_enabled:
        lines.append(f"    alg{suffix}.setHighLimit({float(requirement.high_limit)}d);")
    if low_enabled:
        lines.append(f"    alg{suffix}.setLowLimit({float(requirement.low_limit)}d);")
    lines.extend(
        [
            f"    alg{suffix}.setDeadband({float(requirement.deadband)}d);",
            f"    ext{suffix}.setOffnormalAlgorithm(alg{suffix});",
        ]
    )
    return lines


def _java_source(job: JobSpec, graph: ControlGraph, extensions: list[dict[str, Any]]) -> str:
    class_name = _installer_class_name(graph.name)
    lines = [
        "package com.bactalk.generated;",
        "",
        "import javax.baja.alarm.BAlarmClass;",
        "import javax.baja.alarm.BAlarmService;",
        "import javax.baja.alarm.ext.BLimitEnable;",
        "import javax.baja.alarm.ext.BAlarmSourceExt;",
        "import javax.baja.alarm.ext.offnormal.BBooleanChangeOfStateAlgorithm;",
        "import javax.baja.alarm.ext.offnormal.BOutOfRangeAlgorithm;",
        "import javax.baja.control.BControlPoint;",
        "import javax.baja.naming.BOrd;",
        "import javax.baja.sys.BComponent;",
        "import javax.baja.sys.BRelTime;",
        "import javax.baja.sys.BValue;",
        "import javax.baja.sys.Flags;",
        "import javax.baja.util.BFormat;",
        "",
        "/** Generated review artifact. Compile and qualify against the shop's Niagara SDK. */",
        f"public final class {class_name} {{",
        f"  private {class_name}() {{}}",
        "",
        "  public static void apply(BComponent context, BAlarmService alarmService) "
        "throws Exception {",
    ]
    requirements = {item.point: item for item in job.deliverables.alarms}
    for index, extension in enumerate(extensions, start=1):
        requirement = requirements[extension["point"]]
        suffix = str(index)
        class_slot = extension["alarm_class_slot"]
        lines.extend(
            [
                f"    ensureAlarmClass(alarmService, {_java_string(class_slot)});",
                f"    BControlPoint point{suffix} = resolvePoint(context, "
                f"{_java_string(extension['point_ord'])});",
                f"    BAlarmSourceExt ext{suffix} = ensureExtension(point{suffix}, "
                f"{_java_string(extension['extension_slot'])});",
            ]
        )
        lines.extend(_java_algorithm(requirement, extension["data_type"], suffix))
        lines.extend(
            [
                f"    ext{suffix}.setAlarmClass({_java_string(class_slot)});",
                f"    ext{suffix}.setSourceName(BFormat.make("
                f"{_java_string(extension['source_name_format'])}));",
                f"    ext{suffix}.setTimeDelay(BRelTime.make("
                f"{int(round(requirement.delay_seconds * 1000))}L));",
                f"    ext{suffix}.setToOffnormalText(BFormat.make("
                f"{_java_string(requirement.offnormal_text)}));",
                f"    ext{suffix}.setToNormalText(BFormat.make("
                f"{_java_string(requirement.normal_text)}));",
            ]
        )
    lines.extend(
        [
            "  }",
            "",
            "  private static BControlPoint resolvePoint(BComponent context, String ord) "
            "throws Exception {",
            "    BValue value = BOrd.make(ord).get(context, null);",
            "    if (!(value instanceof BControlPoint))",
            "      throw new IllegalStateException("
            "\"Alarm point is not a BControlPoint: \" + ord);",
            "    return (BControlPoint) value;",
            "  }",
            "",
            "  private static BAlarmSourceExt ensureExtension(BControlPoint point, String slot) "
            "throws Exception {",
            "    BValue value = null;",
            "    try { value = point.get(slot); } catch (Exception missing) { /* add below */ }",
            "    if (value instanceof BAlarmSourceExt) return (BAlarmSourceExt) value;",
            "    if (value != null) throw new IllegalStateException("
            "\"Alarm slot collision: \" + slot);",
            "    BAlarmSourceExt extension = new BAlarmSourceExt();",
            "    point.add(slot, extension, Flags.SUMMARY);",
            "    return (BAlarmSourceExt) point.get(slot);",
            "  }",
            "",
            "  private static BAlarmClass ensureAlarmClass(BAlarmService service, String slot) "
            "throws Exception {",
            "    BAlarmClass existing = service.lookupAlarmClass(slot);",
            "    if (existing != null) return existing;",
            "    service.add(slot, new BAlarmClass(), Flags.SUMMARY);",
            "    return (BAlarmClass) service.get(slot);",
            "  }",
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def build_niagara_alarm_export(job: JobSpec, graph: ControlGraph) -> NiagaraAlarmExport:
    """Compile alarm requirements to a Niagara SDK execution plan and Java source.

    The source is deterministic and rooted in the pinned Apache-2.0 am8x
    BAlarmSourceExt pattern. It remains a review artifact until compiled and
    exercised against the contractor's licensed Niagara SDK/runtime.
    """

    points = {item.name: item for item in job.points}
    blocks = {item.id for item in graph.blocks}
    extensions: list[dict[str, Any]] = []
    class_policies: dict[str, dict[str, Any]] = {}
    for requirement in sorted(job.deliverables.alarms, key=lambda item: item.point):
        point = points[requirement.point]
        if point.name not in blocks:
            raise ValueError(f"alarm point is absent from compiled graph: {point.name}")
        class_slot = _alarm_class_slot(requirement.alarm_class)
        policy = {
            "requested_name": requirement.alarm_class,
            "niagara_slot": class_slot,
            "priority": requirement.priority,
            "acknowledgement_required": requirement.acknowledgement_required,
            "routing": requirement.routing,
            "target_compiled": False,
            "runtime_gate": (
                "Priority, acknowledgement workflow, recipients, escalation, and routing are "
                "AlarmService policy and must be bound to the shop's alarm classes."
            ),
        }
        previous = class_policies.get(class_slot)
        if previous is not None and previous != policy:
            raise ValueError(
                f"alarm class {requirement.alarm_class!r} has conflicting policy requirements"
            )
        class_policies[class_slot] = policy
        extensions.append(
            {
                "point": point.name,
                "data_type": point.data_type,
                "point_ord": f"{program_root_ord(job, graph)}/{point.name}",
                "extension_slot": "bactalkAlarmExt",
                "niagara_extension_class": "javax.baja.alarm.ext.BAlarmSourceExt",
                "alarm_class_slot": class_slot,
                "source_name_format": f"%parent.displayName% {point.label}",
                "algorithm": _algorithm(requirement, point.data_type),
                "delay_seconds": requirement.delay_seconds,
                "offnormal_text": requirement.offnormal_text,
                "normal_text": requirement.normal_text,
                "source_extension_compiled": True,
                "bog_extension_emitted": False,
                "licensed_runtime_qualified": False,
            }
        )

    serializable_extensions = [
        {**item, "data_type": item["data_type"].value} for item in extensions
    ]
    plan = {
        "schema": "bactalk.niagara-alarm-plan/v1",
        "equipment_name": job.equipment_name,
        "graph_name": graph.name,
        "source_reference": {
            "repository": AM8X_REPOSITORY,
            "revision": AM8X_REVISION,
            "license": "Apache-2.0",
            "borrowed_pattern": [
                "ensure BAlarmClass",
                "attach BAlarmSourceExt without overwriting a conflicting slot",
                "configure typed offnormal algorithm",
                "bind alarm class, source format, and transition text",
            ],
            "excluded_domain_logic": "All AM-8x fire-panel names, points, ordinals, and policy.",
        },
        "alarm_classes": list(class_policies.values()),
        "extensions": serializable_extensions,
        "source_extension_plan_compiled": bool(extensions),
        "alarm_class_policy_compiled": False,
        "licensed_runtime_qualified": False,
        "live_station_modified": False,
    }
    java = _java_source(job, graph, extensions)
    readback = {
        "schema": "bactalk.niagara-alarm-readback/v1",
        "method": "nHaystack alarmRead plus Niagara property inspection",
        "expected_sources": [
            {
                "point": item["point"],
                "point_ord": item["point_ord"],
                "extension_slot": item["extension_slot"],
                "alarm_class_slot": item["alarm_class_slot"],
            }
            for item in serializable_extensions
        ],
        "mutating_operations": [],
        "runtime_required": True,
    }
    artifacts = (
        NiagaraAlarmArtifact("niagara-alarm-plan.json", canonical_json(plan)),
        NiagaraAlarmArtifact(
            f"{_installer_class_name(graph.name)}.java",
            java,
        ),
        NiagaraAlarmArtifact("niagara-alarm-readback.json", canonical_json(readback)),
    )
    manifest = {
        "schema": "bactalk.niagara-alarm-export/v1",
        "alarm_count": len(extensions),
        "source_extension_plan_compiled": bool(extensions),
        "java_source_emitted": True,
        "bog_extension_emitted": False,
        "alarm_class_policy_compiled": False,
        "licensed_runtime_qualified": False,
        "artifacts": [
            {
                "path": item.relative_path,
                "bytes": len(item.content.encode("utf-8")),
                "sha256": hashlib.sha256(item.content.encode("utf-8")).hexdigest(),
            }
            for item in artifacts
        ],
        "runtime_gate": (
            "Compile against the exact licensed Niagara SDK, bind shop AlarmService class "
            "policy, test transitions/acknowledgement/routing in a disposable station, and "
            "capture the readback before target qualification."
        ),
    }
    return NiagaraAlarmExport(artifacts=artifacts, manifest=manifest)
