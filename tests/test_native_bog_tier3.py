"""N9: the Tier 3 hot water plant under the Test Generation Protocol: native lowering,
static validity, the generated suite, decision coverage, invariants, traceability, and
the committed adequacy artifact matching the code."""

from __future__ import annotations

from pathlib import Path

import pytest

from bactalk.library_tier3 import ITEMS, adequacy_artifact, requirement_set, tier3_job
from bactalk.niagara.emit import emit_bog
from bactalk.niagara.lowering import LoweringPolicy, plan_lowering
from bactalk.niagara.module import declared_types
from bactalk.niagara.validate import validate_bog
from bactalk.protocol import generate_test_plan, protocol_reference
from bactalk.protocol.adequacy import check_invariants, run_suite

pytestmark = [pytest.mark.native_bog]

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs" / "test-plans" / "hw-plant-boiler.md"


@pytest.fixture(scope="module")
def hw_plant():
    rs = requirement_set("hw-plant-boiler")
    plan = generate_test_plan(rs)
    return rs, plan, tier3_job("hw-plant-boiler", plan=plan)


def test_every_tier3_item_declares_its_protocol_reference() -> None:
    for item in ITEMS:
        rs = requirement_set(item.id)
        job = tier3_job(item.id)
        assert protocol_reference(job) == (rs.sequence_id, rs.digest())
        assert job.control_graph is not None
        assert job.control_graph.metadata["requirements_digest"] == rs.digest()


def test_hw_plant_requirements_cite_and_trace(hw_plant) -> None:
    rs, plan, job = hw_plant
    assert rs.tier == 3 and len(rs.requirements) >= 17 and len(rs.invariants) >= 5
    for requirement in rs.requirements:
        assert requirement.citation.document.startswith("ASHRAE Guideline 36")
    traced = plan.traceability()
    assert set(traced) == {r.id for r in rs.requirements}, "every requirement has scenarios"
    traceability = job.control_graph.metadata["traceability"]
    cited = {req for reqs in traceability.values() for req in reqs if req.startswith("R-")}
    assert cited == {r.id for r in rs.requirements}, "every requirement is implemented by a block"
    for block in job.control_graph.blocks:
        assert block.id in traceability, block.id


def test_hw_plant_lowers_natively_and_validates(hw_plant) -> None:
    _, _, job = hw_plant
    plan = plan_lowering(job.control_graph, LoweringPolicy())
    assert plan.lane in {"native_stock", "native_with_module"} and not plan.blockers
    content = emit_bog(job.control_graph, points=job.points).content
    report = validate_bog(content, declared_types=declared_types())
    assert report.ok, [str(issue) for issue in report.errors[:5]]


def test_hw_plant_passes_its_generated_suite_with_full_decision_coverage(hw_plant) -> None:
    rs, plan, job = hw_plant
    report, suite = run_suite(job, plan, rs)
    assert suite["passed"], [s["name"] for s in suite["scenarios"] if not s["passed"]]
    assert suite["count"] == len(plan.scenarios) >= 150
    assert report.coverage["fully_covered"], report.coverage["gaps"]
    assert suite["invariant_violations"] == []


def test_hw_plant_invariants_hold_on_random_sequences(hw_plant) -> None:
    rs, _, job = hw_plant
    result = check_invariants(job, rs, sequences=200, steps=24, seed=3)
    assert result["violations"] == 0, result["examples"][:3]


def test_committed_adequacy_artifact_matches_the_code(hw_plant) -> None:
    rs, plan, _ = hw_plant
    artifact = adequacy_artifact("hw-plant-boiler")
    assert artifact is not None, "run scripts/protocol_adequacy.py hw-plant-boiler"
    assert artifact["schema"] == "bactalk.protocol-adequacy/v1"
    assert artifact["requirements_digest"] == rs.digest()
    assert artifact["plan_digest"] == plan.digest()
    assert artifact["suite"]["passed"] is True and artifact["decisions"]["fully_covered"] is True
    assert (
        artifact["invariants"]["sequences"] >= 10_000 and artifact["invariants"]["violations"] == 0
    )
    assert "catch_rate" in (artifact["mutation"] or {}), artifact.get("mutation")
    assert artifact["gate_g_eng"] in {"approved", "unapproved", "stale"}
    assert PLAN.is_file() and rs.digest() in PLAN.read_text(encoding="utf-8")
