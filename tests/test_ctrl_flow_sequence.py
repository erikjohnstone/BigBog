from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from bactalk.api import create_app
from bactalk.intake import parse_sequence_document
from bactalk.integrations.ctrl_flow import CtrlFlowLibrary
from bactalk.integrations.ctrl_flow_planning import AHU_TEMPLATE
from bactalk.integrations.ctrl_flow_sequence import CtrlFlowSequenceReconciler

RICH_AHU_SEQUENCE = """
NORMAL OPERATION
During occupied operation, a PID control loop shall modulate outputs between the minimum and
maximum commands.
When unoccupied, the AHU shall shut down to a safe state; minimum ventilation is zero and
alarms remain enabled unless specifically qualified.

INPUT AND COMMUNICATION FAILURES
An invalid sensor or bad quality input shall select a documented fallback and issue an
operator-visible alarm.
A stale value timer of 5 minutes detects an unchanged value, selects the fallback, and recovery
occurs only after fresh data is valid.
On communications loss or BACnet timeout, the controller enters local mode fallback and raises
a communications alarm. Communications recovery occurs after the network is restored.

OVERRIDES, RESTART, AND ACTUATORS
A manual override follows an explicit priority and arbitration table. The override indication
is displayed. On release, control returns to automatic in a bumpless manner.
Following a power cycle or warm restart, initialization holds outputs in a safe off state. Timer
state is restored per policy, and the controlled restart sequence applies a startup delay.
An actuator failure or command-feedback disagreement starts a feedback proof timeout, selects a
safe-position fallback, and raises an actuator alarm. Actuator recovery requires feedback to
return and a reset.
The fault clears when its clear criteria have persisted. A manual reset is required for latched
faults, followed by a controlled recovery and bumpless resume.

LIFE SAFETY AND FAN PROOF
A fire alarm or smoke detector input has highest priority override. On smoke alarm, the supply
fan is commanded off and the outdoor-air damper is closed; fire/smoke requires manual reset.
A duct high-pressure trip immediately shuts down the fan, latches an alarm, and permits restart
only after a manual reset.
If supply fan proof fails after a 30 second proof delay, coils are disabled and dampers close,
the supply fan alarm is issued, and supply fan recovery occurs when proof returns and is reset.

ECONOMIZER AND LOW LIMITS
The economizer enable and disable criteria include an economizer high limit, minimum outdoor
air ventilation, and integrated cooling. An invalid economizer temperature sensor selects a
documented fallback.
At the mixed-air low limit, the outdoor-air damper is limited closed and the heating coil valve
opens. The mixed-air low-limit stage escalates to a freeze alarm.

PLANT AND COIL COORDINATION
When the heating plant is unavailable, the heating-plant request remains visible, the plant
fallback closes or limits the coil command, and a plant alarm is qualified. Plant recovery occurs
when the plant is available and restored.
Simultaneous heating and cooling is prevented by a heating/cooling deadband interlock. Heating
coil and cooling coil commands have maximum limits and are bounded.

FREEZE, RELIEF, AND AIRFLOW STATIONS
Freeze protection defines every stage threshold. During freeze protection the fan stops and the
damper closes; during freeze protection the heating coil valve commands fully open. Freeze
protection is latched and requires manual reset; freeze protection recovery restarts only after
the fault clears.
A return fan proof failure or feedback fault selects a building-pressure fallback, raises a
return fan alarm, and return fan recovery requires proof to restore and reset.
An airflow station invalid or stale failure selects a static-pressure fallback and raises an
airflow station alarm.
""".strip()


def test_rich_sequence_mentions_every_ahu_scenario_but_still_requires_review() -> None:
    document = parse_sequence_document(
        RICH_AHU_SEQUENCE.encode(),
        "ahu-sequence.md",
        "text/markdown",
    )
    result = CtrlFlowLibrary().reconcile_sequence(AHU_TEMPLATE, {}, document)

    missing = {
        scenario["id"]: scenario["missing_facets"]
        for scenario in result["scenarios"]
        if scenario["coverage_status"] != "all-facets-mentioned"
    }
    assert missing == {}
    assert result["all_facets_mentioned_count"] == result["scenario_count"] == 19
    assert result["language_coverage_complete"] is True
    assert result["gate"] == "engineer-review-required"
    assert result["ready_for_code_generation"] is False
    assert result["semantic_validation_complete"] is False
    assert result["engineer_review_required"] is True
    assert result["source_document"]["sha256"] == document.sha256
    evidence = result["scenarios"][0]["facets"][0]["evidence"][0]
    assert 0 <= evidence["start"] < evidence["end"] <= len(document.text)
    assert len(evidence["excerpt"]) < 400


