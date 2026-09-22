"""N6 exit: the Shadow Runtime runs every Tier 1 export through its acceptance suite."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import pytest

from bactalk.domain import AcceptanceCase, FaultInjection, OutputExpectation
from bactalk.library_demo import lbnl_multizone_ahu_demo_job, lbnl_vav_reheat_demo_job
from bactalk.niagara.emit import emit_bog
from bactalk.niagara.shadow import (
    ENGINE_PREFIX,
    PLAUSIBLE_POLICIES,
    ShadowDriverError,
    ShadowRunOptions,
    run_shadow_case,
    run_shadow_suite,
    run_under_policies,
)
from bactalk.niagara.shadow.__main__ import main as shadow_main
from bactalk.niagara.shadow.differential import compare_case, summarize
from bactalk.niagara.shadow.jobs import (
    RQ_FUNCTION,
    ProgramSuite,
    enqueue_project_suite,
    run_program_job,
    run_project_suite,
)
from bactalk.simulator import run_acceptance_suite

pytestmark = [pytest.mark.native_bog]

TIER_ONE = [lbnl_vav_reheat_demo_job, lbnl_multizone_ahu_demo_job]
PYTHON = ShadowRunOptions(kernel_backend="python")


@pytest.fixture(scope="module")
def exports() -> dict[str, tuple[object, bytes]]:
    result = {}
    for build in TIER_ONE:
        job = build()
        result[job.equipment_name] = (job, emit_bog(job.control_graph, points=job.points).content)
    return result


@pytest.mark.parametrize("name", ["VAV_21", "AHU_1"])
def test_tier_one_export_passes_its_acceptance_suite_in_the_shadow_runtime(
    exports, name: str
) -> None:
    """S-SAMPLE-1."""

    job, content = exports[name]
    options = ShadowRunOptions(kernel_backend="python", sequence_family=job.sequence.family)
    report = run_shadow_suite(content, job.acceptance_tests, options=options)
    assert report.passed, [
        (s.name, [a for a in s.assertions if not a.passed])
        for s in report.scenarios
        if not s.passed
    ]
    assert report.engine.startswith(ENGINE_PREFIX) and "kernels python" in report.engine
    assert [s.name for s in report.scenarios] == [c.name for c in job.acceptance_tests]
    shadow = report.coverage["shadow"]
    assert shadow["component_count"] > 400 and shadow["kernel_backend"] == "python"
    assert shadow["scan_count"] == sum(
        sum(p.repeat for p in c.timeline) if c.timeline else c.repeat for c in job.acceptance_tests
    )
    # The IR suite grades the same cases the same way.
    reference = run_acceptance_suite(job.control_graph, job)
    assert [s.passed for s in reference.scenarios] == [s.passed for s in report.scenarios]
    # Sample shape: the keys the web trace builder reads, plus every internal slot.
    sample = report.scenarios[0].samples[0]
    assert sample["step"] == 1.0 and sample["time_seconds"] == job.acceptance_tests[0].step_seconds
    for point in job.points:
        assert point.name in sample, point.name
    for expectation in (
        job.acceptance_tests[0].expectations or job.acceptance_tests[0].timeline[-1].expectations
    ):
        assert expectation.target in sample
    assert any("/" in key and key.endswith(".out") for key in sample), "internal slots are recorded"
    assert all(isinstance(value, (float, bool)) for value in sample.values())
    assert report.coverage["decisions"]["decision_count"] > 50
    assert report.coverage["qualification_matrix"]["schema"].startswith("bactalk")


def test_reports_name_the_first_diverging_block_against_the_interpreter(exports) -> None:
    job, content = exports["VAV_21"]
    case = job.acceptance_tests[0]
    divergences = compare_case(job, case, content=content)
    # Since N7 the edge, latch and sampler kinds are tick-semantic module components,
    # so the deadband scenario agrees block for block; a tight tolerance still
    # names the first PID whose 1 s integration leads the interpreter's scan.
    assert not [d for d in divergences if d.kind.endswith("_output")]
    tight = compare_case(job, job.acceptance_tests[1], content=content, tolerance=1e-12)
    lines = summarize(tight, limit=3)
    assert lines and "pid_with_reset" in lines[0]


def test_faults_apply_to_input_values_and_optionally_flag_status(exports) -> None:
    """S-FAULT-1."""

    job, content = exports["VAV_21"]
    base = job.acceptance_tests[0]
    inputs = dict(base.timeline[0].inputs if base.timeline else base.inputs)
    case = AcceptanceCase(
        name="stale zone temperature",
        inputs=inputs,
        expectations=[OutputExpectation(target="VSet_flow", operator="gte", value=0.0)],
        repeat=3,
        step_seconds=60.0,
        faults=[FaultInjection(id="stale_tzon", target="TZon", kind="stale")],
    )
    result, values = run_shadow_case(content, case, options=PYTHON)
    assert result.passed
    sample = result.samples[-1]
    assert (
        sample["fault.stale_tzon.active"] is True
        and sample["fault.stale_tzon.elapsed_seconds"] == 180.0
    )
    assert sample["effective.TZon"] == inputs["TZon"] and "TZon.status" not in sample
    flagged, _ = run_shadow_case(
        content, case, options=ShadowRunOptions(kernel_backend="python", inject_fault_status=True)
    )
    assert flagged.samples[-1]["TZon.status"] == 16.0, "stale bit on the input point"
    bad = case.model_copy(update={"faults": [FaultInjection(id="x", target="Nope", kind="stale")]})
    with pytest.raises(ValueError, match="not a graph input"):
        run_shadow_case(content, bad, options=PYTHON)
    wrong = case.model_copy(update={"inputs": {**inputs, "NotAPoint": 1.0}, "faults": []})
    with pytest.raises(ShadowDriverError, match="NotAPoint"):
        run_shadow_case(content, wrong, options=PYTHON)


def test_verdicts_hold_under_every_plausible_policy(exports) -> None:
    job, content = exports["VAV_21"]
    cases = job.acceptance_tests[:2]
    policies = [
        PLAUSIBLE_POLICIES[0],
        *[
            p
            for p in PLAUSIBLE_POLICIES
            if p.name in {"reverse-links", "breadth", "document-start"}
        ],
    ]
    robustness = run_under_policies(content, cases, policies=policies, options=PYTHON)
    assert list(robustness.reports) == [p.name for p in policies]
    assert robustness.verdict_dependent == []
    assert robustness.robust, robustness.to_dict()["output_disagreements"]
    payload = robustness.to_dict()
    assert payload["schema"] == "bactalk.shadow-robustness/v1" and payload["robust"] is True


def test_project_fan_out_runs_an_ahu_and_25_vavs_inside_the_budget(exports, tmp_path: Path) -> None:
    ahu_job, ahu = exports["AHU_1"]
    vav_job, vav = exports["VAV_21"]
    (tmp_path / "ahu.bog").write_bytes(ahu)
    (tmp_path / "vav.bog").write_bytes(vav)
    programs = [
        ProgramSuite(
            "AHU_1", tmp_path / "ahu.bog", tuple(ahu_job.acceptance_tests), ahu_job.sequence.family
        )
    ]
    programs += [
        ProgramSuite(
            f"VAV_{i:02d}",
            tmp_path / "vav.bog",
            tuple(vav_job.acceptance_tests),
            vav_job.sequence.family,
        )
        for i in range(1, 26)
    ]
    started = time.perf_counter()
    reports = run_project_suite(programs, kernel_backend="python")
    elapsed = time.perf_counter() - started
    assert len(reports) == 26 and all(report.passed for report in reports.values())
    assert elapsed < 300.0, f"AHU + 25 VAVs took {elapsed:.0f}s"
    # The RQ path enqueues the same worker function with JSON arguments.
    calls: list[tuple] = []

    class FakeQueue:
        def enqueue(self, func, *args, **kwargs):
            calls.append((func, args, kwargs))
            return len(calls)

    jobs = enqueue_project_suite(FakeQueue(), programs[:2], kernel_backend="python")
    assert jobs == [1, 2] and all(call[0] == RQ_FUNCTION for call in calls)
    func, args, kwargs = calls[0]
    payload = run_program_job(*args, **kwargs)
    assert payload["passed"] is True and payload["engine"].startswith(ENGINE_PREFIX)
    json.dumps(payload)


def test_cli_runs_a_job_against_an_export(exports, tmp_path: Path) -> None:
    job, content = exports["VAV_21"]
    bog = tmp_path / "vav.bog"
    bog.write_bytes(content)
    spec = tmp_path / "job.json"
    spec.write_text(job.model_dump_json())
    output = tmp_path / "report.json"
    assert (
        shadow_main(
            ["run", str(bog), "--job", str(spec), "--kernels", "python", "--output", str(output)]
        )
        == 0
    )
    report = json.loads(output.read_text())
    assert report["passed"] is True and len(report["scenarios"]) == len(job.acceptance_tests)


def test_jvm_backend_reaches_the_same_verdicts(exports) -> None:
    job, content = exports["AHU_1"]
    case = job.acceptance_tests[2]  # the shortest AHU scenario
    python_result, python_values = run_shadow_case(content, case, options=PYTHON)
    jvm_result, jvm_values = run_shadow_case(
        content, case, options=ShadowRunOptions(kernel_backend="jvm")
    )
    assert python_result.passed == jvm_result.passed
    for key, value in python_values.items():
        other = jvm_values[key]
        if isinstance(value, bool):
            assert other == value, key
        elif math.isnan(float(value)) or math.isinf(float(value)):
            assert repr(float(other)) == repr(float(value)), key
        else:
            assert abs(float(other) - float(value)) <= 1e-9, key
