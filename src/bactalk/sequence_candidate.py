from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bactalk.domain import (
    AcceptanceCase,
    AcceptancePhase,
    BlockKind,
    ControlGraph,
    FaultInjection,
    OutputExpectation,
    canonical_json,
)
from bactalk.simulator import run_generic_acceptance_suite


class SequenceCandidatePreflightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    oracle_artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    controller_parameters: dict[str, Any] = Field(default_factory=dict, max_length=1_000)
    point_bindings: dict[str, str] = Field(default_factory=dict, max_length=10_000)
    execution_profile: Literal["modelica_exact", "host_tick_v1"] = "modelica_exact"

    @model_validator(mode="after")
    def bindings_are_one_to_one(self) -> SequenceCandidatePreflightRequest:
        if len(set(self.point_bindings.values())) != len(self.point_bindings):
            raise ValueError("candidate point bindings must be one-to-one")
        return self


def _blocker(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def _bound(identifier: str, bindings: dict[str, str]) -> str:
    return bindings.get(identifier, identifier)


def _bind_expectation(
    expectation: OutputExpectation,
    bindings: dict[str, str],
) -> OutputExpectation:
    return expectation.model_copy(
        update={"target": _bound(expectation.target, bindings)}
    )


def _bind_fault(
    fault: FaultInjection,
    bindings: dict[str, str],
) -> FaultInjection:
    return fault.model_copy(
        update={
            "target": _bound(fault.target, bindings),
            "quality_target": (
                _bound(fault.quality_target, bindings)
                if fault.quality_target is not None
                else None
            ),
        }
    )


def _bind_case(
    case: AcceptanceCase,
    bindings: dict[str, str],
) -> AcceptanceCase:
    timeline = [
        phase.model_copy(
            update={
                "inputs": {
                    _bound(point, bindings): value
                    for point, value in phase.inputs.items()
                },
                "expectations": [
                    _bind_expectation(expectation, bindings)
                    for expectation in phase.expectations
                ],
                "faults": [_bind_fault(fault, bindings) for fault in phase.faults],
            }
        )
        for phase in case.timeline
    ]
    return case.model_copy(
        update={
            "inputs": {
                _bound(point, bindings): value for point, value in case.inputs.items()
            },
            "expectations": [
                _bind_expectation(expectation, bindings)
                for expectation in case.expectations
            ],
            "faults": [_bind_fault(fault, bindings) for fault in case.faults],
            "timeline": [AcceptancePhase.model_validate(phase) for phase in timeline],
        }
    )


def _case_point_sets(cases: list[AcceptanceCase]) -> tuple[set[str], set[str]]:
    inputs: set[str] = set()
    outputs: set[str] = set()
    for case in cases:
        inputs.update(case.inputs)
        outputs.update(expectation.target for expectation in case.expectations)
        for phase in case.timeline:
            inputs.update(phase.inputs)
            outputs.update(expectation.target for expectation in phase.expectations)
    return inputs, outputs


def compile_sequence_candidate_preflight(
    *,
    oracle_record: dict[str, Any],
    review_record: dict[str, Any],
    point_record: dict[str, Any],
    programming_brief: dict[str, Any],
    request: SequenceCandidatePreflightRequest,
    g36_library: Any,
) -> dict[str, Any]:
    """Prove the immutable chain and test a reference graph without retaining a candidate."""

    if request.oracle_artifact_digest != oracle_record.get("artifact_digest"):
        raise ValueError("sequence oracle artifact changed; reload the retained approval")
    oracle = oracle_record["result"]
    review = review_record["result"]
    if oracle_record.get("review_id") != review_record.get("id"):
        raise ValueError("sequence oracle approval references a different requirement review")
    if oracle_record.get("review_artifact_digest") != review_record.get(
        "artifact_digest"
    ):
        raise ValueError("sequence requirement review artifact changed after oracle approval")
    point_evidence = review.get("contractor_point_reconciliation")
    if not isinstance(point_evidence, dict):
        raise ValueError(
            "sequence review predates retained contractor points; repeat requirement review"
        )
    if point_evidence.get("id") != point_record.get("id"):
        raise ValueError("sequence review references a different contractor point artifact")
    if point_evidence.get("artifact_digest") != point_record.get("artifact_digest"):
        raise ValueError("contractor point reconciliation artifact changed")
    point_result = point_record["result"]
    configuration_digest = programming_brief["configuration_digest"]
    if any(
        digest != configuration_digest
        for digest in (
            review.get("configuration_digest"),
            point_record.get("configuration_digest"),
            point_result.get("configuration_digest"),
        )
    ):
        raise ValueError("ctrl-flow configuration changed across retained artifacts")

    controller_id = programming_brief["design_binding"]["controller_id"]
    blockers: list[dict[str, Any]] = []
    if not point_result.get("ready_for_sequence_reconciliation", False):
        blockers.append(
            _blocker(
                "contractor-points-blocked",
                "The retained contractor point reconciliation does not pass.",
                blocking_issues=point_result.get("blocking_issues", []),
            )
        )
    if not oracle.get("ready_for_graph_generation", False):
        blockers.append(
            _blocker(
                "sequence-oracle-coverage-incomplete",
                "Every selected scenario facet needs an approved executable oracle.",
                scenario_oracle_gap_count=oracle.get("scenario_oracle_gap_count"),
            )
        )
    conversions = point_result.get("unit_conversions", [])
    if conversions:
        blockers.append(
            _blocker(
                "unit-converter-lowering-required",
                "Explicit unit converters must be inserted before the candidate can run.",
                conversions=conversions,
            )
        )

    parameter_contract = g36_library.parameter_schema(controller_id)
    parameterization = parameter_contract["parameterization"]
    required_parameters = set(parameterization.get("required_parameters", []))
    missing_parameters = sorted(required_parameters - set(request.controller_parameters))
    if missing_parameters:
        blockers.append(
            _blocker(
                "controller-parameters-missing",
                "Required controller parameters are missing.",
                parameters=missing_parameters,
            )
        )

    result: dict[str, Any] = {
        "schema": "bactalk.sequence-candidate-preflight/v1",
        "oracle_approval_id": oracle_record["id"],
        "review_id": review_record["id"],
        "point_reconciliation_id": point_record["id"],
        "configuration_digest": configuration_digest,
        "controller_id": controller_id,
        "execution_profile": request.execution_profile,
        "parameter_contract": parameter_contract,
        "provided_parameter_names": sorted(request.controller_parameters),
        "point_bindings": dict(sorted(request.point_bindings.items())),
        "translation": {"attempted": False},
        "candidate_graph": None,
        "test_report": None,
        "blockers": blockers,
        "ready_for_candidate_generation": False,
        "ready_for_deployment": False,
        "safety": {
            "live_writes_enabled": False,
            "preflight_retains_candidate": False,
            "preflight_authorizes_deployment": False,
        },
    }
    if blockers:
        return result

    try:
        translation = g36_library.translate(
            controller_id,
            execution_profile=request.execution_profile,
            parameters=request.controller_parameters,
        )
    except Exception as exc:
        message = str(exc)
        result["translation"] = {
            "attempted": True,
            "passed": False,
            "error_type": type(exc).__name__,
            "error_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
            "diagnostics": message.splitlines()[:25],
            "diagnostic_line_count": len(message.splitlines()),
        }
        result["blockers"].append(
            _blocker(
                "controller-translation-failed",
                "The pinned G36 controller did not lower into executable typed IR.",
                error_type=type(exc).__name__,
            )
        )
        return result

    typed_ir = translation.get("typed_ir")
    result["translation"] = {
        "attempted": True,
        "passed": typed_ir is not None,
        "product_status": translation.get("product_status"),
        "lowering": translation.get("lowering"),
    }
    if typed_ir is None:
        result["blockers"].append(
            _blocker(
                "typed-ir-unavailable",
                "The reference controller translation did not produce typed IR.",
            )
        )
        return result

    graph = ControlGraph.model_validate(typed_ir)
    target = g36_library.assess_niagara_source_target(translation)
    result["translation"]["target_assessment"] = target
    if not target.get("complete", False):
        result["blockers"].append(
            _blocker(
                "niagara-target-incomplete",
                "The translated reference controller has no complete Niagara target.",
                target_assessment=target,
            )
        )

    design_point_ids = {
        point["id"] for point in review["point_contract"]["points"]
    }
    unknown_binding_keys = sorted(set(request.point_bindings) - design_point_ids)
    if unknown_binding_keys:
        result["blockers"].append(
            _blocker(
                "point-binding-source-unknown",
                "Point bindings reference identifiers outside the retained design contract.",
                points=unknown_binding_keys,
            )
        )
    acceptance_cases = [
        AcceptanceCase.model_validate(case) for case in oracle["acceptance_cases"]
    ]
    canonical_inputs, canonical_outputs = _case_point_sets(acceptance_cases)
    block_by_id = {block.id: block for block in graph.blocks}
    bound_inputs = {
        point: _bound(point, request.point_bindings) for point in canonical_inputs
    }
    bound_outputs = {
        point: _bound(point, request.point_bindings) for point in canonical_outputs
    }
    missing_graph_inputs = sorted(
        point for point, target_id in bound_inputs.items() if target_id not in block_by_id
    )
    missing_graph_outputs = sorted(
        point for point, target_id in bound_outputs.items() if target_id not in block_by_id
    )
    wrong_input_kinds = sorted(
        point
        for point, target_id in bound_inputs.items()
        if target_id in block_by_id
        and block_by_id[target_id].kind
        not in {BlockKind.NUMERIC_INPUT, BlockKind.BOOLEAN_INPUT}
    )
    wrong_output_kinds = sorted(
        point
        for point, target_id in bound_outputs.items()
        if target_id in block_by_id
        and block_by_id[target_id].kind
        not in {BlockKind.NUMERIC_OUTPUT, BlockKind.BOOLEAN_OUTPUT}
    )
    if missing_graph_inputs or missing_graph_outputs or wrong_input_kinds or wrong_output_kinds:
        result["blockers"].append(
            _blocker(
                "oracle-interface-bindings-incomplete",
                "Approved oracle points are not fully bound to typed graph boundary ports.",
                missing_inputs=missing_graph_inputs,
                missing_outputs=missing_graph_outputs,
                wrong_input_kinds=wrong_input_kinds,
                wrong_output_kinds=wrong_output_kinds,
            )
        )

    result["candidate_graph"] = {
        "sha256": hashlib.sha256(canonical_json(graph).encode("utf-8")).hexdigest(),
        "block_count": len(graph.blocks),
        "link_count": len(graph.links),
        "metadata": graph.metadata,
    }
    if result["blockers"]:
        return result

    bound_cases = [_bind_case(case, request.point_bindings) for case in acceptance_cases]
    report = run_generic_acceptance_suite(graph, bound_cases)
    result["test_report"] = report.model_dump(mode="json")
    if not report.passed:
        result["blockers"].append(
            _blocker(
                "approved-oracles-failed",
                "The translated candidate failed one or more independently approved tests.",
                failed_scenarios=[
                    scenario.name for scenario in report.scenarios if not scenario.passed
                ],
            )
        )
        return result

    result["ready_for_candidate_generation"] = True
    return result
