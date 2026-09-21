from __future__ import annotations

import json
from importlib import metadata
from pathlib import Path

import yaml
from alfalfa_client import AlfalfaClient

ROOT = Path(__file__).resolve().parents[1]
WEB_IMAGE = (
    "ghcr.io/natlabrockies/alfalfa/web@sha256:"
    "9f79f502a18e629e5362be08795ae26680e947ccd4268666319f6c20089a9fb8"
)
WORKER_BASE = (
    "ghcr.io/natlabrockies/alfalfa/worker@sha256:"
    "3afbad460c406d52be06b3724079ed1a5570f9f3f82f577285c07c1cb45ed23b"
)
WORKER_IMAGE = "bactalk/alfalfa-worker:1.0.0-output-value-fix.1"
MONGO_IMAGE = (
    "mongo:4.4.29@sha256:"
    "6189a342f8da4568b4b111c378a890b1fe186b1bc133742bff8811fe63d2e01e"
)


def main() -> int:
    upstream_path = ROOT / ".vendor/alfalfa/docker-compose.yml"
    upstream = yaml.safe_load(upstream_path.read_text(encoding="utf-8"))
    services = set(upstream["services"])
    required = {"web", "worker", "mongo", "redis", "minio"}
    assert required <= services

    product_path = ROOT / "ops/alfalfa.compose.yml"
    product = yaml.safe_load(product_path.read_text(encoding="utf-8"))
    product_services = product["services"]
    assert required | {"mc"} <= set(product_services)
    assert product_services["web"]["image"] == WEB_IMAGE
    assert product_services["worker"]["image"] == WORKER_IMAGE
    assert product_services["mongo"]["image"] == MONGO_IMAGE
    dockerfile = (ROOT / "ops/alfalfa-worker/Dockerfile").read_text(encoding="utf-8")
    assert f"FROM {WORKER_BASE}" in dockerfile
    patcher = (ROOT / "ops/alfalfa-worker/patch_output_value.py").read_text(encoding="utf-8")
    assert 'OLD = "            point.value = y_output\\n"' in patcher
    assert 'NEW = "            point.value = value\\n"' in patcher
    assert product_services["web"]["platform"] == "linux/amd64"
    assert product_services["worker"]["platform"] == "linux/amd64"
    assert product_services["web"]["ports"] == ["127.0.0.1:8088:80"]
    assert product_services["minio"]["ports"] == ["127.0.0.1:9100:9000"]

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
    evidence_path = ROOT / ".bactalk/alfalfa-runtime-evidence.json"
    runtime_evidence = None
    if evidence_path.is_file():
        runtime_evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    graph_evidence_path = ROOT / ".bactalk/alfalfa-graph-evidence.json"
    graph_evidence = None
    if graph_evidence_path.is_file():
        graph_evidence = json.loads(graph_evidence_path.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "engine": "Alfalfa pinned runtime contract",
                "client_version": metadata.version("alfalfa-client"),
                "api": client.url,
                "upstream_compose_services": sorted(services),
                "product_compose_services": sorted(product_services),
                "images": {
                    "web": WEB_IMAGE,
                    "worker": WORKER_IMAGE,
                    "worker_base": WORKER_BASE,
                    "mongo": MONGO_IMAGE,
                },
                "runtime_lane_configured": True,
                "retained_runtime_status": (
                    runtime_evidence.get("status") if runtime_evidence is not None else "not_run"
                ),
                "retained_graph_status": (
                    graph_evidence.get("status") if graph_evidence is not None else "not_run"
                ),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
