"""N2 contract: the lowering matrix, its policy, and the generated document."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bactalk.compiler import NiagaraCompiler
from bactalk.demo import standard_ahu_demo_job, standard_vav_demo_job
from bactalk.domain import Block, BlockKind, ControlGraph, Link
from bactalk.library_demo import lbnl_multizone_ahu_demo_job, lbnl_vav_reheat_demo_job
from bactalk.niagara.catalog import load_catalog
from bactalk.niagara.lowering import (
    LOWERING_MATRIX,
    MATRIX_DOC,
    MODULE_NAME,
    TRUE_DELAY_MODULE,
    LoweringClass,
    LoweringPolicy,
    classify,
    classify_block,
    plan_lowering,
    render_matrix_markdown,
)
from bactalk.repository import RunRepository
from bactalk.service import WorkbenchService

pytestmark = [pytest.mark.minimal, pytest.mark.native_bog]


def test_every_block_kind_has_exactly_one_decision() -> None:
    assert set(LOWERING_MATRIX) == set(BlockKind)
    for kind in BlockKind:
        decision = classify(kind)
        assert decision.kind is kind
        if decision.lowering is LoweringClass.UNSUPPORTED:
            assert decision.target == "" and decision.note
        else:
            assert decision.target, kind


def test_stock_targets_and_slots_exist_in_the_catalog() -> None:
    catalog = load_catalog()
    for decision in LOWERING_MATRIX.values():
        if decision.lowering not in {LoweringClass.STOCK_EXACT, LoweringClass.STOCK_WITHIN_BANDS}:
            continue
        if decision.composite:
            continue
        spec = catalog.get(decision.target)
        assert spec is not None, decision.target
        for ir_slot, niagara_slot in decision.slot_map.items():
            assert niagara_slot in spec.slots, f"{decision.kind.value}.{ir_slot} -> {niagara_slot}"


def test_stock_slot_maps_agree_with_the_compiler() -> None:
    """Until N4 unifies them, the compiler's table and the matrix must not drift."""

    for kind, slots in NiagaraCompiler.SLOT_NAMES.items():
        decision = classify(kind)
        assert decision.lowering is not LoweringClass.MODULE, kind
        assert dict(decision.slot_map) == slots, kind


def test_within_bands_rows_document_their_deviation_and_scenarios() -> None:
    for decision in LOWERING_MATRIX.values():
        if decision.lowering is LoweringClass.STOCK_WITHIN_BANDS:
            assert decision.deviation, decision.kind
            assert len(decision.bounding_scenarios) >= 2, decision.kind
        else:
            assert not decision.deviation and not decision.bounding_scenarios, decision.kind


def test_module_rows_name_bactalk_g36_components() -> None:
    module_rows = [d for d in LOWERING_MATRIX.values() if d.lowering is LoweringClass.MODULE]
    assert module_rows
    for decision in module_rows:
        assert decision.target.startswith(f"{MODULE_NAME}:"), decision.kind
    expected = {
        "TrueFalseHold",
        "Timer",
        "TimerWithReset",
        "TimerAccumulating",
        "MovingAverage",
        "TrimAndRespond",
        "TrimAndRespondHold",
        "PIDWithReset",
    }
    assert expected <= {d.target.split(":")[1] for d in module_rows}


def test_boolean_delay_is_configuration_dependent() -> None:
    stock = Block(id="d1", kind=BlockKind.BOOLEAN_DELAY, label="d", config={"on_delay_seconds": 5})
    assert classify_block(stock).lowering is LoweringClass.STOCK_WITHIN_BANDS
    cdl = Block(
        id="d2",
        kind=BlockKind.BOOLEAN_DELAY,
        label="d",
        config={"on_delay_seconds": 5, "delay_on_init": False},
    )
    assert classify_block(cdl) is TRUE_DELAY_MODULE
    assert TRUE_DELAY_MODULE.target == f"{MODULE_NAME}:TrueDelay"


@pytest.mark.parametrize("build", [standard_vav_demo_job, standard_ahu_demo_job])
def test_pack_demos_are_native_stock(build) -> None:
    from bactalk.agent import SequencePackPlanner

    plan = plan_lowering(SequencePackPlanner().plan(build()))
    assert plan.lane == "native_stock", plan.blockers
    assert plan.counts["MODULE"] == 0 and plan.counts["UNSUPPORTED"] == 0


@pytest.mark.parametrize("build", [lbnl_vav_reheat_demo_job, lbnl_multizone_ahu_demo_job])
def test_tier_one_controllers_have_no_unsupported_kind(build) -> None:
    """N2 exit: no UNSUPPORTED entries for a Tier 1 configuration."""

    job = build()
    assert job.control_graph is not None
    plan = plan_lowering(job.control_graph)
    assert plan.unsupported == ()
    assert plan.lane == "native_with_module", plan.blockers
    assert plan.module_types, "Tier 1 needs bactalkG36 components (N3)"
    assert all(name.startswith(f"{MODULE_NAME}:") for name in plan.module_types)


def test_plant_kinds_block_the_native_lane_unless_expert() -> None:
    # Plant blocks validate their pinned contract on construction; the matrix
    # only reads kind and config, so build the graph without validation.
    graph = ControlGraph.model_construct(
        name="PLANT",
        blocks=[
            Block(id="en", kind=BlockKind.BOOLEAN_INPUT, label="en", config={"default": True}),
            Block.model_construct(
                id="stage", kind=BlockKind.PLANT_STAGE_INDEX, label="stage", config={}
            ),
        ],
        links=[],
    )
    plan = plan_lowering(graph)
    assert plan.lane == "blocked"
    assert plan.unsupported == (("stage", BlockKind.PLANT_STAGE_INDEX),)
    assert "plant_stage_index" in plan.blockers[0]
    expert = plan_lowering(graph, LoweringPolicy(expert_program_objects=True))
    assert expert.lane == "program_objects" and expert.blockers == ()


def test_plan_serialises() -> None:
    graph = ControlGraph(
        name="TINY",
        blocks=[
            Block(id="a", kind=BlockKind.NUMERIC_INPUT, label="a", config={"default": 1.0}),
            Block(id="o", kind=BlockKind.NUMERIC_OUTPUT, label="o"),
        ],
        links=[Link(source="a", target="o", target_slot="in")],
    )
    payload = json.loads(json.dumps(plan_lowering(graph).to_dict()))
    assert payload["lane"] == "native_stock"
    assert payload["blocks"]["o"]["target"] == "control:NumericWritable"


def test_service_records_the_lowering_plan(tmp_path: Path) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    record = service.create_run(lbnl_vav_reheat_demo_job())
    plan_path = Path(record.program_package_path or record.bog_path or "").with_name(
        "niagara-lowering.json"
    )
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    assert payload["lane"] == "native_with_module"
    assert payload["unsupported"] == []


def test_matrix_document_is_current() -> None:
    assert MATRIX_DOC.read_text(encoding="utf-8") == render_matrix_markdown()
