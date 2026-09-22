"""Three-way differential testing with pyfunnel bands (GOAL-NATIVE-BOG.md N7, D3).

For every acceptance scenario of a job, three trajectories per output point are
compared pairwise inside documented tolerance funnels (``bands.json``):

- ``shadow``: the exported ``.bog`` executed by the Shadow Runtime;
- ``interpreter``: BACTalk's IR interpreter (the same graph the emitter lowered);
- ``reference``: the item's source of truth, when one is retained (for Tier 1 the
  LBNL controller executed by the Open Control Engine).

A disagreement fails the run and names the first diverging block and slot,
found by walking the Shadow Runtime and the interpreter scan by scan.
"""

from __future__ import annotations

import json
import math
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from bactalk.domain import AcceptanceCase, JobSpec, TestReport
from bactalk.integrations.funnel import FunnelScorer
from bactalk.niagara.emit import emit_bog
from bactalk.niagara.shadow.differential import compare_case
from bactalk.niagara.shadow.driver import ShadowRunOptions, run_shadow_suite
from bactalk.niagara.shadow.policy import DEFAULT_POLICY, ExecutionPolicy
from bactalk.optional_dependencies import PYFUNNEL
from bactalk.simulator import run_acceptance_suite

LEGS: tuple[tuple[str, str, str], ...] = (
    ("shadow_vs_interpreter", "shadow", "interpreter"),
    ("interpreter_vs_reference", "interpreter", "reference"),
    ("shadow_vs_reference", "shadow", "reference"),
)


def load_bands() -> dict[str, Any]:
    text = resources.files("bactalk.niagara").joinpath("bands.json").read_text(encoding="utf-8")
    return json.loads(text)


