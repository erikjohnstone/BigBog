from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from bactalk.api import create_app
from bactalk.domain import (
    AcceptanceCase,
    Block,
    BlockKind,
    ControlGraph,
    DataType,
    JobSpec,
    Link,
    OutputExpectation,
    PointRole,
    PointSpec,
    SequenceSpec,
)
from bactalk.integrations.boptest_graph import (
    BoptestActuatorBinding,
    BoptestGraphMap,
    BoptestMeasurementBinding,
    BoptestTrajectoryOracle,
)

ROOT = Path(__file__).resolve().parents[1]


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _require(response: object, status_code: int, label: str) -> None:
    actual = getattr(response, "status_code", None)
    if actual != status_code:
        text = getattr(response, "text", "")
        raise RuntimeError(f"{label} returned {actual}, expected {status_code}: {text}")


def fan_controller() -> ControlGraph:
    return ControlGraph(
        name="BoptestFanController",
        metadata={
            "purpose": "real closed-loop BACTalk IR to BOPTEST qualification",
            "threshold_kelvin": 292.0,
        },
        blocks=[
            Block(
                id="room_temp",
                kind=BlockKind.NUMERIC_INPUT,
                label="Room temperature",
                config={"default": 293.15},
            ),
            Block(
                id="threshold",
                kind=BlockKind.NUMERIC_CONST,
                label="Cooling threshold",
                config={"value": 292.0},
            ),
            Block(id="is_hot", kind=BlockKind.GREATER_THAN, label="Cooling request"),
            Block(
                id="fan_on",
                kind=BlockKind.NUMERIC_CONST,
                label="Fan on",
                config={"value": 1.0},
            ),
            Block(
                id="fan_off",
                kind=BlockKind.NUMERIC_CONST,
                label="Fan off",
                config={"value": 0.0},
            ),
            Block(id="select_fan", kind=BlockKind.NUMERIC_SWITCH, label="Fan selector"),
            Block(id="fan_command", kind=BlockKind.NUMERIC_OUTPUT, label="Fan command"),
        ],
        links=[
            Link(source="room_temp", target="is_hot", target_slot="a"),
            Link(source="threshold", target="is_hot", target_slot="b"),
            Link(source="is_hot", target="select_fan", target_slot="selector"),
            Link(source="fan_on", target="select_fan", target_slot="when_true"),
            Link(source="fan_off", target="select_fan", target_slot="when_false"),
            Link(source="select_fan", target="fan_command", target_slot="in"),
        ],
    )


