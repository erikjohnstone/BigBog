from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import signal
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bactalk.domain import (
    AssertionResult,
    BacnetDeviceSpec,
    ComparisonOperator,
    DataType,
    JobSpec,
    ScenarioResult,
    TestReport,
    canonical_json,
)

SUPPORTED_OBJECT_TYPES = {
    "analog-input",
    "analog-output",
    "analog-value",
    "binary-input",
    "binary-output",
    "binary-value",
    "multi-state-input",
    "multi-state-output",
    "multi-state-value",
}

_UNIT_ALIASES = {
    "%": "percent",
    "percent": "percent",
    "°f": "degreesFahrenheit",
    "degf": "degreesFahrenheit",
    "degrees fahrenheit": "degreesFahrenheit",
    "°c": "degreesCelsius",
    "degc": "degreesCelsius",
    "degrees celsius": "degreesCelsius",
    "cfm": "cubicFeetPerMinute",
    "gpm": "usGallonsPerMinute",
    "pa": "pascals",
    "in. wc": "inchesOfWater",
    "in wc": "inchesOfWater",
    "kw": "kilowatts",
    "w": "watts",
    "ppm": "partsPerMillion",
}

_INDEPENDENT_SIMULATOR_OBJECT_TYPES = {
    "analog-input": "analogInput",
    "analog-output": "analogOutput",
    "analog-value": "analogValue",
    "binary-input": "binaryInput",
    "binary-output": "binaryOutput",
    "binary-value": "binaryValue",
    "multi-state-input": "multiStateInput",
    "multi-state-output": "multiStateOutput",
    "multi-state-value": "multiStateValue",
}


class LabObjectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_identifier: str = Field(pattern=r"^[a-z-]+,[0-9]+$")
    object_name: str = Field(min_length=1, max_length=500)
    source_object_name: str = Field(min_length=1, max_length=500)
    point_name: str | None = Field(default=None, max_length=120)
    data_type: DataType
    present_value: float | bool
    units: str | None = None
    controller_writable: bool
    scenario_injectable: bool
    command_capture: bool
    number_of_states: int | None = Field(default=None, ge=2, le=65_535)

    @model_validator(mode="after")
    def supported_object_and_value(self) -> LabObjectConfig:
        object_type = self.object_identifier.rsplit(",", 1)[0]
        if object_type not in SUPPORTED_OBJECT_TYPES:
            raise ValueError(f"unsupported BACnet lab object type: {object_type}")
        if object_type.startswith("binary-") and self.data_type != DataType.BOOLEAN:
            raise ValueError("binary BACnet objects require boolean data type")
        if not object_type.startswith("binary-") and self.data_type != DataType.NUMERIC:
            raise ValueError("analog and multi-state BACnet objects require numeric data type")
        if object_type.startswith("multi-state-") and self.number_of_states is None:
            self.number_of_states = max(2, int(float(self.present_value)), 16)
        return self


class LabDeviceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_instance: int = Field(ge=0, le=4_194_302)
    device_name: str = Field(min_length=1, max_length=500)
    vendor_id: int = Field(default=999, ge=0, le=65_535)
    source_address: str
    source_transport: Literal["bacnet_ip", "mstp"]
    source_network_number: int | None = Field(default=None, ge=1, le=65_534)
    source_mac_address: int | None = Field(default=None, ge=0, le=254)
    bind_address: str = Field(pattern=r"^127\.0\.0\.1/32:[0-9]+$")
    network_address: str = Field(pattern=r"^127\.0\.0\.1:[0-9]+$")
    objects: list[LabObjectConfig] = Field(min_length=1, max_length=50_000)

    @model_validator(mode="after")
    def unique_objects(self) -> LabDeviceConfig:
        identifiers = [item.object_identifier for item in self.objects]
        names = [item.object_name for item in self.objects]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("virtual BACnet object identifiers must be unique")
        if len(names) != len(set(names)):
            raise ValueError("virtual BACnet object names must be unique")
        return self


