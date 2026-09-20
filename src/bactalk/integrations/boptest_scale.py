from __future__ import annotations

import math
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from bactalk.integrations.boptest import BoptestClient


@dataclass(frozen=True, slots=True)
class BoptestScaleProfile:
    """Bounded concurrency profile for the real BOPTEST service.

    This qualifies the virtual-building execution plane. It deliberately does
    not claim licensed Niagara, BACnet-network, controller, or field-equipment
    capacity.
    """

    base_url: str = "http://127.0.0.1:8000"
    test_case: str = "multizone_office_complex_air"
    instances: int = 4
    concurrency: int = 4
    steps: int = 12
    step_seconds: float = 300.0
    request_timeout_seconds: float = 180.0

    def __post_init__(self) -> None:
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must use HTTP or HTTPS")
        if not self.test_case:
            raise ValueError("test_case is required")
        if not 1 <= self.instances <= 1_000:
            raise ValueError("instances must be from 1 through 1000")
        if not 1 <= self.concurrency <= self.instances:
            raise ValueError("concurrency must be from 1 through instances")
        if not 1 <= self.steps <= 100_000:
            raise ValueError("steps must be from 1 through 100000")
        if not math.isfinite(self.step_seconds) or self.step_seconds <= 0:
            raise ValueError("step_seconds must be positive and finite")
        if (
            not math.isfinite(self.request_timeout_seconds)
            or self.request_timeout_seconds <= 0
        ):
            raise ValueError("request_timeout_seconds must be positive and finite")


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = math.ceil(percentile * len(ordered)) - 1
    return ordered[max(0, min(index, len(ordered) - 1))]


class BoptestScaleRunner:
    """Exercise many isolated building models through the official REST API."""

    def __init__(
        self,
        profile: BoptestScaleProfile,
        *,
        client_factory: Callable[[], BoptestClient] | None = None,
    ) -> None:
        self.profile = profile
        self.client_factory = client_factory or (
            lambda: BoptestClient(
                profile.base_url,
                timeout=profile.request_timeout_seconds,
            )
        )

    @staticmethod
    def _case_ids(value: Any) -> set[str]:
        if not isinstance(value, list):
            return set()
        return {
            str(item["testcaseid"])
            for item in value
            if isinstance(item, dict) and item.get("testcaseid")
        }

    def _run_instance(self, instance: int) -> dict[str, Any]:
        started = time.perf_counter()
        selected_at: float | None = None
        test_id: str | None = None
        stopped: Any = None
        error: str | None = None
        input_count = 0
        measurement_count = 0
        last_time: float | None = None
        kpis: Any = None

        client = self.client_factory()
        try:
            test_id = client.select(self.profile.test_case)
            selected_at = time.perf_counter()
            client.initialize(test_id, start_time=0.0, warmup_period=0.0)
            client.set_step(test_id, self.profile.step_seconds)
            input_count = len(client.inputs(test_id))
            measurement_count = len(client.measurements(test_id))
            for _ in range(self.profile.steps):
                snapshot = client.advance(test_id, {})
                if not isinstance(snapshot, dict) or "time" not in snapshot:
                    raise ValueError("BOPTEST advance omitted simulation time")
                last_time = float(snapshot["time"])
            expected_time = self.profile.steps * self.profile.step_seconds
            if last_time is None or not math.isclose(last_time, expected_time, abs_tol=1e-6):
                raise ValueError(
                    f"BOPTEST advanced to {last_time}; expected {expected_time}"
                )
            kpis = client.kpis(test_id)
        except Exception as exc:  # Evidence must retain every worker failure.
            error = f"{type(exc).__name__}: {exc}"
        finally:
            if test_id is not None:
                try:
                    stopped = client.stop(test_id)
                except Exception as exc:  # pragma: no cover - runtime-only failure path
                    stop_error = f"{type(exc).__name__}: {exc}"
                    error = f"{error}; stop failed: {stop_error}" if error else stop_error
            client.close()

        finished = time.perf_counter()
        passed = error is None and stopped == "OK"
        if error is None and stopped != "OK":
            error = f"BOPTEST stop returned {stopped!r}"
        return {
            "instance": instance,
            "status": "pass" if passed else "fail",
            "test_id": test_id,
            "selection_seconds": None if selected_at is None else selected_at - started,
            "duration_seconds": finished - started,
            "steps_completed": self.profile.steps if passed else 0,
            "simulated_seconds": (
                self.profile.steps * self.profile.step_seconds if passed else 0.0
            ),
            "last_simulation_time": last_time,
            "input_count": input_count,
            "measurement_count": measurement_count,
            "kpis": kpis,
            "stop": stopped,
            "error": error,
        }

    def run(self) -> dict[str, Any]:
        discovery_started = time.perf_counter()
        discovery = self.client_factory()
        try:
            version = discovery.version()
            available_cases = self._case_ids(discovery.test_cases())
        finally:
            discovery.close()
        if self.profile.test_case not in available_cases:
            raise ValueError(f"BOPTEST test case is unavailable: {self.profile.test_case}")
        discovery_seconds = time.perf_counter() - discovery_started

        started = time.perf_counter()
        results: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=self.profile.concurrency) as executor:
            futures = {
                executor.submit(self._run_instance, instance): instance
                for instance in range(1, self.profile.instances + 1)
            }
            for future in as_completed(futures):
                results.append(future.result())
        wall_seconds = time.perf_counter() - started
        results.sort(key=lambda item: int(item["instance"]))

        passed = [item for item in results if item["status"] == "pass"]
        durations = [float(item["duration_seconds"]) for item in results]
        selection_durations = [
            float(value)
            for item in results
            if (value := item["selection_seconds"]) is not None
        ]
        total_steps = sum(int(item["steps_completed"]) for item in results)
        total_simulated_seconds = sum(float(item["simulated_seconds"]) for item in results)

        return {
            "schema": "bactalk.boptest-scale-evidence/v1",
            "created_at": datetime.now(UTC).isoformat(),
            "status": "pass" if len(passed) == self.profile.instances else "fail",
            "scope": "concurrent whole-building physics service qualification",
            "claims": [
                "real BOPTEST service API",
                "independent FMU lifecycle per instance",
                "concurrent initialize/advance/KPI/stop",
                "retained per-instance latency and model I/O counts",
            ],
            "not_proven": [
                "licensed Niagara runtime capacity",
                "BACnet network or router capacity",
                "physical controller scan time",
                "field wiring or mechanical safety",
                "live-building deployment readiness",
            ],
            "profile": {
                "base_url": self.profile.base_url,
                "test_case": self.profile.test_case,
                "instances": self.profile.instances,
                "concurrency": self.profile.concurrency,
                "steps": self.profile.steps,
                "step_seconds": self.profile.step_seconds,
            },
            "runtime": {
                "version": version,
                "discovery_seconds": discovery_seconds,
                "wall_seconds": wall_seconds,
                "passed_instances": len(passed),
                "failed_instances": self.profile.instances - len(passed),
                "total_steps": total_steps,
                "total_simulated_seconds": total_simulated_seconds,
                "steps_per_wall_second": total_steps / wall_seconds,
                "simulated_seconds_per_wall_second": total_simulated_seconds / wall_seconds,
                "instance_duration_p50_seconds": _percentile(durations, 0.50),
                "instance_duration_p95_seconds": _percentile(durations, 0.95),
                "selection_p95_seconds": _percentile(selection_durations, 0.95),
            },
            "instances": results,
        }
