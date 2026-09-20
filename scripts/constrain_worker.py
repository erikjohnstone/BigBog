from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pandas as pd


def main() -> None:
    request = json.load(sys.stdin)
    rule = request.get("rule")
    rows = request.get("rows")
    if not isinstance(rule, str) or not rule.isidentifier():
        raise SystemExit("rule must be a Python identifier")
    if not isinstance(rows, list) or not rows:
        raise SystemExit("rows must be a non-empty list")

    root = Path(__file__).resolve().parents[1]
    rule_path = root / ".vendor/constrain/constrain/library" / f"{rule}.py"
    if not rule_path.is_file():
        raise SystemExit(f"unknown or non-executable ConStrain rule: {rule}")

    normalized: list[dict] = []
    timestamps: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or "timestamp" not in row:
            raise SystemExit("each row must be an object with a timestamp")
        copy = dict(row)
        timestamps.append(str(copy.pop("timestamp")))
        normalized.append(copy)
    frame = pd.DataFrame(normalized, index=pd.to_datetime(timestamps, utc=True))

    module = importlib.import_module(f"constrain.library.{rule}")
    rule_class = getattr(module, rule)
    tolerances = json.loads(
        (root / ".vendor/constrain/constrain/tolerances.json").read_text(encoding="utf-8")
    )
    instance = rule_class(
        frame,
        params=request.get("parameters") or None,
        tolerances=tolerances,
    )
    passed, detail = instance.get_checks
    print(
        json.dumps(
            {
                "engine": "PNNL ConStrain",
                "version": "0.8.0",
                "rule": rule,
                "passed": passed,
                "detail": detail,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
