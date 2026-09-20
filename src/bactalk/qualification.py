from __future__ import annotations

from typing import Any

from bactalk.domain import (
    AcceptanceCase,
    QualificationCategory,
    QualificationLevel,
    QualificationProfile,
    QualificationRequirement,
    ScenarioResult,
)


def _requirement(
    category: QualificationCategory,
    description: str,
    *,
    level: QualificationLevel = QualificationLevel.REQUIRED,
    fault: bool = False,
    recovery: bool = False,
) -> QualificationRequirement:
    return QualificationRequirement(
        category=category,
        level=level,
        description=description,
        fault_required=fault,
        recovery_required=recovery,
    )


_CONDITIONAL_COMMON = [
    _requirement(
        QualificationCategory.SENSOR_INVALID,
        "Invalid sensor quality selects an explicit safe fallback and alarm policy.",
        level=QualificationLevel.CONDITIONAL,
        fault=True,
    ),
    _requirement(
        QualificationCategory.SENSOR_STALE,
        "Stale telemetry is detected and handled without silently trusting the held value.",
        level=QualificationLevel.CONDITIONAL,
        fault=True,
    ),
    _requirement(
        QualificationCategory.COMMUNICATIONS_LOSS,
        "Loss of the upstream/downstream communications dependency reaches a defined state.",
        level=QualificationLevel.CONDITIONAL,
        fault=True,
    ),
    _requirement(
        QualificationCategory.MANUAL_OVERRIDE,
        "Manual and emergency overrides have explicit precedence, indication, and "
        "release behavior.",
        level=QualificationLevel.CONDITIONAL,
    ),
    _requirement(
        QualificationCategory.POWER_CYCLE,
        "Initialization after restart preserves safety and avoids unintended commands.",
        level=QualificationLevel.CONDITIONAL,
    ),
]


