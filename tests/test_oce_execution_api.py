from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from bactalk.api import create_app

FIXTURE = Path(
    ".vendor/open-control-engine/crates/oce-cxf/tests/fixtures/g36/ahu_economizer.jsonld"
)
ROOT = "http://example.org#g36.ahu_economizer"


def test_cxf_execution_api_runs_native_stateful_g36_trajectory(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))
    difference = f"{ROOT}.returnMinusOutdoor.y"
    latch = f"{ROOT}.enableLatch.y"
    damper = f"{ROOT}.damperSwitch.y"

    response = client.post(
        "/api/execute/cxf",
        json={
            "document": json.loads(FIXTURE.read_text(encoding="utf-8")),
            "samples": [
                {
                    "time": 0,
                    "inputs": {
                        f"{ROOT}.return_air_temp": 24,
                        f"{ROOT}.outdoor_air_temp": 18,
                        f"{ROOT}.operating_mode": 1,
                    },
                },
                {
                    "time": 180,
                    "inputs": {
                        f"{ROOT}.return_air_temp": 24,
                        f"{ROOT}.outdoor_air_temp": 27,
                        f"{ROOT}.operating_mode": 1,
                    },
                },
            ],
            "collect": [difference, latch, damper],
        },
    )

    assert response.status_code == 200, response.text
    trace = response.json()
    assert trace["schema"] == "bactalk.oce-trace/v1"
    assert trace["sample_count"] == 2
    assert trace["trace"][0]["outputs"][difference]["value"] == 6.0
    assert trace["trace"][0]["outputs"][latch]["value"] is True
    assert trace["trace"][0]["outputs"][damper]["value"] == 1.0
    assert trace["trace"][1]["outputs"][difference]["value"] == -3.0
    assert trace["trace"][1]["outputs"][latch]["value"] is False
    assert trace["trace"][1]["outputs"][damper]["value"] == 0.2


def test_cxf_execution_api_rejects_unknown_input(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))

    response = client.post(
        "/api/execute/cxf",
        json={
            "document": json.loads(FIXTURE.read_text(encoding="utf-8")),
            "samples": [{"time": 0, "inputs": {"not-a-real-point": 1}}],
            "collect": [f"{ROOT}.returnMinusOutdoor.y"],
        },
    )

    assert response.status_code == 422
    assert "unknown scenario input" in response.json()["detail"]
