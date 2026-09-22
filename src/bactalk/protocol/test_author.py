"""The protocol's test author.

Acceptance scenarios are built mechanically from an approved requirement set:
per requirement a positive and a negative scenario, timing boundaries just before
and after every delay and release window, value boundaries at every threshold and
deadband edge, the stated failure behaviour per input, and recovery. Invariants
come from the set as written and are checked at every step of every scenario and
across randomised input sequences (``invariants``).

This module sees requirements only. It imports the requirement model and the
acceptance-case schema, never a control graph, the Shadow Runtime or a library
job; ``tests/test_protocol.py`` checks that import list, which is the "no API
access to the logic" rule of the protocol enforced in code.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

from bactalk.domain import AcceptanceCase, AcceptancePhase, FaultInjection, FaultKind
from bactalk.protocol.invariants import condition_holds, random_input_sequences
from bactalk.protocol.requirements import (
    Condition,
    FailureBehaviour,
    Outcome,
    PointDeclaration,
    Requirement,
    RequirementSet,
    canonical_digest,
)

GENERATOR_VERSION = "bactalk.protocol-test-author/v1"

ScenarioKind = Literal[
    "positive",
    "negative",
    "negative_single",
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
]


@dataclass(frozen=True)
class PlannedScenario:
    id: str
    requirement_id: str
    kind: ScenarioKind
    subject: str | None
    rationale: str
    case: AcceptanceCase

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "requirement_id": self.requirement_id,
            "kind": self.kind,
            "subject": self.subject,
            "rationale": self.rationale,
            "case": self.case.model_dump(mode="json"),
        }


@dataclass
class TestPlan:
    sequence_id: str
    requirements_digest: str
    scenarios: list[PlannedScenario] = field(default_factory=list)
    invariant_ids: list[str] = field(default_factory=list)
    gaps: list[dict[str, str]] = field(default_factory=list)
    generator: str = GENERATOR_VERSION

    def cases(self) -> list[AcceptanceCase]:
        return [scenario.case for scenario in self.scenarios]

    def traceability(self) -> dict[str, list[str]]:
        table: dict[str, list[str]] = {}
        for scenario in self.scenarios:
            table.setdefault(scenario.requirement_id, []).append(scenario.id)
        return table

    def scenario(self, name: str) -> PlannedScenario:
        for scenario in self.scenarios:
            if scenario.case.name == name or scenario.id == name:
                return scenario
        raise KeyError(name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bactalk.protocol-test-plan/v1",
            "generator": self.generator,
            "sequence_id": self.sequence_id,
            "requirements_digest": self.requirements_digest,
            "scenarios": [scenario.to_dict() for scenario in self.scenarios],
            "invariants": list(self.invariant_ids),
            "gaps": list(self.gaps),
        }

    def digest(self) -> str:
        return canonical_digest(self.to_dict())


# --- values on either side of a condition -------------------------------------------


def _clamp(point: PointDeclaration, value: float) -> float:
    low = point.minimum if point.minimum is not None else value
    high = point.maximum if point.maximum is not None else value
    return min(high, max(low, value))


def satisfying_value(condition: Condition, point: PointDeclaration) -> float | bool:
    """A value that makes the condition true, clear of any deadband edge."""

    if isinstance(condition.value, bool):
        return condition.value if condition.operator == "eq" else not condition.value
    threshold = float(condition.value)
    margin = point.margin
    match condition.operator:
        case "eq":
            value = threshold
        case "ne" | "gt":
            value = threshold + margin
        case "gte":
            value = threshold
        case "lt":
            value = threshold - margin
        case "lte":
            value = threshold
        case _:
            value = (threshold + float(condition.upper or threshold)) / 2.0
    return _clamp(point, value)


def violating_value(condition: Condition, point: PointDeclaration) -> float | bool:
    """A value that makes the condition false and clears its deadband."""

    if isinstance(condition.value, bool):
        return (not condition.value) if condition.operator == "eq" else condition.value
    threshold = float(condition.value)
    margin = point.margin
    deadband = condition.deadband
    match condition.operator:
        case "eq":
            value = threshold + margin
        case "ne":
            value = threshold
        case "gt" | "gte":
            value = threshold - deadband - margin
        case "lt" | "lte":
            value = threshold + deadband + margin
        case _:
            value = threshold - margin
    return _clamp(point, value)


def boundary_values(condition: Condition, point: PointDeclaration) -> list[tuple[str, float, bool]]:
    """(label, value, condition holds) at the edges of a numeric condition."""

    if isinstance(condition.value, bool):
        return []
    threshold = float(condition.value)
    margin = point.margin
    match condition.operator:
        case "gt":
            edges = [("at threshold", threshold, False), ("just above", threshold + margin, True)]
        case "gte":
            edges = [("just below", threshold - margin, False), ("at threshold", threshold, True)]
        case "lt":
            edges = [("at threshold", threshold, False), ("just below", threshold - margin, True)]
        case "lte":
            edges = [("just above", threshold + margin, False), ("at threshold", threshold, True)]
        case "eq":
            edges = [("at value", threshold, True), ("just above", threshold + margin, False)]
        case "ne":
            edges = [("at value", threshold, False), ("just above", threshold + margin, True)]
        case _:
            upper = float(condition.upper or threshold)
            edges = [
                ("at lower edge", threshold, True),
                ("just below lower edge", threshold - margin, False),
                ("at upper edge", upper, True),
                ("just above upper edge", upper + margin, False),
            ]
    return [(label, _clamp(point, value), holds) for label, value, holds in edges]


def deadband_values(condition: Condition, point: PointDeclaration) -> tuple[float, float] | None:
    """(still held inside the deadband, released past it) for a hysteretic condition."""

    if isinstance(condition.value, bool) or not condition.deadband:
        return None
    threshold = float(condition.value)
    margin = point.margin
    if condition.operator in {"gt", "gte"}:
        return (
            _clamp(point, threshold - condition.deadband + margin),
            _clamp(point, threshold - condition.deadband - margin),
        )
    if condition.operator in {"lt", "lte"}:
        return (
            _clamp(point, threshold + condition.deadband - margin),
            _clamp(point, threshold + condition.deadband + margin),
        )
    return None


# --- the generator --------------------------------------------------------------------


def _steps(seconds: float, step: float) -> int:
    return max(0, math.ceil(seconds / step - 1e-9))


def _expectations(outcomes: list[Outcome]) -> list:
    return [outcome.expectation() for outcome in outcomes]


class _Author:
    def __init__(self, requirements: RequirementSet):
        self.requirements = requirements
        self.plan = TestPlan(
            sequence_id=requirements.sequence_id,
            requirements_digest=requirements.digest(),
            invariant_ids=[invariant.id for invariant in requirements.invariants],
        )

    # helpers ---------------------------------------------------------------------

    def _gap(self, requirement: Requirement, kind: str, question: str) -> None:
        self.plan.gaps.append(
            {"requirement_id": requirement.id, "kind": kind, "question": question}
        )

    def _add(
        self,
        requirement: Requirement,
        kind: ScenarioKind,
        subject: str | None,
        rationale: str,
        phases: list[AcceptancePhase],
    ) -> None:
        suffix = f" [{subject}]" if subject else ""
        name = f"{requirement.id} {kind}{suffix}"
        if not any(phase.expectations for phase in phases):
            return
        final = next(phase.expectations for phase in reversed(phases) if phase.expectations)
        # Top-level expectations are the end state of the timeline (the runner checks
        # them after the last phase), so they repeat the last phase that expects anything.
        case = AcceptanceCase(name=name[:200], timeline=phases, expectations=list(final))
        self.plan.scenarios.append(
            PlannedScenario(
                id=name[:200],
                requirement_id=requirement.id,
                kind=kind,
                subject=subject,
                rationale=rationale,
                case=case,
            )
        )

    def _phase(
        self,
        name: str,
        inputs: dict[str, float | bool],
        repeat: int,
        step: float,
        outcomes: list[Outcome] | None = None,
        faults: list[FaultInjection] | None = None,
    ) -> AcceptancePhase:
        expected = list(outcomes or [])
        if not faults:
            expected = self._with_invariants(inputs, expected)
        return AcceptancePhase(
            name=name,
            inputs=dict(inputs),
            repeat=max(1, repeat),
            step_seconds=step,
            expectations=_expectations(expected),
            faults=list(faults or []),
        )

    def _with_invariants(
        self, inputs: dict[str, float | bool], outcomes: list[Outcome]
    ) -> list[Outcome]:
        """Every invariant whose ``when`` the phase establishes (on its inputs, or through
        an outcome the phase already expects) adds its ``then`` to the phase, so the
        suite asserts the invariants at every phase end, not only the adequacy runner
        at every step. This is what lets a mutant that breaks an invariant fail the
        suite oracle."""

        expected = list(outcomes)
        seen = {(o.point, o.operator, o.value, o.upper) for o in expected}
        for invariant in self.requirements.invariants:
            holds = True
            for condition in invariant.when:
                if condition.point in inputs:
                    holds = condition_holds(condition, inputs[condition.point])
                else:
                    implied = next(
                        (
                            o
                            for o in outcomes
                            if o.point == condition.point
                            and o.operator == "eq"
                            and condition.operator == "eq"
                            and o.value == condition.value
                        ),
                        None,
                    )
                    holds = implied is not None
                if not holds:
                    break
            if not holds:
                continue
            for outcome in invariant.then:
                key = (outcome.point, outcome.operator, outcome.value, outcome.upper)
                if key in seen or any(o.point == outcome.point for o in expected):
                    continue
                seen.add(key)
                expected.append(outcome)
        return expected

    def _setup(self, requirement: Requirement, step: float) -> list[AcceptancePhase]:
        nominal = self.requirements.nominal_inputs()
        phases = []
        inputs = dict(nominal)
        for index, setup in enumerate(self.requirements.effective_setup(requirement), start=1):
            inputs.update(setup.inputs)
            phases.append(
                self._phase(
                    f"setup {index}: {setup.name}",
                    inputs,
                    _steps(setup.seconds, step),
                    step,
                )
            )
        return phases

    # per requirement -------------------------------------------------------------

    def author(self) -> TestPlan:
        for requirement in self.requirements.requirements:
            self._requirement(requirement)
        return self.plan

    def _requirement(self, requirement: Requirement) -> None:
        rs = self.requirements
        step = requirement.step_seconds or rs.step_seconds
        # Inherited conditions (``assumes``) are the context every scenario keeps
        # satisfied; the requirement's own conditions are what the scenarios drive. A
        # requirement with no conditions of its own is driven through its context.
        context: dict[str, Condition] = {}
        for other in rs.assumption_closure(requirement.id):
            for condition in rs.requirement(other).conditions:
                context[condition.point] = condition
        own = list(requirement.conditions) or list(context.values())
        for condition in own:
            context.pop(condition.point, None)
        conditions = own
        points = {c.point: rs.point(c.point) for c in [*own, *context.values()]}
        base = dict(rs.nominal_inputs())
        for setup in rs.effective_setup(requirement):
            base.update(setup.inputs)
        for condition in context.values():
            base[condition.point] = satisfying_value(condition, points[condition.point])
        satisfied = {
            **base,
            **{c.point: satisfying_value(c, points[c.point]) for c in conditions},
        }
        violated = {
            **base,
            **{c.point: violating_value(c, points[c.point]) for c in conditions},
        }
        for condition in conditions:
            if satisfied[condition.point] == violated[condition.point]:
                self._gap(
                    requirement,
                    "unreachable_condition",
                    f"{condition.point} cannot be made both true and false inside its "
                    "declared range; which range should the tests use?",
                )
        delay_steps = _steps(requirement.timing.delay_seconds, step)
        release_steps = _steps(requirement.timing.release_seconds, step)
        for label, seconds in (
            ("delay", requirement.timing.delay_seconds),
            ("release", requirement.timing.release_seconds),
        ):
            if seconds and abs(seconds / step - round(seconds / step)) > 1e-9:
                self._gap(
                    requirement,
                    "timing_resolution",
                    f"the {label} of {seconds} s is not a multiple of the {step} s scan; "
                    "the boundary scenarios round up. Which scan applies?",
                )
        settle = max(release_steps + 1, 2)
        setup = self._setup(requirement, step)
        otherwise = requirement.otherwise
        before = requirement.before if requirement.before is not None else otherwise
        lag = requirement.timing.tolerance_scans
        # A delay referenced to the context runs from the start of the baseline phase,
        # so the trigger phase is shorter by the baseline's length.
        offset = settle if requirement.timing.reference == "context" else 0
        if not otherwise:
            self._gap(
                requirement,
                "no_otherwise",
                "what should the outputs be while the conditions do not hold? Without "
                "it the negative, boundary-false and recovery scenarios assert nothing.",
            )

        def baseline(expect: bool = True) -> AcceptancePhase:
            return self._phase(
                "baseline: conditions not met", violated, settle, step, otherwise if expect else []
            )

        def trigger(repeat: int, outcomes: list[Outcome], name: str = "conditions met") -> Any:
            return self._phase(name, satisfied, repeat, step, outcomes)

        # positive / negative ---------------------------------------------------
        self._add(
            requirement,
            "positive",
            None,
            "every condition holds for the stated delay; the stated outputs follow",
            [*setup, baseline(), trigger(delay_steps + lag + 2 - offset, requirement.outcomes)],
        )
        self._add(
            requirement,
            "negative",
            None,
            "no condition holds for longer than the release window; the 'otherwise' outputs hold",
            [
                *setup,
                baseline(False),
                self._phase(
                    "conditions not met",
                    violated,
                    delay_steps + lag + release_steps + 2,
                    step,
                    otherwise,
                ),
            ],
        )
        if len(conditions) > 1:
            for condition in conditions:
                single = {**satisfied, condition.point: violated[condition.point]}
                self._add(
                    requirement,
                    "negative_single",
                    condition.point,
                    f"all conditions hold except {condition.point}; the outputs must not follow",
                    [
                        *setup,
                        baseline(False),
                        self._phase(
                            f"all met but {condition.point}",
                            single,
                            delay_steps + lag + release_steps + 2,
                            step,
                            otherwise,
                        ),
                    ],
                )
        # timing: the runner primes every phase with a zero-length scan, so a window of
        # D seconds has elapsed after D / step repeats; one scan short is one repeat less.
        if delay_steps - 1 - offset >= 1:
            self._add(
                requirement,
                "timing_before",
                None,
                f"conditions held one scan short of the {requirement.timing.delay_seconds} s "
                "delay; the outputs must not have changed yet",
                [
                    *setup,
                    baseline(False),
                    trigger(delay_steps - 1 - offset, before, "one scan short"),
                ],
            )
            self._add(
                requirement,
                "timing_after",
                None,
                f"conditions held exactly {requirement.timing.delay_seconds} s"
                + (f" plus {lag} scans of tolerance" if lag else "")
                + "; the outputs follow",
                [
                    *setup,
                    baseline(False),
                    trigger(delay_steps + lag - offset, requirement.outcomes, "delay elapsed"),
                ],
            )
        if release_steps > 1:
            self._add(
                requirement,
                "release_before",
                None,
                f"conditions cleared one scan short of the {requirement.timing.release_seconds} s "
                "release; the outputs persist",
                [
                    *setup,
                    baseline(False),
                    trigger(delay_steps + lag + 2 - offset, requirement.outcomes),
                    self._phase(
                        "cleared, one scan short",
                        violated,
                        release_steps - 1,
                        step,
                        requirement.outcomes,
                    ),
                ],
            )
            self._add(
                requirement,
                "release_after",
                None,
                f"conditions cleared for {requirement.timing.release_seconds} s; "
                "the outputs release",
                [
                    *setup,
                    baseline(False),
                    trigger(delay_steps + lag + 2 - offset, requirement.outcomes),
                    self._phase(
                        "cleared, release elapsed",
                        violated,
                        release_steps + lag,
                        step,
                        otherwise,
                    ),
                ],
            )
        # value boundaries ------------------------------------------------------------
        for condition in conditions:
            point = points[condition.point]
            for label, value, holds in boundary_values(condition, point):
                inputs = {**satisfied, condition.point: value}
                self._add(
                    requirement,
                    "boundary_true" if holds else "boundary_false",
                    f"{condition.point} {label}",
                    f"{condition.point} {label} ({value:g}); the condition "
                    + ("holds" if holds else "does not hold"),
                    [
                        *setup,
                        baseline(False),
                        self._phase(
                            f"{condition.point} {label}",
                            inputs,
                            delay_steps + lag + release_steps + 2,
                            step,
                            requirement.outcomes if holds else otherwise,
                        ),
                    ],
                )
            edges = deadband_values(condition, point)
            if edges is not None:
                held, released = edges
                self._add(
                    requirement,
                    "deadband_hold",
                    condition.point,
                    f"{condition.point} falls back inside the {condition.deadband:g} deadband; "
                    "the outputs persist",
                    [
                        *setup,
                        baseline(False),
                        trigger(delay_steps + lag + 2 - offset, requirement.outcomes),
                        self._phase(
                            "inside the deadband",
                            {**satisfied, condition.point: held},
                            release_steps + 2,
                            step,
                            requirement.outcomes,
                        ),
                    ],
                )
                self._add(
                    requirement,
                    "deadband_release",
                    condition.point,
                    f"{condition.point} passes the far side of the deadband; the outputs release",
                    [
                        *setup,
                        baseline(False),
                        trigger(delay_steps + lag + 2 - offset, requirement.outcomes),
                        self._phase(
                            "past the deadband",
                            {**satisfied, condition.point: released},
                            release_steps + 2,
                            step,
                            otherwise,
                        ),
                    ],
                )
        # failures per input ----------------------------------------------------------
        declared = {(failure.point, failure.mode) for failure in requirement.failures}
        for failure in requirement.failures:
            self._failure(
                requirement, failure, satisfied, setup, baseline(False), delay_steps, step
            )
        unstated: list[str] = []
        for condition in conditions:
            point = points[condition.point]
            modes = ["stuck", "stale"] + (
                ["out_of_range_low", "out_of_range_high"] if point.data_type == "numeric" else []
            )
            missing = [mode for mode in modes if (condition.point, mode) not in declared]
            if missing:
                unstated.append(
                    f"{condition.point} " + ", ".join(m.replace("_", " ") for m in missing)
                )
        if unstated:
            self._gap(
                requirement,
                "failure_behaviour",
                "what should the outputs do when " + "; ".join(unstated) + "? No behaviour "
                "is stated, so no failure scenario asserts it.",
            )
        # recovery --------------------------------------------------------------------
        recovery = requirement.recovery if requirement.recovery is not None else otherwise
        self._add(
            requirement,
            "recovery",
            None,
            "after the outputs followed, the conditions clear; the outputs recover",
            [
                *setup,
                baseline(False),
                trigger(delay_steps + lag + 2 - offset, requirement.outcomes),
                self._phase("conditions cleared", violated, release_steps + 2, step, recovery),
            ],
        )

    def _failure(
        self,
        requirement: Requirement,
        failure: FailureBehaviour,
        satisfied: dict[str, float | bool],
        setup: list[AcceptancePhase],
        baseline: AcceptancePhase,
        delay_steps: int,
        step: float,
    ) -> None:
        point = self.requirements.point(failure.point)
        lag = requirement.timing.tolerance_scans
        span = 0.0
        if point.minimum is not None and point.maximum is not None:
            span = point.maximum - point.minimum
        fault_id = f"{failure.point}_{failure.mode}"
        if failure.mode == "stuck":
            fault = FaultInjection(id=fault_id, target=failure.point, kind=FaultKind.STUCK)
        elif failure.mode == "stale":
            fault = FaultInjection(id=fault_id, target=failure.point, kind=FaultKind.STALE)
        elif failure.mode == "out_of_range_low":
            value = float(point.minimum or 0.0) - max(span * 0.1, point.margin)
            fault = FaultInjection(
                id=fault_id, target=failure.point, kind=FaultKind.FORCE, value=value
            )
        else:
            value = float(point.maximum or 0.0) + max(span * 0.1, point.margin)
            fault = FaultInjection(
                id=fault_id, target=failure.point, kind=FaultKind.FORCE, value=value
            )
        self._add(
            requirement,
            "failure",
            f"{failure.point} {failure.mode.replace('_', ' ')}",
            failure.note
            or f"{failure.point} {failure.mode.replace('_', ' ')}: the stated "
            "failure behaviour holds, then the outputs recover once the input is healthy",
            [
                *setup,
                baseline,
                self._phase(
                    "conditions met", satisfied, delay_steps + lag + 2, step, requirement.outcomes
                ),
                self._phase(
                    f"{failure.point} {failure.mode.replace('_', ' ')}",
                    satisfied,
                    delay_steps + 2,
                    step,
                    failure.outcomes,
                    faults=[fault],
                ),
                self._phase(
                    "input healthy again", satisfied, delay_steps + 2, step, requirement.outcomes
                ),
            ],
        )


def generate_test_plan(requirements: RequirementSet) -> TestPlan:
    """Build the plan; deterministic for one requirement set."""

    return _Author(requirements).author()


__all__ = [
    "GENERATOR_VERSION",
    "PlannedScenario",
    "TestPlan",
    "boundary_values",
    "deadband_values",
    "generate_test_plan",
    "random_input_sequences",
    "satisfying_value",
    "violating_value",
]