BUILTIN_PROFILES: dict[str, QualificationProfile] = {
    "G36_VAV_REHEAT": QualificationProfile(
        id="terminal-vav-reheat-safety-v1",
        version="1.0.0",
        source="BACTalk baseline derived from the installed bounded G36 terminal pack",
        requirements=[
            _requirement(
                QualificationCategory.NORMAL_OPERATION,
                "Heating and cooling demand drive bounded terminal outputs.",
            ),
            _requirement(
                QualificationCategory.UNOCCUPIED_SHUTDOWN,
                "Unoccupied mode reaches the declared minimum/safe terminal state.",
            ),
            _requirement(
                QualificationCategory.MODE_TRANSITION,
                "Heating, deadband, cooling, and occupancy transitions are exercised.",
            ),
            _requirement(
                QualificationCategory.OUTPUT_BOUNDS,
                "Damper and valve commands remain inside configured limits.",
            ),
            _requirement(
                QualificationCategory.ACTUATOR_PROOF_FAILURE,
                "Damper or reheat actuator failure behavior is defined when proof/feedback exists.",
                level=QualificationLevel.CONDITIONAL,
                fault=True,
            ),
            *_CONDITIONAL_COMMON,
        ],
    ),
    "CUSTOM_AHU_SAFETY_COOLING": QualificationProfile(
        id="ahu-safety-cooling-v1",
        version="1.0.0",
        source="BACTalk AHU safety baseline; project hazards remain contractor-authoritative",
        requirements=[
            _requirement(
                QualificationCategory.NORMAL_OPERATION,
                "Occupied enable and cooling control produce bounded commands.",
            ),
            _requirement(
                QualificationCategory.UNOCCUPIED_SHUTDOWN,
                "Unoccupied mode shuts down commanded equipment.",
            ),
            _requirement(
                QualificationCategory.HIGH_PRESSURE_SHUTDOWN,
                "High duct pressure overrides normal fan command and alarms.",
            ),
            _requirement(
                QualificationCategory.OUTPUT_BOUNDS,
                "All analog commands remain within configured physical bounds.",
            ),
            _requirement(
                QualificationCategory.FIRE_SMOKE_SHUTDOWN,
                "Fire/smoke interlocks drive the project-specific shutdown or smoke-control state.",
                level=QualificationLevel.CONDITIONAL,
            ),
            _requirement(
                QualificationCategory.FREEZE_PROTECTION,
                "Every specified freeze-protection stage and reset path is exercised.",
                level=QualificationLevel.CONDITIONAL,
            ),
            _requirement(
                QualificationCategory.ACTUATOR_PROOF_FAILURE,
                "Fan/valve/damper proof loss asserts the defined fallback and alarm.",
                level=QualificationLevel.CONDITIONAL,
                fault=True,
            ),
            *_CONDITIONAL_COMMON,
        ],
    ),
    "EXHAUST_FAN_PROOF": QualificationProfile(
        id="exhaust-fan-proof-safety-v1",
        version="1.0.0",
        source="BACTalk exhaust proof pack",
        requirements=[
            _requirement(
                QualificationCategory.NORMAL_OPERATION,
                "Enable produces a fan command without a nuisance proof alarm.",
            ),
            _requirement(
                QualificationCategory.ACTUATOR_PROOF_FAILURE,
                "Loss of fan proof beyond the configured delay asserts the alarm.",
                fault=True,
            ),
            _requirement(
                QualificationCategory.ALARM_BEHAVIOR,
                "Proof alarm delay, assertion, and clear behavior are explicit.",
            ),
            _requirement(
                QualificationCategory.RECOVERY,
                "Restored proof clears the alarm while preserving the commanded operating state.",
                fault=True,
                recovery=True,
            ),
            _requirement(
                QualificationCategory.FIRE_SMOKE_SHUTDOWN,
                "Fire/smoke interlock behavior is defined when this fan participates in "
                "life safety.",
                level=QualificationLevel.CONDITIONAL,
            ),
            *_CONDITIONAL_COMMON,
        ],
    ),
    "AHU_DUCT_STATIC_PI": QualificationProfile(
        id="ahu-duct-static-loop-safety-v1",
        version="1.0.0",
        source="BACTalk duct-static PI pack",
        requirements=[
            _requirement(
                QualificationCategory.DISABLED_SHUTDOWN, "Disabled loop commands zero output."
            ),
            _requirement(
                QualificationCategory.NORMAL_OPERATION,
                "Loop responds in the correct direction below and above setpoint.",
            ),
            _requirement(
                QualificationCategory.OUTPUT_BOUNDS,
                "Fan-speed command remains between zero and one hundred percent.",
            ),
            _requirement(
                QualificationCategory.ACTUATOR_PROOF_FAILURE,
                "Fan proof loss disables or limits the loop according to the project sequence.",
                level=QualificationLevel.CONDITIONAL,
                fault=True,
            ),
            *_CONDITIONAL_COMMON,
        ],
    ),
    "TWO_PUMP_AVAILABILITY_SELECTOR": QualificationProfile(
        id="two-pump-selector-safety-v1",
        version="1.0.0",
        source="BACTalk fail-closed duty/standby selector",
        requirements=[
            _requirement(
                QualificationCategory.DISABLED_SHUTDOWN, "Disabled system commands neither pump."
            ),
            _requirement(
                QualificationCategory.NORMAL_OPERATION,
                "Selected available lead pump runs without commanding standby.",
            ),
            _requirement(
                QualificationCategory.EQUIPMENT_UNAVAILABLE,
                "Lead unavailability transfers command to the available standby pump.",
                fault=True,
            ),
            _requirement(
                QualificationCategory.ALL_EQUIPMENT_UNAVAILABLE,
                "Loss of all available pumps fails closed and asserts the no-pump alarm.",
                fault=True,
            ),
            _requirement(
                QualificationCategory.LEAD_LAG_ROTATION,
                "Rotation and restart persistence are exercised when runtime/cycle rotation "
                "is used.",
                level=QualificationLevel.CONDITIONAL,
            ),
            _requirement(
                QualificationCategory.RECOVERY,
                "A recovered pump returns through the declared reset/reselection policy.",
                level=QualificationLevel.CONDITIONAL,
                fault=True,
                recovery=True,
            ),
            *_CONDITIONAL_COMMON,
        ],
    ),
}


def builtin_qualification_profile(sequence_family: str | None) -> QualificationProfile | None:
    if sequence_family is None:
        return None
    return BUILTIN_PROFILES.get(sequence_family)


