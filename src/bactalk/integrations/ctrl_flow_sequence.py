# The audited expression catalog is clearer when each complete regex remains on one line.
# ruff: noqa: E501

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from bactalk.intake import SequenceDocument
from bactalk.sequence_requirements import extract_sequence_requirement_candidates


@dataclass(frozen=True)
class _Facet:
    id: str
    label: str
    patterns: tuple[str, ...]


def _facet(facet_id: str, label: str, *patterns: str) -> _Facet:
    return _Facet(facet_id, label, patterns)


# These rules deliberately look for observable engineering language, not generic topic words.
# A match proves only that a facet was mentioned. It never proves the sequence is correct.
_COMMON: dict[str, tuple[_Facet, ...]] = {
    "normal-operation": (
        _facet("occupied-mode", "occupied operating mode", r"\boccupied (?:mode|operation|period)\b"),
        _facet(
            "controlled-response",
            "closed-loop or modulating response",
            r"\b(?:modulat(?:e|es|ing)|pid|control loop)\b",
        ),
        _facet(
            "bounded-command",
            "minimum and maximum output bounds",
            r"\b(?:minimum|maximum|min(?:imum)? and max(?:imum)?|upper limit|lower limit)\b",
        ),
    ),
    "unoccupied-shutdown": (
        _facet("unoccupied-mode", "unoccupied or disabled mode", r"\b(?:unoccupied|disabled)\b"),
        _facet(
            "shutdown-state",
            "declared shutdown output state",
            r"\b(?:shut ?down|shut off|de-energiz(?:e|ed)|command(?:ed)? off|safe state)\b",
        ),
        _facet(
            "ventilation-policy",
            "unoccupied ventilation policy",
            r"\b(?:minimum ventilation|outdoor air|outside air|ventilation)\b",
        ),
        _facet(
            "alarm-policy",
            "unoccupied alarm policy",
            r"\b(?:suppress(?:ed|ion)?|inhibit(?:ed|ion)?|alarm delay|alarms? remain)\b",
        ),
    ),
    "sensor-invalid": (
        _facet(
            "invalid-detection",
            "invalid-quality detection",
            r"\b(?:invalid|bad quality|unreliable|sensor fault|out of range)\b",
        ),
        _facet("fallback", "declared fallback", r"\b(?:fallback|fail[- ]safe|substitute value)\b"),
        _facet(
            "operator-visibility",
            "operator-visible cause or alarm",
            r"\b(?:alarm|notify|operator visible|diagnostic)\b",
        ),
    ),
    "sensor-stale": (
        _facet(
            "stale-detection",
            "stale or frozen-value detection",
            r"\b(?:stale|frozen value|unchanged value|no change in (?:value|reading))\b",
        ),
        _facet(
            "stale-timer",
            "staleness timer",
            r"\b(?:stale|unchanged|no change)[^.\n]{0,100}\b(?:timer|minutes?|seconds?|timeout)\b",
        ),
        _facet("fallback", "declared stale-data fallback", r"\b(?:fallback|fail[- ]safe|substitute value)\b"),
        _facet("recovery", "fresh-data recovery", r"\b(?:fresh data|valid data|recover(?:y|ed)?|restor(?:e|ed))\b"),
    ),
    "communications-loss": (
        _facet(
            "loss-detection",
            "communications-loss detection",
            r"\b(?:communications?|bacnet|network|peer controller)[ -](?:loss|failure|fault|timeout)\b",
            r"\b(?:offline|heartbeat timeout)\b",
        ),
        _facet(
            "local-fallback",
            "safe local fallback",
            r"\b(?:local control|local mode|last known|fallback|fail[- ]safe)\b",
        ),
        _facet("alarm", "communications alarm", r"\b(?:communications?|network|offline)[^.\n]{0,100}\balarm\b"),
        _facet("recovery", "communications recovery", r"\b(?:communications?|network|bacnet)[^.\n]{0,120}\b(?:recover|restore|reconnect|return)\w*\b"),
    ),
    "manual-override": (
        _facet(
            "override-source",
            "operator or hand override",
            r"\b(?:manual override|operator override|hand[- /]off[- /]auto|hoa switch|hand mode)\b",
        ),
        _facet(
            "priority",
            "command priority or arbitration",
            r"\b(?:priority|precedence|arbitrat(?:e|ion)|highest command)\b",
        ),
        _facet(
            "indication",
            "override indication",
            r"\b(?:override|hand mode)[^.\n]{0,100}\b(?:indicat(?:e|ion)|alarm|display|notify)\w*\b",
        ),
        _facet(
            "release",
            "controlled return to automatic control",
            r"\b(?:release|return)[^.\n]{0,100}\b(?:automatic|auto mode|normal control|bumpless)\b",
        ),
    ),
    "power-cycle": (
        _facet(
            "restart-event",
            "power-cycle or warm-restart behavior",
            r"\b(?:power cycle|power failure|warm restart|controller restart|reboot)\b",
        ),
        _facet(
            "safe-initialization",
            "safe output initialization",
            r"\b(?:initializ(?:e|ation)|startup)[^.\n]{0,120}\b(?:safe|off|closed|de-energized)\b",
        ),
        _facet(
            "timer-state",
            "timer/state restoration policy",
            r"\b(?:timer|state)[^.\n]{0,120}\b(?:restore|retain|reset|restart|initialize)\w*\b",
        ),
        _facet(
            "controlled-restart",
            "controlled restart sequence",
            r"\b(?:restart|startup)[^.\n]{0,120}\b(?:delay|sequence|stagger|prove|controlled)\w*\b",
        ),
    ),
    "actuator-failure": (
        _facet(
            "disagreement",
            "command/feedback disagreement",
            r"\bcommand(?:ed)?[^.\n]{0,100}\b(?:feedback|position|status|proof)[^.\n]{0,80}\b(?:disagree|fail|not|loss|mismatch)\w*\b",
            r"\b(?:actuator|valve|damper)[ -](?:failure|fault)\b",
        ),
        _facet("proof-timeout", "proof timeout", r"\b(?:proof|feedback)[^.\n]{0,100}\b(?:delay|timer|timeout|seconds?|minutes?)\b"),
        _facet("fallback", "failure fallback", r"\b(?:fallback|fail[- ]safe|safe position|safe state)\b"),
        _facet("alarm", "actuator alarm", r"\b(?:actuator|feedback|proof|position)[^.\n]{0,100}\balarm\b"),
        _facet("recovery", "actuator recovery", r"\b(?:feedback|proof|actuator)[^.\n]{0,120}\b(?:recover|restore|reset|return)\w*\b"),
    ),
    "recovery": (
        _facet(
            "clear-criteria",
            "fault-clear criteria",
            r"\b(?:fault|alarm)[^.\n]{0,100}\b(?:clear criteria|clears? when|clear after|return to normal)\b",
        ),
        _facet(
            "reset-policy",
            "latch and reset policy",
            r"\b(?:manual reset|automatic reset|auto reset|latch(?:ed|ing)?|reset required)\b",
        ),
        _facet(
            "bumpless-resume",
            "controlled or bumpless resume",
            r"\b(?:bumpless|controlled|ramp(?:ed)?)\b[^.\n]{0,80}\b(?:resume|restart|recovery|return)\b",
        ),
    ),
}


