from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from run_alfalfa_graph import DEFAULT_MODEL, _graph, _mapping

from bactalk.api import create_app
from bactalk.domain import (
    AcceptanceCase,
    BacnetDeviceSpec,
    BacnetObjectSpec,
    BacnetScan,
    DataType,
    JobSpec,
    OutputExpectation,
    PointRole,
    PointSpec,
    SequenceSpec,
)
from bactalk.integrations.alfalfa import write_evidence_atomic

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".bactalk/alfalfa-product-evidence.json"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _job() -> JobSpec:
    graph = _graph()
    graph = graph.model_copy(
        update={
            "blocks": [
                block.model_copy(update={"config": {"default": 294.0}})
                if block.id == "zone_temperature"
                else block
                for block in graph.blocks
            ]
        }
    )
    return JobSpec(
        name="Real Alfalfa product workflow qualification",
        site="Isolated whole-building FMU lab",
        equipment_name="WholeBuilding_AHU_1",
        sequence=SequenceSpec(
            family="CUSTOM_FAN",
            version="Alfalfa product smoke v1",
        ),
        points=[
            PointSpec(
                name="zone_temperature",
                label="Zone temperature",
                data_type=DataType.NUMERIC,
                role=PointRole.SENSOR,
                units="K",
                default=294.0,
                bacnet_device_instance=120_001,
                bacnet_object="analog-input,1",
            ),
            PointSpec(
                name="fan_command",
                label="Fan command",
                data_type=DataType.NUMERIC,
                role=PointRole.COMMAND,
                units="fraction",
                default=0.0,
                bacnet_device_instance=120_001,
                bacnet_object="analog-output,1",
            ),
        ],
        control_graph=graph,
        acceptance_tests=[
            AcceptanceCase(
                name="warm zone enables fan",
                inputs={"zone_temperature": 294.0},
                expectations=[OutputExpectation(target="fan_command", value=0.37)],
            )
        ],
        bacnet_scan=BacnetScan(
            source="isolated Alfalfa product qualification fixture",
            devices=[
                BacnetDeviceSpec(
                    device_instance=120_001,
                    address="192.0.2.101/24:47808",
                    name="Whole-building AHU virtual controller",
                    vendor_id=999,
                    objects=[
                        BacnetObjectSpec(
                            object_id="analog-input,1",
                            name="Zone Temperature",
                            data_type=DataType.NUMERIC,
                            units="K",
                            present_value=294.0,
                        ),
                        BacnetObjectSpec(
                            object_id="analog-output,1",
                            name="Fan Command",
                            data_type=DataType.NUMERIC,
                            writable=True,
                            units="noUnits",
                            present_value=0.0,
                        ),
                    ],
                )
            ],
        ),
    )


