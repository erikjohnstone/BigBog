"""The demo candidates are LBNL-sourced (GOAL-NATIVE-BOG.md, N0).

Base-install tests build both demo jobs from the retained translations. The
integration-tier test re-translates the pinned LBNL source and fails if the retained
copy has drifted, so "retained" never quietly becomes "stale".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bactalk.library_demo import (
    RETAINED,
    lbnl_multizone_ahu_demo_job,
    lbnl_vav_reheat_demo_job,
    retained_translation,
)
from bactalk.repository import RunRepository
from bactalk.service import WorkbenchService
from bactalk.simulator import run_acceptance_suite


@pytest.mark.minimal
@pytest.mark.native_bog
@pytest.mark.parametrize("build", [lbnl_vav_reheat_demo_job, lbnl_multizone_ahu_demo_job])
def test_demo_candidates_are_retained_lbnl_translations(build) -> None:
    job = build()
    assert job.sequence.family == "LBNL_G36_CONTROLLER"
    assert job.sequence.library == "g36"
    assert job.control_graph is not None
    retained = retained_translation(job.sequence.controller_id)
    assert retained["schema"] == "bactalk.retained-library-translation/v1"
    assert retained["source"]["tag"] == "v13.0.0"
    assert len(retained["source"]["revision"]) == 40
    assert len(retained["source"]["source_sha256"]) == 64
    assert len(retained["translator"]["cxf_source_sha256"]) == 64
    assert retained["source"]["revision"][:12] in job.sequence.version
    # Every interface port is a job point and a graph boundary block.
    port_names = {point["name"] for point in retained["points"]}
    assert {point.name for point in job.points} == port_names
    boundary = {
        block.id
        for block in job.control_graph.blocks
        if block.kind.value.endswith(("_input", "_output"))
    }
    assert port_names <= boundary
    # SI units travel with the points, honestly.
    units = {point.name: point.units for point in job.points}
    assert units["TZon" if "TZon" in units else "TAirSup"] == "K"


@pytest.mark.minimal
@pytest.mark.native_bog
@pytest.mark.parametrize("build", [lbnl_vav_reheat_demo_job, lbnl_multizone_ahu_demo_job])
def test_demo_candidates_pass_their_cited_acceptance_tests(build) -> None:
    job = build()
    report = run_acceptance_suite(job.control_graph, job)
    failures = [
        (scenario.name, assertion.name, assertion.observed, assertion.expected)
        for scenario in report.scenarios
        for assertion in scenario.assertions
        if not assertion.passed
    ]
    assert report.passed, failures
    observed = {
        expectation.target for case in job.acceptance_tests for expectation in case.expectations
    }
    outputs = {
        block.id for block in job.control_graph.blocks if block.kind.value.endswith("_output")
    }
    assert outputs <= observed, sorted(outputs - observed)


@pytest.mark.minimal
@pytest.mark.native_bog
def test_demo_builds_on_a_base_install_without_the_translation_toolchain(tmp_path: Path) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    record = service.create_run(lbnl_vav_reheat_demo_job())
    assert record.status.value == "ready_for_review"
    # Until N4 the honest artifact for an LBNL controller is the ProgramObject package.
    assert record.target_artifact_kind.value == "niagara_program_source_package"
    assert record.program_package_path is not None
    assert Path(record.program_package_path).is_file()
    assert record.bog_path is None


@pytest.mark.integration
@pytest.mark.native_bog
@pytest.mark.parametrize("controller_id", sorted(RETAINED))
def test_retained_translations_match_the_pinned_source(controller_id: str) -> None:
    from bactalk.integrations.g36_library import G36Library

    retained = retained_translation(controller_id)
    fresh = G36Library().translate(
        controller_id,
        parameters=dict(retained["parameters"]),
        execution_profile=retained["execution_profile"],
    )
    assert fresh["controller"]["source_sha256"] == retained["source"]["source_sha256"]
    assert fresh["lowering"]["source_sha256"] == retained["translator"]["cxf_source_sha256"]
    assert json.dumps(fresh["typed_ir"], sort_keys=True) == json.dumps(
        retained["typed_ir"], sort_keys=True
    ), "retained typed IR drifted from the pinned LBNL translation; regenerate it"