class BacnetLabManifest(BaseModel):
    model_config = ConfigDict(extra="allow")

    format: Literal["bactalk.bacnet-lab.v1"]
    mode: Literal["isolated-loopback"]
    devices: list[dict[str, Any]]
    point_index: dict[str, dict[str, Any]]
    scenario_file: str


@dataclass(frozen=True)
class BacnetLabArtifact:
    relative_path: str
    content: str


@dataclass(frozen=True)
class BacnetLabExport:
    artifacts: list[BacnetLabArtifact]
    manifest: dict[str, Any]


def _source_transport(device: BacnetDeviceSpec) -> str:
    return str(getattr(device, "transport", "bacnet_ip"))


def _default_value(job: JobSpec, device: BacnetDeviceSpec, object_id: str) -> float | bool:
    scanned = next(item for item in device.objects if item.object_id == object_id)
    if isinstance(scanned.present_value, (float, int, bool)):
        return scanned.present_value
    for point in job.points:
        if point.bacnet_object != object_id:
            continue
        if point.bacnet_device_instance not in {None, device.device_instance}:
            continue
        return point.default
    return False if scanned.data_type == DataType.BOOLEAN else 0.0


def _point_name(job: JobSpec, device: BacnetDeviceSpec, object_id: str) -> str | None:
    for point in job.points:
        if point.bacnet_object != object_id:
            continue
        if point.bacnet_device_instance in {None, device.device_instance}:
            return point.name
    return None


def _bacnet_units(value: str | None) -> str | None:
    if value is None:
        return None
    return _UNIT_ALIASES.get(value.strip().lower(), "noUnits")


def _unique_object_name(source_name: str, object_id: str, used: set[str]) -> str:
    if source_name not in used:
        used.add(source_name)
        return source_name
    candidate = f"{source_name} [{object_id}]"
    if candidate in used:
        raise ValueError(f"cannot produce unique BACnet object name for {object_id}")
    used.add(candidate)
    return candidate


