from __future__ import annotations

import hashlib
import math
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bactalk.domain import BlockKind, ControlGraph, canonical_json
from bactalk.simulator import GraphInterpreter


class BoptestRuntime(Protocol):
    def version(self) -> Any: ...

    def select(self, test_case: str) -> str: ...

    def initialize(self, test_id: str, *, start_time: float, warmup_period: float) -> Any: ...

    def set_step(self, test_id: str, seconds: float) -> Any: ...

    def measurements(self, test_id: str) -> Any: ...

    def inputs(self, test_id: str) -> Any: ...

    def advance(self, test_id: str, overrides: dict[str, float | int]) -> Any: ...

    def kpis(self, test_id: str) -> Any: ...

    def stop(self, test_id: str) -> Any: ...


class BoptestMeasurementBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph_input: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    measurement: str = Field(min_length=1, max_length=240)
    scale: float = 1.0
    offset: float = 0.0

    @model_validator(mode="after")
    def finite_transform(self) -> BoptestMeasurementBinding:
        if not math.isfinite(self.scale) or not math.isfinite(self.offset):
            raise ValueError("measurement transforms must be finite")
        return self


class BoptestActuatorBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph_output: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    actuator: str = Field(min_length=1, max_length=240)
    activation_actuator: str | None = Field(default=None, min_length=1, max_length=240)
    scale: float = 1.0
    offset: float = 0.0

    @model_validator(mode="after")
    def finite_transform(self) -> BoptestActuatorBinding:
        if not math.isfinite(self.scale) or not math.isfinite(self.offset):
            raise ValueError("actuator transforms must be finite")
        if self.activation_actuator == self.actuator:
            raise ValueError("activation_actuator must differ from actuator")
        return self


class BoptestGraphMap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_case: str = Field(min_length=1, max_length=240)
    measurements: list[BoptestMeasurementBinding] = Field(min_length=1, max_length=2_000)
    actuators: list[BoptestActuatorBinding] = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def unique_bindings(self) -> BoptestGraphMap:
        for label, values in (
            ("graph inputs", [item.graph_input for item in self.measurements]),
            ("measurements", [item.measurement for item in self.measurements]),
            ("graph outputs", [item.graph_output for item in self.actuators]),
            ("actuators", [item.actuator for item in self.actuators]),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"BOPTEST mapping contains duplicate {label}")
        activations = [
            item.activation_actuator
            for item in self.actuators
            if item.activation_actuator is not None
        ]
        if len(activations) != len(set(activations)):
            raise ValueError("BOPTEST mapping contains duplicate activation actuators")
        if set(activations) & {item.actuator for item in self.actuators}:
            raise ValueError("activation actuators cannot also be mapped control actuators")
        return self


