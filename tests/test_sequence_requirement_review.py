from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bactalk.api import create_app
from bactalk.intake import parse_sequence_document
from bactalk.integrations.ctrl_flow import CtrlFlowLibrary
from bactalk.integrations.ctrl_flow_planning import AHU_TEMPLATE
from bactalk.security import Role, required_role
from bactalk.sequence_requirements import SequenceRequirementReviewRequest
from bactalk.sequence_review_repository import (
    SequenceRequirementReviewRepository,
    SequenceReviewIntegrityError,
)

REVIEWABLE_SEQUENCE = """
If mixed-air temperature falls below 38 °F for 5 minutes, close the outdoor-air damper.
If duct static pressure exceeds 1.5 in. w.c. for 10 seconds, stop the supply fan.
""".strip()


def _inspection():
    document = parse_sequence_document(REVIEWABLE_SEQUENCE.encode(), "reviewable-sequence.txt")
    reconciliation = CtrlFlowLibrary().reconcile_sequence(AHU_TEMPLATE, {}, document)
    return document, reconciliation


def _review_payload(reconciliation: dict) -> dict:
    candidates = reconciliation["requirement_candidates"]
    decisions = []
    for group in ("quantities", "actions", "policies"):
        for item in candidates[group]:
            selected_point = None
            point_candidates = item.get("point_candidates", item.get("input_point_candidates", []))
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
    for item in candidates["unresolved"]:
        decisions.append(
            {
                "candidate_id": item["id"],
                "disposition": "resolve",
                "replacement_text": "Resolved in a forthcoming source revision.",
                "note": "Revise and re-upload the contractor sequence.",
            }
        )
    return {
        "candidate_digest": candidates["candidate_digest"],
        "reviewer": "Controls Engineer",
        "decisions": decisions,
    }


def test_exhaustive_review_emits_source_bound_non_executable_oracle_drafts() -> None:
    document, reconciliation = _inspection()
    payload = _review_payload(reconciliation)
    review = CtrlFlowLibrary().review_sequence_requirements(
        AHU_TEMPLATE,
        {},
        document,
        SequenceRequirementReviewRequest.model_validate(payload),
        reviewer="Controls Engineer",
        actor_id=None,
        tenant_id=None,
        authentication="self-asserted-local",
    )

    assert review["blockers"] == []
    assert review["ready_for_independent_oracle_authoring"] is True
    assert review["ready_for_graph_generation"] is False
    assert review["ready_for_deployment"] is False
    assert review["oracle_draft_count"] == 2
    assert len(review["review_digest"]) == 64
    assert review["source_sha256"] == document.sha256
    assert review["safety"]["text_approval_authorizes_deployment"] is False

    by_input = {
        draft["conditions"][0]["point"]: draft for draft in review["oracle_drafts"]
    }
    mixed_air = by_input["MixedAirTemp"]
    assert mixed_air["conditions"][0]["operator"] == "lt"
    assert mixed_air["conditions"][0]["value"] == 38.0
    assert mixed_air["durations"][0]["seconds"] == 300.0
    assert mixed_air["expectations"] == [
        {
            "point": "OutdoorDamperCommand",
            "operator": "eq",
            "value": 0.0,
            "verb": "close",
            "action_candidate_id": mixed_air["expectations"][0]["action_candidate_id"],
            "command_value_candidate_id": None,
        }
    ]
    duct = by_input["DuctStatic"]
    assert duct["durations"][0]["seconds"] == 10.0
    assert duct["expectations"][0]["point"] == "SupplyFanCommand"
    assert duct["expectations"][0]["value"] is False
    assert all(draft["executable"] is False for draft in review["oracle_drafts"])


def test_review_rederivation_rejects_digest_tampering_and_incomplete_decisions() -> None:
    document, reconciliation = _inspection()
    payload = _review_payload(reconciliation)
    payload["candidate_digest"] = "0" * 64
    with pytest.raises(ValueError, match="candidate digest changed"):
        CtrlFlowLibrary().review_sequence_requirements(
            AHU_TEMPLATE,
            {},
            document,
            SequenceRequirementReviewRequest.model_validate(payload),
            reviewer="Controls Engineer",
            actor_id=None,
            tenant_id=None,
            authentication="self-asserted-local",
        )

    payload = _review_payload(reconciliation)
    payload["decisions"] = payload["decisions"][:-1]
    with pytest.raises(ValueError, match="must decide every candidate"):
        CtrlFlowLibrary().review_sequence_requirements(
            AHU_TEMPLATE,
            {},
            document,
            SequenceRequirementReviewRequest.model_validate(payload),
            reviewer="Controls Engineer",
            actor_id=None,
            tenant_id=None,
            authentication="self-asserted-local",
        )


