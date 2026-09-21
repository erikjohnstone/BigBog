from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bactalk.domain import (
    AcceptanceCase,
    AcceptancePhase,
    BlockKind,
    ControlGraph,
    DataType,
    FaultInjection,
    JobSpec,
    OutputExpectation,
    PointRole,
    PointSpec,
    SequenceSpec,
    canonical_json,
)
from bactalk.simulator import run_acceptance_suite


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


class SequenceCandidateGenerationRequest(SequenceCandidatePreflightRequest):
    name: str = Field(min_length=1, max_length=240)
    site: str = Field(min_length=1, max_length=240)
    equipment_name: str = Field(
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
        max_length=120,
    )
    equipment_brick_class: str | None = Field(default=None, max_length=240)
    notes: str | None = Field(default=None, max_length=5_000)

    def preflight_request(self) -> SequenceCandidatePreflightRequest:
        return SequenceCandidatePreflightRequest.model_validate(
            self.model_dump(
                include={
                    "oracle_artifact_digest",
                    "controller_parameters",
                    "point_bindings",
                    "execution_profile",
                }
            )
        )


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


_INPUT_KINDS = {BlockKind.NUMERIC_INPUT, BlockKind.BOOLEAN_INPUT}
_OUTPUT_KINDS = {BlockKind.NUMERIC_OUTPUT, BlockKind.BOOLEAN_OUTPUT}


