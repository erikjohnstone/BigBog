"""Invariant evaluation and randomised input sequences.

Pure functions over requirement-set data and sampled values; nothing here knows
what a control graph is.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterator, Mapping
from typing import Any

from bactalk.protocol.requirements import Condition, Outcome, RequirementSet

Value = float | bool


def condition_holds(condition: Condition, value: Value) -> bool:
    if isinstance(condition.value, bool):
        return (bool(value) == condition.value) == (condition.operator == "eq")
    number = float(value)
    threshold = float(condition.value)
    if condition.operator == "eq":
        return math.isclose(number, threshold, rel_tol=0.0, abs_tol=1e-9)
    if condition.operator == "ne":
        return not math.isclose(number, threshold, rel_tol=0.0, abs_tol=1e-9)
    if condition.operator == "gt":
        return number > threshold
    if condition.operator == "gte":
        return number >= threshold
    if condition.operator == "lt":
        return number < threshold
    if condition.operator == "lte":
        return number <= threshold
    return threshold <= number <= float(condition.upper or threshold)


def outcome_holds(outcome: Outcome, value: Value) -> bool:
    if isinstance(outcome.value, bool):
        return (bool(value) == outcome.value) == (outcome.operator == "eq")
    number = float(value)
    if not math.isfinite(number):
        return False
    expected = float(outcome.value)
    tolerance = outcome.tolerance
    if outcome.operator == "eq":
        return abs(number - expected) <= tolerance
    if outcome.operator == "ne":
        return abs(number - expected) > tolerance
    if outcome.operator == "gt":
        return number > expected - tolerance
    if outcome.operator == "gte":
        return number >= expected - tolerance
    if outcome.operator == "lt":
        return number < expected + tolerance
    if outcome.operator == "lte":
        return number <= expected + tolerance
    return expected - tolerance <= number <= float(outcome.upper or expected) + tolerance


def invariant_violations(
    requirements: RequirementSet, sample: Mapping[str, Value]
) -> list[dict[str, Any]]:
    """Every (invariant, outcome) that fails on one sample of inputs and outputs.

    A ``when`` or ``then`` point missing from the sample is itself a violation: an
    invariant that cannot be checked is not an invariant that held.
    """

    violations: list[dict[str, Any]] = []
    for invariant in requirements.invariants:
        applicable = True
        for condition in invariant.when:
            if condition.point not in sample:
                violations.append(
                    {"invariant": invariant.id, "point": condition.point, "reason": "unsampled"}
                )
                applicable = False
                break
            if not condition_holds(condition, sample[condition.point]):
                applicable = False
                break
        if not applicable:
            continue
        for outcome in invariant.then:
            if outcome.point not in sample:
                violations.append(
                    {"invariant": invariant.id, "point": outcome.point, "reason": "unsampled"}
                )
            elif not outcome_holds(outcome, sample[outcome.point]):
                violations.append(
                    {
                        "invariant": invariant.id,
                        "point": outcome.point,
                        "observed": sample[outcome.point],
                        "expected": outcome.model_dump(mode="json"),
                    }
                )
    return violations


def _thresholds(requirements: RequirementSet) -> dict[str, list[float]]:
    """Every numeric threshold the requirements mention, per input, so random
    sequences land on the edges the logic switches at."""

    edges: dict[str, list[float]] = {}
    conditions: list[Condition] = []
    for requirement in requirements.requirements:
        conditions.extend(requirement.conditions)
    for invariant in requirements.invariants:
        conditions.extend(invariant.when)
    for condition in conditions:
        if isinstance(condition.value, bool):
            continue
        values = edges.setdefault(condition.point, [])
        values.append(float(condition.value))
        if condition.upper is not None:
            values.append(float(condition.upper))
        if condition.deadband:
            values.append(float(condition.value) - condition.deadband)
            values.append(float(condition.value) + condition.deadband)
    return edges


def random_input_sequences(
    requirements: RequirementSet,
    *,
    count: int,
    steps: int,
    seed: int = 0,
    hold_probability: float = 0.8,
) -> Iterator[list[dict[str, Value]]]:
    """``count`` sequences of ``steps`` input dictionaries.

    Inputs mostly hold their value between steps (so delays and persistence windows
    can elapse), jump uniformly inside the declared range otherwise, and sometimes
    land a hair either side of a threshold the requirements name.
    """

    generator = random.Random(seed)
    edges = _thresholds(requirements)
    inputs = requirements.inputs
    for _ in range(count):
        current: dict[str, Value] = {}
        for point in inputs:
            current[point.name] = point.nominal
        sequence: list[dict[str, Value]] = []
        for _ in range(steps):
            for point in inputs:
                if generator.random() < hold_probability and sequence:
                    continue
                if point.data_type == "boolean":
                    current[point.name] = generator.random() < 0.5
                    continue
                low = float(point.minimum if point.minimum is not None else point.nominal)
                high = float(point.maximum if point.maximum is not None else point.nominal)
                candidates = edges.get(point.name)
                if candidates and generator.random() < 0.3:
                    edge = generator.choice(candidates)
                    value = edge + generator.choice((-1.0, 0.0, 1.0)) * point.margin
                    current[point.name] = min(high, max(low, value))
                else:
                    current[point.name] = generator.uniform(low, high)
            sequence.append(dict(current))
        yield sequence


__all__ = [
    "condition_holds",
    "invariant_violations",
    "outcome_holds",
    "random_input_sequences",
]
