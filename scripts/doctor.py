#!/usr/bin/env python3
"""Report what this machine can run and exactly how to fix what it cannot.

``make doctor`` is the diagnostic counterpart to ``make bootstrap-full``. It
checks prerequisites (interpreters, toolchains, container runtime, disk,
ports), compares every vendored checkout against the revision pinned in
``ops/stack.lock.json``, reports installed package versions and optional
extras, and inspects the queue and worker plane.

Every finding carries a status and, when it is not ready, the exact command
that fixes it. Nothing here mutates the machine.

Statuses:
  ready       the capability is installed and usable
  degraded    usable, but not the pinned or preferred configuration
  missing     not installed; remediation names the command to run
  blocked     unavailable for a reason this machine cannot fix (for example an
              egress policy that denies a container registry, or a licensed
              runtime that BACTalk does not ship)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bactalk.stack_lock import StackLock, StackLockError  # noqa: E402

VENDOR = ROOT / ".vendor"

READY = "ready"
DEGRADED = "degraded"
MISSING = "missing"
BLOCKED = "blocked"

_ICON = {READY: "OK  ", DEGRADED: "WARN", MISSING: "MISS", BLOCKED: "BLOCK"}


@dataclass
class Finding:
    section: str
    name: str
    status: str
    detail: str = ""
    remediation: str = ""
    expected: str = ""
    actual: str = ""


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    def count(self, status: str) -> int:
        return sum(1 for item in self.findings if item.status == status)

    @property
    def ok(self) -> bool:
        """True when nothing required is missing.

        ``blocked`` findings do not fail the report: they record an external
        constraint (an egress policy, a licensed runtime) that this machine
        cannot resolve, and they are listed separately so they are never
        mistaken for a working capability.
        """
        return self.count(MISSING) == 0


def which_version(tool: str, args: list[str] | None = None) -> str | None:
    if shutil.which(tool) is None:
        return None
    try:
        result = subprocess.run(
            [tool] + (args or ["--version"]),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    output = (result.stdout or result.stderr or "").strip()
    # Some JVM launchers prepend a JAVA_TOOL_OPTIONS banner.
    lines = [line for line in output.splitlines() if "Picked up" not in line]
    return lines[0].strip() if lines else None


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------


def check_interpreters(report: Report) -> None:
    section = "interpreters"
    major, minor = sys.version_info[:2]
    report.add(
        Finding(
            section,
            "python",
            READY if (major, minor) >= (3, 11) else MISSING,
            detail=f"{sys.version.split()[0]} at {sys.executable}",
            remediation="" if (major, minor) >= (3, 11) else "Install Python 3.11 or newer",
            expected=">=3.11",
            actual=f"{major}.{minor}",
        )
    )

    for tool, minimum, remediation in (
        ("node", "20", "Install Node.js 20+ (https://nodejs.org)"),
        ("npm", "10", "Install npm 10+ (ships with Node.js 20+)"),
        ("git", "2", "Install git 2.x"),
    ):
        version = which_version(tool)
        report.add(
            Finding(
                section,
                tool,
                READY if version else MISSING,
                detail=version or "not installed",
                remediation="" if version else remediation,
                expected=f">={minimum}",
                actual=version or "",
            )
        )

    java = which_version("java", ["-version"])
    javac = which_version("javac")
    report.add(
        Finding(
            section,
            "java/javac",
            READY if javac else DEGRADED,
            detail=f"java={java or 'missing'} javac={javac or 'missing'}",
            remediation=(
                ""
                if javac
                else "Install a JDK (javac) to compile generated ProgramObject "
                "qualification kernels: apt install default-jdk"
            ),
            expected="JDK with javac",
            actual=javac or "",
        )
    )

    cargo = which_version("cargo")
    report.add(
        Finding(
            section,
            "cargo/rustc",
            READY if cargo else MISSING,
            detail=cargo or "not installed",
            remediation=""
            if cargo
            else "Install Rust (https://rustup.rs) to build the Open Control "
            "Engine runner and the Rumoca flattener",
            expected="cargo",
            actual=cargo or "",
        )
    )


def check_system_libraries(report: Report) -> None:
    """Report native development libraries the Rust builds link against.

    Rumoca pulls in libudev-sys, whose build script needs the libudev
    development headers. Without them `make bootstrap-full` fails deep inside
    a cargo build with a linker error, so name the package up front.
    """
    section = "system libraries"
    requirements = (
        (
            "libudev",
            "Rumoca (libudev-sys) build dependency",
            "apt install libudev-dev pkg-config   # Debian/Ubuntu\n"
            "                                      dnf install systemd-devel  # Fedora/RHEL\n"
            "                                      (not required on macOS)",
        ),
    )
    if not have_pkg_config():
        report.add(
            Finding(
                section,
                "pkg-config",
                DEGRADED,
                detail="not installed; native library detection is unavailable",
                remediation="apt install pkg-config",
            )
        )
        return
    for library, purpose, remediation in requirements:
        present = (
            subprocess.run(
                ["pkg-config", "--exists", library], capture_output=True, timeout=30
            ).returncode
            == 0
        )
        report.add(
            Finding(
                section,
                library,
                READY if present else MISSING,
                detail=("present - " if present else "absent - ") + purpose,
                remediation="" if present else remediation,
            )
        )


def have_pkg_config() -> bool:
    return shutil.which("pkg-config") is not None


def check_container_runtime(report: Report) -> None:
    """Report the container runtime and whether images can actually be pulled.

    A reachable daemon is not sufficient: the Docker-tier simulations need to
    pull pinned images, and an egress policy that denies the registry blocks
    them just as completely as a missing daemon. Probing the registry keeps
    that distinction visible instead of failing later inside a compose up.
    """
    section = "containers"
    docker = which_version("docker")
    if docker is None:
        report.add(
            Finding(
                section,
                "docker",
                MISSING,
                detail="not installed",
                remediation="Install Docker Engine or Colima to run the "
                "BOPTEST/Alfalfa simulation tiers",
            )
        )
        return

    daemon = subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if daemon.returncode != 0:
        report.add(
            Finding(
                section,
                "docker daemon",
                MISSING,
                detail=docker,
                remediation="Start the container runtime: `colima start` or "
                "`sudo systemctl start docker`",
            )
        )
        return

    report.add(
        Finding(
            section,
            "docker daemon",
            READY,
            detail=f"client {docker}, server {daemon.stdout.strip()}",
        )
    )

    probe = subprocess.run(
        ["docker", "manifest", "inspect", "redis:7.4-alpine"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if probe.returncode == 0:
        report.add(
            Finding(section, "container registry", READY, detail="registry reachable")
        )
    else:
        combined = (probe.stderr or probe.stdout or "").strip()
        message = combined.splitlines()
        reason = message[-1][:200] if message else "unknown error"
        # Match against the whole output: registries put the denial token at
        # the end of a very long signed URL, past any display truncation.
        denied = any(
            token in combined.lower() for token in ("403", "denied", "forbidden", "401")
        )
        if denied:
            reason = "registry denied by this network's egress policy"
        report.add(
            Finding(
                section,
                "container registry",
                BLOCKED if denied else MISSING,
                detail=reason,
                remediation=(
                    "This network denies the container registry, so the "
                    "Docker-tier simulations (BOPTEST, Alfalfa) cannot run "
                    "here. Run `make full-stack-smoke` on a host that can "
                    "reach the registry, or allow it in the egress policy."
                    if denied
                    else "Check network access to the container registry"
                ),
            )
        )


def check_disk(report: Report, required_gb: int = 25) -> None:
    usage = shutil.disk_usage(ROOT)
    free_gb = usage.free / 1024**3
    report.add(
        Finding(
            "resources",
            "disk space",
            READY if free_gb >= required_gb else DEGRADED,
            detail=f"{free_gb:.1f} GiB free at {ROOT}",
            remediation=""
            if free_gb >= required_gb
            else f"A full bootstrap needs about {required_gb} GiB; free space "
            "or set a different checkout location",
            expected=f">={required_gb} GiB",
            actual=f"{free_gb:.1f} GiB",
        )
    )


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex((host, port)) == 0


def check_ports(report: Report) -> None:
    """Report the loopback ports the stack binds, and who is on them."""
    ports = {
        8000: "BACTalk API (make serve)",
        8011: "frontend dev proxy target",
        6380: "qualification queue (Valkey/Redis)",
        8088: "Alfalfa API",
        5000: "BOPTEST API",
    }
    for port, purpose in sorted(ports.items()):
        listening = _port_open(port)
        report.add(
            Finding(
                "ports",
                f"127.0.0.1:{port}",
                READY if listening else DEGRADED,
                detail=f"{'in use' if listening else 'free'} - {purpose}",
                remediation="",
            )
        )


def check_stack_lock(report: Report, lock: StackLock) -> None:
    """Compare every vendored checkout against its pinned revision."""
    section = "pinned sources"

    # Component name in the lock -> directory under .vendor/
    checkouts = {
        "modelica-buildings": "modelica-buildings",
        "modelica-standard-library": "modelica-standard-library",
        "modelica-json": "modelica-json",
        "open-control-engine": "open-control-engine",
        "open-control-library": "open-control-library",
        "aixocat": "aixocat",
        "pybog-source": "pybog",
        "n4-hvac-optimization-blocks": "n4-hvac-optimization-blocks",
        "dflexlibs": "dflexlibs",
        "boptest": "boptest",
        "alfalfa": "alfalfa",
        "ctrl-flow": "ctrl-flow-dev",
        "rumoca": "rumoca",
        "constrain": "constrain",
        "buildingmotif": "buildingmotif",
        "bacnet-simulator": "bacnet-simulator",
        "nhaystack": "nhaystack",
        "am8x-control": "am8x-control",
    }

    for component_name, directory in checkouts.items():
        try:
            component = lock.get(component_name)
        except StackLockError as exc:
            report.add(Finding(section, component_name, MISSING, detail=str(exc)))
            continue
        expected = component.revision or ""
        path = VENDOR / directory
        if not (path / ".git").exists():
            report.add(
                Finding(
                    section,
                    component_name,
                    MISSING,
                    detail=f"not checked out at .vendor/{directory}",
                    remediation="make bootstrap-full",
                    expected=expected[:12],
                )
            )
            continue
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        actual = result.stdout.strip()
        if actual == expected:
            report.add(
                Finding(
                    section,
                    component_name,
                    READY,
                    detail=f"{component.version_label()} @ {actual[:12]}",
                    expected=expected[:12],
                    actual=actual[:12],
                )
            )
        else:
            report.add(
                Finding(
                    section,
                    component_name,
                    DEGRADED,
                    detail="checkout is not at the pinned revision",
                    remediation=f"make bootstrap-full  (or: git -C .vendor/{directory} "
                    f"checkout --detach {expected})",
                    expected=expected[:12],
                    actual=actual[:12] or "unknown",
                )
            )


def check_built_artifacts(report: Report) -> None:
    section = "built helpers"
    artifacts = {
        "rumoca binary": (
            VENDOR / "bin" / "rumoca",
            "make bootstrap-full  (step: rumoca)",
        ),
        "oce runner": (
            ROOT
            / "ops"
            / "open-control-engine-runner"
            / "target"
            / "release"
            / "bactalk-oce-runner",
            "make bootstrap-full  (step: oce-runner)",
        ),
        "haxall toolchain": (
            ROOT / "ops" / "haxall" / "node_modules",
            "make bootstrap-full  (step: haxall)",
        ),
        "frontend deps": (
            ROOT / "web" / "node_modules",
            "make bootstrap-full  (step: frontend)",
        ),
        "frontend build": (
            ROOT / "src" / "bactalk" / "static-next" / "index.html",
            "make web-build",
        ),
        "ctrl-flow client deps": (
            VENDOR / "ctrl-flow-dev" / "client" / "node_modules",
            "make bootstrap-full  (step: ctrl-flow)",
        ),
        "modelica-json deps": (
            VENDOR / "modelica-json" / "node_modules",
            "make bootstrap-full  (step: modelica-json)",
        ),
    }
    for name, (path, remediation) in artifacts.items():
        present = path.exists()
        report.add(
            Finding(
                section,
                name,
                READY if present else MISSING,
                detail=str(path.relative_to(ROOT)) if present else f"absent: {path}",
                remediation="" if present else remediation,
            )
        )


def check_environments(report: Report) -> None:
    section = "isolated environments"
    environments = {
        ".venv": "make install",
        ".buildingmotif-venv": "make bootstrap-full  (step: buildingmotif)",
        ".constrain-venv": "make bootstrap-full  (step: constrain)",
        ".bacnet-simulator-venv": "make bootstrap-full  (step: bacnet-simulator)",
        ".volttron-venv": "make bootstrap-full  (step: volttron)",
    }
    for directory, remediation in environments.items():
        path = ROOT / directory / "bin" / "python"
        present = path.exists()
        report.add(
            Finding(
                section,
                directory,
                READY if present else MISSING,
                detail="present" if present else "absent",
                remediation="" if present else remediation,
            )
        )


def check_python_packages(report: Report) -> None:
    """Report base and optional Python package availability."""
    section = "python packages"
    try:
        from bactalk.optional_dependencies import optional_dependency_status
    except ImportError as exc:
        report.add(
            Finding(
                section,
                "bactalk",
                MISSING,
                detail=f"cannot import the package: {exc}",
                remediation="make install",
            )
        )
        return

    report.add(Finding(section, "bactalk", READY, detail="importable"))
    for item in optional_dependency_status():
        report.add(
            Finding(
                section,
                item["distribution"],
                READY if item["installed"] else MISSING,
                detail=(
                    f"{item['version']} - {item['capability']}"
                    if item["installed"]
                    else f"absent - {item['capability']} unavailable"
                ),
                remediation=item["remediation"] or "",
            )
        )


def check_queue_and_workers(report: Report) -> None:
    """Report the durable qualification queue and any running worker."""
    section = "queue and workers"
    url = os.getenv("BACTALK_QUEUE_URL", "redis://:bactalk-queue-local-secret@127.0.0.1:6380/0")
    reachable = False
    detail = "not reachable"
    try:
        import redis  # noqa: PLC0415 - optional at diagnosis time

        client = redis.Redis.from_url(url, socket_connect_timeout=2)
        client.ping()
        reachable = True
        detail = f"reachable at {url.rsplit('@', 1)[-1]}"
    except ImportError:
        detail = "redis client not installed"
    except Exception as exc:  # noqa: BLE001 - any failure means not reachable
        detail = f"{type(exc).__name__}: {str(exc)[:120]}"

    report.add(
        Finding(
            section,
            "qualification queue",
            READY if reachable else MISSING,
            detail=detail,
            remediation="" if reachable else "make queue-up",
        )
    )

    if reachable:
        try:
            import redis  # noqa: PLC0415
            from rq import Worker  # noqa: PLC0415

            connection = redis.Redis.from_url(url, socket_connect_timeout=2)
            workers = Worker.all(connection=connection)
            report.add(
                Finding(
                    section,
                    "qualification workers",
                    READY if workers else DEGRADED,
                    detail=f"{len(workers)} registered",
                    remediation="" if workers else "make qualification-worker",
                )
            )
        except Exception as exc:  # noqa: BLE001
            report.add(
                Finding(
                    section,
                    "qualification workers",
                    DEGRADED,
                    detail=f"cannot enumerate: {type(exc).__name__}",
                )
            )


def check_services(report: Report) -> None:
    """Probe the HTTP services the simulation tiers depend on."""
    section = "services"
    services = {
        "BOPTEST": (os.getenv("BACTALK_BOPTEST_URL", "http://127.0.0.1:5000"), "/version"),
        "Alfalfa": (os.getenv("BACTALK_ALFALFA_URL", "http://127.0.0.1:8088"), "/api/v2/version"),
    }
    try:
        import httpx  # noqa: PLC0415
    except ImportError:
        return
    for name, (base, path) in services.items():
        try:
            response = httpx.get(f"{base.rstrip('/')}{path}", timeout=3.0)
            ok = response.status_code < 400
            report.add(
                Finding(
                    section,
                    name,
                    READY if ok else DEGRADED,
                    detail=f"{base} -> HTTP {response.status_code}",
                    remediation="" if ok else f"make full-stack-up  (start {name})",
                )
            )
        except Exception as exc:  # noqa: BLE001
            # A service that only runs in a container is blocked, not broken,
            # when this network denies the registry that would supply it.
            blocked = _registry_is_blocked()
            report.add(
                Finding(
                    section,
                    name,
                    BLOCKED if blocked else MISSING,
                    detail=(
                        f"{base} unreachable; container registry denied by this "
                        "network's egress policy"
                        if blocked
                        else f"{base} unreachable ({type(exc).__name__})"
                    ),
                    remediation=(
                        f"Run the {name} tier on a host that can pull the pinned "
                        "images, or allow the registry in the egress policy."
                        if blocked
                        else f"make full-stack-up  (start {name}); requires a "
                        "container runtime with registry access"
                    ),
                )
            )


def _registry_is_blocked() -> bool:
    """True when a container runtime exists but its registry is denied."""
    if shutil.which("docker") is None:
        return False
    info = subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if info.returncode != 0:
        return False
    probe = subprocess.run(
        ["docker", "manifest", "inspect", "redis:7.4-alpine"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if probe.returncode == 0:
        return False
    combined = (probe.stderr or probe.stdout or "").lower()
    return any(token in combined for token in ("403", "denied", "forbidden", "401"))


def check_environment_variables(report: Report) -> None:
    section = "environment"
    variables = {
        "CEREBRAS_API_KEY": "AI conversation and coding roles (optional)",
        "BACTALK_QUEUE_URL": "durable qualification queue (defaults to loopback)",
        "BACTALK_RUNS": "run store location (defaults to .bactalk/runs)",
        "BACTALK_BOPTEST_URL": "BOPTEST service (defaults to http://127.0.0.1:5000)",
        "BACTALK_ALFALFA_URL": "Alfalfa service (defaults to http://127.0.0.1:8088)",
        "BACTALK_AUTH_CONFIG": "identity and RBAC configuration (optional)",
    }
    for name, purpose in variables.items():
        present = bool(os.getenv(name))
        report.add(
            Finding(
                section,
                name,
                READY if present else DEGRADED,
                # Never print a secret: report only presence.
                detail=("set" if present else "unset") + f" - {purpose}",
            )
        )


def check_licensed_blockers(report: Report) -> None:
    """Record the runtimes BACTalk deliberately does not ship."""
    report.add(
        Finding(
            "licensed runtimes",
            "Niagara Workbench / Station",
            BLOCKED,
            detail="No licensed Niagara runtime is bundled or qualified. Generated "
            ".bog and ProgramObject source packages require licensed Workbench "
            "compilation and station qualification outside BACTalk.",
            remediation="Supply a licensed Niagara lab; not reproducible from this repo.",
        )
    )


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def render(report: Report) -> str:
    lines: list[str] = []
    width = 30
    current = None
    for finding in report.findings:
        if finding.section != current:
            current = finding.section
            lines.append("")
            lines.append(current.upper())
            lines.append("-" * max(len(current), 20))
        line = f"  [{_ICON[finding.status]}] {finding.name:<{width}} {finding.detail}"
        lines.append(line)
        if finding.expected and finding.actual and finding.status != READY:
            lines.append(f"{'':<{width + 10}}expected {finding.expected}, found {finding.actual}")
        if finding.remediation:
            lines.append(f"{'':<{width + 10}}fix: {finding.remediation}")
    lines.append("")
    lines.append("=" * 72)
    lines.append(
        f"ready={report.count(READY)}  degraded={report.count(DEGRADED)}  "
        f"missing={report.count(MISSING)}  blocked={report.count(BLOCKED)}"
    )
    if report.count(BLOCKED):
        lines.append("")
        lines.append("Blocked capabilities (external constraint, not a defect):")
        for finding in report.findings:
            if finding.status == BLOCKED:
                lines.append(f"  - {finding.name}: {finding.detail}")
    if report.ok:
        lines.append("")
        lines.append("All required capabilities are installed.")
    else:
        lines.append("")
        lines.append("Missing capabilities; run `make bootstrap-full` or the fixes above.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--output", help="also write the JSON report to this path")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero when anything is missing (default: report only)",
    )
    args = parser.parse_args(argv)

    report = Report()
    check_interpreters(report)
    check_system_libraries(report)
    check_resources_and_lock(report)
    check_python_packages(report)
    check_environments(report)
    check_built_artifacts(report)
    check_container_runtime(report)
    check_queue_and_workers(report)
    check_services(report)
    check_ports(report)
    check_environment_variables(report)
    check_licensed_blockers(report)

    payload: dict[str, Any] = {
        "schema": "bactalk.doctor-report/v1",
        "ok": report.ok,
        "counts": {
            status: report.count(status)
            for status in (READY, DEGRADED, MISSING, BLOCKED)
        },
        "findings": [asdict(item) for item in report.findings],
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(render(report))

    if args.output:
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(payload, indent=2) + "\n")

    if args.strict and not report.ok:
        return 1
    return 0


def check_resources_and_lock(report: Report) -> None:
    check_disk(report)
    try:
        lock = StackLock()
    except StackLockError as exc:
        report.add(
            Finding("pinned sources", "ops/stack.lock.json", MISSING, detail=str(exc))
        )
        return
    report.add(
        Finding(
            "resources",
            "stack lock",
            READY,
            detail=f"verified {lock.verified_at}, sha256 {lock.sha256()[:12]}",
        )
    )
    check_stack_lock(report, lock)


if __name__ == "__main__":
    raise SystemExit(main())