def _candidate_boundary(
    graph: ControlGraph,
    *,
    review: dict[str, Any],
    point_result: dict[str, Any],
    bindings: dict[str, str],
) -> tuple[
    ControlGraph,
    list[PointSpec],
    list[dict[str, Any]],
    list[dict[str, str]],
    list[dict[str, Any]],
]:
    """Bind every translated boundary to one retained contractor point, fail closed."""

    contract_points = review.get("point_contract", {}).get("points", [])
    design_points = {
        str(point["id"]): point
        for point in contract_points
        if isinstance(point, dict) and isinstance(point.get("id"), str)
    }
    retained_points: dict[str, PointSpec] = {}
    invalid_retained_points: list[str] = []
    for payload in point_result.get("canonical_points", []):
        try:
            point = PointSpec.model_validate(payload)
        except ValueError:
            invalid_retained_points.append(str(payload.get("name", "unknown")))
            continue
        retained_points[point.name] = point

    boundary_blocks = {
        block.id: block
        for block in graph.blocks
        if block.kind in _INPUT_KINDS | _OUTPUT_KINDS
    }
    boundary_ids = set(boundary_blocks)
    blockers: list[dict[str, Any]] = []
    unknown_sources = sorted(set(bindings) - set(design_points))
    unknown_targets = sorted(set(bindings.values()) - boundary_ids)
    if unknown_sources:
        blockers.append(
            _blocker(
                "point-binding-source-unknown",
                "Point bindings reference identifiers outside the retained design contract.",
                points=unknown_sources,
            )
        )
    if unknown_targets:
        blockers.append(
            _blocker(
                "point-binding-target-unknown",
                "Point bindings reference identifiers outside the translated graph boundary.",
                points=unknown_targets,
            )
        )

    target_to_sources: dict[str, list[str]] = {}
    for design_id in sorted(design_points):
        target = _bound(design_id, bindings)
        if target in boundary_ids:
            target_to_sources.setdefault(target, []).append(design_id)
    duplicate_targets = {
        target: sources
        for target, sources in target_to_sources.items()
        if len(sources) != 1
    }
    if duplicate_targets:
        blockers.append(
            _blocker(
                "point-binding-target-ambiguous",
                "More than one retained design point resolves to the same graph boundary.",
                targets=duplicate_targets,
            )
        )
    missing_boundaries = sorted(boundary_ids - set(target_to_sources))
    if missing_boundaries:
        blockers.append(
            _blocker(
                "graph-boundary-bindings-incomplete",
                "Every translated graph input and output requires a retained contractor point.",
                graph_boundaries=missing_boundaries,
            )
        )
    if invalid_retained_points:
        blockers.append(
            _blocker(
                "contractor-point-payload-invalid",
                "One or more retained contractor points cannot form a typed job point.",
                points=sorted(invalid_retained_points),
            )
        )

    candidate_points: list[PointSpec] = []
    boundary_bindings: list[dict[str, str]] = []
    wrong_types: list[str] = []
    wrong_roles: list[str] = []
    missing_contractor_points: list[str] = []
    for target in sorted(boundary_ids):
        sources = target_to_sources.get(target, [])
        if len(sources) != 1:
            continue
        design_id = sources[0]
        point = retained_points.get(design_id)
        if point is None:
            missing_contractor_points.append(design_id)
            continue
        block = boundary_blocks[target]
        expected_type = (
            DataType.BOOLEAN
            if block.kind in {BlockKind.BOOLEAN_INPUT, BlockKind.BOOLEAN_OUTPUT}
            else DataType.NUMERIC
        )
        if point.data_type != expected_type:
            wrong_types.append(design_id)
            continue
        if block.kind in _INPUT_KINDS and point.role not in {
            PointRole.SENSOR,
            PointRole.SETPOINT,
            PointRole.STATUS,
        }:
            wrong_roles.append(design_id)
            continue
        if block.kind in _OUTPUT_KINDS and point.role not in {
            PointRole.COMMAND,
            PointRole.ALARM,
        }:
            wrong_roles.append(design_id)
            continue
        source_name = point.source_name
        if target != point.name and source_name is None:
            source_name = point.name
        candidate_points.append(
            point.model_copy(update={"name": target, "source_name": source_name})
        )
        boundary_bindings.append(
            {
                "design_point": design_id,
                "graph_boundary": target,
                "contractor_source": source_name or point.name,
            }
        )

    if missing_contractor_points:
        blockers.append(
            _blocker(
                "graph-boundary-contractor-points-missing",
                "A graph boundary resolves to a design point absent from the retained point list.",
                points=sorted(missing_contractor_points),
            )
        )
    if wrong_types or wrong_roles:
        blockers.append(
            _blocker(
                "graph-boundary-point-contract-invalid",
                "Retained contractor point types or roles do not match translated boundaries.",
                wrong_types=sorted(wrong_types),
                wrong_roles=sorted(wrong_roles),
            )
        )

    points_by_target = {point.name: point for point in candidate_points}
    bound_blocks = []
    for block in graph.blocks:
        point = points_by_target.get(block.id)
        if point is not None and block.kind in _INPUT_KINDS:
            block = block.model_copy(
                update={"config": {**block.config, "default": point.default}}
            )
        bound_blocks.append(block)
    selected_design_by_target = {
        item["graph_boundary"]: item["design_point"] for item in boundary_bindings
    }
    boundary_contract: list[dict[str, Any]] = []
    for target, block in sorted(boundary_blocks.items()):
        is_input = block.kind in _INPUT_KINDS
        expected_type = (
            DataType.BOOLEAN
            if block.kind in {BlockKind.BOOLEAN_INPUT, BlockKind.BOOLEAN_OUTPUT}
            else DataType.NUMERIC
        )
        allowed_roles = (
            {PointRole.SENSOR, PointRole.SETPOINT, PointRole.STATUS}
            if is_input
            else {PointRole.COMMAND, PointRole.ALARM}
        )
        compatible_design_points = sorted(
            design_id
            for design_id, point in retained_points.items()
            if point.data_type == expected_type and point.role in allowed_roles
        )
        boundary_contract.append(
            {
                "id": target,
                "label": block.label,
                "direction": "input" if is_input else "output",
                "data_type": expected_type.value,
                "selected_design_point": selected_design_by_target.get(target),
                "compatible_design_points": compatible_design_points,
            }
        )
    return (
        graph.model_copy(update={"blocks": bound_blocks}),
        candidate_points,
        blockers,
        boundary_bindings,
        boundary_contract,
    )


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

    (
        graph,
        candidate_points,
        boundary_blockers,
        boundary_bindings,
        boundary_contract,
    ) = _candidate_boundary(
        graph,
        review=review,
        point_result=point_result,
        bindings=request.point_bindings,
    )
    result["blockers"].extend(boundary_blockers)
    result["boundary_bindings"] = boundary_bindings
    result["graph_boundary_contract"] = boundary_contract
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

    bound_cases = [_bind_case(case, request.point_bindings) for case in acceptance_cases]
    _, covered_graph_outputs = _case_point_sets(bound_cases)
    graph_output_ids = {
        block.id for block in graph.blocks if block.kind in _OUTPUT_KINDS
    }
    untested_graph_outputs = sorted(graph_output_ids - covered_graph_outputs)
    if untested_graph_outputs:
        result["blockers"].append(
            _blocker(
                "graph-output-oracle-coverage-incomplete",
                "Independent approved tests must observe every translated controller output.",
                graph_outputs=untested_graph_outputs,
            )
        )

    result["candidate_graph"] = {
        "sha256": hashlib.sha256(canonical_json(graph).encode("utf-8")).hexdigest(),
        "block_count": len(graph.blocks),
        "link_count": len(graph.links),
        "boundary_count": len(candidate_points),
        "metadata": graph.metadata,
    }
    if result["blockers"]:
        return result

    validation_job = JobSpec(
        name="Approved sequence candidate preflight",
        site="Preflight",
        equipment_name="SequenceCandidate",
        sequence=SequenceSpec(
            family="LBNL_G36_CONTROLLER",
            version="Pinned LBNL Modelica Buildings G36 source",
            library="g36",
            controller_id=controller_id,
            execution_profile=request.execution_profile,
            parameters=request.controller_parameters,
        ),
        points=candidate_points,
        control_graph=graph,
        acceptance_tests=bound_cases,
    )
    report = run_acceptance_suite(graph, validation_job)
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


