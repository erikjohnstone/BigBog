from __future__ import annotations

import asyncio
import hashlib
import json
import math
import socket
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from bactalk.domain import BlockKind, ControlGraph, canonical_json
from bactalk.integrations.alfalfa import AlfalfaClientLike
from bactalk.integrations.alfalfa_graph import AlfalfaGraphMap, AlfalfaGraphRunner
from bactalk.integrations.bacnet_lab import (
    BacnetLabManifest,
    LabDeviceConfig,
    VirtualBacnetLab,
)
from bactalk.simulator import GraphInterpreter


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _free_loopback_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def prepare_runtime_bacnet_lab(
    source_manifest_path: Path,
    destination: Path,
) -> VirtualBacnetLab:
    """Clone a signed lab topology onto fresh loopback-only UDP ports.

    Generated run artifacts retain stable addresses for review, but concurrent
    qualifications cannot safely bind the same ports. This creates a retained
    runtime derivative that changes only loopback bind addresses; devices,
    objects, roles, values, actuator models, and safety flags remain exact.
    """

    source_manifest_path = source_manifest_path.resolve()
    source_root = source_manifest_path.parent
    raw = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    manifest = BacnetLabManifest.model_validate(raw)
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    devices_directory = destination / "devices"
    devices_directory.mkdir()

    ports: dict[int, int] = {}
    runtime_devices: list[dict[str, Any]] = []
    used_ports: set[int] = set()
    for summary in manifest.devices:
        instance = int(summary["device_instance"])
        config_path = (source_root / str(summary["config"])).resolve()
        if not config_path.is_relative_to(source_root):
            raise ValueError("BACnet runtime source config escapes its manifest directory")
        config = LabDeviceConfig.model_validate_json(config_path.read_text(encoding="utf-8"))
        if config.device_instance != instance:
            raise ValueError("BACnet runtime device summary and config identity differ")
        port = _free_loopback_udp_port()
        while port in used_ports:
            port = _free_loopback_udp_port()
        used_ports.add(port)
        ports[instance] = port
        runtime_config = config.model_copy(
            update={
                "bind_address": f"127.0.0.1/32:{port}",
                "network_address": f"127.0.0.1:{port}",
            }
        )
        relative_config = f"devices/{instance}.json"
        (destination / relative_config).write_text(
            canonical_json(runtime_config),
            encoding="utf-8",
        )
        runtime_devices.append(
            {
                **summary,
                "network_address": runtime_config.network_address,
                "config": relative_config,
            }
        )

    runtime_index: dict[str, dict[str, Any]] = {}
    for point_name, point in manifest.point_index.items():
        instance = int(point["device_instance"])
        if instance not in ports:
            raise ValueError(f"BACnet point {point_name!r} references an unknown device")
        runtime_index[point_name] = {
            **point,
            "network_address": f"127.0.0.1:{ports[instance]}",
        }

    source_scenario = (source_root / manifest.scenario_file).resolve()
    if not source_scenario.is_relative_to(source_root) or not source_scenario.is_file():
        raise ValueError("BACnet runtime scenario contract is missing or unsafe")
    scenario_name = "acceptance-scenarios.json"
    (destination / scenario_name).write_bytes(source_scenario.read_bytes())
    runtime_manifest = {
        **raw,
        "devices": runtime_devices,
        "point_index": runtime_index,
        "scenario_file": scenario_name,
        "qualification_runtime": {
            "source_manifest_sha256": _sha256(source_manifest_path),
            "port_binding": "fresh_ephemeral_loopback",
            "semantic_changes": False,
        },
    }
    runtime_path = destination / "manifest.json"
    runtime_path.write_text(canonical_json(runtime_manifest), encoding="utf-8")
    return VirtualBacnetLab.load(runtime_path)


