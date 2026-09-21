from __future__ import annotations

import json

import httpx
import pytest

from bactalk.domain import Block, BlockKind, ControlGraph, Link
from bactalk.integrations.boptest import (
    BoptestClient,
    discover_boptest_catalog,
    inspect_boptest_test_case,
)
from bactalk.integrations.boptest_graph import (
    BoptestActuatorBinding,
    BoptestGraphMap,
    BoptestGraphRunner,
    BoptestMeasurementBinding,
    BoptestScenario,
)


def test_boptest_client_unwraps_service_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/testcases/bestest_air/select":
            assert request.method == "POST"
            assert json.loads(request.content) == {}
            return httpx.Response(
                200,
                json={"status": 200, "message": "ok", "payload": {"testid": "test-123"}},
            )
        if request.url.path == "/advance/test-123":
            assert json.loads(request.content) == {"ahu_coil_u": 0.5}
            return httpx.Response(
                200,
                json={"status": 200, "message": "ok", "payload": {"zone_temp": 294.1}},
            )
        return httpx.Response(404)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    boptest = BoptestClient("http://boptest", client=http_client)

    assert boptest.select("bestest_air") == "test-123"
    assert boptest.advance("test-123", {"ahu_coil_u": 0.5}) == {"zone_temp": 294.1}


