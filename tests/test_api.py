from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook

from bactalk.api import create_app
from bactalk.demo import demo_job, generalist_demo_job
from bactalk.projects import EquipmentRelationship, ProjectSpec

EXAMPLES = Path(__file__).parents[1] / "examples"


def _example_points_xlsx() -> bytes:
    source_rows = list(
        csv.reader((EXAMPLES / "vav-reheat-points.csv").read_text(encoding="utf-8").splitlines())
    )
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Point Schedule"
    sheet.append(["North Wing controls point schedule"])
    sheet.append(source_rows[0])
    for row in source_rows[1:]:
        sheet.append(row)
    target = io.BytesIO()
    workbook.save(target)
    return target.getvalue()


def test_review_api_flow(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))

    assert client.get("/api/health").json() == {"status": "ok", "mode": "offline-safe"}
    create_response = client.post("/api/runs/demo")
    assert create_response.status_code == 201
    run = create_response.json()
    run_id = run["id"]
    assert run["status"] == "ready_for_review"
    edge_manifest = client.get(f"/api/runs/{run_id}/volttron-manifest")
    assert edge_manifest.status_code == 200
    assert edge_manifest.json()["writes_enabled"] is False
    assert edge_manifest.json()["devices"][0]["mapped_points"] == 3
    nhaystack = client.get(f"/api/runs/{run_id}/nhaystack-manifest")
    assert nhaystack.status_code == 200
    assert nhaystack.json()["writes_enabled"] is False
    assert nhaystack.json()["point_count"] == len(demo_job().points)
    assert nhaystack.json()["tag_annotation_count"] == len(demo_job().points) + 2
    assert nhaystack.json()["existing_tag_overwrite_allowed"] is False
    bacnet_lab = client.get(f"/api/runs/{run_id}/bacnet-lab-manifest")
    assert bacnet_lab.status_code == 200
    assert bacnet_lab.json()["mode"] == "isolated-loopback"
    assert bacnet_lab.json()["devices"][0]["object_count"] == 3
    probe = client.post(f"/api/runs/{run_id}/bacnet-lab/probe")
    assert probe.status_code == 200, probe.text
    assert probe.json()["passed"] is True
    assert probe.json()["point_count"] == 3
    assert probe.json()["writes_performed"] is False
    assert probe.json()["live_network_routes_allowed"] is False
    assert client.get(f"/api/runs/{run_id}/environment-manifest").status_code == 404
    deliverables = client.get(f"/api/runs/{run_id}/deliverables")
    assert deliverables.status_code == 200
    assert deliverables.json()["deployment_ready"] is False
    assert len(deliverables.json()["artifacts"]) == 15
    alarm_plan = client.get(f"/api/runs/{run_id}/niagara-alarm-plan")
    assert alarm_plan.status_code == 200
    assert alarm_plan.json()["extensions"][0]["point"] == "HighZoneTempAlarm"
    assert alarm_plan.json()["live_station_modified"] is False
    graphics_model = client.get(f"/api/runs/{run_id}/graphics-model")
    assert graphics_model.status_code == 200
    assert graphics_model.json()["views"][0]["id"] == "VavOverview"
    graphics_plan = client.get(f"/api/runs/{run_id}/niagara-graphics-plan")
    assert graphics_plan.status_code == 200
    assert graphics_plan.json()["all_declared_views_target_compiled"] is False

    release = client.get(f"/api/runs/{run_id}/release-summary")
    assert release.status_code == 200
    assert release.json()["integrity"]["verified"] is True
    assert release.json()["behavior"]["passed"] is True
    assert release.json()["behavior"]["scenario_count"] == 5
    assert release.json()["deliverables"]["available"] is True
    assert len(release.json()["deliverables"]["artifacts"]) == 15
    assert release.json()["downloads"]["available"] is False
    assert release.json()["safety"]["live_writes_enabled"] is False

    assert client.get(f"/api/runs/{run_id}/export").status_code == 403
    assert client.get(f"/api/runs/{run_id}/review-bundle").status_code == 403
    approval = client.post(
        f"/api/runs/{run_id}/approve",
        json={"reviewer": "Alex Engineer"},
    )
    assert approval.status_code == 200
    assert approval.json()["status"] == "approved"

    approved_release = client.get(f"/api/runs/{run_id}/release-summary")
    assert approved_release.status_code == 200
    assert approved_release.json()["downloads"]["available"] is True
    assert approved_release.json()["downloads"]["target_url"].endswith("/export")
    assert approved_release.json()["downloads"]["review_bundle_url"].endswith(
        "/review-bundle"
    )

    export = client.get(f"/api/runs/{run_id}/export")
    assert export.status_code == 200
    assert export.content.startswith(b"PK")
    bundle = client.get(f"/api/runs/{run_id}/review-bundle")
    assert bundle.status_code == 200
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        assert "deliverables/alarms.json" in archive.namelist()
        assert "deliverables/schedules.json" in archive.namelist()
        assert "nhaystack/expected-readback.zinc" in archive.namelist()
        assert "nhaystack/BactalkHaystackTagInstaller_VAV_12.java" in archive.namelist()