class AlfalfaBacnetGraphRunner:
    """Close the Alfalfa loop through real, isolated BACnet/IP datagrams.

    Alfalfa still supplies the building physics, while the generated virtual
    devices form the controller I/O boundary. The candidate graph reads every
    measurement through BACnet and writes every command back through BACnet at
    an explicit priority before the FMU is advanced. This does not claim a
    Niagara runtime; the controller runtime is identified in retained evidence.
    """

    READ_TIMEOUT_SECONDS = 5.0
    WRITE_PRIORITY = 8
    PROTOCOL_RELATIVE_TOLERANCE = 1e-6
    PROTOCOL_ABSOLUTE_TOLERANCE = 1e-6

    def __init__(
        self,
        client: AlfalfaClientLike,
        graph: ControlGraph,
        mapping: AlfalfaGraphMap,
        lab: VirtualBacnetLab,
    ) -> None:
        self.client = client
        self.graph = graph
        self.mapping = mapping
        self.lab = lab
        self.core = AlfalfaGraphRunner(client, graph, mapping)
        self.blocks = {block.id: block for block in graph.blocks}
        self._validate_bacnet_boundary()

    def _validate_bacnet_boundary(self) -> None:
        if self.lab.manifest.mode != "isolated-loopback":
            raise ValueError("Alfalfa BACnet qualification requires an isolated-loopback lab")
        safety = (self.lab.manifest.model_extra or {}).get("safety", {})
        if not isinstance(safety, dict):
            raise ValueError("BACnet lab safety contract is invalid")
        if (
            safety.get("live_network_routes_allowed") is not False
            or safety.get("writes_affect_virtual_objects_only") is not True
        ):
            raise ValueError("BACnet lab safety contract does not deny live-network writes")

        errors: list[str] = []
        for binding in self.mapping.outputs:
            point = self.lab.manifest.point_index.get(binding.graph_input)
            if point is None:
                errors.append(f"graph input {binding.graph_input!r} has no BACnet object")
                continue
            if point.get("scenario_injectable") is not True:
                errors.append(
                    f"graph input {binding.graph_input!r} is not an injectable BACnet input"
                )
            self._check_type(binding.graph_input, point, errors)
        for binding in self.mapping.inputs:
            point = self.lab.manifest.point_index.get(binding.graph_output)
            if point is None:
                errors.append(f"graph output {binding.graph_output!r} has no BACnet object")
                continue
            if point.get("command_capture") is not True:
                errors.append(
                    f"graph output {binding.graph_output!r} is not a writable BACnet command"
                )
            self._check_type(binding.graph_output, point, errors)
        if errors:
            raise ValueError("BACnet graph boundary is incomplete: " + "; ".join(errors))

    def _check_type(
        self,
        block_id: str,
        point: dict[str, Any],
        errors: list[str],
    ) -> None:
        block = self.blocks[block_id]
        expected = (
            "boolean"
            if block.kind in {BlockKind.BOOLEAN_INPUT, BlockKind.BOOLEAN_OUTPUT}
            else "numeric"
        )
        if point.get("data_type") != expected:
            errors.append(
                f"BACnet point {block_id!r} is {point.get('data_type')!r}, expected {expected!r}"
            )

    @staticmethod
    def _normalize_protocol_value(value: Any, *, boolean: bool, label: str) -> float | bool:
        if boolean:
            if isinstance(value, bool):
                return value
            text = str(value).lower()
            if text in {"active", "1", "true"}:
                return True
            if text in {"inactive", "0", "false"}:
                return False
            raise ValueError(f"BACnet value {label} is not boolean-like: {value!r}")
        if isinstance(value, bool):
            raise ValueError(f"BACnet value {label} is unexpectedly Boolean")
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"BACnet value {label} is not numeric: {value!r}") from exc
        if not math.isfinite(numeric):
            raise ValueError(f"BACnet value {label} is not finite")
        return numeric

    @staticmethod
    def _multistate_value(value: float | bool, label: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"BACnet multi-state value {label} is unexpectedly Boolean")
        numeric = float(value)
        if not math.isfinite(numeric) or not numeric.is_integer() or numeric < 1:
            raise ValueError(
                f"BACnet multi-state value {label} must be a positive integer, got {value!r}"
            )
        return int(numeric)

    async def _read_point(self, application: Any, point_name: str) -> tuple[float | bool, dict]:
        binding = self.lab.manifest.point_index[point_name]
        address = str(binding["network_address"])
        object_identifier = str(binding["object_identifier"])
        raw = await asyncio.wait_for(
            application.read_property(address, object_identifier, "present-value"),
            timeout=self.READ_TIMEOUT_SECONDS,
        )
        block = self.blocks[point_name]
        boolean = block.kind in {BlockKind.BOOLEAN_INPUT, BlockKind.BOOLEAN_OUTPUT}
        value = self._normalize_protocol_value(raw, boolean=boolean, label=point_name)
        return value, {
            "address": address,
            "object_identifier": object_identifier,
            "property": "present-value",
            "value": value,
        }

    async def _write_point(
        self,
        application: Any,
        point_name: str,
        value: float | bool,
    ) -> dict:
        binding = self.lab.manifest.point_index[point_name]
        address = str(binding["network_address"])
        object_identifier = str(binding["object_identifier"])
        block = self.blocks[point_name]
        boolean = block.kind == BlockKind.BOOLEAN_OUTPUT
        object_type = object_identifier.rsplit(",", 1)[0]
        if boolean:
            wire_value: float | int | str = "active" if bool(value) else "inactive"
        elif object_type.startswith("multi-state-"):
            wire_value = self._multistate_value(value, point_name)
        else:
            wire_value = float(value)
        await asyncio.wait_for(
            application.write_property(
                address,
                object_identifier,
                "present-value",
                wire_value,
                priority=self.WRITE_PRIORITY,
            ),
            timeout=self.READ_TIMEOUT_SECONDS,
        )
        readback, read_evidence = await self._read_point(application, point_name)
        matched = (
            readback is bool(value)
            if boolean
            else math.isclose(
                float(readback),
                float(value),
                rel_tol=self.PROTOCOL_RELATIVE_TOLERANCE,
                abs_tol=self.PROTOCOL_ABSOLUTE_TOLERANCE,
            )
        )
        if not matched:
            raise ValueError(
                f"BACnet command readback mismatch for {point_name}: "
                f"command={value!r}, readback={readback!r}"
            )
        return {
            "address": address,
            "object_identifier": object_identifier,
            "property": "present-value",
            "priority": self.WRITE_PRIORITY,
            "command": value,
            "readback": readback,
            "matched": True,
            "readback_transaction": read_evidence,
        }

    def _controller_application(self) -> Any:
        from bacpypes3.app import Application

        used_instances = set(self.lab.device_configs)
        instance = 4_194_302
        while instance in used_instances:
            instance -= 1
        return Application.from_args(
            SimpleNamespace(
                vendoridentifier=999,
                instance=instance,
                name="BACTalk-Alfalfa-Controller",
                address=f"127.0.0.1/32:{_free_loopback_udp_port()}",
                foreign=None,
                network=0,
                ttl=30,
                bbmd=None,
            )
        )

    async def run(
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
            or not 1 <= steps <= self.core.MAX_STEPS
        ):
            raise ValueError(f"steps must be an integer from 1 through {self.core.MAX_STEPS}")
        if not math.isfinite(step_seconds) or step_seconds <= 0:
            raise ValueError("step_seconds must be positive and finite")
        model_path = model_path.resolve()
        if not model_path.is_file():
            raise FileNotFoundError(model_path)

        run_id: str | None = None
        started = False
        stopped_status: str | None = None
        application: Any = None
        status_after_start: str | None = None
        runtime_inputs: list[str] = []
        current_outputs: dict[str, Any] = {}
        trajectory: list[dict[str, Any]] = []
        end = start + timedelta(seconds=steps * step_seconds)
        try:
            await self.lab.start()
            application = self._controller_application()
            await asyncio.sleep(0.05)

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
            previous_time = self.client.get_sim_time(run_id)
            for index in range(steps):
                injected_inputs, initial_output_values = self.core._graph_inputs(
                    current_outputs,
                    allow_initial_values=index == 0,
                )
                for point_name, value in injected_inputs.items():
                    point = self.lab.manifest.point_index[point_name]
                    object_identifier = str(point["object_identifier"])
                    injected_value = (
                        self._multistate_value(value, point_name)
                        if object_identifier.startswith("multi-state-")
                        else value
                    )
                    self.lab.set_present_value(point_name, injected_value)

                graph_inputs: dict[str, float | bool] = {}
                protocol_reads: dict[str, dict] = {}
                for point_name in sorted(injected_inputs):
                    value, transaction = await self._read_point(application, point_name)
                    injected = injected_inputs[point_name]
                    matched = (
                        value is injected
                        if isinstance(injected, bool)
                        else math.isclose(
                            float(value),
                            float(injected),
                            rel_tol=self.PROTOCOL_RELATIVE_TOLERANCE,
                            abs_tol=self.PROTOCOL_ABSOLUTE_TOLERANCE,
                        )
                    )
                    transaction.update({"injected": injected, "matched": matched})
                    if not matched:
                        raise ValueError(
                            f"BACnet sensor readback mismatch for {point_name}: "
                            f"injected={injected!r}, readback={value!r}"
                        )
                    graph_inputs[point_name] = value
                    protocol_reads[point_name] = transaction

                controller_values = interpreter.evaluate(
                    graph_inputs,
                    step_seconds=0.0 if index == 0 else step_seconds,
                )
                protocol_writes: dict[str, dict] = {}
                readback_values = dict(controller_values)
                for binding in sorted(self.mapping.inputs, key=lambda item: item.graph_output):
                    point_name = binding.graph_output
                    transaction = await self._write_point(
                        application,
                        point_name,
                        controller_values[point_name],
                    )
                    protocol_writes[point_name] = transaction
                    readback_values[point_name] = transaction["readback"]

                commands, graph_outputs = self.core._commands(readback_values)
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
                    feedback = self.core._number(
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
                        "bacnet_reads": protocol_reads,
                        "bacnet_writes": protocol_writes,
                    }
                )
                current_outputs = advanced_outputs
                previous_time = advanced_time
        finally:
            if application is not None:
                application.close()
            self.lab.close()
            if run_id is not None and started:
                self.client.stop(run_id)
                stopped_status = str(self.client.status(run_id))

        if stopped_status is None or stopped_status.upper() != "COMPLETE":
            raise ValueError(f"Alfalfa did not stop cleanly: {stopped_status!r}")
        manifest_path = self.lab.root / "manifest.json"
        manifest_sha256 = (
            _sha256(manifest_path)
            if manifest_path.is_file()
            else hashlib.sha256(
                canonical_json(self.lab.manifest).encode("utf-8")
            ).hexdigest()
        )
        read_count = sum(len(sample["bacnet_reads"]) for sample in trajectory)
        write_count = sum(len(sample["bacnet_writes"]) for sample in trajectory)
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
            "control_transport": {
                "kind": "bacnet_ip_loopback",
                "protocol": "BACnet/IP over UDP",
                "controller_runtime": "BACTalk GraphInterpreter",
                "write_priority": self.WRITE_PRIORITY,
                "numeric_relative_tolerance": self.PROTOCOL_RELATIVE_TOLERANCE,
                "numeric_absolute_tolerance": self.PROTOCOL_ABSOLUTE_TOLERANCE,
                "manifest_sha256": manifest_sha256,
                "mapped_point_count": len(self.lab.manifest.point_index),
                "read_transaction_count": read_count,
                "write_transaction_count": write_count,
                "readbacks_matched": True,
                "bind_scope": "127.0.0.1/32",
                "live_network_routes_allowed": False,
                "writes_affect_virtual_objects_only": True,
                "licensed_niagara_runtime": False,
            },
            "live_building_writes": False,
        }
