from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bactalk.api import create_app
from bactalk.domain import PointSpec
from bactalk.intake import parse_sequence_document
from bactalk.integrations.ctrl_flow import CtrlFlowLibrary
from bactalk.integrations.ctrl_flow_planning import AHU_TEMPLATE
from bactalk.security import (
    Principal,
    Role,
    SecurityConfig,
    TokenCredential,
    hash_token,
    required_role,
)
from bactalk.sequence_oracles import (
    SequenceOracleApprovalRepository,
    SequenceOracleApprovalRequest,
    SequenceOracleIntegrityError,
    compile_sequence_oracle_approval,
)
from bactalk.sequence_requirements import SequenceRequirementReviewRequest
from bactalk.sequence_review_repository import SequenceRequirementReviewRepository

SEQUENCE = """
If mixed-air temperature falls below 38 °F for 5 minutes, close the outdoor-air damper.
If duct static pressure exceeds 1.5 in. w.c. for 10 seconds, stop the supply fan.
""".strip()
REVIEWER_TOKEN = "requirement-reviewer-token-000000000000000000"
ORACLE_TOKEN = "oracle-author-token-000000000000000000000000"


def _credential(token: str, subject: str, display_name: str) -> TokenCredential:
    principal = Principal(
        subject=subject,
        display_name=display_name,
        tenant_id="oracle-test-tenant",
        roles=frozenset({Role.APPROVER, Role.PROGRAMMER}),
        credential_id=f"{subject}-token",
    )
    return TokenCredential(principal.credential_id, hash_token(token), principal)


def _security() -> SecurityConfig:
    return SecurityConfig(
        enabled=True,
        require_https=False,
        source="test",
        credentials=(
            _credential(REVIEWER_TOKEN, "reviewer@example.com", "Requirement Reviewer"),
            _credential(ORACLE_TOKEN, "oracle@example.com", "Oracle Author"),
        ),
    )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _review_payload(reconciliation: dict) -> dict:
    candidates = reconciliation["requirement_candidates"]
    decisions = []
    for group in ("quantities", "actions", "policies"):
        for item in candidates[group]:
            point_candidates = item.get("point_candidates", item.get("input_point_candidates", []))
            selected_point = None
            if len(point_candidates) > 1:
                selected_point = (
                    "SupplyFanCommand"
                    if "SupplyFanCommand" in point_candidates
                    else point_candidates[0]
                )
            decisions.append(
                {
                    "candidate_id": item["id"],
                    "disposition": "approve",
                    "selected_point": selected_point,
                }
            )
    return {
        "candidate_digest": candidates["candidate_digest"],
        "reviewer": "Controls Engineer",
        "decisions": decisions,
    }


def _point_evidence(library: CtrlFlowLibrary | None = None) -> dict:
    library = library or CtrlFlowLibrary()
    brief = library.programming_brief(AHU_TEMPLATE, {})
    points = [
        PointSpec(
            name=point["id"],
            label=point["label"],
            data_type=point["data_type"],
            role=point["role"],
            units=point["units"],
            default=False if point["data_type"] == "boolean" else 0.0,
        )
        for point in brief["point_requirements"]["points"]
        if point["required"]
    ]
    result = library.reconcile_points(AHU_TEMPLATE, {}, points)
    return {
        "id": "1" * 32,
        "artifact_digest": "2" * 64,
        "result_digest": "3" * 64,
        "source_sha256": "4" * 64,
        "source_filename": "points.csv",
        "template_id": AHU_TEMPLATE,
        "configuration_digest": result["configuration_digest"],
        "ready_for_sequence_reconciliation": result["ready_for_sequence_reconciliation"],
        "canonical_points": result["canonical_points"],
        "matches": result["matches"],
        "unit_conversions": result["unit_conversions"],
        "unmatched_provided": result["unmatched_provided"],
    }


