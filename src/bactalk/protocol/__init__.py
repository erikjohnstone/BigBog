"""Test Generation Protocol (GOAL-NATIVE-BOG.md, N9–N11).

Tiers 3 and up have no LBNL reference model. A numbered, plain-language requirement
set (``requirements``) is the source of truth; a human approves its digest (Gate
G-ENG, ``approvals``); the test author (``test_author``) builds acceptance
scenarios and invariants from that set alone; ``adequacy`` runs them against the
logic and proves the suite (mutation, decision coverage, randomised invariants);
``classify`` turns a failure into a logic bug, a test bug or a question for a human;
``plan`` renders the readable test plan that joins the approval digest.
"""

from bactalk.protocol.requirements import (
    REQUIREMENTS_SCHEMA,
    Citation,
    Condition,
    FailureBehaviour,
    Invariant,
    Outcome,
    PointDeclaration,
    Requirement,
    RequirementApproval,
    RequirementSet,
    SetupPhase,
    Timing,
    approval_status,
    load_requirement_set,
    protocol_reference,
)
from bactalk.protocol.test_author import PlannedScenario, TestPlan, generate_test_plan

__all__ = [
    "REQUIREMENTS_SCHEMA",
    "Citation",
    "Condition",
    "FailureBehaviour",
    "Invariant",
    "Outcome",
    "PlannedScenario",
    "PointDeclaration",
    "Requirement",
    "RequirementApproval",
    "RequirementSet",
    "SetupPhase",
    "TestPlan",
    "Timing",
    "approval_status",
    "generate_test_plan",
    "load_requirement_set",
    "protocol_reference",
]
