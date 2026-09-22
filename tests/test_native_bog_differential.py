"""N7 D3: three-way agreement between the .bog in the Shadow Runtime, the IR
interpreter and the retained Open Control Engine reference, within documented
pyfunnel bands (docs/decisions/008)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bactalk.library_demo import (
    RETAINED,
    lbnl_multizone_ahu_demo_job,
    lbnl_vav_reheat_demo_job,
    reference_trace,
)
from bactalk.niagara.differential import (
    LEGS,
    Trajectory,
    band_for,
    compare_trajectories,
    load_bands,
    three_way_differential,
)
from bactalk.niagara.shadow.policy import PLAUSIBLE_POLICIES

pytestmark = [pytest.mark.native_bog]

TIER_ONE = [lbnl_vav_reheat_demo_job, lbnl_multizone_ahu_demo_job]
COARSE = next(policy for policy in PLAUSIBLE_POLICIES if policy.name == "coarse-module-tick")
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("build", TIER_ONE)
def test_tier_one_agrees_three_ways_within_the_engineering_bands(build) -> None:
    job = build()
    reference = reference_trace(job.sequence.controller_id)
    assert reference is not None and reference["schema"] == "bactalk.retained-reference-trace/v1"
    report = three_way_differential(job, reference=reference)
    assert report.reference_available and report.reference_engine == "Open Control Engine"
    assert report.passed, report.summary()
    payload = report.to_dict()
    assert payload["schema"] == "bactalk.three-way-differential/v1"
    for case in payload["cases"]:
        assert set(case["legs_available"]) == {"shadow", "interpreter", "reference"}
        for signal in case["signals"]:
            assert set(signal["legs"]) == {leg for leg, _, _ in LEGS}
            assert signal["band"]["source"] == "default" and signal["band"]["rationale"]
            for leg in signal["legs"].values():
                assert leg["engine"] == "pyfunnel", leg


@pytest.mark.parametrize("build", TIER_ONE)
def test_tier_one_agrees_exactly_when_modules_step_once_per_scan(build) -> None:
    """Under the coarse-module-tick policy the Shadow Runtime uses the interpreter's
    discretisation, so the tight band set must pass: any residual difference
    would be a semantic disagreement, not discretisation."""

    job = build()
    report = three_way_differential(
        job, reference=reference_trace(job.sequence.controller_id), policy=COARSE, band_set="coarse"
    )
    assert report.passed, report.summary()
    for case in report.to_dict()["cases"]:
        for signal in case["signals"]:
            assert signal["band"]["source"] == "coarse"


def test_a_disagreement_names_the_first_diverging_block_and_slot() -> None:
    job = lbnl_vav_reheat_demo_job()
    bands = json.loads(json.dumps(load_bands()))
    for kind in ("numeric", "boolean", "integer"):
        bands["default"][kind]["atolx_scans"] = 0
    bands["default"]["numeric"]["atoly_relative"] = 0.0
    bands["default"]["numeric"]["atoly_minimum"] = 1e-12
    report = three_way_differential(
        job, reference=reference_trace(job.sequence.controller_id), bands=bands
    )
    assert not report.passed
    failing = next(case for case in report.cases if not case.passed)
    assert failing.first_divergence is not None
    assert failing.first_divergence["block"] and failing.first_divergence["slot"]
    assert failing.first_divergence["kind"]
    summary = report.summary()
    assert "first divergence" in summary and failing.first_divergence["block"] in summary


def test_bands_come_from_the_documented_file_and_overrides_need_a_decision() -> None:
    bands = load_bands()
    assert bands["schema"] == "bactalk.differential-bands/v1"
    for band_set in ("default", "coarse"):
        for kind in ("numeric", "boolean", "integer"):
            assert (
                "docs/decisions/008" in bands[band_set][kind]["rationale"] or band_set == "coarse"
            )
    for override in bands["overrides"]:
        assert override.get("decision", "").startswith("docs/decisions/"), override
        assert (ROOT / override["decision"]).is_file(), override
    numeric = band_for(
        bands,
        controller_id=None,
        signal="x",
        kind="numeric",
        scan_seconds=60.0,
        reference_range=2.0,
    )
    assert numeric.atolx == 120.0 and numeric.atoly == pytest.approx(0.04)
    boolean = band_for(
        bands,
        controller_id=None,
        signal="x",
        kind="boolean",
        scan_seconds=60.0,
        reference_range=1.0,
    )
    assert boolean.atolx == 120.0 and boolean.atoly == 0.0
    tight = band_for(
        bands,
        controller_id=None,
        signal="x",
        kind="numeric",
        scan_seconds=60.0,
        reference_range=2.0,
        band_set="coarse",
    )
    assert tight.atolx == 60.0 and tight.atoly == pytest.approx(0.002)


def test_funnel_comparison_reports_max_error_and_first_violation() -> None:
    times = [60.0 * (i + 1) for i in range(10)]
    reference = Trajectory(times, [float(i + 1) for i in range(10)])
    band = band_for(
        load_bands(),
        controller_id=None,
        signal="x",
        kind="numeric",
        scan_seconds=60.0,
        reference_range=9.0,
    )
    # One scan late, holding its initial value for the first scan (both engines
    # start from the same state, so a lag shows from the second sample on).
    shifted = Trajectory(times, [1.0] + [float(i + 1) for i in range(9)])
    assert compare_trajectories(reference, shifted, band).passed
    wrong = Trajectory(times, [float(i + 1) if i != 4 else 9.0 for i in range(10)])
    result = compare_trajectories(reference, wrong, band)
    assert not result.passed and result.first_violation_time == 300.0
    assert result.max_error is not None and result.max_error > 1.0


def test_retained_reference_traces_match_a_fresh_oce_run() -> None:
    """Integration tier: the retained third leg never quietly goes stale."""

    import importlib.util
    import sys

    from bactalk.integrations.g36_library import G36Library

    script = Path(__file__).resolve().parents[1] / "scripts" / "retain_reference_traces.py"
    spec = importlib.util.spec_from_file_location("retain_reference_traces", script)
    assert spec and spec.loader
    retain = importlib.util.module_from_spec(spec)
    sys.modules["retain_reference_traces"] = retain
    spec.loader.exec_module(retain)

    library = G36Library()
    for controller_id, filename in RETAINED.items():
        fresh = retain.reference_for(retain.JOBS[controller_id](), library)
        retained = reference_trace(controller_id)
        assert retained is not None
        assert fresh["cases"] == retained["cases"], filename
        assert (
            fresh["source"] == retained["source"] and fresh["parameters"] == retained["parameters"]
        )
