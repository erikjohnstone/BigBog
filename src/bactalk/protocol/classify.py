"""Failure classification: logic bug, test bug or ambiguous requirement.

The protocol's third step. It is rule-based and deterministic: the scenario kind
and the plan's own gaps decide the class. Only an ambiguous requirement becomes a
question for a human; a logic bug goes back to the logic author and a test bug to
the test author, neither of whom may touch the other's work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from bactalk.protocol.requirements import RequirementSet
from bactalk.protocol.test_author import PlannedScenario, TestPlan

Category = Literal["logic_bug", "test_bug", "ambiguous_requirement"]

_BOUNDARY_KINDS = {"boundary_true", "boundary_false"}
_TIMING_KINDS = {"timing_before", "timing_after", "release_before", "release_after"}
_DEADBAND_KINDS = {"deadband_hold", "deadband_release"}


@dataclass(frozen=True)
class Classification:
    scenario: str
    requirement_id: str
    kind: str
    assertion: str
    observed: str
    expected: str
    category: Category
    reason: str
    question: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "requirement_id": self.requirement_id,
            "kind": self.kind,
            "assertion": self.assertion,
            "observed": self.observed,
            "expected": self.expected,
            "category": self.category,
            "reason": self.reason,
            "question": self.question,
        }


def _conflicting_expectations(scenario: PlannedScenario) -> str | None:
    for phase in scenario.case.timeline:
        seen: dict[str, Any] = {}
        for expectation in phase.expectations:
            if expectation.operator.value != "eq":
                continue
            previous = seen.setdefault(expectation.target, expectation.value)
            if previous != expectation.value:
                return (
                    f"phase '{phase.name}' expects {expectation.target} to equal both "
                    f"{previous} and {expectation.value}"
                )
    return None


def classify_failure(
    requirements: RequirementSet,
    plan: TestPlan,
    scenario_name: str,
    assertion: str,
    observed: str,
    expected: str,
) -> Classification:
    scenario = plan.scenario(scenario_name)
    requirement = requirements.requirement(scenario.requirement_id)
    base = {
        "scenario": scenario.id,
        "requirement_id": requirement.id,
        "kind": scenario.kind,
        "assertion": assertion,
        "observed": observed,
        "expected": expected,
    }
    conflict = _conflicting_expectations(scenario)
    if conflict is not None:
        return Classification(
            **base,
            category="test_bug",
            reason="the generated scenario contradicts itself: " + conflict,
        )
    gap_kinds = {gap["kind"] for gap in plan.gaps if gap["requirement_id"] == requirement.id}
    if "unreachable_condition" in gap_kinds:
        return Classification(
            **base,
            category="test_bug",
            reason="a condition of this requirement cannot be driven to both sides inside "
            "the declared input range, so the scenario does not test what it says",
        )
    if scenario.kind in _BOUNDARY_KINDS:
        return Classification(
            **base,
            category="ambiguous_requirement",
            reason="the logic and the requirement disagree exactly at a threshold",
            question=(
                f"{requirement.id} ({requirement.title}): with {scenario.subject}, the logic "
                f"gives {observed} where the requirement expects {expected}. Is the "
                "comparison at the threshold inclusive or exclusive?"
            ),
        )
    if scenario.kind in _TIMING_KINDS:
        return Classification(
            **base,
            category="ambiguous_requirement",
            reason="the logic and the requirement disagree by one scan at a timing edge",
            question=(
                f"{requirement.id} ({requirement.title}): one scan either side of the "
                f"{requirement.timing.delay_seconds:g} s delay / "
                f"{requirement.timing.release_seconds:g} s release the logic gives "
                f"{observed} where the requirement expects {expected}. Does the window "
                "count from the scan in which the condition first holds, or from the next?"
            ),
        )
    if scenario.kind in _DEADBAND_KINDS:
        return Classification(
            **base,
            category="ambiguous_requirement",
            reason="the logic and the requirement disagree at a deadband edge",
            question=(
                f"{requirement.id} ({requirement.title}): at the far edge of the "
                f"{scenario.subject} deadband the logic gives {observed} where the "
                f"requirement expects {expected}. Which side of the deadband releases?"
            ),
        )
    return Classification(
        **base,
        category="logic_bug",
        reason="the requirement states this case without ambiguity and the logic does not meet it",
    )


__all__ = ["Category", "Classification", "classify_failure"]
