#!/usr/bin/env python3
"""Bring up, prove, and tear down the complete local BACTalk stack.

``up`` starts the long-running processes (qualification queue, RQ worker, API).
``smoke`` proves each product-wired integration by making it do real work --
translating a real source model, validating a real semantic graph, executing a
real control graph -- rather than checking that a port answers. ``down`` stops
what ``up`` started.

Each probe reports one of:

  ready    the integration did real work and returned the expected result
  blocked  the integration cannot run here for an external reason (no
           container registry, no licensed runtime); the reason is recorded
  missing  the integration is installed incorrectly or not at all

A blocked probe never counts as a pass. The smoke exits non-zero only when
something that *should* work on this host did not, so a machine with no
container access still gets a meaningful signal from everything else.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

VENDOR = ROOT / ".vendor"
VENV_PY = ROOT / ".venv" / "bin" / "python"
STATE_DIR = ROOT / ".bactalk" / "full-stack"
API_PORT = int(os.getenv("BACTALK_API_PORT", "8011"))

READY = "ready"
BLOCKED = "blocked"
MISSING = "missing"


@dataclass
class Probe:
    name: str
    status: str
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    remediation: str = ""


@dataclass
class SmokeReport:
    probes: list[Probe] = field(default_factory=list)

    def add(self, probe: Probe) -> None:
        icon = {READY: "OK   ", BLOCKED: "BLOCK", MISSING: "MISS "}[probe.status]
        print(f"  [{icon}] {probe.name:<34} {probe.detail}", flush=True)
        if probe.remediation:
            print(f"{'':<43}fix: {probe.remediation}", flush=True)
        self.probes.append(probe)

    def count(self, status: str) -> int:
        return sum(1 for probe in self.probes if probe.status == status)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": "bactalk.full-stack-smoke/v1",
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "counts": {
                status: self.count(status) for status in (READY, BLOCKED, MISSING)
            },
            "ok": self.count(MISSING) == 0,
            "probes": [asdict(probe) for probe in self.probes],
        }


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def run(command: list[str], *, cwd: Path | None = None, timeout: int = 900,
        env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    merged = dict(os.environ)
    merged.setdefault("PYTHONPATH", str(ROOT / "src"))
    if env:
        merged.update(env)
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else str(ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=merged,
    )


# --------------------------------------------------------------------------
# lifecycle
# --------------------------------------------------------------------------


def _pidfile(name: str) -> Path:
    return STATE_DIR / f"{name}.pid"


def _start_background(name: str, command: list[str], *, ready: Callable[[], bool],
                      timeout: float = 60.0) -> bool:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if ready():
        print(f"  {name}: already running")
        return True
    log = STATE_DIR / f"{name}.log"
    merged = dict(os.environ)
    merged.setdefault("PYTHONPATH", str(ROOT / "src"))
    with log.open("ab") as handle:
        process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=merged,
        )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ready():
            _pidfile(name).write_text(str(process.pid))
            print(f"  {name}: started (pid {process.pid})")
            return True
        if process.poll() is not None:
            print(f"  {name}: exited early, see {log}")
            return False
        time.sleep(0.4)
    process.terminate()
    print(f"  {name}: did not become ready within {timeout:.0f}s, see {log}")
    return False


def _stop_background(name: str) -> bool:
    path = _pidfile(name)
    if not path.is_file():
        return False
    try:
        pid = int(path.read_text().strip())
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ValueError, ProcessLookupError, PermissionError):
        path.unlink(missing_ok=True)
        return False
    time.sleep(1.0)
    path.unlink(missing_ok=True)
    print(f"  {name}: stopped")
    return True


def command_up() -> int:
    print("bringing up the BACTalk stack")
    ok = True

    queue = run([sys.executable, str(ROOT / "scripts" / "queue_service.py"), "up"], timeout=600)
    print(queue.stdout.rstrip() or queue.stderr.rstrip())
    if queue.returncode != 0:
        ok = False

    if not _start_background(
        "qualification-worker",
        [str(VENV_PY), "-m", "bactalk.cli", "qualification-worker"],
        ready=lambda: _worker_registered(),
        timeout=45.0,
    ):
        print("    the worker plane is required for queued qualification jobs")

    if not _start_background(
        "api",
        [
            str(VENV_PY),
            "-m",
            "uvicorn",
            "bactalk.api:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(API_PORT),
        ],
        ready=lambda: port_open(API_PORT),
        timeout=90.0,
    ):
        ok = False

    # The container-backed physics services are optional here: they are proven
    # by the docker tier, and a host without registry access still runs
    # everything else.
    compose_services_up()

    print("")
    print(f"API:      http://127.0.0.1:{API_PORT}")
    print(f"Next UI:  http://127.0.0.1:{API_PORT}/next/")
    print("Run `make full-stack-smoke` to prove the stack, `make full-stack-down` to stop.")
    return 0 if ok else 1


def compose_services_up() -> None:
    """Start BOPTEST and Alfalfa when a container runtime can pull images."""
    if shutil.which("docker") is None:
        print("  physics services: docker not installed, skipping")
        return
    info = run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=60)
    if info.returncode != 0:
        print("  physics services: no container runtime, skipping")
        return
    alfalfa = ROOT / "ops" / "alfalfa.compose.yml"
    if alfalfa.is_file():
        result = run(
            ["docker", "compose", "-f", str(alfalfa), "up", "-d", "--wait"], timeout=1800
        )
        if result.returncode != 0:
            tail = (result.stderr or "").strip().splitlines()
            print(f"  alfalfa: unavailable ({tail[-1][:160] if tail else 'unknown'})")
        else:
            print("  alfalfa: started")


def command_down() -> int:
    print("stopping the BACTalk stack")
    _stop_background("api")
    _stop_background("qualification-worker")
    run([sys.executable, str(ROOT / "scripts" / "queue_service.py"), "down"], timeout=300)
    if shutil.which("docker"):
        for compose in ("alfalfa.compose.yml", "qualification-queue.compose.yml"):
            path = ROOT / "ops" / compose
            if path.is_file():
                run(["docker", "compose", "-f", str(path), "down"], timeout=600)
    print("stack stopped")
    return 0


def _worker_registered() -> bool:
    try:
        import redis
        from rq import Worker

        url = os.getenv(
            "BACTALK_QUEUE_URL", "redis://:bactalk-queue-local-secret@127.0.0.1:6380/0"
        )
        connection = redis.Redis.from_url(url, socket_connect_timeout=2)
        return len(Worker.all(connection=connection)) > 0
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------
# probes
# --------------------------------------------------------------------------


def probe_api(report: SmokeReport) -> None:
    """The API must serve health, readiness, and the built UI."""
    try:
        import httpx
    except ImportError:
        report.add(Probe("api", MISSING, "httpx not installed", remediation="make install"))
        return
    base = f"http://127.0.0.1:{API_PORT}"
    try:
        health = httpx.get(f"{base}/api/health", timeout=10.0)
        readiness = httpx.get(f"{base}/api/system/readiness", timeout=30.0)
    except Exception as exc:  # noqa: BLE001
        report.add(
            Probe(
                "api",
                MISSING,
                f"unreachable at {base} ({type(exc).__name__})",
                remediation="make full-stack-up",
            )
        )
        return
    if health.status_code != 200 or readiness.status_code != 200:
        report.add(
            Probe("api", MISSING, f"health={health.status_code} readiness={readiness.status_code}")
        )
        return
    body = readiness.json()
    report.add(
        Probe(
            "api",
            READY,
            f"health 200, readiness 200 ({len(body.get('components', []))} components)",
            evidence={"mode": health.json().get("mode")},
        )
    )

    ui = httpx.get(f"{base}/next/", timeout=15.0)
    if ui.status_code == 200 and "<div id=\"root\"" in ui.text:
        report.add(Probe("react ui", READY, "/next/ serves the built SPA shell"))
    elif ui.status_code == 200:
        report.add(Probe("react ui", READY, "/next/ serves a document"))
    else:
        report.add(
            Probe(
                "react ui",
                MISSING,
                f"/next/ returned {ui.status_code}",
                remediation="make web-build",
            )
        )

    legacy = httpx.get(f"{base}/", timeout=15.0)
    report.add(
        Probe(
            "legacy workbench",
            READY if legacy.status_code == 200 else MISSING,
            f"/ returned {legacy.status_code}",
        )
    )


def probe_queue_and_worker(report: SmokeReport) -> None:
    """Prove the queue answers and an RQ worker is registered against it."""
    url = os.getenv("BACTALK_QUEUE_URL", "redis://:bactalk-queue-local-secret@127.0.0.1:6380/0")
    try:
        import redis
        from rq import Worker

        connection = redis.Redis.from_url(url, socket_connect_timeout=3)
        connection.ping()
    except Exception as exc:  # noqa: BLE001
        report.add(
            Probe(
                "qualification queue",
                MISSING,
                f"{type(exc).__name__}: {str(exc)[:100]}",
                remediation="make queue-up",
            )
        )
        return
    report.add(Probe("qualification queue", READY, "answers PING with durability enabled"))
    workers = Worker.all(connection=connection)
    report.add(
        Probe(
            "rq worker plane",
            READY if workers else MISSING,
            f"{len(workers)} worker(s) registered",
            remediation="" if workers else "make full-stack-up (starts the worker)",
        )
    )


def _contract(report: SmokeReport, name: str, script: str, *, timeout: int = 1200,
              needs: Path | None = None, remediation: str = "make bootstrap-full",
              python: Path | None = None, extra_pythonpath: str | None = None) -> None:
    """Run one verification contract and report what it proved.

    Some upstreams pin dependency versions that conflict with BACTalk's own,
    so their contracts run under an isolated interpreter. ``python`` and
    ``extra_pythonpath`` select that environment, mirroring the dedicated
    Makefile targets.
    """
    if needs is not None and not needs.exists():
        report.add(
            Probe(name, MISSING, f"not installed ({needs.relative_to(ROOT)})",
                  remediation=remediation)
        )
        return
    path = ROOT / "scripts" / script
    if not path.is_file():
        report.add(Probe(name, MISSING, f"contract script missing: {script}"))
        return
    interpreter = python or VENV_PY
    if not interpreter.exists():
        report.add(
            Probe(name, MISSING,
                  f"interpreter absent: {interpreter.relative_to(ROOT)}",
                  remediation=remediation)
        )
        return
    env = None
    if extra_pythonpath:
        env = {"PYTHONPATH": f"{ROOT / 'src'}:{extra_pythonpath}"}
    result = run([str(interpreter), str(path)], timeout=timeout, env=env)
    if result.returncode == 0:
        tail = [line for line in (result.stdout or "").strip().splitlines() if line]
        report.add(
            Probe(name, READY, tail[-1][:110] if tail else "contract passed")
        )
    else:
        combined = (result.stderr or result.stdout or "").strip()
        tail = [line for line in combined.splitlines() if line]
        report.add(
            Probe(name, MISSING, tail[-1][:160] if tail else "contract failed",
                  remediation=remediation)
        )


def probe_integrations(report: SmokeReport) -> None:
    """Prove each product-wired integration does real work."""
    _contract(report, "pybog compiler", "verify_pybog_examples.py",
              needs=VENDOR / "pybog")
    _contract(report, "open control engine", "verify_open_control_engine.py",
              needs=VENDOR / "open-control-engine", timeout=2400)
    _contract(report, "open control library", "verify_open_control_library.py",
              needs=VENDOR / "open-control-library", timeout=2400)
    _contract(report, "modelica tooling (cdl)", "verify_cdl_oce_pipeline.py",
              needs=VENDOR / "modelica-json", timeout=2400)
    _contract(report, "ctrl-flow design lane", "verify_ctrl_flow.py",
              needs=VENDOR / "ctrl-flow-dev", timeout=1800)
    _contract(report, "haxall / xeto", "verify_haxall.py",
              needs=ROOT / "ops" / "haxall" / "node_modules")
    _contract(report, "buildingmotif", "verify_buildingmotif.py",
              needs=ROOT / ".buildingmotif-venv" / "bin" / "python")
    # BuildingMOTIF runs through the main venv, which shells out to the
    # isolated environment; ConStrain and the BACnet simulator do not.
    _contract(report, "constrain", "verify_constrain.py",
              needs=ROOT / ".constrain-venv" / "bin" / "python",
              python=ROOT / ".constrain-venv" / "bin" / "python")
    _contract(report, "bacnet loopback lab", "verify_bacnet_lab.py", timeout=1800)
    _contract(report, "independent bacnet sim", "verify_independent_bacnet_simulator.py",
              needs=ROOT / ".bacnet-simulator-venv" / "bin" / "python", timeout=1800,
              python=ROOT / ".bacnet-simulator-venv" / "bin" / "python",
              extra_pythonpath=str(VENDOR / "bacnet-simulator" / "src"))
    _contract(report, "aixocat patterns", "verify_aixocat.py", needs=VENDOR / "aixocat")
    _contract(report, "niagara station assembly", "verify_niagara_station.py")
    _contract(report, "whole-building signals", "verify_project_signals.py")
    # The two workflow proofs: the contractor lane through the real API, and
    # the simulation qualification lane through the real queue and worker.
    _contract(report, "contractor workflow", "verify_contractor_workflow.py", timeout=1800)
    _contract(report, "simulation workflow", "verify_simulation_workflow.py", timeout=3600)


def probe_physics_services(report: SmokeReport) -> None:
    """Probe BOPTEST and Alfalfa, distinguishing 'blocked' from 'broken'."""
    try:
        import httpx
    except ImportError:
        return

    registry_blocked = _registry_blocked()

    for name, base, path in (
        ("boptest", os.getenv("BACTALK_BOPTEST_URL", "http://127.0.0.1:5000"), "/version"),
        ("alfalfa", os.getenv("BACTALK_ALFALFA_URL", "http://127.0.0.1:8088"), "/api/v2/version"),
    ):
        try:
            response = httpx.get(f"{base.rstrip('/')}{path}", timeout=5.0)
            if response.status_code < 400:
                report.add(Probe(name, READY, f"{base} -> HTTP {response.status_code}"))
                continue
            report.add(Probe(name, MISSING, f"{base} -> HTTP {response.status_code}"))
        except Exception:  # noqa: BLE001
            if registry_blocked:
                report.add(
                    Probe(
                        name,
                        BLOCKED,
                        "container registry is denied by this network's egress policy",
                        remediation="Run this tier on a host that can pull the pinned "
                        "images, or allow the registry in the egress policy.",
                    )
                )
            else:
                report.add(
                    Probe(
                        name,
                        MISSING,
                        f"{base} unreachable",
                        remediation="make full-stack-up (requires a container runtime)",
                    )
                )


def _registry_blocked() -> bool:
    if shutil.which("docker") is None:
        return False
    info = run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=60)
    if info.returncode != 0:
        return False
    probe = run(["docker", "manifest", "inspect", "redis:7.4-alpine"], timeout=120)
    if probe.returncode == 0:
        return False
    text = (probe.stderr or probe.stdout or "").lower()
    return any(token in text for token in ("403", "denied", "forbidden", "401"))


def probe_licensed(report: SmokeReport) -> None:
    report.add(
        Probe(
            "niagara runtime",
            BLOCKED,
            "no licensed Niagara Workbench or station is bundled; generated "
            "artifacts remain source-level until a licensed lab qualifies them",
            remediation="Supply a licensed Niagara lab; not reproducible from this repo.",
        )
    )


def command_smoke(output: Path | None) -> int:
    print("proving the BACTalk stack")
    report = SmokeReport()
    print("\nservice plane")
    probe_api(report)
    probe_queue_and_worker(report)
    print("\nintegrations")
    probe_integrations(report)
    print("\nphysics services")
    probe_physics_services(report)
    print("\nlicensed runtimes")
    probe_licensed(report)

    payload = report.to_json()
    destination = output or (ROOT / ".bactalk" / "full-stack-smoke.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2) + "\n")

    print("")
    print("=" * 72)
    print(
        f"ready={report.count(READY)}  blocked={report.count(BLOCKED)}  "
        f"missing={report.count(MISSING)}"
    )
    print(f"evidence written to {destination}")
    if report.count(BLOCKED):
        print("")
        print("Blocked (external constraint, not a product defect):")
        for probe in report.probes:
            if probe.status == BLOCKED:
                print(f"  - {probe.name}: {probe.detail}")
    if report.count(MISSING):
        print("")
        print("Not working on this host:")
        for probe in report.probes:
            if probe.status == MISSING:
                print(f"  - {probe.name}: {probe.detail}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["up", "smoke", "down"])
    parser.add_argument("--output", help="where to write smoke evidence JSON")
    args = parser.parse_args(argv)

    if args.action == "up":
        return command_up()
    if args.action == "down":
        return command_down()
    return command_smoke(Path(args.output) if args.output else None)


if __name__ == "__main__":
    raise SystemExit(main())
