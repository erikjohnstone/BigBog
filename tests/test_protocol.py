"""N9: the Test Generation Protocol (bactalk.protocol) on a small synthetic sequence."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from bactalk.domain import Block, BlockKind, ControlGraph, JobSpec, Link, PointSpec
from bactalk.protocol import (
    Citation,
    Condition,
    FailureBehaviour,
    Invariant,
    Outcome,
    PointDeclaration,
    Requirement,
    RequirementApproval,
    RequirementSet,
    Timing,
    approval_status,
    generate_test_plan,
)
from bactalk.protocol.adequacy import assess_adequacy, check_invariants, run_suite
from bactalk.protocol.approvals import RequirementApprovalRepository
from bactalk.protocol.classify import classify_failure
from bactalk.protocol.invariants import condition_holds, invariant_violations, outcome_holds
from bactalk.protocol.plan import approval_digest, render_test_plan
from bactalk.protocol.requirements import Source
from bactalk.protocol.test_author import (
    boundary_values,
    deadband_values,
    satisfying_value,
    violating_value,
)

ROOT = Path(__file__).resolve().parents[1]
CITE = Citation(document="Test guideline", section="§1", fidelity="designer")


def _requirements(*, delay: float = 60.0, release: float = 0.0) -> RequirementSet:
    """A fan that runs when enabled and the temperature is high (with deadband) for a delay."""

    return RequirementSet(
        sequence_id="test-fan",
        title="Fan on high temperature",
        version="1",
        tier=3,
        sources=[Source(document="Test guideline", edition="2026")],
        step_seconds=10.0,
        points=[
            PointDeclaration(
                name="uEna", label="Enable", data_type="boolean", direction="input", nominal=True
            ),
            PointDeclaration(
                name="TZon",
                label="Zone temperature",
                data_type="numeric",
                direction="input",
                unit="K",
                minimum=280.0,
                maximum=310.0,
                nominal=293.0,
                resolution=0.1,
            ),
            PointDeclaration(
                name="yFan", label="Fan", data_type="boolean", direction="output", nominal=False
            ),
            PointDeclaration(
                name="ySpe",
                label="Speed",
                data_type="numeric",
                direction="output",
                minimum=0.0,
                maximum=1.0,
            ),
        ],
        requirements=[
            Requirement(
                id="R-01",
                title="Enable",
                text="The fan logic is enabled by the enable input.",
                citation=CITE,
                conditions=[Condition(point="uEna", operator="eq", value=True)],
                outcomes=[Outcome(point="ySpe", operator="gte", value=0.0)],
                otherwise=[Outcome(point="yFan", operator="eq", value=False)],
            ),
            Requirement(
                id="R-02",
                title="Fan on high temperature",
                kind="control",
                text="When enabled and the zone is above 297 K (1 K deadband) for the delay, "
                "the fan runs.",
                citation=CITE,
                assumes=["R-01"],
                conditions=[Condition(point="TZon", operator="gt", value=297.0, deadband=1.0)],
                timing=Timing(delay_seconds=delay, release_seconds=release),
                outcomes=[Outcome(point="yFan", operator="eq", value=True)],
                otherwise=[Outcome(point="yFan", operator="eq", value=False)],
                failures=[
                    FailureBehaviour(
                        point="TZon",
                        mode="out_of_range_high",
                        outcomes=[Outcome(point="yFan", operator="eq", value=True)],
                    )
                ],
            ),
        ],
        invariants=[
            Invariant(
                id="I-01",
                text="The fan never runs while disabled",
                citation=CITE,
                when=[Condition(point="uEna", operator="eq", value=False)],
                then=[Outcome(point="yFan", operator="eq", value=False)],
            ),
            Invariant(
                id="I-02",
                text="Speed is a fraction",
                citation=CITE,
                then=[Outcome(point="ySpe", operator="between", value=0.0, upper=1.0)],
            ),
        ],
    )


def _graph(*, delay: float = 60.0, release: float = 0.0, broken: bool = False) -> ControlGraph:
    blocks = [
        Block(id="uEna", kind=BlockKind.BOOLEAN_INPUT, label="Enable", config={"default": True}),
        Block(id="TZon", kind=BlockKind.NUMERIC_INPUT, label="Zone", config={"default": 293.0}),
        Block(
            id="hot",
            kind=BlockKind.HYSTERESIS,
            label="Hot",
            config={"u_low": 296.0 if not broken else 296.9, "u_high": 297.0},
        ),
        Block(id="cond", kind=BlockKind.AND, label="Enabled and hot"),
        Block(
            id="delay",
            kind=BlockKind.BOOLEAN_DELAY,
            label="Delay",
            config={"on_delay_seconds": delay, "off_delay_seconds": release},
        ),
        Block(id="yFan", kind=BlockKind.BOOLEAN_OUTPUT, label="Fan"),
        Block(id="one", kind=BlockKind.NUMERIC_CONST, label="One", config={"value": 1.0}),
        Block(id="zero", kind=BlockKind.NUMERIC_CONST, label="Zero", config={"value": 0.0}),
        Block(id="speed", kind=BlockKind.NUMERIC_SWITCH, label="Speed"),
        Block(id="ySpe", kind=BlockKind.NUMERIC_OUTPUT, label="Speed out"),
    ]
    links = [
        Link(source="TZon", target="hot", target_slot="in"),
        Link(source="hot", target="delay", target_slot="in"),
        Link(source="uEna", target="cond", target_slot="a"),
        Link(source="delay", target="cond", target_slot="b"),
        Link(source="cond", target="yFan", target_slot="in"),
        Link(source="cond", target="speed", target_slot="selector"),
        Link(source="one", target="speed", target_slot="when_true"),
        Link(source="zero", target="speed", target_slot="when_false"),
        Link(source="speed", target="ySpe", target_slot="in"),
    ]
    return ControlGraph(name="TestFan", blocks=blocks, links=links)


def _job(graph: ControlGraph) -> JobSpec:
    return JobSpec(
        name="test fan",
        site="test",
        equipment_name="FAN_1",
        points=[
            PointSpec(
                name="uEna", label="Enable", data_type="boolean", role="status", default=True
            ),
            PointSpec(
                name="TZon",
                label="Zone",
                data_type="numeric",
                role="sensor",
                units="K",
                default=293.0,
            ),
            PointSpec(name="yFan", label="Fan", data_type="boolean", role="command", default=False),
            PointSpec(name="ySpe", label="Speed", data_type="numeric", role="command", default=0.0),
        ],
        control_graph=graph,
    )


# --- the requirement model ------------------------------------------------------------------


def test_requirement_set_digest_is_stable_and_references_resolve() -> None:
    rs = _requirements()
    assert rs.digest() == _requirements().digest()
    assert rs.effective_conditions(rs.requirement("R-02"))[0].point == "uEna"
    with pytest.raises(ValueError, match="unknown output"):
        _requirements().model_copy(
            update={
                "requirements": [
                    Requirement(
                        id="R-09",
                        title="Bad",
                        text="Outcome names an input.",
                        citation=CITE,
                        conditions=[Condition(point="uEna", operator="eq", value=True)],
                        outcomes=[Outcome(point="uEna", operator="eq", value=True)],
                    )
                ]
            }
        ).model_validate(
            _requirements().model_dump(mode="json", by_alias=True)
            | {
                "requirements": [
                    {
                        "id": "R-09",
                        "title": "Bad",
                        "text": "Outcome names an input.",
                        "citation": CITE.model_dump(),
                        "conditions": [{"point": "uEna", "operator": "eq", "value": True}],
                        "outcomes": [{"point": "uEna", "operator": "eq", "value": True}],
                    }
                ]
            }
        )


def test_assumes_cycles_are_refused() -> None:
    payload = _requirements().model_dump(mode="json", by_alias=True)
    payload["requirements"][0]["assumes"] = ["R-02"]
    with pytest.raises(ValueError, match="cycle"):
        RequirementSet.model_validate(payload)


def test_approval_status_tracks_the_digest() -> None:
    rs = _requirements()
    assert approval_status(rs, None) == "unapproved"
    approval = RequirementApproval(
        sequence_id=rs.sequence_id, requirements_digest=rs.digest(), reviewer="Engineer"
    )
    assert approval_status(rs, approval) == "approved"
    assert approval_status(rs.model_copy(update={"version": "2"}), approval) == "stale"


def test_approval_repository_retains_one_record_per_digest(tmp_path: Path) -> None:
    rs = _requirements()
    repo = RequirementApprovalRepository(tmp_path)
    assert repo.status(rs) == "unapproved"
    repo.save(
        RequirementApproval(
            sequence_id=rs.sequence_id, requirements_digest=rs.digest(), reviewer="Engineer"
        )
    )
    assert repo.status(rs) == "approved"
    assert repo.is_approved(rs.sequence_id, rs.digest())
    with pytest.raises(FileExistsError):
        repo.save(
            RequirementApproval(
                sequence_id=rs.sequence_id, requirements_digest=rs.digest(), reviewer="Again"
            )
        )
    assert repo.status(rs.model_copy(update={"version": "2"})) == "stale"


# --- the test author ---------------------------------------------------------------------------


def test_test_author_sees_requirements_only() -> None:
    """Protocol rule 2 enforced in code: no import of the logic side."""

    source = (ROOT / "src" / "bactalk" / "protocol" / "test_author.py").read_text(encoding="utf-8")
    imported = {
        node.module for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    forbidden = {
        "bactalk.simulator",
        "bactalk.niagara",
        "bactalk.library_demo",
        "bactalk.library_tier2",
        "bactalk.library_tier3",
        "bactalk.compiler",
    }
    assert not {m for m in imported if any(m == f or m.startswith(f + ".") for f in forbidden)}, (
        imported
    )
    assert "ControlGraph" not in source and "control_graph" not in source


def test_values_either_side_of_a_condition() -> None:
    point = _requirements().point("TZon")
    hot = Condition(point="TZon", operator="gt", value=297.0, deadband=1.0)
    assert satisfying_value(hot, point) == pytest.approx(297.1)
    assert violating_value(hot, point) == pytest.approx(295.9)
    assert [(label, holds) for label, _, holds in boundary_values(hot, point)] == [
        ("at threshold", False),
        ("just above", True),
    ]
    held, released = deadband_values(hot, point)
    assert held == pytest.approx(296.1) and released == pytest.approx(295.9)
    assert satisfying_value(Condition(point="uEna", operator="eq", value=False), point) is False


def test_plan_covers_every_requirement_with_the_protocol_kinds() -> None:
    rs = _requirements(delay=60.0, release=30.0)
    plan = generate_test_plan(rs)
    kinds = {(s.requirement_id, s.kind) for s in plan.scenarios}
    for kind in (
        "positive",
        "negative",
        "timing_before",
        "timing_after",
        "release_before",
        "release_after",
        "boundary_true",
        "boundary_false",
        "deadband_hold",
        "deadband_release",
        "failure",
        "recovery",
    ):
        assert ("R-02", kind) in kinds, kind
    assert set(plan.traceability()) == {"R-01", "R-02"}
    assert plan.invariant_ids == ["I-01", "I-02"]
    assert {gap["kind"] for gap in plan.gaps} == {"failure_behaviour"}
    assert plan.digest() == generate_test_plan(rs).digest()
    # every scenario names its requirement and carries the same top-level and final expectations
    for scenario in plan.scenarios:
        assert scenario.case.name.startswith(scenario.requirement_id)
        final = next(p.expectations for p in reversed(scenario.case.timeline) if p.expectations)
        assert scenario.case.expectations == final


def test_timing_scenarios_sit_one_scan_either_side_of_the_delay() -> None:
    plan = generate_test_plan(_requirements(delay=60.0))
    before = plan.scenario("R-02 timing_before").case.timeline[-1]
    after = plan.scenario("R-02 timing_after").case.timeline[-1]
    assert (before.repeat, after.repeat) == (5, 6)


# --- invariants -----------------------------------------------------------------------------------


def test_invariant_evaluation() -> None:
    rs = _requirements()
    assert condition_holds(Condition(point="TZon", operator="gte", value=1.0), 1.0)
    assert outcome_holds(Outcome(point="ySpe", operator="eq", value=1.0, tolerance=0.01), 1.005)
    assert invariant_violations(rs, {"uEna": False, "yFan": False, "ySpe": 0.0}) == []
    found = invariant_violations(rs, {"uEna": False, "yFan": True, "ySpe": 2.0})
    assert [(v["invariant"], v["point"]) for v in found] == [("I-01", "yFan"), ("I-02", "ySpe")]
    assert invariant_violations(rs, {"uEna": False})[0]["reason"] == "unsampled"


# --- adequacy and classification ---------------------------------------------------------------


def test_correct_logic_passes_the_generated_suite_and_invariants() -> None:
    rs = _requirements(delay=60.0, release=30.0)
    plan = generate_test_plan(rs)
    job = _job(_graph(delay=60.0, release=30.0))
    report, suite = run_suite(job, plan, rs)
    assert suite["passed"], [s for s in suite["scenarios"] if not s["passed"]]
    assert report.coverage["fully_covered"], report.coverage["gaps"]
    invariants = check_invariants(job, rs, sequences=50, steps=12, seed=1)
    assert invariants["passed"] and invariants["violations"] == 0


def test_a_wrong_deadband_is_caught_and_classified_as_a_question() -> None:
    """The broken graph releases at the threshold instead of the deadband edge: the
    deadband_hold scenario fails and the protocol turns it into a question, not a fix."""

    rs = _requirements(delay=60.0)
    plan = generate_test_plan(rs)
    job = _job(_graph(delay=60.0, broken=True))
    adequacy = assess_adequacy(
        job, rs, plan, mutants=None, invariant_sequences=20, invariant_steps=8
    )
    assert not adequacy.accepted
    failed = {s["name"] for s in adequacy.suite["scenarios"] if not s["passed"]}
    assert "R-02 deadband_hold [TZon]" in failed
    categories = {c.scenario: c.category for c in adequacy.classifications}
    assert categories["R-02 deadband_hold [TZon]"] == "ambiguous_requirement"
    assert any("deadband" in q for q in adequacy.questions)
    payload = adequacy.to_dict()
    assert payload["schema"] == "bactalk.protocol-adequacy/v1" and payload["accepted"] is False


def test_classification_rules() -> None:
    rs = _requirements(delay=60.0)
    plan = generate_test_plan(rs)
    logic = classify_failure(rs, plan, "R-02 positive", "yFan", "False", "eq True")
    assert logic.category == "logic_bug" and logic.question is None
    timing = classify_failure(rs, plan, "R-02 timing_before", "yFan", "True", "eq False")
    assert timing.category == "ambiguous_requirement" and "scan" in (timing.question or "")
    boundary = classify_failure(
        rs, plan, "R-02 boundary_false [TZon at threshold]", "yFan", "True", "eq False"
    )
    assert boundary.category == "ambiguous_requirement" and "inclusive" in (boundary.question or "")


def test_adequacy_refuses_a_plan_from_another_requirement_set() -> None:
    rs = _requirements()
    plan = generate_test_plan(rs.model_copy(update={"version": "other"}))
    with pytest.raises(ValueError, match="different requirement set"):
        assess_adequacy(
            _job(_graph()), rs, plan, mutants=None, invariant_sequences=1, invariant_steps=1
        )


# --- the readable plan ---


def test_rendered_plan_lists_requirements_scenarios_results_and_questions() -> None:
    rs = _requirements(delay=60.0)
    plan = generate_test_plan(rs)
    job = _job(_graph(delay=60.0, broken=True))
    adequacy = assess_adequacy(
        job, rs, plan, mutants=None, invariant_sequences=5, invariant_steps=5
    ).to_dict()
    text = render_test_plan(rs, plan, adequacy)
    assert "# Test plan: Fan on high temperature" in text
    assert "Gate G-ENG): **unapproved**" in text
    assert "### R-02 Fan on high temperature" in text
    assert "| R-02 positive | positive |" in text
    assert "FAIL:" in text and "Questions for the engineer" in text
    assert "- **I-01**" in text and "Gaps the test author could not close" in text
    digest = approval_digest(rs, plan, adequacy)
    assert len(digest) == 64 and digest != approval_digest(rs, plan, None)
