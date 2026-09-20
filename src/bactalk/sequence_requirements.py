from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bactalk.intake import SequenceDocument


class SequenceCandidateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(pattern=r"^seqreq-[0-9a-f]{16}$")
    disposition: Literal["approve", "reject", "resolve"]
    selected_point: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
    )
    replacement_text: str | None = Field(default=None, min_length=1, max_length=2_000)
    note: str | None = Field(default=None, min_length=2, max_length=2_000)

    @model_validator(mode="after")
    def disposition_fields_are_coherent(self) -> SequenceCandidateDecision:
        if self.disposition == "resolve" and self.replacement_text is None:
            raise ValueError("resolve decisions require replacement_text")
        if self.disposition == "reject" and self.note is None:
            raise ValueError("reject decisions require an engineering note")
        if self.disposition != "resolve" and self.replacement_text is not None:
            raise ValueError("replacement_text is only valid for resolve decisions")
        return self


class SequenceRequirementReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer: str | None = Field(default=None, min_length=2, max_length=120)
    decisions: list[SequenceCandidateDecision] = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def candidate_decisions_are_unique(self) -> SequenceRequirementReviewRequest:
        candidate_ids = [decision.candidate_id for decision in self.decisions]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("sequence requirement decisions contain duplicate candidate IDs")
        return self

_QUANTITY = re.compile(
    r"(?<![\w.])(?P<value>[+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*"
    r"(?P<unit>"
    r"milliseconds?|msec|ms|seconds?|secs?|sec|s|minutes?|mins?|min|hours?|hrs?|hr|h|"
    r"degrees?\s*(?:fahrenheit|celsius|f|c)|deg\s*[fc]|°\s*[fc]|"
    r"percent|%|ppm|cfm|l/s|m3/s|m\^3/s|"
    r"in(?:ches?)?\.?\s*(?:w\.?\s*c\.?|h2o)|pa|kpa|psi|"
    r"btu/lb|kj/kg|hz|rpm"
    r")\b|(?<![\w.])(?P<percent_value>[+-]?\d+(?:\.\d+)?)\s*(?P<percent_unit>%)",
    flags=re.IGNORECASE,
)

_SUBJECTS = (
    "supply fan",
    "return fan",
    "relief fan",
    "exhaust fan",
    "outdoor-air damper",
    "outdoor air damper",
    "outside-air damper",
    "outside air damper",
    "return-air damper",
    "return air damper",
    "relief damper",
    "heating coil valve",
    "cooling coil valve",
    "heating valve",
    "cooling valve",
    "reheat valve",
    "damper",
    "valve",
    "pump",
    "alarm",
    "ahu",
    "air handler",
    "system",
    "controller",
)
_SUBJECT_PATTERN = "|".join(re.escape(subject) for subject in _SUBJECTS)
_ACTION_FORWARD = re.compile(
    rf"\b(?P<verb>stop|start|restart|open|close|enable|disable|limit|modulate|command|latch|reset|"
    rf"de-energize|energize)\w*\s+(?:the\s+)?(?P<subject>{_SUBJECT_PATTERN})\b",
    flags=re.IGNORECASE,
)
_ACTION_REVERSE = re.compile(
    rf"\b(?P<subject>{_SUBJECT_PATTERN})\b\s+(?:shall\s+|must\s+|is\s+|are\s+)?"
    rf"(?:be\s+)?(?:command(?:ed)?\s+)?(?:to\s+)?"
    rf"(?P<verb>stop|start|restart|open|close|enable|disable|limit|modulate|latch|reset|"
    rf"de-energize|energize)\w*\b",
    flags=re.IGNORECASE,
)
_ALARM_ACTION = re.compile(
    r"\b(?P<verb>raise|issue|generate|annunciate)\w*\s+(?:an?\s+)?(?P<subject>alarm)\b",
    flags=re.IGNORECASE,
)

_MEASUREMENT_POINTS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"\bmixed[- ]air temperature\b", re.I), ("MixedAirTemp",)),
    (re.compile(r"\bdischarge[- ]air temperature\b", re.I), ("DischargeAirTemp",)),
    (re.compile(r"\bsupply[- ]air temperature\b", re.I), ("SupplyAirTemp",)),
    (re.compile(r"\bout(?:door|side)[- ]air temperature\b", re.I), ("OutdoorAirTemp",)),
    (re.compile(r"\breturn[- ]air temperature\b", re.I), ("ReturnAirTemp",)),
    (re.compile(r"\bzone temperature\b", re.I), ("ZoneTemp",)),
    (re.compile(r"\bduct (?:static )?pressure\b", re.I), ("DuctStatic",)),
    (re.compile(r"\bbuilding[- ]pressure\b", re.I), ("BuildingPressure",)),
    (re.compile(r"\bzone co2\b", re.I), ("ZoneCO2",)),
    (
        re.compile(r"\b(?:primary )?airflow\b", re.I),
        ("PrimaryAirflow", "SupplyAirflow", "OutdoorAirflow", "ReturnAirflow"),
    ),
)

