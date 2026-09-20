from __future__ import annotations

import pytest

from bactalk.domain import (
    AcceptanceCase,
    AcceptancePhase,
    Block,
    BlockKind,
    ControlGraph,
    Link,
    OutputExpectation,
)
from bactalk.sequence_candidate import (
    SequenceCandidatePreflightRequest,
    compile_sequence_candidate_preflight,
)

CONFIGURATION_DIGEST = "a" * 64
ORACLE_ARTIFACT_DIGEST = "b" * 64
REVIEW_ARTIFACT_DIGEST = "c" * 64
POINT_ARTIFACT_DIGEST = "d" * 64


def _graph() -> ControlGraph:
    return ControlGraph(
        name="ReferenceCandidate",
        blocks=[
            Block(
                id="Input",
                label="Input",
                kind=BlockKind.NUMERIC_INPUT,
                config={"default": 0.0},
            ),
            Block(
                id="Output",
                label="Output",
                kind=BlockKind.NUMERIC_OUTPUT,
            ),
        ],
        links=[Link(source="Input", target="Output", target_slot="in")],
        metadata={"sequence_family": "TEST_REFERENCE"},
    )


def _acceptance_case() -> AcceptanceCase:
    baseline = OutputExpectation(target="DamperCommand", value=0.0)
    trigger = OutputExpectation(target="DamperCommand", value=1.0)
    return AcceptanceCase(
        name="Bound event and recovery",
        expectations=[baseline],
        timeline=[
            AcceptancePhase(
                name="baseline",
                inputs={"ZoneTemp": 0.0},
                expectations=[baseline],
            ),
            AcceptancePhase(
                name="trigger",
                inputs={"ZoneTemp": 1.0},
                expectations=[trigger],
            ),
            AcceptancePhase(
                name="recovery",
                inputs={"ZoneTemp": 0.0},
                expectations=[baseline],
            ),
        ],
    )


def _records(*, oracle_ready: bool = True) -> tuple[dict, dict, dict, dict]:
    point_id = "1" * 32
    review_id = "2" * 32
    oracle_id = "3" * 32
    point_record = {
        "id": point_id,
        "artifact_digest": POINT_ARTIFACT_DIGEST,
        "configuration_digest": CONFIGURATION_DIGEST,
        "result": {
            "configuration_digest": CONFIGURATION_DIGEST,
            "ready_for_sequence_reconciliation": True,
            "blocking_issues": [],
            "unit_conversions": [],
        },
    }
    review_record = {
        "id": review_id,
        "artifact_digest": REVIEW_ARTIFACT_DIGEST,
        "result": {
            "configuration_digest": CONFIGURATION_DIGEST,
            "contractor_point_reconciliation": {
                "id": point_id,
                "artifact_digest": POINT_ARTIFACT_DIGEST,
            },
            "point_contract": {
                "points": [
                    {"id": "ZoneTemp", "data_type": "numeric", "role": "sensor"},
                    {
                        "id": "DamperCommand",
                        "data_type": "numeric",
                        "role": "command",
                    },
                ]
            },
        },
    }
    oracle_record = {
        "id": oracle_id,
        "review_id": review_id,
        "review_artifact_digest": REVIEW_ARTIFACT_DIGEST,
        "artifact_digest": ORACLE_ARTIFACT_DIGEST,
        "result": {
            "ready_for_graph_generation": oracle_ready,
            "scenario_oracle_gap_count": 0 if oracle_ready else 7,
            "acceptance_cases": [_acceptance_case().model_dump(mode="json")],
        },
    }
    brief = {
        "configuration_digest": CONFIGURATION_DIGEST,
        "design_binding": {"controller_id": "Example.Controller"},
    }
    return oracle_record, review_record, point_record, brief


class _PassingLibrary:
    def parameter_schema(self, controller_id: str) -> dict:
        assert controller_id == "Example.Controller"
        return {
            "schema": "bactalk.g36-parameter-schema/v1",
            "parameterization": {
                "required_parameters": [],
                "parameters": [],
            },
        }

    def translate(self, controller_id: str, **_: object) -> dict:
        assert controller_id == "Example.Controller"
        return {
            "typed_ir": _graph().model_dump(mode="json"),
            "lowering": {"translatable": True},
            "product_status": "executable",
        }

    def assess_niagara_source_target(self, translation: dict) -> dict:
        assert translation["typed_ir"]
        return {"complete": True, "generated_program_count": 1}


class _MissingParameterLibrary(_PassingLibrary):
    def parameter_schema(self, controller_id: str) -> dict:
        result = super().parameter_schema(controller_id)
        result["parameterization"]["required_parameters"] = ["designFlow"]
        return result


class _FailingLibrary(_PassingLibrary):
    def translate(self, controller_id: str, **_: object) -> dict:
        raise RuntimeError("CXF validation failed\nerror|class-not-found|nested controller")


def _request(**updates: object) -> SequenceCandidatePreflightRequest:
    payload = {
        "oracle_artifact_digest": ORACLE_ARTIFACT_DIGEST,
        "point_bindings": {"ZoneTemp": "Input", "DamperCommand": "Output"},
    }
    payload.update(updates)
    return SequenceCandidatePreflightRequest.model_validate(payload)


def test_candidate_preflight_proves_chain_boundary_bindings_and_approved_tests() -> None:
    oracle, review, points, brief = _records()
    result = compile_sequence_candidate_preflight(
        oracle_record=oracle,
        review_record=review,
        point_record=points,
        programming_brief=brief,
        request=_request(),
        g36_library=_PassingLibrary(),
    )

    assert result["blockers"] == []
    assert result["translation"]["passed"] is True
    assert result["candidate_graph"]["block_count"] == 2
    assert result["test_report"]["passed"] is True
    assert result["ready_for_candidate_generation"] is True
    assert result["ready_for_deployment"] is False


def test_candidate_preflight_reports_missing_parameters_and_oracle_coverage() -> None:
    oracle, review, points, brief = _records(oracle_ready=False)
    result = compile_sequence_candidate_preflight(
        oracle_record=oracle,
        review_record=review,
        point_record=points,
        programming_brief=brief,
        request=_request(),
        g36_library=_MissingParameterLibrary(),
    )

    assert {item["code"] for item in result["blockers"]} == {
        "controller-parameters-missing",
        "sequence-oracle-coverage-incomplete",
    }
    assert result["translation"] == {"attempted": False}
    assert result["ready_for_candidate_generation"] is False


def test_candidate_preflight_preserves_bounded_translation_diagnostics() -> None:
    oracle, review, points, brief = _records()
    result = compile_sequence_candidate_preflight(
        oracle_record=oracle,
        review_record=review,
        point_record=points,
        programming_brief=brief,
        request=_request(),
        g36_library=_FailingLibrary(),
    )

    assert result["blockers"][0]["code"] == "controller-translation-failed"
    assert result["translation"]["diagnostic_line_count"] == 2
    assert result["translation"]["diagnostics"][1].startswith("error|class-not-found")


def test_candidate_preflight_rejects_digest_chain_tampering() -> None:
    oracle, review, points, brief = _records()
    points["artifact_digest"] = "e" * 64
    with pytest.raises(ValueError, match="point reconciliation artifact changed"):
        compile_sequence_candidate_preflight(
            oracle_record=oracle,
            review_record=review,
            point_record=points,
            programming_brief=brief,
            request=_request(),
            g36_library=_PassingLibrary(),
        )