def _case_faults(case: AcceptanceCase) -> list[Any]:
    if case.timeline:
        return [fault for phase in case.timeline for fault in phase.faults]
    return list(case.faults)


def _case_has_recovery(case: AcceptanceCase) -> bool:
    fault_seen = False
    for phase in case.timeline:
        if phase.faults:
            fault_seen = True
        elif fault_seen and phase.expectations:
            return True
    return False


def assess_qualification_matrix(
    *,
    sequence_family: str | None,
    cases: list[AcceptanceCase],
    results: list[ScenarioResult],
    profile: QualificationProfile | None = None,
) -> dict[str, Any]:
    selected = profile or builtin_qualification_profile(sequence_family)
    if selected is None:
        return {
            "schema": "bactalk-qualification-matrix/v1",
            "sequence_family": sequence_family,
            "profile": None,
            "required_passed": 0,
            "required_count": 0,
            "conditional_addressed": 0,
            "conditional_count": 0,
            "engineering_matrix_complete": False,
            "requirements": [],
            "blockers": [
                "No built-in or contractor-supplied qualification profile defines the required "
                "normal, fault, safety, and recovery evidence for this sequence."
            ],
        }

    result_by_name = {result.name: result for result in results}
    rows: list[dict[str, Any]] = []
    blockers: list[str] = []
    for requirement in selected.requirements:
        tagged = [case for case in cases if requirement.category in case.qualifications]
        passing = [
            case
            for case in tagged
            if result_by_name.get(case.name) is not None and result_by_name[case.name].passed
        ]
        has_fault = any(_case_faults(case) for case in passing)
        has_recovery = any(_case_has_recovery(case) for case in passing)
        if requirement.level == QualificationLevel.NOT_APPLICABLE:
            status = "not_applicable"
            reason = "Profile explicitly marks this category not applicable."
        elif tagged and not passing:
            status = "failed"
            reason = "Tagged evidence exists, but one or more required assertions failed."
        elif passing and requirement.fault_required and not has_fault:
            status = "insufficient_fault_evidence"
            reason = "Passing cases did not inject a typed fault as required."
        elif passing and requirement.recovery_required and not has_recovery:
            status = "insufficient_recovery_evidence"
            reason = "Passing cases did not include an asserted no-fault recovery phase."
        elif passing:
            status = "passed"
            reason = "Passing tagged acceptance evidence satisfies this engineering requirement."
        elif requirement.level == QualificationLevel.CONDITIONAL:
            status = "needs_applicability_review"
            reason = (
                "Contractor must supply evidence or explicitly mark this condition not applicable."
            )
        else:
            status = "missing"
            reason = "No passing acceptance case is tagged for this required category."
        row = {
            "category": requirement.category.value,
            "level": requirement.level.value,
            "description": requirement.description,
            "fault_required": requirement.fault_required,
            "recovery_required": requirement.recovery_required,
            "status": status,
            "reason": reason,
            "evidence_cases": [case.name for case in passing],
        }
        rows.append(row)
        if status not in {"passed", "not_applicable"}:
            blockers.append(f"{requirement.category.value}: {reason}")

    required = [row for row in rows if row["level"] == QualificationLevel.REQUIRED.value]
    conditional = [row for row in rows if row["level"] == QualificationLevel.CONDITIONAL.value]
    required_passed = sum(row["status"] in {"passed", "not_applicable"} for row in required)
    conditional_addressed = sum(
        row["status"] in {"passed", "not_applicable"} for row in conditional
    )
    return {
        "schema": "bactalk-qualification-matrix/v1",
        "sequence_family": sequence_family,
        "profile": {
            "id": selected.id,
            "version": selected.version,
            "source": selected.source,
        },
        "required_passed": required_passed,
        "required_count": len(required),
        "conditional_addressed": conditional_addressed,
        "conditional_count": len(conditional),
        "engineering_matrix_complete": not blockers,
        "requirements": rows,
        "blockers": blockers,
        "interpretation": (
            "The declared engineering safety matrix is complete for this profile."
            if not blockers
            else "Normal acceptance can pass while safety-profile evidence remains incomplete."
        ),
    }
