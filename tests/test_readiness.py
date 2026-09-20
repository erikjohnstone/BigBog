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
        "open-control-engine",
        "open-control-library",
        "n4-hvac-optimization-blocks",
        "constrain",
        "boptest",
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


def test_readiness_api(tmp_path: Path) -> None:
    response = TestClient(create_app(tmp_path)).get("/api/system/readiness")
    assert response.status_code == 200
    assert response.json()["production_ready"] is False