def _require(response: object, status_code: int, label: str) -> None:
    actual = getattr(response, "status_code", None)
    if actual != status_code:
        text = getattr(response, "text", "")
        raise RuntimeError(f"{label} returned {actual}, expected {status_code}: {text}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prove the complete BACTalk API-to-real-Alfalfa contractor workflow"
    )
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()

    model = arguments.model.resolve()
    if not model.is_file():
        raise FileNotFoundError(model)
    with tempfile.TemporaryDirectory(prefix="bactalk-alfalfa-product-") as directory:
        queue_url = os.getenv(
            "BACTALK_QUEUE_URL",
            "redis://:bactalk-queue-local-secret@127.0.0.1:6380/0",
        )
        queue_name = f"bactalk-qualification-smoke-{uuid4().hex}"
        os.environ["BACTALK_QUALIFICATION_QUEUE"] = queue_name
        client = TestClient(create_app(Path(directory) / "runs"))
        with model.open("rb") as stream:
            inspected = client.post(
                "/api/integrations/alfalfa/inspect-fmu",
                files={"model_file": (model.name, stream, "application/zip")},
            )
        _require(inspected, 200, "FMU inspection")
        created = client.post("/api/runs", json=_job().model_dump(mode="json"))
        _require(created, 201, "candidate creation")
        run_id = created.json()["id"]

        denied = client.get(f"/api/runs/{run_id}/export")
        _require(denied, 403, "pre-approval export")

        qualification = {
            "mapping": _mapping().model_dump(mode="json"),
            "oracles": [
                {
                    "id": "zone-temperature-response",
                    "signal_kind": "fmu_output",
                    "signal": "hvac_reaZonCor_TZon_y",
                    "reference_times": [60.0, 120.0, 180.0, 240.0, 300.0],
                    "reference_values": [
                        293.15735,
                        293.16227,
                        293.16072,
                        293.15350,
                        293.14196,
                    ],
                    "absolute_time_tolerance": 0.0,
                    "absolute_value_tolerance": 0.05,
                }
            ],
            "steps": 5,
            "step_seconds": 60.0,
            "start": "2019-01-01T00:00:00",
            "transport": "bacnet_ip_loopback",
        }
        with model.open("rb") as stream:
            queued = client.post(
                f"/api/runs/{run_id}/qualification-jobs/alfalfa",
                data={"qualification": json.dumps(qualification)},
                files={"model_file": (model.name, stream, "application/zip")},
            )
        _require(queued, 202, "Alfalfa qualification queue submission")
        job_id = queued.json()["id"]
        worker_environment = {
            **os.environ,
            "BACTALK_QUEUE_URL": queue_url,
            "BACTALK_QUALIFICATION_QUEUE": queue_name,
            "PYTHONPATH": str(ROOT / "src"),
        }
        worker = subprocess.run(
            [
                sys.executable,
                "-m",
                "bactalk.cli",
                "qualification-worker",
                "--burst",
                "--queue",
                queue_name,
                "--output",
                str(Path(directory) / "runs"),
                "--jobs",
                str(Path(directory) / "qualification-jobs"),
            ],
            cwd=ROOT,
            env=worker_environment,
            capture_output=True,
            text=True,
            timeout=1_800,
        )
        if worker.returncode != 0:
            raise RuntimeError(
                "qualification worker failed: "
                f"stdout={worker.stdout[-4_000:]}, stderr={worker.stderr[-4_000:]}"
            )
        job = client.get(f"/api/qualification-jobs/{job_id}")
        _require(job, 200, "retained qualification job")
        if job.json()["status"] != "succeeded":
            raise RuntimeError(f"qualification job did not succeed: {job.json()}")

        retained = client.get(f"/api/runs/{run_id}/verify/alfalfa")
        _require(retained, 200, "retained Alfalfa evidence")
        qualified_run = client.get(f"/api/runs/{run_id}")
        _require(qualified_run, 200, "qualified candidate")

        approved = client.post(
            f"/api/runs/{run_id}/approve",
            json={"reviewer": "Alfalfa product smoke identity"},
        )
        _require(approved, 200, "candidate approval")
        exported = client.get(f"/api/runs/{run_id}/export")
        _require(exported, 200, "approved artifact export")
        bundle = client.get(f"/api/runs/{run_id}/review-bundle")
        _require(bundle, 200, "approved review bundle export")
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            names = sorted(archive.namelist())
        expected = {
            f"alfalfa-verification/{model.name}",
            "alfalfa-verification/evidence.json",
            "alfalfa-verification/oracle-001-zone-temperature-response/errors.csv",
        }
        if not expected.issubset(names):
            raise RuntimeError(
                f"review bundle is missing Alfalfa artifacts: {sorted(expected - set(names))}"
            )

        evidence = {
            "schema": "bactalk.alfalfa-product-workflow/v1",
            "status": "pass",
            "product_api_exercised": True,
            "fmu_inspection": inspected.json(),
            "run_id": run_id,
            "preapproval_export_denied": True,
            "qualification_job": job.json(),
            "qualified_run": qualified_run.json(),
            "runtime_evidence": retained.json(),
            "approved_run": approved.json(),
            "approved_export": {
                "bytes": len(exported.content),
                "sha256": _sha256(exported.content),
            },
            "review_bundle": {
                "bytes": len(bundle.content),
                "sha256": _sha256(bundle.content),
                "members": names,
            },
            "live_building_writes": False,
        }
        transport = retained.json().get("control_transport")
        if not isinstance(transport, dict) or transport.get("kind") != "bacnet_ip_loopback":
            raise RuntimeError("product qualification did not traverse BACnet/IP loopback")
        if not transport.get("readbacks_matched"):
            raise RuntimeError("BACnet/IP qualification did not retain matched command readbacks")
        oracles = retained.json().get("oracles")
        if not isinstance(oracles, list) or not oracles or not oracles[0].get("passed"):
            raise RuntimeError("whole-building response trajectory did not pass its oracle")
        write_evidence_atomic(arguments.output, evidence)
        print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
