from __future__ import annotations

import csv
import io

from bactalk.demo import demo_job
from bactalk.integrations.volttron import REGISTRY_COLUMNS, build_readonly_volttron_export


def test_volttron_export_is_valid_and_forces_every_point_read_only() -> None:
    export = build_readonly_volttron_export(demo_job())

    assert export is not None
    assert export.manifest["mode"] == "observation-only"
    assert export.manifest["writes_enabled"] is False
    assert export.manifest["devices"][0]["mapped_points"] == 3
    registry = next(item for item in export.artifacts if item.relative_path.endswith(".csv"))
    rows = list(csv.DictReader(io.StringIO(registry.content)))
    assert rows
    assert list(rows[0]) == REGISTRY_COLUMNS
    assert {row["Volttron Point Name"] for row in rows} == {
        "DamperCommand",
        "ValveCommand",
        "ZoneTemp",
    }
    assert {row["Writable"] for row in rows} == {"FALSE"}
    assert rows[0]["BACnet Object Type"] == "analogOutput"


def test_volttron_export_skips_job_without_scan() -> None:
    job = demo_job().model_copy(update={"bacnet_scan": None})

    assert build_readonly_volttron_export(job) is None