def _scenario_contract(job: JobSpec, point_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    all_unmapped: set[str] = set()
    for case in job.acceptance_tests:
        raw_phases = (
            case.timeline
            if case.timeline
            else [
                SimpleNamespace(
                    name=case.name,
                    inputs=case.inputs,
                    expectations=case.expectations,
                    repeat=case.repeat,
                    step_seconds=case.step_seconds,
                )
            ]
        )
        phases: list[dict[str, Any]] = []
        for phase in raw_phases:
            mapped_inputs = []
            mapped_expectations = []
            unmapped = []
            invalid_inputs = []
            invalid_expectations = []
            for point, value in phase.inputs.items():
                mapping = point_index.get(point)
                if mapping is None:
                    unmapped.append(point)
                    all_unmapped.add(point)
                elif not mapping["scenario_injectable"]:
                    invalid_inputs.append(point)
                    all_unmapped.add(point)
                else:
                    mapped_inputs.append({"point": point, "value": value, **mapping})
            for expectation in phase.expectations:
                mapping = point_index.get(expectation.target)
                if mapping is None:
                    unmapped.append(expectation.target)
                    all_unmapped.add(expectation.target)
                elif not mapping["command_capture"]:
                    invalid_expectations.append(expectation.target)
                    all_unmapped.add(expectation.target)
                else:
                    mapped_expectations.append({**expectation.model_dump(mode="json"), **mapping})
            phases.append(
                {
                    "name": phase.name,
                    "repeat": phase.repeat,
                    "step_seconds": phase.step_seconds,
                    "inputs": mapped_inputs,
                    "expectations": mapped_expectations,
                    "unmapped_points": sorted(set(unmapped)),
                    "invalid_input_points": sorted(set(invalid_inputs)),
                    "invalid_expectation_points": sorted(set(invalid_expectations)),
                }
            )
        cases.append({"name": case.name, "phases": phases})
    return {
        "format": "bactalk.bacnet-lab-scenarios.v1",
        "cases": cases,
        "fully_mapped": not all_unmapped,
        "unmapped_points": sorted(all_unmapped),
        "execution": {
            "wall_clock_required_for_external_controller_timers": True,
            "automatic_result_capture_implemented": True,
            "reason": (
                "The runner drives mapped virtual inputs and grades mapped virtual outputs while "
                "an external controller is connected. Licensed Niagara execution remains a "
                "separate runtime-qualification gate."
            ),
        },
    }


def _independent_simulator_device(
    source: BacnetDeviceSpec,
    config: LabDeviceConfig,
) -> dict[str, Any]:
    """Project a scan into the pinned MIT bacnet-simulator device contract."""

    points: list[dict[str, Any]] = []
    for item in config.objects:
        object_type, raw_instance = item.object_identifier.rsplit(",", 1)
        point: dict[str, Any] = {
            "object_type": _INDEPENDENT_SIMULATOR_OBJECT_TYPES[object_type],
            "object_instance": int(raw_instance),
            "object_name": item.object_name,
            "description": item.source_object_name,
            "present_value": item.present_value,
            "units": item.units or "",
            "cov_increment": 0.0 if item.data_type == DataType.BOOLEAN else 0.5,
        }
        if object_type.startswith("multi-state-"):
            count = item.number_of_states or 16
            point["state_text"] = [f"State {index}" for index in range(1, count + 1)]
            point["present_value"] = max(1, min(count, int(float(item.present_value))))
        points.append(point)
    return {
        "device_id": source.device_instance,
        "name": source.name,
        "description": (
            "BACTalk independent-oracle mirror; source address is retained only in the "
            "signed primary manifest"
        ),
        "points": points,
    }


def build_bacnet_lab_export(job: JobSpec, *, base_port: int = 47_820) -> BacnetLabExport | None:
    """Mirror a scan as isolated BACnet/IP devices without contacting the source network."""

    if job.bacnet_scan is None:
        return None
    if base_port < 1024 or base_port + len(job.bacnet_scan.devices) > 65_535:
        raise ValueError("BACnet lab port range is invalid")

    artifacts: list[BacnetLabArtifact] = []
    devices: list[dict[str, Any]] = []
    point_index: dict[str, dict[str, Any]] = {}
    ordered_devices = sorted(
        job.bacnet_scan.devices,
        key=lambda item: item.device_instance,
    )
    for index, source in enumerate(ordered_devices):
        port = base_port + index
        used_names: set[str] = set()
        objects: list[LabObjectConfig] = []
        for scanned in source.objects:
            object_type = scanned.object_id.rsplit(",", 1)[0]
            if object_type not in SUPPORTED_OBJECT_TYPES:
                raise ValueError(
                    f"BACnet lab cannot emulate object type {object_type!r} on device "
                    f"{source.device_instance}"
                )
            point_name = _point_name(job, source, scanned.object_id)
            item = LabObjectConfig(
                object_identifier=scanned.object_id,
                object_name=_unique_object_name(scanned.name, scanned.object_id, used_names),
                source_object_name=scanned.name,
                point_name=point_name,
                data_type=scanned.data_type,
                present_value=_default_value(job, source, scanned.object_id),
                units=_bacnet_units(scanned.units),
                controller_writable=scanned.writable,
                scenario_injectable=object_type.endswith("-input"),
                command_capture=object_type.endswith(("-output", "-value")) and scanned.writable,
            )
            objects.append(item)
            if point_name is not None:
                if point_name in point_index:
                    raise ValueError(f"point {point_name} maps to more than one BACnet lab object")
                point_index[point_name] = {
                    "device_instance": source.device_instance,
                    "network_address": f"127.0.0.1:{port}",
                    "object_identifier": scanned.object_id,
                    "data_type": scanned.data_type.value,
                    "scenario_injectable": item.scenario_injectable,
                    "command_capture": item.command_capture,
                }
        config = LabDeviceConfig(
            device_instance=source.device_instance,
            device_name=source.name,
            vendor_id=source.vendor_id if source.vendor_id is not None else 999,
            source_address=source.address,
            source_transport=_source_transport(source),
            source_network_number=getattr(source, "network_number", None),
            source_mac_address=getattr(source, "mac_address", None),
            bind_address=f"127.0.0.1/32:{port}",
            network_address=f"127.0.0.1:{port}",
            objects=objects,
        )
        relative_path = f"devices/{source.device_instance}.json"
        artifacts.append(
            BacnetLabArtifact(relative_path=relative_path, content=canonical_json(config))
        )
        artifacts.append(
            BacnetLabArtifact(
                relative_path=(f"independent-simulator/devices/{source.device_instance}.yaml"),
                # JSON is a strict YAML subset. Keeping one canonical serializer avoids an
                # additional production dependency while the independent runtime still loads
                # this through yaml.safe_load.
                content=canonical_json(_independent_simulator_device(source, config)),
            )
        )
        devices.append(
            {
                "device_instance": source.device_instance,
                "device_name": source.name,
                "source_transport": _source_transport(source),
                "emulation_transport": "bacnet_ip_loopback",
                "network_address": config.network_address,
                "config": relative_path,
                "object_count": len(objects),
                "scenario_injectable_objects": sum(item.scenario_injectable for item in objects),
                "command_capture_objects": sum(item.command_capture for item in objects),
            }
        )

    scenario = _scenario_contract(job, point_index)
    artifacts.append(
        BacnetLabArtifact(
            relative_path="acceptance-scenarios.json",
            content=canonical_json(scenario),
        )
    )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=["point_name", "device_instance", "network_address", "object_identifier"],
        lineterminator="\n",
    )
    writer.writeheader()
    for point_name, mapping in sorted(point_index.items()):
        writer.writerow(
            {
                "point_name": point_name,
                "device_instance": mapping["device_instance"],
                "network_address": mapping["network_address"],
                "object_identifier": mapping["object_identifier"],
            }
        )
    artifacts.append(BacnetLabArtifact(relative_path="point-map.csv", content=stream.getvalue()))
    artifacts.append(
        BacnetLabArtifact(
            relative_path="run-lab.py",
            content=(
                "from bactalk.integrations.bacnet_lab import main\n\n"
                "if __name__ == '__main__':\n"
                "    main()\n"
            ),
        )
    )
    artifacts.append(
        BacnetLabArtifact(
            relative_path="probe-with-bac0.py",
            content=(
                "from bactalk.integrations.bacnet_lab import bac0_probe_main\n\n"
                "if __name__ == '__main__':\n"
                "    bac0_probe_main()\n"
            ),
        )
    )
    artifacts.append(
        BacnetLabArtifact(
            relative_path="run-acceptance.py",
            content=(
                "from bactalk.integrations.bacnet_lab import acceptance_main\n\n"
                "if __name__ == '__main__':\n"
                "    acceptance_main()\n"
            ),
        )
    )
    independent_settings = {
        "http": {"host": "127.0.0.1", "port": 18_080},
        "bacnet": {"ip": "127.0.0.1", "prefix": 32, "port_start": base_port},
        "db_path": "data/bacnet_lab.db",
        "log_level": "INFO",
        "devices_dir": "devices",
        "sync_interval": 0.25,
        "snapshot_interval": 300,
        "retention_days": 30,
        "webhook_allowed_hosts": ["localhost", "127.0.0.1"],
    }
    artifacts.extend(
        [
            BacnetLabArtifact(
                relative_path="independent-simulator/settings.yaml",
                content=canonical_json(independent_settings),
            ),
            BacnetLabArtifact(
                relative_path="independent-simulator/run.py",
                content=(
                    "import os\n"
                    "from pathlib import Path\n\n"
                    "import uvicorn\n"
                    "from bacnet_lab.adapters.http.app import create_app\n"
                    "from bacnet_lab.infrastructure.config import load_settings\n\n"
                    "root = Path(__file__).resolve().parent\n"
                    "os.chdir(root)\n"
                    "settings = load_settings('settings.yaml')\n"
                    "uvicorn.run(create_app(settings=settings), host=settings.http.host, "
                    "port=settings.http.port, log_level=settings.log_level.lower())\n"
                ),
            ),
        ]
    )
    try:
        bacpypes_version = metadata.version("bacpypes3")
    except metadata.PackageNotFoundError:
        bacpypes_version = None
    manifest = {
        "format": "bactalk.bacnet-lab.v1",
        "mode": "isolated-loopback",
        "source": job.bacnet_scan.source,
        "bacpypes3_version": bacpypes_version,
        "devices": devices,
        "point_index": point_index,
        "scenario_file": "acceptance-scenarios.json",
        "launcher": "run-lab.py",
        "launch_command": "python run-lab.py manifest.json",
        "independent_probe": "probe-with-bac0.py",
        "probe_command": "python probe-with-bac0.py manifest.json",
        "acceptance_runner": "run-acceptance.py",
        "acceptance_command": "python run-acceptance.py manifest.json --startup-seconds 10",
        "independent_protocol_oracle": {
            "implementation": "quentinnippert/bacnet-simulator",
            "license": "MIT",
            "revision": "d06fccb963abd4c773f6b5dd74e12f9ec79a5edd",
            "config_root": "independent-simulator",
            "settings": "independent-simulator/settings.yaml",
            "launcher": "independent-simulator/run.py",
            "launch_command": "python run.py",
            "capabilities": [
                "priority_arrays",
                "relinquish",
                "change_of_value",
                "device_offline_recovery",
                "rest_observation",
            ],
            "limitations": (
                "Independent simulator values and outputs are commandable according to object "
                "type; per-point source write permissions remain enforced by the primary "
                "BACTalk lab contract."
            ),
        },
        "safety": {
            "bind_scope": "127.0.0.1/32",
            "live_network_discovery_performed": False,
            "live_network_routes_allowed": False,
            "writes_affect_virtual_objects_only": True,
            "source_addresses_never_bound": True,
            "human_approval_does_not_enable_live_writes": True,
        },
        "transport_boundary": {
            "bacnet_ip": "Executable UDP/IP device emulation on loopback.",
            "mstp": (
                "MS/TP-origin identity and object behavior are mirrored through loopback "
                "BACnet/IP. Exact token/baud/router behavior requires the serial/HIL lane."
            ),
        },
    }
    return BacnetLabExport(artifacts=artifacts, manifest=manifest)


