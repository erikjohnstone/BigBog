"""Adequacy: is the generated suite strong enough, and does the logic pass it?

Accepted only when every scenario passes, every typed decision saw both outcomes,
every invariant held at every step of every scenario and across the randomised
sequences, a seeded mutant sample of the exported ``.bog`` is caught at or above
95 %, and every requirement has at least one scenario. Anything less is reported
as measured with the failing scenarios classified.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from bactalk.domain import JobSpec, TestReport
from bactalk.niagara.differential import three_way_differential
from bactalk.niagara.emit import emit_bog
from bactalk.niagara.mutate import generate_mutants, run_mutation_suite
from bactalk.niagara.shadow.policy import DEFAULT_POLICY, SCAN_POLICY, ExecutionPolicy
from bactalk.protocol.classify import Classification, classify_failure
from bactalk.protocol.invariants import invariant_violations, random_input_sequences
from bactalk.protocol.requirements import RequirementSet, canonical_digest
from bactalk.protocol.test_author import TestPlan
from bactalk.simulator import GraphInterpreter, run_acceptance_suite

ADEQUACY_SCHEMA = "bactalk.protocol-adequacy/v1"
MUTATION_TARGET = 0.95
INVARIANT_SEQUENCES = 10_000
INVARIANT_STEPS = 24
MUTATION_SEED = 7
LEGS: dict[str, tuple[ExecutionPolicy, str]] = {
    "default": (DEFAULT_POLICY, "default"),
    "scan": (SCAN_POLICY, "scan"),
}


@dataclass
class AdequacyReport:
    sequence_id: str
    requirements_digest: str
    plan_digest: str
    suite: dict[str, Any]
    decisions: dict[str, Any]
    invariants: dict[str, Any]
    differential: dict[str, Any]
    mutation: dict[str, Any] | None
    traceability: dict[str, Any]
    gaps: list[dict[str, str]]
    classifications: list[Classification] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return (
            bool(self.suite["passed"])
            and bool(self.decisions.get("fully_covered"))
            and bool(self.invariants["passed"])
            and self.invariants["sequences"] >= INVARIANT_SEQUENCES
            and any(leg.get("passed") for leg in self.differential.values() if leg)
            and self.mutation is not None
            and "catch_rate" in self.mutation
            and self.mutation["catch_rate"] >= MUTATION_TARGET
            and not self.traceability["requirements_without_scenarios"]
        )

    @property
    def questions(self) -> list[str]:
        return [
            item.question
            for item in self.classifications
            if item.category == "ambiguous_requirement" and item.question
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": ADEQUACY_SCHEMA,
            "sequence_id": self.sequence_id,
            "requirements_digest": self.requirements_digest,
            "plan_digest": self.plan_digest,
            "accepted": self.accepted,
            "mutation_target": MUTATION_TARGET,
            "invariant_sequences_required": INVARIANT_SEQUENCES,
            "suite": self.suite,
            "decisions": self.decisions,
            "invariants": self.invariants,
            "differential": self.differential,
            "mutation": self.mutation,
            "traceability": self.traceability,
            "gaps": self.gaps,
            "classifications": [item.to_dict() for item in self.classifications],
            "questions": self.questions,
        }

    def digest(self) -> str:
        return canonical_digest(self.to_dict())


def job_with_plan(job: JobSpec, plan: TestPlan) -> JobSpec:
    return job.model_copy(update={"acceptance_tests": plan.cases()})


def run_suite(
    job: JobSpec, plan: TestPlan, requirements: RequirementSet
) -> tuple[TestReport, dict[str, Any]]:
    """The interpreter runs every planned scenario; invariants are checked on every sample."""

    if job.control_graph is None:
        raise ValueError("the job carries no control graph")
    started = time.time()
    planned = job_with_plan(job, plan)
    report = run_acceptance_suite(planned.control_graph, planned)
    scenarios: list[dict[str, Any]] = []
    invariant_failures: list[dict[str, Any]] = []
    for result in report.scenarios:
        scenario = plan.scenario(result.name)
        failures = [
            {"assertion": a.name, "observed": a.observed, "expected": a.expected}
            for a in result.assertions
            if not a.passed
        ]
        step_violations = 0
        for index, sample in enumerate(result.samples):
            for violation in invariant_violations(requirements, sample):
                step_violations += 1
                if len(invariant_failures) < 50:
                    invariant_failures.append({"scenario": result.name, "step": index, **violation})
        scenarios.append(
            {
                "name": result.name,
                "requirement_id": scenario.requirement_id,
                "kind": scenario.kind,
                "passed": result.passed and step_violations == 0,
                "failures": failures,
                "invariant_violations": step_violations,
            }
        )
    summary = {
        "passed": all(item["passed"] for item in scenarios),
        "scenarios": scenarios,
        "count": len(scenarios),
        "failed": sum(1 for item in scenarios if not item["passed"]),
        "invariant_violations": invariant_failures,
        "seconds": round(time.time() - started, 1),
    }
    return report, summary


def check_invariants(
    job: JobSpec,
    requirements: RequirementSet,
    *,
    sequences: int = INVARIANT_SEQUENCES,
    steps: int = INVARIANT_STEPS,
    seed: int = MUTATION_SEED,
) -> dict[str, Any]:
    """Every invariant on every step of ``sequences`` randomised input sequences."""

    if job.control_graph is None:
        raise ValueError("the job carries no control graph")
    started = time.time()
    outputs = [point.name for point in requirements.outputs]
    violations: list[dict[str, Any]] = []
    count = 0
    checked = 0
    for index, sequence in enumerate(
        random_input_sequences(requirements, count=sequences, steps=steps, seed=seed)
    ):
        interpreter = GraphInterpreter(job.control_graph)
        for step, inputs in enumerate(sequence):
            values = interpreter.evaluate(inputs, step_seconds=requirements.step_seconds)
            sample = {**inputs, **{name: values[name] for name in outputs if name in values}}
            found = invariant_violations(requirements, sample)
            checked += 1
            count += len(found)
            for violation in found:
                if len(violations) < 25:
                    violations.append(
                        {"sequence": index, "step": step, "inputs": inputs, **violation}
                    )
    return {
        "sequences": sequences,
        "steps_per_sequence": steps,
        "steps_checked": checked,
        "seed": seed,
        "invariants": [invariant.id for invariant in requirements.invariants],
        "violations": count,
        "examples": violations,
        "passed": count == 0 and bool(requirements.invariants),
        "seconds": round(time.time() - started, 1),
    }


def differential_leg(job: JobSpec, plan: TestPlan, leg: str = "scan") -> dict[str, Any]:
    """D3 with no reference: the Shadow Runtime and the interpreter agree inside the
    bands on every scenario, under one execution policy (docs/decisions/010 items 7–8)."""

    if job.control_graph is None:
        raise ValueError("the job carries no control graph")
    policy, band_set = LEGS[leg]
    started = time.time()
    planned = job_with_plan(job, plan)
    content = emit_bog(planned.control_graph, points=planned.points).content
    report = three_way_differential(
        planned, bog=content, reference=None, policy=policy, band_set=band_set
    )
    failing = [case.name for case in report.cases if not case.passed]
    return {
        "policy": policy.name,
        "band_set": band_set,
        "passed": report.passed,
        "cases": len(report.cases),
        "failing_cases": failing[:10],
        "first_divergence": next(
            (case.first_divergence for case in report.cases if not case.passed), None
        ),
        "seconds": round(time.time() - started, 1),
    }


def mutation_score(
    job: JobSpec,
    plan: TestPlan,
    *,
    mutants: int = 200,
    seed: int = MUTATION_SEED,
    leg: str = "scan",
) -> dict[str, Any]:
    """D4 for the protocol suite: the interpreter and the Shadow Runtime judge each mutant
    under the ``leg`` policy. Tier 3 plants carry multi-day scenarios (runtime rotation),
    which a per-second module tick cannot judge 200 times over, so the scan leg (module
    kernels tick once per scan, coarse bands) is the default and the artifact names it."""

    if job.control_graph is None:
        raise ValueError("the job carries no control graph")
    policy, band_set = LEGS[leg]
    started = time.time()
    planned = job_with_plan(job, plan)
    content = emit_bog(planned.control_graph, points=planned.points).content
    generated = len(generate_mutants(content, seed=seed))
    try:
        report = run_mutation_suite(
            content,
            plan.cases(),
            seed=seed,
            limit=mutants,
            job=planned,
            reference=None,
            policy=policy,
            band_set=band_set,
        )
    except ValueError as exc:
        return {
            "blocker": f"baseline: {exc}",
            "policy": policy.name,
            "band_set": band_set,
            "mutants_generated": generated,
            "seconds": round(time.time() - started, 1),
        }
    summary = report.to_dict()
    return {
        "passed": summary["catch_rate"] >= MUTATION_TARGET,
        "policy": policy.name,
        "band_set": band_set,
        "mutants_generated": generated,
        "sample": summary["total"],
        "caught": summary["caught"],
        "catch_rate": summary["catch_rate"],
        "by_catcher": summary["by_catcher"],
        "by_operator": summary["by_operator"],
        "survivors": summary["survivors"][:25],
        "seconds": round(time.time() - started, 1),
    }


def assess_adequacy(
    job: JobSpec,
    requirements: RequirementSet,
    plan: TestPlan,
    *,
    mutants: int | None = 200,
    invariant_sequences: int = INVARIANT_SEQUENCES,
    invariant_steps: int = INVARIANT_STEPS,
    seed: int = MUTATION_SEED,
    mutation_leg: str = "scan",
    differential_legs: tuple[str, ...] = ("scan",),
) -> AdequacyReport:
    """Run the suite, decision coverage, invariants, the D3 legs and (unless ``mutants``
    is None) the mutation sample; classify every failure."""

    if plan.requirements_digest != requirements.digest():
        raise ValueError("the test plan was generated from a different requirement set")
    report, suite = run_suite(job, plan, requirements)
    decisions = {
        key: report.coverage.get(key)
        for key in (
            "decision_count",
            "outcomes_observed",
            "outcomes_possible",
            "percent",
            "fully_covered",
            "gaps",
        )
    }
    invariants = check_invariants(
        job, requirements, sequences=invariant_sequences, steps=invariant_steps, seed=seed
    )
    differential = {leg: differential_leg(job, plan, leg) for leg in differential_legs}
    mutation = (
        mutation_score(job, plan, mutants=mutants, seed=seed, leg=mutation_leg) if mutants else None
    )
    traced = plan.traceability()
    traceability = {
        "requirements_without_scenarios": [
            requirement.id
            for requirement in requirements.requirements
            if requirement.id not in traced
        ],
        "scenarios_per_requirement": {key: len(value) for key, value in traced.items()},
    }
    classifications = [
        classify_failure(
            requirements,
            plan,
            scenario["name"],
            failure["assertion"],
            failure["observed"],
            failure["expected"],
        )
        for scenario in suite["scenarios"]
        for failure in scenario["failures"]
    ]
    return AdequacyReport(
        sequence_id=requirements.sequence_id,
        requirements_digest=requirements.digest(),
        plan_digest=plan.digest(),
        suite=suite,
        decisions=decisions,
        invariants=invariants,
        differential=differential,
        mutation=mutation,
        traceability=traceability,
        gaps=list(plan.gaps),
        classifications=classifications,
    )


__all__ = [
    "ADEQUACY_SCHEMA",
    "INVARIANT_SEQUENCES",
    "MUTATION_TARGET",
    "AdequacyReport",
    "assess_adequacy",
    "check_invariants",
    "differential_leg",
    "job_with_plan",
    "mutation_score",
    "run_suite",
]