def test_multipart_plant_controller_intake_builds_reviewable_source_package(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(tmp_path / "runs"))

    response = client.post(
        "/api/runs/import",
        data={
            "name": "Plant hold controller",
            "site": "Qualification lab",
            "equipment_name": "PlantHold",
            "sequence_family": "LBNL_PLANT_CONTROLLER",
            "sequence_library": "plant_controls",
            "controller_id": "Utilities.HoldReal",
            "execution_profile": "modelica_exact",
            "sequence_parameters": json.dumps({"dtHol": 3.0}),
            "acceptance_tests": json.dumps(
                [
                    {
                        "name": "passes input while not held",
                        "inputs": {"u": 10.0, "u1": False},
                        "expectations": [{"target": "y", "value": 10.0}],
                    }
                ]
            ),
        },
        files={
            "points_file": (
                "plant-points.csv",
                b"name,label,data_type,role,default,required\n"
                b"u,Value,numeric,sensor,0,true\n"
                b"u1,Trigger,boolean,sensor,false,true\n"
                b"y,Held value,numeric,command,0,true\n",
                "text/csv",
            )
        },
    )

    assert response.status_code == 201, response.text
    run = response.json()
    assert run["status"] == "ready_for_review"
    assert run["target_artifact_kind"] == "niagara_program_source_package"
    assert run["bog_path"] is None
    assert run["program_package_path"] == run["target_artifact_path"]
    approval = client.post(
        f"/api/runs/{run['id']}/approve",
        json={"reviewer": "Alex Engineer"},
    )
    assert approval.status_code == 200, approval.text
    export = client.get(f"/api/runs/{run['id']}/export")
    assert export.status_code == 200
    with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
        assert "manifest.json" in archive.namelist()
        assert "wiring-plan.json" in archive.namelist()


def test_reject_api_records_named_decision_and_refuses_export(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))
    run = client.post("/api/runs/demo").json()

    response = client.post(
        f"/api/runs/{run['id']}/reject",
        json={"reviewer": "Alex Engineer", "reason": "Correct the mapped actuator."},
    )

    assert response.status_code == 200, response.text
    rejected = response.json()
    assert rejected["status"] == "rejected"
    assert rejected["rejection"]["reviewer"] == "Alex Engineer"
    assert rejected["rejection"]["artifact_sha256"] == run["artifact_sha256"]
    assert client.get(f"/api/runs/{run['id']}/export").status_code == 403


def test_static_workbench_is_served(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))
    response = client.get("/")
    assert response.status_code == 200
    assert "Controls Workbench" in response.text
    assert 'name="points_file"' in response.text
    assert 'name="sequence_document"' in response.text
    assert 'name="environment_pack"' in response.text
    assert 'id="reject"' in response.text
    assert 'id="inspect-intake"' in response.text
    assert 'id="agent-loop-summary"' in response.text
    assert 'id="agent-attempts"' in response.text
    assert 'id="probe-bacnet-lab"' in response.text
    script = client.get("/app.js")
    assert script.status_code == 200
    assert "renderAgentAttempts(run)" in script.text
    assert "run.agent_attempts" in script.text

    next_response = client.get("/next/")
    assert next_response.status_code == 200
    assert "BACTalk Studio" in next_response.text
    assert 'id="root"' in next_response.text
    deep_link = client.get("/next/studio/example-run/tests")
    assert deep_link.status_code == 200
    assert 'id="root"' in deep_link.text


