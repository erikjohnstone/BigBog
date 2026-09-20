#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import json
from importlib.metadata import version

from volttron.driver.interfaces.bacnet.bacnet import BacnetPointConfig, BacnetRemoteConfig

from bactalk.demo import demo_job
from bactalk.integrations.volttron import build_readonly_volttron_export

EXPECTED_VERSIONS = {
    "volttron": "11.0.0rc3",
    "volttron-core": "2.0.0rc34",
    "volttron-platform-driver": "2.0.0rc7",
    "volttron-lib-bacnet-driver": "2.0.0rc3",
    "volttron-lib-fake-driver": "2.0.0rc0",
}


def main() -> None:
    installed = {name: version(name) for name in EXPECTED_VERSIONS}
    if installed != EXPECTED_VERSIONS:
        raise SystemExit(f"VOLTTRON version drift: expected {EXPECTED_VERSIONS}, got {installed}")

    export = build_readonly_volttron_export(demo_job())
    if export is None:
        raise SystemExit("demo job did not produce a VOLTTRON export")
    registry = next(item for item in export.artifacts if item.relative_path.endswith(".csv"))
    config = next(item for item in export.artifacts if item.relative_path.endswith(".json"))
    points = [
        BacnetPointConfig.model_validate(row)
        for row in csv.DictReader(io.StringIO(registry.content))
    ]
    device = json.loads(config.content)
    remote = BacnetRemoteConfig.model_validate(
        {**device["driver_config"], "driver_type": device["driver_type"]}
    )
    if not points or any(point.writable for point in points):
        raise SystemExit("read-only invariant failed")
    print(
        f"validated {len(points)} read-only points for device {remote.device_id} "
        f"against VOLTTRON {installed['volttron']}"
    )


if __name__ == "__main__":
    main()
