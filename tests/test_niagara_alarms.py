from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from bactalk.agent import SequencePackPlanner
from bactalk.demo import demo_job
from bactalk.domain import DataType
from bactalk.integrations.niagara_alarms import build_niagara_alarm_export


def test_boolean_alarm_compiles_to_generic_niagara_sdk_source_without_vendor_logic() -> None:
    job = demo_job()
    graph = SequencePackPlanner().plan(job)

    export = build_niagara_alarm_export(job, graph)
    files = {item.relative_path: item.content for item in export.artifacts}
    plan = json.loads(files["niagara-alarm-plan.json"])
    source = files["BactalkAlarmInstaller_VAV_12.java"]

    extension = plan["extensions"][0]
    assert extension["data_type"] == DataType.BOOLEAN.value
    assert extension["algorithm"]["alarm_value"] is True
    assert extension["source_extension_compiled"] is True
    assert extension["bog_extension_emitted"] is False
    assert "BBooleanChangeOfStateAlgorithm" in source
    assert "setAlarmValue(true)" in source
    assert "setTimeDelay(BRelTime.make(300000L))" in source
    assert "HVAC_Critical" in source
    assert "Am8x" not in source
    assert "ESCLUSIONI" not in source
    assert export.manifest["licensed_runtime_qualified"] is False


def test_alarm_trigger_type_must_match_point_type() -> None:
    payload = demo_job().model_dump(mode="json")
    payload["deliverables"]["alarms"][0]["trigger"] = "above"
    payload["deliverables"]["alarms"][0]["high_limit"] = 80.0

    with pytest.raises(ValidationError, match="requires a boolean trigger"):
        type(demo_job()).model_validate(payload)


def test_numeric_alarm_requires_explicit_limit_semantics() -> None:
    payload = demo_job().model_dump(mode="json")
    alarm_name = payload["deliverables"]["alarms"][0]["point"]
    for point in payload["points"]:
        if point["name"] == alarm_name:
            point["data_type"] = "numeric"
            point["default"] = 0.0

    with pytest.raises(ValidationError, match="requires numeric limits"):
        type(demo_job()).model_validate(payload)
