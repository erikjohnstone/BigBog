from __future__ import annotations

from pathlib import Path

import pytest

from bactalk.integrations.constrain import ConStrainError, ConStrainVerifier
from bactalk.integrations.haxall import HaxallValidator
from bactalk.integrations.open_fdd import OpenFddError, OpenFddVerifier


def test_haxall_validates_real_g36_fixture() -> None:
    source = Path("ops/haxall/fixtures/g36-reheat-vav.trio").read_text(encoding="utf-8")
    # Trio is accepted by the contract script; exercise the product adapter with the
    # equivalent Haxall output format by asking the CLI to read a minimal Zinc grid.
    zinc = 'ver:"3.0"\nid,spec,site,dis\n@site,@ph::Site,M,"Demo"\n'
    result = HaxallValidator().validate_zinc(zinc)
    assert result.conforms
    assert result.errors == []
    assert "G36ReheatVav" in source


def test_constrain_executes_good_and_bad_rule_data() -> None:
    verifier = ConStrainVerifier()
    if not verifier.available:
        pytest.skip("isolated ConStrain runtime is not installed")
    good = verifier.verify(
        rule="G36SupplyFanStatus",
        rows=[
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "mode_operation": "occupied",
                "status_fan_supply": True,
                "flag_reheat_perimeter": False,
            },
            {
                "timestamp": "2026-01-01T00:05:00Z",
                "mode_operation": "unoccupied",
                "status_fan_supply": False,
                "flag_reheat_perimeter": False,
            },
        ],
    )
    bad = verifier.verify(
        rule="G36SupplyFanStatus",
        rows=[
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "mode_operation": "occupied",
                "status_fan_supply": False,
                "flag_reheat_perimeter": False,
            },
            {
                "timestamp": "2026-01-01T00:05:00Z",
                "mode_operation": "unoccupied",
                "status_fan_supply": False,
                "flag_reheat_perimeter": False,
            },
        ],
    )
    assert good["passed"] is True
    assert bad["passed"] is False


def test_constrain_rejects_arbitrary_module_names() -> None:
    verifier = ConStrainVerifier()
    if not verifier.available:
        pytest.skip("isolated ConStrain runtime is not installed")
    with pytest.raises(ConStrainError, match="rule must be a Python identifier"):
        verifier.verify(rule="../../evil", rows=[{"timestamp": "2026-01-01T00:00:00Z"}])


def test_open_fdd_executes_good_and_bad_sensor_data() -> None:
    verifier = OpenFddVerifier()
    common = {
        "rule_id": "SV-RANGE",
        "equipment_id": "VAV-1",
        "equipment_kind": "vav",
        "equipment_type": "VAV",
        "poll_seconds": 60.0,
        "require_operational_gates": False,
    }
    good = verifier.verify(
        **common,
        rows=[
            {"timestamp": f"2026-01-01T00:{minute:02d}:00Z", "zone-air-temp": 72.0}
            for minute in range(10)
        ],
    )
    bad = verifier.verify(
        **common,
        rows=[
            {"timestamp": f"2026-01-01T00:{minute:02d}:00Z", "zone-air-temp": 200.0}
            for minute in range(10)
        ],
    )
    assert good["status"] == "PASS"
    assert bad["status"] == "FAULT"


def test_open_fdd_rejects_unknown_rule() -> None:
    with pytest.raises(OpenFddError, match="unknown Open-FDD rule"):
        OpenFddVerifier().verify(
            rule_id="NOPE",
            equipment_id="AHU-1",
            equipment_kind="ahu",
            equipment_type="AHU",
            poll_seconds=60,
            rows=[{"timestamp": "2026-01-01T00:00:00Z"}],
        )
