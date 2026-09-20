import pytest

from bactalk.domain import DataType, PointRole, PointSpec
from bactalk.point_mapping import PointMappingError, canonicalize_points


def _point(name: str, label: str) -> PointSpec:
    return PointSpec(
        name=name,
        label=label,
        data_type=DataType.NUMERIC,
        role=PointRole.SENSOR,
    )


def test_exact_alias_mapping_preserves_contractor_provenance() -> None:
    result = canonicalize_points(
        [_point("ZN_T", "Zone Temperature"), _point("SAT", "Supply air temp")],
        "G36_VAV_REHEAT",
    )

    assert result.points[0].name == "ZoneTemp"
    assert result.points[0].source_name == "ZN_T"
    assert result.mappings[0] == {
        "source_name": "ZN_T",
        "canonical_name": "ZoneTemp",
        "method": "exact_alias",
    }
    assert "CoolingSetpoint" in result.missing_required
    assert result.points[1].name == "SAT"


def test_multiple_contractor_points_for_one_logical_role_fail_closed() -> None:
    points = [_point("ZN_T", "Zone temp"), _point("SpaceTemp", "Space temperature")]

    with pytest.raises(PointMappingError, match="multiple contractor points map to ZoneTemp"):
        canonicalize_points(points, "G36_VAV_REHEAT")
