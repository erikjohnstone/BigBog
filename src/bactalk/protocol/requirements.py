"""Requirements model for the Test Generation Protocol.

A requirement set is data, never logic: numbered plain-language requirements with
the structured fields the test author needs (inputs, conditions, timing, expected
outputs, failure behaviour, recovery), a citation each, and the invariants that must
hold at every step. Its digest is what a human approves (Gate G-ENG) and what every
generated scenario references.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bactalk.domain import ComparisonOperator, JobSpec, OutputExpectation

REQUIREMENTS_SCHEMA = "bactalk.protocol-requirements/v1"
APPROVAL_SCHEMA = "bactalk.protocol-requirement-approval/v1"

Operator = Literal["eq", "ne", "gt", "gte", "lt", "lte", "between"]
_NAME = r"^[A-Za-z_][A-Za-z0-9_]*$"


def canonical_digest(value: Any) -> str:
    """sha256 of the canonical JSON form of ``value``."""

    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Citation(BaseModel):
    """Where a requirement comes from; ``fidelity`` says how literal the text is."""

    model_config = ConfigDict(extra="forbid")

    document: str = Field(min_length=1, max_length=200)
    section: str = Field(min_length=1, max_length=120)
    paragraph: str | None = Field(default=None, max_length=120)
    fidelity: Literal["verbatim", "paraphrase", "designer"] = "paraphrase"
    note: str | None = Field(default=None, max_length=2_000)


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: str = Field(min_length=1, max_length=200)
    edition: str = Field(min_length=1, max_length=120)
    url: str | None = Field(default=None, max_length=500)


class PointDeclaration(BaseModel):
    """One public input or output with the range the test author may exercise."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=_NAME, max_length=120)
    label: str = Field(min_length=1, max_length=200)
    data_type: Literal["numeric", "boolean"]
    direction: Literal["input", "output"]
    unit: str | None = Field(default=None, max_length=40)
    minimum: float | None = None
    maximum: float | None = None
    nominal: float | bool = 0.0
    resolution: float | None = Field(default=None, gt=0.0)
    brick_class: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def range_is_coherent(self) -> PointDeclaration:
        if self.data_type == "boolean":
            if not isinstance(self.nominal, bool):
                raise ValueError(f"{self.name}: boolean point needs a boolean nominal")
            if self.minimum is not None or self.maximum is not None or self.resolution:
                raise ValueError(f"{self.name}: boolean point has no range or resolution")
            return self
        if isinstance(self.nominal, bool):
            raise ValueError(f"{self.name}: numeric point needs a numeric nominal")
        for name in ("minimum", "maximum", "nominal"):
            value = getattr(self, name)
            if value is not None and not math.isfinite(float(value)):
                raise ValueError(f"{self.name}: {name} must be finite")
        if self.direction == "input" and (self.minimum is None or self.maximum is None):
            raise ValueError(f"{self.name}: numeric inputs declare minimum and maximum")
        if self.minimum is not None and self.maximum is not None:
            if self.minimum >= self.maximum:
                raise ValueError(f"{self.name}: minimum must be below maximum")
            if not self.minimum <= float(self.nominal) <= self.maximum:
                raise ValueError(f"{self.name}: nominal lies outside the declared range")
        return self

    @property
    def margin(self) -> float:
        """The smallest change the test author treats as meaningful."""

        if self.resolution is not None:
            return self.resolution
        if self.minimum is not None and self.maximum is not None:
            return (self.maximum - self.minimum) / 1_000.0
        return 0.01


class Condition(BaseModel):
    """A predicate on one input; ``deadband`` is the hysteresis the text states."""

    model_config = ConfigDict(extra="forbid")

    point: str = Field(pattern=_NAME, max_length=120)
    operator: Operator = "eq"
    value: float | bool
    upper: float | None = None
    deadband: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def operator_matches_value(self) -> Condition:
        if isinstance(self.value, bool):
            if self.operator not in {"eq", "ne"}:
                raise ValueError(f"{self.point}: boolean conditions use eq or ne")
            if self.deadband or self.upper is not None:
                raise ValueError(f"{self.point}: boolean conditions have no deadband or upper")
        if self.operator == "between":
            if self.upper is None or self.upper < float(self.value):
                raise ValueError(f"{self.point}: between needs upper at or above value")
        elif self.upper is not None:
            raise ValueError(f"{self.point}: upper is only valid for between")
        if self.operator in {"eq", "ne"} and self.deadband:
            raise ValueError(f"{self.point}: eq/ne conditions have no deadband")
        return self


