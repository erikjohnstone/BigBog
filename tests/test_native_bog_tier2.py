"""N8: every retained Tier 2 configuration builds a job, lowers natively and validates;
the committed coverage report matches the code."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from bactalk.library_tier2 import (
    CONFIGURATIONS,
    CONFIGURATIONS_BY_ID,
    OPERATION_MODES,
    Configuration,
    absent_inputs,
    nominal_input,
    reference_trace,
    retained_ids,
    retained_translation,
    scenarios_for,
    tier2_job,
)
from bactalk.niagara.emit import emit_bog
from bactalk.niagara.lowering import LoweringPolicy, plan_lowering
from bactalk.niagara.module import declared_types
from bactalk.niagara.validate import validate_bog
from bactalk.protocol import catalog as protocol_catalog
from bactalk.simulator import run_acceptance_suite

pytestmark = [pytest.mark.native_bog]

ROOT = Path(__file__).resolve().parents[1]
BLOCKERS = ROOT / "src" / "bactalk" / "library_tier2" / "blockers.json"
COVERAGE = ROOT / "src" / "bactalk" / "library_tier2" / "coverage.json"
DOCUMENT = ROOT / "docs" / "coverage.md"
RETAINED = [CONFIGURATIONS_BY_ID[item] for item in retained_ids() if reference_trace(item)]


def _blockers() -> dict[str, dict[str, str]]:
    return json.loads(BLOCKERS.read_text(encoding="utf-8")) if BLOCKERS.is_file() else {}


def test_every_configuration_is_retained_or_has_a_recorded_blocker() -> None:
    blockers = _blockers()
    for config in CONFIGURATIONS:
        retained = config.id in retained_ids() and reference_trace(config.id) is not None
        assert retained or config.id in blockers, (
            f"{config.id} has neither retained data nor a blocker; run scripts/retain_tier2.py"
        )
        assert not (retained and config.id in blockers), f"{config.id} is both retained and blocked"
    assert set(blockers) <= {config.id for config in CONFIGURATIONS}
    assert RETAINED, "no Tier 2 configuration is retained"


def test_configuration_ids_and_parameters_are_unique_and_complete() -> None:
    assert len({item.id for item in CONFIGURATIONS}) == len(CONFIGURATIONS)
    for config in CONFIGURATIONS:
        assert config.execution_profile == "host_tick_v1"
        assert config.tier in {"2", "2b"}
        # Tier 2b is exactly the Templates.Plants.Controls rows (GOAL-NATIVE-BOG.md N8)
        assert (config.tier == "2b") == (config.source == "templates")
    families = {item.family for item in CONFIGURATIONS}
    assert {
        "AHUs",
        "TerminalUnits",
        "FanCoilUnits",
        "ThermalZones",
        "ZoneGroups",
        "Plants.Chillers",
        "Plants.Templates",
    } <= families


def test_nominal_inputs_are_typed_and_the_scenarios_cover_every_input() -> None:
    assert nominal_input("uOpeMod", "integer") == OPERATION_MODES["occupied"]
    assert nominal_input("u1Fan", "boolean") is True
    assert nominal_input("TZon", "numeric") == pytest.approx(295.15)
    assert isinstance(nominal_input("VUnknown_flow", "numeric"), float)
    for config in RETAINED:
        translation = retained_translation(config.id)
        inputs = [
            p["name"]
            for p in translation["points"]
            if p["source_interface_direction"] == "input"
            and p["name"] not in absent_inputs(config.id)
        ]
        scenarios = scenarios_for(config.id)
        assert scenarios[0].name == "nominal"
        events = {event[0] for event in config.events}
        assert events <= {s.name for s in scenarios}, config.id
        perturbed = {s.name.split(" ")[0] for s in scenarios[1:] if s.name not in events}
        assert perturbed == set(inputs), config.id
        names = [s.name for s in scenarios]
        assert len(names) == len(set(names))


@pytest.mark.parametrize("config", RETAINED, ids=lambda c: c.id)
def test_retained_configuration_builds_lowers_and_validates(config: Configuration) -> None:
    """D1 and D2 for every retained configuration; the reference-derived suite passes
    in the interpreter (the D3 interpreter-vs-reference leg in end-state form)."""

    job = tier2_job(config.id)
    assert job.control_graph is not None
    assert job.sequence.controller_id == config.controller_id
    assert job.sequence.parameters == config.parameters
    reference = reference_trace(config.id)
    assert reference is not None
    assert [case["name"] for case in reference["cases"]] == [
        case.name for case in job.acceptance_tests
    ]
    plan = plan_lowering(job.control_graph, LoweringPolicy())
    assert plan.lane in {"native_stock", "native_with_module"}, plan.blockers
    content = emit_bog(job.control_graph, points=job.points).content
    report = validate_bog(content, declared_types=declared_types(), label=config.id)
    assert report.ok, [str(issue) for issue in report.errors[:5]]
    suite = run_acceptance_suite(job.control_graph, job)
    failures = [
        (scenario.name, assertion.name, assertion.observed, assertion.expected)
        for scenario in suite.scenarios
        for assertion in scenario.assertions
        if not assertion.passed
    ]
    assert suite.passed, failures[:10]


def test_committed_coverage_report_matches_the_code() -> None:
    """scripts/coverage_report.py --check in test form (the slow D3/D4 grading is not
    rerun here; the committed report must list every configuration consistently)."""

    assert COVERAGE.is_file() and DOCUMENT.is_file(), "run scripts/coverage_report.py"
    report = json.loads(COVERAGE.read_text(encoding="utf-8"))
    assert report["schema"] == "bactalk.native-bog-coverage/v1"
    ids = [item["id"] for item in report["items"]]
    assert ids == (
        ["tier1-vav-reheat", "tier1-ahu-multizone-vav"]
        + [c.id for c in CONFIGURATIONS]
        + protocol_catalog.sequence_ids()
    ), "Tier 1, Tier 2, then every protocol row (Tiers 3–5) in catalogue order"
    blockers = _blockers()
    for item in report["items"]:
        for proof in ("d1", "d2", "d3", "d4"):
            assert "passed" in item[proof]
        if item["id"] in blockers:
            assert item["blocker"]["reason"] == blockers[item["id"]]["reason"]
        if item["tier"] == "1":
            assert item["d1"]["passed"] and item["d2"]["passed"] and item["d3"]["passed"]
    spec = importlib.util.spec_from_file_location(
        "coverage_report", ROOT / "scripts" / "coverage_report.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["coverage_report"] = module
    spec.loader.exec_module(module)
    assert DOCUMENT.read_text(encoding="utf-8") == module.render(report)
    summary = report["summary"]
    assert summary["configurations"] == len(ids)
    assert summary["all_four"] <= summary["d4"] <= summary["configurations"]