_EQUIPMENT: dict[str, tuple[_Facet, ...]] = {
    "airflow-proof": (
        _facet("flow-failure", "airflow proof or tracking failure", r"\b(?:airflow|flow)[ -](?:proof|tracking|failure|fault|loss)\b"),
        _facet("damper-limit", "bounded damper response", r"\bdamper[^.\n]{0,100}\b(?:limit|minimum|maximum|bounded|close)\w*\b"),
        _facet("delayed-alarm", "delayed airflow alarm", r"\b(?:airflow|flow)[^.\n]{0,100}\b(?:alarm delay|delayed alarm|alarm after|timer)\b"),
        _facet("sensor-fallback", "airflow-sensor fallback", r"\b(?:airflow|flow) sensor[^.\n]{0,120}\b(?:fallback|fail[- ]safe|default)\b"),
    ),
    "zone-mode-transitions": (
        _facet("modes", "heating, deadband, and cooling modes", r"\bheating\b[^.\n]{0,160}\bdeadband\b[^.\n]{0,160}\bcooling\b", r"\bcooling\b[^.\n]{0,160}\bdeadband\b[^.\n]{0,160}\bheating\b"),
        _facet("hysteresis", "transition hysteresis", r"\b(?:hysteresis|deadband timer|minimum mode time)\b"),
        _facet("airflow-bounds", "bounded airflow", r"\bairflow[^.\n]{0,100}\b(?:minimum|maximum|limit|bounded)\b"),
        _facet("requests", "system requests", r"\b(?:heating|cooling|static pressure|temperature)[ -]request\b"),
    ),
    "ahu-unavailable": (
        _facet("availability", "upstream AHU availability", r"\b(?:ahu|air handler)[^.\n]{0,100}\b(?:unavailable|disabled|off|failure)\b"),
        _facet("damper-state", "declared damper state", r"\bdamper[^.\n]{0,100}\b(?:close|closed|minimum|position|state)\b"),
        _facet("alarm-policy", "alarm suppression or qualification", r"\b(?:suppress|inhibit|qualif)\w*[^.\n]{0,100}\balarm\b", r"\balarm[^.\n]{0,100}\b(?:suppress|inhibit|qualif)\w*\b"),
        _facet("recovery", "AHU availability recovery", r"\b(?:ahu|air handler)[^.\n]{0,120}\b(?:available|recover|restart|returns?)\w*\b"),
    ),
    "reheat-failure": (
        _facet("failure-proof", "reheat command proof", r"\breheat[^.\n]{0,120}\b(?:failure|fault|proof|feedback)\b"),
        _facet("proof-timer", "reheat proof timer", r"\breheat[^.\n]{0,120}\b(?:timer|delay|timeout|minutes?|seconds?)\b"),
        _facet("alarm", "reheat failure alarm", r"\breheat[^.\n]{0,120}\balarm\b"),
        _facet("temperature-bound", "bounded discharge temperature", r"\bdischarge(?: air)? temperature[^.\n]{0,100}\b(?:limit|maximum|high)\b"),
    ),
    "plant-unavailable": (
        _facet("availability", "plant availability", r"\b(?:heating|cooling|hot water|chilled water|plant)[ -](?:plant )?(?:is )?(?:unavailable|available|failure|disabled)\b"),
        _facet("request", "plant request", r"\b(?:heating|cooling|hot water|chilled water|plant)[ -]request\b"),
        _facet("fallback", "plant-loss command policy", r"\bplant[^.\n]{0,120}\b(?:fallback|disable|close|limit|command policy)\b"),
        _facet("alarm-policy", "plant-qualified alarm", r"\bplant[^.\n]{0,120}\balarm\b", r"\balarm[^.\n]{0,120}\bplant\b"),
        _facet("recovery", "plant recovery", r"\bplant[^.\n]{0,120}\b(?:recover|available|restore|return)\w*\b"),
    ),
    "discharge-high-limit": (
        _facet("high-limit", "discharge-air high limit", r"\bdischarge(?: air)? temperature[^.\n]{0,100}\b(?:high limit|maximum|exceeds?)\b"),
        _facet("limit-action", "command limiting action", r"\b(?:high limit|maximum)[^.\n]{0,120}\b(?:limit|close|reduce|disable)\w*\b"),
        _facet("alarm", "high-temperature alarm", r"\b(?:discharge|high temperature)[^.\n]{0,100}\balarm\b"),
        _facet("recovery", "automatic high-limit recovery", r"\b(?:discharge|high limit)[^.\n]{0,120}\b(?:automatic(?:ally)?|recover|reset|clear)\w*\b"),
    ),
    "co2-failure": (
        _facet("detection", "CO2 invalid/stale detection", r"\bco2[^.\n]{0,100}\b(?:invalid|stale|failure|fault)\b"),
        _facet("default", "CO2 failure default", r"\bco2[^.\n]{0,120}\b(?:default|fallback|substitute|fail[- ]safe)\b"),
        _facet("alarm", "CO2 sensor alarm", r"\bco2[^.\n]{0,100}\balarm\b"),
        _facet("recovery", "CO2 recovery", r"\bco2[^.\n]{0,120}\b(?:recover|valid|restore|return)\w*\b"),
    ),
    "occupancy-sensor-failure": (
        _facet("detection", "occupancy sensor invalid/stale detection", r"\boccupancy sensor[^.\n]{0,100}\b(?:invalid|stale|failure|fault)\b"),
        _facet("default", "occupancy failure default", r"\boccupancy sensor[^.\n]{0,120}\b(?:default|fallback|substitute|schedule)\b"),
        _facet("alarm", "occupancy sensor alarm", r"\boccupancy sensor[^.\n]{0,100}\balarm\b"),
        _facet("recovery", "occupancy sensor recovery", r"\boccupancy sensor[^.\n]{0,120}\b(?:recover|valid|restore|return)\w*\b"),
    ),
    "window-sensor-failure": (
        _facet("detection", "window sensor invalid/stale detection", r"\bwindow sensor[^.\n]{0,100}\b(?:invalid|stale|failure|fault)\b"),
        _facet("default", "window failure default", r"\bwindow sensor[^.\n]{0,120}\b(?:default|fallback|substitute|closed)\b"),
        _facet("alarm", "window sensor alarm", r"\bwindow sensor[^.\n]{0,100}\balarm\b"),
        _facet("recovery", "window sensor recovery", r"\bwindow sensor[^.\n]{0,120}\b(?:recover|valid|restore|return)\w*\b"),
    ),
    "fire-smoke": (
        _facet("life-safety-input", "fire/smoke input or alarm", r"\b(?:fire alarm|smoke detector|smoke alarm|fire[- ]smoke)\b"),
        _facet("priority", "life-safety priority", r"\b(?:fire|smoke)[^.\n]{0,120}\b(?:override|highest priority|priority)\b"),
        _facet("output-state", "declared fan and damper state", r"\b(?:fire|smoke)[^.\n]{0,180}\b(?:fan|damper)[^.\n]{0,120}\b(?:off|stop|close|open|state)\b"),
        _facet("reset", "manual-reset boundary", r"\b(?:fire|smoke)[^.\n]{0,150}\bmanual reset\b", r"\bmanual reset[^.\n]{0,150}\b(?:fire|smoke)\b"),
    ),
    "duct-high-pressure": (
        _facet("trip", "duct high-pressure trip", r"\bduct high[- ]pressure\b", r"\bhigh duct (?:static )?pressure\b"),
        _facet("shutdown", "immediate fan shutdown", r"\b(?:duct high[- ]pressure|high duct (?:static )?pressure)[^.\n]{0,150}\b(?:immediate|stop|shut ?down|off)\w*\b"),
        _facet("latch", "latched alarm/reset policy", r"\b(?:duct high[- ]pressure|high duct (?:static )?pressure)[^.\n]{0,150}\b(?:latch|manual reset|alarm)\w*\b"),
        _facet("restart", "safe restart", r"\b(?:duct high[- ]pressure|high duct (?:static )?pressure)[^.\n]{0,180}\b(?:restart|reset|recover)\w*\b"),
    ),
    "supply-fan-proof": (
        _facet("proof-loss", "supply fan proof loss", r"\bsupply fan[^.\n]{0,100}\b(?:proof|status)[^.\n]{0,80}\b(?:fail|loss|not|off)\w*\b"),
        _facet("delay", "fan proof delay", r"\bsupply fan[^.\n]{0,120}\b(?:proof delay|timeout|timer|seconds?|minutes?)\b"),
        _facet("dependent-outputs", "dependent coil/damper fallback", r"\bsupply fan[^.\n]{0,200}\b(?:coil|damper)[^.\n]{0,100}\b(?:close|disable|fallback|safe)\w*\b"),
        _facet("alarm", "fan proof alarm", r"\bsupply fan[^.\n]{0,120}\balarm\b"),
        _facet("recovery", "fan proof recovery", r"\bsupply fan[^.\n]{0,150}\b(?:proof returns|recover|restart|reset)\w*\b"),
    ),
    "economizer-limits": (
        _facet("enable-disable", "economizer enable/disable criteria", r"\beconomizer[^.\n]{0,120}\b(?:enable|disable)\w*\b"),
        _facet("high-limit", "economizer high limit", r"\beconomizer[^.\n]{0,120}\bhigh limit\b", r"\bhigh limit[^.\n]{0,120}\beconomizer\b"),
        _facet("minimum-ventilation", "minimum ventilation", r"\bminimum (?:outdoor air|outside air|ventilation)\b"),
        _facet("integrated-cooling", "integrated cooling", r"\bintegrated (?:cooling|economizer)\b"),
        _facet("sensor-fallback", "economizer sensor fallback", r"\beconomizer[^.\n]{0,160}\b(?:sensor|temperature|enthalpy)[^.\n]{0,100}\b(?:fallback|failure|invalid)\w*\b"),
    ),
    "mixed-air-low-limit": (
        _facet("low-limit", "mixed-air low limit", r"\bmixed[- ]air[^.\n]{0,80}\b(?:low limit|minimum|freeze)\b"),
        _facet("damper-action", "outdoor-air damper limiting", r"\b(?:mixed[- ]air|low limit)[^.\n]{0,160}\b(?:outdoor|outside)[- ]air damper[^.\n]{0,80}\b(?:limit|close|reduce|modulat)\w*\b"),
        _facet("heating-action", "heating response", r"\b(?:mixed[- ]air|low limit)[^.\n]{0,160}\b(?:heating|preheat|coil|valve)\b"),
        _facet("escalation", "low-limit escalation", r"\b(?:mixed[- ]air|low limit)[^.\n]{0,180}\b(?:escalat|stage|alarm|freeze)\w*\b"),
    ),
    "simultaneous-heat-cool": (
        _facet("exclusion", "simultaneous heating/cooling exclusion", r"\b(?:simultaneous|concurrent)[ -](?:heating and cooling|heat and cool)\b", r"\bprevent[^.\n]{0,100}\bheating[^.\n]{0,80}\bcooling\b"),
        _facet("deadband", "heating/cooling deadband or sequencing", r"\b(?:heating|cooling)[^.\n]{0,120}\b(?:deadband|sequence|interlock)\b"),
        _facet("bounded-commands", "bounded coil commands", r"\b(?:heating|cooling) (?:coil|valve)[^.\n]{0,120}\b(?:limit|maximum|minimum|bounded)\b"),
    ),
    "freeze-protection": (
        _facet("stages", "every freeze-protection stage/threshold", r"\bfreeze(?:stat| protection)?[^.\n]{0,150}\b(?:stage|threshold|setpoint|temperature)\b"),
        _facet("fan-damper", "freeze fan/damper action", r"\bfreeze(?:stat| protection)?[^.\n]{0,180}\b(?:fan|damper)[^.\n]{0,100}\b(?:stop|off|close|open|command)\w*\b"),
        _facet("coil", "freeze coil/valve action", r"\bfreeze(?:stat| protection)?[^.\n]{0,180}\b(?:coil|valve|heating)[^.\n]{0,100}\b(?:open|enable|command|maximum)\w*\b"),
        _facet("latch-reset", "freeze latch/reset policy", r"\bfreeze(?:stat| protection)?[^.\n]{0,160}\b(?:latch|manual reset|automatic reset)\w*\b"),
        _facet("recovery", "freeze recovery", r"\bfreeze(?:stat| protection)?[^.\n]{0,180}\b(?:recover|restart|reset|clear)\w*\b"),
    ),
    "return-relief-failure": (
        _facet("proof", "return/relief proof or feedback failure", r"\b(?:return|relief) (?:fan|damper)[^.\n]{0,120}\b(?:proof|feedback|failure|fault)\b"),
        _facet("pressure-fallback", "building-pressure fallback", r"\b(?:return|relief|building pressure)[^.\n]{0,160}\b(?:fallback|safe|default)\b"),
        _facet("alarm", "return/relief alarm", r"\b(?:return|relief) (?:fan|damper)[^.\n]{0,120}\balarm\b"),
        _facet("recovery", "return/relief recovery", r"\b(?:return|relief) (?:fan|damper)[^.\n]{0,150}\b(?:recover|reset|restore|return)\w*\b"),
    ),
    "airflow-station-failure": (
        _facet("invalid-stale", "airflow-station invalid/stale detection", r"\bairflow station[^.\n]{0,120}\b(?:invalid|stale|failure|fault)\b"),
        _facet("fallback", "airflow tracking fallback", r"\bairflow station[^.\n]{0,160}\b(?:fallback|static pressure|default speed|safe speed)\b"),
        _facet("alarm", "airflow-station alarm", r"\bairflow station[^.\n]{0,100}\balarm\b"),
    ),
    "building-pressure-failure": (
        _facet("sensor-failure", "building-pressure sensor failure", r"\bbuilding[- ]pressure sensor[^.\n]{0,100}\b(?:invalid|stale|failure|fault)\b"),
        _facet("fallback", "building-pressure fallback", r"\bbuilding[- ]pressure[^.\n]{0,140}\b(?:fallback|default|safe)\b"),
        _facet("bounded-output", "bounded return/relief output", r"\bbuilding[- ]pressure[^.\n]{0,180}\b(?:fan|damper)[^.\n]{0,100}\b(?:limit|bounded|minimum|maximum)\b"),
        _facet("alarm", "building-pressure alarm", r"\bbuilding[- ]pressure[^.\n]{0,100}\balarm\b"),
    ),
}


