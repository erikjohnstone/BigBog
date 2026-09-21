"""N4 contract: the native ``.bog`` emitter, its layout, previews and lane wiring."""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

import pytest

from bactalk.domain import Block, BlockKind, ControlGraph, Link
from bactalk.library_demo import lbnl_multizone_ahu_demo_job, lbnl_vav_reheat_demo_job
from bactalk.niagara.emit import (
    INPUTS_FOLDER,
    OUTPUTS_FOLDER,
    EmitError,
    EmitOptions,
    emit_bog,
)
from bactalk.niagara.layout import Placement, layout_folder, overlaps
from bactalk.niagara.module import declared_types
from bactalk.niagara.preview import render_previews
from bactalk.niagara.validate import validate_bog
from bactalk.repository import RunRepository
from bactalk.service import WorkbenchService

pytestmark = [pytest.mark.minimal, pytest.mark.native_bog]

TIER_ONE = [lbnl_vav_reheat_demo_job, lbnl_multizone_ahu_demo_job]


def _xml(content: bytes) -> ElementTree.Element:
    with zipfile.ZipFile(BytesIO(content)) as archive:
        return ElementTree.fromstring(archive.read("file.xml"))


@pytest.mark.parametrize("build", TIER_ONE)
def test_tier_one_exports_one_bog_that_passes_the_validator(build) -> None:
    job = build()
    result = emit_bog(job.control_graph, points=job.points)
    report = validate_bog(result.content, declared_types=declared_types(), label=job.equipment_name)
    assert report.ok, [str(issue) for issue in report.errors]
    assert not report.warnings, [str(issue) for issue in report.warnings]
    assert result.plan.lane == "native_with_module"
    # Without the module declared the same file is rejected on its bactalkG36 types.
    assert "type.known" in validate_bog(result.content).rules("error")


@pytest.mark.parametrize("build", TIER_ONE)
def test_output_is_byte_identical_for_identical_input(build) -> None:
    job = build()
    first = emit_bog(job.control_graph, points=job.points).content
    second = emit_bog(job.control_graph, points=job.points).content
    assert first == second


@pytest.mark.parametrize("build", TIER_ONE)
def test_folders_follow_the_cdl_composites_and_stay_readable(build) -> None:
    job = build()
    report = emit_bog(job.control_graph, points=job.points).report
    paths = [folder.path for folder in report.folders]
    assert paths[0] == INPUTS_FOLDER and paths[-1] == OUTPUTS_FOLDER
    assert len(paths) > 4, "composites became folders"
    assert "Logic" not in paths, "origins were recorded, so no anonymous Logic folder"
    for folder in report.folders:
        assert len(folder.components) <= EmitOptions().max_blocks_per_folder, folder.path
        names = [name for name, *_ in folder.components]
        assert len(names) == len(set(names)), folder.path
        assert all(name.isidentifier() for name in names), folder.path
        placements = [Placement(n, 0, 0, x, y, w) for n, _, x, y, w in folder.components]
        assert overlaps(placements) == [], folder.path
    assert report.link_count >= len(job.control_graph.links)


@pytest.mark.parametrize("build", TIER_ONE)
def test_every_ir_link_is_a_resolved_niagara_link(build) -> None:
    job = build()
    root = _xml(emit_bog(job.control_graph, points=job.points).content)
    handles = {element.get("h") for element in root.iter("p") if element.get("h")}
    links = [element for element in root.iter("p") if element.get("t") == "b:Link"]
    assert len(links) >= len(job.control_graph.links)
    for link in links:
        fields = {child.get("n"): child.get("v") for child in link}
        assert fields["sourceOrd"].startswith("h:")
        assert fields["sourceOrd"][2:] in handles
        assert fields["sourceSlotName"] and fields["targetSlotName"]


