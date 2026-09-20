from __future__ import annotations

from collections import defaultdict, deque
from typing import TYPE_CHECKING

from bactalk.domain import (
    AssertionResult,
    ComparisonOperator,
    ControlGraph,
    ScenarioResult,
    TestReport,
)
from bactalk.simulator import GraphInterpreter

if TYPE_CHECKING:
    from bactalk.projects import ProjectOutputExpectation, ProjectSpec


class ProjectGraphInterpreter:
    """Execute multiple typed equipment programs with explicit signal flow."""

    def __init__(self, project: ProjectSpec, graphs: dict[str, ControlGraph]):
        expected = {job.equipment_name for job in project.equipment}
        if set(graphs) != expected:
            raise ValueError("project simulator requires exactly one graph per equipment job")
        self.project = project
        self.graphs = graphs
        self.interpreters = {
            equipment: GraphInterpreter(graph) for equipment, graph in graphs.items()
        }
        self.order = _equipment_order(project)
        self.incoming = defaultdict(list)
        for binding in project.signal_bindings:
            self.incoming[binding.target_equipment].append(binding)

    def evaluate(
        self,
        inputs: dict[str, float | bool],
        *,
        step_seconds: float,
    ) -> dict[str, float | bool]:
        per_equipment: dict[str, dict[str, float | bool]] = defaultdict(dict)
        for qualified, value in inputs.items():
            equipment, point = qualified.split(".", 1)
            per_equipment[equipment][point] = value

        values: dict[str, dict[str, float | bool]] = {}
        flattened: dict[str, float | bool] = {}
        for equipment in self.order:
            equipment_inputs = dict(per_equipment[equipment])
            for binding in self.incoming[equipment]:
                equipment_inputs[binding.target_point] = values[binding.source_equipment][
                    binding.source_point
                ]
            equipment_values = self.interpreters[equipment].evaluate(
                equipment_inputs,
                step_seconds=step_seconds,
            )
            values[equipment] = equipment_values
            flattened.update(
                {f"{equipment}.{point}": value for point, value in equipment_values.items()}
            )
        return flattened


def run_project_acceptance_suite(
    project: ProjectSpec,
    graphs: dict[str, ControlGraph],
) -> TestReport:
    results: list[ScenarioResult] = []
    for case in project.acceptance_tests:
        interpreter = ProjectGraphInterpreter(project, graphs)
        current_inputs: dict[str, float | bool] = {}
        samples: list[dict[str, float | bool]] = []
        assertions: list[AssertionResult] = []
        scan = 0
        for phase_index, phase in enumerate(case.phases, start=1):
            current_inputs.update(phase.inputs)
            interpreter.evaluate(current_inputs, step_seconds=0.0)
            values: dict[str, float | bool] = {}
            for phase_step in range(1, phase.repeat + 1):
                scan += 1
                values = interpreter.evaluate(
                    current_inputs,
                    step_seconds=phase.step_seconds,
                )
                samples.append(
                    {
                        "step": float(scan),
                        "phase": float(phase_index),
                        "phase_step": float(phase_step),
                        **current_inputs,
                        **values,
                    }
                )
            for expectation in phase.expectations:
                qualified = f"{expectation.equipment}.{expectation.point}"
                observed = values[qualified]
                assertions.append(
                    AssertionResult(
                        name=f"{case.name} / {phase.name}: {qualified}",
                        passed=_compare(expectation, observed),
                        observed=str(observed),
                        expected=_expected_text(expectation),
                    )
                )
        results.append(
            ScenarioResult(
                name=case.name,
                passed=all(assertion.passed for assertion in assertions),
                assertions=assertions,
                samples=samples,
            )
        )
    return TestReport(
        passed=all(result.passed for result in results),
        scenarios=results,
        engine="BACTalk typed whole-building signal simulator (Tier 1)",
        coverage={
            "schema": "bactalk.project-signal-coverage/v1",
            "equipment_count": len(project.equipment),
            "signal_binding_count": len(project.signal_bindings),
            "acceptance_case_count": len(project.acceptance_tests),
            "phase_count": sum(len(case.phases) for case in project.acceptance_tests),
            "all_project_acceptance_passed": all(result.passed for result in results),
            "scope": (
                "Typed cross-equipment signal execution; this is not a dynamic building-physics "
                "or licensed Niagara runtime test."
            ),
        },
    )


def _equipment_order(project: ProjectSpec) -> list[str]:
    names = [job.equipment_name for job in project.equipment]
    adjacency: dict[str, set[str]] = defaultdict(set)
    indegree = {name: 0 for name in names}
    for binding in project.signal_bindings:
        if binding.target_equipment not in adjacency[binding.source_equipment]:
            adjacency[binding.source_equipment].add(binding.target_equipment)
            indegree[binding.target_equipment] += 1
    queue = deque(sorted(name for name, degree in indegree.items() if degree == 0))
    ordered: list[str] = []
    while queue:
        current = queue.popleft()
        ordered.append(current)
        for target in sorted(adjacency[current]):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if len(ordered) != len(names):
        raise ValueError("project signal graph is cyclic")
    return ordered


def _compare(expectation: ProjectOutputExpectation, observed: float | bool) -> bool:
    expected = expectation.value
    if isinstance(expected, bool):
        if expectation.operator == ComparisonOperator.EQUAL:
            return observed is expected
        if expectation.operator == ComparisonOperator.NOT_EQUAL:
            return observed is not expected
        return False
    if isinstance(observed, bool):
        return False
    actual = float(observed)
    target = float(expected)
    tolerance = expectation.tolerance
    if expectation.operator == ComparisonOperator.EQUAL:
        return abs(actual - target) <= tolerance
    if expectation.operator == ComparisonOperator.NOT_EQUAL:
        return abs(actual - target) > tolerance
    if expectation.operator == ComparisonOperator.GREATER_THAN:
        return actual > target
    if expectation.operator == ComparisonOperator.GREATER_THAN_OR_EQUAL:
        return actual + tolerance >= target
    if expectation.operator == ComparisonOperator.LESS_THAN:
        return actual < target
    if expectation.operator == ComparisonOperator.LESS_THAN_OR_EQUAL:
        return actual - tolerance <= target
    if expectation.operator == ComparisonOperator.BETWEEN:
        return (
            expectation.upper is not None
            and target - tolerance <= actual <= expectation.upper + tolerance
        )
    raise ValueError(f"unsupported comparison operator: {expectation.operator}")


def _expected_text(expectation: ProjectOutputExpectation) -> str:
    if expectation.operator == ComparisonOperator.BETWEEN:
        return f"between {expectation.value} and {expectation.upper}"
    return f"{expectation.operator.value} {expectation.value} ± {expectation.tolerance}"
