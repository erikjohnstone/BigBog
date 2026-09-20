from bactalk.demo import generalist_demo_job
from bactalk.domain import (
    AcceptanceCase,
    AcceptancePhase,
    FaultInjection,
    FaultKind,
    QualificationCategory,
    QualificationLevel,
    QualificationProfile,
    QualificationRequirement,
    ScenarioResult,
)
from bactalk.qualification import assess_qualification_matrix


def _passing(name: str) -> ScenarioResult:
    return ScenarioResult(name=name, passed=True, assertions=[], samples=[])


def test_builtin_ahu_matrix_credits_only_explicit_passing_categories() -> None:
    job = generalist_demo_job()
    results = [_passing(case.name) for case in job.acceptance_tests]

    matrix = assess_qualification_matrix(
        sequence_family=job.sequence.family,
        cases=job.acceptance_tests,
        results=results,
    )

    assert matrix["profile"]["id"] == "ahu-safety-cooling-v1"
    assert matrix["required_passed"] == matrix["required_count"] == 4
    assert matrix["conditional_count"] > 0
    assert matrix["conditional_addressed"] == 0
    assert matrix["engineering_matrix_complete"] is False
    assert any("fire_smoke_shutdown" in blocker for blocker in matrix["blockers"])


def test_fault_and_recovery_require_mechanical_evidence_not_just_a_tag() -> None:
    case = AcceptanceCase(
        name="proof loss and return",
        qualifications=[
            QualificationCategory.ACTUATOR_PROOF_FAILURE,
            QualificationCategory.RECOVERY,
        ],
        expectations=[{"target": "Alarm", "value": False}],
        timeline=[
            AcceptancePhase(
                name="proof lost",
                inputs={"Proof": True},
                faults=[
                    FaultInjection(
                        id="proof_lost",
                        target="Proof",
                        kind=FaultKind.FORCE,
                        value=False,
                    )
                ],
            ),
            AcceptancePhase(
                name="proof restored", expectations=[{"target": "Alarm", "value": False}]
            ),
        ],
    )

    matrix = assess_qualification_matrix(
        sequence_family="EXHAUST_FAN_PROOF",
        cases=[case],
        results=[_passing(case.name)],
    )
    rows = {row["category"]: row for row in matrix["requirements"]}

    assert rows["actuator_proof_failure"]["status"] == "passed"
    assert rows["recovery"]["status"] == "passed"

    unproven = case.model_copy(update={"timeline": [], "faults": []})
    unproven_matrix = assess_qualification_matrix(
        sequence_family="EXHAUST_FAN_PROOF",
        cases=[unproven],
        results=[_passing(unproven.name)],
    )
    unproven_rows = {row["category"]: row for row in unproven_matrix["requirements"]}
    assert unproven_rows["actuator_proof_failure"]["status"] == "insufficient_fault_evidence"
    assert unproven_rows["recovery"]["status"] == "insufficient_fault_evidence"


def test_contractor_profile_can_resolve_project_specific_applicability() -> None:
    profile = QualificationProfile(
        id="contractor-custom-unit-v1",
        version="1.0.0",
        source="Contractor approved hazard review",
        requirements=[
            QualificationRequirement(
                category=QualificationCategory.NORMAL_OPERATION,
                description="Normal enable and disable behavior.",
            ),
            QualificationRequirement(
                category=QualificationCategory.FIRE_SMOKE_SHUTDOWN,
                level=QualificationLevel.NOT_APPLICABLE,
                description="Equipment is outside the smoke-control sequence boundary.",
            ),
        ],
    )
    case = AcceptanceCase(
        name="normal",
        inputs={"Enable": True},
        qualifications=[QualificationCategory.NORMAL_OPERATION],
        expectations=[{"target": "Command", "value": True}],
    )

    matrix = assess_qualification_matrix(
        sequence_family="CONTRACTOR_CUSTOM",
        profile=profile,
        cases=[case],
        results=[_passing(case.name)],
    )

    assert matrix["required_passed"] == matrix["required_count"] == 1
    assert matrix["engineering_matrix_complete"] is True
    assert matrix["blockers"] == []


def test_unknown_sequence_reports_missing_profile_instead_of_implied_coverage() -> None:
    matrix = assess_qualification_matrix(
        sequence_family="UNKNOWN_CUSTOM",
        cases=[],
        results=[],
    )

    assert matrix["profile"] is None
    assert matrix["engineering_matrix_complete"] is False
    assert matrix["blockers"]