def build_sequence_candidate_job(
    *,
    oracle_record: dict[str, Any],
    review_record: dict[str, Any],
    point_record: dict[str, Any],
    programming_brief: dict[str, Any],
    request: SequenceCandidateGenerationRequest,
    g36_library: Any,
) -> tuple[dict[str, Any], JobSpec | None]:
    """Turn a passing retained preflight into the exact immutable contractor job."""

    preflight_request = request.preflight_request()
    preflight = compile_sequence_candidate_preflight(
        oracle_record=oracle_record,
        review_record=review_record,
        point_record=point_record,
        programming_brief=programming_brief,
        request=preflight_request,
        g36_library=g36_library,
    )
    if not preflight["ready_for_candidate_generation"]:
        return preflight, None

    controller_id = programming_brief["design_binding"]["controller_id"]
    translation = g36_library.translate(
        controller_id,
        execution_profile=request.execution_profile,
        parameters=request.controller_parameters,
    )
    graph = ControlGraph.model_validate(translation["typed_ir"])
    review = review_record["result"]
    point_result = point_record["result"]
    graph, points, blockers, boundary_bindings, boundary_contract = _candidate_boundary(
        graph,
        review=review,
        point_result=point_result,
        bindings=request.point_bindings,
    )
    if blockers:
        raise ValueError("candidate boundary changed after passing preflight")
    graph_sha256 = hashlib.sha256(canonical_json(graph).encode("utf-8")).hexdigest()
    if graph_sha256 != preflight["candidate_graph"]["sha256"]:
        raise ValueError("candidate graph changed after passing preflight")
    if boundary_bindings != preflight["boundary_bindings"]:
        raise ValueError("candidate boundary bindings changed after passing preflight")
    if boundary_contract != preflight["graph_boundary_contract"]:
        raise ValueError("candidate boundary contract changed after passing preflight")

    oracle = oracle_record["result"]
    cases = [
        _bind_case(AcceptanceCase.model_validate(case), request.point_bindings)
        for case in oracle["acceptance_cases"]
    ]
    equipment_family = programming_brief["design_binding"]["equipment_family"]
    default_brick_class = (
        "brick:Air_Handling_Unit"
        if str(equipment_family).startswith("ahu.")
        else "brick:Terminal_Unit"
        if str(equipment_family).startswith("terminal.")
        else "brick:Equipment"
    )
    source_bytes_sha256 = str(review_record.get("source_sha256", ""))
    sequence = SequenceSpec(
        family="LBNL_G36_CONTROLLER",
        version="Pinned LBNL Modelica Buildings G36 source",
        library="g36",
        controller_id=controller_id,
        execution_profile=request.execution_profile,
        parameters=request.controller_parameters,
        source_filename=review_record.get("source_filename"),
        source_media_type=review_record.get("source_media_type"),
        source_sha256=source_bytes_sha256 or None,
    )
    provenance_note = (
        "Generated only after the retained ctrl-flow configuration, contractor point "
        "reconciliation, requirement review, independent oracle approval, complete graph "
        "boundary binding, complete output coverage, Niagara target assessment, and local "
        "oracle replay all passed. Engineering approval still does not authorize live writes."
    )
    job = JobSpec(
        name=request.name,
        site=request.site,
        equipment_name=request.equipment_name,
        equipment_brick_class=request.equipment_brick_class or default_brick_class,
        sequence=sequence,
        points=points,
        control_graph=graph,
        acceptance_tests=cases,
        notes=(f"{request.notes}\n\n{provenance_note}" if request.notes else provenance_note),
    )
    replay = run_acceptance_suite(graph, job)
    replay_payload = replay.model_dump(mode="json", exclude={"generated_at"})
    preflight_report = {
        key: value
        for key, value in preflight["test_report"].items()
        if key != "generated_at"
    }
    if not replay.passed or replay_payload != preflight_report:
        raise ValueError("candidate oracle replay changed after passing preflight")
    return preflight, job
