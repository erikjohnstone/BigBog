from __future__ import annotations

import math
from typing import Any

from bactalk.domain import ControlGraph
from bactalk.simulator import GraphInterpreter


class CxfVectorError(ValueError):
    pass


class CxfVectorVerifier:
    """Replay cxf-library vectors against imported BACTalk IR on an explicit time axis."""

    def verify(self, graph: ControlGraph, vectors: dict[str, Any]) -> dict[str, Any]:
        if vectors.get("schema") != "cxf-library/vectors/v1":
            raise CxfVectorError("unsupported CXF vector schema")
        clock = vectors.get("clock", {})
        step = float(clock.get("step_s", 0))
        horizon = float(clock.get("horizon_s", -1))
        if not math.isfinite(step) or step <= 0 or not math.isfinite(horizon) or horizon < 0:
            raise CxfVectorError(
                "vector clock must have positive step_s and non-negative horizon_s"
            )
        if horizon / step > 1_000_000:
            raise CxfVectorError("vector clock exceeds the one-million-sample safety limit")

        rendered: list[dict[str, Any]] = []
        for scenario in vectors.get("scenarios", []):
            rendered.append(self._verify_scenario(graph, scenario, step, horizon))
        return {
            "schema": "bactalk-cxf-vector-report/v1",
            "passed": all(item["passed"] for item in rendered),
            "engine": "BACTalk typed-IR interpreter",
            "step_s": step,
            "horizon_s": horizon,
            "scenario_count": len(rendered),
            "scenarios": rendered,
        }

    def _verify_scenario(
        self,
        graph: ControlGraph,
        scenario: dict[str, Any],
        step: float,
        horizon: float,
    ) -> dict[str, Any]:
        interpreter = GraphInterpreter(graph)
        current: dict[str, float | bool] = {}
        events: list[tuple[float, str, float | bool]] = []
        for name, specification in scenario.get("inputs", {}).items():
            if isinstance(specification, list):
                for event in specification:
                    timestamp = float(event["t"])
                    events.append((timestamp, name, event["value"]))
            else:
                current[name] = specification

        events.sort(key=lambda item: item[0])
        next_event = 0
        samples: dict[float, dict[str, float | bool]] = {}
        count = int(round(horizon / step))
        for index in range(count + 1):
            timestamp = round(index * step, 9)
            while next_event < len(events) and events[next_event][0] <= timestamp:
                _, name, value = events[next_event]
                current[name] = value
                next_event += 1
            samples[timestamp] = interpreter.evaluate(
                current,
                step_seconds=0.0 if index == 0 else step,
            )

        assertions: list[dict[str, Any]] = []
        for expectation in scenario.get("expect", []):
            output = expectation["output"]
            expected = expectation["equals"]
            tolerance = float(expectation.get("tolerance", 0.0))
            start = float(expectation["from_s"])
            end = float(expectation["to_s"])
            failures: list[dict[str, Any]] = []
            checked = 0
            for timestamp, values in samples.items():
                if timestamp < start - 1e-9 or timestamp > end + 1e-9:
                    continue
                if output not in values:
                    raise CxfVectorError(f"vector expectation references unknown output {output}")
                observed = values[output]
                checked += 1
                if not self._matches(observed, expected, tolerance):
                    failures.append({"t": timestamp, "observed": observed})
                    if len(failures) == 10:
                        break
            if checked == 0:
                raise CxfVectorError(f"expectation for {output} has no samples in [{start}, {end}]")
            assertions.append(
                {
                    "output": output,
                    "from_s": start,
                    "to_s": end,
                    "expected": expected,
                    "tolerance": tolerance,
                    "passed": not failures,
                    "checked_samples": checked,
                    "failures": failures,
                }
            )
        return {
            "name": scenario.get("name", "unnamed"),
            "passed": all(item["passed"] for item in assertions),
            "assertions": assertions,
        }

    @staticmethod
    def _matches(observed: float | bool, expected: float | bool, tolerance: float) -> bool:
        if isinstance(expected, bool):
            return observed is expected
        if isinstance(observed, bool) or not isinstance(observed, (int, float)):
            return False
        return abs(float(observed) - float(expected)) <= tolerance
