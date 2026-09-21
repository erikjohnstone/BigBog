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
            }
        ),
        encoding="utf-8",
    )
    oracle_qualified = {
        item["id"]: item for item in IntegrationReadiness(tmp_path).report()["components"]
    }

    assert "independent trajectory oracle" not in oracle_qualified["alfalfa"]["blocker"]
    assert oracle_qualified["alfalfa"]["production_ready"] is False


def test_readiness_api(tmp_path: Path) -> None:
    response = TestClient(create_app(tmp_path)).get("/api/system/readiness")
    assert response.status_code == 200
    assert response.json()["production_ready"] is False