def test_capability_and_readiness_ledgers_are_exposed(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))

    readiness = client.get("/api/system/readiness")
    capabilities = client.get("/api/capability-packs")

    assert readiness.status_code == 200
    assert readiness.json()["production_ready"] is False
    assert capabilities.status_code == 200
    assert capabilities.json()["summary"]["production_supported_packs"] == 0
    assert capabilities.json()["summary"]["catalogued_equipment_families"] >= 15
    pack = capabilities.json()["packs"][0]
    assert pack["release_assessment"]["eligible_for_production_support"] is False
    gates = client.get(f"/api/capability-packs/{pack['id']}/release-gates")
    assert gates.status_code == 200
    assert gates.json()["blocking_gate_ids"]
    assert client.get("/api/capability-packs/missing/release-gates").status_code == 404


def test_open_control_library_catalog_and_translation_are_exposed(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))

    catalog = client.get("/api/library/open-control/faults")
    translated = client.post("/api/library/open-control/faults/AHU-0039/translate")

    assert catalog.status_code == 200
    assert catalog.json()["count"] == 137
    assert catalog.json()["ir_vector_verified_count"] == 137
    assert catalog.json()["niagara_vector_verified_count"] == 113
    assert translated.status_code == 200
    assert translated.json()["coverage"]["translatable"] is True
    assert translated.json()["vector_report"]["passed"] is True


def test_niagara_program_library_catalog_and_source_are_exposed(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))

    catalog = client.get("/api/library/niagara-programs")
    inspected = client.get("/api/library/niagara-programs/GL36_VAV_AHU_SYSTEM")

    assert catalog.status_code == 200
    assert catalog.json()["count"] == 20
    assert catalog.json()["program_object_count"] == 36
    assert inspected.status_code == 200
    assert inspected.json()["program_object_count"] == 10
    assert inspected.json()["runtime_qualified"] is False
    assert all(item["source"] for item in inspected.json()["programs"])
    assert client.get("/api/library/niagara-programs/missing").status_code == 404


def test_whole_building_api_build_approval_and_export(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))
    vav = demo_job().model_copy(update={"equipment_name": "VAV_1"})
    ahu = generalist_demo_job().model_copy(update={"equipment_name": "AHU_1", "site": vav.site})
    project = ProjectSpec(
        name="Two equipment proof",
        site=vav.site,
        equipment=[vav, ahu],
        relationships=[EquipmentRelationship(source="AHU_1", relation="feeds", target="VAV_1")],
    )

    response = client.post(
        "/api/projects/build",
        json=project.model_dump(mode="json"),
    )

    assert response.status_code == 201, response.text
    record = response.json()
    assert record["status"] == "ready_for_review"
    assert len(record["equipment_runs"]) == 2
    report = client.get(f"/api/projects/{record['id']}/report")
    assert report.status_code == 200
    assert report.json()["passed"] is True
    assert report.json()["coverage"]["equipment_count"] == 2
    assert client.get(f"/api/projects/{record['id']}/export").status_code == 403
    approval = client.post(
        f"/api/projects/{record['id']}/approve",
        json={"reviewer": "Alex Engineer"},
    )
    assert approval.status_code == 200
    export = client.get(f"/api/projects/{record['id']}/export")
    assert export.status_code == 200
    assert export.content.startswith(b"PK")


