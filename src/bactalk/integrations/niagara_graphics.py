from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree

from bactalk.domain import ControlGraph, JobSpec, canonical_json
from bactalk.integrations.environment_pack import EnvironmentPackExport
from bactalk.integrations.niagara_bindings import program_root_ord

PX_GRAPHICS_GUIDE = (
    "https://downloads.innon.com/hubfs/downloads.innon.com/Tridium%20Niagara/"
    "Niagara4/Documents/Tridium_Niagara_4_Graphics_Guide_Documents.pdf"
)

_PLACEHOLDER = re.compile(
    r"\{\{BACTALK:(?P<kind>[A-Z_]+)(?::(?P<point>[A-Za-z_][A-Za-z0-9_]*))?\}\}"
)
_FORBIDDEN_URI = re.compile(r"(?:https?://|javascript:|data:)", re.IGNORECASE)
_FORBIDDEN_XML = re.compile(br"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)


@dataclass(frozen=True)
class NiagaraGraphicsArtifact:
    relative_path: str
    content: bytes


@dataclass(frozen=True)
class NiagaraGraphicsExport:
    artifacts: tuple[NiagaraGraphicsArtifact, ...]
    manifest: dict[str, Any]


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _template_payload(
    environment: EnvironmentPackExport,
    template_id: str,
) -> tuple[bytes, str, str]:
    templates = {item.id: item for item in environment.descriptor.graphics_templates}
    template = templates.get(template_id)
    if template is None:
        raise ValueError(
            f"graphics view references undeclared environment template {template_id!r}"
        )
    if template.media_type != "application/vnd.tridium.px":
        raise ValueError(
            f"graphics template {template_id!r} is not a Niagara PX artifact"
        )
    relative_path = f"assets/{template.artifact}"
    artifacts = {item.relative_path: item.content for item in environment.artifacts}
    payload = artifacts.get(relative_path)
    if payload is None:
        raise ValueError(f"graphics template bytes are missing for {template_id!r}")
    return payload, relative_path, template.sha256


def _render_px(
    payload: bytes,
    *,
    job: JobSpec,
    graph: ControlGraph,
    view_id: str,
    view_title: str,
    point_names: list[str],
) -> tuple[bytes, dict[str, Any]]:
    if _FORBIDDEN_XML.search(payload):
        raise ValueError(f"graphics template {view_id!r} contains a DTD or entity declaration")
    try:
        source = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"graphics template {view_id!r} must be UTF-8 XML") from exc
    if _FORBIDDEN_URI.search(source):
        raise ValueError(f"graphics template {view_id!r} contains an external or active URI")
    try:
        root = ElementTree.fromstring(source)
    except ElementTree.ParseError as exc:
        raise ValueError(f"graphics template {view_id!r} is not well-formed XML") from exc

    points = {item.name: item for item in job.points}
    requested = set(point_names)
    if missing := sorted(requested - points.keys()):
        raise ValueError(
            f"graphics view {view_id!r} references unknown points: {', '.join(missing)}"
        )
    root_ord = program_root_ord(job, graph)
    replacements = {
        "EQUIPMENT_NAME": job.equipment_name,
        "VIEW_TITLE": view_title,
    }
    point_ord_counts = {name: 0 for name in point_names}
    replacement_counts: dict[str, int] = {}

    def replace(value: str) -> str:
        def one(match: re.Match[str]) -> str:
            kind = match.group("kind")
            point_name = match.group("point")
            key = kind if point_name is None else f"{kind}:{point_name}"
            if kind in replacements and point_name is None:
                replacement = replacements[kind]
            elif kind in {"POINT_ORD", "POINT_LABEL", "POINT_UNITS"} and point_name:
                if point_name not in requested:
                    raise ValueError(
                        f"graphics template {view_id!r} references point {point_name!r} "
                        "outside the view contract"
                    )
                point = points[point_name]
                if kind == "POINT_ORD":
                    replacement = f"{root_ord}/{point_name}"
                    point_ord_counts[point_name] += 1
                elif kind == "POINT_LABEL":
                    replacement = point.label
                else:
                    replacement = point.units or ""
            else:
                raise ValueError(
                    f"graphics template {view_id!r} contains unsupported placeholder {key!r}"
                )
            replacement_counts[key] = replacement_counts.get(key, 0) + 1
            return replacement

        return _PLACEHOLDER.sub(one, value)

    for element in root.iter():
        if isinstance(element.tag, str) and element.tag.lower().endswith("script"):
            raise ValueError(f"graphics template {view_id!r} contains a script element")
        if element.text:
            element.text = replace(element.text)
        if element.tail:
            element.tail = replace(element.tail)
        for name, value in list(element.attrib.items()):
            element.set(name, replace(value))

    if unresolved := sorted(name for name, count in point_ord_counts.items() if count == 0):
        raise ValueError(
            f"graphics template {view_id!r} has no POINT_ORD binding for: "
            + ", ".join(unresolved)
        )
    rendered = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
    if _PLACEHOLDER.search(rendered.decode("utf-8")):
        raise ValueError(f"graphics template {view_id!r} contains unresolved placeholders")
    ElementTree.fromstring(rendered)
    return rendered, {
        "program_root_ord": root_ord,
        "point_ords": {name: f"{root_ord}/{name}" for name in point_names},
        "point_ord_placeholder_counts": point_ord_counts,
        "replacement_counts": dict(sorted(replacement_counts.items())),
    }