class Timing(BaseModel):
    """How long the conditions must hold (delay) and how long the outcome persists
    after they clear (release)."""

    model_config = ConfigDict(extra="forbid")

    delay_seconds: float = Field(default=0.0, ge=0.0, le=1_000_000.0)
    release_seconds: float = Field(default=0.0, ge=0.0, le=1_000_000.0)
    reference: Literal["conditions", "context"] = "conditions"
    """What the delay counts from: this requirement's own conditions becoming true, or
    the assumed context being established at the start of the scenario (a delay that
    runs from plant enable, say, not from the request count changing)."""

    tolerance_scans: int = Field(default=0, ge=0, le=10)
    """Scans the outcome may lag the delay by (accumulators and samplers that update one
    scan late); the after-delay scenario waits this much longer, the one-scan-short
    scenario does not move."""


class Outcome(BaseModel):
    """An expected output value, in the same vocabulary as ``OutputExpectation``."""

    model_config = ConfigDict(extra="forbid")

    point: str = Field(pattern=_NAME, max_length=120)
    operator: Operator = "eq"
    value: float | bool
    upper: float | None = None
    tolerance: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def operator_matches_value(self) -> Outcome:
        if isinstance(self.value, bool) and self.operator not in {"eq", "ne"}:
            raise ValueError(f"{self.point}: boolean outcomes use eq or ne")
        if self.operator == "between":
            if self.upper is None or isinstance(self.value, bool) or self.upper < self.value:
                raise ValueError(f"{self.point}: between needs numeric value and upper")
        elif self.upper is not None:
            raise ValueError(f"{self.point}: upper is only valid for between")
        return self

    def expectation(self) -> OutputExpectation:
        return OutputExpectation(
            target=self.point,
            operator=ComparisonOperator(self.operator),
            value=self.value,
            upper=self.upper,
            tolerance=self.tolerance,
        )


class FailureBehaviour(BaseModel):
    """What the outputs do when one input fails in a stated way."""

    model_config = ConfigDict(extra="forbid")

    point: str = Field(pattern=_NAME, max_length=120)
    mode: Literal["stuck", "out_of_range_low", "out_of_range_high", "stale"]
    outcomes: list[Outcome] = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=2_000)


class SetupPhase(BaseModel):
    """Inputs held for a while before a scenario starts (a settled plant, a warm loop)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    inputs: dict[str, float | bool] = Field(default_factory=dict, max_length=1_000)
    seconds: float = Field(gt=0.0, le=10_000_000.0)


RequirementKind = Literal[
    "enable", "staging", "rotation", "reset", "loop", "alarm", "safety", "control"
]


class Requirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^R-[0-9]{2,3}$")
    title: str = Field(min_length=3, max_length=200)
    text: str = Field(min_length=10, max_length=4_000)
    citation: Citation
    kind: RequirementKind = "control"
    assumes: list[str] = Field(default_factory=list, max_length=20)
    setup: list[SetupPhase] = Field(default_factory=list, max_length=20)
    conditions: list[Condition] = Field(default_factory=list, max_length=50)
    timing: Timing = Field(default_factory=Timing)
    outcomes: list[Outcome] = Field(min_length=1, max_length=200)
    otherwise: list[Outcome] = Field(default_factory=list, max_length=200)
    before: list[Outcome] | None = None
    """Outputs while the conditions hold but the delay has not elapsed (defaults to
    ``otherwise``)."""
    recovery: list[Outcome] | None = None
    failures: list[FailureBehaviour] = Field(default_factory=list, max_length=100)
    step_seconds: float | None = Field(default=None, gt=0.0, le=86_400.0)
    parameters: dict[str, float] = Field(default_factory=dict, max_length=50)

    @model_validator(mode="after")
    def has_a_trigger(self) -> Requirement:
        if not self.conditions and not self.assumes:
            raise ValueError(f"{self.id}: a requirement needs conditions or assumes")
        if len({condition.point for condition in self.conditions}) != len(self.conditions):
            raise ValueError(f"{self.id}: one condition per input")
        if len(set(self.assumes)) != len(self.assumes) or self.id in self.assumes:
            raise ValueError(f"{self.id}: assumes must be distinct other requirements")
        return self


class Invariant(BaseModel):
    """``then`` must hold at every step where ``when`` holds (always, when empty)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^I-[0-9]{2,3}$")
    text: str = Field(min_length=10, max_length=2_000)
    citation: Citation
    when: list[Condition] = Field(default_factory=list, max_length=20)
    then: list[Outcome] = Field(min_length=1, max_length=50)


