from __future__ import annotations

import json
import tempfile
from pathlib import Path

from bacnet_lab.adapters.bacnet.device_factory import load_all_devices
from bacnet_lab.infrastructure.config import load_settings

from bactalk.demo import demo_job
from bactalk.integrations.bacnet_lab import build_bacnet_lab_export


def main() -> int:
    export = build_bacnet_lab_export(demo_job(), base_port=49_120)
    if export is None:
        raise RuntimeError("demo job did not produce a BACnet lab export")
    with tempfile.TemporaryDirectory(prefix="bactalk-independent-bacnet-") as raw_root:
        root = Path(raw_root)
        for artifact in export.artifacts:
            target = root / artifact.relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(artifact.content, encoding="utf-8")
        oracle = export.manifest["independent_protocol_oracle"]
        devices_root = root / oracle["config_root"] / "devices"
        devices = load_all_devices(str(devices_root))
        settings = load_settings(str(root / oracle["settings"]))

    expected_devices = len(demo_job().bacnet_scan.devices)
    expected_objects = sum(len(device.objects) for device in demo_job().bacnet_scan.devices)
    actual_objects = sum(len(device.points) for device in devices)
    if len(devices) != expected_devices or actual_objects != expected_objects:
        raise RuntimeError("independent BACnet simulator projection lost devices or objects")
    if settings.bacnet.ip != "127.0.0.1" or settings.bacnet.prefix != 32:
        raise RuntimeError("independent BACnet simulator is not loopback constrained")
    if settings.bacnet.port_start != 49_120:
        raise RuntimeError("independent BACnet simulator port projection changed")
    commandable = sum(point.commandable for device in devices for point in device.points)
    if commandable < 1:
        raise RuntimeError("independent BACnet simulator has no commandable test object")
    print(
        json.dumps(
            {
                "schema": "bactalk.independent-bacnet-simulator-contract/v1",
                "revision": oracle["revision"],
                "device_count": len(devices),
                "object_count": actual_objects,
                "commandable_object_count": commandable,
                "loopback_only": True,
                "passed": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