class VirtualBacnetLab:
    """Runtime for generated loopback-only BACnet devices."""

    def __init__(self, root: Path, manifest: BacnetLabManifest):
        self.root = root.resolve()
        self.manifest = manifest
        self.apps: list[Any] = []
        self.objects: dict[tuple[int, str], Any] = {}

    @classmethod
    def load(cls, manifest_path: Path) -> VirtualBacnetLab:
        path = manifest_path.resolve()
        manifest = BacnetLabManifest.model_validate_json(path.read_text(encoding="utf-8"))
        return cls(path.parent, manifest)

    @staticmethod
    def _application_args(config: LabDeviceConfig) -> SimpleNamespace:
        return SimpleNamespace(
            vendoridentifier=config.vendor_id,
            instance=config.device_instance,
            name=config.device_name,
            address=config.bind_address,
            foreign=None,
            network=0,
            ttl=30,
            bbmd=None,
        )

    @staticmethod
    def _object(config: LabObjectConfig) -> Any:
        from bacpypes3.errors import PropertyError
        from bacpypes3.local.analog import (
            AnalogInputObject,
            AnalogOutputObject,
            AnalogValueObject,
            AnalogValueObjectCmd,
        )
        from bacpypes3.local.binary import (
            BinaryInputObject,
            BinaryOutputObject,
            BinaryValueObject,
            BinaryValueObjectCmd,
        )
        from bacpypes3.local.multistate import (
            MultiStateInputObject,
            MultiStateOutputObject,
            MultiStateValueObject,
        )
        from bacpypes3.local.oos import OutOfService

        class ReadOnlyPresentValue:
            async def write_property(
                self: Any,
                attr: Any,
                value: Any,
                index: int | None = None,
                priority: int | None = None,
            ) -> None:
                normalized = str(attr).replace("-", "").lower()
                if normalized in {"presentvalue", "85"}:
                    raise PropertyError("writeAccessDenied")
                await super().write_property(attr, value, index, priority)

        class InjectableAnalogInput(OutOfService, AnalogInputObject):
            pass

        class InjectableBinaryInput(OutOfService, BinaryInputObject):
            pass

        class InjectableMultiStateInput(OutOfService, MultiStateInputObject):
            pass

        object_type, instance_text = config.object_identifier.rsplit(",", 1)
        type_parts = object_type.split("-")
        bacpypes_type = type_parts[0] + "".join(part.title() for part in type_parts[1:])
        object_identifier = (bacpypes_type, int(instance_text))
        common: dict[str, Any] = {
            "objectIdentifier": object_identifier,
            "objectName": config.object_name,
            "description": f"BACTalk isolated lab mirror of {config.source_object_name}",
            "statusFlags": [0, 0, 0, 0],
        }
        if object_type.startswith("binary-"):
            common.update(
                presentValue="active" if config.present_value else "inactive",
                eventState="normal",
                outOfService=False,
            )
            if object_type in {"binary-input", "binary-output"}:
                common["polarity"] = "normal"
            classes: dict[str, type[Any]] = {
                "binary-input": InjectableBinaryInput,
                "binary-output": BinaryOutputObject,
                "binary-value": (
                    BinaryValueObjectCmd
                    if config.controller_writable
                    else type("ReadOnlyBinaryValue", (ReadOnlyPresentValue, BinaryValueObject), {})
                ),
            }
        elif object_type.startswith("multi-state-"):
            common.update(
                presentValue=max(1, int(float(config.present_value))),
                eventState="normal",
                outOfService=False,
                numberOfStates=config.number_of_states or 16,
            )
            classes = {
                "multi-state-input": InjectableMultiStateInput,
                "multi-state-output": MultiStateOutputObject,
                "multi-state-value": MultiStateValueObject,
            }
        else:
            common.update(
                presentValue=float(config.present_value),
                covIncrement=0.1,
                units=config.units or "noUnits",
                outOfService=False,
                eventState="normal",
            )
            classes = {
                "analog-input": InjectableAnalogInput,
                "analog-output": AnalogOutputObject,
                "analog-value": (
                    AnalogValueObjectCmd
                    if config.controller_writable
                    else type("ReadOnlyAnalogValue", (ReadOnlyPresentValue, AnalogValueObject), {})
                ),
            }
        return classes[object_type](**common)

    async def start(self) -> None:
        from bacpypes3.app import Application

        if self.apps:
            raise RuntimeError("BACnet lab is already running")
        try:
            for summary in self.manifest.devices:
                config_path = (self.root / str(summary["config"])).resolve()
                if not config_path.is_relative_to(self.root):
                    raise ValueError("BACnet lab device config escapes its manifest directory")
                config = LabDeviceConfig.model_validate_json(
                    config_path.read_text(encoding="utf-8")
                )
                if not config.bind_address.startswith("127.0.0.1/32:"):
                    raise ValueError("BACnet lab refuses non-loopback bind addresses")
                app = Application.from_args(self._application_args(config))
                self.apps.append(app)
                for object_config in config.objects:
                    obj = self._object(object_config)
                    app.add_object(obj)
                    self.objects[(config.device_instance, object_config.object_identifier)] = obj
            await asyncio.sleep(0)
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        for app in reversed(self.apps):
            app.close()
        self.apps.clear()
        self.objects.clear()

    def set_present_value(self, point_name: str, value: float | bool) -> None:
        mapping = self.manifest.point_index.get(point_name)
        if mapping is None:
            raise KeyError(point_name)
        if not mapping.get("scenario_injectable", False):
            raise ValueError(f"point {point_name} is not an injectable BACnet input")
        obj = self.objects[(int(mapping["device_instance"]), str(mapping["object_identifier"]))]
        obj.presentValue = "active" if value is True else "inactive" if value is False else value

    def get_present_value(self, point_name: str) -> float | bool:
        mapping = self.manifest.point_index.get(point_name)
        if mapping is None:
            raise KeyError(point_name)
        obj = self.objects[(int(mapping["device_instance"]), str(mapping["object_identifier"]))]
        value = obj.presentValue
        if str(value) in {"active", "inactive"}:
            return str(value) == "active"
        return float(value)

    @staticmethod
    def _expectation_passes(observed: float | bool, expectation: dict[str, Any]) -> bool:
        operator = ComparisonOperator(expectation["operator"])
        expected = expectation["value"]
        tolerance = float(expectation.get("tolerance", 0.0))
        if operator == ComparisonOperator.EQUAL:
            if isinstance(expected, bool):
                return isinstance(observed, bool) and observed is expected
            return not isinstance(observed, bool) and (
                abs(float(observed) - float(expected)) <= tolerance
            )
        if operator == ComparisonOperator.NOT_EQUAL:
            return not VirtualBacnetLab._expectation_passes(
                observed,
                {**expectation, "operator": ComparisonOperator.EQUAL.value},
            )
        if isinstance(observed, bool) or isinstance(expected, bool):
            return False
        numeric = float(observed)
        target = float(expected)
        if operator == ComparisonOperator.GREATER_THAN:
            return numeric > target - tolerance
        if operator == ComparisonOperator.GREATER_THAN_OR_EQUAL:
            return numeric >= target - tolerance
        if operator == ComparisonOperator.LESS_THAN:
            return numeric < target + tolerance
        if operator == ComparisonOperator.LESS_THAN_OR_EQUAL:
            return numeric <= target + tolerance
        if operator == ComparisonOperator.BETWEEN:
            upper = expectation.get("upper")
            return upper is not None and target - tolerance <= numeric <= float(upper) + tolerance
        raise AssertionError(operator)

    async def run_acceptance_scenarios(
        self,
        *,
        time_scale: float = 1.0,
        max_steps: int = 100_000,
    ) -> TestReport:
        """Drive mapped inputs and grade outputs while a controller uses the virtual devices."""

        if not self.apps:
            raise RuntimeError("BACnet lab must be started before running acceptance scenarios")
        if time_scale <= 0 or time_scale > 100:
            raise ValueError("time_scale must be greater than zero and no more than 100")
        scenario_path = (self.root / self.manifest.scenario_file).resolve()
        if not scenario_path.is_relative_to(self.root):
            raise ValueError("BACnet lab scenario path escapes its manifest directory")
        scenario_contract = json.loads(scenario_path.read_text(encoding="utf-8"))
        results: list[ScenarioResult] = []
        executed_steps = 0
        for case in scenario_contract["cases"]:
            assertions: list[AssertionResult] = []
            samples: list[dict[str, float | bool]] = []
            for phase in case["phases"]:
                mapping_errors = {
                    **{point: "mapped BACnet object" for point in phase["unmapped_points"]},
                    **{
                        point: "scenario-injectable BACnet input"
                        for point in phase["invalid_input_points"]
                    },
                    **{
                        point: "controller-command BACnet output/value"
                        for point in phase["invalid_expectation_points"]
                    },
                }
                if mapping_errors:
                    for point, expected_mapping in mapping_errors.items():
                        assertions.append(
                            AssertionResult(
                                name=f"{phase['name']}:{point}:mapped",
                                passed=False,
                                observed="not executable through mapped BACnet role",
                                expected=expected_mapping,
                            )
                        )
                    continue
                for item in phase["inputs"]:
                    self.set_present_value(item["point"], item["value"])
                for iteration in range(int(phase["repeat"])):
                    executed_steps += 1
                    if executed_steps > max_steps:
                        raise ValueError("BACnet acceptance scenarios exceed max_steps")
                    await asyncio.sleep(float(phase["step_seconds"]) * time_scale)
                    sample: dict[str, float | bool] = {}
                    for expectation in phase["expectations"]:
                        observed = self.get_present_value(expectation["target"])
                        sample[expectation["target"]] = observed
                        passed = self._expectation_passes(observed, expectation)
                        assertions.append(
                            AssertionResult(
                                name=(
                                    f"{phase['name']}[{iteration}]:"
                                    f"{expectation['target']}:{expectation['operator']}"
                                ),
                                passed=passed,
                                observed=str(observed),
                                expected=str(
                                    expectation["value"]
                                    if expectation.get("upper") is None
                                    else [expectation["value"], expectation["upper"]]
                                ),
                            )
                        )
                    samples.append(sample)
            results.append(
                ScenarioResult(
                    name=case["name"],
                    passed=bool(assertions) and all(item.passed for item in assertions),
                    assertions=assertions,
                    samples=samples,
                )
            )
        return TestReport(
            passed=bool(results) and all(item.passed for item in results),
            scenarios=results,
            engine="bacpypes3-loopback-external-controller",
            coverage={
                "executed_steps": executed_steps,
                "mapped_point_count": len(self.manifest.point_index),
                "live_network_routes_allowed": False,
                "time_scale": time_scale,
            },
        )