def test_thin_sequence_exposes_missing_safety_degraded_and_recovery_language() -> None:
    document = parse_sequence_document(
        b"During occupied operation, the supply fan shall run.",
        "thin-sequence.txt",
        "text/plain",
    )
    result = CtrlFlowLibrary().reconcile_sequence(AHU_TEMPLATE, {}, document)

    by_id = {scenario["id"]: scenario for scenario in result["scenarios"]}
    assert by_id["normal-operation"]["coverage_status"] == "partial"
    assert by_id["fire-smoke"]["coverage_status"] == "not-mentioned"
    assert by_id["freeze-protection"]["coverage_status"] == "not-mentioned"
    assert by_id["communications-loss"]["coverage_status"] == "not-mentioned"
    assert result["language_coverage_complete"] is False
    assert result["missing_facet_count"] > 50
    assert result["gate"] == "blocked-missing-or-partial-sequence-language"


def test_topic_like_words_do_not_count_as_life_safety_behavior() -> None:
    document = parse_sequence_document(
        b"The cabinet uses fireproof insulation and a smoke-colored finish.",
        "materials.txt",
        "text/plain",
    )
    result = CtrlFlowLibrary().reconcile_sequence(AHU_TEMPLATE, {}, document)
    fire_smoke = next(item for item in result["scenarios"] if item["id"] == "fire-smoke")

    assert fire_smoke["coverage_status"] == "not-mentioned"
    assert fire_smoke["mentioned_facet_count"] == 0


def test_life_safety_words_do_not_satisfy_unrelated_generic_facets() -> None:
    document = parse_sequence_document(
        (
            b"On smoke alarm, shut down the AHU, close the outdoor air damper, and keep "
            b"the alarm active until manual reset."
        ),
        "smoke-only.txt",
        "text/plain",
    )
    result = CtrlFlowLibrary().reconcile_sequence(AHU_TEMPLATE, {}, document)
    by_id = {scenario["id"]: scenario for scenario in result["scenarios"]}

    assert by_id["fire-smoke"]["coverage_status"] == "partial"
    assert by_id["unoccupied-shutdown"]["mentioned_facet_count"] == 0
    assert by_id["sensor-invalid"]["mentioned_facet_count"] == 0
    assert by_id["actuator-failure"]["mentioned_facet_count"] == 0


def test_context_scoping_skips_earlier_unrelated_match_and_keeps_real_one() -> None:
    document = parse_sequence_document(
        (
            b"On fire alarm, issue an alarm. If the sensor is invalid, select a fallback "
            b"and issue an operator-visible alarm."
        ),
        "scoped-evidence.txt",
        "text/plain",
    )
    result = CtrlFlowLibrary().reconcile_sequence(AHU_TEMPLATE, {}, document)
    sensor_invalid = next(
        scenario for scenario in result["scenarios"] if scenario["id"] == "sensor-invalid"
    )
    by_facet = {facet["id"]: facet for facet in sensor_invalid["facets"]}

    assert by_facet["invalid-detection"]["mentioned"] is True
    assert by_facet["fallback"]["mentioned"] is True
    assert by_facet["operator-visibility"]["mentioned"] is True
    assert by_facet["operator-visibility"]["evidence"][0]["start"] > document.text.index(
        "sensor is invalid"
    )
    assert (
        by_facet["operator-visibility"]["evidence"][0]["scope_evidence"]["matched_text"]
        == "invalid"
    )


