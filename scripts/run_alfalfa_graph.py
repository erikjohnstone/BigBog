from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import httpx
from alfalfa_client import AlfalfaClient

from bactalk.domain import Block, BlockKind, ControlGraph, Link
from bactalk.integrations.alfalfa import write_evidence_atomic
from bactalk.integrations.alfalfa_graph import (
    AlfalfaGraphMap,
    AlfalfaGraphRunner,
    AlfalfaInputBinding,
    AlfalfaOutputBinding,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / ".vendor/alfalfa/tests/integration/models/wrapped.fmu"
DEFAULT_OUTPUT = ROOT / ".bactalk/alfalfa-graph-evidence.json"


def _graph() -> ControlGraph:
    return ControlGraph(
        name="AlfalfaWholeBuildingFanController",
        blocks=[
            Block(id="zone_temperature", kind=BlockKind.NUMERIC_INPUT, label="Zone temperature"),
            Block(
                id="cooling_threshold",
                kind=BlockKind.NUMERIC_CONST,
                label="Cooling threshold",
                config={"value": 292.0},
            ),
            Block(id="cooling_request", kind=BlockKind.GREATER_THAN, label="Cooling request"),
            Block(
                id="fan_on",
                kind=BlockKind.NUMERIC_CONST,
                label="Fan qualification command",
                config={"value": 0.37},
            ),
            Block(
                id="fan_off",
                kind=BlockKind.NUMERIC_CONST,
                label="Fan off command",
                config={"value": 0.0},
            ),
            Block(id="fan_select", kind=BlockKind.NUMERIC_SWITCH, label="Fan selector"),
            Block(id="fan_command", kind=BlockKind.NUMERIC_OUTPUT, label="Fan command"),
        ],
        links=[
            Link(source="zone_temperature", target="cooling_request", target_slot="a"),
            Link(source="cooling_threshold", target="cooling_request", target_slot="b"),
            Link(source="cooling_request", target="fan_select", target_slot="selector"),
            Link(source="fan_on", target="fan_select", target_slot="when_true"),
            Link(source="fan_off", target="fan_select", target_slot="when_false"),
            Link(source="fan_select", target="fan_command", target_slot="in"),
        ],
    )


def _mapping() -> AlfalfaGraphMap:
    return AlfalfaGraphMap(
        outputs=[
            AlfalfaOutputBinding(
                graph_input="zone_temperature",
                output="hvac_reaZonCor_TZon_y",
                initial_output_value=294.0,
            )
        ],
        inputs=[
            AlfalfaInputBinding(
                graph_output="fan_command",
                input="hvac_oveAhu_yFan_u",
                minimum=0.0,
                maximum=1.0,
            )
        ],
        observed_outputs=[
            "hvac_oveAhu_yFan_y",
            "hvac_reaAhu_TSup_y",
            "hvac_reaZonCor_TZon_y",
        ],
        command_echoes={"hvac_oveAhu_yFan_u": "hvac_oveAhu_yFan_y"},
    )


def _server_version(base_url: str) -> Any:
    response = httpx.get(f"{base_url.rstrip('/')}/api/v2/version", timeout=15.0)
    response.raise_for_status()
    body = response.json()
    return body.get("payload", body) if isinstance(body, dict) else body


def _running_image_ids() -> dict[str, list[str]]:
    compose = ROOT / "ops/alfalfa.compose.yml"
    result: dict[str, list[str]] = {}
    for service in ("web", "worker", "mongo", "redis", "minio"):
        containers = subprocess.run(
            ["docker", "compose", "-f", str(compose), "ps", "-q", service],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()
        if not containers:
            raise RuntimeError(f"Alfalfa service has no running container: {service}")
        result[service] = sorted(
            {
                subprocess.run(
                    ["docker", "inspect", "--format", "{{.Image}}", container],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                for container in containers
            }
        )
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a complete typed BACTalk graph against a real Alfalfa FMU"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8088")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()

    evidence = AlfalfaGraphRunner(
        AlfalfaClient(arguments.base_url),
        _graph(),
        _mapping(),
    ).run(
        arguments.model,
        steps=5,
        step_seconds=60.0,
        start=datetime(2019, 1, 1),
        server_version=_server_version(arguments.base_url),
        client_version=metadata.version("alfalfa-client"),
    )
    evidence["images"] = {
        "running_image_ids": _running_image_ids(),
        "worker_patch_sha256": _sha256(
            ROOT / "ops/alfalfa-worker/patch_output_value.py"
        ),
    }
    evidence["not_proven"] = [
        "Niagara import, execution, restart, or readback",
        "BACnet protocol attachment or controller hardware-in-loop behavior",
        "production Linux capacity or high availability",
        "job-specific model and signal-map authority",
        "field-equipment or occupied-building behavior",
        "live-building deployment readiness",
    ]
    write_evidence_atomic(arguments.output, evidence)
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
