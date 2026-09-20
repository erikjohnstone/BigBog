from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Any

from bactalk.domain import (
    BacnetDeviceSpec,
    JobSpec,
    PointSpec,
    canonical_json,
    safe_component_name,
)

REGISTRY_COLUMNS = [
    "Point Name",
    "Volttron Point Name",
    "Units",
    "Unit Details",
    "BACnet Object Type",
    "Property",
    "Writable",
    "Index",
    "Notes",
]

_OBJECT_TYPES = {
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


@dataclass(frozen=True)
class VolttronArtifact:
    relative_path: str
    content: str


@dataclass(frozen=True)
class VolttronExport:
    artifacts: list[VolttronArtifact]
    manifest: dict[str, Any]


def _point_device_instance(job: JobSpec, point: PointSpec) -> int | None:
    if point.bacnet_device_instance is not None:
        return point.bacnet_device_instance
    if job.bacnet_scan is not None and len(job.bacnet_scan.devices) == 1:
        return job.bacnet_scan.devices[0].device_instance
    return None


def _registry_csv(device: BacnetDeviceSpec, points: list[PointSpec]) -> str:
    objects = {item.object_id: item for item in device.objects}
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=REGISTRY_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for point in sorted(points, key=lambda item: item.name):
        if point.bacnet_object is None:
            continue
        object_type, instance = point.bacnet_object.split(",", maxsplit=1)
        if object_type not in _OBJECT_TYPES:
            raise ValueError(f"VOLTTRON export does not support BACnet object type {object_type!r}")
        scanned = objects[point.bacnet_object]
        writer.writerow(
            {
                "Point Name": scanned.name,
                "Volttron Point Name": point.name,
                "Units": point.units or scanned.units or "",
                "Unit Details": "",
                "BACnet Object Type": _OBJECT_TYPES[object_type],
                "Property": "presentValue",
                # This export is deliberately observation-only. A writable scan never
                # becomes permission for an edge runtime to command equipment.
                "Writable": "FALSE",
                "Index": instance,
                "Notes": f"BACTalk read-only mapping: {point.label}",
            }
        )
    return stream.getvalue()


def build_readonly_volttron_export(job: JobSpec) -> VolttronExport | None:
    """Build Platform Driver artifacts without granting a BACnet write path."""

    if job.bacnet_scan is None:
        return None

    artifacts: list[VolttronArtifact] = []
    devices: list[dict[str, Any]] = []
    equipment = safe_component_name(job.equipment_name).lower()
    for device in sorted(job.bacnet_scan.devices, key=lambda item: item.device_instance):
        mapped = [
            point
            for point in job.points
            if point.bacnet_object is not None
            and _point_device_instance(job, point) == device.device_instance
        ]
        if not mapped:
            continue
        stem = f"{equipment}-{device.device_instance}"
        registry_file = f"{stem}-registry.csv"
        config_file = f"{stem}-device.json"
        config_store_key = f"devices/bactalk/{equipment}/{device.device_instance}"
        registry_key = f"bactalk-{equipment}-{device.device_instance}-registry.csv"
        registry = _registry_csv(device, mapped)
        device_config = {
            "driver_config": {
                "device_address": device.address,
                "device_id": device.device_instance,
            },
            "driver_type": "bacnet",
            "registry_config": f"config://{registry_key}",
            "interval": 15,
            "timezone": "UTC",
            "reservation_required_for_write": True,
        }
        artifacts.extend(
            [
                VolttronArtifact(relative_path=registry_file, content=registry),
                VolttronArtifact(
                    relative_path=config_file,
                    content=canonical_json(device_config),
                ),
            ]
        )
        devices.append(
            {
                "device_instance": device.device_instance,
                "device_name": device.name,
                "config_file": config_file,
                "registry_file": registry_file,
                "registry_config_store_key": registry_key,
                "device_config_store_key": config_store_key,
                "mapped_points": len(mapped),
                "writes_enabled": False,
            }
        )

    manifest = {
        "format": "bactalk.volttron-readonly.v1",
        "mode": "observation-only",
        "writes_enabled": False,
        "source": job.bacnet_scan.source,
        "devices": devices,
        "safety": {
            "registry_writable_forced_false": True,
            "command_capability_emitted": False,
            "live_network_connection_not_performed": True,
            "human_approval_does_not_enable_live_writes": True,
        },
    }
    return VolttronExport(artifacts=artifacts, manifest=manifest)