@dataclass(frozen=True)
class Band:
    kind: str
    atolx: float
    atoly: float
    rationale: str
    source: str
    """``default`` or the override's id."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "atolx": self.atolx,
            "atoly": self.atoly,
            "rationale": self.rationale,
            "source": self.source,
        }


def band_for(
    bands: Mapping[str, Any],
    *,
    controller_id: str | None,
    signal: str,
    kind: str,
    scan_seconds: float,
    reference_range: float,
    band_set: str = "default",
) -> Band:
    """Resolve the funnel for one signal: an override when one names it, else the default."""

    for override in bands.get("overrides", []):
        if override.get("signal") != signal:
            continue
        if override.get("controller") not in (None, controller_id):
            continue
        return Band(
            kind,
            float(override.get("atolx_scans", 1)) * scan_seconds,
            float(override["atoly"]),
            str(override.get("rationale", "")),
            str(override.get("id", signal)),
        )
    default = bands[band_set][kind]
    atolx = float(default.get("atolx_scans", 1)) * scan_seconds
    if kind == "numeric":
        atoly = max(
            float(default["atoly_minimum"]),
            float(default["atoly_relative"]) * abs(reference_range),
        )
    else:
        atoly = float(default.get("atoly", 0.0))
    return Band(kind, atolx, atoly, str(default.get("rationale", "")), band_set)


# --- trajectories --------------------------------------------------------------------


@dataclass
class Trajectory:
    times: list[float]
    values: list[float]

    @property
    def value_range(self) -> float:
        finite = [value for value in self.values if math.isfinite(value)]
        return (max(finite) - min(finite)) if finite else 0.0


def _kind_of(values: Sequence[Any]) -> str:
    if all(isinstance(value, bool) for value in values):
        return "boolean"
    if all(
        isinstance(value, bool) or float(value).is_integer()
        for value in values
        if value is not None
    ):
        return "integer"
    return "numeric"


def _as_floats(values: Sequence[Any]) -> list[float]:
    return [1.0 if value is True else 0.0 if value is False else float(value) for value in values]


def trajectories_from_report(
    report: TestReport, case: AcceptanceCase, signals: Sequence[str]
) -> dict[str, Trajectory]:
    scenario = next(item for item in report.scenarios if item.name == case.name)
    step = case.timeline[0].step_seconds if case.timeline else case.step_seconds
    times: list[float] = []
    clock = 0.0
    if case.timeline:
        for phase in case.timeline:
            for _ in range(phase.repeat):
                clock += phase.step_seconds
                times.append(clock)
    else:
        times = [step * (index + 1) for index in range(case.repeat)]
    result: dict[str, Trajectory] = {}
    for signal in signals:
        values = [sample.get(signal) for sample in scenario.samples]
        if any(value is None for value in values):
            continue
        result[signal] = Trajectory(list(times), _as_floats(values))  # type: ignore[arg-type]
    return result


def trajectories_from_reference(
    reference: Mapping[str, Any], case: AcceptanceCase, signals: Sequence[str]
) -> dict[str, Trajectory] | None:
    entry = next(
        (item for item in reference.get("cases", []) if item.get("name") == case.name), None
    )
    if entry is None:
        return None
    times = [float(value) for value in entry["times"]]
    result: dict[str, Trajectory] = {}
    for signal in signals:
        values = entry["outputs"].get(signal)
        if values is None:
            continue
        # The reference samples t=0 as well; the reports start at the first scan.
        result[signal] = Trajectory(times[1:], _as_floats(values[1:]))
    return result


# --- funnel comparison -------------------------------------------------------------


@dataclass(frozen=True)
class LegResult:
    leg: str
    passed: bool
    max_error: float | None
    first_violation_time: float | None
    engine: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "leg": self.leg,
            "passed": self.passed,
            "max_error": self.max_error,
            "first_violation_time": self.first_violation_time,
            "engine": self.engine,
        }


def _pure_funnel(reference: Trajectory, test: Trajectory, band: Band) -> LegResult:
    """A funnel check without pyfunnel: each test point must sit within atoly of some
    reference point at most atolx away in time (the funnel's rectangle)."""

    violations: list[tuple[float, float]] = []
    max_error = 0.0
    for time_seconds, value in zip(test.times, test.values, strict=True):
        candidates = [
            ref_value
            for ref_time, ref_value in zip(reference.times, reference.values, strict=True)
            if abs(ref_time - time_seconds) <= band.atolx + 1e-9
        ]
        if not candidates:
            continue
        if any(math.isnan(candidate) and math.isnan(value) for candidate in candidates):
            continue
        error = min(abs(value - candidate) for candidate in candidates)
        excess = max(0.0, error - band.atoly)
        max_error = max(max_error, error)
        if excess > 1e-12:
            violations.append((time_seconds, excess))
    return LegResult(
        "",
        not violations,
        max_error,
        violations[0][0] if violations else None,
        "tolerance-rectangle (pyfunnel not installed)",
    )


def compare_trajectories(
    reference: Trajectory, test: Trajectory, band: Band, *, scorer: FunnelScorer | None = None
) -> LegResult:
    # A trajectory allowed to lead the reference by atolx cannot be judged over its
    # last atolx seconds (the reference has no later point to match), so those test
    # points are left out; the reference keeps its full extent.
    if band.atolx > 0.0 and reference.times:
        horizon = reference.times[-1] - band.atolx + 1e-9
        kept = [(t, v) for t, v in zip(test.times, test.values, strict=True) if t <= horizon]
        if kept and kept[-1][0] < reference.times[-1]:
            # pyfunnel needs equal time extents: pad the unjudged tail with the
            # reference's own end value, which is inside the funnel by construction.
            kept.append((reference.times[-1], reference.values[-1]))
        if kept:
            test = Trajectory([t for t, _ in kept], [v for _, v in kept])
    if not PYFUNNEL.available():
        return _pure_funnel(reference, test, band)
    ref_times, ref_values = _finite_pairs(reference)
    test_times, test_values = _finite_pairs(test)
    if len(ref_times) < 2 or len(test_times) < 2:
        return _pure_funnel(reference, test, band)
    scorer = scorer or FunnelScorer()
    with tempfile.TemporaryDirectory() as tmp:
        result = scorer.compare(
            ref_times,
            ref_values,
            test_times,
            test_values,
            Path(tmp),
            absolute_time_tolerance=band.atolx,
            absolute_value_tolerance=band.atoly,
        )
        if not result.completed:
            fallback = _pure_funnel(reference, test, band)
            return LegResult(
                "",
                fallback.passed,
                fallback.max_error,
                fallback.first_violation_time,
                "tolerance-rectangle (pyfunnel did not complete)",
            )
        errors = result.error_points
        violations = [(time, error) for time, error in errors if error != 0.0]
        return LegResult(
            "",
            not violations,
            max((abs(error) for _, error in errors), default=0.0),
            violations[0][0] if violations else None,
            "pyfunnel",
        )


def _finite_pairs(trajectory: Trajectory) -> tuple[list[float], list[float]]:
    pairs = [
        (t, v) for t, v in zip(trajectory.times, trajectory.values, strict=True) if math.isfinite(v)
    ]
    return [t for t, _ in pairs], [v for _, v in pairs]


# --- the three-way report -------------------------------------------------------------


@dataclass
class SignalComparison:
    signal: str
    band: Band
    legs: dict[str, LegResult] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.legs.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "band": self.band.to_dict(),
            "passed": self.passed,
            "legs": {name: result.to_dict() for name, result in self.legs.items()},
        }


