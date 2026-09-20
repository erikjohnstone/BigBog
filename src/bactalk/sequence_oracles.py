from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bactalk.domain import AcceptanceCase, AcceptancePhase, OutputExpectation


class SequenceOracleIntegrityError(ValueError):
    """Raised when retained oracle evidence no longer matches its manifest."""


class SequenceOracleExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte", "between"] = "eq"
    value: float | bool
    upper: float | None = None
    tolerance: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def finite_and_coherent(self) -> SequenceOracleExpectation:
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("oracle expectation value must be finite")
        if self.operator == "between":
            if isinstance(self.value, bool) or self.upper is None:
                raise ValueError("between expectations require numeric value and upper")
            if not math.isfinite(self.upper) or float(self.value) > self.upper:
                raise ValueError("between expectation bounds must be finite and ordered")
        elif self.upper is not None:
            raise ValueError("upper is only valid for a between expectation")
        return self

    def domain(self) -> OutputExpectation:
        return OutputExpectation.model_validate(self.model_dump(mode="json"))


class SequenceOracleCaseAuthoring(BaseModel):
    model_config = ConfigDict(extra="forbid")

    oracle_id: str = Field(pattern=r"^oracle-[0-9a-f]{16}$")
    name: str = Field(min_length=2, max_length=200)
    baseline_inputs: dict[str, float | bool] = Field(min_length=1, max_length=1_000)
    trigger_inputs: dict[str, float | bool] = Field(min_length=1, max_length=1_000)
    recovery_inputs: dict[str, float | bool] = Field(min_length=1, max_length=1_000)
    step_seconds: float = Field(gt=0.0, le=86_400.0, allow_inf_nan=False)
    baseline_repeat: int = Field(default=1, ge=1, le=1_000_000)
    recovery_repeat: int = Field(default=1, ge=1, le=1_000_000)
    baseline_expectations: list[SequenceOracleExpectation] = Field(
        min_length=1, max_length=1_000
    )
    pre_trigger_expectations: list[SequenceOracleExpectation] = Field(
        default_factory=list, max_length=1_000
    )
    post_trigger_expectations: list[SequenceOracleExpectation] = Field(
        min_length=1, max_length=1_000
    )
    recovery_expectations: list[SequenceOracleExpectation] = Field(
        min_length=1, max_length=1_000
    )

    @model_validator(mode="after")
    def values_and_expectations_are_well_formed(self) -> SequenceOracleCaseAuthoring:
        for phase, inputs in (
            ("baseline", self.baseline_inputs),
            ("trigger", self.trigger_inputs),
            ("recovery", self.recovery_inputs),
        ):
            for point, value in inputs.items():
                if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", point) is None:
                    raise ValueError(f"{phase} input point is invalid: {point}")
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError(f"{phase} input {point} must be finite")
        for phase, expectations in (
            ("baseline", self.baseline_expectations),
            ("pre-trigger", self.pre_trigger_expectations),
            ("post-trigger", self.post_trigger_expectations),
            ("recovery", self.recovery_expectations),
        ):
            targets = [expectation.target for expectation in expectations]
            if len(targets) != len(set(targets)):
                raise ValueError(f"{phase} expectation targets must be unique")
        return self


class SequenceOracleApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    author: str | None = Field(default=None, min_length=2, max_length=120)
    cases: list[SequenceOracleCaseAuthoring] = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def oracle_ids_are_unique(self) -> SequenceOracleApprovalRequest:
        ids = [case.oracle_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("sequence oracle authoring contains duplicate oracle IDs")
        return self


class SequenceOracleApprovalRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_name: Literal["bactalk.sequence-oracle-approval-record/v1"] = Field(
        default="bactalk.sequence-oracle-approval-record/v1", alias="schema"
    )
    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    review_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    review_artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    oracle_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    result: dict[str, Any]


_UNIT_TO_BASE: dict[str, tuple[str, float]] = {
    "Pa": ("pressure", 1.0),
    "kPa": ("pressure", 1_000.0),
    "psi": ("pressure", 6_894.757293168),
    "inH2O": ("pressure", 249.08891),
    "m3/s": ("airflow", 1.0),
    "L/s": ("airflow", 0.001),
    "cfm": ("airflow", 0.00047194745),
    "%": ("percentage", 1.0),
    "ppm": ("concentration", 1.0),
    "Hz": ("frequency", 1.0),
    "rpm": ("rotational_speed", 1.0),
    "Btu/lb": ("enthalpy_btu", 1.0),
    "kJ/kg": ("enthalpy_kj", 1.0),
}


def _canonical(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", by_alias=True)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _convert(value: float, source_unit: str, target_unit: str) -> float:
    if source_unit == target_unit:
        return value
    if source_unit == "degF" and target_unit == "degC":
        return (value - 32.0) * 5.0 / 9.0
    if source_unit == "degC" and target_unit == "degF":
        return value * 9.0 / 5.0 + 32.0
    source = _UNIT_TO_BASE.get(source_unit)
    target = _UNIT_TO_BASE.get(target_unit)
    if source is None or target is None or source[0] != target[0]:
        raise ValueError(
            f"cannot convert sequence threshold from {source_unit} to point unit {target_unit}"
        )
    return value * source[1] / target[1]


def _condition_holds(condition: dict[str, Any], value: float | bool) -> tuple[bool, float]:
    if isinstance(value, bool):
        raise ValueError(f"condition input {condition['point']} must be numeric")
    point_unit = condition.get("point_unit")
    if not point_unit:
        raise ValueError(f"condition point {condition['point']} has no engineering unit")
    threshold = _convert(
        float(condition["value"]),
        str(condition["unit"]),
        str(point_unit),
    )
    numeric = float(value)
    operator = condition["operator"]
    result = {
        "lt": numeric < threshold,
        "le": numeric <= threshold,
        "gt": numeric > threshold,
        "ge": numeric >= threshold,
        "eq": numeric == threshold,
    }.get(operator)
    if result is None:
        raise ValueError(f"unsupported sequence condition operator {operator}")
    return result, threshold


def _same_scalar(left: float | bool, right: float | bool) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-12)


def _draft_expectation_covered(
    draft: dict[str, Any], submitted: list[SequenceOracleExpectation]
) -> bool:
    return any(
        item.target == draft["point"]
        and item.operator == "eq"
        and _same_scalar(item.value, draft["value"])
        and item.tolerance == 0.0
        for item in submitted
    )


def _phase_proves_non_triggered(
    draft: dict[str, Any], submitted: list[SequenceOracleExpectation]
) -> bool:
    return any(
        item.target == draft["point"]
        and not (
            item.operator == "eq"
            and _same_scalar(item.value, draft["value"])
            and item.tolerance == 0.0
        )
        for item in submitted
    )


def compile_sequence_oracle_approval(
    review_id: str,
    review_record: dict[str, Any],
    request: SequenceOracleApprovalRequest,
    *,
    author: str,
    actor_id: str | None,
    tenant_id: str | None,
    authentication: str,
) -> dict[str, Any]:
    """Validate independent trajectories and emit executable AcceptanceCase objects."""

    if request.review_artifact_digest != review_record["artifact_digest"]:
        raise ValueError("sequence review artifact changed; reload the retained review")
    review = review_record["result"]
    if not review.get("ready_for_independent_oracle_authoring") or review.get("blockers"):
        raise ValueError("sequence requirement review is not ready for oracle authoring")
    reviewed_by = review["review"]["reviewer"]
    reviewed_actor = review["review"].get("actor_id")
    if actor_id is not None and reviewed_actor is not None:
        if actor_id == reviewed_actor:
            raise ValueError("independent oracle author must differ from requirement reviewer")
    elif author.strip().casefold() == str(reviewed_by).strip().casefold():
        raise ValueError("independent oracle author must differ from requirement reviewer")
    reviewed_tenant = review["review"].get("tenant_id")
    if reviewed_tenant != tenant_id:
        raise ValueError("oracle author and retained review must belong to the same tenant")

    drafts = {draft["id"]: draft for draft in review["oracle_drafts"]}
    authored = {case.oracle_id: case for case in request.cases}
    unknown = sorted(set(authored) - set(drafts))
    missing = sorted(set(drafts) - set(authored))
    if unknown:
        raise ValueError(f"oracle approval contains unknown draft IDs: {', '.join(unknown)}")
    if missing:
        raise ValueError(f"oracle approval must cover every draft; missing: {', '.join(missing)}")

    point_contract_payload = review.get("point_contract")
    if not isinstance(point_contract_payload, dict) or not isinstance(
        point_contract_payload.get("points"), list
    ):
        raise ValueError(
            "retained review predates the oracle point contract; repeat requirement review"
        )
    point_contract = {point["id"]: point for point in point_contract_payload["points"]}
    acceptance_cases: list[AcceptanceCase] = []
    evidence: list[dict[str, Any]] = []
    for oracle_id in sorted(drafts):
        draft = drafts[oracle_id]
        case = authored[oracle_id]
        known_inputs = set(point_contract)
        for phase_name, inputs in (
            ("baseline", case.baseline_inputs),
            ("trigger", case.trigger_inputs),
            ("recovery", case.recovery_inputs),
        ):
            unknown_points = sorted(set(inputs) - known_inputs)
            if unknown_points:
                raise ValueError(
                    f"{oracle_id} {phase_name} inputs reference unknown points: "
                    + ", ".join(unknown_points)
                )
        expected_targets = {item["point"] for item in draft["expectations"]}
        for phase_name, expectations in (
            ("baseline", case.baseline_expectations),
            ("pre-trigger", case.pre_trigger_expectations),
            ("post-trigger", case.post_trigger_expectations),
            ("recovery", case.recovery_expectations),
        ):
            unknown_targets = sorted(
                {item.target for item in expectations} - set(point_contract)
            )
            if unknown_targets:
                raise ValueError(
                    f"{oracle_id} {phase_name} expectations reference unknown points: "
                    + ", ".join(unknown_targets)
                )
        for draft_expectation in draft["expectations"]:
            if not _draft_expectation_covered(
                draft_expectation, case.post_trigger_expectations
            ):
                raise ValueError(
                    f"{oracle_id} post-trigger expectations weaken or omit "
                    f"{draft_expectation['point']}={draft_expectation['value']}"
                )
            for phase_name, phase_expectations in (
                ("baseline", case.baseline_expectations),
                ("recovery", case.recovery_expectations),
            ):
                if not _phase_proves_non_triggered(draft_expectation, phase_expectations):
                    raise ValueError(
                        f"{oracle_id} {phase_name} must prove "
                        f"{draft_expectation['point']} is not in its triggered state"
                    )

        condition_evidence = []
        for condition in draft["conditions"]:
            point = condition["point"]
            missing_phases = [
                phase
                for phase, inputs in (
                    ("baseline", case.baseline_inputs),
                    ("trigger", case.trigger_inputs),
                    ("recovery", case.recovery_inputs),
                )
                if point not in inputs
            ]
            if missing_phases:
                raise ValueError(
                    f"{oracle_id} condition point {point} is missing from: "
                    + ", ".join(missing_phases)
                )
            baseline_holds, threshold = _condition_holds(
                condition, case.baseline_inputs[point]
            )
            trigger_holds, _ = _condition_holds(condition, case.trigger_inputs[point])
            recovery_holds, _ = _condition_holds(
                condition, case.recovery_inputs[point]
            )
            if baseline_holds:
                raise ValueError(f"{oracle_id} baseline already satisfies condition on {point}")
            if not trigger_holds:
                raise ValueError(f"{oracle_id} trigger does not satisfy condition on {point}")
            if recovery_holds:
                raise ValueError(f"{oracle_id} recovery still satisfies condition on {point}")
            condition_evidence.append(
                {
                    "point": point,
                    "operator": condition["operator"],
                    "threshold_in_point_units": threshold,
                    "point_unit": condition["point_unit"],
                    "baseline": case.baseline_inputs[point],
                    "trigger": case.trigger_inputs[point],
                    "recovery": case.recovery_inputs[point],
                    "false_true_false_proven": True,
                }
            )

        durations = draft["durations"]
        unsupported = sorted(
            {
                duration["relation"]
                for duration in durations
                if duration["relation"] not in {"persistence", "on-delay"}
            }
        )
        if unsupported:
            raise ValueError(
                f"{oracle_id} has timing relations that need a specialized oracle: "
                + ", ".join(unsupported)
            )
        duration_seconds = max(
            (float(duration["seconds"]) for duration in durations), default=0.0
        )
        timeline = [
            AcceptancePhase(
                name="baseline",
                inputs=case.baseline_inputs,
                repeat=case.baseline_repeat,
                step_seconds=case.step_seconds,
                expectations=[item.domain() for item in case.baseline_expectations],
            )
        ]
        before_repeat = 0
        if duration_seconds > 0:
            if case.step_seconds >= duration_seconds:
                raise ValueError(
                    f"{oracle_id} step_seconds must be less than {duration_seconds:g} "
                    "to prove the output does not change early"
                )
            if not case.pre_trigger_expectations:
                raise ValueError(
                    f"{oracle_id} requires pre-trigger expectations for its timed condition"
                )
            for draft_expectation in draft["expectations"]:
                if not _phase_proves_non_triggered(
                    draft_expectation, case.pre_trigger_expectations
                ):
                    raise ValueError(
                        f"{oracle_id} pre-trigger phase must prove "
                        f"{draft_expectation['point']} has not changed early"
                    )
            trigger_steps = math.ceil(duration_seconds / case.step_seconds)
            before_repeat = trigger_steps - 1
            timeline.append(
                AcceptancePhase(
                    name="trigger-before-duration",
                    inputs=case.trigger_inputs,
                    repeat=before_repeat,
                    step_seconds=case.step_seconds,
                    expectations=[
                        item.domain() for item in case.pre_trigger_expectations
                    ],
                )
            )
        elif case.pre_trigger_expectations:
            raise ValueError(
                f"{oracle_id} has no duration and must not claim a pre-trigger timing phase"
            )
        timeline.extend(
            [
                AcceptancePhase(
                    name="trigger-after-duration" if duration_seconds else "trigger-response",
                    inputs=case.trigger_inputs,
                    repeat=1,
                    step_seconds=case.step_seconds,
                    expectations=[
                        item.domain() for item in case.post_trigger_expectations
                    ],
                ),
                AcceptancePhase(
                    name="recovery",
                    inputs=case.recovery_inputs,
                    repeat=case.recovery_repeat,
                    step_seconds=case.step_seconds,
                    expectations=[item.domain() for item in case.recovery_expectations],
                ),
            ]
        )
        acceptance = AcceptanceCase(
            name=case.name,
            expectations=[item.domain() for item in case.recovery_expectations],
            timeline=timeline,
        )
        acceptance_cases.append(acceptance)
        evidence.append(
            {
                "oracle_id": oracle_id,
                "source": draft["source"],
                "condition_checks": condition_evidence,
                "duration_seconds": duration_seconds,
                "step_seconds": case.step_seconds,
                "pre_expiration_steps": before_repeat,
                "post_expiration_steps": 1,
                "expected_targets": sorted(expected_targets),
                "complete_false_true_false_trajectory": True,
            }
        )

    approval_payload = {
        "review_id": review_id,
        "review_artifact_digest": request.review_artifact_digest,
        "author": author,
        "actor_id": actor_id,
        "tenant_id": tenant_id,
        "authentication": authentication,
        "authored_cases": [case.model_dump(mode="json") for case in request.cases],
        "acceptance_cases": [case.model_dump(mode="json") for case in acceptance_cases],
    }
    oracle_digest = _digest(approval_payload)
    scenario_coverage_complete = bool(
        review.get("all_scenario_facets_have_oracle_drafts", False)
    )
    return {
        "schema": "bactalk.sequence-oracle-approval/v1",
        "review_id": review_id,
        "review_artifact_digest": request.review_artifact_digest,
        "review_digest": review["review_digest"],
        "source_sha256": review["source_sha256"],
        "oracle_digest": oracle_digest,
        "approval": {
            "author": author,
            "actor_id": actor_id,
            "tenant_id": tenant_id,
            "authentication": authentication,
            "approved_at": datetime.now(UTC).isoformat(),
            "independent_from_requirement_reviewer": True,
        },
        "case_count": len(acceptance_cases),
        "acceptance_cases": [case.model_dump(mode="json") for case in acceptance_cases],
        "validation_evidence": evidence,
        "approved_oracle_gate_passed": True,
        "sequence_requirement_gate_passed": scenario_coverage_complete,
        "ready_for_graph_generation": scenario_coverage_complete,
        "ready_for_deployment": False,
        "scenario_oracle_gap_count": review.get("scenario_oracle_gap_count"),
        "next_gate": (
            "A planner may generate a new whole-system candidate graph against these immutable "
            "acceptance cases; that graph must pass every test and all target/runtime release "
            "gates."
            if scenario_coverage_complete
            else "Author and independently approve executable oracles for every remaining "
            "selected scenario facet before whole-system graph generation."
        ),
        "safety": {
            "live_writes_enabled": False,
            "oracle_author_can_modify_generated_graph": False,
            "passing_this_gate_authorizes_deployment": False,
        },
    }


def _record_payload(record: SequenceOracleApprovalRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "review_id": record.review_id,
        "review_artifact_digest": record.review_artifact_digest,
        "created_at": record.created_at.isoformat(),
        "oracle_digest": record.oracle_digest,
        "result": record.result,
    }


class SequenceOracleApprovalRepository:
    """Append-only, hash-verified store for approved independent sequence oracles."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for candidate in self.root.iterdir():
            if candidate.is_dir() and re.fullmatch(
                r"\.[0-9a-f]{32}\.staging", candidate.name
            ):
                shutil.rmtree(candidate)

    def _directory(self, approval_id: str, *, staging: bool = False) -> Path:
        if re.fullmatch(r"[0-9a-f]{32}", approval_id) is None:
            raise ValueError("invalid sequence oracle approval id")
        return self.root / (f".{approval_id}.staging" if staging else approval_id)

    def save(self, result: dict[str, Any]) -> SequenceOracleApprovalRecord:
        if result.get("schema") != "bactalk.sequence-oracle-approval/v1":
            raise ValueError("unsupported sequence oracle approval result")
        approval_id = uuid4().hex
        created_at = datetime.now(UTC)
        provisional = SequenceOracleApprovalRecord(
            id=approval_id,
            review_id=result["review_id"],
            review_artifact_digest=result["review_artifact_digest"],
            created_at=created_at,
            oracle_digest=result["oracle_digest"],
            artifact_digest="0" * 64,
            result=result,
        )
        record = provisional.model_copy(
            update={"artifact_digest": _digest(_record_payload(provisional))}
        )
        staging = self._directory(approval_id, staging=True)
        final = self._directory(approval_id)
        staging.mkdir(parents=False, exist_ok=False)
        try:
            manifest = staging / "manifest.json"
            with manifest.open("x", encoding="utf-8") as stream:
                stream.write(_canonical(record))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(staging, final)
            directory_fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise
        return record

    def get(self, approval_id: str) -> SequenceOracleApprovalRecord:
        manifest = self._directory(approval_id) / "manifest.json"
        if not manifest.exists():
            raise KeyError(approval_id)
        try:
            record = SequenceOracleApprovalRecord.model_validate_json(
                manifest.read_text(encoding="utf-8")
            )
        except (ValueError, json.JSONDecodeError) as exc:
            raise SequenceOracleIntegrityError(
                f"sequence oracle approval {approval_id} manifest is invalid"
            ) from exc
        if record.id != approval_id:
            raise SequenceOracleIntegrityError(
                f"sequence oracle approval {approval_id} identity changed"
            )
        if record.result.get("oracle_digest") != record.oracle_digest:
            raise SequenceOracleIntegrityError(
                f"sequence oracle approval {approval_id} oracle digest changed"
            )
        if record.result.get("review_id") != record.review_id:
            raise SequenceOracleIntegrityError(
                f"sequence oracle approval {approval_id} review identity changed"
            )
        if record.result.get("review_artifact_digest") != record.review_artifact_digest:
            raise SequenceOracleIntegrityError(
                f"sequence oracle approval {approval_id} review digest changed"
            )
        if _digest(_record_payload(record)) != record.artifact_digest:
            raise SequenceOracleIntegrityError(
                f"sequence oracle approval {approval_id} artifact digest changed"
            )
        return record

    def list(self) -> list[SequenceOracleApprovalRecord]:
        records = [self.get(path.parent.name) for path in self.root.glob("*/manifest.json")]
        return sorted(records, key=lambda item: item.created_at, reverse=True)
