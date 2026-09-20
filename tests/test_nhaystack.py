from __future__ import annotations

import json

from phable.io.ph_zinc import ph_from_zinc

from bactalk.agent import SequencePackPlanner
from bactalk.demo import demo_job
from bactalk.integrations.nhaystack import build_readonly_nhaystack_export


def test_nhaystack_export_round_trips_every_compiled_point_without_write_capability() -> None:
    job = demo_job()
    graph = SequencePackPlanner().plan(job)

    export = build_readonly_nhaystack_export(job, graph)

    artifacts = {item.relative_path: item.content for item in export.artifacts}
    grid = ph_from_zinc(artifacts["expected-readback.zinc"])
    point_rows = [row for row in grid.rows if "point" in row]
    assert len(grid.rows) == len(job.points) + 2
    assert len(point_rows) == len(job.points)
    assert all("cur" in row for row in point_rows)
    assert all("write" not in row and "writeVal" not in row for row in grid.rows)
    by_path = {str(row["n4SlotPath"]): row for row in point_rows}
    root = "slot:/Config/Drivers/BACnetNetwork/ExampleCampus/VAV_12"
    assert "his" in by_path[f"{root}/ZoneTemp"]
    assert "his" not in by_path[f"{root}/DamperCommand"]
    assert str(by_path[f"{root}/ZoneTemp"]["unit"]) == "°F"

    verification = json.loads(artifacts["verification.json"])
    assert verification["filter"] == "point and equipRef"
    assert len(verification["expected_points"]) == len(job.points)
    assert export.manifest["writes_enabled"] is False
    assert export.manifest["historized_point_count"] == 1
    assert export.manifest["tag_annotation_count"] == len(job.points) + 2
    assert export.manifest["existing_tag_overwrite_allowed"] is False

    installer = next(
        content for path, content in artifacts.items() if path.endswith(".java")
    )
    assert "BHDict.make(zinc)" in installer
    assert "Existing haystack tags differ" in installer
    assert "component.set(" not in installer
    assert "siteRef:@C.Config.Sites.ExampleCampus" in installer
    assert "equipRef:@C.Config.Drivers.BACnetNetwork.ExampleCampus.VAV_12" in installer


def test_nhaystack_export_has_human_and_runtime_gates() -> None:
    job = demo_job()
    graph = SequencePackPlanner().plan(job)

    export = build_readonly_nhaystack_export(job, graph)
    install = json.loads(
        next(item.content for item in export.artifacts if item.relative_path == "install-plan.json")
    )

    assert install["module_distribution_included"] is False
    assert install["module_source"]["license"] == "AFL-3.0"
    assert any("deny commands" in item for item in install["required_safety_controls"])
    assert "licensed Niagara runtime" in export.manifest["runtime_gate"]


def test_nhaystack_export_omits_site_reference_when_no_exact_site_ord_exists() -> None:
    job = demo_job()
    assert job.deliverables.shop_profile is not None
    job.deliverables.shop_profile.niagara_site_ord = None
    graph = SequencePackPlanner().plan(job)

    export = build_readonly_nhaystack_export(job, graph)
    grid = ph_from_zinc(
        next(
            item.content
            for item in export.artifacts
            if item.relative_path == "expected-readback.zinc"
        )
    )

    assert len(grid.rows) == len(job.points) + 1
    assert all("siteRef" not in row for row in grid.rows)
    assert export.manifest["site_ord"] is None
    assert export.manifest["tag_annotation_count"] == len(job.points) + 1
