from __future__ import annotations

import json
from pathlib import Path

import pytest

from bactalk.ctrl_flow_point_repository import (
    CtrlFlowPointIntegrityError,
    CtrlFlowPointReconciliationRepository,
)
from bactalk.domain import PointSpec
from bactalk.integrations.ctrl_flow import CtrlFlowLibrary
from bactalk.integrations.ctrl_flow_planning import AHU_TEMPLATE


def _result() -> dict:
    library = CtrlFlowLibrary()
    brief = library.programming_brief(AHU_TEMPLATE, {})
    points = [
        PointSpec(
            name=point["id"],
            label=point["label"],
            data_type=point["data_type"],
            role=point["role"],
            units=point["units"],
            default=False if point["data_type"] == "boolean" else 0.0,
        )
        for point in brief["point_requirements"]["points"]
        if point["required"]
    ]
    return library.reconcile_points(AHU_TEMPLATE, {}, points)


def test_point_reconciliation_repository_retains_exact_source_and_detects_tampering(
    tmp_path: Path,
) -> None:
    repository = CtrlFlowPointReconciliationRepository(tmp_path / "points")
    source = b"name,label,data_type,role,default\nZoneTemp,Zone temp,numeric,sensor,72\n"
    record = repository.save(
        template_id=AHU_TEMPLATE,
        selections={},
        source_content=source,
        source_filename="points.csv",
        source_media_type="text/csv",
        actor_id="engineer@example.com",
        tenant_id="contractor-a",
        result=_result(),
    )

    assert repository.get(record.id) == record
    assert repository.source(record.id) == source
    assert repository.list() == [record]
    assert record.result["ready_for_sequence_reconciliation"] is True

    manifest = tmp_path / "points" / record.id / "manifest.json"
    payload = json.loads(manifest.read_text())
    payload["result"]["matched_requirement_count"] = 0
    manifest.write_text(json.dumps(payload))
    with pytest.raises(CtrlFlowPointIntegrityError, match="result digest changed"):
        repository.get(record.id)


def test_point_reconciliation_repository_rejects_non_reconciliation_results(
    tmp_path: Path,
) -> None:
    repository = CtrlFlowPointReconciliationRepository(tmp_path / "points")
    with pytest.raises(ValueError, match="unsupported"):
        repository.save(
            template_id=AHU_TEMPLATE,
            selections={},
            source_content=b"points",
            source_filename="points.csv",
            source_media_type="text/csv",
            actor_id=None,
            tenant_id=None,
            result={"schema": "wrong"},
        )
