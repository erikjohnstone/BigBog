"""Scenario driver: acceptance cases against an exported ``.bog`` (N6 item 6).

``run_shadow_suite`` applies each acceptance scenario's input trajectories to the
program's input points, advances the simulated clock scan by scan, captures every
output and internal slot into the same sample shape the IR interpreter and the
web UI use, and grades the case's expectations. ``run_under_policies`` repeats a
suite under several execution policies and reports where the verdict or the
outputs depend on the policy (N6 item 3).
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bactalk.domain import (
    AcceptanceCase,
    AssertionResult,
    DataType,
    QualificationProfile,
    ScenarioResult,
    TestReport,
)
from bactalk.niagara.shadow.blocks import Block, WritablePoint, _Comparison, _Switch
from bactalk.niagara.shadow.engine import ShadowRuntime
from bactalk.niagara.shadow.loader import Program
from bactalk.niagara.shadow.policy import DEFAULT_POLICY, PLAUSIBLE_POLICIES, ExecutionPolicy
from bactalk.niagara.shadow.status import Status
from bactalk.simulator import FaultInjector, _evaluate_expectations, _fault_coverage

ENGINE_PREFIX = "Niagara Shadow Runtime (bog-simulated"


class ShadowDriverError(ValueError):
    pass


@dataclass(frozen=True)
class ShadowRunOptions:
    policy: ExecutionPolicy = DEFAULT_POLICY
    kernel_backend: str = "auto"
    inject_fault_status: bool = False
    """S-FAULT-1: also flag stale/fault status on faulted input points."""

    sequence_family: str | None = None
    qualification_profile: QualificationProfile | None = None
    record_internals: bool = True
    """Record every internal slot (False keeps only the writable points)."""

    progress: Callable[[int, int], None] | None = None
    """Called with (scans done, scans total) after every scan."""


DEFAULT_OPTIONS = ShadowRunOptions()


@dataclass
class ShadowTrace:
    """One scenario's raw samples before grading."""

    name: str
    samples: list[dict[str, float | bool]]
    final: dict[str, float | bool]
    assertions: list[AssertionResult] = field(default_factory=list)


def _scan_total(cases: Sequence[AcceptanceCase]) -> int:
    return sum(
        sum(phase.repeat for phase in case.timeline) if case.timeline else case.repeat
        for case in cases
    )


def _sample_keys(runtime: ShadowRuntime, *, internals: bool) -> dict[str, tuple[Block, str]]:
    keys = runtime.signal_keys()
    if internals:
        return keys
    return {key: value for key, value in keys.items() if isinstance(value[0], WritablePoint)}


def _policy_for(policy: ExecutionPolicy, case: AcceptanceCase) -> ExecutionPolicy:
    """SCAN_POLICY (module period 0.0) resolves to the case's scan interval."""

    if policy.module_period_seconds != 0.0:
        return policy
    steps = [phase.step_seconds for phase in case.timeline] or [case.step_seconds]
    return policy.variant(policy.name, module_period_seconds=float(min(steps)))


def run_shadow_case(
    source: Path | bytes | Program,
    case: AcceptanceCase,
    *,
    options: ShadowRunOptions = DEFAULT_OPTIONS,
    scan_offset: int = 0,
    scan_total: int | None = None,
) -> tuple[ScenarioResult, dict[str, float | bool]]:
    """Run one case; returns the graded result and the final values."""

    runtime = ShadowRuntime(
        source, policy=_policy_for(options.policy, case), kernel_backend=options.kernel_backend
    )
    try:
        return _run_case(runtime, case, options, scan_offset, scan_total or _scan_total([case]))
    finally:
        runtime.close()


