"""N10: every Tier 4 configuration (BACTalk standard sequences) under the Test
Generation Protocol: the author reproduces the retained requirement set, the graph
lowers natively and validates, the generated suite passes with full decision coverage,
invariants hold, every requirement is implemented and tested, and the retained
adequacy artifact belongs to the current requirement digest."""

from __future__ import annotations

import importlib

import pytest

from bactalk.library_tier4 import ITEMS, TIER4_LABEL
from bactalk.niagara.emit import emit_bog
from bactalk.niagara.lowering import LoweringPolicy, plan_lowering
from bactalk.niagara.module import declared_types
from bactalk.niagara.validate import validate_bog
from bactalk.protocol import catalog, generate_test_plan, protocol_reference
from bactalk.protocol.adequacy import check_invariants, run_suite

pytestmark = [pytest.mark.native_bog]

ROWS = [entry for entry in catalog.rows() if entry.item.tier == 4]
IDS = [f"{entry.item.id}/{entry.configuration.id}" for entry in ROWS]


def test_tier4_items_are_labelled_standard_sequences_never_g36() -> None:
    assert {item.id for item in ITEMS} >= {
        "exhaust-fan",
        "pump-duty-standby",
        "rtu",
        "heat-pump",
        "doas",
    }
    for item in ITEMS:
        assert item.label == TIER4_LABEL and item.family == "BACTALK_STANDARD_SEQUENCE"
        for configuration in item.configurations:
            requirements = catalog.Row(item, configuration).requirement_set()
            assert requirements.tier == 4
            assert "Guideline 36" not in requirements.title
            for requirement in requirements.requirements:
                assert "G36" not in requirement.citation.document
                assert requirement.citation.fidelity == "designer"


@pytest.mark.parametrize("entry", ROWS, ids=IDS)
def test_author_reproduces_the_retained_requirement_set(entry: catalog.Row) -> None:
    author = importlib.import_module(f"{entry.item.package}.author")
    document = author.DOCUMENTS[entry.configuration.requirements_file]
    assert document["sequence_id"] == entry.requirement_set().sequence_id
    assert author.main(["--check"]) == 0


@pytest.mark.parametrize("entry", ROWS, ids=IDS)
def test_configuration_lowers_validates_and_passes_its_generated_suite(entry: catalog.Row) -> None:
    requirements = entry.requirement_set()
    plan = generate_test_plan(requirements)
    job = catalog.protocol_job(requirements.sequence_id, plan=plan)
    assert protocol_reference(job) == (requirements.sequence_id, requirements.digest())
    assert job.sequence.parameters["protocol"]["label"] == TIER4_LABEL
    assert job.sequence.parameters["protocol"]["options"] == entry.configuration.options
    lowering = plan_lowering(job.control_graph, LoweringPolicy())
    assert lowering.lane in {"native_stock", "native_with_module"} and not lowering.blockers
    content = emit_bog(job.control_graph, points=job.points).content
    validation = validate_bog(content, declared_types=declared_types())
    assert validation.ok, [str(issue) for issue in validation.errors[:5]]
    report, suite = run_suite(job, plan, requirements)
    assert suite["passed"], [s["name"] for s in suite["scenarios"] if not s["passed"]]
    assert report.coverage["fully_covered"], report.coverage["gaps"]
    traced = plan.traceability()
    assert set(traced) == {r.id for r in requirements.requirements}
    traceability = job.control_graph.metadata["traceability"]
    cited = {req for reqs in traceability.values() for req in reqs if req.startswith("R-")}
    assert cited == {r.id for r in requirements.requirements}
    invariants = check_invariants(job, requirements, sequences=100, steps=16, seed=5)
    assert invariants["violations"] == 0, invariants["examples"][:2]


@pytest.mark.parametrize("entry", ROWS, ids=IDS)
def test_retained_adequacy_artifact_is_current(entry: catalog.Row) -> None:
    requirements = entry.requirement_set()
    artifact = entry.adequacy_artifact()
    assert artifact is not None, f"run scripts/protocol_adequacy.py {requirements.sequence_id}"
    assert artifact["requirements_digest"] == requirements.digest()
    assert artifact["plan_digest"] == generate_test_plan(requirements).digest()
    assert artifact["suite"]["passed"] is True and artifact["decisions"]["fully_covered"] is True
    assert (
        artifact["invariants"]["sequences"] >= 10_000 and artifact["invariants"]["violations"] == 0
    )
    assert "catch_rate" in (artifact["mutation"] or {}), artifact.get("mutation")
    assert artifact["gate_g_eng"] in {"approved", "unapproved", "stale"}
