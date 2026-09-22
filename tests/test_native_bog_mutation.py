"""N7 (D4): deliberately broken .bog files are caught, and survivors are listed."""

from __future__ import annotations

import pytest

from bactalk.library_demo import (
    lbnl_multizone_ahu_demo_job,
    lbnl_vav_reheat_demo_job,
    reference_trace,
)
from bactalk.niagara.emit import emit_bog
from bactalk.niagara.mutate import (
    OPERATORS,
    generate_mutants,
    judge_mutant,
    run_mutation_suite,
)

pytestmark = [pytest.mark.native_bog]

SEED = 7
SAMPLE = 12
# Measured floors (artifacts/native-bog/d4-tier1.json, decision 009): the AHU suite
# meets the 95 % target; the VAV reheat suite does not yet, and N8 must raise it.
FLOORS = {"AHU_1": 0.95, "VAV_21": 0.55}


def test_every_operator_produces_mutants_for_the_vav_export() -> None:
    job = lbnl_vav_reheat_demo_job()
    content = emit_bog(job.control_graph, points=job.points).content
    mutants = generate_mutants(content, seed=SEED)
    assert len(mutants) > 1000
    assert {m.mutation.operator for m in mutants} == set(OPERATORS)
    assert len({m.mutation.path + m.mutation.detail for m in mutants}) == len(mutants)
    assert generate_mutants(content, seed=SEED, limit=5)[0].mutation == mutants[0].mutation


def test_a_deleted_output_link_is_caught_before_the_differential() -> None:
    job = lbnl_vav_reheat_demo_job()
    content = emit_bog(job.control_graph, points=job.points).content
    mutant = next(
        m
        for m in generate_mutants(content, seed=SEED, operators=("delete_link",))
        if m.mutation.path.endswith("/Outputs/yDam/Link")
    )
    caught_by, detail = judge_mutant(mutant.content, job.acceptance_tests)
    assert caught_by == "suite", detail
    assert "yDam" in detail


@pytest.mark.parametrize("build", [lbnl_vav_reheat_demo_job, lbnl_multizone_ahu_demo_job])
def test_seeded_sample_meets_the_recorded_floor_and_lists_survivors(build) -> None:
    job = build()
    content = emit_bog(job.control_graph, points=job.points).content
    report = run_mutation_suite(
        content,
        job.acceptance_tests,
        seed=SEED,
        limit=SAMPLE,
        job=job,
        reference=reference_trace(job.sequence.controller_id),
    )
    summary = report.to_dict()
    assert summary["total"] == SAMPLE
    assert set(summary["by_catcher"]) <= {
        "validator",
        "loader",
        "suite",
        "differential",
        "survived",
    }
    assert summary["catch_rate"] >= FLOORS[job.equipment_name], summary
    for survivor in summary["survivors"]:
        assert survivor["caught_by"] is None
        assert survivor["path"].startswith("/Controller/")
    assert len(summary["survivors"]) == summary["total"] - summary["caught"]