@dataclass
class CaseComparison:
    name: str
    signals: list[SignalComparison]
    first_divergence: dict[str, Any] | None = None
    legs_available: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return all(item.passed for item in self.signals)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "legs_available": list(self.legs_available),
            "signals": [item.to_dict() for item in self.signals],
            "first_divergence": self.first_divergence,
        }


@dataclass
class DifferentialReport:
    controller_id: str | None
    cases: list[CaseComparison]
    reference_available: bool
    shadow_engine: str
    interpreter_engine: str
    reference_engine: str | None

    @property
    def passed(self) -> bool:
        return all(case.passed for case in self.cases)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "bactalk.three-way-differential/v1",
            "controller_id": self.controller_id,
            "passed": self.passed,
            "reference_available": self.reference_available,
            "engines": {
                "shadow": self.shadow_engine,
                "interpreter": self.interpreter_engine,
                "reference": self.reference_engine,
            },
            "cases": [case.to_dict() for case in self.cases],
            "failing_cases": [case.name for case in self.cases if not case.passed],
        }

    def summary(self) -> str:
        lines = [
            f"three-way differential: {'PASS' if self.passed else 'FAIL'} ({len(self.cases)} cases)"
        ]
        for case in self.cases:
            if case.passed:
                continue
            failing = [item for item in case.signals if not item.passed]
            lines.append(
                f"  {case.name}: "
                + ", ".join(
                    f"{item.signal}[{','.join(k for k, v in item.legs.items() if not v.passed)}]"
                    for item in failing
                )
            )
            if case.first_divergence:
                lines.append(f"    first divergence: {case.first_divergence}")
        return "\n".join(lines)


def output_signals(job: JobSpec) -> list[str]:
    return [
        point.name
        for point in job.points
        if point.role.value in {"command", "alarm", "status_output", "output"}
    ] or [
        block.id
        for block in (job.control_graph.blocks if job.control_graph else [])
        if block.kind.value.endswith("_output")
    ]


def three_way_differential(
    job: JobSpec,
    *,
    bog: bytes | None = None,
    reference: Mapping[str, Any] | None = None,
    policy: ExecutionPolicy = DEFAULT_POLICY,
    kernel_backend: str = "python",
    bands: Mapping[str, Any] | None = None,
    shadow_report: TestReport | None = None,
    interpreter_report: TestReport | None = None,
    band_set: str = "default",
) -> DifferentialReport:
    """Run all three engines on the job's acceptance suite and compare every output."""

    if job.control_graph is None:
        raise ValueError("the job carries no control graph")
    graph = job.control_graph
    content = bog if bog is not None else emit_bog(graph, points=job.points).content
    bands = bands or load_bands()
    interpreter_report = interpreter_report or run_acceptance_suite(graph, job)
    shadow_report = shadow_report or run_shadow_suite(
        content,
        job.acceptance_tests,
        options=ShadowRunOptions(
            policy=policy, kernel_backend=kernel_backend, sequence_family=job.sequence.family
        ),
    )
    signals = [block.id for block in graph.blocks if block.kind.value.endswith("_output")]
    controller_id = job.sequence.controller_id
    # The value band is relative to the signal's range over the whole suite, so a
    # signal that barely moves in one scenario is not held to a vanishing tolerance.
    suite_ranges: dict[str, float] = {}
    for case in job.acceptance_tests:
        for signal, trajectory in trajectories_from_report(
            interpreter_report, case, signals
        ).items():
            finite = [v for v in trajectory.values if math.isfinite(v)]
            if not finite:
                continue
            low, high = min(finite), max(finite)
            previous = suite_ranges.get(signal)
            suite_ranges[signal] = (
                max(high, previous[1]) - min(low, previous[0])
                if isinstance(previous, tuple)
                else high - low
            )
            suite_ranges[f"{signal}:bounds"] = (  # type: ignore[assignment]
                min(low, previous[0]) if isinstance(previous, tuple) else low,
                max(high, previous[1]) if isinstance(previous, tuple) else high,
            )
            suite_ranges[signal] = suite_ranges[f"{signal}:bounds"]  # type: ignore[assignment]
    units = {point.name: point.units for point in job.points}
    ranges: dict[str, float] = {}
    for signal, bounds in suite_ranges.items():
        if signal.endswith(":bounds"):
            continue
        low, high = bounds  # type: ignore[misc]
        span = high - low
        # A dimensionless signal (a fraction or a count) is banded on its scale,
        # max(range, |max|); a signal with physical units on its range alone, so a
        # temperature's absolute offset never widens its band.
        ranges[signal] = span if units.get(signal) else max(span, abs(high), abs(low))
    cases: list[CaseComparison] = []
    for case in job.acceptance_tests:
        scan = case.timeline[0].step_seconds if case.timeline else case.step_seconds
        legs: dict[str, dict[str, Trajectory]] = {
            "shadow": trajectories_from_report(shadow_report, case, signals),
            "interpreter": trajectories_from_report(interpreter_report, case, signals),
        }
        reference_legs = (
            trajectories_from_reference(reference, case, signals) if reference else None
        )
        if reference_legs:
            legs["reference"] = reference_legs
        comparisons: list[SignalComparison] = []
        for signal in signals:
            interpreter_leg = legs["interpreter"].get(signal)
            if interpreter_leg is None:
                continue
            kind = _kind_of(
                [
                    sample[signal]
                    for sample in next(
                        s for s in interpreter_report.scenarios if s.name == case.name
                    ).samples
                ]
            )
            band = band_for(
                bands,
                controller_id=controller_id,
                signal=signal,
                kind=kind,
                scan_seconds=scan,
                reference_range=ranges.get(signal, interpreter_leg.value_range),
                band_set=band_set,
            )
            comparison = SignalComparison(signal, band)
            for leg_name, test_name, ref_name in LEGS:
                test = legs.get(test_name, {}).get(signal)
                ref = legs.get(ref_name, {}).get(signal)
                if test is None or ref is None:
                    continue
                result = compare_trajectories(ref, test, band)
                comparison.legs[leg_name] = LegResult(
                    leg_name,
                    result.passed,
                    result.max_error,
                    result.first_violation_time,
                    result.engine,
                )
            comparisons.append(comparison)
        case_result = CaseComparison(case.name, comparisons, legs_available=tuple(legs))
        if not case_result.passed:
            case_result.first_divergence = _first_divergence(
                job, case, content, policy, kernel_backend, comparisons
            )
        cases.append(case_result)
    return DifferentialReport(
        controller_id=controller_id,
        cases=cases,
        reference_available=reference is not None,
        shadow_engine=shadow_report.engine,
        interpreter_engine=interpreter_report.engine,
        reference_engine=str(reference.get("runtime")) if reference else None,
    )