def _run_case(
    runtime: ShadowRuntime,
    case: AcceptanceCase,
    options: ShadowRunOptions,
    scan_offset: int,
    scan_total: int,
) -> tuple[ScenarioResult, dict[str, float | bool]]:
    free = runtime.free_inputs()
    input_types = {
        name: (DataType.NUMERIC if block.KIND == "n" else DataType.BOOLEAN)
        for name, block in free.items()
    }
    defaults = {name: block.fallback.value for name, block in free.items()}
    injector = FaultInjector.from_inputs(input_types, defaults)
    keys = _sample_keys(runtime, internals=options.record_internals)
    known = set(keys) | set(free)
    samples: list[dict[str, float | bool]] = []
    assertions: list[AssertionResult] = []
    values: dict[str, float | bool] = {}
    phases = case.timeline or [case]
    current: dict[str, float | bool] = {}
    scan = 0

    def apply(effective: Mapping[str, float | bool], faulted: Iterable[str]) -> None:
        flagged = set(faulted) if options.inject_fault_status else set()
        for name, value in effective.items():
            block = free.get(name)
            if block is None:
                raise ShadowDriverError(
                    f"acceptance case {case.name!r} sets {name!r}, "
                    "which is not an input point of the program"
                )
            status = Status.STALE if name in flagged else Status.OK
            runtime.write_point(block.path, value, status=status)

    def faulted_names(faults: Sequence[Any]) -> list[str]:
        return [
            fault.target
            for fault in faults
            if fault.kind.value in {"stale", "stuck", "dropout", "force"}
        ]

    for phase_index, phase in enumerate(phases, start=1):
        current.update(phase.inputs)
        faults = list(phase.faults)
        primed, _ = injector.apply(dict(current), faults, step_seconds=0.0)
        apply(primed, faulted_names(faults))
        if not runtime.started:
            runtime.start()
        for phase_step in range(1, phase.repeat + 1):
            scan += 1
            effective, evidence = injector.apply(
                dict(current), faults, step_seconds=phase.step_seconds
            )
            if options.policy.inputs_before_timers:
                apply(effective, faulted_names(faults))
                runtime.advance(phase.step_seconds)
            else:
                runtime.advance(phase.step_seconds)
                apply(effective, faulted_names(faults))
            values = runtime.snapshot(keys=keys)
            sample: dict[str, float | bool] = {"step": float(scan), "time_seconds": runtime.now}
            if case.timeline:
                sample["phase"] = float(phase_index)
                sample["phase_step"] = float(phase_step)
            sample.update(current)
            sample.update(evidence)
            sample.update(values)
            samples.append(sample)
            if options.progress is not None:
                options.progress(scan_offset + scan, scan_total)
        if case.timeline:
            assertions.extend(
                _evaluate_expectations(
                    f"{case.name} / {phase.name}", phase.expectations, values, known
                )
            )
    assertions.extend(_evaluate_expectations(case.name, case.expectations, values, known))
    return (
        ScenarioResult(
            name=case.name,
            passed=all(item.passed for item in assertions),
            assertions=assertions,
            samples=samples,
        ),
        values,
    )


def _decision_coverage(runtime: ShadowRuntime, results: Sequence[ScenarioResult]) -> dict[str, Any]:
    """Decision coverage from the file: comparison outputs and switch selectors."""

    samples = [sample for result in results for sample in result.samples]
    keys = runtime.signal_keys()
    by_block: dict[str, str] = {}
    for key, (block, slot) in keys.items():
        if slot == next(iter(block.outputs)) and "." not in key.split("/")[-1]:
            by_block.setdefault(block.path, key)
    decisions: list[tuple[str, str]] = []
    for block in runtime.ordered:
        if isinstance(block, _Comparison):
            decisions.append((by_block[block.path], by_block[block.path]))
        elif isinstance(block, _Switch):
            wire = runtime.in_links.get((block.path, "inSwitch"))
            if wire is not None and wire.source.path in by_block:
                decisions.append((f"{by_block[block.path]}.inSwitch", by_block[wire.source.path]))
    entries = []
    observed_outcomes = 0
    for decision_id, sample_key in decisions:
        observed = sorted({bool(sample[sample_key]) for sample in samples if sample_key in sample})
        observed_outcomes += len(observed)
        entries.append(
            {"decision": decision_id, "observed": observed, "both_outcomes": len(observed) == 2}
        )
    possible = len(entries) * 2
    gaps = [item["decision"] for item in entries if not item["both_outcomes"]]
    return {
        "schema": "bactalk-decision-coverage/v1",
        "decision_count": len(entries),
        "outcomes_observed": observed_outcomes,
        "outcomes_possible": possible,
        "percent": 100.0 if possible == 0 else round(100 * observed_outcomes / possible, 1),
        "fully_covered": not gaps,
        "gaps": gaps,
        "decisions": entries,
        "interpretation": (
            "Both true and false outcomes were exercised for every typed decision "
            "in the exported program."
            if not gaps
            else "Passing assertions leave one or more typed decision outcomes "
            "in the exported program unexercised."
        ),
    }


