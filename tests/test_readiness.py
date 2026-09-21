import json
from pathlib import Path

from fastapi.testclient import TestClient

from bactalk.api import create_app
from bactalk.integrations.readiness import STAGES, IntegrationReadiness


def test_readiness_is_conservative_and_complete() -> None:
    report = IntegrationReadiness().report()
    components = {item["id"]: item for item in report["components"]}
    assert report["production_ready"] is False
    assert report["stage_order"] == list(STAGES)
    assert {
        "pybog",
        "aixocat",
        "contractor-niagara-environments",
        "niagara-point-bindings",
        "modelica-buildings",
        "modelica-json",
        "ctrl-flow",
        "open-control-engine",
        "open-control-library",
        "n4-hvac-optimization-blocks",
        "constrain",
        "boptest",
        "alfalfa",
        "alfalfa-client",
        "qualification-job-plane",
        "pyfunnel",
        "brick",
        "haxall",
        "phable",
        "bacpypes3",
        "bac0",
        "open-fdd",
        "volttron",
        "nhaystack",
        "am8x-alarm-pattern",
        "openmodelica",
        "bacnet-stack",
        "niagara-runtime",
    } <= components.keys()
    assert components["pybog"]["stage"] == "target-compiled"
    assert components["boptest"]["stage"] == "product-wired"
    assert components["nhaystack"]["stage"] == "product-wired"
    assert components["am8x-alarm-pattern"]["stage"] == "product-wired"
    assert components["niagara-runtime"]["production_ready"] is False


def test_alfalfa_runtime_evidence_advances_readiness_without_claiming_production(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / ".bactalk/alfalfa-runtime-evidence.json"
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text(
        json.dumps(
            {
                "schema": "bactalk.alfalfa-runtime-evidence/v1",
                "status": "pass",
                "results": {"clean_stop": True, "changed_output_count": 95},
            }
        ),
        encoding="utf-8",
    )

    components = {
        item["id"]: item for item in IntegrationReadiness(tmp_path).report()["components"]
    }

    assert components["alfalfa"]["stage"] == "product-wired"
    assert components["alfalfa-client"]["stage"] == "product-wired"
    assert components["alfalfa"]["production_ready"] is False
    assert "typed graph-to-FMU" in components["alfalfa"]["blocker"]

    (tmp_path / ".bactalk/alfalfa-graph-evidence.json").write_text(
        json.dumps(
            {
                "schema": "bactalk.alfalfa-graph-run/v1",
                "status": "pass",
                "clean_stop": True,
                "trajectory": [
                    {
                        "command_echoes": {
                            "fan_command": {"matched": True},
                        }
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    graph_qualified = {
        item["id"]: item for item in IntegrationReadiness(tmp_path).report()["components"]
    }

    assert "typed graph-to-FMU" not in graph_qualified["alfalfa"]["blocker"]
    assert "independent trajectory oracle" in graph_qualified["alfalfa"]["blocker"]
    assert graph_qualified["alfalfa"]["production_ready"] is False

    queue_compose = tmp_path / "ops/qualification-queue.compose.yml"
    queue_compose.parent.mkdir(parents=True)
    queue_compose.write_text("services: {}\n", encoding="utf-8")
    (tmp_path / ".bactalk/alfalfa-product-evidence.json").write_text(
        json.dumps(
            {
                "schema": "bactalk.alfalfa-product-workflow/v1",
                "status": "pass",
                "runtime_evidence": {
                    "schema": "bactalk.alfalfa-graph-run/v1",
                    "status": "pass",
                    "approval_allowed": True,
                    "oracles": [
                        {"completed": True, "passed": True, "pyfunnel_status_code": 0}
                    ],
                },
                "qualification_job": {
                    "schema_version": "bactalk.qualification-job/v3",
                    "status": "succeeded",
                    "worker_id": "worker-1",
                    "progress": {"percent": 100.0},
                    "qualification_passed": True,
                    "candidate_artifact_sha256": "c" * 64,
                    "input_sha256": "a" * 64,
                    "result_artifact_sha256": "b" * 64,
                },
            }
        ),
        encoding="utf-8",
    )
    oracle_qualified = {
        item["id"]: item for item in IntegrationReadiness(tmp_path).report()["components"]
    }

    assert "independent trajectory oracle" not in oracle_qualified["alfalfa"]["blocker"]
    assert oracle_qualified["alfalfa"]["production_ready"] is False
    assert oracle_qualified["qualification-job-plane"]["stage"] == "executable"
    assert (
        "queued BOPTEST" in oracle_qualified["qualification-job-plane"]["blocker"]
    )

    (tmp_path / ".bactalk/boptest-graph-runtime-evidence.json").write_text(
        json.dumps(
            {
                "schema": "bactalk.boptest-contractor-e2e/v2",
                "status": "pass",
                "room_temperature_changed": True,
                "boptest_catalog": {
                    "schema": "bactalk.boptest-catalog/v1",
                    "test_cases": ["bestest_air"],
                },
                "inspected_test_case_contract": {
                    "schema": "bactalk.boptest-test-case-contract/v1",
                    "test_case": "bestest_air",
                    "clean_stop": True,
                    "initialized": False,
                },
                "qualification_job": {
                    "schema_version": "bactalk.qualification-job/v3",
                    "kind": "boptest",
                    "status": "succeeded",
                    "worker_id": "worker-2",
                    "progress": {"percent": 100.0},
                    "qualification_passed": True,
                    "candidate_artifact_sha256": "d" * 64,
                    "input_sha256": "e" * 64,
                    "result_artifact_sha256": "f" * 64,
                },
            }
        ),
        encoding="utf-8",
    )
    both_qualified = {
        item["id"]: item for item in IntegrationReadiness(tmp_path).report()["components"]
    }

    assert both_qualified["qualification-job-plane"]["stage"] == "product-wired"
    assert "queued BOPTEST" not in both_qualified["qualification-job-plane"]["blocker"]
    assert both_qualified["qualification-job-plane"]["production_ready"] is False
    assert "native BOPTEST scenario" in both_qualified["boptest"]["blocker"]

    (tmp_path / ".bactalk/boptest-scenario-runtime-evidence.json").write_text(
        json.dumps(
            {
                "schema": "bactalk.boptest-contractor-e2e/v2",
                "status": "pass",
                "scenario_request": {
                    "time_period": "peak_cool_day",
                    "temperature_uncertainty": "medium",
                    "seed": 42,
                },
                "scenario_state": {
                    "time_period": "peak_cool_day",
                    "temperature_uncertainty": "medium",
                    "seed": 42,
                },
                "scenario_readback_verified": True,
                "oracle_passed": True,
                "room_temperature_changed": True,
                "runtime_evidence": {
                    "oracle_clock": {"basis": "elapsed_seconds_from_run_start"}
                },
                "qualification_job": {
                    "schema_version": "bactalk.qualification-job/v3",
                    "status": "succeeded",
                    "qualification_passed": True,
                    "progress": {"percent": 100.0},
                },
            }
        ),
        encoding="utf-8",
    )
    scenario_qualified = {
        item["id"]: item for item in IntegrationReadiness(tmp_path).report()["components"]
    }
    assert "native BOPTEST scenario" not in scenario_qualified["boptest"]["blocker"]
    assert "authoritative BOPTEST point maps" in scenario_qualified["boptest"]["blocker"]


def test_readiness_api(tmp_path: Path) -> None:
    response = TestClient(create_app(tmp_path)).get("/api/system/readiness")
    assert response.status_code == 200
    assert response.json()["production_ready"] is False