def test_imports_contractor_files_and_diffs_template(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))
    baseline = client.post("/api/runs/demo").json()
    template = Path(baseline["bog_path"]).read_bytes()

    response = client.post(
        "/api/runs/import",
        data={
            "name": "North Wing contractor import",
            "site": "Example Campus",
            "equipment_name": "VAV_12",
            "sequence_parameters": (
                '{"loop_span_f":3,"minimum_damper_pct":20,"high_zone_temp_f":80}'
            ),
            "deliverable_requirements": json.dumps(
                {
                    "alarms": [
                        {
                            "point": "HighZoneTempAlarm",
                            "alarm_class": "HVAC-Critical",
                            "priority": 100,
                        }
                    ],
                    "schedules": [
                        {
                            "id": "OccupancySchedule",
                            "output_point": "Occupied",
                            "timezone": "America/New_York",
                            "weekly_periods": [{"day": "monday", "start": "07:00", "end": "18:00"}],
                        }
                    ],
                    "histories": [
                        {
                            "point": "ZoneTemp",
                            "mode": "fixed_interval",
                            "interval_seconds": 300,
                            "retention_days": 365,
                        }
                    ],
                    "graphics": [
                        {
                            "id": "VavOverview",
                            "title": "VAV Overview",
                            "points": ["ZoneTemp", "DamperCommand", "HighZoneTempAlarm"],
                        }
                    ],
                }
            ),
        },
        files={
            "points_csv": (
                "points.csv",
                (EXAMPLES / "vav-reheat-points.csv").read_bytes(),
                "text/csv",
            ),
            "bacnet_scan": (
                "scan.json",
                (EXAMPLES / "vav-reheat-scan.json").read_bytes(),
                "application/json",
            ),
            "template_bog": ("template.bog", template, "application/zip"),
        },
    )

    assert response.status_code == 201, response.text
    imported = response.json()
    assert imported["status"] == "ready_for_review"
    assert Path(imported["semantic_model_path"]).is_file()
    assert Path(imported["template_analysis_path"]).is_file()
    assert imported["changes"]["added"] == []
    assert imported["changes"]["modified"] == [
        "/VAV_12/ZoneTemp/NumericInterval/historyConfig/source"
    ]
    assert any("OccupancySchedule" in path for path in imported["changes"]["removed"])
    analysis = client.get(f"/api/runs/{imported['id']}/template-analysis")
    assert analysis.status_code == 200
    assert analysis.json()["comparison"]["summary"]["left"]["nodes"] > 300


def test_import_rejects_non_bog_template(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))
    response = client.post(
        "/api/runs/import",
        data={"name": "Bad", "site": "Site", "equipment_name": "VAV_1"},
        files={
            "points_csv": (
                "points.csv",
                (EXAMPLES / "vav-reheat-points.csv").read_bytes(),
                "text/csv",
            ),
            "template_bog": ("template.bog", b"not-a-zip", "application/zip"),
        },
    )
    assert response.status_code == 422
    assert "valid .bog" in response.json()["detail"]


