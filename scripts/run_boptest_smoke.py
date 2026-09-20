from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from bactalk.integrations.boptest import BoptestClient


def _test_case_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        str(item.get("testcaseid"))
        for item in value
        if isinstance(item, dict) and item.get("testcaseid")
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Exercise a real BOPTEST service lifecycle")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--test-case", default="bestest_air")
    parser.add_argument("--step", type=float, default=300.0)
    parser.add_argument(
        "--output",
        type=Path,
        help="Optionally retain the runtime evidence as JSON",
    )
    arguments = parser.parse_args()

    evidence: dict[str, Any] = {
        "base_url": arguments.base_url,
        "test_case": arguments.test_case,
    }
    test_id: str | None = None
    with BoptestClient(arguments.base_url, timeout=60.0) as boptest:
        evidence["version"] = boptest.version()
        cases = boptest.test_cases()
        evidence["available_test_cases"] = _test_case_ids(cases)
        if arguments.test_case not in evidence["available_test_cases"]:
            raise SystemExit(f"BOPTEST test case is unavailable: {arguments.test_case}")
        try:
            test_id = boptest.select(arguments.test_case)
            evidence["test_id"] = test_id
            evidence["initialize"] = boptest.initialize(
                test_id,
                start_time=0.0,
                warmup_period=0.0,
            )
            evidence["step"] = boptest.set_step(test_id, arguments.step)
            evidence["input_count"] = len(boptest.inputs(test_id))
            evidence["measurement_count"] = len(boptest.measurements(test_id))
            evidence["advance"] = boptest.advance(test_id, {})
            evidence["kpis"] = boptest.kpis(test_id)
        finally:
            if test_id is not None:
                evidence["stop"] = boptest.stop(test_id)

    advanced_time = evidence.get("advance", {}).get("time")
    if advanced_time != arguments.step:
        raise SystemExit(
            f"BOPTEST advanced to {advanced_time!r}; expected {arguments.step!r}"
        )
    if evidence.get("input_count", 0) <= 0:
        raise SystemExit("BOPTEST exposed no controller inputs")
    if evidence.get("measurement_count", 0) <= 0:
        raise SystemExit("BOPTEST exposed no measurements")
    if evidence.get("stop") != "OK":
        raise SystemExit(f"BOPTEST did not stop cleanly: {evidence.get('stop')!r}")

    evidence["status"] = "pass"
    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