def build_niagara_graphics_export(
    job: JobSpec,
    graph: ControlGraph,
    environment: EnvironmentPackExport | None,
) -> NiagaraGraphicsExport:
    """Compile contractor PX templates without executing Niagara or template content."""

    artifacts: list[NiagaraGraphicsArtifact] = []
    views: list[dict[str, Any]] = []
    for view in job.deliverables.graphics:
        if view.template is None:
            views.append(
                {
                    "id": view.id,
                    "status": "blocked",
                    "reason": "No contractor PX template id was declared.",
                    "points": view.points,
                }
            )
            continue
        if environment is None:
            views.append(
                {
                    "id": view.id,
                    "template": view.template,
                    "status": "blocked",
                    "reason": "The referenced contractor environment pack was not supplied.",
                    "points": view.points,
                }
            )
            continue
        payload, source_path, source_hash = _template_payload(environment, view.template)
        rendered, bindings = _render_px(
            payload,
            job=job,
            graph=graph,
            view_id=view.id,
            view_title=view.title,
            point_names=view.points,
        )
        output_path = f"niagara-graphics/{view.id}.px"
        artifacts.append(NiagaraGraphicsArtifact(output_path, rendered))
        views.append(
            {
                "id": view.id,
                "title": view.title,
                "template": view.template,
                "source_path": source_path,
                "source_sha256": source_hash,
                "output_path": output_path,
                "output_sha256": _sha256(rendered),
                "status": "target-compiled",
                "navigation_parent": view.navigation_parent,
                **bindings,
            }
        )

    emitted = sum(item["status"] == "target-compiled" for item in views)
    manifest = {
        "schema": "bactalk.niagara-px-export/v1",
        "equipment_name": job.equipment_name,
        "views": views,
        "declared_view_count": len(job.deliverables.graphics),
        "emitted_px_count": emitted,
        "all_declared_views_target_compiled": bool(views) and emitted == len(views),
        "source_reference": {
            "name": "Tridium Niagara 4 Graphics Guide",
            "url": PX_GRAPHICS_GUIDE,
            "contract": "PX XML with component value bindings addressed by ORD",
        },
        "safety": {
            "template_content_executed_by_bactalk": False,
            "xml_dtd_and_entities_allowed": False,
            "script_elements_allowed": False,
            "external_or_active_uris_allowed": False,
            "undeclared_point_bindings_allowed": False,
            "unbound_declared_points_allowed": False,
            "licensed_runtime_qualified": False,
        },
        "runtime_gate": (
            "Generated PX is well-formed, hash-bound, and complete against its placeholder "
            "contract. It still requires import/render/navigation/value-readback testing in "
            "the exact licensed Niagara version and module environment."
        ),
    }
    plan = canonical_json(manifest).encode("utf-8")
    return NiagaraGraphicsExport(
        artifacts=(NiagaraGraphicsArtifact("niagara-graphics-plan.json", plan), *artifacts),
        manifest=manifest,
    )
