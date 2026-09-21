from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bactalk.api import create_app
from bactalk.integrations.ctrl_flow import CtrlFlowError, CtrlFlowLibrary
from bactalk.stack_lock import locked_revision

AHU_TEMPLATE = "Buildings.Templates.AirHandlersFans.VAVMultiZone"
DRAW_THROUGH_SELECTION = "Buildings.Templates.AirHandlersFans.VAVMultiZone.fanSupDra-fanSupDra"
NO_FAN = "Buildings.Templates.Components.Fans.None"
BLOW_THROUGH_SELECTION = "Buildings.Templates.AirHandlersFans.VAVMultiZone.fanSupBlo-fanSupBlo"
SINGLE_FAN = "Buildings.Templates.Components.Fans.SingleVariable"
COOLING_ONLY_TEMPLATE = "Buildings.Templates.ZoneEquipment.VAVBoxCoolingOnly"
REHEAT_TEMPLATE = "Buildings.Templates.ZoneEquipment.VAVBoxReheat"
CO2_SELECTION = (
    "Buildings.Templates.ZoneEquipment.Components.Interfaces.PartialControllerVAVBox."
    "have_CO2Sen-ctl.have_CO2Sen"
)


def test_ctrl_flow_adapter_does_not_create_a_capability_import_cycle() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from bactalk.projects import ProjectSpec; "
                "from bactalk.capabilities import CapabilityRegistry; "
                "assert CapabilityRegistry().packs"
            ),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_catalog_exposes_real_upstream_linkage_schema() -> None:
    catalog = CtrlFlowLibrary().catalog()

    assert catalog["revision"] == locked_revision("ctrl-flow")
    assert catalog["template_count"] == 3
    assert catalog["option_count"] == 2_593
    assert len(catalog["snapshot_sha256"]) == 64
    ahu = next(template for template in catalog["templates"] if template["id"] == AHU_TEMPLATE)
    assert ahu["visible_option_count"] == 589
    assert ahu["conditional_option_count"] == 174
    assert ahu["product_status"] == "upstream-interpreter-wired"


def test_configure_runs_upstream_conditional_option_interpreter() -> None:
    library = CtrlFlowLibrary()
    baseline = library.schema(AHU_TEMPLATE)
    baseline_instances = {field["instance_path"] for field in baseline["fields"]}

    assert "fanSupDra" in baseline_instances
    assert "fanSupBlo" not in baseline_instances
    assert baseline["visible_field_count"] == 11
    assert baseline["evaluated_value_count"] >= 150

    configured = library.configure(AHU_TEMPLATE, {DRAW_THROUGH_SELECTION: NO_FAN})
    configured_by_instance = {field["instance_path"]: field for field in configured["fields"]}

    assert configured["accepted_selection_count"] == 1
    assert configured["rejected_selection_count"] == 0
    assert configured_by_instance["fanSupDra"]["value"] == NO_FAN
    assert "fanSupBlo" in configured_by_instance
    assert configured["downstream_boundary"]["engineering_brief_ready"] is True
    assert configured["downstream_boundary"]["niagara_code_generated"] is False
    assert configured["safety"]["live_writes_enabled"] is False


def test_hidden_or_unknown_selections_are_rejected_without_applying_them() -> None:
    configured = CtrlFlowLibrary().configure(AHU_TEMPLATE, {BLOW_THROUGH_SELECTION: NO_FAN})

    assert configured["accepted_selection_count"] == 0
    assert configured["rejected_selection_count"] == 1
    assert configured["downstream_boundary"]["engineering_brief_ready"] is False


def test_valid_blow_through_fan_pair_survives_reciprocal_upstream_visibility() -> None:
    configured = CtrlFlowLibrary().configure(
        AHU_TEMPLATE,
        {
            DRAW_THROUGH_SELECTION: NO_FAN,
            BLOW_THROUGH_SELECTION: SINGLE_FAN,
        },
    )

    assert configured["accepted_selection_count"] == 2
    assert configured["rejected_selection_count"] == 0
    assert configured["selections"][DRAW_THROUGH_SELECTION] == NO_FAN
    assert configured["selections"][BLOW_THROUGH_SELECTION] == SINGLE_FAN
    visible_instances = {field["instance_path"] for field in configured["fields"]}
    assert "fanSupBlo" in visible_instances
    assert "fanSupDra" not in visible_instances

    brief = CtrlFlowLibrary().programming_brief(
        AHU_TEMPLATE,
        {
            BLOW_THROUGH_SELECTION: SINGLE_FAN,
            DRAW_THROUGH_SELECTION: NO_FAN,
        },
    )
    component_ids = {component["id"] for component in brief["components"]}
    assert "blow-through-supply-fan" in component_ids
    assert "draw-through-supply-fan" not in component_ids


def test_choice_outside_upstream_choice_set_fails_closed() -> None:
    with pytest.raises(CtrlFlowError, match="outside the upstream choice set"):
        CtrlFlowLibrary().configure(AHU_TEMPLATE, {DRAW_THROUGH_SELECTION: "Bad.Fan"})