class RequirementSet(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_name: Literal["bactalk.protocol-requirements/v1"] = Field(
        default=REQUIREMENTS_SCHEMA, alias="schema"
    )
    sequence_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,80}$")
    title: str = Field(min_length=3, max_length=200)
    version: str = Field(min_length=1, max_length=120)
    tier: int = Field(ge=3, le=5)
    equipment_brick_class: str = Field(default="brick:Equipment", max_length=200)
    sources: list[Source] = Field(min_length=1, max_length=20)
    step_seconds: float = Field(default=10.0, gt=0.0, le=86_400.0)
    points: list[PointDeclaration] = Field(min_length=2, max_length=1_000)
    requirements: list[Requirement] = Field(min_length=1, max_length=1_000)
    invariants: list[Invariant] = Field(default_factory=list, max_length=200)
    notes: str | None = Field(default=None, max_length=10_000)

    @model_validator(mode="after")
    def references_resolve(self) -> RequirementSet:
        points = {point.name: point for point in self.points}
        if len(points) != len(self.points):
            raise ValueError("point names must be unique")
        if not any(point.direction == "input" for point in self.points):
            raise ValueError("a requirement set declares at least one input")
        if not any(point.direction == "output" for point in self.points):
            raise ValueError("a requirement set declares at least one output")
        ids = [requirement.id for requirement in self.requirements]
        if len(ids) != len(set(ids)):
            raise ValueError("requirement ids must be unique")
        invariant_ids = [invariant.id for invariant in self.invariants]
        if len(invariant_ids) != len(set(invariant_ids)):
            raise ValueError("invariant ids must be unique")
        known = set(ids)
        for requirement in self.requirements:
            for other in requirement.assumes:
                if other not in known:
                    raise ValueError(f"{requirement.id} assumes unknown {other}")
            self._check_conditions(requirement.id, requirement.conditions, points, "input")
            for phase in requirement.setup:
                for name in phase.inputs:
                    if name not in points or points[name].direction != "input":
                        raise ValueError(f"{requirement.id} setup names unknown input {name}")
            self._check_outcomes(requirement.id, requirement.outcomes, points)
            self._check_outcomes(requirement.id, requirement.otherwise, points)
            self._check_outcomes(requirement.id, requirement.before or [], points)
            self._check_outcomes(requirement.id, requirement.recovery or [], points)
            for failure in requirement.failures:
                if failure.point not in points or points[failure.point].direction != "input":
                    raise ValueError(f"{requirement.id}: failure names unknown input")
                if points[failure.point].data_type == "boolean" and failure.mode.startswith(
                    "out_of_range"
                ):
                    raise ValueError(f"{requirement.id}: boolean {failure.point} has no range")
                self._check_outcomes(requirement.id, failure.outcomes, points)
        for invariant in self.invariants:
            self._check_conditions(invariant.id, invariant.when, points, None)
            self._check_outcomes(invariant.id, invariant.then, points)
        # assumes must be acyclic
        for requirement in self.requirements:
            self.assumption_closure(requirement.id)
        return self

    @staticmethod
    def _check_conditions(
        owner: str,
        conditions: list[Condition],
        points: dict[str, PointDeclaration],
        direction: str | None,
    ) -> None:
        for condition in conditions:
            point = points.get(condition.point)
            if point is None:
                raise ValueError(f"{owner}: condition names unknown point {condition.point}")
            if direction is not None and point.direction != direction:
                raise ValueError(f"{owner}: conditions are on {direction}s, not {condition.point}")
            if (point.data_type == "boolean") != isinstance(condition.value, bool):
                raise ValueError(f"{owner}: condition type mismatch on {condition.point}")

    @staticmethod
    def _check_outcomes(
        owner: str, outcomes: list[Outcome], points: dict[str, PointDeclaration]
    ) -> None:
        for outcome in outcomes:
            point = points.get(outcome.point)
            if point is None or point.direction != "output":
                raise ValueError(f"{owner}: outcome names unknown output {outcome.point}")
            if (point.data_type == "boolean") != isinstance(outcome.value, bool):
                raise ValueError(f"{owner}: outcome type mismatch on {outcome.point}")

    # --- lookups ---------------------------------------------------------------------

    def point(self, name: str) -> PointDeclaration:
        for point in self.points:
            if point.name == name:
                return point
        raise KeyError(name)

    @property
    def inputs(self) -> list[PointDeclaration]:
        return [point for point in self.points if point.direction == "input"]

    @property
    def outputs(self) -> list[PointDeclaration]:
        return [point for point in self.points if point.direction == "output"]

    def requirement(self, requirement_id: str) -> Requirement:
        for requirement in self.requirements:
            if requirement.id == requirement_id:
                return requirement
        raise KeyError(requirement_id)

    def assumption_closure(self, requirement_id: str) -> list[str]:
        """Requirement ids whose conditions this one inherits, dependencies first."""

        order: list[str] = []
        visiting: list[str] = []

        def visit(current: str) -> None:
            if current in visiting:
                raise ValueError("assumes form a cycle: " + " -> ".join([*visiting, current]))
            if current in order:
                return
            visiting.append(current)
            for other in self.requirement(current).assumes:
                visit(other)
            visiting.pop()
            order.append(current)

        visit(requirement_id)
        order.remove(requirement_id)
        return order

    def effective_conditions(self, requirement: Requirement) -> list[Condition]:
        """Inherited conditions first, the requirement's own last (same input: own wins)."""

        merged: dict[str, Condition] = {}
        for other in self.assumption_closure(requirement.id):
            for condition in self.requirement(other).conditions:
                merged[condition.point] = condition
        for condition in requirement.conditions:
            merged[condition.point] = condition
        return list(merged.values())

    def effective_setup(self, requirement: Requirement) -> list[SetupPhase]:
        phases: list[SetupPhase] = []
        for other in self.assumption_closure(requirement.id):
            phases.extend(self.requirement(other).setup)
        phases.extend(requirement.setup)
        return phases

    def nominal_inputs(self) -> dict[str, float | bool]:
        return {point.name: point.nominal for point in self.inputs}

    def digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json", by_alias=True))