def test_boptest_stop_accepts_official_plain_text_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/stop/test-123"
        return httpx.Response(200, text="OK", headers={"content-type": "text/plain"})

    boptest = BoptestClient(
        "http://boptest",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert boptest.stop("test-123") == "OK"


def test_boptest_client_sets_and_reads_native_scenario() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "PUT":
            assert json.loads(request.content) == {
                "time_period": "peak_cool_day",
                "electricity_price": "dynamic",
            }
        return httpx.Response(
            200,
            json={
                "status": 200,
                "message": "ok",
                "payload": {
                    "time_period": "peak_cool_day",
                    "electricity_price": "dynamic",
                },
            },
        )

    boptest = BoptestClient(
        "http://boptest",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    requested = {"time_period": "peak_cool_day", "electricity_price": "dynamic"}
    assert boptest.set_scenario("test-123", requested) == requested
    assert boptest.get_scenario("test-123") == requested
    assert calls == [
        ("PUT", "/scenario/test-123"),
        ("GET", "/scenario/test-123"),
    ]


def test_boptest_client_rejects_invalid_scenario_timeout() -> None:
    with pytest.raises(ValueError, match="positive and finite"):
        BoptestClient("http://boptest", scenario_timeout=0)


def _fan_graph() -> ControlGraph:
    return ControlGraph(
        name="BoptestFanController",
        blocks=[
            Block(id="room_temp", kind=BlockKind.NUMERIC_INPUT, label="Room temperature"),
            Block(
                id="threshold",
                kind=BlockKind.NUMERIC_CONST,
                label="Cooling threshold",
                config={"value": 292.0},
            ),
            Block(id="is_hot", kind=BlockKind.GREATER_THAN, label="Cooling request"),
            Block(
                id="fan_on",
                kind=BlockKind.NUMERIC_CONST,
                label="Fan on",
                config={"value": 1.0},
            ),
            Block(
                id="fan_off",
                kind=BlockKind.NUMERIC_CONST,
                label="Fan off",
                config={"value": 0.0},
            ),
            Block(id="select_fan", kind=BlockKind.NUMERIC_SWITCH, label="Fan selector"),
            Block(id="fan_command", kind=BlockKind.NUMERIC_OUTPUT, label="Fan command"),
        ],
        links=[
            Link(source="room_temp", target="is_hot", target_slot="a"),
            Link(source="threshold", target="is_hot", target_slot="b"),
            Link(source="is_hot", target="select_fan", target_slot="selector"),
            Link(source="fan_on", target="select_fan", target_slot="when_true"),
            Link(source="fan_off", target="select_fan", target_slot="when_false"),
            Link(source="select_fan", target="fan_command", target_slot="in"),
        ],
    )


def _fan_map() -> BoptestGraphMap:
    return BoptestGraphMap(
        test_case="bestest_air",
        measurements=[
            BoptestMeasurementBinding(
                graph_input="room_temp",
                measurement="zon_reaTRooAir_y",
            )
        ],
        actuators=[
            BoptestActuatorBinding(
                graph_output="fan_command",
                actuator="fcu_oveFan_u",
                activation_actuator="fcu_oveFan_activate",
            )
        ],
    )


class _FakeBoptest:
    def __init__(self) -> None:
        self.time = 0.0
        self.commands: list[dict[str, float | int]] = []
        self.stopped = False
        self.initialize_count = 0
        self.scenario_state: dict[str, object] = {}

    def version(self) -> dict[str, str]:
        return {"version": "test"}

    def test_cases(self) -> list[dict[str, str]]:
        return [{"testcaseid": "bestest_air"}]

    def select(self, test_case: str) -> str:
        assert test_case == "bestest_air"
        return "test-123"

    def initialize(self, test_id: str, *, start_time: float, warmup_period: float) -> dict:
        assert test_id == "test-123"
        assert warmup_period == 0.0
        self.initialize_count += 1
        self.time = start_time
        return {"time": self.time, "zon_reaTRooAir_y": 293.15}

    def set_step(self, test_id: str, seconds: float) -> dict[str, float]:
        assert test_id == "test-123"
        self.step = seconds
        return {"step": seconds}

    def measurements(self, test_id: str) -> dict[str, dict]:
        return {"zon_reaTRooAir_y": {"Unit": "K"}}

    def inputs(self, test_id: str) -> dict[str, dict]:
        return {
            "fcu_oveFan_u": {"Minimum": 0, "Maximum": 1},
            "fcu_oveFan_activate": {"Minimum": None, "Maximum": None},
        }

    def set_scenario(self, test_id: str, scenario: dict[str, object]) -> dict:
        self.scenario_state = {
            key: None if value == "none" else value for key, value in scenario.items()
        }
        response = {**self.scenario_state}
        if scenario.get("time_period"):
            self.time = 1_234_800.0
            response["time_period"] = {
                "time": self.time,
                "zon_reaTRooAir_y": 297.15,
            }
        return response

    def get_scenario(self, test_id: str) -> dict[str, object]:
        return self.scenario_state

    def advance(self, test_id: str, overrides: dict[str, float | int]) -> dict:
        self.commands.append(overrides)
        self.time += self.step
        return {"time": self.time, "zon_reaTRooAir_y": 292.5}

    def kpis(self, test_id: str) -> dict[str, float]:
        return {"ener_tot": 1.0}

    def stop(self, test_id: str) -> str:
        self.stopped = True
        return "OK"


def test_boptest_catalog_inspection_returns_exact_signals_and_stops_case() -> None:
    client = _FakeBoptest()

    catalog = discover_boptest_catalog(client)
    contract = inspect_boptest_test_case(client, "bestest_air")

    assert catalog["test_cases"] == ["bestest_air"]
    assert contract["schema"] == "bactalk.boptest-test-case-contract/v1"
    assert contract["test_case"] == "bestest_air"
    assert contract["measurement_count"] == 1
    assert contract["measurements"][0]["name"] == "zon_reaTRooAir_y"
    assert contract["measurements"][0]["unit"] == "K"
    assert contract["input_count"] == 2
    assert next(
        item for item in contract["inputs"] if item["name"] == "fcu_oveFan_activate"
    )["activation_signal"] is True
    assert contract["clean_stop"] is True
    assert contract["initialized"] is False
    assert client.stopped is True


def test_boptest_catalog_refuses_unadvertised_case_without_selecting() -> None:
    client = _FakeBoptest()

    with pytest.raises(ValueError, match="not advertised"):
        inspect_boptest_test_case(client, "unknown_case")

    assert client.stopped is False


def test_graph_runner_executes_complete_closed_loop_mapping() -> None:
    client = _FakeBoptest()
    evidence = BoptestGraphRunner(client, _fan_graph(), _fan_map()).run(
        steps=2,
        step_seconds=300.0,
    )

    assert evidence["status"] == "pass"
    assert evidence["steps"] == 2
    assert evidence["trajectory"][0]["controller_outputs"] == {"fan_command": 1.0}
    assert client.commands == [
        {"fcu_oveFan_u": 1.0, "fcu_oveFan_activate": 1},
        {"fcu_oveFan_u": 1.0, "fcu_oveFan_activate": 1},
    ]
    assert client.stopped is True


def test_graph_runner_applies_and_verifies_named_weather_scenario() -> None:
    client = _FakeBoptest()
    scenario = BoptestScenario(
        time_period="peak_cool_day",
        electricity_price="dynamic",
        temperature_uncertainty="medium",
        solar_uncertainty="none",
        seed=42,
    )
    evidence = BoptestGraphRunner(client, _fan_graph(), _fan_map()).run(
        steps=1,
        step_seconds=300.0,
        scenario=scenario,
    )

    assert client.initialize_count == 0
    assert evidence["scenario_request"] == {
        "time_period": "peak_cool_day",
        "electricity_price": "dynamic",
        "temperature_uncertainty": "medium",
        "solar_uncertainty": "none",
        "seed": 42,
    }
    assert evidence["scenario_state"] == {
        "time_period": "peak_cool_day",
        "electricity_price": "dynamic",
        "temperature_uncertainty": "medium",
        "solar_uncertainty": None,
        "seed": 42,
    }
    assert evidence["scenario_initialized_model"] is True
    assert evidence["trajectory"][0]["start_time"] == 1_234_800.0
    assert client.stopped is True


def test_graph_runner_fails_closed_when_scenario_readback_differs() -> None:
    class MismatchBoptest(_FakeBoptest):
        def get_scenario(self, test_id: str) -> dict[str, object]:
            return {**self.scenario_state, "electricity_price": "constant"}

    client = MismatchBoptest()
    with pytest.raises(ValueError, match="did not apply electricity_price"):
        BoptestGraphRunner(client, _fan_graph(), _fan_map()).run(
            steps=1,
            step_seconds=300.0,
            scenario=BoptestScenario(electricity_price="dynamic"),
        )
    assert client.stopped is True


def test_boptest_scenario_rejects_seed_without_uncertainty_and_ambiguous_clock() -> None:
    with pytest.raises(ValueError, match="seed requires weather uncertainty"):
        BoptestScenario(seed=42)
    with pytest.raises(ValueError, match="define their own start and warmup"):
        BoptestGraphRunner(_FakeBoptest(), _fan_graph(), _fan_map()).run(
            steps=1,
            step_seconds=300.0,
            start_time=60.0,
            scenario=BoptestScenario(time_period="peak_heat_day"),
        )


def test_graph_runner_rejects_incomplete_boundary_mapping() -> None:
    mapping = _fan_map().model_copy(update={"measurements": []})
    with pytest.raises(ValueError, match="cover every graph input"):
        BoptestGraphRunner(_FakeBoptest(), _fan_graph(), mapping)


def test_graph_runner_rejects_commands_outside_runtime_bounds() -> None:
    graph = _fan_graph()
    on = next(block for block in graph.blocks if block.id == "fan_on")
    on.config["value"] = 1.5
    client = _FakeBoptest()
    with pytest.raises(ValueError, match="above BOPTEST maximum"):
        BoptestGraphRunner(client, graph, _fan_map()).run(
            steps=1,
            step_seconds=300.0,
        )
    assert client.stopped is True
