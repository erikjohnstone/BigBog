from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from bactalk.domain import (
    AcceptanceCase,
    AcceptancePhase,
    Block,
    BlockKind,
    ControlGraph,
    Link,
    OutputExpectation,
    RunStatus,
    canonical_json,
)
from bactalk.repository import RunRepository
from bactalk.sequence_candidate import (
    SequenceCandidateGenerationRequest,
    SequenceCandidatePreflightRequest,
    build_sequence_candidate_job,
    compile_sequence_candidate_preflight,
)
from bactalk.service import WorkbenchService
from bactalk.simulator import run_acceptance_suite

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
            "canonical_points": [
                {
                    "name": "ZoneTemp",
                    "label": "Zone temperature",
                    "data_type": "numeric",
                    "role": "sensor",
                    "default": 0.0,
                    "required": True,
                },
                {
                    "name": "DamperCommand",
                    "label": "Damper command",
                    "data_type": "numeric",
                    "role": "command",
                    "default": 0.0,
                    "required": True,
                },
            ],
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
        "design_binding": {
            "controller_id": "Example.Controller",
            "equipment_family": "ahu.multi-zone-vav",
        },
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


class _ExtraOutputLibrary(_PassingLibrary):
    def translate(self, controller_id: str, **_: object) -> dict:
        graph = _graph()
        graph = graph.model_copy(
            update={
                "blocks": [
                    *graph.blocks,
                    Block(
                        id="AlarmOutput",
                        label="Alarm output",
                        kind=BlockKind.NUMERIC_OUTPUT,
                    ),
                ],
                "links": [
                    *graph.links,
                    Link(source="Input", target="AlarmOutput", target_slot="in"),
                ],
            }
        )
        return {
            "typed_ir": graph.model_dump(mode="json"),
            "lowering": {"translatable": True},
            "product_status": "executable",
        }


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


def test_candidate_preflight_requires_every_translated_output_in_independent_oracles() -> None:
    oracle, review, points, brief = _records()
    review["result"]["point_contract"]["points"].append(
        {"id": "Alarm", "data_type": "numeric", "role": "alarm"}
    )
    points["result"]["canonical_points"].append(
        {
            "name": "Alarm",
            "label": "Alarm",
            "data_type": "numeric",
            "role": "alarm",
            "default": 0.0,
            "required": True,
        }
    )

    result = compile_sequence_candidate_preflight(
        oracle_record=oracle,
        review_record=review,
        point_record=points,
        programming_brief=brief,
        request=_request(
            point_bindings={
                "ZoneTemp": "Input",
                "DamperCommand": "Output",
                "Alarm": "AlarmOutput",
            }
        ),
        g36_library=_ExtraOutputLibrary(),
    )

    blocker = next(
        item
        for item in result["blockers"]
        if item["code"] == "graph-output-oracle-coverage-incomplete"
    )
    assert blocker["details"]["graph_outputs"] == ["AlarmOutput"]
    assert result["ready_for_candidate_generation"] is False


def test_passing_preflight_builds_the_exact_replayable_contractor_job() -> None:
    oracle, review, points, brief = _records()
    request = SequenceCandidateGenerationRequest(
        name="Approved AHU controller",
        site="Qualification Campus",
        equipment_name="AHU_1",
        oracle_artifact_digest=ORACLE_ARTIFACT_DIGEST,
        point_bindings={"ZoneTemp": "Input", "DamperCommand": "Output"},
    )

    preflight, job = build_sequence_candidate_job(
        oracle_record=oracle,
        review_record=review,
        point_record=points,
        programming_brief=brief,
        request=request,
        g36_library=_PassingLibrary(),
    )

    assert preflight["ready_for_candidate_generation"] is True
    assert job is not None
    assert job.sequence.library == "g36"
    assert job.control_graph is not None
    assert [point.name for point in job.points] == ["Input", "Output"]
    assert job.points[0].source_name == "ZoneTemp"
    assert job.acceptance_tests[0].timeline[1].inputs == {"Input": 1.0}
    assert job.acceptance_tests[0].timeline[1].expectations[0].target == "Output"
    assert run_acceptance_suite(job.control_graph, job).passed is True


def test_approved_document_job_materializes_signed_niagara_candidate(
    tmp_path: Path,
) -> None:
    oracle, review, points, brief = _records()
    preflight, job = build_sequence_candidate_job(
        oracle_record=oracle,
        review_record=review,
        point_record=points,
        programming_brief=brief,
        request=SequenceCandidateGenerationRequest(
            name="Approved AHU controller",
            site="Qualification Campus",
            equipment_name="AHU_1",
            oracle_artifact_digest=ORACLE_ARTIFACT_DIGEST,
            point_bindings={"ZoneTemp": "Input", "DamperCommand": "Output"},
        ),
        g36_library=_PassingLibrary(),
    )
    assert job is not None

    repository = RunRepository(tmp_path / "runs")
    record = WorkbenchService(repository).create_run(
        job,
        source_documents={
            "points.csv": b"name,label\nZoneTemp,Zone temperature\n",
            "sequence.txt": b"The damper command shall follow zone temperature.\n",
            "approved-sequence-evidence.json": canonical_json(preflight).encode(),
        },
    )

    assert record.status == RunStatus.READY_FOR_REVIEW
    assert record.bog_path is not None
    assert Path(record.bog_path).is_file()
    assert len(record.source_artifact_paths) == 3
    retained_graph = ControlGraph.model_validate_json(Path(record.graph_path).read_text())
    assert (
        hashlib.sha256(canonical_json(retained_graph).encode()).hexdigest()
        == preflight["candidate_graph"]["sha256"]
    )
