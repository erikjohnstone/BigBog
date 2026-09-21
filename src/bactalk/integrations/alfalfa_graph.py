from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bactalk.domain import BlockKind, ControlGraph, canonical_json
from bactalk.integrations.alfalfa import AlfalfaClientLike
from bactalk.simulator import GraphInterpreter


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class AlfalfaOutputBinding(BaseModel):
    """Map one FMU output into one typed BACTalk graph input."""

    model_config = ConfigDict(extra="forbid")

    graph_input: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    output: str = Field(min_length=1, max_length=240)
    scale: float = 1.0
    offset: float = 0.0
    initial_output_value: float | bool | None = None

    @model_validator(mode="after")
    def finite_transform(self) -> AlfalfaOutputBinding:
        if not math.isfinite(self.scale) or not math.isfinite(self.offset):
            raise ValueError("Alfalfa output transforms must be finite")
        if (
            self.initial_output_value is not None
            and not isinstance(self.initial_output_value, bool)
            and not math.isfinite(self.initial_output_value)
        ):
            raise ValueError("Alfalfa initial output values must be finite")
        return self


class AlfalfaInputBinding(BaseModel):
    """Map one typed BACTalk graph output into one bounded FMU input."""

    model_config = ConfigDict(extra="forbid")

    graph_output: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    input: str = Field(min_length=1, max_length=240)
    scale: float = 1.0
    offset: float = 0.0
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode="after")
    def valid_bounds_and_transform(self) -> AlfalfaInputBinding:
        values = (self.scale, self.offset, self.minimum, self.maximum)
        if any(value is not None and not math.isfinite(value) for value in values):
            raise ValueError("Alfalfa input transforms and bounds must be finite")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("Alfalfa input minimum cannot exceed maximum")
        return self