def test_temporal_math_and_actions_are_extracted_as_review_candidates() -> None:
    sequence = """
If mixed-air temperature falls below 38 °F for 5 minutes, limit the outdoor-air
damper to 20% and command the heating coil valve to 100%.
Automatically recover when mixed-air temperature rises above 42 °F for 2 minutes.
If duct static pressure exceeds 1.5 in. w.c. for 10 seconds, stop the supply fan and
latch the alarm until manual reset.
After a short delay, restart the system as required.
""".strip()
    document = parse_sequence_document(sequence.encode(), "numeric-sequence.txt")
    result = CtrlFlowLibrary().reconcile_sequence(AHU_TEMPLATE, {}, document)
    candidates = result["requirement_candidates"]

    assert candidates["duration_count"] == 3
    assert candidates["threshold_count"] == 3
    assert candidates["action_count"] >= 5
    assert candidates["ready_for_graph_generation"] is False
    assert candidates["approval_required"] is True

    thresholds = {
        (item["canonical"]["value"], item["canonical"]["unit"]): item
        for item in candidates["quantities"]
        if item["kind"] == "threshold"
    }
    assert thresholds[(38.0, "degF")]["comparison"] == "lt"
    assert thresholds[(38.0, "degF")]["input_point_candidates"] == ["MixedAirTemp"]
    assert thresholds[(42.0, "degF")]["comparison"] == "gt"
    assert thresholds[(1.5, "inH2O")]["comparison"] == "gt"
    assert thresholds[(1.5, "inH2O")]["input_point_candidates"] == ["DuctStatic"]

    durations = {
        item["canonical"]["value"]: item
        for item in candidates["quantities"]
        if item["kind"] == "duration"
    }
    assert set(durations) == {120.0, 300.0, 10.0}
    assert all(item["timing_relation"] == "persistence" for item in durations.values())
    assert all(item["point_binding_status"] == "not-applicable" for item in durations.values())
    assert all(item["condition_quantity_candidate_id"] for item in durations.values())

    command_values = [item for item in candidates["quantities"] if item["kind"] == "command-value"]
    assert {(item["canonical"]["value"], item["canonical"]["unit"]) for item in command_values} == {
        (20.0, "%"),
        (100.0, "%"),
    }
    assert {tuple(item["input_point_candidates"]) for item in command_values} == {
        ("OutdoorDamperCommand",),
        (),
    }
    assert all(item["action_candidate_id"] for item in command_values)

    numeric_relationships = [
        item
        for item in candidates["relationships"]
        if item["shape"] == "numeric-condition-to-actions"
    ]
    assert len(numeric_relationships) == 2
    assert all(item["threshold_candidate_ids"] for item in numeric_relationships)
    assert all(item["duration_candidate_ids"] for item in numeric_relationships)
    assert all(item["action_candidate_ids"] for item in numeric_relationships)

    policies = {item["policy"] for item in candidates["policies"]}
    assert {"latched", "manual-reset"} <= policies
    unresolved = {item["kind"] for item in candidates["unresolved"]}
    assert {"non-numeric-delay", "external-policy"} <= unresolved
    assert all(
        item["source"]["sha256"] == document.sha256
        for group in ("quantities", "actions", "policies", "unresolved")
        for item in candidates[group]
    )


def test_unknown_future_scenario_fails_closed_without_a_coverage_rule() -> None:
    brief = CtrlFlowLibrary().programming_brief(AHU_TEMPLATE, {})
    brief["qualification_plan"]["scenarios"] = [
        {
            "id": "future-hazard",
            "title": "Future hazard",
            "level": "required",
            "reason": "New hazards need an audited deterministic rule.",
        }
    ]
    document = parse_sequence_document(b"Future hazard is fully handled.", "future.txt")
    result = CtrlFlowSequenceReconciler().reconcile(brief, document)

    assert result["coverage_rule_missing_count"] == 1
    assert result["language_coverage_complete"] is False
    assert result["scenarios"][0]["coverage_status"] == "coverage-rule-missing"


def test_uploaded_sequence_document_uses_the_same_reconciliation_boundary(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(tmp_path / "runs"))
    response = client.post(
        f"/api/library/ctrl-flow/templates/{AHU_TEMPLATE}/inspect-sequence",
        data={"selections": "{}"},
        files={
            "sequence_document": (
                "ahu-sequence.md",
                RICH_AHU_SEQUENCE.encode(),
                "text/markdown",
            )
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema"] == "bactalk.ctrl-flow-sequence-reconciliation/v1"
    assert payload["source_document"]["filename"] == "ahu-sequence.md"
    assert payload["scenario_count"] == 19
    assert payload["language_coverage_complete"] is True
    assert payload["ready_for_code_generation"] is False
    assert payload["requirement_candidates"]["schema"] == (
        "bactalk.sequence-requirement-candidates/v1"
    )
    assert payload["requirement_candidates"]["ready_for_graph_generation"] is False
