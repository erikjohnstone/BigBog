from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from bactalk.domain import Block, BlockKind, ControlGraph, Link
from bactalk.integrations.alfalfa_graph import (
    AlfalfaGraphMap,
    AlfalfaGraphRunner,
    AlfalfaInputBinding,
    AlfalfaOutputBinding,
)


def _fan_graph() -> ControlGraph:
    return ControlGraph(
        name="AlfalfaFanController",
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
                config={"value": 0.37},
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


def _mapping() -> AlfalfaGraphMap:
    return AlfalfaGraphMap(
        outputs=[
            AlfalfaOutputBinding(
                graph_input="room_temp",
                output="hvac_reaZonCor_TZon_y",
            )
        ],
        inputs=[
            AlfalfaInputBinding(
                graph_output="fan_command",
                input="hvac_oveAhu_yFan_u",
                minimum=0.0,
                maximum=1.0,
            )
        ],
        observed_outputs=["hvac_oveAhu_yFan_y"],
        command_echoes={"hvac_oveAhu_yFan_u": "hvac_oveAhu_yFan_y"},
    )


class _FakeAlfalfa:
    def __init__(
        self,
        *,
        actual_step_seconds: float = 60.0,
        omit_echo: bool = False,
        initial_null: bool = False,
    ) -> None:
        self.time = datetime(2019, 1, 1)
        self.actual_step_seconds = actual_step_seconds
        self.omit_echo = omit_echo
        self.initial_null = initial_null
        self.commands: list[dict[str, float]] = []
        self.current_commands: dict[str, float] = {}
        self.stopped = False

    def submit(self, model_path: str, wait_for_status: bool = True) -> str:
        assert Path(model_path).is_file()
        return "alfalfa-run-123"

    def start(
        self,
        run_id: str,
        start_datetime: datetime,
        end_datetime: datetime,
        timescale: int = 5,
        external_clock: bool = False,
        realtime: bool = False,
        wait_for_status: bool = True,
    ) -> None:
        assert run_id == "alfalfa-run-123"
        assert external_clock is True
        assert end_datetime > start_datetime
        self.time = start_datetime

    def status(self, _run_id: str) -> str:
        return "COMPLETE" if self.stopped else "RUNNING"

    def get_inputs(self, _run_id: str) -> list[str]:
        return ["hvac_oveAhu_yFan_u"]

    def set_inputs(self, _run_id: str, inputs: dict[str, float]) -> None:
        self.current_commands.update(inputs)
        self.commands.append(dict(inputs))

    def get_outputs(self, _run_id: str) -> dict[str, float | None]:
        outputs: dict[str, float | None] = {
            "hvac_reaZonCor_TZon_y": (
                None
                if self.initial_null and not self.commands
                else 294.0 - self.time.minute / 10
            ),
        }
        if not self.omit_echo:
            outputs["hvac_oveAhu_yFan_y"] = self.current_commands.get(
                "hvac_oveAhu_yFan_u", 0.0
            )
        return outputs

    def get_sim_time(self, _run_id: str) -> datetime:
        return self.time

    def advance(self, _run_id: str) -> None:
        self.time += timedelta(seconds=self.actual_step_seconds)

    def stop(self, _run_id: str, wait_for_status: bool = True) -> None:
        self.stopped = True


def _model(tmp_path: Path) -> Path:
    model = tmp_path / "building.fmu"
    model.write_bytes(b"fake-fmu")
    return model


def test_graph_runner_executes_complete_closed_loop_mapping(tmp_path: Path) -> None:
    client = _FakeAlfalfa()

    evidence = AlfalfaGraphRunner(client, _fan_graph(), _mapping()).run(
        _model(tmp_path),
        steps=2,
        step_seconds=60.0,
        start=datetime(2019, 1, 1),
        server_version="1.0.0",
        client_version="1.0.0",
    )

    assert evidence["schema"] == "bactalk.alfalfa-graph-run/v1"
    assert evidence["status"] == "pass"
    assert evidence["steps"] == 2
    assert evidence["clean_stop"] is True
    assert evidence["live_building_writes"] is False
    assert evidence["trajectory"][0]["controller_outputs"] == {"fan_command": 0.37}
    assert evidence["trajectory"][0]["fmu_inputs"] == {
        "hvac_oveAhu_yFan_u": 0.37
    }
    assert evidence["trajectory"][0]["observed_outputs"][
        "hvac_oveAhu_yFan_y"
    ] == pytest.approx(0.37)
    assert evidence["trajectory"][0]["command_echoes"]["hvac_oveAhu_yFan_u"][
        "matched"
    ] is True
    assert client.commands == [
        {"hvac_oveAhu_yFan_u": 0.37},
        {"hvac_oveAhu_yFan_u": 0.37},
    ]
    assert client.stopped is True


def test_graph_runner_rejects_incomplete_boundary_mapping() -> None:
    mapping = _mapping().model_copy(
        update={
            "outputs": [
                AlfalfaOutputBinding(
                    graph_input="unknown_input",
                    output="hvac_reaZonCor_TZon_y",
                )
            ]
        }
    )

    with pytest.raises(ValueError, match="cover every graph input"):
        AlfalfaGraphRunner(_FakeAlfalfa(), _fan_graph(), mapping)


def test_graph_runner_rejects_out_of_bounds_command_and_stops(tmp_path: Path) -> None:
    graph = _fan_graph()
    next(block for block in graph.blocks if block.id == "fan_on").config["value"] = 1.5
    client = _FakeAlfalfa()

    with pytest.raises(ValueError, match="above Alfalfa maximum"):
        AlfalfaGraphRunner(client, graph, _mapping()).run(
            _model(tmp_path),
            steps=1,
            step_seconds=60.0,
            start=datetime(2019, 1, 1),
        )

    assert client.stopped is True


def test_graph_runner_rejects_missing_runtime_signal_and_stops(tmp_path: Path) -> None:
    client = _FakeAlfalfa(omit_echo=True)

    with pytest.raises(ValueError, match="missing_outputs"):
        AlfalfaGraphRunner(client, _fan_graph(), _mapping()).run(
            _model(tmp_path),
            steps=1,
            step_seconds=60.0,
            start=datetime(2019, 1, 1),
        )

    assert client.stopped is True


def test_graph_runner_retains_explicit_first_tick_initial_value(tmp_path: Path) -> None:
    client = _FakeAlfalfa(initial_null=True)
    mapping = _mapping().model_copy(
        update={
            "outputs": [
                _mapping().outputs[0].model_copy(update={"initial_output_value": 294.0})
            ]
        }
    )

    evidence = AlfalfaGraphRunner(client, _fan_graph(), mapping).run(
        _model(tmp_path),
        steps=1,
        step_seconds=60.0,
        start=datetime(2019, 1, 1),
    )

    assert evidence["trajectory"][0]["initial_output_values"] == {
        "hvac_reaZonCor_TZon_y": 294.0
    }
    assert evidence["trajectory"][0]["graph_inputs"] == {"room_temp": 294.0}


def test_graph_runner_rejects_unreviewed_first_tick_null_and_stops(tmp_path: Path) -> None:
    client = _FakeAlfalfa(initial_null=True)

    with pytest.raises(ValueError, match="must be numeric"):
        AlfalfaGraphRunner(client, _fan_graph(), _mapping()).run(
            _model(tmp_path),
            steps=1,
            step_seconds=60.0,
            start=datetime(2019, 1, 1),
        )

    assert client.stopped is True


def test_graph_runner_rejects_wrong_runtime_step_and_stops(tmp_path: Path) -> None:
    client = _FakeAlfalfa(actual_step_seconds=30.0)

    with pytest.raises(ValueError, match="expected 2019-01-01T00:01:00"):
        AlfalfaGraphRunner(client, _fan_graph(), _mapping()).run(
            _model(tmp_path),
            steps=1,
            step_seconds=60.0,
            start=datetime(2019, 1, 1),
        )

    assert client.stopped is True