_ACTION_POINTS: dict[str, tuple[str, ...]] = {
    "supply fan": ("SupplyFanCommand", "SupplyFanSpeedCommand"),
    "return fan": ("ReturnFanCommand", "ReturnFanSpeedCommand"),
    "relief fan": ("ReliefFanCommand", "ReliefFanSpeedCommand"),
    "exhaust fan": ("ExhaustFanCommand", "ExhaustFanSpeedCommand"),
    "outdoor-air damper": ("OutdoorDamperCommand", "OutdoorAirDamperCommand"),
    "outdoor air damper": ("OutdoorDamperCommand", "OutdoorAirDamperCommand"),
    "outside-air damper": ("OutdoorDamperCommand", "OutdoorAirDamperCommand"),
    "outside air damper": ("OutdoorDamperCommand", "OutdoorAirDamperCommand"),
    "return-air damper": ("ReturnAirDamperCommand",),
    "return air damper": ("ReturnAirDamperCommand",),
    "relief damper": ("ReliefDamperCommand",),
    "heating coil valve": ("HeatingValveCommand",),
    "cooling coil valve": ("CoolingValveCommand",),
    "heating valve": ("HeatingValveCommand", "ValveCommand"),
    "cooling valve": ("CoolingValveCommand",),
    "reheat valve": ("ValveCommand",),
    "damper": ("DamperCommand", "OutdoorAirDamperCommand", "ReturnAirDamperCommand"),
    "valve": ("ValveCommand", "HeatingValveCommand", "CoolingValveCommand"),
    "pump": ("PumpCommand",),
}

_UNRESOLVED = (
    ("non-numeric-delay", re.compile(r"\b(?:short|brief|appropriate|adjustable) delay\b", re.I)),
    (
        "external-policy",
        re.compile(r"\b(?:as required|as needed|per manufacturer|per vendor)\b", re.I),
    ),
    ("placeholder", re.compile(r"\b(?:tbd|to be determined|by others)\b", re.I)),
    ("unnumbered-stage", re.compile(r"\b(?:all|every) (?:freeze[- ]protection )?stages?\b", re.I)),
    (
        "unnumbered-limit",
        re.compile(r"\b(?:low|high|minimum|maximum) limit\b(?!\s*(?:of|=)?\s*[+-]?\d)", re.I),
    ),
)


def _clauses(text: str) -> list[tuple[int, int, str]]:
    separators = re.compile(r"[;!?](?:\s+|$)|\.(?=\s+[A-Z])|\Z")
    clauses: list[tuple[int, int, str]] = []
    start = 0
    for match in separators.finditer(text):
        end = match.end()
        clause = text[start:end].strip()
        if clause:
            left_trim = len(text[start:end]) - len(text[start:end].lstrip())
            right_trim = len(text[start:end].rstrip())
            clauses.append((start + left_trim, start + right_trim, clause))
        start = end
    if start < len(text):
        remainder = text[start:].strip()
        if remainder:
            left_trim = len(text[start:]) - len(text[start:].lstrip())
            clauses.append((start + left_trim, len(text.rstrip()), remainder))
    return clauses


def _normal_unit(raw: str) -> tuple[str, str, float]:
    value = re.sub(r"\s+", "", raw.lower().replace("degrees", "deg").replace("degree", "deg"))
    value = value.replace("fahrenheit", "f").replace("celsius", "c")
    value = value.replace(".", "")
    if value in {"millisecond", "milliseconds", "msec", "ms"}:
        return "time", "s", 0.001
    if value in {"second", "seconds", "sec", "secs", "s"}:
        return "time", "s", 1.0
    if value in {"minute", "minutes", "min", "mins"}:
        return "time", "s", 60.0
    if value in {"hour", "hours", "hr", "hrs", "h"}:
        return "time", "s", 3600.0
    if value in {"degf", "°f", "f"}:
        return "temperature", "degF", 1.0
    if value in {"degc", "°c", "c"}:
        return "temperature", "degC", 1.0
    if value in {"percent", "%"}:
        return "percentage", "%", 1.0
    if value in {"inwc", "inh2o", "incheswc", "inchesh2o", "inchwc", "inchh2o"}:
        return "pressure", "inH2O", 1.0
    normalized = {
        "pa": ("pressure", "Pa"),
        "kpa": ("pressure", "kPa"),
        "psi": ("pressure", "psi"),
        "cfm": ("airflow", "cfm"),
        "l/s": ("airflow", "L/s"),
        "m3/s": ("airflow", "m3/s"),
        "m^3/s": ("airflow", "m3/s"),
        "ppm": ("concentration", "ppm"),
        "btu/lb": ("enthalpy", "Btu/lb"),
        "kj/kg": ("enthalpy", "kJ/kg"),
        "hz": ("frequency", "Hz"),
        "rpm": ("rotational_speed", "rpm"),
    }.get(value)
    if normalized is None:  # guarded by the expression allowlist
        return "unknown", raw, 1.0
    return normalized[0], normalized[1], 1.0


