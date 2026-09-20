from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from bactalk.api import create_app
from bactalk.domain import PointSpec
from bactalk.integrations.ctrl_flow import CtrlFlowLibrary
from bactalk.integrations.ctrl_flow_planning import AHU_TEMPLATE


def _points_for_required_brief() -> list[PointSpec]:
    brief = CtrlFlowLibrary().programming_brief(AHU_TEMPLATE, {})
    return [
        PointSpec(
            name=requirement["id"],
            label=requirement["label"],
            data_type=requirement["data_type"],
            role=requirement["role"],
            units=requirement["units"],
            default=False if requirement["data_type"] == "boolean" else 0.0,
        )
        for requirement in brief["point_requirements"]["points"]
        if requirement["required"]
    ]


def test_complete_exact_points_contract_is_ready_for_sequence_reconciliation() -> None:
    points = _points_for_required_brief()
    result = CtrlFlowLibrary().reconcile_points(AHU_TEMPLATE, {}, points)

    assert result["ready_for_sequence_reconciliation"] is True
    assert result["complete_niagara_job_ready"] is False
    assert result["matched_requirement_count"] == result["required_point_count"]
    assert result["missing_required"] == []
    assert result["blocking_issues"] == []
    assert len(result["canonical_points"]) == len(points)


def test_audited_alias_and_convertible_units_are_retained_explicitly() -> None:
    points = _points_for_required_brief()
    index = next(i for i, point in enumerate(points) if point.name == "DischargeAirTemp")
    points[index] = points[index].model_copy(
        update={
            "name": "DATSensor",
            "source_name": "DAT",
            "units": "degC",
        }
    )

    result = CtrlFlowLibrary().reconcile_points(AHU_TEMPLATE, {}, points)
    mapping = next(
        item for item in result["matches"] if item["requirement_id"] == "DischargeAirTemp"
    )

    assert result["ready_for_sequence_reconciliation"] is True
    assert mapping["method"] == "audited-alias"
    assert mapping["unit_status"] == "conversion-required"
    assert result["unit_conversions"] == [
        {
            "requirement_id": "DischargeAirTemp",
            "source_name": "DAT",
            "from": "degC",
            "to": "degF",
            "status": "explicit-converter-required",
        }
    ]
    canonical = next(
        point for point in result["canonical_points"] if point["name"] == "DischargeAirTemp"
    )
    assert canonical["source_name"] == "DAT"


def test_missing_duplicate_and_semantic_mismatches_fail_closed() -> None:
    points = _points_for_required_brief()
    points = [point for point in points if point.name != "SupplyFanCommand"]
    duct_index = next(i for i, point in enumerate(points) if point.name == "DuctStatic")
    points[duct_index] = PointSpec.model_validate(
        {
            **points[duct_index].model_dump(mode="json"),
            "role": "status",
            "units": "psi",
        }
    )
    points.append(
        PointSpec(
            name="DuplicateDuctPressure",
            source_name="DSP",
            label="Duct static pressure",
            data_type="numeric",
            role="sensor",
            units="inH2O",
        )
    )

    result = CtrlFlowLibrary().reconcile_points(AHU_TEMPLATE, {}, points)
    issue_kinds = {item["kind"] for item in result["blocking_issues"]}

    assert result["ready_for_sequence_reconciliation"] is False
    assert "SupplyFanCommand" in result["missing_required"]
    assert {"missing_required_point", "role_mismatch", "units_incompatible", "duplicate"} <= (
        issue_kinds
    )
    assert result["duplicates"][0]["requirement_id"] == "DuctStatic"


def test_unmatched_extra_point_is_preserved_without_satisfying_a_requirement() -> None:
    points = _points_for_required_brief()
    points.append(
        PointSpec(
            name="FilterHours",
            label="Filter runtime hours",
            data_type="numeric",
            role="status",
            units="h",
        )
    )

    result = CtrlFlowLibrary().reconcile_points(AHU_TEMPLATE, {}, points)

    assert result["ready_for_sequence_reconciliation"] is True
    assert result["unmatched_provided"] == [
        {
            "source_name": "FilterHours",
            "name": "FilterHours",
            "label": "Filter runtime hours",
            "reason": "no exact canonical name or audited alias matched",
        }
    ]
    assert any(point["name"] == "FilterHours" for point in result["canonical_points"])


def test_point_reconciliation_is_exposed_through_product_api(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))
    point = PointSpec(
        name="SupplyFanCommand",
        label="Supply fan command",
        data_type="boolean",
        role="command",
    )

    response = client.post(
        f"/api/library/ctrl-flow/templates/{AHU_TEMPLATE}/reconcile-points",
        json={"selections": {}, "points": [point.model_dump(mode="json")]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["matched_requirement_count"] == 1
    assert response.json()["missing_required_count"] > 20
    assert response.json()["ready_for_sequence_reconciliation"] is False


def test_uploaded_contractor_points_file_uses_the_same_reconciliation_boundary(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(tmp_path / "runs"))
    points = _points_for_required_brief()
    header = "name,label,data_type,role,units,default,required\n"
    rows = "".join(
        f"{point.name},{point.label},{point.data_type.value},{point.role.value},"
        f"{point.units or ''},{point.default},true\n"
        for point in points
    )

    response = client.post(
        f"/api/library/ctrl-flow/templates/{AHU_TEMPLATE}/inspect-points",
        data={"selections": "{}"},
        files={"points_file": ("ahu-points.csv", (header + rows).encode(), "text/csv")},
    )

    assert response.status_code == 200, response.text
    assert response.json()["provided_point_count"] == len(points)
    assert response.json()["ready_for_sequence_reconciliation"] is True
