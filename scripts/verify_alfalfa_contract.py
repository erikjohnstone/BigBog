from __future__ import annotations

import json
from importlib import metadata
from pathlib import Path

import yaml
from alfalfa_client import AlfalfaClient

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    compose_path = ROOT / ".vendor/alfalfa/docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    services = set(compose["services"])
    required = {"web", "worker", "mongo", "redis", "minio"}
    assert required <= services
    client = AlfalfaClient("http://127.0.0.1:9999")
    assert client.url == "http://127.0.0.1:9999/api/v2/"
    required_methods = {
        "submit",
        "start",
        "advance",
        "get_inputs",
        "set_inputs",
        "get_outputs",
        "stop",
    }
    assert all(callable(getattr(client, method, None)) for method in required_methods)
    print(
        json.dumps(
            {
                "engine": "Alfalfa client/source contract",
                "client_version": metadata.version("alfalfa-client"),
                "api": client.url,
                "compose_services": sorted(services),
                "runtime_started": False,
                "blocker": "Docker/Compose is unavailable on this host.",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
