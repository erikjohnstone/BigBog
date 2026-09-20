from __future__ import annotations

import argparse
import json
from pathlib import Path

from bactalk.integrations.boptest_scale import BoptestScaleProfile, BoptestScaleRunner


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Retain concurrent real-BOPTEST scale qualification evidence"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--test-case", default="multizone_office_complex_air")
    parser.add_argument("--instances", type=int, default=4)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--step", type=float, default=300.0)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".bactalk/boptest-scale-evidence.json"),
    )
    arguments = parser.parse_args()

    profile = BoptestScaleProfile(
        base_url=arguments.base_url,
        test_case=arguments.test_case,
        instances=arguments.instances,
        concurrency=arguments.concurrency,
        steps=arguments.steps,
        step_seconds=arguments.step,
        request_timeout_seconds=arguments.timeout,
    )
    evidence = BoptestScaleRunner(profile).run()
    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = arguments.output.with_suffix(arguments.output.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(arguments.output)
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "evidence": str(arguments.output),
                "passed_instances": evidence["runtime"]["passed_instances"],
                "failed_instances": evidence["runtime"]["failed_instances"],
                "wall_seconds": evidence["runtime"]["wall_seconds"],
            },
            sort_keys=True,
        )
    )
    if evidence["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