def _comparison(prefix: str) -> str | None:
    tests = (
        ("ge", r"(?:at or above|greater than or equal to|not less than)\s*$"),
        ("le", r"(?:at or below|less than or equal to|not greater than)\s*$"),
        ("gt", r"(?:above|greater than|exceeds?|rises? above)\s*$"),
        ("lt", r"(?:below|less than|falls? below|drops? below)\s*$"),
        ("eq", r"(?:equal to|equals?|at)\s*$"),
    )
    for operator, pattern in tests:
        if re.search(pattern, prefix, flags=re.IGNORECASE):
            return operator
    return None


def _timing_relation(prefix: str) -> str:
    tests = (
        ("persistence", r"\bfor\s*$"),
        ("on-delay", r"\bafter\s*$"),
        ("deadline", r"\bwithin\s*$"),
        ("off-delay", r"\bbefore\s*$"),
        ("minimum-dwell", r"\b(?:minimum|min\.)\s*$"),
        ("maximum-dwell", r"\b(?:maximum|max\.)\s*$"),
    )
    for relation, pattern in tests:
        if re.search(pattern, prefix, flags=re.IGNORECASE):
            return relation
    return "duration"


def _stable_id(document_hash: str, kind: str, start: int, end: int, value: str) -> str:
    digest = hashlib.sha256(
        f"{document_hash}:{kind}:{start}:{end}:{value}".encode()
    ).hexdigest()[:16]
    return f"seqreq-{digest}"