class RequirementApproval(BaseModel):
    """Gate G-ENG: a named engineer approved one exact requirement set."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_name: Literal["bactalk.protocol-requirement-approval/v1"] = Field(
        default=APPROVAL_SCHEMA, alias="schema"
    )
    sequence_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,80}$")
    requirements_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer: str = Field(min_length=2, max_length=120)
    actor_id: str | None = None
    tenant_id: str | None = None
    authentication: str = "self-asserted-local"
    approved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    note: str | None = Field(default=None, max_length=4_000)


ApprovalStatus = Literal["approved", "unapproved", "stale"]


def approval_status(
    requirements: RequirementSet, approval: RequirementApproval | None
) -> ApprovalStatus:
    """``stale`` when an approval exists for an earlier digest of the same sequence."""

    if approval is None:
        return "unapproved"
    if approval.sequence_id != requirements.sequence_id:
        return "unapproved"
    return "approved" if approval.requirements_digest == requirements.digest() else "stale"


def load_requirement_set(path: Path) -> RequirementSet:
    return RequirementSet.model_validate(json.loads(path.read_text(encoding="utf-8")))


def protocol_reference(job: JobSpec) -> tuple[str, str] | None:
    """(sequence_id, requirements_digest) when the job was built under the protocol."""

    reference = job.sequence.parameters.get("protocol")
    if not isinstance(reference, dict):
        return None
    sequence_id = reference.get("sequence_id")
    digest = reference.get("requirements_digest")
    if isinstance(sequence_id, str) and isinstance(digest, str):
        return sequence_id, digest
    return None


__all__ = [
    "APPROVAL_SCHEMA",
    "REQUIREMENTS_SCHEMA",
    "ApprovalStatus",
    "Citation",
    "Condition",
    "FailureBehaviour",
    "Invariant",
    "Outcome",
    "PointDeclaration",
    "Requirement",
    "RequirementApproval",
    "RequirementSet",
    "SetupPhase",
    "Source",
    "Timing",
    "approval_status",
    "canonical_digest",
    "load_requirement_set",
    "protocol_reference",
]
