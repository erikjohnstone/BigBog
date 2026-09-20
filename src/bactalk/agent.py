from __future__ import annotations

import hashlib
from typing import Protocol

from pydantic import BaseModel

from bactalk.domain import (
    BlockKind,
    ControlGraph,
    JobSpec,
    TestReport,
    canonical_json,
    graph_changes,
)
from bactalk.integrations.g36_library import G36Library
from bactalk.integrations.plant_controls_library import PlantControlsLibrary
from bactalk.sequences import (
    build_ahu_safety_cooling,
    build_ahu_static_pressure_pi,
    build_exhaust_fan_proof,
    build_g36_vav_reheat,
    build_two_pump_selector,
)
from bactalk.simulator import run_acceptance_suite


class AgentFailure(BaseModel):
    scenario: str
    assertion: str
    observed: str
    expected: str


class AgentAttempt(BaseModel):
    iteration: int
    passed: bool
    failed_assertions: list[str]
    failures: list[AgentFailure]
    graph_sha256: str
    changes: dict[str, list[str]]


class AgentResult(BaseModel):
    graph: ControlGraph
    report: TestReport
    attempts: list[AgentAttempt]


class ControlsPlanner(Protocol):
    """Boundary implemented by deterministic packs now and an LLM planner later."""

    def plan(self, job: JobSpec) -> ControlGraph: ...

    def revise(
        self,
        job: JobSpec,
        graph: ControlGraph,
        report: TestReport,
    ) -> ControlGraph: ...


class SequencePackPlanner:
    def __init__(
        self,
        *,
        plant_controls: PlantControlsLibrary | None = None,
        g36: G36Library | None = None,
    ):
        self.plant_controls = plant_controls or PlantControlsLibrary()
        self.g36 = g36 or G36Library()

    def plan(self, job: JobSpec) -> ControlGraph:
        if job.control_graph is not None:
            return job.control_graph
        if job.sequence.library in {"plant_controls", "g36"}:
            if job.sequence.controller_id is None:  # guarded by SequenceSpec
                raise ValueError("library controller_id is required")
            library = (
                self.plant_controls
                if job.sequence.library == "plant_controls"
                else self.g36
            )
            translation = library.translate(
                job.sequence.controller_id,
                execution_profile=job.sequence.execution_profile,
                parameters=dict(job.sequence.parameters),
            )
            target_assessment = library.assess_niagara_source_target(translation)
            if not target_assessment["complete"]:
                raise ValueError(
                    f"library controller {job.sequence.controller_id!r} has no complete "
                    f"Niagara target: {target_assessment['blocker']}"
                )
            if translation.get("product_status") == "source_catalog_only":
                raise ValueError(
                    f"library controller {job.sequence.controller_id!r} is catalog-only and "
                    "cannot be used in a contractor build"
                )
            graph = ControlGraph.model_validate(translation["typed_ir"])
            points = {point.name: point for point in job.points}
            blocks = []
            for block in graph.blocks:
                point = points.get(block.id)
                if point is not None and block.kind in {
                    BlockKind.NUMERIC_INPUT,
                    BlockKind.BOOLEAN_INPUT,
                }:
                    block = block.model_copy(
                        update={"config": {**block.config, "default": point.default}}
                    )
                blocks.append(block)
            return graph.model_copy(
                update={
                    "blocks": blocks,
                    "metadata": {
                        **graph.metadata,
                        "sequence_family": job.sequence.family,
                        "library": job.sequence.library,
                        "controller_id": job.sequence.controller_id,
                        "execution_profile": job.sequence.execution_profile,
                        "product_status": translation.get("product_status"),
                        "target_assessment": target_assessment,
                    },
                }
            )
        if job.sequence.family == "G36_VAV_REHEAT":
            return build_g36_vav_reheat(job)
        if job.sequence.family == "CUSTOM_AHU_SAFETY_COOLING":
            return build_ahu_safety_cooling(job)
        if job.sequence.family == "AHU_DUCT_STATIC_PI":
            return build_ahu_static_pressure_pi(job)
        if job.sequence.family == "EXHAUST_FAN_PROOF":
            return build_exhaust_fan_proof(job)
        if job.sequence.family == "TWO_PUMP_AVAILABILITY_SELECTOR":
            return build_two_pump_selector(job)
        raise ValueError(
            f"sequence {job.sequence.family!r} has no installed deterministic pack; "
            "supply a typed control_graph or use the AI programmer"
        )

    def revise(
        self,
        job: JobSpec,
        graph: ControlGraph,
        report: TestReport,
    ) -> ControlGraph:
        raise RuntimeError(
            "the deterministic sequence pack produced a failing graph; "
            "manual sequence-pack repair is required"
        )


class ProgrammingAgent:
    """Bounded plan-test-diagnose-revise loop over validated typed graphs."""

    def __init__(self, planner: ControlsPlanner, *, max_attempts: int = 3):
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        self.planner = planner
        self.max_attempts = max_attempts

    def run(self, job: JobSpec) -> AgentResult:
        graph = self.planner.plan(job)
        attempts: list[AgentAttempt] = []
        previous_graph: ControlGraph | None = None
        for iteration in range(1, self.max_attempts + 1):
            report = run_acceptance_suite(graph, job)
            failures = [
                AgentFailure(
                    scenario=scenario.name,
                    assertion=assertion.name,
                    observed=assertion.observed,
                    expected=assertion.expected,
                )
                for scenario in report.scenarios
                for assertion in scenario.assertions
                if not assertion.passed
            ]
            attempts.append(
                AgentAttempt(
                    iteration=iteration,
                    passed=report.passed,
                    failed_assertions=[failure.assertion for failure in failures],
                    failures=failures,
                    graph_sha256=hashlib.sha256(
                        canonical_json(graph).encode("utf-8")
                    ).hexdigest(),
                    changes=(
                        {"added": [], "modified": [], "removed": []}
                        if previous_graph is None
                        else graph_changes(previous_graph, graph)
                    ),
                )
            )
            if report.passed or iteration == self.max_attempts:
                return AgentResult(graph=graph, report=report, attempts=attempts)
            previous_graph = graph
            graph = self.planner.revise(job, graph, report)
        raise AssertionError("unreachable")