def test_ahu_programming_brief_expands_design_into_points_scenarios_and_gates() -> None:
    brief = CtrlFlowLibrary().programming_brief(AHU_TEMPLATE, {})

    assert brief["status"] == "engineering-brief-ready"
    assert brief["design_binding"]["equipment_family"] == "ahu.multi-zone-vav"
    assert brief["design_binding"]["controller_id"] == "AHUs.MultiZone.VAV.Controller"
    point_ids = {point["id"] for point in brief["point_requirements"]["points"]}
    assert {
        "SupplyFanCommand",
        "DuctHighPressure",
        "MinimumOutdoorAirflow",
        "ReturnFanCommand",
        "CoolingValveCommand",
        "FreezeProtectionStage",
    } <= point_ids
    scenario_ids = {scenario["id"] for scenario in brief["qualification_plan"]["scenarios"]}
    assert {"fire-smoke", "freeze-protection", "duct-high-pressure", "recovery"} <= (scenario_ids)
    for scenario in brief["qualification_plan"]["scenarios"]:
        io_contract = scenario["io_contract"]
        assert io_contract["status"] == "ready"
        assert io_contract["input_point_candidates"]
        assert io_contract["output_point_candidates"]
        assert set(io_contract["input_point_candidates"]) <= point_ids
        assert set(io_contract["output_point_candidates"]) <= point_ids
    fire_smoke = next(
        scenario
        for scenario in brief["qualification_plan"]["scenarios"]
        if scenario["id"] == "fire-smoke"
    )
    assert fire_smoke["io_contract"]["input_point_candidates"] == ["FireSmokeShutdown"]
    assert fire_smoke["io_contract"]["output_point_candidates"] == [
        "SupplyFanCommand",
        "OutdoorDamperCommand",
    ]
    assert brief["qualification_plan"]["execution_status"] == "not-run"
    assert brief["capability_alignment"]["reference_controller_available"] is True
    assert brief["capability_alignment"]["complete_niagara_job_ready"] is False
    assert brief["safety"]["live_writes_enabled"] is False


def test_terminal_briefs_are_equipment_specific_and_optional_sensors_are_conditional() -> None:
    library = CtrlFlowLibrary()
    cooling = library.programming_brief(COOLING_ONLY_TEMPLATE, {CO2_SELECTION: True})
    reheat = library.programming_brief(REHEAT_TEMPLATE, {})

    cooling_points = {point["id"] for point in cooling["point_requirements"]["points"]}
    reheat_points = {point["id"] for point in reheat["point_requirements"]["points"]}
    assert {"ZoneCO2", "ZoneCO2Setpoint"} <= cooling_points
    assert "ValveCommand" not in cooling_points
    assert {"ValveCommand", "DischargeAirTemp", "HotWaterRequest"} <= reheat_points
    assert {
        "SensorQualityValid",
        "CommunicationsHealthy",
        "ManualOverrideActive",
        "PowerRestart",
        "ActuatorProof",
        "FaultReset",
    } <= cooling_points
    for brief in (cooling, reheat):
        point_ids = {point["id"] for point in brief["point_requirements"]["points"]}
        for scenario in brief["qualification_plan"]["scenarios"]:
            io_contract = scenario["io_contract"]
            assert io_contract["status"] == "ready"
            assert set(io_contract["input_point_candidates"]) <= point_ids
            assert set(io_contract["output_point_candidates"]) <= point_ids
    assert cooling["design_binding"]["controller_id"] == ("TerminalUnits.CoolingOnly.Controller")
    assert reheat["design_binding"]["controller_id"] == "TerminalUnits.Reheat.Controller"


def test_rejected_configuration_produces_a_blocked_programming_brief() -> None:
    brief = CtrlFlowLibrary().programming_brief(
        AHU_TEMPLATE,
        {BLOW_THROUGH_SELECTION: NO_FAN},
    )

    assert brief["status"] == "blocked"
    assert brief["release_blockers"][0].startswith("Resolve every rejected")


def test_ctrl_flow_product_api_catalog_schema_and_configuration(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))

    catalog = client.get("/api/library/ctrl-flow/templates")
    assert catalog.status_code == 200
    assert catalog.json()["option_count"] == 2_593

    schema = client.get(f"/api/library/ctrl-flow/templates/{AHU_TEMPLATE}/schema")
    assert schema.status_code == 200, schema.text
    assert schema.json()["visible_field_count"] == 11

    configured = client.post(
        f"/api/library/ctrl-flow/templates/{AHU_TEMPLATE}/configure",
        json={"selections": {DRAW_THROUGH_SELECTION: NO_FAN}},
    )
    assert configured.status_code == 200, configured.text
    assert configured.json()["accepted_selection_count"] == 1
    assert any(field["instance_path"] == "fanSupBlo" for field in configured.json()["fields"])

    brief = client.post(
        f"/api/library/ctrl-flow/templates/{REHEAT_TEMPLATE}/programming-brief",
        json={"selections": {}},
    )
    assert brief.status_code == 200, brief.text
    assert brief.json()["point_requirements"]["required_count"] >= 20
    assert brief.json()["qualification_plan"]["scenario_count"] >= 10

    missing = client.get("/api/library/ctrl-flow/templates/Not.A.Template/schema")
    assert missing.status_code == 404