def _excerpt(text: str, start: int, end: int, *, radius: int = 150) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    snippet = re.sub(r"\s+", " ", text[left:right]).strip()
    if left:
        snippet = "…" + snippet
    if right < len(text):
        snippet += "…"
    return snippet


def _match_facet(text: str, searchable_text: str, facet: _Facet) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    occupied: list[tuple[int, int]] = []
    for pattern in facet.patterns:
        match = re.search(pattern, searchable_text, flags=re.IGNORECASE)
        if match is None:
            continue
        span = match.span()
        if any(abs(span[0] - prior[0]) < 20 for prior in occupied):
            continue
        occupied.append(span)
        evidence.append(
            {
                "matched_text": re.sub(r"\s+", " ", text[span[0] : span[1]]).strip(),
                "start": span[0],
                "end": span[1],
                "excerpt": _excerpt(text, *span),
            }
        )
        if len(evidence) == 2:
            break
    return evidence


class CtrlFlowSequenceReconciler:
    """Triage sequence language against the scenario contract without claiming semantics."""

    def reconcile(
        self,
        programming_brief: dict[str, Any],
        document: SequenceDocument,
    ) -> dict[str, Any]:
        scenarios: list[dict[str, Any]] = programming_brief["qualification_plan"]["scenarios"]
        # Preserve character offsets while making hard-wrapped PDF/DOCX prose searchable.
        searchable_text = "".join(" " if character.isspace() else character for character in document.text)
        results: list[dict[str, Any]] = []
        for scenario in scenarios:
            facets = _COMMON.get(scenario["id"]) or _EQUIPMENT.get(scenario["id"])
            if facets is None:
                results.append(
                    {
                        "id": scenario["id"],
                        "title": scenario["title"],
                        "level": scenario["level"],
                        "coverage_status": "coverage-rule-missing",
                        "facet_count": 0,
                        "mentioned_facet_count": 0,
                        "facets": [],
                        "missing_facets": ["BACTalk has no deterministic coverage rule"],
                        "engineering_note": scenario["reason"],
                    }
                )
                continue

            facet_results = []
            for facet in facets:
                evidence = _match_facet(document.text, searchable_text, facet)
                facet_results.append(
                    {
                        "id": facet.id,
                        "label": facet.label,
                        "mentioned": bool(evidence),
                        "evidence": evidence,
                    }
                )
            mentioned = sum(item["mentioned"] for item in facet_results)
            status = (
                "all-facets-mentioned"
                if mentioned == len(facet_results)
                else "partial"
                if mentioned
                else "not-mentioned"
            )
            results.append(
                {
                    "id": scenario["id"],
                    "title": scenario["title"],
                    "level": scenario["level"],
                    "coverage_status": status,
                    "facet_count": len(facet_results),
                    "mentioned_facet_count": mentioned,
                    "facets": facet_results,
                    "missing_facets": [
                        item["label"] for item in facet_results if not item["mentioned"]
                    ],
                    "engineering_note": scenario["reason"],
                }
            )

        all_mentioned = sum(
            item["coverage_status"] == "all-facets-mentioned" for item in results
        )
        partial = sum(item["coverage_status"] == "partial" for item in results)
        not_mentioned = sum(item["coverage_status"] == "not-mentioned" for item in results)
        rules_missing = sum(
            item["coverage_status"] == "coverage-rule-missing" for item in results
        )
        missing_facet_count = sum(len(item["missing_facets"]) for item in results)
        language_complete = all_mentioned == len(results) and bool(results)
        requirement_candidates = extract_sequence_requirement_candidates(
            document,
            programming_brief,
            results,
        )
        return {
            "schema": "bactalk.ctrl-flow-sequence-reconciliation/v1",
            "configuration_digest": programming_brief["configuration_digest"],
            "design_binding": programming_brief["design_binding"],
            "source_document": {
                "filename": document.filename,
                "media_type": document.media_type,
                "sha256": document.sha256,
                "character_count": len(document.text),
                "suggested_sequence_families": document.suggested_sequence_families,
            },
            "scenario_count": len(results),
            "all_facets_mentioned_count": all_mentioned,
            "partial_count": partial,
            "not_mentioned_count": not_mentioned,
            "coverage_rule_missing_count": rules_missing,
            "missing_facet_count": missing_facet_count,
            "language_coverage_complete": language_complete,
            "scenarios": results,
            "requirement_candidates": requirement_candidates,
            "gate": (
                "engineer-review-required"
                if language_complete
                else "blocked-missing-or-partial-sequence-language"
            ),
            "ready_for_code_generation": False,
            "semantic_validation_complete": False,
            "engineer_review_required": True,
            "limitations": [
                "Deterministic phrase evidence shows that a behavior was mentioned; it does not prove the behavior is correct, complete, coordinated, or testable.",
                "Thresholds, delays, priorities, reset behavior, units, and acceptance criteria still require structured extraction and engineer confirmation.",
                "Code generation remains blocked until the sequence is converted into approved executable requirements and linked test oracles.",
            ],
            "safety": {
                "offline_only": True,
                "live_writes_enabled": False,
                "human_approval_required": True,
            },
        }