def _retain_point_contract(
    client: TestClient,
    headers: dict[str, str] | None = None,
) -> dict:
    brief = CtrlFlowLibrary().programming_brief(AHU_TEMPLATE, {})
    rows = ["name,label,data_type,role,units,default,required"]
    for point in brief["point_requirements"]["points"]:
        if point["required"]:
            rows.append(
                ",".join(
                    (
                        point["id"],
                        point["label"],
                        point["data_type"],
                        point["role"],
                        point["units"] or "",
                        "false" if point["data_type"] == "boolean" else "0",
                        "true",
                    )
                )
            )
    response = client.post(
        f"/api/library/ctrl-flow/templates/{AHU_TEMPLATE}/inspect-points",
        headers=headers,
        data={"selections": "{}"},
        files={"points_file": ("points.csv", "\n".join(rows).encode(), "text/csv")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _retained_review(tmp_path: Path, sequence: str = SEQUENCE):
    library = CtrlFlowLibrary()
    document = parse_sequence_document(sequence.encode(), "sequence.txt")
    reconciliation = library.reconcile_sequence(AHU_TEMPLATE, {}, document)
    result = library.review_sequence_requirements(
        AHU_TEMPLATE,
        {},
        document,
        SequenceRequirementReviewRequest.model_validate(_review_payload(reconciliation)),
        reviewer="Controls Engineer",
        actor_id=None,
        tenant_id=None,
        authentication="self-asserted-local",
        point_reconciliation=_point_evidence(library),
    )
    record = SequenceRequirementReviewRepository(tmp_path / "reviews").save(
        template_id=AHU_TEMPLATE,
        selections={},
        source_content=sequence.encode(),
        source_filename=document.filename,
        source_media_type=document.media_type,
        result=result,
    )
    return record


def _non_triggered_expectation(expectation: dict) -> dict:
    value = expectation["value"]
    if isinstance(value, bool):
        return {"target": expectation["point"], "operator": "eq", "value": not value}
    return {"target": expectation["point"], "operator": "gt", "value": float(value)}


def _condition_values(condition: dict) -> tuple[float, float, float]:
    threshold = float(condition["value"])
    if condition["operator"] in {"lt", "le"}:
        return threshold + 10.0, threshold - 10.0, threshold + 10.0
    if condition["operator"] in {"gt", "ge"}:
        return threshold - 0.5, threshold + 0.5, threshold - 0.5
    return threshold + 1.0, threshold, threshold + 1.0


def _oracle_payload(record) -> dict:
    cases = []
    for draft in record.result["oracle_drafts"]:
        baseline_inputs = {}
        trigger_inputs = {}
        recovery_inputs = {}
        for condition in draft["conditions"]:
            baseline, trigger, recovery = _condition_values(condition)
            baseline_inputs[condition["point"]] = baseline
            trigger_inputs[condition["point"]] = trigger
            recovery_inputs[condition["point"]] = recovery
        post = [
            {
                "target": expectation["point"],
                "operator": "eq",
                "value": expectation["value"],
            }
            for expectation in draft["expectations"]
        ]
        non_triggered = [
            _non_triggered_expectation(expectation) for expectation in draft["expectations"]
        ]
        duration = max((float(item["seconds"]) for item in draft["durations"]), default=0.0)
        cases.append(
            {
                "oracle_id": draft["id"],
                "name": f"Independent trajectory for {draft['id']}",
                "baseline_inputs": baseline_inputs,
                "trigger_inputs": trigger_inputs,
                "recovery_inputs": recovery_inputs,
                "step_seconds": duration / 5.0 if duration else 1.0,
                "baseline_expectations": non_triggered,
                "pre_trigger_expectations": non_triggered if duration else [],
                "post_trigger_expectations": post,
                "recovery_expectations": non_triggered,
            }
        )
    return {
        "review_artifact_digest": record.artifact_digest,
        "author": "Independent Test Engineer",
        "cases": cases,
    }


def test_independent_oracle_approval_emits_timed_acceptance_cases(tmp_path: Path) -> None:
    record = _retained_review(tmp_path)
    result = compile_sequence_oracle_approval(
        record.id,
        record.model_dump(mode="json"),
        SequenceOracleApprovalRequest.model_validate(_oracle_payload(record)),
        author="Independent Test Engineer",
        actor_id=None,
        tenant_id=None,
        authentication="self-asserted-local",
    )

    assert result["approved_oracle_gate_passed"] is True
    assert result["sequence_requirement_gate_passed"] is False
    assert result["ready_for_graph_generation"] is False
    assert result["ready_for_deployment"] is False
    assert result["case_count"] == 2
    assert len(result["oracle_digest"]) == 64
    by_duration = {item["duration_seconds"]: item for item in result["validation_evidence"]}
    assert by_duration[300.0]["pre_expiration_steps"] == 4
    assert by_duration[10.0]["pre_expiration_steps"] == 4
    assert all(
        check["false_true_false_proven"]
        for evidence in result["validation_evidence"]
        for check in evidence["condition_checks"]
    )
    for case in result["acceptance_cases"]:
        assert [phase["name"] for phase in case["timeline"]] == [
            "baseline",
            "trigger-before-duration",
            "trigger-after-duration",
            "recovery",
        ]


def test_oracle_gate_rejects_self_review_bad_trigger_and_weakened_output(
    tmp_path: Path,
) -> None:
    record = _retained_review(tmp_path)
    payload = _oracle_payload(record)
    request = SequenceOracleApprovalRequest.model_validate(payload)
    with pytest.raises(ValueError, match="must differ"):
        compile_sequence_oracle_approval(
            record.id,
            record.model_dump(mode="json"),
            request,
            author="Controls Engineer",
            actor_id=None,
            tenant_id=None,
            authentication="self-asserted-local",
        )

    condition_point = record.result["oracle_drafts"][0]["conditions"][0]["point"]
    payload["cases"][0]["trigger_inputs"][condition_point] = payload["cases"][0]["baseline_inputs"][
        condition_point
    ]
    with pytest.raises(ValueError, match="trigger does not satisfy"):
        compile_sequence_oracle_approval(
            record.id,
            record.model_dump(mode="json"),
            SequenceOracleApprovalRequest.model_validate(payload),
            author="Independent Test Engineer",
            actor_id=None,
            tenant_id=None,
            authentication="self-asserted-local",
        )

    payload = _oracle_payload(record)
    payload["cases"][0]["post_trigger_expectations"][0]["value"] = 77.0
    with pytest.raises(ValueError, match="weaken or omit"):
        compile_sequence_oracle_approval(
            record.id,
            record.model_dump(mode="json"),
            SequenceOracleApprovalRequest.model_validate(payload),
            author="Independent Test Engineer",
            actor_id=None,
            tenant_id=None,
            authentication="self-asserted-local",
        )


def test_oracle_thresholds_are_converted_to_point_engineering_units(tmp_path: Path) -> None:
    sequence = (
        "If mixed-air temperature falls below 5 °C for 5 minutes, close the outdoor-air damper."
    )
    record = _retained_review(tmp_path, sequence)
    payload = _oracle_payload(record)
    case = payload["cases"][0]
    case["baseline_inputs"] = {"MixedAirTemp": 50.0}
    case["trigger_inputs"] = {"MixedAirTemp": 32.0}
    case["recovery_inputs"] = {"MixedAirTemp": 50.0}
    result = compile_sequence_oracle_approval(
        record.id,
        record.model_dump(mode="json"),
        SequenceOracleApprovalRequest.model_validate(payload),
        author="Independent Test Engineer",
        actor_id=None,
        tenant_id=None,
        authentication="self-asserted-local",
    )

    check = result["validation_evidence"][0]["condition_checks"][0]
    assert check["point_unit"] == "degF"
    assert check["threshold_in_point_units"] == pytest.approx(41.0)


def test_oracle_approval_api_persists_and_retrieves_exact_gate(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))
    library = CtrlFlowLibrary()
    document = parse_sequence_document(SEQUENCE.encode(), "sequence.txt")
    reconciliation = library.reconcile_sequence(AHU_TEMPLATE, {}, document)
    point_record = _retain_point_contract(client)
    review_response = client.post(
        f"/api/library/ctrl-flow/templates/{AHU_TEMPLATE}/review-requirements/approve",
        data={
            "selections": "{}",
            "review": json.dumps(_review_payload(reconciliation)),
            "point_reconciliation_id": point_record["point_reconciliation_id"],
        },
        files={"sequence_document": ("sequence.txt", SEQUENCE.encode(), "text/plain")},
    )
    assert review_response.status_code == 200, review_response.text
    review_payload = review_response.json()
    review_record_response = client.get(
        f"/api/sequence-requirement-reviews/{review_payload['review_id']}"
    )
    retained = review_record_response.json()
    request_payload = _oracle_payload(
        type(
            "Retained",
            (),
            {
                "artifact_digest": retained["artifact_digest"],
                "result": retained["result"],
            },
        )()
    )
    response = client.post(
        f"/api/sequence-requirement-reviews/{review_payload['review_id']}/oracles/approve",
        json=request_payload,
    )

    assert response.status_code == 200, response.text
    approved = response.json()
    assert approved["approved_oracle_gate_passed"] is True
    assert approved["ready_for_graph_generation"] is False
    assert approved["ready_for_deployment"] is False
    assert len(approved["oracle_approval_id"]) == 32
    assert (
        required_role(
            "POST",
            f"/api/sequence-requirement-reviews/{review_payload['review_id']}/oracles/approve",
        )
        is Role.APPROVER
    )
    fetched = client.get(f"/api/sequence-oracle-approvals/{approved['oracle_approval_id']}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["result"]["oracle_digest"] == approved["oracle_digest"]
    listing = client.get("/api/sequence-oracle-approvals")
    assert listing.json()["approvals"][0]["id"] == approved["oracle_approval_id"]


def test_retained_oracle_detects_manifest_tampering(tmp_path: Path) -> None:
    record = _retained_review(tmp_path)
    result = compile_sequence_oracle_approval(
        record.id,
        record.model_dump(mode="json"),
        SequenceOracleApprovalRequest.model_validate(_oracle_payload(record)),
        author="Independent Test Engineer",
        actor_id=None,
        tenant_id=None,
        authentication="self-asserted-local",
    )
    repository = SequenceOracleApprovalRepository(tmp_path / "oracles")
    approved = repository.save(result)
    assert repository.get(approved.id) == approved

    manifest = tmp_path / "oracles" / approved.id / "manifest.json"
    payload = json.loads(manifest.read_text())
    payload["result"]["case_count"] = 99
    manifest.write_text(json.dumps(payload))
    with pytest.raises(SequenceOracleIntegrityError, match="artifact digest changed"):
        repository.get(approved.id)


def test_authenticated_oracle_gate_requires_a_different_principal(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs", security_config=_security()))
    library = CtrlFlowLibrary()
    document = parse_sequence_document(SEQUENCE.encode(), "sequence.txt")
    reconciliation = library.reconcile_sequence(AHU_TEMPLATE, {}, document)
    point_record = _retain_point_contract(client, _bearer(REVIEWER_TOKEN))
    review_response = client.post(
        f"/api/library/ctrl-flow/templates/{AHU_TEMPLATE}/review-requirements/approve",
        headers=_bearer(REVIEWER_TOKEN),
        data={
            "selections": "{}",
            "review": json.dumps(_review_payload(reconciliation)),
            "point_reconciliation_id": point_record["point_reconciliation_id"],
        },
        files={"sequence_document": ("sequence.txt", SEQUENCE.encode(), "text/plain")},
    )
    assert review_response.status_code == 200, review_response.text
    review_id = review_response.json()["review_id"]
    retained_response = client.get(
        f"/api/sequence-requirement-reviews/{review_id}",
        headers=_bearer(REVIEWER_TOKEN),
    )
    retained = retained_response.json()
    request_payload = _oracle_payload(
        type(
            "Retained",
            (),
            {
                "artifact_digest": retained["artifact_digest"],
                "result": retained["result"],
            },
        )()
    )

    same_principal = client.post(
        f"/api/sequence-requirement-reviews/{review_id}/oracles/approve",
        headers=_bearer(REVIEWER_TOKEN),
        json=request_payload,
    )
    assert same_principal.status_code == 422
    assert "must differ" in same_principal.json()["detail"]

    independent = client.post(
        f"/api/sequence-requirement-reviews/{review_id}/oracles/approve",
        headers=_bearer(ORACLE_TOKEN),
        json=request_payload,
    )
    assert independent.status_code == 200, independent.text
    assert independent.json()["approval"]["actor_id"] == "oracle@example.com"
    assert independent.json()["approval"]["author"] == "Oracle Author"


def test_source_bound_boolean_facet_oracle_adds_an_executable_recovery_case(
    tmp_path: Path,
) -> None:
    record = _retained_review(tmp_path)
    retained = deepcopy(record.model_dump(mode="json"))
    retained["artifact_digest"] = "a" * 64
    retained["result"]["manual_facet_oracle_requirements"] = [
        {
            "scenario_id": "fire-smoke",
            "scenario_title": "Fire and smoke shutdown",
            "facet_id": "shutdown-actions",
            "facet_label": "fan and outdoor-air shutdown actions",
            "phrase_mentioned": True,
            "source_evidence": [
                {
                    "start": 0,
                    "end": 60,
                    "excerpt": "On smoke alarm, the supply fan is commanded off.",
                }
            ],
            "input_point_candidates": ["FireSmokeShutdown"],
            "output_point_candidates": ["SupplyFanCommand", "OutdoorDamperCommand"],
            "io_contract_status": "ready",
            "authoring_allowed": True,
            "blocking_reason": "Author an independent trajectory.",
        }
    ]
    payload = _oracle_payload(record)
    payload["review_artifact_digest"] = "a" * 64
    payload["facet_cases"] = [
        {
            "scenario_id": "fire-smoke",
            "facet_id": "shutdown-actions",
            "name": "Smoke shutdown and recovery",
            "baseline_inputs": {"FireSmokeShutdown": False},
            "trigger_inputs": {"FireSmokeShutdown": True},
            "recovery_inputs": {"FireSmokeShutdown": False},
            "step_seconds": 1.0,
            "baseline_expectations": [
                {"target": "SupplyFanCommand", "operator": "eq", "value": True}
            ],
            "trigger_expectations": [
                {"target": "SupplyFanCommand", "operator": "eq", "value": False}
            ],
            "recovery_expectations": [
                {"target": "SupplyFanCommand", "operator": "eq", "value": True}
            ],
        }
    ]
    result = compile_sequence_oracle_approval(
        record.id,
        retained,
        SequenceOracleApprovalRequest.model_validate(payload),
        author="Independent Test Engineer",
        actor_id=None,
        tenant_id=None,
        authentication="self-asserted-local",
    )

    assert result["case_count"] == 3
    assert result["ready_for_graph_generation"] is True
    facet_evidence = next(
        item
        for item in result["validation_evidence"]
        if item.get("kind") == "manual-scenario-facet"
    )
    assert facet_evidence["changed_and_recovered_inputs"] == ["FireSmokeShutdown"]
    assert facet_evidence["changed_and_recovered_outputs"] == ["SupplyFanCommand"]
    assert [phase["name"] for phase in result["acceptance_cases"][-1]["timeline"]] == [
        "baseline",
        "trigger",
        "recovery",
    ]


def test_event_only_sequence_can_author_manual_trajectories_without_fake_numeric_case(
    tmp_path: Path,
) -> None:
    sequence = (
        "When the smoke shutdown input is active, stop the supply fan and close the outdoor "
        "air damper. When the smoke input clears, restart the supply fan and open the outdoor "
        "air damper."
    )
    record = _retained_review(tmp_path, sequence)
    assert record.result["oracle_draft_count"] == 0
    assert record.result["authorable_manual_facet_count"] > 0
    assert record.result["ready_for_independent_oracle_authoring"] is True

    point_by_id = {
        point["id"]: point for point in record.result["point_contract"]["points"]
    }
    facet_cases = []
    for requirement in record.result["manual_facet_oracle_requirements"]:
        if not requirement["authoring_allowed"]:
            continue
        input_point = requirement["input_point_candidates"][0]
        output_point = requirement["output_point_candidates"][0]
        input_is_boolean = point_by_id[input_point]["data_type"] == "boolean"
        output_is_boolean = point_by_id[output_point]["data_type"] == "boolean"
        facet_cases.append(
            {
                "scenario_id": requirement["scenario_id"],
                "facet_id": requirement["facet_id"],
                "name": f"{requirement['scenario_title']} event trajectory",
                "baseline_inputs": {input_point: False if input_is_boolean else 0.0},
                "trigger_inputs": {input_point: True if input_is_boolean else 1.0},
                "recovery_inputs": {input_point: False if input_is_boolean else 0.0},
                "step_seconds": 1.0,
                "baseline_expectations": [
                    {
                        "target": output_point,
                        "operator": "eq",
                        "value": False if output_is_boolean else 0.0,
                    }
                ],
                "trigger_expectations": [
                    {
                        "target": output_point,
                        "operator": "eq",
                        "value": True if output_is_boolean else 1.0,
                    }
                ],
                "recovery_expectations": [
                    {
                        "target": output_point,
                        "operator": "eq",
                        "value": False if output_is_boolean else 0.0,
                    }
                ],
            }
        )
    request = SequenceOracleApprovalRequest.model_validate(
        {
            "review_artifact_digest": record.artifact_digest,
            "author": "Independent Event Test Engineer",
            "cases": [],
            "facet_cases": facet_cases,
        }
    )
    result = compile_sequence_oracle_approval(
        record.id,
        record.model_dump(mode="json"),
        request,
        author="Independent Event Test Engineer",
        actor_id=None,
        tenant_id=None,
        authentication="self-asserted-local",
    )

    assert result["approved_oracle_gate_passed"] is True
    assert result["case_count"] == len(facet_cases)
    assert result["ready_for_graph_generation"] is False
    assert all(
        evidence["kind"] == "manual-scenario-facet"
        for evidence in result["validation_evidence"]
    )


def test_oracle_request_rejects_an_empty_approval() -> None:
    with pytest.raises(ValueError, match="at least one executable trajectory"):
        SequenceOracleApprovalRequest.model_validate(
            {
                "review_artifact_digest": "a" * 64,
                "author": "Independent Test Engineer",
                "cases": [],
                "facet_cases": [],
            }
        )


def test_manual_facet_oracle_is_exhaustive_and_rejects_non_recovery(tmp_path: Path) -> None:
    record = _retained_review(tmp_path)
    retained = deepcopy(record.model_dump(mode="json"))
    retained["artifact_digest"] = "b" * 64
    retained["result"]["manual_facet_oracle_requirements"] = [
        {
            "scenario_id": "communications-loss",
            "scenario_title": "Communications loss",
            "facet_id": "loss-detection",
            "facet_label": "communications loss detection",
            "phrase_mentioned": True,
            "source_evidence": [{"start": 0, "end": 10, "excerpt": "communications loss"}],
            "input_point_candidates": ["CommunicationsHealthy"],
            "output_point_candidates": ["CommunicationsAlarm"],
            "io_contract_status": "ready",
            "authoring_allowed": True,
            "blocking_reason": "Author an independent trajectory.",
        }
    ]
    payload = _oracle_payload(record)
    payload["review_artifact_digest"] = "b" * 64
    with pytest.raises(ValueError, match="must cover every source-mentioned facet"):
        compile_sequence_oracle_approval(
            record.id,
            retained,
            SequenceOracleApprovalRequest.model_validate(payload),
            author="Independent Test Engineer",
            actor_id=None,
            tenant_id=None,
            authentication="self-asserted-local",
        )

    payload["facet_cases"] = [
        {
            "scenario_id": "communications-loss",
            "facet_id": "loss-detection",
            "name": "Communications fallback",
            "baseline_inputs": {"CommunicationsHealthy": True},
            "trigger_inputs": {"CommunicationsHealthy": False},
            "recovery_inputs": {"CommunicationsHealthy": False},
            "step_seconds": 1.0,
            "baseline_expectations": [
                {"target": "CommunicationsAlarm", "operator": "eq", "value": False}
            ],
            "trigger_expectations": [
                {"target": "CommunicationsAlarm", "operator": "eq", "value": True}
            ],
            "recovery_expectations": [
                {"target": "CommunicationsAlarm", "operator": "eq", "value": False}
            ],
        }
    ]
    with pytest.raises(ValueError, match="return it to baseline"):
        compile_sequence_oracle_approval(
            record.id,
            retained,
            SequenceOracleApprovalRequest.model_validate(payload),
            author="Independent Test Engineer",
            actor_id=None,
            tenant_id=None,
            authentication="self-asserted-local",
        )

    case = payload["facet_cases"][0]
    case["baseline_inputs"] = {"FireSmokeShutdown": False}
    case["trigger_inputs"] = {"FireSmokeShutdown": True}
    case["recovery_inputs"] = {"FireSmokeShutdown": False}
    with pytest.raises(ValueError, match="outside the audited scenario I/O contract"):
        compile_sequence_oracle_approval(
            record.id,
            retained,
            SequenceOracleApprovalRequest.model_validate(payload),
            author="Independent Test Engineer",
            actor_id=None,
            tenant_id=None,
            authentication="self-asserted-local",
        )

    case["baseline_inputs"] = {"CommunicationsHealthy": True}
    case["trigger_inputs"] = {"CommunicationsHealthy": False}
    case["recovery_inputs"] = {"CommunicationsHealthy": True}
    for phase in (
        "baseline_expectations",
        "trigger_expectations",
        "recovery_expectations",
    ):
        case[phase][0]["target"] = "SupplyFanCommand"
    with pytest.raises(ValueError, match="outside the audited scenario I/O contract"):
        compile_sequence_oracle_approval(
            record.id,
            retained,
            SequenceOracleApprovalRequest.model_validate(payload),
            author="Independent Test Engineer",
            actor_id=None,
            tenant_id=None,
            authentication="self-asserted-local",
        )