def contractor_job() -> JobSpec:
    return JobSpec(
        name="BOPTEST contractor qualification job",
        site="BACTalk isolated simulation lab",
        equipment_name="FCU_BOPTEST_1",
        sequence=SequenceSpec(
            family="CUSTOM_FAN",
            version="Contractor-authored threshold control v1",
        ),
        points=[
            PointSpec(
                name="room_temp",
                label="Room temperature",
                data_type=DataType.NUMERIC,
                role=PointRole.SENSOR,
                units="K",
                default=293.15,
            ),
            PointSpec(
                name="fan_command",
                label="Fan command",
                data_type=DataType.NUMERIC,
                role=PointRole.COMMAND,
                units="%",
                default=0.0,
            ),
        ],
        control_graph=fan_controller(),
        acceptance_tests=[
            AcceptanceCase(
                name="hot room starts fan",
                inputs={"room_temp": 293.15},
                expectations=[OutputExpectation(target="fan_command", value=1.0)],
            )
        ],
        notes=(
            "Executable integration proof only. The generated BOG is not licensed-Niagara "
            "runtime-qualified and is not authorized for live-building deployment."
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a typed BACTalk controller against the real BOPTEST bestest_air FMU"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--steps", type=int, default=4)
    parser.add_argument("--step", type=float, default=300.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".bactalk/boptest-graph-runtime-evidence.json"),
    )
    parser.add_argument(
        "--run-root",
        type=Path,
        default=Path(".bactalk/boptest-contractor-runs"),
    )
    arguments = parser.parse_args()

    mapping = BoptestGraphMap(
        test_case="bestest_air",
        measurements=[
            BoptestMeasurementBinding(
                graph_input="room_temp",
                measurement="zon_reaTRooAir_y",
            )
        ],
        actuators=[
            BoptestActuatorBinding(
                graph_output="fan_command",
                actuator="fcu_oveFan_u",
                activation_actuator="fcu_oveFan_activate",
            )
        ],
    )
    reference_times = [arguments.step * (index + 1) for index in range(arguments.steps)]
    oracle = BoptestTrajectoryOracle(
        id="fan-command-enabled",
        signal_kind="graph_output",
        signal="fan_command",
        reference_times=reference_times,
        reference_values=[1.0] * arguments.steps,
        absolute_value_tolerance=0.0,
    )
    queue_url = os.getenv(
        "BACTALK_QUEUE_URL",
        "redis://:bactalk-queue-local-secret@127.0.0.1:6380/0",
    )
    queue_name = f"bactalk-boptest-qualification-smoke-{uuid4().hex}"
    os.environ["BACTALK_QUALIFICATION_QUEUE"] = queue_name
    jobs_root = arguments.run_root.parent / "qualification-jobs"
    client = TestClient(create_app(arguments.run_root))
    created = client.post("/api/runs", json=contractor_job().model_dump(mode="json"))
    _require(created, 201, "candidate creation")
    run_id = created.json()["id"]

    denied = client.get(f"/api/runs/{run_id}/export")
    _require(denied, 403, "pre-approval export")
    qualification = {
        "mapping": mapping.model_dump(mode="json"),
        "oracles": [oracle.model_dump(mode="json")],
        "steps": arguments.steps,
        "step_seconds": arguments.step,
        "start_time": 0.0,
        "warmup_period": 0.0,
    }
    queued = client.post(
        f"/api/runs/{run_id}/qualification-jobs/boptest",
        json=qualification,
    )
    _require(queued, 202, "BOPTEST qualification queue submission")
    job_id = queued.json()["id"]
    worker_environment = {
        **os.environ,
        "BACTALK_QUEUE_URL": queue_url,
        "BACTALK_QUALIFICATION_QUEUE": queue_name,
        "BACTALK_BOPTEST_URL": arguments.base_url,
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
            str(arguments.run_root),
            "--jobs",
            str(jobs_root),
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

    retained = client.get(f"/api/runs/{run_id}/verify/boptest")
    _require(retained, 200, "retained BOPTEST evidence")
    evidence = retained.json()
    qualified = client.get(f"/api/runs/{run_id}")
    _require(qualified, 200, "qualified candidate")
    if qualified.json()["status"] != "ready_for_review":
        raise SystemExit("BOPTEST trajectory oracle failed")
    trajectory = evidence["runtime"]["trajectory"]
    room_temperatures = [
        float(row["measurements"]["zon_reaTRooAir_y"]) for row in trajectory
    ]
    if len(set(room_temperatures)) <= 1:
        raise SystemExit("BOPTEST room temperature did not respond across the trajectory")

    approved = client.post(
        f"/api/runs/{run_id}/approve",
        json={"reviewer": "BACTalk Integration Test Reviewer"},
    )
    _require(approved, 200, "candidate approval")
    exported = client.get(f"/api/runs/{run_id}/export")
    _require(exported, 200, "approved artifact export")
    review_bundle = client.get(f"/api/runs/{run_id}/review-bundle")
    _require(review_bundle, 200, "approved review bundle export")
    with zipfile.ZipFile(io.BytesIO(review_bundle.content)) as archive:
        bundle_entries = archive.namelist()
    if "boptest-verification/evidence.json" not in bundle_entries:
        raise SystemExit("review bundle omitted signed BOPTEST evidence")

    retained = {
        "schema": "bactalk.boptest-contractor-e2e/v2",
        "status": "pass",
        "run_id": run_id,
        "workflow": [
            "contractor_job_created",
            "deterministic_acceptance_tests_passed",
            "niagara_bog_generated",
            "preapproval_export_denied",
            "real_boptest_closed_loop_passed",
            "pyfunnel_oracle_passed",
            "simulation_evidence_bound_to_artifact_digest",
            "test_identity_approved",
            "approved_bog_and_review_bundle_exported",
        ],
        "candidate_artifact_sha256": created.json()["artifact_sha256"],
        "qualified_artifact_sha256": qualified.json()["artifact_sha256"],
        "qualification_changed_digest": (
            created.json()["artifact_sha256"] != qualified.json()["artifact_sha256"]
        ),
        "preapproval_export_denied": True,
        "qualification_job": job.json(),
        "qualified_run": qualified.json(),
        "runtime_evidence": evidence,
        "qualification_evidence": qualified.json()["boptest_verification_path"],
        "verification_artifact_count": len(qualified.json()["verification_artifact_paths"]),
        "room_temperature_changed": len(set(room_temperatures)) > 1,
        "room_temperatures_kelvin": room_temperatures,
        "oracle_passed": evidence["oracles"][0]["passed"],
        "boptest_version": evidence["runtime"]["version"],
        "boptest_kpis": evidence["runtime"]["kpis"],
        "approved_run": approved.json(),
        "approved_artifact": {
            "bytes": len(exported.content),
            "sha256": _sha256(exported.content),
        },
        "review_bundle": {
            "bytes": len(review_bundle.content),
            "sha256": _sha256(review_bundle.content),
            "members": sorted(bundle_entries),
        },
        "review_bundle_contains_boptest_evidence": True,
        "approval_mode": "self-asserted integration-test identity",
        "boptest_qualified": True,
        "niagara_runtime_qualified": False,
        "live_deployment_allowed": False,
    }

    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = arguments.output.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(retained, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(arguments.output)
    print(
        json.dumps(
            {
                "status": "pass",
                "run_id": run_id,
                "evidence": str(arguments.output),
                "job_id": job_id,
            }
        )
    )


if __name__ == "__main__":
    main()
