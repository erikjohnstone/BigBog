from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from importlib import metadata
from pathlib import Path
from typing import Any

import httpx
from alfalfa_client import AlfalfaClient

from bactalk.integrations.alfalfa import qualify_alfalfa_runtime, write_evidence_atomic

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / ".vendor/alfalfa/tests/integration/models/wrapped.fmu"
DEFAULT_OUTPUT = ROOT / ".bactalk/alfalfa-runtime-evidence.json"
IMAGES = {
    "web": (
        "ghcr.io/natlabrockies/alfalfa/web@sha256:"
        "9f79f502a18e629e5362be08795ae26680e947ccd4268666319f6c20089a9fb8"
    ),
    "worker_base": (
        "ghcr.io/natlabrockies/alfalfa/worker@sha256:"
        "3afbad460c406d52be06b3724079ed1a5570f9f3f82f577285c07c1cb45ed23b"
    ),
    "worker": "bactalk/alfalfa-worker:1.0.0-output-value-fix.1",
}


def _server_version(base_url: str) -> Any:
    response = httpx.get(f"{base_url.rstrip('/')}/api/v2/version", timeout=15.0)
    response.raise_for_status()
    body = response.json()
    return body.get("payload", body) if isinstance(body, dict) else body


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        image_ids = {
            subprocess.run(
                ["docker", "inspect", "--format", "{{.Image}}", container],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            for container in containers
        }
        result[service] = sorted(image_ids)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Qualify a real Alfalfa FMU lifecycle")
    parser.add_argument("--base-url", default="http://127.0.0.1:8088")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()

    try:
        version = _server_version(arguments.base_url)
    except Exception as exc:
        version = {"unavailable": f"{type(exc).__name__}: {exc}"}

    runtime_images: dict[str, Any] = {
        "declared": IMAGES,
        "running_image_ids": _running_image_ids(),
        "worker_patch_sha256": _sha256(
            ROOT / "ops/alfalfa-worker/patch_output_value.py"
        ),
    }
    evidence = qualify_alfalfa_runtime(
        AlfalfaClient(arguments.base_url),
        arguments.model,
        server_version=version,
        client_version=metadata.version("alfalfa-client"),
        images=runtime_images,
    )
    write_evidence_atomic(arguments.output, evidence)
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
