from __future__ import annotations

import hashlib
import re
from typing import Any

from bactalk.intake import SequenceDocument

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
    return {
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
