from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bactalk.domain import PointSpec
from bactalk.intake import parse_sequence_document
from bactalk.integrations.ctrl_flow import CtrlFlowLibrary
from bactalk.integrations.ctrl_flow_planning import AHU_TEMPLATE
from bactalk.integrations.ctrl_flow_reconciliation import CtrlFlowPointReconciler
from bactalk.integrations.ctrl_flow_sequence import CtrlFlowSequenceReconciler

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = ROOT / ".bactalk/ctrl-flow-planning-evidence.json"
DRAW_THROUGH = "Buildings.Templates.AirHandlersFans.VAVMultiZone.fanSupDra-fanSupDra"
BLOW_THROUGH = "Buildings.Templates.AirHandlersFans.VAVMultiZone.fanSupBlo-fanSupBlo"
NO_FAN = "Buildings.Templates.Components.Fans.None"
SINGLE_FAN = "Buildings.Templates.Components.Fans.SingleVariable"


def _validate_brief(brief: dict[str, Any]) -> None:
    if brief["status"] != "engineering-brief-ready":
        raise RuntimeError("an upstream-visible selection produced a blocked programming brief")
    point_ids = [point["id"] for point in brief["point_requirements"]["points"]]
    scenario_ids = [item["id"] for item in brief["qualification_plan"]["scenarios"]]
    if len(point_ids) != len(set(point_ids)):
        raise RuntimeError("programming brief contains duplicate point requirements")
    if len(scenario_ids) != len(set(scenario_ids)):
        raise RuntimeError("programming brief contains duplicate scenario requirements")
    if not point_ids or not scenario_ids:
        raise RuntimeError("programming brief must contain points and scenarios")
    if brief["capability_alignment"]["complete_niagara_job_ready"]:
        raise RuntimeError("design configuration must not claim a complete Niagara job")
    if brief["safety"]["live_writes_enabled"]:
        raise RuntimeError("ctrl-flow planning must remain offline")


def main() -> int:
    library = CtrlFlowLibrary(ROOT)
    reconciler = CtrlFlowPointReconciler()
    sequence_reconciler = CtrlFlowSequenceReconciler()
    blank_sequence = parse_sequence_document(
        b"No project sequence language was supplied for this contract audit.",
        "coverage-audit.txt",
        "text/plain",
    )
    per_template: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "variant_count": 0,
            "minimum_required_points": None,
            "maximum_required_points": 0,
            "minimum_scenarios": None,
            "maximum_scenarios": 0,
        }
    )
    total_variants = 0
    point_contracts_proved = 0
    total_required_point_obligations = 0
    scenario_contracts_proved = 0
    for template in library.catalog()["templates"]:
        template_id = template["id"]
        for field in library.schema(template_id)["fields"]:
            values = [choice["value"] for choice in field.get("choices", [])]
            if not values:
                values = field.get("boolean_choices", [])
            for value in values:
                brief = library.programming_brief(
                    template_id,
                    {field["selection_path"]: value},
                )
                _validate_brief(brief)
                contractor_points = [
                    PointSpec(
                        name=requirement["id"],
                        label=requirement["label"],
                        data_type=requirement["data_type"],
                        role=requirement["role"],
                        units=requirement["units"],
                        default=(False if requirement["data_type"] == "boolean" else 0.0),
                    )
                    for requirement in brief["point_requirements"]["points"]
                    if requirement["required"]
                ]
                reconciliation = reconciler.reconcile(brief, contractor_points)
                if not reconciliation["ready_for_sequence_reconciliation"]:
                    raise RuntimeError(
                        "an exact generated point contract failed reconciliation: "
                        f"{reconciliation['blocking_issues']}"
                    )
                sequence_reconciliation = sequence_reconciler.reconcile(
                    brief,
                    blank_sequence,
                )
                if sequence_reconciliation["coverage_rule_missing_count"]:
                    raise RuntimeError(
                        "a generated scenario has no deterministic sequence-coverage rule"
                    )
                required_points = brief["point_requirements"]["required_count"]
                scenarios = brief["qualification_plan"]["scenario_count"]
                stats = per_template[template_id]
                stats["variant_count"] += 1
                stats["minimum_required_points"] = (
                    required_points
                    if stats["minimum_required_points"] is None
                    else min(stats["minimum_required_points"], required_points)
                )
                stats["maximum_required_points"] = max(
                    stats["maximum_required_points"], required_points
                )
                stats["minimum_scenarios"] = (
                    scenarios
                    if stats["minimum_scenarios"] is None
                    else min(stats["minimum_scenarios"], scenarios)
                )
                stats["maximum_scenarios"] = max(stats["maximum_scenarios"], scenarios)
                total_variants += 1
                point_contracts_proved += 1
                total_required_point_obligations += required_points
                scenario_contracts_proved += scenarios

    # The fan-position selectors form a reciprocal upstream dependency. Prove
    # that both request key orders produce the same valid blow-through design.
    blow_through_digests = set()
    for selections in (
        {DRAW_THROUGH: NO_FAN, BLOW_THROUGH: SINGLE_FAN},
        {BLOW_THROUGH: SINGLE_FAN, DRAW_THROUGH: NO_FAN},
    ):
        brief = library.programming_brief(AHU_TEMPLATE, selections)
        _validate_brief(brief)
        components = {item["id"] for item in brief["components"]}
        if "blow-through-supply-fan" not in components:
            raise RuntimeError("blow-through dependency pair was not preserved")
        if "draw-through-supply-fan" in components:
            raise RuntimeError("disabled draw-through fan remained in component inventory")
        blow_through_digests.add(brief["configuration_digest"])
    if len(blow_through_digests) != 1:
        raise RuntimeError("configuration digest depends on request key order")

    if total_variants != 44:
        raise RuntimeError(f"expected 44 pinned first-order variants, found {total_variants}")
    evidence = {
        "schema": "bactalk.ctrl-flow-planning-contract/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "passed": True,
        "template_count": len(per_template),
        "first_order_variant_count": total_variants,
        "point_contracts_proved": point_contracts_proved,
        "required_point_obligations_proved": total_required_point_obligations,
        "sequence_scenario_contracts_proved": scenario_contracts_proved,
        "reciprocal_fan_dependency_orders_proved": 2,
        "templates": dict(sorted(per_template.items())),
        "complete_niagara_job_ready": False,
        "live_writes_enabled": False,
        "policy": (
            "This proves deterministic design-to-brief expansion for every currently exposed "
            "first-order choice. It does not prove licensed Niagara runtime or field behavior."
        ),
    }
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = EVIDENCE_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(EVIDENCE_PATH)
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
