#!/usr/bin/env python3
"""Prove the simulation qualification lane with real infrastructure.

The qualification lane has four independently verifiable parts:

  1. **Durable job plane** -- the queue, a real out-of-process RQ worker, the
     heartbeat lease, digest binding to the exact candidate, and the terminal
     state a contractor polls.
  2. **Trajectory grading** -- pyfunnel scoring a real reference against a real
     measured trajectory, including a failure that must not be reported as a
     pass.
  3. **Control boundary** -- the loopback BACnet/IP fake building driving a
     typed graph over real UDP.
  4. **Physics** -- BOPTEST and Alfalfa executing a building model.

Parts 1 to 3 need no container runtime and are proven here on any host. Part 4
needs the pinned container images; when they are unreachable this script says
so precisely and exits without claiming a physics result. It never substitutes
a stand-in for a physics engine and calls it proof.

Run ``make full-stack-up`` first so the queue and worker are live.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

READY = "proven"
BLOCKED = "blocked"
FAILED = "failed"


class Recorder:
    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []

    def add(self, name: str, status: str, detail: str, **evidence: Any) -> None:
        icon = {READY: "OK   ", BLOCKED: "BLOCK", FAILED: "FAIL "}[status]
        print(f"  [{icon}] {name:<34} {detail}", flush=True)
        self.steps.append(
            {"step": name, "status": status, "detail": detail, "evidence": evidence}
        )

    @property
    def failed(self) -> list[dict[str, Any]]:
        return [item for item in self.steps if item["status"] == FAILED]

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": "bactalk.simulation-workflow-evidence/v1",
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "steps": self.steps,
            "proven": sum(1 for item in self.steps if item["status"] == READY),
            "blocked": sum(1 for item in self.steps if item["status"] == BLOCKED),
            "failed": len(self.failed),
            "ok": not self.failed,
            "safety": {
                "live_building_writes": False,
                "licensed_niagara_runtime_qualified": False,
            },
        }


# --------------------------------------------------------------------------
# 1. durable job plane
# --------------------------------------------------------------------------


def prove_queue_and_worker(recorder: Recorder) -> bool:
    """The queue answers and a real worker process is registered against it."""
    url = os.getenv("BACTALK_QUEUE_URL", "redis://:bactalk-queue-local-secret@127.0.0.1:6380/0")
    try:
        import redis
        from rq import Worker

        connection = redis.Redis.from_url(url, socket_connect_timeout=3)
        connection.ping()
        workers = Worker.all(connection=connection)
    except Exception as exc:  # noqa: BLE001
        recorder.add(
            "durable queue",
            FAILED,
            f"{type(exc).__name__}: {str(exc)[:120]} (run: make full-stack-up)",
        )
        return False

    recorder.add(
        "durable queue",
        READY,
        f"Redis-protocol queue answers PING, {len(workers)} worker(s) registered",
        worker_count=len(workers),
    )
    return True


def _boptest_payload():
    """A minimal valid BOPTEST qualification payload.

    The bindings name real `bestest_air` signals so the payload passes the
    same validation a contractor's submission does; no physics runs here.
    """
    from bactalk.integrations.boptest_graph import (
        BoptestActuatorBinding,
        BoptestGraphMap,
        BoptestMeasurementBinding,
        BoptestTrajectoryOracle,
    )
    from bactalk.qualification_jobs import BoptestQualificationPayload

    return BoptestQualificationPayload(
        mapping=BoptestGraphMap(
            test_case="bestest_air",
            measurements=[
                BoptestMeasurementBinding(
                    graph_input="room_temp", measurement="zon_reaTRooAir_y"
                )
            ],
            actuators=[
                BoptestActuatorBinding(
                    graph_output="fan_command",
                    actuator="fcu_oveFan_u",
                    activation_actuator="fcu_oveFan_activate",
                )
            ],
        ),
        oracles=[
            BoptestTrajectoryOracle(
                id="room-temperature-holds",
                signal="zon_reaTRooAir_y",
                signal_kind="measurement",
                reference_times=[300.0, 600.0, 900.0],
                reference_values=[293.15, 293.15, 293.15],
                absolute_value_tolerance=0.5,
            )
        ],
        steps=3,
        step_seconds=300.0,
    )


def prove_job_lifecycle(recorder: Recorder) -> None:
    """A queued job is digest-bound, and a changed candidate is refused.

    This exercises the repository the worker and the API share: the record is
    written atomically, its inputs are re-hashed on every read, and a job
    bound to one candidate digest cannot be executed against a different one.
    """
    import tempfile

    from bactalk.qualification_jobs import (
        QualificationJobIntegrityError,
        QualificationJobRepository,
    )

    with tempfile.TemporaryDirectory(prefix="bactalk-jobs-") as workdir:
        jobs = QualificationJobRepository(Path(workdir))
        record = jobs.create_boptest(
            run_id="simproof0001",
            candidate_artifact_sha256="a" * 64,
            payload=_boptest_payload(),
        )
        reread = jobs.get(record.id)
        if reread.input_sha256 != record.input_sha256:
            recorder.add("job digest binding", FAILED, "input digest is not stable")
            return

        # Corrupt the retained request: the next read must refuse it.
        request_path = Path(workdir) / record.id / "request.json"
        original = request_path.read_bytes()
        request_path.write_bytes(json.dumps({"kind": "boptest", "steps": 9999}).encode())
        detected = False
        try:
            jobs.get(record.id)
        except QualificationJobIntegrityError:
            detected = True
        request_path.write_bytes(original)

        if not detected:
            recorder.add(
                "job digest binding",
                FAILED,
                "a tampered qualification request was accepted",
            )
            return

        recorder.add(
            "job digest binding",
            READY,
            "job bound to the candidate digest; a tampered request is refused",
            job_id=record.id,
            input_sha256=record.input_sha256[:16],
        )


def prove_orphan_fails_closed(recorder: Recorder) -> None:
    """A worker that dies mid-job must fail the job, never leave it running.

    This is the difference between a contractor seeing an honest failure and
    waiting forever on a spinner that implies work is still happening.
    """
    import tempfile
    from datetime import UTC, datetime, timedelta

    from bactalk.qualification_jobs import QualificationJobRepository, QualificationJobStatus

    with tempfile.TemporaryDirectory(prefix="bactalk-orphan-") as workdir:
        jobs = QualificationJobRepository(Path(workdir))
        record = jobs.create_boptest(
            run_id="orphanproof1",
            candidate_artifact_sha256="b" * 64,
            payload=_boptest_payload(),
        )
        jobs.mark_running(record.id, worker_id="worker-that-will-die")

        # Expire the lease as a hard process death would.
        path = Path(workdir) / record.id / "record.json"
        document = json.loads(path.read_text())
        document["lease_expires_at"] = (
            datetime.now(UTC) - timedelta(minutes=10)
        ).isoformat()
        path.write_text(json.dumps(document))

        jobs.expire_stale(record.id)
        after = jobs.get(record.id)
        if after.status != QualificationJobStatus.FAILED:
            recorder.add(
                "orphaned worker fails closed",
                FAILED,
                f"an expired lease left the job {after.status.value}, not failed",
            )
            return
        recorder.add(
            "orphaned worker fails closed",
            READY,
            f"expired lease recorded as {after.status.value}: "
            f"{(after.error or 'worker lost')[:70]}",
            error=after.error,
        )


def prove_real_worker_executes(recorder: Recorder) -> None:
    """A real out-of-process worker drains the queue.

    The web process only enqueues; a separate worker does the work. This runs
    the actual CLI worker in burst mode against the live queue and confirms it
    starts, registers, and exits cleanly.
    """
    venv_python = ROOT / ".venv" / "bin" / "python"
    if not venv_python.exists():
        recorder.add("out-of-process worker", FAILED, "main venv is absent")
        return
    result = subprocess.run(
        [str(venv_python), "-m", "bactalk.cli", "qualification-worker", "--burst"],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip().splitlines()
        recorder.add(
            "out-of-process worker",
            FAILED,
            tail[-1][:160] if tail else "worker exited non-zero",
        )
        return
    recorder.add(
        "out-of-process worker",
        READY,
        "real RQ worker started, drained the queue in burst mode, and exited 0",
    )


# --------------------------------------------------------------------------
# 2. trajectory grading
# --------------------------------------------------------------------------


def prove_trajectory_grading(recorder: Recorder) -> None:
    """pyfunnel must pass a matching trajectory and fail a diverging one."""
    from bactalk.optional_dependencies import PYFUNNEL

    if not PYFUNNEL.available():
        recorder.add(
            "trajectory grading",
            BLOCKED,
            f"pyfunnel is not installed. {PYFUNNEL.remediation}",
        )
        return

    import tempfile

    from bactalk.integrations.funnel import FunnelScorer

    reference_times = [0.0, 300.0, 600.0, 900.0]
    reference_values = [293.15, 293.4, 293.8, 294.0]

    with tempfile.TemporaryDirectory(prefix="bactalk-funnel-") as workdir:
        scorer = FunnelScorer()
        close = scorer.compare(
            reference_times,
            reference_values,
            reference_times,
            [value + 0.01 for value in reference_values],
            Path(workdir) / "pass",
            absolute_value_tolerance=0.05,
        )
        if not close.passed:
            recorder.add(
                "trajectory grading",
                FAILED,
                "pyfunnel rejected a trajectory inside its declared tolerance",
            )
            return

        diverged_values = [value + 5.0 for value in reference_values]
        diverged = scorer.compare(
            reference_times,
            reference_values,
            reference_times,
            diverged_values,
            Path(workdir) / "fail",
            absolute_value_tolerance=0.05,
        )
        if diverged.passed:
            recorder.add(
                "trajectory grading",
                FAILED,
                "pyfunnel reported a 5 K divergence as passing",
            )
            return

        counterexample = (
            diverged.counterexample(reference_times, diverged_values, context_samples=2)
            or {}
        )
        recorder.add(
            "trajectory grading",
            READY,
            "pyfunnel passes a trajectory in tolerance and fails a 5 K divergence "
            f"(peak error {counterexample.get('peak_error', 'n/a')})",
            peak_error=counterexample.get("peak_error"),
        )


# --------------------------------------------------------------------------
# 3. control boundary
# --------------------------------------------------------------------------


def prove_bacnet_control_boundary(recorder: Recorder) -> None:
    """The loopback BACnet/IP lab drives a typed graph over real UDP."""
    from bactalk.optional_dependencies import BAC0, BACPYPES3

    for dependency in (BACPYPES3, BAC0):
        if not dependency.available():
            recorder.add(
                "bacnet control boundary",
                BLOCKED,
                f"{dependency.distribution} is not installed. {dependency.remediation}",
            )
            return

    venv_python = ROOT / ".venv" / "bin" / "python"
    result = subprocess.run(
        [str(venv_python), str(ROOT / "scripts" / "verify_bacnet_lab.py")],
        capture_output=True,
        text=True,
        timeout=1800,
        cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip().splitlines()
        recorder.add(
            "bacnet control boundary",
            FAILED,
            tail[-1][:170] if tail else "bacnet lab contract failed",
        )
        return
    try:
        evidence = json.loads(result.stdout)
    except json.JSONDecodeError:
        evidence = {}
    recorder.add(
        "bacnet control boundary",
        READY,
        "virtual devices served real UDP reads, priority writes, and readbacks",
        acceptance_engine=evidence.get("acceptance_engine"),
        loopback_only=evidence.get("loopback_only", True),
    )


# --------------------------------------------------------------------------
# 4. physics
# --------------------------------------------------------------------------


def _registry_blocked() -> tuple[bool, str]:
    if shutil.which("docker") is None:
        return False, "docker is not installed"
    info = subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if info.returncode != 0:
        return False, "no container runtime is running"
    probe = subprocess.run(
        ["docker", "manifest", "inspect", "redis:7.4-alpine"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if probe.returncode == 0:
        return False, "registry reachable"
    combined = (probe.stderr or probe.stdout or "").lower()
    if any(token in combined for token in ("403", "denied", "forbidden", "401")):
        return True, "container registry denied by this network's egress policy"
    return False, "registry unreachable"


def prove_physics(recorder: Recorder, service: str, url: str, path: str, script: str) -> None:
    """Run the real physics contract, or record precisely why it cannot run."""
    try:
        import httpx

        response = httpx.get(f"{url.rstrip('/')}{path}", timeout=5.0)
        reachable = response.status_code < 400
    except Exception:  # noqa: BLE001
        reachable = False

    if not reachable:
        blocked, reason = _registry_blocked()
        recorder.add(
            f"{service} physics",
            BLOCKED if blocked else FAILED,
            f"{url} is not serving; {reason}",
            remediation=(
                "Run this tier on a host that can pull the pinned images."
                if blocked
                else "make full-stack-up"
            ),
        )
        return

    venv_python = ROOT / ".venv" / "bin" / "python"
    result = subprocess.run(
        [str(venv_python), str(ROOT / "scripts" / script)],
        capture_output=True,
        text=True,
        timeout=5400,
        cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip().splitlines()
        recorder.add(
            f"{service} physics",
            FAILED,
            tail[-1][:170] if tail else f"{script} failed",
        )
        return
    recorder.add(
        f"{service} physics",
        READY,
        f"{script} executed a real building model and graded its oracles",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(ROOT / ".bactalk" / "simulation-workflow-evidence.json"),
    )
    parser.add_argument(
        "--skip-bacnet",
        action="store_true",
        help="skip the loopback BACnet contract (it binds UDP ports)",
    )
    args = parser.parse_args(argv)

    recorder = Recorder()
    print("proving the simulation qualification lane")

    print("\ndurable job plane")
    if prove_queue_and_worker(recorder):
        prove_real_worker_executes(recorder)
    prove_job_lifecycle(recorder)
    prove_orphan_fails_closed(recorder)

    print("\ntrajectory grading")
    prove_trajectory_grading(recorder)

    print("\ncontrol boundary")
    if args.skip_bacnet:
        recorder.add("bacnet control boundary", BLOCKED, "skipped by request")
    else:
        prove_bacnet_control_boundary(recorder)

    print("\nbuilding physics")
    prove_physics(
        recorder,
        "boptest",
        os.getenv("BACTALK_BOPTEST_URL", "http://127.0.0.1:5000"),
        "/version",
        "verify_boptest_graph_runtime.py",
    )
    prove_physics(
        recorder,
        "alfalfa",
        os.getenv("BACTALK_ALFALFA_URL", "http://127.0.0.1:8088"),
        "/api/v2/version",
        "run_alfalfa_product.py",
    )

    payload = recorder.to_json()
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2) + "\n")

    print("")
    print("=" * 72)
    print(
        f"proven={payload['proven']}  blocked={payload['blocked']}  "
        f"failed={payload['failed']}"
    )
    print(f"evidence written to {destination}")
    if payload["blocked"]:
        print("")
        print("Blocked (external constraint, never counted as proof):")
        for step in recorder.steps:
            if step["status"] == BLOCKED:
                print(f"  - {step['step']}: {step['detail']}")
    if recorder.failed:
        print("")
        print("Failed:")
        for step in recorder.failed:
            print(f"  - {step['step']}: {step['detail']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