async def _serve(manifest_path: Path, duration: float | None) -> None:
    lab = VirtualBacnetLab.load(manifest_path)
    await lab.start()
    try:
        if duration is not None:
            await asyncio.sleep(duration)
            return
        stopped = asyncio.Event()
        loop = asyncio.get_running_loop()
        for event in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(event, stopped.set)
            except NotImplementedError:
                pass
        await stopped.wait()
    finally:
        lab.close()


async def probe_manifest_with_bac0(
    manifest_path: Path,
    *,
    client_port: int | None = None,
) -> dict[str, Any]:
    """Read every mapped virtual point through BAC0 as an independent protocol client."""

    import BAC0

    path = manifest_path.resolve()
    manifest = BacnetLabManifest.model_validate_json(path.read_text(encoding="utf-8"))
    ports = [int(str(item["network_address"]).rsplit(":", 1)[1]) for item in manifest.devices]
    selected_port = client_port if client_port is not None else max(ports, default=47_820) + 1
    if selected_port < 1024 or selected_port > 65_535 or selected_port in ports:
        raise ValueError("BAC0 probe client port is invalid or collides with a virtual device")
    BAC0.log_level("error")
    values: dict[str, Any] = {}
    async with BAC0.start(
        ip=f"127.0.0.1/32:{selected_port}",
        deviceId=4_193_999,
        ping=False,
    ) as client:
        for point_name, mapping in sorted(manifest.point_index.items()):
            object_type, instance = str(mapping["object_identifier"]).split(",", 1)
            parts = object_type.split("-")
            bac0_type = parts[0] + "".join(part.title() for part in parts[1:])
            value = await client.read(
                f"{mapping['network_address']} {bac0_type} {instance} presentValue",
                timeout=3,
            )
            if isinstance(value, (float, int, bool, str)):
                normalized = value
            else:
                normalized = str(value)
            values[point_name] = normalized
    return {
        "format": "bactalk.bac0-probe-result.v1",
        "passed": len(values) == len(manifest.point_index),
        "point_count": len(values),
        "values": values,
        "writes_performed": False,
        "client_bind": f"127.0.0.1/32:{selected_port}",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a generated loopback-only BACTalk BACnet lab")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--duration", type=float, default=None)
    args = parser.parse_args()
    asyncio.run(_serve(args.manifest, args.duration))


def bac0_probe_main() -> None:
    parser = argparse.ArgumentParser(description="Probe a running BACTalk BACnet lab with BAC0")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--client-port", type=int, default=None)
    args = parser.parse_args()
    result = asyncio.run(probe_manifest_with_bac0(args.manifest, client_port=args.client_port))
    print(json.dumps(result, indent=2, sort_keys=True))


def acceptance_main() -> None:
    parser = argparse.ArgumentParser(
        description="Run mapped acceptance phases against an external controller"
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--startup-seconds", type=float, default=10.0)
    parser.add_argument("--time-scale", type=float, default=1.0)
    parser.add_argument("--report", type=Path, default=Path("bacnet-acceptance-report.json"))
    args = parser.parse_args()

    async def run() -> TestReport:
        lab = VirtualBacnetLab.load(args.manifest)
        await lab.start()
        try:
            await asyncio.sleep(args.startup_seconds)
            return await lab.run_acceptance_scenarios(time_scale=args.time_scale)
        finally:
            lab.close()

    report = asyncio.run(run())
    args.report.write_text(canonical_json(report), encoding="utf-8")
    print(canonical_json(report), end="")
    raise SystemExit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