def test_vague_language_requires_source_revision_even_after_review_resolution() -> None:
    sequence = REVIEWABLE_SEQUENCE + "\nAfter a short delay, restart the system as required."
    document = parse_sequence_document(sequence.encode(), "vague-sequence.txt")
    reconciliation = CtrlFlowLibrary().reconcile_sequence(AHU_TEMPLATE, {}, document)
    payload = _review_payload(reconciliation)
    review = CtrlFlowLibrary().review_sequence_requirements(
        AHU_TEMPLATE,
        {},
        document,
        SequenceRequirementReviewRequest.model_validate(payload),
        reviewer="Controls Engineer",
        actor_id=None,
        tenant_id=None,
        authentication="self-asserted-local",
    )

    assert review["ready_for_independent_oracle_authoring"] is False
    assert any("source document and reinspection" in blocker for blocker in review["blockers"])


def test_review_approval_api_rederives_the_uploaded_source(tmp_path: Path) -> None:
    document, reconciliation = _inspection()
    client = TestClient(create_app(tmp_path / "runs"))
    response = client.post(
        f"/api/library/ctrl-flow/templates/{AHU_TEMPLATE}/review-requirements/approve",
        data={
            "selections": "{}",
            "review": json.dumps(_review_payload(reconciliation)),
        },
        files={
            "sequence_document": (
                document.filename,
                REVIEWABLE_SEQUENCE.encode(),
                "text/plain",
            )
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema"] == "bactalk.sequence-requirement-review/v1"
    assert payload["review"]["reviewer"] == "Controls Engineer"
    assert payload["review"]["authentication"] == "self-asserted-local"
    assert payload["oracle_draft_count"] == 2
    assert payload["ready_for_graph_generation"] is False
    assert len(payload["review_id"]) == 32
    assert payload["retention"]["source_bytes_retained"] is True
    assert payload["retention"]["external_immutable_retention"] is False
    retained = client.get(f"/api/sequence-requirement-reviews/{payload['review_id']}")
    assert retained.status_code == 200, retained.text
    record = retained.json()
    assert record["result"]["review_digest"] == payload["review_digest"]
    assert record["source_sha256"] == document.sha256
    listing = client.get("/api/sequence-requirement-reviews")
    assert listing.status_code == 200, listing.text
    assert listing.json()["reviews"][0]["id"] == payload["review_id"]
    assert (
        required_role(
            "POST",
            f"/api/library/ctrl-flow/templates/{AHU_TEMPLATE}/review-requirements/approve",
        )
        is Role.APPROVER
    )


def test_retained_review_detects_source_and_manifest_tampering(tmp_path: Path) -> None:
    document, reconciliation = _inspection()
    result = CtrlFlowLibrary().review_sequence_requirements(
        AHU_TEMPLATE,
        {},
        document,
        SequenceRequirementReviewRequest.model_validate(_review_payload(reconciliation)),
        reviewer="Controls Engineer",
        actor_id=None,
        tenant_id=None,
        authentication="self-asserted-local",
    )
    repository = SequenceRequirementReviewRepository(tmp_path / "reviews")
    record = repository.save(
        template_id=AHU_TEMPLATE,
        selections={},
        source_content=REVIEWABLE_SEQUENCE.encode(),
        source_filename=document.filename,
        source_media_type=document.media_type,
        result=result,
    )

    assert repository.get(record.id) == record
    assert repository.source(record.id) == REVIEWABLE_SEQUENCE.encode()
    assert repository.list() == [record]

    source = tmp_path / "reviews" / record.id / "source.bin"
    source.write_bytes(b"changed")
    with pytest.raises(SequenceReviewIntegrityError, match="source hash changed"):
        repository.get(record.id)


def test_retained_review_rejects_mismatched_source_bytes(tmp_path: Path) -> None:
    document, reconciliation = _inspection()
    result = CtrlFlowLibrary().review_sequence_requirements(
        AHU_TEMPLATE,
        {},
        document,
        SequenceRequirementReviewRequest.model_validate(_review_payload(reconciliation)),
        reviewer="Controls Engineer",
        actor_id=None,
        tenant_id=None,
        authentication="self-asserted-local",
    )
    repository = SequenceRequirementReviewRepository(tmp_path / "reviews")

    with pytest.raises(SequenceReviewIntegrityError, match="source hash does not match"):
        repository.save(
            template_id=AHU_TEMPLATE,
            selections={},
            source_content=b"different source",
            source_filename=document.filename,
            source_media_type=document.media_type,
            result=result,
        )