def _first_divergence(
    job: JobSpec,
    case: AcceptanceCase,
    content: bytes,
    policy: ExecutionPolicy,
    kernel_backend: str,
    comparisons: Sequence[SignalComparison],
) -> dict[str, Any] | None:
    """Name the earliest block whose value leaves its band, scan by scan against the interpreter."""

    failing = [item for item in comparisons if not item.passed]
    first_time = min(
        (
            leg.first_violation_time
            for item in failing
            for leg in item.legs.values()
            if leg.first_violation_time is not None
        ),
        default=None,
    )
    tolerance = min((item.band.atoly for item in failing), default=1e-6)
    divergences = compare_case(
        job,
        case,
        policy=policy,
        kernel_backend=kernel_backend,
        tolerance=max(tolerance, 1e-9),
        content=content,
    )
    if not divergences:
        return {
            "signals": [item.signal for item in failing],
            "first_violation_time": first_time,
            "time_seconds": first_time,
            "band": failing[0].band.atoly if failing else None,
            "block": None,
            "note": (
                "the interpreter and the Shadow Runtime agree; "
                "the divergence is against the reference"
            ),
        }
    step = case.timeline[0].step_seconds if case.timeline else case.step_seconds
    scan = int(round(first_time / step)) if first_time is not None else divergences[0].scan
    at_scan = (
        [item for item in divergences if item.scan == scan]
        or [item for item in divergences if item.scan >= scan]
        or divergences
    )
    first = at_scan[0]
    band = next((item.band.atoly for item in failing if item.signal == first.block_id), None)
    return {
        "signals": [item.signal for item in failing],
        "first_violation_time": first_time,
        "time_seconds": first_time,  # the web app's name for the same instant
        "band": band if band is not None else (failing[0].band.atoly if failing else None),
        "scan": first.scan,
        "block": first.block_id,
        "kind": first.kind,
        "slot": first.slot,
        "interpreter": first.interpreter,
        "shadow": first.shadow,
        "shadow_key": first.shadow_key,
    }


__all__ = [
    "LEGS",
    "Band",
    "CaseComparison",
    "DifferentialReport",
    "LegResult",
    "SignalComparison",
    "Trajectory",
    "band_for",
    "compare_trajectories",
    "load_bands",
    "three_way_differential",
    "trajectories_from_reference",
    "trajectories_from_report",
]
