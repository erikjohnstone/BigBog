#!/usr/bin/env python3
"""Start and stop the durable qualification queue.

BACTalk's qualification jobs run on an RQ queue backed by Valkey. The pinned
deployment is the container in ``ops/qualification-queue.compose.yml``, and
that remains the preferred path because it is the configuration the lock file
describes.

Some hosts cannot pull container images at all -- an egress policy that denies
the registry, or a machine with no container runtime. Because the queue is an
ordinary Redis-protocol server, this script falls back to a loopback-only
native ``redis-server`` with the same port, password, and append-only
durability settings. That keeps the worker plane, the heartbeat lease, and the
orphan fail-closed path provable on a restricted host instead of untestable.

The fallback is reported explicitly in the output and in the status JSON so it
is never mistaken for the pinned container deployment.
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "ops" / "qualification-queue.compose.yml"
STATE_DIR = ROOT / ".bactalk" / "queue"
PIDFILE = STATE_DIR / "redis.pid"
LOGFILE = STATE_DIR / "redis.log"
DATA_DIR = STATE_DIR / "data"

DEFAULT_PORT = 6380
DEFAULT_PASSWORD = os.getenv("BACTALK_QUEUE_PASSWORD", "bactalk-queue-local-secret")


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def container_runtime_available() -> bool:
    if shutil.which("docker") is None:
        return False
    probe = subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return probe.returncode == 0


def compose_up() -> bool:
    """Try the pinned container deployment. Returns True on success."""
    if not COMPOSE_FILE.is_file():
        return False
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d", "--wait"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode == 0:
        return True
    reason = (result.stderr or result.stdout or "").strip().splitlines()
    print("  pinned queue container unavailable:", reason[-1][:200] if reason else "unknown")
    return False


def compose_down() -> bool:
    if not COMPOSE_FILE.is_file() or not container_runtime_available():
        return False
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "down"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    return result.returncode == 0


def native_up(port: int, password: str) -> bool:
    """Start a loopback-only redis-server with the queue's durability settings."""
    if shutil.which("redis-server") is None:
        print(
            "  no native redis-server available either; install one with "
            "`apt install redis-server` or enable container registry access"
        )
        return False
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        "redis-server",
        "--bind",
        "127.0.0.1",  # loopback only: the queue is never exposed to a network
        "--port",
        str(port),
        "--requirepass",
        password,
        "--appendonly",
        "yes",
        "--appendfsync",
        "everysec",
        "--dir",
        str(DATA_DIR),
        "--daemonize",
        "no",
        "--save",
        "",
    ]
    with LOGFILE.open("ab") as log:
        process = subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    for _ in range(50):
        if port_open(port):
            PIDFILE.write_text(str(process.pid))
            return True
        if process.poll() is not None:
            print(f"  redis-server exited early; see {LOGFILE}")
            return False
        time.sleep(0.2)
    process.terminate()
    return False


def native_down(port: int) -> bool:
    if not PIDFILE.is_file():
        return False
    try:
        pid = int(PIDFILE.read_text().strip())
    except ValueError:
        PIDFILE.unlink(missing_ok=True)
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        PIDFILE.unlink(missing_ok=True)
        return False
    for _ in range(30):
        if not port_open(port):
            break
        time.sleep(0.2)
    PIDFILE.unlink(missing_ok=True)
    return True


def queue_url(port: int, password: str) -> str:
    return f"redis://:{password}@127.0.0.1:{port}/0"


def verify(port: int, password: str) -> bool:
    """Prove the queue actually answers the Redis protocol."""
    try:
        sys.path.insert(0, str(ROOT / "src"))
        import redis
    except ImportError:
        print("  redis client is not installed; run `make install`")
        return False
    try:
        client = redis.Redis.from_url(queue_url(port, password), socket_connect_timeout=3)
        return bool(client.ping())
    except Exception as exc:  # noqa: BLE001
        print(f"  queue did not answer PING: {type(exc).__name__}: {exc}")
        return False


def command_up(port: int, password: str) -> int:
    if port_open(port):
        if verify(port, password):
            print(f"queue already running at 127.0.0.1:{port}")
            return 0
        print(f"port {port} is in use but does not answer as the BACTalk queue")
        return 1

    mode = "unavailable"
    print("starting qualification queue")
    if container_runtime_available() and compose_up():
        mode = "container (pinned)"
    elif native_up(port, password):
        mode = "native redis-server (fallback)"
    else:
        print("could not start the qualification queue")
        return 1

    if not verify(port, password):
        print("queue started but did not answer PING")
        return 1

    print(f"queue ready: {mode} at 127.0.0.1:{port}")
    if mode.startswith("native"):
        print(
            "  note: this is the loopback fallback, not the pinned container. "
            "It is protocol-compatible and durable (appendonly), but the "
            "container image itself is not what was verified."
        )
    print(f"  export BACTALK_QUEUE_URL={queue_url(port, '***')}")
    return 0


def command_down(port: int) -> int:
    stopped = []
    if native_down(port):
        stopped.append("native redis-server")
    if compose_down():
        stopped.append("queue container")
    if not stopped:
        print("queue was not running")
        return 0
    print("stopped: " + ", ".join(stopped))
    return 0


def command_status(port: int, password: str) -> int:
    running = port_open(port)
    answered = verify(port, password) if running else False
    native = PIDFILE.is_file()
    print(
        json.dumps(
            {
                "schema": "bactalk.queue-status/v1",
                "port": port,
                "listening": running,
                "answers_ping": answered,
                "mode": "native-fallback" if native else ("container" if running else "stopped"),
            },
            indent=2,
        )
    )
    return 0 if answered else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["up", "down", "status"])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    args = parser.parse_args(argv)

    if args.action == "up":
        return command_up(args.port, args.password)
    if args.action == "down":
        return command_down(args.port)
    return command_status(args.port, args.password)


if __name__ == "__main__":
    raise SystemExit(main())
