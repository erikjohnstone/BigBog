from __future__ import annotations

import hashlib
import json
from xml.etree import ElementTree

from bactalk.agent import SequencePackPlanner
from bactalk.demo import demo_job
from bactalk.integrations.environment_pack import (
    EnvironmentArtifact,
    EnvironmentPackExport,
    EnvironmentPackManifest,
)
from bactalk.integrations.niagara_graphics import build_niagara_graphics_export


def _environment(payload: bytes) -> EnvironmentPackExport:
    descriptor = EnvironmentPackManifest.model_validate(
        {
            "id": "px-contract",
            "name": "PX contract",
            "version": "1",
            "niagara_version": "4.14",
            "graphics_templates": [
                {
                    "id": "ExampleVavOverview",
                    "artifact": "graphics/vav.px",
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "media_type": "application/vnd.tridium.px",
                }
            ],
        }
    )
    return EnvironmentPackExport(
        manifest={},
        artifacts=[EnvironmentArtifact("assets/graphics/vav.px", payload)],
        descriptor=descriptor,
    )


def main() -> int:
    job = demo_job()
    graph = SequencePackPlanner().plan(job)
    labels = "".join(
        (
            f'<BoundLabel ord="{{{{BACTALK:POINT_ORD:{point.name}}}}}" '
            f'text="{{{{BACTALK:POINT_LABEL:{point.name}}}}}"/>'
        )
        for point in job.points
    )
    source = (
        '<Px title="{{BACTALK:VIEW_TITLE}}" '
        'equipment="{{BACTALK:EQUIPMENT_NAME}}">'
        + labels
        + "</Px>"
    ).encode()
    export = build_niagara_graphics_export(job, graph, _environment(source))
    generated = next(
        item.content for item in export.artifacts if item.relative_path.endswith(".px")
    )
    ElementTree.fromstring(generated)
    if b"{{BACTALK:" in generated:
        raise RuntimeError("generated PX retained a placeholder")
    view = export.manifest["views"][0]
    if any(count < 1 for count in view["point_ord_placeholder_counts"].values()):
        raise RuntimeError("generated PX omitted a declared point binding")

    unsafe_refused = False
    try:
        build_niagara_graphics_export(
            job,
            graph,
            _environment(b'<Px image="https://example.invalid/remote.png"/>'),
        )
    except ValueError as exc:
        unsafe_refused = "external or active URI" in str(exc)
    if not unsafe_refused:
        raise RuntimeError("external PX content was not refused")

    print(
        json.dumps(
            {
                "passed": True,
                "declared_views": export.manifest["declared_view_count"],
                "emitted_px": export.manifest["emitted_px_count"],
                "exact_point_bindings": len(view["point_ords"]),
                "well_formed_xml": True,
                "unresolved_placeholders": 0,
                "external_content_refused": True,
                "template_content_executed_by_bactalk": False,
                "licensed_runtime_qualified": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