def test_points_carry_units_and_module_blocks_carry_parameters() -> None:
    job = lbnl_vav_reheat_demo_job()
    root = _xml(emit_bog(job.control_graph, points=job.points).content)
    facets = {
        element.get("n"): child.get("v")
        for element in root.iter("p")
        if element.get("t") == "c:NumericWritable"
        for child in element
        if child.get("n") == "facets"
    }
    assert facets["TZon"].startswith("units=u:kelvin;")
    assert facets["VDis_flow"].startswith("units=u:cubic meters per second;")
    modules = [
        element for element in root.iter("p") if (element.get("t") or "").startswith("bactalkG36:")
    ]
    assert modules, "the VAV reheat controller needs bactalkG36 components"
    delays = [m for m in modules if m.get("t") == "bactalkG36:TrueDelay"]
    assert delays
    props = {child.get("n"): (child.get("t"), child.get("v")) for child in delays[0]}
    assert props["delayTime"][0] == "b:RelTime" and props["delayTime"][1].isdigit()
    assert props["delayOnInit"] == ("b:Boolean", "false")


def test_composites_expand_per_the_matrix() -> None:
    graph = ControlGraph(
        name="COMPOSITES",
        blocks=[
            Block(id="s", kind=BlockKind.BOOLEAN_INPUT, label="set", config={"default": False}),
            Block(id="c", kind=BlockKind.BOOLEAN_INPUT, label="clear", config={"default": False}),
            Block(id="v", kind=BlockKind.NUMERIC_INPUT, label="value", config={"default": 1.0}),
            Block(id="latch", kind=BlockKind.BOOLEAN_SET_RESET, label="latch"),
            Block(id="fall", kind=BlockKind.BOOLEAN_FALLING_EDGE, label="fall"),
            Block(
                id="samp",
                kind=BlockKind.NUMERIC_SAMPLER,
                label="samp",
                config={"sample_period_seconds": 120.0},
            ),
            Block(
                id="hys",
                kind=BlockKind.HYSTERESIS,
                label="hys",
                config={"u_low": 1.0, "u_high": 3.0},
            ),
            Block(id="o1", kind=BlockKind.BOOLEAN_OUTPUT, label="o1"),
            Block(id="o2", kind=BlockKind.BOOLEAN_OUTPUT, label="o2"),
            Block(id="o3", kind=BlockKind.NUMERIC_OUTPUT, label="o3"),
            Block(id="o4", kind=BlockKind.BOOLEAN_OUTPUT, label="o4"),
        ],
        links=[
            Link(source="s", target="latch", target_slot="set"),
            Link(source="c", target="latch", target_slot="clear"),
            Link(source="s", target="fall", target_slot="in"),
            Link(source="v", target="samp", target_slot="in"),
            Link(source="v", target="hys", target_slot="in"),
            Link(source="latch", target="o1", target_slot="in"),
            Link(source="fall", target="o2", target_slot="in"),
            Link(source="samp", target="o3", target_slot="in"),
            Link(source="hys", target="o4", target_slot="in"),
        ],
    )
    result = emit_bog(graph)
    assert result.plan.lane == "native_stock"
    root = _xml(result.content)
    types = sorted(element.get("t") for element in root.iter("p") if element.get("h"))
    assert types.count("kitControl:OneShot") == 2  # set pulse + falling edge
    assert "kitControl:MultiVibrator" in types and "kitControl:NumericLatch" in types
    assert "kitControl:Tstat" in types
    tstat = next(e for e in root.iter("p") if e.get("t") == "kitControl:Tstat")
    values = {
        child.get("n"): next(v.get("v") for v in child if v.get("n") == "value")
        for child in tstat
        if child.get("n") in {"sp", "diff"}
    }
    assert values == {"sp": "2.0", "diff": "2.0"}
    report = validate_bog(result.content)
    assert report.ok, [str(issue) for issue in report.errors]


def test_blocked_graphs_are_refused_not_emitted() -> None:
    graph = ControlGraph.model_construct(
        name="PLANT",
        blocks=[
            Block.model_construct(
                id="stage", kind=BlockKind.PLANT_STAGE_INDEX, label="stage", config={}
            )
        ],
        links=[],
    )
    with pytest.raises(EmitError, match="plant_stage_index"):
        emit_bog(graph)


def test_layout_is_layered_left_to_right_and_deterministic() -> None:
    nodes = ["c", "a", "b", "d"]
    edges = [("a", "b"), ("b", "c"), ("a", "d"), ("d", "c")]
    first = layout_folder(nodes, edges)
    second = layout_folder(list(reversed(nodes)), list(reversed(edges)))
    assert {n: (p.layer, p.row) for n, p in first.items()} == {
        n: (p.layer, p.row) for n, p in second.items()
    }
    assert first["a"].layer == 0 and first["c"].layer == 2
    assert first["a"].x < first["b"].x < first["c"].x
    assert overlaps(first.values()) == []


