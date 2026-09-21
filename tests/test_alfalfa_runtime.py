from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from bactalk.integrations.alfalfa import qualify_alfalfa_runtime, write_evidence_atomic


class FakeAlfalfaClient:
    def __init__(self, *, fail_advance: bool = False) -> None:
        self.time = datetime(2019, 1, 1)
        self.commands: dict[str, float] = {}
        self.fail_advance = fail_advance
        self.stopped = False

    def submit(self, model_path: str, wait_for_status: bool = True) -> str:
        assert Path(model_path).is_file()
        return "run-123"

    def start(self, *_args: object, **_kwargs: object) -> None:
        return None

    def status(self, _run_id: str) -> str:
        return "COMPLETE" if self.stopped else "RUNNING"

    def get_inputs(self, _run_id: str) -> list[str]:
        return [
            "hvac_oveAhu_TSupSet_u",
            "hvac_oveAhu_yCoo_u",
            "hvac_oveAhu_yFan_u",
            "hvac_oveAhu_yHea_u",
            "hvac_oveAhu_yOA_u",
        ]

    def set_inputs(self, _run_id: str, inputs: dict[str, float]) -> None:
        self.commands.update(inputs)

    def get_outputs(self, _run_id: str) -> dict[str, float]:
        return {
            "hvac_oveAhu_yFan_y": self.commands.get("hvac_oveAhu_yFan_u", 0.0),
            "hvac_reaAhu_TSup_y": 285.0 + self.time.minute,
            "hvac_reaZonCor_TZon_y": 294.0 + self.time.minute / 10,
        }

    def get_sim_time(self, _run_id: str) -> datetime:
        return self.time

    def advance(self, _run_id: str) -> None:
        if self.fail_advance:
            raise RuntimeError("worker failed")
        self.time += timedelta(minutes=1)

    def stop(self, _run_id: str, wait_for_status: bool = True) -> None:
        self.stopped = True


def test_qualifier_proves_trajectory_command_and_clean_stop(tmp_path: Path) -> None:
    model = tmp_path / "building.fmu"
    model.write_bytes(b"fake-fmu")
    client = FakeAlfalfaClient()

    evidence = qualify_alfalfa_runtime(client, model, client_version="1.0.0")

    assert evidence["status"] == "pass"
    assert evidence["results"]["advances_completed"] == 5
    assert evidence["results"]["simulated_seconds"] == 300
    assert evidence["results"]["changed_output_count"] == 3
    assert evidence["results"]["command_echoes"]["hvac_oveAhu_yFan_u"]["matched"] is True
    assert evidence["results"]["clean_stop"] is True
    assert client.stopped is True


def test_qualifier_retains_failure_and_still_stops(tmp_path: Path) -> None:
    model = tmp_path / "building.fmu"
    model.write_bytes(b"fake-fmu")
    client = FakeAlfalfaClient(fail_advance=True)

    evidence = qualify_alfalfa_runtime(client, model)

    assert evidence["status"] == "fail"
    assert any("worker failed" in error for error in evidence["errors"])
    assert evidence["results"]["clean_stop"] is True
    assert client.stopped is True


def test_evidence_write_is_complete_json(tmp_path: Path) -> None:
    output = tmp_path / "nested" / "evidence.json"
    evidence = {"schema": "test/v1", "status": "pass"}

    write_evidence_atomic(output, evidence)

    assert json.loads(output.read_text(encoding="utf-8")) == evidence
    assert not list(output.parent.glob("*.tmp"))


def test_worker_output_patch_is_exact_and_fail_closed(tmp_path: Path) -> None:
    patcher = Path("ops/alfalfa-worker/patch_output_value.py").resolve()
    target = tmp_path / "step_run.py"
    target.write_text("before\n            point.value = y_output\nafter\n", encoding="utf-8")

    subprocess.run([sys.executable, str(patcher), str(target)], check=True)

    assert "point.value = value" in target.read_text(encoding="utf-8")
    second = subprocess.run(
        [sys.executable, str(patcher), str(target)],
        capture_output=True,
        text=True,
    )
    assert second.returncode != 0
    assert "expected one vulnerable assignment, found 0" in second.stderr
