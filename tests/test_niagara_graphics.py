from __future__ import annotations

import hashlib
from xml.etree import ElementTree

import pytest

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
            "id": "graphics-contract",
            "name": "Graphics contract",
            "version": "1",
            "niagara_version": "4.14",
            "graphics_templates": [
                {
                    "id": "ExampleVavOverview",
                    "artifact": "graphics/template.px",
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "media_type": "application/vnd.tridium.px",
                }
            ],
        }
    )
    return EnvironmentPackExport(
        manifest={},
        artifacts=[EnvironmentArtifact("assets/graphics/template.px", payload)],
        descriptor=descriptor,
    )


def _job_with_two_graphic_points():
    job = demo_job()
    view = job.deliverables.graphics[0]
    view.points = ["ZoneTemp", "DamperCommand"]
    return job


def test_contractor_px_template_compiles_exact_point_ords() -> None:
    payload = b"""<Px title="{{BACTALK:VIEW_TITLE}}">
  <BoundLabel ord="{{BACTALK:POINT_ORD:ZoneTemp}}"
    text="{{BACTALK:POINT_LABEL:ZoneTemp}} {{BACTALK:POINT_UNITS:ZoneTemp}}"/>
  <BoundLabel ord="{{BACTALK:POINT_ORD:DamperCommand}}"
    text="{{BACTALK:POINT_LABEL:DamperCommand}}"/>
</Px>"""
    job = _job_with_two_graphic_points()
    graph = SequencePackPlanner().plan(job)

    export = build_niagara_graphics_export(job, graph, _environment(payload))

    assert export.manifest["all_declared_views_target_compiled"] is True
    assert export.manifest["emitted_px_count"] == 1
    generated = next(
        item.content for item in export.artifacts if item.relative_path.endswith(".px")
    )
    ElementTree.fromstring(generated)
    text = generated.decode()
    assert "{{BACTALK:" not in text
    assert (
        "station:|slot:/Config/Drivers/BACnetNetwork/ExampleCampus/VAV_12/ZoneTemp"
        in text
    )
    view = export.manifest["views"][0]
    assert view["point_ord_placeholder_counts"] == {
        "ZoneTemp": 1,
        "DamperCommand": 1,
    }


def test_px_template_requires_an_ord_binding_for_every_view_point() -> None:
    payload = b'<Px><BoundLabel ord="{{BACTALK:POINT_ORD:ZoneTemp}}"/></Px>'
    job = _job_with_two_graphic_points()
    graph = SequencePackPlanner().plan(job)

    with pytest.raises(ValueError, match="has no POINT_ORD binding for: DamperCommand"):
        build_niagara_graphics_export(job, graph, _environment(payload))


@pytest.mark.parametrize(
    "payload,error",
    [
        (b'<!DOCTYPE Px [<!ENTITY x "bad">]><Px/>', "DTD or entity"),
        (b'<Px image="https://example.invalid/x.png"/>', "external or active URI"),
        (b"<Px><script>bad()</script></Px>", "script element"),
        (b'<Px ord="{{BACTALK:POINT_ORD:Unknown}}"/>', "outside the view contract"),
    ],
)
def test_px_template_rejects_unsafe_or_undeclared_content(payload: bytes, error: str) -> None:
    job = _job_with_two_graphic_points()
    graph = SequencePackPlanner().plan(job)

    with pytest.raises(ValueError, match=error):
        build_niagara_graphics_export(job, graph, _environment(payload))


def test_px_generation_stays_blocked_without_contractor_environment() -> None:
    job = _job_with_two_graphic_points()
    graph = SequencePackPlanner().plan(job)

    export = build_niagara_graphics_export(job, graph, None)

    assert export.manifest["emitted_px_count"] == 0
    assert export.manifest["all_declared_views_target_compiled"] is False
    assert [item.relative_path for item in export.artifacts] == [
        "niagara-graphics-plan.json"
    ]
