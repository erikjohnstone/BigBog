from __future__ import annotations

import json

import pandas as pd
from open_fdd.rules.runner import RULES_BY_ID, run_cookbook_rule


def _evaluate(values: list[float]) -> dict:
    frame = pd.DataFrame(
        {"zone-air-temp": values},
        index=pd.date_range("2026-01-01", periods=len(values), freq="1min"),
    )
    result = run_cookbook_rule(
        RULES_BY_ID["SV-RANGE"],
        frame,
        equipment_id="VAV-1",
        equipment_kind="vav",
        equipment_type="VAV",
        poll_seconds=60.0,
        require_operational_gates=False,
    )
    return result.to_dict()


def main() -> None:
    passing = _evaluate([72.0] * 10)
    failing = _evaluate([200.0] * 10)
    if passing["status"] != "PASS":
        raise SystemExit(f"Open-FDD rejected known-good sensor data: {passing}")
    if failing["status"] != "FAULT" or failing["fault_sample_count"] == 0:
        raise SystemExit(f"Open-FDD accepted known-bad sensor data: {failing}")
    print(
        json.dumps(
            {
                "engine": "Open-FDD",
                "version": "4.4.1",
                "rule_exercised": "SV-RANGE",
                "known_good_status": passing["status"],
                "known_bad_status": failing["status"],
                "known_bad_fault_samples": failing["fault_sample_count"],
                "available_rules": len(RULES_BY_ID),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