def run_shadow_suite(
    source: Path | bytes | Program,
    cases: Sequence[AcceptanceCase],
    *,
    options: ShadowRunOptions = DEFAULT_OPTIONS,
) -> TestReport:
    """Run every case against the ``.bog`` and grade it like the IR suite does."""

    if not cases:
        raise ShadowDriverError("the Shadow Runtime needs at least one acceptance case")
    total = _scan_total(cases)
    results: list[ScenarioResult] = []
    offset = 0
    started = time.perf_counter()
    last_runtime: ShadowRuntime | None = None
    backend_name = ""
    for case in cases:
        runtime = ShadowRuntime(
            source, policy=_policy_for(options.policy, case), kernel_backend=options.kernel_backend
        )
        backend_name = runtime.kernels.name
        try:
            result, _ = _run_case(runtime, case, options, offset, total)
        finally:
            runtime.close()
        results.append(result)
        offset += _scan_total([case])
        last_runtime = runtime
    assert last_runtime is not None
    coverage: dict[str, Any] = {
        "decisions": _decision_coverage(last_runtime, results),
        "fault_injection": _fault_coverage(list(cases), results),
    }
    from bactalk.qualification import assess_qualification_matrix

    coverage["qualification_matrix"] = assess_qualification_matrix(
        sequence_family=options.sequence_family,
        cases=list(cases),
        results=results,
        profile=options.qualification_profile,
    )
    coverage["shadow"] = {
        "schema": "bactalk.shadow-run/v1",
        "policy": options.policy.name,
        "kernel_backend": backend_name,
        "component_count": len(last_runtime.blocks),
        "link_count": len(last_runtime.wires),
        "scan_count": total,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    return TestReport(
        passed=all(result.passed for result in results),
        scenarios=results,
        engine=f"{ENGINE_PREFIX}, policy {options.policy.name}, kernels {backend_name})",
        coverage=coverage,
    )


# --- robustness across policies -------------------------------------------------------


@dataclass(frozen=True)
class PolicyDisagreement:
    scenario: str
    key: str
    policies: tuple[str, ...]
    values: tuple[float | bool, ...]


@dataclass
class RobustnessReport:
    reports: dict[str, TestReport]
    verdict_dependent: list[str]
    """Scenarios whose pass/fail depends on the policy."""

    output_disagreements: list[PolicyDisagreement]
    """Final output values (writable points) that differ across policies beyond tolerance."""

    @property
    def robust(self) -> bool:
        return not self.verdict_dependent and not self.output_disagreements

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bactalk.shadow-robustness/v1",
            "policies": list(self.reports),
            "robust": self.robust,
            "verdicts": {
                name: {s.name: s.passed for s in report.scenarios}
                for name, report in self.reports.items()
            },
            "verdict_dependent": self.verdict_dependent,
            "output_disagreements": [
                {
                    "scenario": d.scenario,
                    "key": d.key,
                    "policies": list(d.policies),
                    "values": list(d.values),
                }
                for d in self.output_disagreements
            ],
        }


def run_under_policies(
    source: Path | bytes | Program,
    cases: Sequence[AcceptanceCase],
    *,
    policies: Sequence[ExecutionPolicy] = PLAUSIBLE_POLICIES,
    options: ShadowRunOptions = DEFAULT_OPTIONS,
    tolerance: float = 1e-6,
) -> RobustnessReport:
    """Run the suite under each policy; report verdicts and outputs that depend on it."""

    reports: dict[str, TestReport] = {}
    for policy in policies:
        run_options = ShadowRunOptions(
            policy=policy,
            kernel_backend=options.kernel_backend,
            inject_fault_status=options.inject_fault_status,
            sequence_family=options.sequence_family,
            qualification_profile=options.qualification_profile,
            record_internals=False,
        )
        reports[policy.name] = run_shadow_suite(source, cases, options=run_options)
    names = list(reports)
    verdict_dependent: list[str] = []
    disagreements: list[PolicyDisagreement] = []
    for index, case in enumerate(cases):
        verdicts = {reports[name].scenarios[index].passed for name in names}
        if len(verdicts) > 1:
            verdict_dependent.append(case.name)
        finals = [reports[name].scenarios[index].samples[-1] for name in names]
        keys = [
            key
            for key in finals[0]
            if "." not in key and key not in {"step", "time_seconds", "phase", "phase_step"}
        ]
        for key in keys:
            values = [final.get(key) for final in finals]
            if any(value is None for value in values):
                continue
            first = values[0]
            if all(_same(first, value, tolerance) for value in values[1:]):
                continue
            disagreements.append(PolicyDisagreement(case.name, key, tuple(names), tuple(values)))  # type: ignore[arg-type]
    return RobustnessReport(reports, verdict_dependent, disagreements)


def _same(a: float | bool, b: float | bool, tolerance: float) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    if math.isnan(float(a)) and math.isnan(float(b)):
        return True
    return math.isclose(float(a), float(b), rel_tol=tolerance, abs_tol=tolerance)


__all__ = [
    "ENGINE_PREFIX",
    "PolicyDisagreement",
    "RobustnessReport",
    "ShadowDriverError",
    "ShadowRunOptions",
    "ShadowTrace",
    "run_shadow_case",
    "run_shadow_suite",
    "run_under_policies",
]