def test_intake_inspects_xlsx_and_sequence_without_starting_build(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))
    response = client.post(
        "/api/intake/inspect",
        files={
            "points_file": (
                "points.xlsx",
                _example_points_xlsx(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            "sequence_document": (
                "sequence.md",
                b"The VAV terminal shall modulate its damper and enable reheat.",
                "text/markdown",
            ),
        },
    )

    assert response.status_code == 200, response.text
    inspection = response.json()
    assert inspection["point_count"] == 9
    assert inspection["sequence"]["suggested_sequence_families"][0]["family"] == ("G36_VAV_REHEAT")
    assert inspection["selected_sequence_family"] == "G36_VAV_REHEAT"
    assert inspection["missing_required_points"] == []
    assert inspection["build_started"] is False
    assert inspection["writes_enabled"] is False


def test_imports_xlsx_and_auto_selected_sequence_with_signed_sources(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))
    response = client.post(
        "/api/runs/import",
        data={
            "name": "North Wing spreadsheet import",
            "site": "Example Campus",
            "equipment_name": "VAV_12",
            "sequence_family": "AUTO",
            "sequence_parameters": (
                '{"loop_span_f":3,"minimum_damper_pct":20,"high_zone_temp_f":80}'
            ),
            "deliverable_requirements": json.dumps(
                {
                    "alarms": [
                        {
                            "point": "HighZoneTempAlarm",
                            "alarm_class": "HVAC-Critical",
                            "priority": 100,
                        }
                    ],
                    "schedules": [
                        {
                            "id": "OccupancySchedule",
                            "output_point": "Occupied",
                            "timezone": "America/New_York",
                            "weekly_periods": [{"day": "monday", "start": "07:00", "end": "18:00"}],
                        }
                    ],
                    "histories": [
                        {
                            "point": "ZoneTemp",
                            "mode": "fixed_interval",
                            "interval_seconds": 300,
                            "retention_days": 365,
                        }
                    ],
                    "graphics": [
                        {
                            "id": "VavOverview",
                            "title": "VAV Overview",
                            "points": ["ZoneTemp", "DamperCommand", "HighZoneTempAlarm"],
                        }
                    ],
                }
            ),
        },
        files={
            "points_file": (
                "points.xlsx",
                _example_points_xlsx(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            "sequence_document": (
                "sequence.md",
                b"The VAV terminal shall modulate its damper and enable reheat.",
                "text/markdown",
            ),
        },
    )

    assert response.status_code == 201, response.text
    run = response.json()
    assert run["job"]["sequence"]["family"] == "G36_VAV_REHEAT"
    assert run["job"]["sequence"]["source_filename"] == "sequence.md"
    assert len(run["source_artifact_paths"]) == 2
    assert all(Path(path).is_file() for path in run["source_artifact_paths"])
    assert client.get(f"/api/runs/{run['id']}/export").status_code == 403


def test_import_maps_common_contractor_point_aliases_to_pack_contract(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))
    points = b"""name,label,data_type,role,units,default,required
ZN-T,Zone temperature,numeric,sensor,degF,76,true
CLG-SP,Cooling setpoint,numeric,setpoint,degF,74,true
HTG-SP,Heating setpoint,numeric,setpoint,degF,70,true
OCC,Occupied mode,boolean,status,,true,true
DPR-C,Damper command,numeric,command,%,0,true
RHT-VLV-C,Reheat valve command,numeric,command,%,0,true
CLG-DMD,Cooling demand,numeric,status,%,0,true
HTG-DMD,Heating demand,numeric,status,%,0,true
HI-ZN-T-ALM,High zone temp alarm,boolean,alarm,,false,true
"""
    response = client.post(
        "/api/runs/import",
        data={
            "name": "Alias mapping proof",
            "site": "Example Campus",
            "equipment_name": "VAV_12",
            "sequence_family": "G36_VAV_REHEAT",
            "sequence_parameters": (
                '{"loop_span_f":3,"minimum_damper_pct":20,"high_zone_temp_f":80}'
            ),
            "deliverable_requirements": json.dumps(
                {
                    "alarms": [
                        {
                            "point": "HI-ZN-T-ALM",
                            "alarm_class": "HVAC-Critical",
                            "priority": 100,
                        }
                    ],
                    "schedules": [
                        {
                            "id": "OccupancySchedule",
                            "output_point": "OCC",
                            "timezone": "America/New_York",
                            "weekly_periods": [{"day": "monday", "start": "07:00", "end": "18:00"}],
                        }
                    ],
                    "histories": [
                        {
                            "point": "ZN-T",
                            "mode": "fixed_interval",
                            "interval_seconds": 300,
                            "retention_days": 365,
                        }
                    ],
                    "graphics": [
                        {
                            "id": "VavOverview",
                            "title": "VAV Overview",
                            "points": ["ZN-T", "DPR-C", "HI-ZN-T-ALM"],
                        }
                    ],
                }
            ),
        },
        files={"points_file": ("points.csv", points, "text/csv")},
    )

    assert response.status_code == 201, response.text
    run = response.json()
    by_name = {point["name"]: point for point in run["job"]["points"]}
    assert set(by_name) >= {
        "ZoneTemp",
        "CoolingSetpoint",
        "DamperCommand",
        "HighZoneTempAlarm",
    }
    assert by_name["ZoneTemp"]["source_name"] == "ZN-T"
    assert by_name["DamperCommand"]["source_name"] == "DPR-C"
    artifacts = {Path(path).name: Path(path) for path in run["deliverable_artifact_paths"]}
    assert json.loads(artifacts["alarms.json"].read_text())["status"] == ("requirements_complete")
    assert json.loads(artifacts["schedules.json"].read_text())["status"] == (
        "requirements_complete"
    )
