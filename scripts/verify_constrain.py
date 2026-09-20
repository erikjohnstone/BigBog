from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from constrain.library.G36SupplyFanStatus import G36SupplyFanStatus


def _frame(statuses: list[bool]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "mode_operation": ["occupied", "occupied", "unoccupied"],
            "status_fan_supply": statuses,
            "flag_reheat_perimeter": [False, False, False],
        },
        index=pd.date_range("2026-01-01", periods=3, freq="5min"),
    )


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    tolerances = json.loads(
        (root / ".vendor/constrain/constrain/tolerances.json").read_text(encoding="utf-8")
    )
    passing = G36SupplyFanStatus(_frame([True, True, False]), tolerances=tolerances)
    failing = G36SupplyFanStatus(_frame([False, True, False]), tolerances=tolerances)
    passed, passing_detail = passing.get_checks
    failed, failing_detail = failing.get_checks
    if passed is not True:
        raise SystemExit(f"ConStrain did not accept known-good fan behavior: {passing_detail}")
    if failed is not False:
        raise SystemExit(f"ConStrain did not reject known-bad fan behavior: {failing_detail}")
    library = json.loads(
        (root / ".vendor/constrain/constrain/schema/library.json").read_text(encoding="utf-8")
    )
    print(
        json.dumps(
            {
                "engine": "PNNL ConStrain",
                "version": "0.8.0",
                "rules": len(library),
                "rule_exercised": "G36SupplyFanStatus",
                "known_good": passing_detail,
                "known_bad": failing_detail,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
