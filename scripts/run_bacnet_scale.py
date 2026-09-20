from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from uuid import uuid4

from bactalk.integrations.bacnet_scale import BacnetScaleProfile, BacnetScaleRunner


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Retain isolated real-UDP BACnet scale qualification evidence"
    )
    parser.add_argument("--devices", type=int, default=100)
    parser.add_argument("--analog-inputs", type=int, default=16)
    parser.add_argument("--binary-inputs", type=int, default=2)
    parser.add_argument("--analog-outputs", type=int, default=1)
    parser.add_argument("--binary-outputs", type=int, default=1)
    parser.add_argument("--poll-rounds", type=int, default=2)
    parser.add_argument("--cov-subscriptions", type=int, default=None)
    parser.add_argument("--cov-burst-rounds", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--base-port", type=int, default=40_000)
    parser.add_argument("--request-timeout", type=float, default=3.0)
    parser.add_argument("--outage-timeout", type=float, default=0.5)
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=Path(".bactalk/bacnet-scale-runtime"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".bactalk/bacnet-scale-evidence.json"),
    )
    arguments = parser.parse_args()
    profile = BacnetScaleProfile(
        devices=arguments.devices,
        analog_inputs_per_device=arguments.analog_inputs,
        binary_inputs_per_device=arguments.binary_inputs,
        analog_outputs_per_device=arguments.analog_outputs,
        binary_outputs_per_device=arguments.binary_outputs,
        poll_rounds=arguments.poll_rounds,
        cov_subscriptions=arguments.cov_subscriptions,
        cov_burst_rounds=arguments.cov_burst_rounds,
        concurrency=arguments.concurrency,
        base_port=arguments.base_port,
        request_timeout_seconds=arguments.request_timeout,
        outage_timeout_seconds=arguments.outage_timeout,
    )
    runtime_root = arguments.runtime_root / f"run-{uuid4().hex}"
    evidence = asyncio.run(BacnetScaleRunner(profile, runtime_root).run())
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
                "devices": evidence["profile"]["devices"],
                "total_points": evidence["profile"]["total_points"],
                "wall_seconds": evidence["runtime"]["wall_seconds"],
                "error_count": len(evidence["errors"]),
            },
            sort_keys=True,
        )
    )
    if evidence["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