class AlfalfaGraphMap(BaseModel):
    """Explicit, complete mapping between a BACTalk graph and one Alfalfa FMU."""

    model_config = ConfigDict(extra="forbid")

    outputs: list[AlfalfaOutputBinding] = Field(min_length=1, max_length=2_000)
    inputs: list[AlfalfaInputBinding] = Field(min_length=1, max_length=2_000)
    observed_outputs: list[str] = Field(default_factory=list, max_length=2_000)
    command_echoes: dict[str, str] = Field(default_factory=dict, max_length=2_000)
    echo_tolerance: float = Field(default=1e-6, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def unique_bindings(self) -> AlfalfaGraphMap:
        for label, values in (
            ("graph inputs", [item.graph_input for item in self.outputs]),
            ("FMU outputs", [item.output for item in self.outputs]),
            ("graph outputs", [item.graph_output for item in self.inputs]),
            ("FMU inputs", [item.input for item in self.inputs]),
            ("observed FMU outputs", self.observed_outputs),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"Alfalfa mapping contains duplicate {label}")
        bound_inputs = {item.input for item in self.inputs}
        unknown_echo_inputs = set(self.command_echoes) - bound_inputs
        if unknown_echo_inputs:
            raise ValueError(
                "Alfalfa command echoes reference unmapped FMU inputs: "
                f"{sorted(unknown_echo_inputs)}"
            )
        echo_outputs = list(self.command_echoes.values())
        if len(echo_outputs) != len(set(echo_outputs)):
            raise ValueError("Alfalfa mapping contains duplicate command echo outputs")
        return self


class AlfalfaGraphRunner:
    """Execute a complete typed BACTalk graph in closed loop with an Alfalfa FMU.

    Signal names are never guessed. Every public graph input and output must have
    exactly one reviewed mapping, every numeric command has explicit bounds, and
    the Alfalfa run is stopped even when validation or execution fails.
    """

    MAX_STEPS = 100_000

    def __init__(
        self,
        client: AlfalfaClientLike,
        graph: ControlGraph,
        mapping: AlfalfaGraphMap,
    ) -> None:
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
        mapped_inputs = {binding.graph_input for binding in self.mapping.outputs}
        if mapped_inputs != graph_inputs:
            raise ValueError(
                "Alfalfa mapping must cover every graph input exactly; "
                f"missing={sorted(graph_inputs - mapped_inputs)}, "
                f"unknown={sorted(mapped_inputs - graph_inputs)}"
            )

        graph_outputs = {
            block.id
            for block in self.graph.blocks
            if block.kind in {BlockKind.NUMERIC_OUTPUT, BlockKind.BOOLEAN_OUTPUT}
        }
        mapped_outputs = {binding.graph_output for binding in self.mapping.inputs}
        if mapped_outputs != graph_outputs:
            raise ValueError(
                "Alfalfa mapping must cover every graph output exactly; "
                f"missing={sorted(graph_outputs - mapped_outputs)}, "
                f"unknown={sorted(mapped_outputs - graph_outputs)}"
            )

    @staticmethod
    def _number(value: Any, label: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{label} must be numeric")
        result = float(value)
        if not math.isfinite(result):
            raise ValueError(f"{label} must be finite")
        return result

    def _graph_inputs(
        self,
        outputs: dict[str, Any],
        *,
        allow_initial_values: bool,
    ) -> tuple[dict[str, float | bool], dict[str, float | bool]]:
        values: dict[str, float | bool] = {}
        initial_values: dict[str, float | bool] = {}
        for binding in self.mapping.outputs:
            if binding.output not in outputs:
                raise ValueError(f"Alfalfa output snapshot is missing {binding.output}")
            raw = outputs[binding.output]
            if (
                raw is None
                and allow_initial_values
                and binding.initial_output_value is not None
            ):
                raw = binding.initial_output_value
                initial_values[binding.output] = raw
            block = self.blocks[binding.graph_input]
            if block.kind == BlockKind.BOOLEAN_INPUT:
                if not isinstance(raw, bool) and raw not in (0, 1):
                    raise ValueError(f"Alfalfa output {binding.output} is not boolean-like")
                values[binding.graph_input] = bool(raw)
            else:
                value = self._number(raw, f"Alfalfa output {binding.output}")
                values[binding.graph_input] = value * binding.scale + binding.offset
        return values, initial_values

    def _commands(
        self,
        controller_values: dict[str, float | bool],
    ) -> tuple[dict[str, float], dict[str, float | bool]]:
        commands: dict[str, float] = {}
        outputs: dict[str, float | bool] = {}
        for binding in self.mapping.inputs:
            block = self.blocks[binding.graph_output]
            raw = controller_values[binding.graph_output]
            outputs[binding.graph_output] = raw
            if block.kind == BlockKind.BOOLEAN_OUTPUT:
                command = float(bool(raw))
            else:
                command = (
                    self._number(raw, f"graph output {binding.graph_output}")
                    * binding.scale
                    + binding.offset
                )
            if binding.minimum is not None and command < binding.minimum:
                raise ValueError(
                    f"command {binding.input}={command} is below Alfalfa minimum "
                    f"{binding.minimum}"
                )
            if binding.maximum is not None and command > binding.maximum:
                raise ValueError(
                    f"command {binding.input}={command} is above Alfalfa maximum "
                    f"{binding.maximum}"
                )
            commands[binding.input] = command
        return commands, outputs

    def run(
        self,
        model_path: Path,
        *,
        steps: int,
        step_seconds: float,
        start: datetime,
        server_version: Any = None,
        client_version: str | None = None,
    ) -> dict[str, Any]:
        if (
            isinstance(steps, bool)
            or not isinstance(steps, int)
            or not 1 <= steps <= self.MAX_STEPS
        ):
            raise ValueError(f"steps must be an integer from 1 through {self.MAX_STEPS}")
        if not math.isfinite(step_seconds) or step_seconds <= 0:
            raise ValueError("step_seconds must be positive and finite")
        model_path = model_path.resolve()
        if not model_path.is_file():
            raise FileNotFoundError(model_path)

        run_id: str | None = None
        started = False
        stopped_status: str | None = None
        end = start + timedelta(seconds=steps * step_seconds)
        try:
            run_id = str(self.client.submit(str(model_path)))
            self.client.start(run_id, start, end, external_clock=True)
            started = True
            status_after_start = str(self.client.status(run_id))
            runtime_inputs = sorted(self.client.get_inputs(run_id))
            current_outputs = self.client.get_outputs(run_id)
            if not isinstance(current_outputs, dict):
                raise ValueError("Alfalfa returned an invalid output snapshot")

            required_inputs = {binding.input for binding in self.mapping.inputs}
            required_outputs = {
                *(binding.output for binding in self.mapping.outputs),
                *self.mapping.observed_outputs,
                *self.mapping.command_echoes.values(),
            }
            missing_inputs = required_inputs - set(runtime_inputs)
            missing_outputs = required_outputs - current_outputs.keys()
            if missing_inputs or missing_outputs:
                raise ValueError(
                    "Alfalfa mapping does not match the submitted FMU; "
                    f"missing_inputs={sorted(missing_inputs)}, "
                    f"missing_outputs={sorted(missing_outputs)}"
                )

            interpreter = GraphInterpreter(self.graph)
            trajectory: list[dict[str, Any]] = []
            previous_time = self.client.get_sim_time(run_id)
            for index in range(steps):
                graph_inputs, initial_output_values = self._graph_inputs(
                    current_outputs,
                    allow_initial_values=index == 0,
                )
                controller_values = interpreter.evaluate(
                    graph_inputs,
                    step_seconds=0.0 if index == 0 else step_seconds,
                )
                commands, graph_outputs = self._commands(controller_values)
                self.client.set_inputs(run_id, commands)
                self.client.advance(run_id)
                advanced_time = self.client.get_sim_time(run_id)
                expected_time = previous_time + timedelta(seconds=step_seconds)
                if advanced_time != expected_time:
                    raise ValueError(
                        f"Alfalfa advanced to {advanced_time.isoformat()}; "
                        f"expected {expected_time.isoformat()}"
                    )
                advanced_outputs = self.client.get_outputs(run_id)
                if not isinstance(advanced_outputs, dict):
                    raise ValueError("Alfalfa returned an invalid output snapshot")
                command_echoes: dict[str, dict[str, Any]] = {}
                for input_name, output_name in self.mapping.command_echoes.items():
                    command = commands[input_name]
                    feedback = self._number(
                        advanced_outputs.get(output_name),
                        f"Alfalfa command echo {output_name}",
                    )
                    matched = math.isclose(
                        command,
                        feedback,
                        rel_tol=0.0,
                        abs_tol=self.mapping.echo_tolerance,
                    )
                    command_echoes[input_name] = {
                        "output": output_name,
                        "command": command,
                        "feedback": feedback,
                        "matched": matched,
                    }
                    if not matched:
                        raise ValueError(
                            f"Alfalfa command echo mismatch for {input_name}: "
                            f"command={command}, feedback={feedback}"
                        )
                trajectory.append(
                    {
                        "index": index,
                        "start_time": previous_time.isoformat(),
                        "end_time": advanced_time.isoformat(),
                        "graph_inputs": graph_inputs,
                        "initial_output_values": initial_output_values,
                        "controller_outputs": graph_outputs,
                        "fmu_inputs": commands,
                        "command_echoes": command_echoes,
                        "observed_outputs": {
                            name: advanced_outputs.get(name)
                            for name in sorted(required_outputs)
                        },
                    }
                )
                current_outputs = advanced_outputs
                previous_time = advanced_time
        finally:
            if run_id is not None and started:
                self.client.stop(run_id)
                stopped_status = str(self.client.status(run_id))

        if stopped_status is None or stopped_status.upper() != "COMPLETE":
            raise ValueError(f"Alfalfa did not stop cleanly: {stopped_status!r}")
        return {
            "schema": "bactalk.alfalfa-graph-run/v1",
            "status": "pass",
            "runtime": "Alfalfa",
            "server_version": server_version,
            "client_version": client_version,
            "run_id": run_id,
            "status_after_start": status_after_start,
            "status_after_stop": stopped_status,
            "model_name": model_path.name,
            "model_sha256": _sha256(model_path),
            "graph_name": self.graph.name,
            "graph_sha256": hashlib.sha256(
                canonical_json(self.graph).encode("utf-8")
            ).hexdigest(),
            "mapping": self.mapping.model_dump(mode="json"),
            "runtime_input_count": len(runtime_inputs),
            "runtime_output_count": len(current_outputs),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "step_seconds": step_seconds,
            "steps": steps,
            "trajectory": trajectory,
            "clean_stop": True,
            "live_building_writes": False,
        }