def test_previews_are_deterministic_svgs_per_folder() -> None:
    job = lbnl_vav_reheat_demo_job()
    report = emit_bog(job.control_graph, points=job.points).report
    previews = render_previews(report)
    assert set(previews) == {folder.path for folder in report.folders}
    for path, svg in previews.items():
        assert svg.startswith("<svg ") and svg.rstrip().endswith("</svg>")
        assert f"<title>{path}</title>" in svg
    assert previews == render_previews(emit_bog(job.control_graph, points=job.points).report)


def test_service_takes_the_native_lane_for_the_lbnl_demo(tmp_path: Path) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    record = service.create_run(lbnl_vav_reheat_demo_job())
    assert record.status.value == "ready_for_review"
    assert record.target_artifact_kind.value == "niagara_bog"
    assert record.program_package_path is None
    assert record.bog_path is not None and Path(record.bog_path).is_file()
    run_dir = Path(record.bog_path).parent
    validation = json.loads((run_dir / "niagara-validation.json").read_text("utf-8"))
    assert validation["ok"] is True
    lowering = json.loads((run_dir / "niagara-lowering.json").read_text("utf-8"))
    assert lowering["lane"] == "native_with_module"
    emit = json.loads((run_dir / "niagara-emit.json").read_text("utf-8"))
    assert emit["component_count"] > 400
    previews = sorted(path.name for path in (run_dir / "previews").glob("*.svg"))
    assert "Inputs.svg" in previews and "Outputs.svg" in previews


def test_service_refuses_a_blocked_graph_without_the_expert_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A blocked lane is refused with its blockers; only the expert flag opens the old lane."""

    import bactalk.service as service_module
    from bactalk.niagara.lowering import LoweringPlan, LoweringPolicy

    seen: list[LoweringPolicy] = []
    real = service_module.plan_lowering

    def blocked(graph, policy=None):
        seen.append(policy)
        plan = real(graph, policy)
        if policy is not None and policy.expert_program_objects:
            return plan
        return LoweringPlan(
            decisions=plan.decisions,
            counts=plan.counts,
            module_types=plan.module_types,
            unsupported=(("stage", BlockKind.PLANT_STAGE_INDEX),),
            lane="blocked",
            blockers=("no native Niagara lowering for block kinds: plant_stage_index",),
        )

    monkeypatch.setattr(service_module, "plan_lowering", blocked)
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    with pytest.raises(ValueError, match="plant_stage_index.*expert_program_objects"):
        service.create_run(lbnl_vav_reheat_demo_job())
    assert seen and seen[0] is not None and seen[0].expert_program_objects is False


def test_expert_flag_keeps_the_program_object_lane_for_blocked_graphs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The generated-Java package is still produced, only behind the expert flag."""

    import zipfile as zipfile_module

    import bactalk.service as service_module
    from bactalk.niagara.lowering import LoweringPlan

    real = service_module.plan_lowering

    def program_objects(graph, policy=None):
        plan = real(graph, policy)
        lane = "program_objects" if policy and policy.expert_program_objects else "blocked"
        return LoweringPlan(
            decisions=plan.decisions,
            counts=plan.counts,
            module_types=plan.module_types,
            unsupported=(("stage", BlockKind.PLANT_STAGE_INDEX),),
            lane=lane,
            blockers=() if lane == "program_objects" else ("plant_stage_index",),
        )

    monkeypatch.setattr(service_module, "plan_lowering", program_objects)
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    job = lbnl_vav_reheat_demo_job()
    expert = job.model_copy(
        update={"sequence": job.sequence.model_copy(update={"expert_program_objects": True})}
    )
    record = service.create_run(expert)
    assert record.target_artifact_kind.value == "niagara_program_source_package"
    assert record.bog_path is None and record.program_package_path is not None
    with zipfile_module.ZipFile(record.program_package_path) as archive:
        assert "manifest.json" in archive.namelist()
    lowering = json.loads(
        (Path(record.program_package_path).parent / "niagara-lowering.json").read_text("utf-8")
    )
    assert lowering["lane"] == "program_objects"
