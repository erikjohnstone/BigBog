#!/usr/bin/env python3
"""Reconstruct the entire pinned BACTalk stack from a clean clone.

Every selected upstream component is recorded in ``ops/stack.lock.json``; this
script is the one place that turns those pins into a working tree. It clones
each repository at its exact locked revision, verifies licenses and digests
where the lock carries them, applies the tracked patches under ``ops/``,
creates the isolated Python environments whose dependency pins conflict with
the main venv, installs the Node and Rust helpers, and installs the frontend
toolchain.

Design rules:

* **Idempotent.** Every step checks its own completion first, so a rerun is
  cheap and safe. A partially finished bootstrap can always be resumed by
  running the same command again.
* **Lock-driven.** No revision, repository URL, or license digest is written
  here. Anything pinned comes from ``ops/stack.lock.json`` so a checkout and
  the code that trusts it cannot drift.
* **Fail-closed.** A checkout that lands on the wrong revision, or a license
  whose digest does not match the lock, aborts that step loudly instead of
  leaving an unverified tree that later looks installed.

Nothing this script downloads is committed: ``.vendor/``, the virtual
environments, and ``node_modules/`` are all ignored by git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bactalk.stack_lock import StackLock  # noqa: E402

VENDOR = ROOT / ".vendor"
VENV = ROOT / ".venv"

# Isolated environments: these upstream projects pin dependency versions that
# conflict with BACTalk's own, so they are installed behind a process boundary.
BUILDINGMOTIF_VENV = ROOT / ".buildingmotif-venv"
CONSTRAIN_VENV = ROOT / ".constrain-venv"
BACNET_SIM_VENV = ROOT / ".bacnet-simulator-venv"
VOLTTRON_VENV = ROOT / ".volttron-venv"


class BootstrapError(RuntimeError):
    """Raised when a bootstrap step cannot complete."""


# --------------------------------------------------------------------------
# process helpers
# --------------------------------------------------------------------------


def run(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 3600,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run a command, streaming failures with enough context to act on."""
    merged = dict(os.environ)
    if env:
        merged.update(env)
    printable = " ".join(command)
    try:
        completed = subprocess.run(
            list(command),
            cwd=str(cwd) if cwd else None,
            env=merged,
            timeout=timeout,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise BootstrapError(f"timed out after {timeout}s: {printable}") from exc
    except FileNotFoundError as exc:
        raise BootstrapError(f"command not found: {command[0]} ({printable})") from exc
    if check and completed.returncode != 0:
        tail = (completed.stderr or completed.stdout or "").strip().splitlines()[-25:]
        raise BootstrapError(
            f"command failed ({completed.returncode}): {printable}\n" + "\n".join(tail)
        )
    return completed


def have(tool: str) -> bool:
    return shutil.which(tool) is not None


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def log(message: str) -> None:
    print(message, flush=True)


# --------------------------------------------------------------------------
# git helpers
# --------------------------------------------------------------------------


def git_head(repo: Path) -> str | None:
    if not (repo / ".git").exists():
        return None
    result = run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def clone_at_revision(
    repository: str,
    destination: Path,
    revision: str,
    *,
    sparse_paths: Sequence[str] | None = None,
    no_cone: bool = False,
) -> None:
    """Clone (or update) ``repository`` so ``destination`` sits on ``revision``.

    Uses a blobless partial clone, and a sparse checkout when only part of a
    large repository is adopted, so a full history is never downloaded. The
    resulting HEAD is verified against the lock before the step is considered
    done.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    already_at_revision = git_head(destination) == revision
    if already_at_revision and not sparse_paths:
        return
    if already_at_revision and sparse_paths:
        # The revision matches but the adopted subset may not: re-apply the
        # declared sparse scope so a narrowed or widened checkout is corrected
        # rather than silently kept.
        sparse = ["git", "-C", str(destination), "sparse-checkout", "set"]
        if no_cone:
            sparse.append("--no-cone")
        sparse += list(sparse_paths)
        run(sparse)
        run(["git", "-C", str(destination), "checkout", "--detach", revision])
        return

    if not (destination / ".git").exists():
        if destination.exists():
            shutil.rmtree(destination)
        command = ["git", "clone", "--filter=blob:none"]
        if sparse_paths:
            command.append("--no-checkout")
        command += [repository, str(destination)]
        run(command, timeout=3600)

    if sparse_paths:
        sparse = ["git", "-C", str(destination), "sparse-checkout", "set"]
        if no_cone:
            sparse.append("--no-cone")
        sparse += list(sparse_paths)
        run(sparse)

    # Fetch just the pinned commit when the clone does not already contain it.
    fetch = run(
        ["git", "-C", str(destination), "fetch", "--depth", "1", "origin", revision],
        check=False,
        timeout=3600,
    )
    if fetch.returncode != 0:
        run(["git", "-C", str(destination), "fetch", "origin"], timeout=3600)

    run(["git", "-C", str(destination), "checkout", "--detach", revision])

    head = git_head(destination)
    if head != revision:
        raise BootstrapError(
            f"{destination.name} checked out {head}, expected pinned revision {revision}"
        )


def locked_sparse(component) -> tuple[Sequence[str] | None, bool]:
    """Sparse-checkout scope a component declares in the lock.

    The adopted subset of a large upstream is part of the pin: it decides
    which sources BACTalk actually admits. Declaring it in the lock keeps the
    scope reviewable and reproducible instead of hiding it in this script.
    """
    paths = component.data.get("sparse_paths")
    if not paths:
        return None, False
    return list(paths), bool(component.data.get("sparse_no_cone", False))


def verify_license(path: Path, expected_sha256: str, component: str) -> None:
    """Fail closed when a license file does not match the digest in the lock."""
    if not path.is_file():
        raise BootstrapError(f"{component}: license file is missing at {path}")
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise BootstrapError(
            f"{component}: license digest mismatch\n"
            f"  expected {expected_sha256}\n  actual   {actual}\n"
            f"  The upstream license text changed; review it before continuing."
        )


def apply_patch(repo: Path, patch: Path, component: str) -> None:
    """Apply a tracked patch idempotently, or fail if it no longer applies."""
    if not patch.is_file():
        raise BootstrapError(f"{component}: tracked patch missing at {patch}")
    already = run(
        ["git", "-C", str(repo), "apply", "--reverse", "--check", str(patch)],
        check=False,
    )
    if already.returncode == 0:
        return
    applies = run(["git", "-C", str(repo), "apply", "--check", str(patch)], check=False)
    if applies.returncode != 0:
        raise BootstrapError(
            f"{component}: tracked patch {patch.name} does not apply cleanly to the "
            f"pinned revision. Upstream changed; regenerate the patch."
        )
    run(["git", "-C", str(repo), "apply", str(patch)])


def make_venv(path: Path, python: str = "python3.11") -> None:
    if (path / "bin" / "python").exists():
        return
    interpreter = python if have(python) else sys.executable
    run([interpreter, "-m", "venv", str(path)], timeout=600)


# --------------------------------------------------------------------------
# step model
# --------------------------------------------------------------------------


@dataclass
class Step:
    """One idempotent bootstrap unit."""

    name: str
    description: str
    action: Callable[[StackLock], None]
    group: str = "core"
    check: Callable[[], bool] | None = None
    requires_tools: tuple[str, ...] = ()
    optional: bool = False
    """Optional steps report a warning instead of failing the bootstrap."""

    notes: str = ""


@dataclass
class StepResult:
    name: str
    status: str  # ok | skipped | already | failed
    seconds: float
    detail: str = ""


@dataclass
class BootstrapReport:
    results: list[StepResult] = field(default_factory=list)

    def add(self, result: StepResult) -> None:
        self.results.append(result)

    @property
    def failed(self) -> list[StepResult]:
        return [item for item in self.results if item.status == "failed"]

    def to_json(self, lock: StackLock) -> dict:
        return {
            "schema": "bactalk.bootstrap-report/v1",
            "stack_lock_sha256": lock.sha256(),
            "stack_lock_verified_at": lock.verified_at,
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "steps": [
                {
                    "name": item.name,
                    "status": item.status,
                    "seconds": round(item.seconds, 2),
                    "detail": item.detail,
                }
                for item in self.results
            ],
            "ok": not self.failed,
        }


# --------------------------------------------------------------------------
# steps: python environments
# --------------------------------------------------------------------------


def step_python_base(lock: StackLock) -> None:
    make_venv(VENV, "python3.11")
    run(
        [str(VENV / "bin" / "python"), "-m", "pip", "install", "--upgrade", "pip"],
        timeout=900,
    )
    run(
        [str(VENV / "bin" / "python"), "-m", "pip", "install", "-e", ".[test]"],
        cwd=ROOT,
        timeout=1800,
    )


def step_python_suite(lock: StackLock) -> None:
    """Install every optional extra so no capability reports unavailable."""
    run(
        [str(VENV / "bin" / "python"), "-m", "pip", "install", "-e", ".[suite,test]"],
        cwd=ROOT,
        timeout=2400,
    )


# --------------------------------------------------------------------------
# steps: vendored source libraries
# --------------------------------------------------------------------------


def step_modelica_buildings(lock: StackLock) -> None:
    component = lock.get("modelica-buildings")
    sparse_paths, no_cone = locked_sparse(component)
    clone_at_revision(
        component.require_repository(),
        VENDOR / "modelica-buildings",
        component.require_revision(),
        sparse_paths=sparse_paths,
        no_cone=no_cone,
    )


def step_modelica_standard_library(lock: StackLock) -> None:
    component = lock.get("modelica-standard-library")
    clone_at_revision(
        component.require_repository(),
        VENDOR / "modelica-standard-library",
        component.require_revision(),
    )


def step_modelica_buildings_rumoca(lock: StackLock) -> None:
    """A second Buildings checkout carrying the Rumoca compatibility patch.

    Kept separate from the CXF lane's checkout so the source that
    modelica-json translates stays exactly as upstream published it.
    """
    component = lock.get("modelica-buildings")
    destination = VENDOR / "modelica-buildings-rumoca"
    clone_at_revision(
        component.require_repository(),
        destination,
        component.require_revision(),
        sparse_paths=["Buildings/Controls/OBC", "Buildings/Utilities"],
    )
    apply_patch(
        destination,
        ROOT / "ops" / "rumoca" / "modelica-buildings-compat.patch",
        "modelica-buildings-rumoca",
    )


def step_modelica_json(lock: StackLock) -> None:
    component = lock.get("modelica-json")
    destination = VENDOR / "modelica-json"
    clone_at_revision(
        component.require_repository(), destination, component.require_revision()
    )
    patch = ROOT / "ops" / "modelica-json" / "modelica-mode-null-type.patch"
    expected = component.data.get("patch_sha256")
    if expected:
        actual = sha256_file(patch)
        if actual != expected:
            raise BootstrapError(
                f"modelica-json: tracked patch digest mismatch\n"
                f"  expected {expected} (ops/stack.lock.json)\n  actual   {actual}"
            )
    apply_patch(destination, patch, "modelica-json")
    if have("npm"):
        run(
            ["npm", "install", "--ignore-scripts", "--no-audit", "--no-fund"],
            cwd=destination,
            timeout=2400,
        )


def step_open_control_engine(lock: StackLock) -> None:
    component = lock.get("open-control-engine")
    clone_at_revision(
        component.require_repository(),
        VENDOR / "open-control-engine",
        component.require_revision(),
    )


def step_open_control_library(lock: StackLock) -> None:
    component = lock.get("open-control-library")
    clone_at_revision(
        component.require_repository(),
        VENDOR / "open-control-library",
        component.require_revision(),
    )


def step_open_control_engine_pin(lock: StackLock) -> None:
    """Second Open Control Engine checkout at the revision the library pins.

    ``open-control-library`` records the exact engine revision its vectors
    were produced against, which can differ from the engine BACTalk builds its
    runner from. Both are pinned, so both are checked out.
    """
    component = lock.get("open-control-library")
    engine = lock.get("open-control-engine")
    clone_at_revision(
        engine.require_repository(),
        VENDOR / "open-control",
        component.require("engine_revision"),
    )


def step_aixocat(lock: StackLock) -> None:
    component = lock.get("aixocat")
    sparse_paths, no_cone = locked_sparse(component)
    destination = VENDOR / "aixocat"
    clone_at_revision(
        component.require_repository(),
        destination,
        component.require_revision(),
        sparse_paths=sparse_paths,
        no_cone=no_cone,
    )
    # The adopted scope is a count contract: it admits exactly the reviewed
    # control patterns and no vendor binaries. Verify it rather than trusting
    # that the sparse patterns still select what they did when pinned.
    expected = component.data.get("expected_pou_count")
    if expected is not None:
        found = sum(1 for _ in destination.rglob("*.TcPOU"))
        if found != expected:
            raise BootstrapError(
                f"aixocat sparse scope admitted {found} POU sources, expected "
                f"{expected}. The upstream layout or the declared sparse_paths "
                f"in ops/stack.lock.json changed; review the adopted scope."
            )
    binaries = [
        path.name
        for path in destination.rglob("*")
        if path.is_file()
        and path.suffix.lower()
        in {".compiled-library", ".library", ".bootinfo", ".tizip"}
    ]
    if binaries:
        raise BootstrapError(
            f"aixocat sparse scope admitted {len(binaries)} vendor binaries "
            f"(for example {binaries[0]}); the scope must stay source-only."
        )


def step_pybog_source(lock: StackLock) -> None:
    component = lock.get("pybog-source")
    clone_at_revision(
        component.require_repository(), VENDOR / "pybog", component.require_revision()
    )


def step_n4_hvac_library(lock: StackLock) -> None:
    component = lock.get("n4-hvac-optimization-blocks")
    clone_at_revision(
        component.require_repository(),
        VENDOR / "n4-hvac-optimization-blocks",
        component.require_revision(),
    )


def step_dflexlibs(lock: StackLock) -> None:
    component = lock.get("dflexlibs")
    clone_at_revision(
        component.require_repository(), VENDOR / "dflexlibs", component.require_revision()
    )


def step_boptest_source(lock: StackLock) -> None:
    component = lock.get("boptest")
    clone_at_revision(
        component.require_repository(), VENDOR / "boptest", component.require_revision()
    )


def step_alfalfa_source(lock: StackLock) -> None:
    component = lock.get("alfalfa")
    clone_at_revision(
        component.require_repository(), VENDOR / "alfalfa", component.require_revision()
    )


def step_nhaystack(lock: StackLock) -> None:
    component = lock.get("nhaystack")
    clone_at_revision(
        component.require_repository(), VENDOR / "nhaystack", component.require_revision()
    )


def step_am8x_control(lock: StackLock) -> None:
    component = lock.get("am8x-control")
    clone_at_revision(
        component.require_repository(),
        VENDOR / "am8x-control",
        component.require_revision(),
    )


# --------------------------------------------------------------------------
# steps: ctrl-flow (node) and rumoca (rust)
# --------------------------------------------------------------------------


def step_ctrl_flow(lock: StackLock) -> None:
    component = lock.get("ctrl-flow")
    source = VENDOR / "ctrl-flow-dev"
    sparse_paths, no_cone = locked_sparse(component)
    clone_at_revision(
        component.require_repository(),
        source,
        component.require_revision(),
        sparse_paths=sparse_paths,
        no_cone=no_cone,
    )
    license_sha = component.data.get("license_sha256")
    if license_sha:
        verify_license(source / "LICENSE.txt", license_sha, "ctrl-flow")

    if have("npm"):
        run(["npm", "ci", "--ignore-scripts"], cwd=source / "client", timeout=2400)
        run(["npm", "ci", "--ignore-scripts"], cwd=source / "server", timeout=2400)

    # ctrl-flow's parser depends on its own pinned modelica-json revision.
    dependency_root = VENDOR / "ctrl-flow-dependencies"
    dependency_root.mkdir(parents=True, exist_ok=True)
    parser_revision = component.require("parser_dependency_revision")
    modelica_json = lock.get("modelica-json")
    clone_at_revision(
        modelica_json.require_repository(),
        dependency_root / "modelica-json",
        parser_revision,
    )
    if have("npm"):
        run(
            ["npm", "install", "--ignore-scripts", "--no-audit", "--no-fund"],
            cwd=dependency_root / "modelica-json",
            timeout=2400,
        )


def step_rumoca(lock: StackLock) -> None:
    component = lock.get("rumoca")
    source = VENDOR / "rumoca"
    clone_at_revision(
        component.require_repository(), source, component.require_revision()
    )
    binary = VENDOR / "bin" / "rumoca"
    if binary.exists():
        return
    if not have("cargo"):
        raise BootstrapError("cargo is required to build Rumoca; install Rust toolchain")
    run(
        [
            "cargo",
            "build",
            "--release",
            "-p",
            "rumoca",
            "--bin",
            "rumoca",
            "--manifest-path",
            str(source / "Cargo.toml"),
        ],
        timeout=3600,
    )
    binary.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / "target" / "release" / "rumoca", binary)
    binary.chmod(0o755)
    if os.getenv("BACTALK_KEEP_RUMOCA_BUILD_CACHE", "0") != "1":
        run(
            ["cargo", "clean", "--release", "--manifest-path", str(source / "Cargo.toml")],
            check=False,
            timeout=600,
        )


def step_rust_toolchain(lock: StackLock) -> None:
    """Install the exact Rust toolchain Open Control Engine pins.

    Open Control Engine is built with edition 2024 and pins its channel in a
    ``rust-toolchain.toml``. A host whose default toolchain is older cannot
    compile it, so the pinned channel is installed explicitly rather than
    leaving the build to fail with a version error.
    """
    channel = lock.get("rust-toolchain").require("channel")
    if not have("rustup"):
        raise BootstrapError(
            f"rustup is required to install the pinned Rust toolchain {channel}. "
            "Install Rust from https://rustup.rs"
        )
    installed = run(["rustup", "toolchain", "list"], check=False)
    if channel in (installed.stdout or ""):
        return
    run(["rustup", "toolchain", "install", channel, "--profile", "minimal"], timeout=1800)


def step_oce_runner(lock: StackLock) -> None:
    """Build the Rust runner that drives Open Control Engine."""
    if not have("cargo"):
        raise BootstrapError("cargo is required to build the Open Control Engine runner")
    manifest = ROOT / "ops" / "open-control-engine-runner" / "Cargo.toml"
    if not manifest.is_file():
        raise BootstrapError(f"Open Control Engine runner manifest missing at {manifest}")
    if not (VENDOR / "open-control-engine").is_dir():
        raise BootstrapError(
            "Open Control Engine source is not installed; run the "
            "open-control-engine step first"
        )
    channel = lock.get("rust-toolchain").require("channel")
    run(
        ["cargo", "build", "--release", "--manifest-path", str(manifest)],
        timeout=5400,
        # The runner depends on Open Control Engine, which requires the exact
        # pinned channel; a newer or older default toolchain fails to compile.
        env={"RUSTUP_TOOLCHAIN": channel},
    )


# --------------------------------------------------------------------------
# steps: isolated python environments
# --------------------------------------------------------------------------


def step_buildingmotif(lock: StackLock) -> None:
    component = lock.get("buildingmotif")
    source = VENDOR / "buildingmotif"
    clone_at_revision(
        component.require_repository(), source, component.require_revision()
    )
    make_venv(BUILDINGMOTIF_VENV)
    run(
        [str(BUILDINGMOTIF_VENV / "bin" / "pip"), "install", str(source)],
        timeout=2400,
    )


def step_constrain(lock: StackLock) -> None:
    component = lock.get("constrain")
    source = VENDOR / "constrain"
    clone_at_revision(
        component.require_repository(), source, component.require_revision()
    )
    make_venv(CONSTRAIN_VENV)
    run([str(CONSTRAIN_VENV / "bin" / "pip"), "install", "-e", str(source)], timeout=2400)


def step_bacnet_simulator(lock: StackLock) -> None:
    component = lock.get("bacnet-simulator")
    source = VENDOR / "bacnet-simulator"
    clone_at_revision(
        component.require_repository(), source, component.require_revision()
    )
    license_sha = component.data.get("license_sha256")
    if license_sha:
        verify_license(source / "LICENSE", license_sha, "bacnet-simulator")
    make_venv(BACNET_SIM_VENV)
    run(
        [str(BACNET_SIM_VENV / "bin" / "pip"), "install", "-e", f"{source}[dev]"],
        timeout=2400,
    )


def step_volttron(lock: StackLock) -> None:
    """VOLTTRON is a Linux/Python 3.11 edge profile behind its own environment."""
    requirements = ROOT / "ops" / "volttron" / "requirements.txt"
    if not requirements.is_file():
        raise BootstrapError(f"VOLTTRON requirements missing at {requirements}")
    make_venv(VOLTTRON_VENV)
    run(
        [str(VOLTTRON_VENV / "bin" / "pip"), "install", "-r", str(requirements)],
        timeout=3600,
    )


# --------------------------------------------------------------------------
# steps: node toolchains
# --------------------------------------------------------------------------


def step_haxall(lock: StackLock) -> None:
    if not have("npm"):
        raise BootstrapError("npm is required to install Haxall")
    run(["npm", "install", "--no-audit", "--no-fund"], cwd=ROOT / "ops" / "haxall", timeout=2400)


def step_frontend(lock: StackLock) -> None:
    if not have("npm"):
        raise BootstrapError("npm is required to install the frontend toolchain")
    web = ROOT / "web"
    lockfile = web / "package-lock.json"
    command = ["npm", "ci"] if lockfile.is_file() else ["npm", "install"]
    run(command + ["--no-audit", "--no-fund"], cwd=web, timeout=2400)


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------


def build_steps() -> list[Step]:
    return [
        Step(
            "python-base",
            "Create .venv and install BACTalk with test extras",
            step_python_base,
            group="python",
            check=lambda: (VENV / "bin" / "python").exists(),
            requires_tools=("python3",),
        ),
        Step(
            "python-suite",
            "Install every optional extra (AI, BACnet, Alfalfa, funnel, FDD)",
            step_python_suite,
            group="python",
            requires_tools=("python3",),
        ),
        Step(
            "modelica-buildings",
            "LBNL Modelica Buildings OBC/G36 and plant controls source",
            step_modelica_buildings,
            group="sources",
            check=lambda: (VENDOR / "modelica-buildings" / "Buildings").is_dir(),
            requires_tools=("git",),
        ),
        Step(
            "modelica-standard-library",
            "Pinned MSL 4.1.0 used by the Rumoca flattener",
            step_modelica_standard_library,
            group="sources",
            check=lambda: (VENDOR / "modelica-standard-library" / ".git").exists(),
            requires_tools=("git",),
        ),
        Step(
            "modelica-buildings-rumoca",
            "Second Buildings checkout carrying the Rumoca compatibility patch",
            step_modelica_buildings_rumoca,
            group="sources",
            requires_tools=("git",),
        ),
        Step(
            "modelica-json",
            "CDL/CXF translator with the tracked null-type patch",
            step_modelica_json,
            group="sources",
            requires_tools=("git", "npm"),
        ),
        Step(
            "open-control-engine",
            "External CXF validation runtime source",
            step_open_control_engine,
            group="sources",
            check=lambda: (VENDOR / "open-control-engine" / ".git").exists(),
            requires_tools=("git",),
        ),
        Step(
            "open-control-library",
            "137 executable CXF fault rules",
            step_open_control_library,
            group="sources",
            check=lambda: (VENDOR / "open-control-library" / ".git").exists(),
            requires_tools=("git",),
        ),
        Step(
            "open-control-engine-pin",
            "Engine checkout at the revision the fault library was validated against",
            step_open_control_engine_pin,
            group="sources",
            check=lambda: (VENDOR / "open-control" / ".git").exists(),
            requires_tools=("git",),
        ),
        Step(
            "aixocat",
            "Sparse IEC 61131-3 control pattern corpus",
            step_aixocat,
            group="sources",
            check=lambda: (VENDOR / "aixocat" / ".git").exists(),
            requires_tools=("git",),
        ),
        Step(
            "pybog-source",
            "pybog compiler source and equipment examples",
            step_pybog_source,
            group="sources",
            check=lambda: (VENDOR / "pybog" / ".git").exists(),
            requires_tools=("git",),
        ),
        Step(
            "n4-hvac-library",
            "Pinned Niagara ProgramObject reference archives",
            step_n4_hvac_library,
            group="sources",
            check=lambda: (VENDOR / "n4-hvac-optimization-blocks" / ".git").exists(),
            requires_tools=("git",),
        ),
        Step(
            "dflexlibs",
            "LBNL demand-flexibility reference controls",
            step_dflexlibs,
            group="sources",
            check=lambda: (VENDOR / "dflexlibs" / ".git").exists(),
            requires_tools=("git",),
        ),
        Step(
            "boptest-source",
            "BOPTEST building-physics service source and test cases",
            step_boptest_source,
            group="sources",
            check=lambda: (VENDOR / "boptest" / ".git").exists(),
            requires_tools=("git",),
        ),
        Step(
            "alfalfa-source",
            "Alfalfa whole-building FMU service source",
            step_alfalfa_source,
            group="sources",
            check=lambda: (VENDOR / "alfalfa" / ".git").exists(),
            requires_tools=("git",),
        ),
        Step(
            "nhaystack",
            "nHaystack tagging reference source",
            step_nhaystack,
            group="sources",
            check=lambda: (VENDOR / "nhaystack" / ".git").exists(),
            requires_tools=("git",),
            optional=True,
        ),
        Step(
            "am8x-control",
            "Niagara alarm automation reference source",
            step_am8x_control,
            group="sources",
            check=lambda: (VENDOR / "am8x-control" / ".git").exists(),
            requires_tools=("git",),
            optional=True,
        ),
        Step(
            "ctrl-flow",
            "LBNL ctrl-flow Linkage Schema interpreter and its parser dependency",
            step_ctrl_flow,
            group="toolchains",
            requires_tools=("git", "npm"),
        ),
        Step(
            "rumoca",
            "Build the pinned Rumoca Modelica flattener",
            step_rumoca,
            group="toolchains",
            check=lambda: (VENDOR / "bin" / "rumoca").exists(),
            requires_tools=("git", "cargo"),
        ),
        Step(
            "rust-toolchain",
            "Install the exact Rust toolchain Open Control Engine pins",
            step_rust_toolchain,
            group="toolchains",
            requires_tools=("rustup",),
        ),
        Step(
            "oce-runner",
            "Build the Rust Open Control Engine runner",
            step_oce_runner,
            group="toolchains",
            requires_tools=("cargo",),
        ),
        Step(
            "buildingmotif",
            "Isolated BuildingMOTIF semantic template environment",
            step_buildingmotif,
            group="environments",
            check=lambda: (BUILDINGMOTIF_VENV / "bin" / "python").exists(),
            requires_tools=("git", "python3"),
        ),
        Step(
            "constrain",
            "Isolated PNNL ConStrain verification environment",
            step_constrain,
            group="environments",
            check=lambda: (CONSTRAIN_VENV / "bin" / "python").exists(),
            requires_tools=("git", "python3"),
        ),
        Step(
            "bacnet-simulator",
            "Independent BACnet simulator oracle environment",
            step_bacnet_simulator,
            group="environments",
            check=lambda: (BACNET_SIM_VENV / "bin" / "python").exists(),
            requires_tools=("git", "python3"),
        ),
        Step(
            "volttron",
            "Isolated VOLTTRON edge profile (Linux/Python 3.11 only)",
            step_volttron,
            group="environments",
            check=lambda: (VOLTTRON_VENV / "bin" / "python").exists(),
            requires_tools=("python3",),
            optional=True,
            notes="VOLTTRON pins gevent, which only builds on Linux with Python 3.11.",
        ),
        Step(
            "haxall",
            "Haxall/Xeto semantic validation toolchain",
            step_haxall,
            group="toolchains",
            check=lambda: (ROOT / "ops" / "haxall" / "node_modules").is_dir(),
            requires_tools=("npm",),
        ),
        Step(
            "frontend",
            "Install the React/TypeScript frontend toolchain",
            step_frontend,
            group="frontend",
            check=lambda: (ROOT / "web" / "node_modules").is_dir(),
            requires_tools=("npm",),
        ),
    ]


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------


def execute(steps: Sequence[Step], lock: StackLock, *, force: bool) -> BootstrapReport:
    report = BootstrapReport()
    total = len(steps)
    for index, step in enumerate(steps, start=1):
        prefix = f"[{index}/{total}] {step.name}"
        missing = [tool for tool in step.requires_tools if not have(tool)]
        if missing:
            detail = f"missing required tools: {', '.join(missing)}"
            log(f"{prefix}: SKIPPED ({detail})")
            report.add(StepResult(step.name, "skipped", 0.0, detail))
            continue
        if not force and step.check is not None and step.check():
            log(f"{prefix}: already installed")
            report.add(StepResult(step.name, "already", 0.0))
            continue

        log(f"{prefix}: {step.description}")
        started = time.monotonic()
        try:
            step.action(lock)
        except BootstrapError as exc:
            elapsed = time.monotonic() - started
            status = "skipped" if step.optional else "failed"
            log(f"{prefix}: {status.upper()} after {elapsed:.1f}s\n    {exc}")
            if step.notes:
                log(f"    note: {step.notes}")
            report.add(StepResult(step.name, status, elapsed, str(exc)))
            continue
        except Exception as exc:  # noqa: BLE001 - report, never abort the run
            elapsed = time.monotonic() - started
            status = "skipped" if step.optional else "failed"
            log(f"{prefix}: {status.upper()} after {elapsed:.1f}s\n    {exc!r}")
            report.add(StepResult(step.name, status, elapsed, repr(exc)))
            continue
        elapsed = time.monotonic() - started
        log(f"{prefix}: done in {elapsed:.1f}s")
        report.add(StepResult(step.name, "ok", elapsed))
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="*", help="run only these step names")
    parser.add_argument("--skip", nargs="*", default=[], help="skip these step names")
    parser.add_argument("--group", nargs="*", help="run only these groups")
    parser.add_argument(
        "--force", action="store_true", help="re-run steps even when already installed"
    )
    parser.add_argument("--list", action="store_true", help="list steps and exit")
    parser.add_argument(
        "--output",
        default=str(ROOT / ".bactalk" / "bootstrap-report.json"),
        help="where to write the machine-readable report",
    )
    args = parser.parse_args(argv)

    steps = build_steps()
    if args.list:
        for step in steps:
            print(f"{step.group:14s} {step.name:28s} {step.description}")
        return 0

    if args.only:
        known = {step.name for step in steps}
        unknown = set(args.only) - known
        if unknown:
            print(f"unknown step(s): {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2
        steps = [step for step in steps if step.name in set(args.only)]
    if args.group:
        steps = [step for step in steps if step.group in set(args.group)]
    if args.skip:
        steps = [step for step in steps if step.name not in set(args.skip)]

    try:
        lock = StackLock()
    except Exception as exc:  # noqa: BLE001
        print(f"cannot read ops/stack.lock.json: {exc}", file=sys.stderr)
        return 2

    log(f"BACTalk bootstrap: {len(steps)} steps, lock verified {lock.verified_at}")
    report = execute(steps, lock, force=args.force)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report.to_json(lock), indent=2) + "\n")

    ok = sum(1 for item in report.results if item.status in {"ok", "already"})
    skipped = sum(1 for item in report.results if item.status == "skipped")
    log("")
    log(f"bootstrap complete: {ok} ready, {skipped} skipped, {len(report.failed)} failed")
    log(f"report written to {output}")
    if report.failed:
        log("")
        log("failed steps:")
        for item in report.failed:
            log(f"  - {item.name}: {item.detail.splitlines()[0] if item.detail else ''}")
        log("")
        log("Re-run `make bootstrap-full` to retry; completed steps are skipped.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