class BoptestTrajectoryOracle(BaseModel):
    """An independent expected trajectory used to qualify a BOPTEST run."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,119}$")
    signal_kind: Literal["graph_output", "measurement"]
    signal: str = Field(min_length=1, max_length=240)
    reference_times: list[float] = Field(min_length=1, max_length=100_000)
    reference_values: list[float] = Field(min_length=1, max_length=100_000)
    absolute_time_tolerance: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    absolute_value_tolerance: float = Field(default=0.0, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_trajectory(self) -> BoptestTrajectoryOracle:
        if len(self.reference_times) != len(self.reference_values):
            raise ValueError("oracle reference times and values must have equal length")
        if any(not math.isfinite(value) for value in self.reference_times):
            raise ValueError("oracle reference times must be finite")
        if any(not math.isfinite(value) for value in self.reference_values):
            raise ValueError("oracle reference values must be finite")
        if any(
            current <= previous
            for previous, current in zip(
                self.reference_times, self.reference_times[1:], strict=False
            )
        ):
            raise ValueError("oracle reference times must be strictly increasing")
        return self


class BoptestGraphRunner:
    """Run one complete typed BACTalk graph against a real BOPTEST FMU.

    The mapping is explicit and complete. The runner never guesses point names,
    enforces the BOPTEST-advertised actuator bounds, and always attempts to stop
    the selected test case.
    """

    def __init__(
        self,
        client: BoptestRuntime,
        graph: ControlGraph,
        mapping: BoptestGraphMap,
    ):
        self.client = client
        self.graph = graph
        self.mapping = mapping
        self.blocks = {block.id: block for block in graph.blocks}
        self._validate_graph_boundary()

    def _validate_graph_boundary(self) -> None:
        graph_inputs = {
            block.id
            for block in self.graph.blocks
            if block.kind in {BlockKind.NUMERIC_INPUT, BlockKind.BOOLEAN_INPUT}
        }
        mapped_inputs = {item.graph_input for item in self.mapping.measurements}
        if mapped_inputs != graph_inputs:
            raise ValueError(
                "BOPTEST mapping must cover every graph input exactly; "
                f"missing={sorted(graph_inputs - mapped_inputs)}, "
                f"unknown={sorted(mapped_inputs - graph_inputs)}"
            )

        graph_outputs = {
            block.id
            for block in self.graph.blocks
            if block.kind in {BlockKind.NUMERIC_OUTPUT, BlockKind.BOOLEAN_OUTPUT}
        }
        mapped_outputs = {item.graph_output for item in self.mapping.actuators}
        if mapped_outputs != graph_outputs:
            raise ValueError(
                "BOPTEST mapping must cover every graph output exactly; "
                f"missing={sorted(graph_outputs - mapped_outputs)}, "
                f"unknown={sorted(mapped_outputs - graph_outputs)}"
            )

    @staticmethod
    def _catalog(value: Any, label: str) -> dict[str, dict[str, Any]]:
        if not isinstance(value, dict) or not all(
            isinstance(key, str) and isinstance(metadata, dict)
            for key, metadata in value.items()
        ):
            raise ValueError(f"BOPTEST returned an invalid {label} catalog")
        return value

    @staticmethod
    def _snapshot(value: Any, label: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError(f"BOPTEST returned an invalid {label} snapshot")
        return value

    @staticmethod
    def _number(value: Any, label: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{label} must be numeric")
        result = float(value)
        if not math.isfinite(result):
            raise ValueError(f"{label} must be finite")
        return result

    def _graph_inputs(self, snapshot: dict[str, Any]) -> dict[str, float | bool]:
        values: dict[str, float | bool] = {}
        for binding in self.mapping.measurements:
            if binding.measurement not in snapshot:
                raise ValueError(
                    f"BOPTEST snapshot is missing measurement {binding.measurement}"
                )
            raw = snapshot[binding.measurement]
            block = self.blocks[binding.graph_input]
            if block.kind == BlockKind.BOOLEAN_INPUT:
                if not isinstance(raw, bool) and raw not in (0, 1):
                    raise ValueError(
                        f"BOPTEST measurement {binding.measurement} is not boolean-like"
                    )
                values[binding.graph_input] = bool(raw)
            else:
                value = self._number(raw, f"measurement {binding.measurement}")
                values[binding.graph_input] = value * binding.scale + binding.offset
        return values

    def _overrides(
        self,
        controller_values: dict[str, float | bool],
        input_catalog: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, float | int], dict[str, float | bool]]:
        overrides: dict[str, float | int] = {}
        outputs: dict[str, float | bool] = {}
        for binding in self.mapping.actuators:
            block = self.blocks[binding.graph_output]
            raw = controller_values[binding.graph_output]
            outputs[binding.graph_output] = raw
            if block.kind == BlockKind.BOOLEAN_OUTPUT:
                command = int(bool(raw))
            else:
                command = (
                    self._number(raw, f"graph output {binding.graph_output}")
                    * binding.scale
                    + binding.offset
                )
            metadata = input_catalog[binding.actuator]
            minimum = metadata.get("Minimum")
            maximum = metadata.get("Maximum")
            if minimum is not None and command < float(minimum):
                raise ValueError(
                    f"command {binding.actuator}={command} is below BOPTEST minimum {minimum}"
                )
            if maximum is not None and command > float(maximum):
                raise ValueError(
                    f"command {binding.actuator}={command} is above BOPTEST maximum {maximum}"
                )
            overrides[binding.actuator] = command
            if binding.activation_actuator is not None:
                overrides[binding.activation_actuator] = 1
        return overrides, outputs

    def run(
        self,
        *,
        steps: int,
        step_seconds: float,
        start_time: float = 0.0,
        warmup_period: float = 0.0,
    ) -> dict[str, Any]:
        if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= 100_000:
            raise ValueError("steps must be an integer from 1 through 100000")
        if not math.isfinite(step_seconds) or step_seconds <= 0:
            raise ValueError("step_seconds must be positive and finite")

        version = self.client.version()
        test_id = self.client.select(self.mapping.test_case)
        stopped: Any = None
        try:
            initial = self._snapshot(
                self.client.initialize(
                    test_id,
                    start_time=start_time,
                    warmup_period=warmup_period,
                ),
                "initial",
            )
            step_contract = self.client.set_step(test_id, step_seconds)
            measurement_catalog = self._catalog(
                self.client.measurements(test_id), "measurement"
            )
            input_catalog = self._catalog(self.client.inputs(test_id), "input")

            missing_measurements = {
                item.measurement for item in self.mapping.measurements
            } - measurement_catalog.keys()
            requested_actuators = {
                name
                for item in self.mapping.actuators
                for name in (item.actuator, item.activation_actuator)
                if name is not None
            }
            missing_actuators = requested_actuators - input_catalog.keys()
            if missing_measurements or missing_actuators:
                raise ValueError(
                    "BOPTEST mapping does not match the selected test case; "
                    f"missing_measurements={sorted(missing_measurements)}, "
                    f"missing_actuators={sorted(missing_actuators)}"
                )

            interpreter = GraphInterpreter(self.graph)
            current = initial
            trajectory: list[dict[str, Any]] = []
            previous_time = self._number(current.get("time"), "initial time")
            for index in range(steps):
                graph_inputs = self._graph_inputs(current)
                controller_values = interpreter.evaluate(
                    graph_inputs,
                    step_seconds=0.0 if index == 0 else step_seconds,
                )
                overrides, outputs = self._overrides(controller_values, input_catalog)
                advanced = self._snapshot(
                    self.client.advance(test_id, overrides), "advanced"
                )
                advanced_time = self._number(advanced.get("time"), "advanced time")
                expected_time = previous_time + step_seconds
                if not math.isclose(advanced_time, expected_time, abs_tol=1e-6):
                    raise ValueError(
                        f"BOPTEST advanced to {advanced_time}; expected {expected_time}"
                    )
                trajectory.append(
                    {
                        "index": index,
                        "start_time": previous_time,
                        "end_time": advanced_time,
                        "graph_inputs": graph_inputs,
                        "controller_outputs": outputs,
                        "overrides": overrides,
                        "measurements": {
                            item.measurement: advanced[item.measurement]
                            for item in self.mapping.measurements
                        },
                    }
                )
                current = advanced
                previous_time = advanced_time
            kpis = self.client.kpis(test_id)
        finally:
            stopped = self.client.stop(test_id)

        if stopped != "OK":
            raise ValueError(f"BOPTEST did not stop cleanly: {stopped!r}")
        return {
            "schema_version": "1.0",
            "status": "pass",
            "runtime": "BOPTEST",
            "version": version,
            "test_case": self.mapping.test_case,
            "graph_name": self.graph.name,
            "graph_sha256": hashlib.sha256(
                canonical_json(self.graph).encode("utf-8")
            ).hexdigest(),
            "mapping": self.mapping.model_dump(mode="json"),
            "step_seconds": step_seconds,
            "steps": steps,
            "step_contract": step_contract,
            "measurement_catalog_count": len(measurement_catalog),
            "input_catalog_count": len(input_catalog),
            "trajectory": trajectory,
            "kpis": kpis,
            "stop": stopped,
        }
