from __future__ import annotations

import threading

import pytest

from bactalk.integrations.boptest_scale import BoptestScaleProfile, BoptestScaleRunner


class _ScaleClient:
    sequence = 0
    lock = threading.Lock()

    def __init__(self, *, stop_result: str = "OK") -> None:
        self.stop_result = stop_result
        self.step = 0.0
        self.time = 0.0

    def version(self) -> dict[str, str]:
        return {"version": "test"}

    def test_cases(self) -> list[dict[str, str]]:
        return [{"testcaseid": "multizone_office_complex_air"}]

    def select(self, test_case: str) -> str:
        assert test_case == "multizone_office_complex_air"
        with self.lock:
            self.__class__.sequence += 1
            return f"test-{self.sequence}"

    def initialize(self, test_id: str, *, start_time: float, warmup_period: float) -> dict:
        self.time = start_time
        return {"time": start_time}

    def set_step(self, test_id: str, seconds: float) -> dict[str, float]:
        self.step = seconds
        return {"step": seconds}

    def inputs(self, test_id: str) -> dict[str, dict]:
        return {"ahu_supply_fan": {}}

    def measurements(self, test_id: str) -> dict[str, dict]:
        return {"zone_temp": {}}

    def advance(self, test_id: str, overrides: dict) -> dict[str, float]:
        self.time += self.step
        return {"time": self.time}

    def kpis(self, test_id: str) -> dict[str, float]:
        return {"ener_tot": 1.0}

    def stop(self, test_id: str) -> str:
        return self.stop_result

    def close(self) -> None:
        return None


def test_scale_runner_retains_successful_concurrent_evidence() -> None:
    profile = BoptestScaleProfile(instances=4, concurrency=2, steps=3, step_seconds=60.0)
    evidence = BoptestScaleRunner(profile, client_factory=_ScaleClient).run()

    assert evidence["status"] == "pass"
    assert evidence["runtime"]["passed_instances"] == 4
    assert evidence["runtime"]["total_steps"] == 12
    assert evidence["runtime"]["total_simulated_seconds"] == 720.0
    assert all(instance["stop"] == "OK" for instance in evidence["instances"])
    assert "licensed Niagara runtime capacity" in evidence["not_proven"]


def test_scale_runner_fails_closed_when_instances_do_not_stop() -> None:
    profile = BoptestScaleProfile(instances=2, concurrency=2, steps=1)
    evidence = BoptestScaleRunner(
        profile,
        client_factory=lambda: _ScaleClient(stop_result="NOT_OK"),
    ).run()

    assert evidence["status"] == "fail"
    assert evidence["runtime"]["failed_instances"] == 2


def test_scale_profile_rejects_oversubscribed_concurrency() -> None:
    with pytest.raises(ValueError, match="concurrency"):
        BoptestScaleProfile(instances=2, concurrency=3)
