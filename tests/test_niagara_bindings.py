from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from bactalk.demo import demo_job
from bactalk.domain import JobSpec, PointRole, PointSpec
from bactalk.integrations.niagara_bindings import build_niagara_binding_export
from bactalk.sequences.g36_vav import build_g36_vav_reheat


def _job_with_exact_ords() -> JobSpec:
    payload = demo_job().model_dump(mode="json")
    priorities = {"DamperCommand": 8, "ValveCommand": 10}
    for point in payload["points"]:
        if point["bacnet_object"] is None:
            continue
        point["niagara_ord"] = (
            "station:|slot:/Config/Drivers/BacnetNetwork/VAV_12/Points/" + point["name"]
        )
        if point["name"] in priorities:
            point["niagara_write_priority"] = priorities[point["name"]]
    return JobSpec.model_validate(payload)


def test_exact_niagara_ords_generate_typed_input_and_command_links() -> None:
    job = _job_with_exact_ords()
    graph = build_g36_vav_reheat(job)

    export = build_niagara_binding_export(job, graph)
    manifest = export.manifest
    by_point = {item["point"]: item for item in manifest["bindings"]}

    assert manifest["binding_count"] == 3
    assert manifest["all_mapped_points_have_exact_ords"] is True
    assert manifest["unbound_mapped_points"] == []
    assert by_point["ZoneTemp"]["direction"] == "proxy_to_program"
    assert by_point["ZoneTemp"]["target_slot"] == "in16"
    assert by_point["DamperCommand"]["direction"] == "program_to_proxy"
    assert by_point["DamperCommand"]["target_slot"] == "in8"
    assert by_point["ValveCommand"]["target_slot"] == "in10"
    assert by_point["DamperCommand"]["source_ord"].startswith(
        "station:|slot:/Config/Drivers/BACnetNetwork/ExampleCampus/VAV_12/"
    )
    java = next(item.content for item in export.artifacts if item.relative_path.endswith(".java"))
    assert "Target slot already linked" in java
    assert "target.add(null, link);" in java
    readback = json.loads(
        next(
            item.content
            for item in export.artifacts
            if item.relative_path == "niagara-point-binding-readback.json"
        )
    )
    assert len(readback["expected_links"]) == 3


def test_niagara_ord_and_priority_validation_fails_closed() -> None:
    with pytest.raises(ValidationError, match="exact station slot ord"):
        PointSpec(
            name="ZoneTemp",
            label="Zone temperature",
            data_type="numeric",
            role=PointRole.SENSOR,
            niagara_ord='station:|slot:/Config/Bad\";danger',
        )

    with pytest.raises(ValidationError, match="only valid for command or alarm"):
        PointSpec(
            name="ZoneTemp",
            label="Zone temperature",
            data_type="numeric",
            role=PointRole.SENSOR,
            niagara_ord="slot:/Config/ZoneTemp",
            niagara_write_priority=8,
        )


def test_slot_ord_is_normalized_to_station_ord() -> None:
    point = PointSpec(
        name="FanCommand",
        label="Fan command",
        data_type="boolean",
        role=PointRole.COMMAND,
        niagara_ord="slot:/Config/Drivers/BacnetNetwork/Fan/Points/FanCommand",
        niagara_write_priority=8,
    )

    assert point.niagara_ord == (
        "station:|slot:/Config/Drivers/BacnetNetwork/Fan/Points/FanCommand"
    )