def _context_for_clause(
    start: int,
    end: int,
    scenario_results: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    scenarios: set[str] = set()
    facets: set[str] = set()
    for scenario in scenario_results:
        for facet in scenario.get("facets", []):
            if any(
                evidence["start"] < end and evidence["end"] > start
                for evidence in facet.get("evidence", [])
            ):
                scenarios.add(scenario["id"])
                facets.add(f"{scenario['id']}:{facet['id']}")
    return sorted(scenarios), sorted(facets)


def _available_candidates(
    candidates: tuple[str, ...],
    available_points: set[str],
) -> list[str]:
    return [candidate for candidate in candidates if candidate in available_points]


def _measurement_candidates(clause: str, available_points: set[str]) -> list[str]:
    candidates: list[str] = []
    for pattern, point_ids in _MEASUREMENT_POINTS:
        if pattern.search(clause):
            candidates.extend(_available_candidates(point_ids, available_points))
    return sorted(set(candidates))


def _command_candidates(prefix: str, available_points: set[str]) -> list[str]:
    matches = list(_ACTION_FORWARD.finditer(prefix)) + list(_ACTION_REVERSE.finditer(prefix))
    if not matches:
        return []
    nearest = max(matches, key=lambda match: match.end())
    subject = re.sub(r"\s+", " ", nearest.group("subject").lower())
    return _available_candidates(_ACTION_POINTS.get(subject, ()), available_points)


def _binding_status(candidates: list[str]) -> str:
    if len(candidates) == 1:
        return "single-candidate"
    if candidates:
        return "ambiguous"
    return "unbound"


def extract_sequence_requirement_candidates(
    document: SequenceDocument,
    programming_brief: dict[str, Any],
    scenario_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Extract reviewable temporal/math candidates without treating prose as executable code."""

    available_points = {
        point["id"] for point in programming_brief["point_requirements"]["points"]
    }
    quantities: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    policies: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    for clause_start, clause_end, clause in _clauses(document.text):
        searchable_clause = "".join(
            " " if character.isspace() else character for character in clause
        )
        scenario_ids, facet_ids = _context_for_clause(
            clause_start,
            clause_end,
            scenario_results,
        )
        for match in _QUANTITY.finditer(searchable_clause):
            raw_value = match.group("value") or match.group("percent_value")
            raw_unit = match.group("unit") or match.group("percent_unit")
            value = float(raw_value.replace(",", ""))
            dimension, canonical_unit, multiplier = _normal_unit(raw_unit)
            canonical_value = value * multiplier
            absolute_start = clause_start + match.start()
            absolute_end = clause_start + match.end()
            prefix = searchable_clause[max(0, match.start() - 90) : match.start()]
            comparator = None if dimension == "time" else _comparison(prefix)
            timing = _timing_relation(prefix) if dimension == "time" else None
            if dimension == "time":
                kind = "duration"
                usage = timing
            elif comparator is not None:
                kind = "threshold"
                usage = "comparison"
            elif re.search(
                r"\b(?:command|modulate|limit|open|close|set(?:point)?)\b[^.]{0,50}$",
                prefix,
                flags=re.IGNORECASE,
            ):
                kind = "command-value"
                usage = "output"
            else:
                kind = "parameter"
                usage = "unspecified"
            if dimension == "time":
                point_candidates = []
            elif kind == "command-value":
                point_candidates = _command_candidates(prefix, available_points)
            else:
                point_candidates = _measurement_candidates(searchable_clause, available_points)
            quantities.append(
                {
                    "id": _stable_id(
                        document.sha256,
                        kind,
                        absolute_start,
                        absolute_end,
                        f"{canonical_value}:{canonical_unit}",
                    ),
                    "kind": kind,
                    "usage": usage,
                    "raw": {"value": value, "unit": raw_unit},
                    "canonical": {
                        "value": canonical_value,
                        "unit": canonical_unit,
                        "dimension": dimension,
                    },
                    "comparison": comparator,
                    "timing_relation": timing,
                    "input_point_candidates": point_candidates,
                    "point_binding_status": (
                        "not-applicable"
                        if dimension == "time"
                        else _binding_status(point_candidates)
                    ),
                    "scenario_ids": scenario_ids,
                    "facet_ids": facet_ids,
                    "source": {
                        "sha256": document.sha256,
                        "start": absolute_start,
                        "end": absolute_end,
                        "clause_start": clause_start,
                        "clause_end": clause_end,
                        "clause": re.sub(r"\s+", " ", clause),
                    },
                    "status": "candidate-review-required",
                    "approved": False,
                }
            )

        seen_actions: set[tuple[int, int, str, str]] = set()
        for expression in (_ACTION_FORWARD, _ACTION_REVERSE, _ALARM_ACTION):
            for match in expression.finditer(searchable_clause):
                verb = match.group("verb").lower()
                subject = re.sub(r"\s+", " ", match.group("subject").lower())
                key = (match.start(), match.end(), verb, subject)
                if key in seen_actions:
                    continue
                seen_actions.add(key)
                candidates = _available_candidates(
                    _ACTION_POINTS.get(subject, ()),
                    available_points,
                )
                absolute_start = clause_start + match.start()
                absolute_end = clause_start + match.end()
                actions.append(
                    {
                        "id": _stable_id(
                            document.sha256,
                            "action",
                            absolute_start,
                            absolute_end,
                            f"{verb}:{subject}",
                        ),
                        "kind": "action",
                        "verb": verb,
                        "subject": subject,
                        "point_candidates": candidates,
                        "point_binding_status": _binding_status(candidates),
                        "scenario_ids": scenario_ids,
                        "facet_ids": facet_ids,
                        "source": {
                            "sha256": document.sha256,
                            "start": absolute_start,
                            "end": absolute_end,
                            "clause_start": clause_start,
                            "clause_end": clause_end,
                            "clause": re.sub(r"\s+", " ", clause),
                        },
                        "status": "candidate-review-required",
                        "approved": False,
                    }
                )

        for policy, pattern in (
            ("manual-reset", re.compile(r"\bmanual reset\b", re.I)),
            ("automatic-reset", re.compile(r"\b(?:automatic|auto) reset\b", re.I)),
            ("latched", re.compile(r"\blatch(?:ed|ing)?\b", re.I)),
            ("highest-priority", re.compile(r"\bhighest priority\b", re.I)),
            ("bumpless-return", re.compile(r"\bbumpless\b", re.I)),
            ("immediate", re.compile(r"\bimmediate(?:ly)?\b", re.I)),
        ):
            for match in pattern.finditer(searchable_clause):
                absolute_start = clause_start + match.start()
                absolute_end = clause_start + match.end()
                policies.append(
                    {
                        "id": _stable_id(
                            document.sha256,
                            "policy",
                            absolute_start,
                            absolute_end,
                            policy,
                        ),
                        "kind": "policy",
                        "policy": policy,
                        "scenario_ids": scenario_ids,
                        "facet_ids": facet_ids,
                        "source": {
                            "sha256": document.sha256,
                            "start": absolute_start,
                            "end": absolute_end,
                            "clause_start": clause_start,
                            "clause_end": clause_end,
                            "clause": re.sub(r"\s+", " ", clause),
                        },
                        "status": "candidate-review-required",
                        "approved": False,
                    }
                )

        for kind, pattern in _UNRESOLVED:
            for match in pattern.finditer(searchable_clause):
                absolute_start = clause_start + match.start()
                absolute_end = clause_start + match.end()
                unresolved.append(
                    {
                        "id": _stable_id(
                            document.sha256,
                            "unresolved",
                            absolute_start,
                            absolute_end,
                            kind,
                        ),
                        "kind": kind,
                        "text": match.group(0),
                        "scenario_ids": scenario_ids,
                        "facet_ids": facet_ids,
                        "source": {
                            "sha256": document.sha256,
                            "start": absolute_start,
                            "end": absolute_end,
                            "clause_start": clause_start,
                            "clause_end": clause_end,
                            "clause": re.sub(r"\s+", " ", clause),
                        },
                        "blocking_reason": (
                            "The phrase does not provide a complete deterministic value or policy."
                        ),
                    }
                )

    for duration in (item for item in quantities if item["kind"] == "duration"):
        preceding = [
            item
            for item in quantities
            if item["kind"] == "threshold"
            and item["source"]["clause_start"] == duration["source"]["clause_start"]
            and item["source"]["end"] <= duration["source"]["start"]
        ]
        duration["condition_quantity_candidate_id"] = (
            max(preceding, key=lambda item: item["source"]["end"])["id"]
            if preceding
            else None
        )

    for quantity in (item for item in quantities if item["kind"] == "command-value"):
        preceding_actions = [
            item
            for item in actions
            if item["source"]["clause_start"] == quantity["source"]["clause_start"]
            and item["source"]["end"] <= quantity["source"]["start"]
        ]
        quantity["action_candidate_id"] = (
            max(preceding_actions, key=lambda item: item["source"]["end"])["id"]
            if preceding_actions
            else None
        )

    relationships: list[dict[str, Any]] = []
    all_clause_starts = sorted(
        {
            item["source"]["clause_start"]
            for group in (quantities, actions, policies, unresolved)
            for item in group
        }
    )
    for clause_start in all_clause_starts:
        clause_quantities = [
            item for item in quantities if item["source"]["clause_start"] == clause_start
        ]
        clause_actions = [
            item for item in actions if item["source"]["clause_start"] == clause_start
        ]
        clause_policies = [
            item for item in policies if item["source"]["clause_start"] == clause_start
        ]
        clause_unresolved = [
            item for item in unresolved if item["source"]["clause_start"] == clause_start
        ]
        representative = next(
            iter(clause_quantities or clause_actions or clause_policies or clause_unresolved)
        )
        thresholds = [item["id"] for item in clause_quantities if item["kind"] == "threshold"]
        durations = [item["id"] for item in clause_quantities if item["kind"] == "duration"]
        command_values = [
            item["id"] for item in clause_quantities if item["kind"] == "command-value"
        ]
        shape = "observations-only"
        if thresholds and clause_actions:
            shape = "numeric-condition-to-actions"
        elif clause_actions:
            shape = "actions-without-numeric-condition"
        elif thresholds:
            shape = "numeric-condition-without-action"
        relationships.append(
            {
                "id": _stable_id(
                    document.sha256,
                    "clause-relationship",
                    representative["source"]["clause_start"],
                    representative["source"]["clause_end"],
                    shape,
                ),
                "shape": shape,
                "threshold_candidate_ids": thresholds,
                "duration_candidate_ids": durations,
                "action_candidate_ids": [item["id"] for item in clause_actions],
                "command_value_candidate_ids": command_values,
                "policy_candidate_ids": [item["id"] for item in clause_policies],
                "unresolved_candidate_ids": [item["id"] for item in clause_unresolved],
                "source": {
                    "sha256": document.sha256,
                    "clause_start": representative["source"]["clause_start"],
                    "clause_end": representative["source"]["clause_end"],
                    "clause": representative["source"]["clause"],
                },
                "status": "candidate-review-required",
                "approved": False,
            }
        )

    bound_quantity_count = sum(
        item["kind"] == "duration" or item["point_binding_status"] == "single-candidate"
        for item in quantities
    )
    bound_action_count = sum(
        item["point_binding_status"] == "single-candidate" for item in actions
    )
    result = {
        "schema": "bactalk.sequence-requirement-candidates/v1",
        "source_sha256": document.sha256,
        "quantity_count": len(quantities),
        "duration_count": sum(item["kind"] == "duration" for item in quantities),
        "threshold_count": sum(item["kind"] == "threshold" for item in quantities),
        "action_count": len(actions),
        "policy_count": len(policies),
        "unresolved_count": len(unresolved),
        "relationship_count": len(relationships),
        "single_candidate_binding_count": bound_quantity_count + bound_action_count,
        "available_review_points": [
            {
                "id": point["id"],
                "label": point["label"],
                "role": point["role"],
                "data_type": point["data_type"],
                "units": point.get("units"),
            }
            for point in programming_brief["point_requirements"]["points"]
        ],
        "quantities": quantities,
        "actions": actions,
        "policies": policies,
        "unresolved": unresolved,
        "relationships": relationships,
        "ready_for_graph_generation": False,
        "approval_required": True,
        "next_gate": (
            "Resolve every ambiguous/unbound point, vague phrase, condition, and action order; "
            "then approve the normalized requirements and generate independent test oracles."
        ),
    }
    result["candidate_digest"] = hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return result


def _reviewable_candidates(candidates: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    return {
        item["id"]: (group, item)
        for group in ("quantities", "actions", "policies", "unresolved")
        for item in candidates[group]
    }


def _point_role_allowed(group: str, item: dict[str, Any], role: str) -> bool:
    if group == "actions":
        return role in {"command", "alarm"}
    if group == "quantities" and item["kind"] in {"threshold", "parameter"}:
        return role in {"sensor", "status", "setpoint"}
    return True


def _resolve_point(
    group: str,
    item: dict[str, Any],
    decision: SequenceCandidateDecision,
    point_by_id: dict[str, dict[str, Any]],
) -> tuple[str | None, str | None]:
    candidate_field = "point_candidates" if group == "actions" else "input_point_candidates"
    point_candidates = item.get(candidate_field, [])
    selected = decision.selected_point
    if selected is not None:
        point = point_by_id.get(selected)
        if point is None:
            return None, f"{item['id']} selected unknown design point {selected}"
        if not _point_role_allowed(group, item, point["role"]):
            return (
                None,
                f"{item['id']} selected {selected} with incompatible role {point['role']}",
            )
        if point_candidates and selected not in point_candidates:
            return (
                None,
                f"{item['id']} selected {selected} outside its audited point candidates",
            )
        return selected, None
    if len(point_candidates) == 1:
        return point_candidates[0], None
    if len(point_candidates) > 1:
        return None, f"{item['id']} requires one explicit selected_point"
    return None, f"{item['id']} has no point binding"


def _expected_action_value(
    action: dict[str, Any],
    point: dict[str, Any],
    command_value: dict[str, Any] | None,
) -> tuple[float | bool | None, str | None]:
    verb = action["verb"]
    numeric = point["data_type"] == "numeric"
    if verb in {"stop", "disable", "close", "de-energize", "reset"}:
        return (0.0 if numeric else False), None
    if verb in {"start", "restart", "enable", "open", "energize", "latch"}:
        return (100.0 if numeric else True), None
    if verb in {"limit", "modulate", "command"}:
        if command_value is None:
            return None, f"{action['id']} requires an approved numeric command value"
        value = float(command_value["canonical"]["value"])
        if not numeric:
            if value not in {0.0, 100.0}:
                return None, f"{action['id']} cannot apply {value}% to a Boolean point"
            return value == 100.0, None
        return value, None
    return None, f"{action['id']} uses unsupported action verb {verb}"


def compile_sequence_requirement_review(
    programming_brief: dict[str, Any],
    reconciliation: dict[str, Any],
    request: SequenceRequirementReviewRequest,
    *,
    reviewer: str,
    actor_id: str | None,
    tenant_id: str | None,
    authentication: str,
) -> dict[str, Any]:
    """Validate exhaustive human decisions and emit non-executable oracle drafts."""

    candidates = reconciliation["requirement_candidates"]
    if request.candidate_digest != candidates["candidate_digest"]:
        raise ValueError("sequence candidate digest changed; inspect the source again")
    reviewable = _reviewable_candidates(candidates)
    decisions = {decision.candidate_id: decision for decision in request.decisions}
    unknown = sorted(set(decisions) - set(reviewable))
    missing = sorted(set(reviewable) - set(decisions))
    if unknown:
        raise ValueError(f"sequence review contains unknown candidate IDs: {', '.join(unknown)}")
    if missing:
        raise ValueError(
            "sequence review must decide every candidate; missing: " + ", ".join(missing)
        )

    point_by_id = {
        point["id"]: point for point in programming_brief["point_requirements"]["points"]
    }
    reviewed: list[dict[str, Any]] = []
    blockers: list[str] = []
    approved_items: dict[str, dict[str, Any]] = {}
    for candidate_id in sorted(reviewable):
        group, item = reviewable[candidate_id]
        decision = decisions[candidate_id]
        if group == "unresolved":
            if decision.disposition != "resolve":
                blockers.append(f"{candidate_id} vague language must be resolved, not accepted")
            else:
                blockers.append(
                    f"{candidate_id} resolution requires a revised source document and reinspection"
                )
            reviewed.append(
                {
                    "candidate_id": candidate_id,
                    "group": group,
                    **decision.model_dump(mode="json"),
                    "effective_point": None,
                }
            )
            continue
        if decision.disposition == "resolve":
            blockers.append(f"{candidate_id} is structured and cannot use resolve disposition")
            effective_point = None
        elif decision.disposition == "reject":
            effective_point = None
        else:
            needs_point = group == "actions" or (
                group == "quantities" and item["kind"] in {"threshold", "parameter"}
            )
            if needs_point:
                effective_point, point_error = _resolve_point(
                    group,
                    item,
                    decision,
                    point_by_id,
                )
                if point_error is not None:
                    blockers.append(point_error)
            else:
                effective_point = None
                if decision.selected_point is not None:
                    blockers.append(f"{candidate_id} does not accept a selected_point")
            approved_items[candidate_id] = {
                **item,
                "effective_point": effective_point,
            }
        reviewed.append(
            {
                "candidate_id": candidate_id,
                "group": group,
                **decision.model_dump(mode="json"),
                "effective_point": effective_point,
            }
        )

    oracle_drafts: list[dict[str, Any]] = []
    skipped_relationships: list[dict[str, Any]] = []
    for relationship in candidates["relationships"]:
        if relationship["shape"] != "numeric-condition-to-actions":
            skipped_relationships.append(
                {
                    "relationship_id": relationship["id"],
                    "reason": "relationship is not a numeric condition with observable actions",
                }
            )
            continue
        required_ids = (
            relationship["threshold_candidate_ids"]
            + relationship["duration_candidate_ids"]
            + relationship["action_candidate_ids"]
            + relationship["command_value_candidate_ids"]
            + relationship["policy_candidate_ids"]
            + relationship["unresolved_candidate_ids"]
        )
        rejected = [
            candidate_id
            for candidate_id in required_ids
            if decisions[candidate_id].disposition != "approve"
        ]
        if rejected:
            message = (
                f"{relationship['id']} has rejected or unresolved candidates: "
                + ", ".join(rejected)
            )
            blockers.append(message)
            skipped_relationships.append(
                {"relationship_id": relationship["id"], "reason": message}
            )
            continue

        conditions = []
        relation_blockers: list[str] = []
        for candidate_id in relationship["threshold_candidate_ids"]:
            item = approved_items[candidate_id]
            point_id = item.get("effective_point")
            if point_id is None:
                relation_blockers.append(f"{candidate_id} has no approved condition point")
                continue
            point = point_by_id[point_id]
            conditions.append(
                {
                    "point": point_id,
                    "operator": item["comparison"],
                    "value": item["canonical"]["value"],
                    "unit": item["canonical"]["unit"],
                    "point_unit": point.get("units"),
                    "unit_conversion_required": (
                        point.get("units") is not None
                        and point.get("units") != item["canonical"]["unit"]
                    ),
                    "candidate_id": candidate_id,
                }
            )
        durations = [
            {
                "seconds": approved_items[candidate_id]["canonical"]["value"],
                "relation": approved_items[candidate_id]["timing_relation"],
                "condition_candidate_id": approved_items[candidate_id].get(
                    "condition_quantity_candidate_id"
                ),
                "candidate_id": candidate_id,
            }
            for candidate_id in relationship["duration_candidate_ids"]
        ]
        expectations = []
        for action_id in relationship["action_candidate_ids"]:
            action = approved_items[action_id]
            point_id = action.get("effective_point")
            if point_id is None:
                relation_blockers.append(f"{action_id} has no approved action point")
                continue
            command_value = next(
                (
                    approved_items[candidate_id]
                    for candidate_id in relationship["command_value_candidate_ids"]
                    if approved_items[candidate_id].get("action_candidate_id") == action_id
                ),
                None,
            )
            value, action_error = _expected_action_value(
                action,
                point_by_id[point_id],
                command_value,
            )
            if action_error is not None:
                relation_blockers.append(action_error)
                continue
            expectations.append(
                {
                    "point": point_id,
                    "operator": "eq",
                    "value": value,
                    "verb": action["verb"],
                    "action_candidate_id": action_id,
                    "command_value_candidate_id": (
                        command_value["id"] if command_value is not None else None
                    ),
                }
            )
        if relation_blockers or not conditions or not expectations:
            blockers.extend(relation_blockers)
            skipped_relationships.append(
                {
                    "relationship_id": relationship["id"],
                    "reason": "; ".join(relation_blockers)
                    or "condition or expectation set is empty",
                }
            )
            continue
        oracle_drafts.append(
            {
                "id": f"oracle-{relationship['id'].removeprefix('seqreq-')}",
                "relationship_id": relationship["id"],
                "conditions": conditions,
                "durations": durations,
                "expectations": expectations,
                "policies": [
                    approved_items[candidate_id]["policy"]
                    for candidate_id in relationship["policy_candidate_ids"]
                ],
                "source": relationship["source"],
                "status": "draft-independent-oracle-required",
                "executable": False,
            }
        )

    review_payload = {
        "candidate_digest": candidates["candidate_digest"],
        "configuration_digest": reconciliation["configuration_digest"],
        "reviewer": reviewer,
        "actor_id": actor_id,
        "tenant_id": tenant_id,
        "authentication": authentication,
        "decisions": [decision.model_dump(mode="json") for decision in request.decisions],
    }
    review_digest = hashlib.sha256(
        json.dumps(review_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    scenario_oracle_coverage = []
    for scenario in reconciliation["scenarios"]:
        facet_coverage = []
        for facet in scenario["facets"]:
            oracle_ids = sorted(
                draft["id"]
                for draft in oracle_drafts
                if any(
                    draft["source"]["clause_start"] < evidence["end"]
                    and evidence["start"] < draft["source"]["clause_end"]
                    for evidence in facet["evidence"]
                )
            )
            facet_coverage.append(
                {
                    "id": facet["id"],
                    "label": facet["label"],
                    "phrase_mentioned": facet["mentioned"],
                    "oracle_draft_ids": oracle_ids,
                    "executable_oracle_draft_present": bool(oracle_ids),
                }
            )
        scenario_oracle_coverage.append(
            {
                "id": scenario["id"],
                "title": scenario["title"],
                "level": scenario["level"],
                "phrase_coverage_status": scenario["coverage_status"],
                "facets": facet_coverage,
                "all_facets_have_oracle_drafts": bool(facet_coverage)
                and all(item["executable_oracle_draft_present"] for item in facet_coverage),
            }
        )
    all_scenario_facets_have_oracle_drafts = bool(scenario_oracle_coverage) and all(
        item["all_facets_have_oracle_drafts"] for item in scenario_oracle_coverage
    )
    manual_facet_oracle_requirements = [
        {
            "scenario_id": scenario["id"],
            "scenario_title": scenario["title"],
            "facet_id": facet["id"],
            "facet_label": facet["label"],
            "phrase_mentioned": facet["phrase_mentioned"],
            "source_evidence": [
                evidence
                for source_scenario in reconciliation["scenarios"]
                if source_scenario["id"] == scenario["id"]
                for source_facet in source_scenario["facets"]
                if source_facet["id"] == facet["id"]
                for evidence in source_facet["evidence"]
            ],
            "authoring_allowed": facet["phrase_mentioned"],
            "blocking_reason": (
                "Author an independent baseline/trigger/recovery trajectory using the "
                "retained point contract."
                if facet["phrase_mentioned"]
                else "The contractor sequence does not mention this required facet; revise "
                "and re-upload the source before authoring a test."
            ),
        }
        for scenario in scenario_oracle_coverage
        for facet in scenario["facets"]
        if not facet["executable_oracle_draft_present"]
    ]
    return {
        "schema": "bactalk.sequence-requirement-review/v1",
        "candidate_digest": candidates["candidate_digest"],
        "review_digest": review_digest,
        "configuration_digest": reconciliation["configuration_digest"],
        "source_sha256": candidates["source_sha256"],
        "point_contract": {
            "schema": "bactalk.sequence-review-point-contract/v1",
            "points": [
                {
                    key: point.get(key)
                    for key in (
                        "id",
                        "label",
                        "role",
                        "data_type",
                        "units",
                        "required",
                        "condition",
                        "reason",
                        "subsystem",
                    )
                }
                for point in programming_brief["point_requirements"]["points"]
            ],
        },
        "review": {
            "reviewer": reviewer,
            "actor_id": actor_id,
            "tenant_id": tenant_id,
            "authentication": authentication,
            "reviewed_at": datetime.now(UTC).isoformat(),
            "decision_count": len(reviewed),
            "decisions": reviewed,
        },
        "oracle_draft_count": len(oracle_drafts),
        "oracle_drafts": oracle_drafts,
        "scenario_oracle_coverage": scenario_oracle_coverage,
        "all_scenario_facets_have_oracle_drafts": all_scenario_facets_have_oracle_drafts,
        "scenario_oracle_gap_count": sum(
            not facet["executable_oracle_draft_present"]
            for scenario in scenario_oracle_coverage
            for facet in scenario["facets"]
        ),
        "manual_facet_oracle_requirements": manual_facet_oracle_requirements,
        "skipped_relationships": skipped_relationships,
        "blockers": sorted(set(blockers)),
        "ready_for_independent_oracle_authoring": bool(oracle_drafts) and not blockers,
        "ready_for_graph_generation": False,
        "ready_for_deployment": False,
        "next_gate": (
            "An engineer must turn each local draft into an independent acceptance trajectory. "
            "Whole-system graph generation additionally requires an executable oracle for every "
            "selected scenario facet."
        ),
        "safety": {
            "live_writes_enabled": False,
            "text_approval_authorizes_deployment": False,
            "independent_test_oracle_required": True,
        },
    }
