import json

import pytest
from pydantic import ValidationError

from bactalk.deliverables import build_deliverable_package
from bactalk.demo import demo_job
from bactalk.domain import DeliverableRequirements, HistoryRequirement, JobSpec, ShopProfile
from bactalk.sequences.g36_vav import build_g36_vav_reheat
from bactalk.simulator import run_acceptance_suite


def test_declared_deliverable_requirements_are_rendered_without_target_claims() -> None:
    job = demo_job()
    graph = build_g36_vav_reheat(job)
    report = run_acceptance_suite(graph, job)

    package = build_deliverable_package(job, graph, report)
    files = {item.relative_path: item.content for item in package.artifacts}
    alarms = json.loads(files["alarms.json"])
    schedules = json.loads(files["schedules.json"])
    histories = json.loads(files["histories.json"])
    graphics = json.loads(files["graphics-model.json"])
    graphics_plan = json.loads(files["niagara-graphics-plan.json"])
    alarm_plan = json.loads(files["niagara-alarm-plan.json"])

    assert alarms["status"] == "requirements_complete"
    assert alarms["alarms"][0]["alarm_class"] == "HVAC-Critical"
    assert alarms["alarms"][0]["niagara_alarm_extension"] == "alarm:BAlarmSourceExt"
    assert alarm_plan["extensions"][0]["algorithm"]["type"] == "boolean_change_of_state"
    assert alarm_plan["extensions"][0]["point_ord"] == (
        "station:|slot:/Config/Drivers/BACnetNetwork/ExampleCampus/"
        "VAV_12/HighZoneTempAlarm"
    )
    assert alarm_plan["alarm_class_policy_compiled"] is False
    assert b"new BAlarmSourceExt()" in files["BactalkAlarmInstaller_VAV_12.java"]
    binding_plan = json.loads(files["niagara-point-bindings.json"])
    assert binding_plan["binding_count"] == 0
    assert binding_plan["unbound_mapped_points"] == [
        "DamperCommand",
        "ValveCommand",
        "ZoneTemp",
    ]
    assert schedules["status"] == "requirements_complete"
    assert schedules["definitions"][0]["timezone"] == "America/New_York"
    assert package.manifest["coverage"]["schedules"]["target_compiled"] is True
    assert histories["status"] == "requirements_complete"
    assert histories["niagara_history_extensions_emitted"] is True
    assert histories["definitions"][0]["target_compiled"] is True
    assert package.manifest["coverage"]["histories"]["target_compiled"] is True
    assert graphics["requirements_status"] == "requirements_complete"
    assert graphics["niagara_px_emitted"] is False
    assert graphics_plan["emitted_px_count"] == 0
    assert graphics_plan["views"][0]["status"] == "blocked"
    assert package.manifest["deployment_ready"] is False


def test_deliverable_requirement_references_must_resolve_to_job_points() -> None:
    payload = demo_job().model_dump(mode="json")
    payload["deliverables"]["histories"][0]["point"] = "MissingPoint"

    with pytest.raises(ValidationError, match="unknown point MissingPoint"):
        JobSpec.model_validate(payload)


def test_history_modes_reject_mismatched_parameters() -> None:
    with pytest.raises(ValidationError, match="requires interval_seconds only"):
        HistoryRequirement(
            point="ZoneTemp",
            mode="fixed_interval",
            cov_tolerance=0.5,
            retention_days=30,
        )


def test_deliverable_schema_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DeliverableRequirements.model_validate({"schema_version": "1.0", "magic": True})


def test_shop_profile_normalizes_exact_semantic_component_ords() -> None:
    profile = ShopProfile(
        name="Shop",
        version="1",
        station_folder="Config\\ControlPrograms",
        niagara_site_ord="slot:/Config/Sites/Main",
        niagara_equipment_ord="station:|slot:/Config/Equipment/AHU_1",
    )

    assert profile.station_folder == "Config/ControlPrograms"
    assert profile.niagara_site_ord == "station:|slot:/Config/Sites/Main"
    assert profile.niagara_equipment_ord == "station:|slot:/Config/Equipment/AHU_1"


@pytest.mark.parametrize(
    "field,value",
    [
        ("station_folder", "Config/Bad Folder"),
        ("niagara_site_ord", "station:|slot:/Config/Sites/Main?bad=true"),
        ("niagara_equipment_ord", "station:|slot:/Config/../Equipment/AHU_1"),
    ],
)
def test_shop_profile_rejects_ambiguous_component_paths(field: str, value: str) -> None:
    payload = {"name": "Shop", "version": "1", field: value}
    with pytest.raises(ValidationError):
        ShopProfile.model_validate(payload)
