"""The bootstrap and diagnosis machinery must itself be trustworthy.

These tests exercise the parts of ``scripts/bootstrap.py`` and
``scripts/doctor.py`` that decide whether a checkout is verified: the step
registry, revision verification, license-digest checking, idempotent patch
application, and the doctor's report shape. They never touch the network, so
they run on a base install.
"""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.minimal

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    """Import a script from scripts/ as a module."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bootstrap = _load("bootstrap")
doctor = _load("doctor")


# --------------------------------------------------------------------------
# step registry
# --------------------------------------------------------------------------


def test_every_step_has_a_unique_name_and_description() -> None:
    steps = bootstrap.build_steps()
    names = [step.name for step in steps]
    assert len(names) == len(set(names)), "step names must be unique"
    for step in steps:
        assert step.description, f"{step.name} has no description"
        assert step.group, f"{step.name} has no group"


def test_every_locked_repository_component_has_a_bootstrap_step() -> None:
    """A pinned component nobody installs cannot be reconstructed.

    This is the guard against adding a component to the lock and forgetting
    the installer, which would leave a "pinned" dependency that a clean clone
    can never produce.
    """
    from bactalk.stack_lock import StackLock

    # Components installed as ordinary Python packages need no clone step.
    package_only = {
        component.name
        for component in StackLock().components()
        if not component.repository or (component.package and not component.revision)
    }
    # These are pinned for provenance and consumed through another component's
    # step rather than a checkout of their own.
    consumed_by_other_steps = {
        "alfalfa-client",  # installed by the python-suite extra
        "volttron-core",  # installed from ops/volttron/requirements.txt
        "volttron-platform-driver",
        "volttron-bacnet-driver",
        "volttron-fake-driver",
        "rust-toolchain",  # installed by the rust-toolchain step, not cloned
    }

    step_names = {step.name for step in bootstrap.build_steps()}
    # Map lock component names onto the step that installs them.
    aliases = {
        "pybog-source": "pybog-source",
        "n4-hvac-optimization-blocks": "n4-hvac-library",
        "boptest": "boptest-source",
        "alfalfa": "alfalfa-source",
        "modelica-standard-library": "modelica-standard-library",
    }

    missing = []
    for component in StackLock().components():
        name = component.name
        if name in package_only or name in consumed_by_other_steps:
            continue
        if aliases.get(name, name) not in step_names:
            missing.append(name)
    assert missing == [], (
        f"pinned components with no bootstrap step: {missing}. "
        "A component that cannot be installed is not reproducible."
    )


def test_unknown_step_is_rejected() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "bootstrap.py"), "--only", "nope"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 2
    assert "unknown step" in result.stderr


def test_listing_steps_does_not_touch_the_network() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "bootstrap.py"), "--list"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0
    assert "modelica-buildings" in result.stdout
    assert "frontend" in result.stdout


# --------------------------------------------------------------------------
# verification primitives
# --------------------------------------------------------------------------


def test_license_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    """An upstream license whose text changed must stop the install."""
    license_file = tmp_path / "LICENSE"
    license_file.write_text("original license text\n")
    correct = hashlib.sha256(license_file.read_bytes()).hexdigest()

    bootstrap.verify_license(license_file, correct, "probe")  # does not raise

    license_file.write_text("the upstream changed this license\n")
    with pytest.raises(bootstrap.BootstrapError) as excinfo:
        bootstrap.verify_license(license_file, correct, "probe")
    assert "license digest mismatch" in str(excinfo.value)


def test_missing_license_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(bootstrap.BootstrapError) as excinfo:
        bootstrap.verify_license(tmp_path / "absent", "0" * 64, "probe")
    assert "license file is missing" in str(excinfo.value)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        timeout=120,
    )


def test_patch_application_is_idempotent(tmp_path: Path) -> None:
    """Applying a tracked patch twice is a no-op, not a failure.

    Bootstrap reruns must be safe, and a patched checkout is the normal state
    on the second run.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    target = repo / "value.txt"
    target.write_text("original\n")
    _git(repo, "add", "value.txt")
    _git(repo, "commit", "--quiet", "-m", "initial")

    target.write_text("patched\n")
    diff = subprocess.run(
        ["git", "-C", str(repo), "diff"], capture_output=True, text=True, timeout=120
    )
    patch = tmp_path / "change.patch"
    patch.write_text(diff.stdout)
    _git(repo, "checkout", "--", "value.txt")

    bootstrap.apply_patch(repo, patch, "probe")
    assert target.read_text() == "patched\n"

    # Second application must detect the patch is already present.
    bootstrap.apply_patch(repo, patch, "probe")
    assert target.read_text() == "patched\n"


def test_patch_that_does_not_apply_fails_closed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    (repo / "other.txt").write_text("unrelated\n")
    _git(repo, "add", "other.txt")
    _git(repo, "commit", "--quiet", "-m", "initial")

    patch = tmp_path / "bad.patch"
    patch.write_text(
        "diff --git a/missing.txt b/missing.txt\n"
        "--- a/missing.txt\n+++ b/missing.txt\n"
        "@@ -1 +1 @@\n-nothing\n+something\n"
    )
    with pytest.raises(bootstrap.BootstrapError) as excinfo:
        bootstrap.apply_patch(repo, patch, "probe")
    assert "does not apply cleanly" in str(excinfo.value)


def test_missing_patch_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(bootstrap.BootstrapError) as excinfo:
        bootstrap.apply_patch(tmp_path, tmp_path / "absent.patch", "probe")
    assert "tracked patch missing" in str(excinfo.value)


def test_report_marks_failures(tmp_path: Path) -> None:
    """A failing step is recorded, and the run keeps going."""
    from bactalk.stack_lock import StackLock

    def explode(_lock):
        raise bootstrap.BootstrapError("synthetic failure")

    steps = [
        bootstrap.Step("good", "succeeds", lambda _lock: None, group="test"),
        bootstrap.Step("bad", "fails", explode, group="test"),
        bootstrap.Step("opt", "optional failure", explode, group="test", optional=True),
    ]
    report = bootstrap.execute(steps, StackLock(), force=True)
    statuses = {item.name: item.status for item in report.results}
    assert statuses == {"good": "ok", "bad": "failed", "opt": "skipped"}
    assert [item.name for item in report.failed] == ["bad"]
    payload = report.to_json(StackLock())
    assert payload["ok"] is False
    assert len(payload["steps"]) == 3


def test_completed_steps_are_skipped_on_rerun() -> None:
    """Idempotency: a step whose check passes is not run again."""
    from bactalk.stack_lock import StackLock

    calls: list[str] = []
    steps = [
        bootstrap.Step(
            "already-done",
            "no-op",
            lambda _lock: calls.append("ran"),
            group="test",
            check=lambda: True,
        )
    ]
    report = bootstrap.execute(steps, StackLock(), force=False)
    assert calls == []
    assert report.results[0].status == "already"

    # --force overrides the check.
    report = bootstrap.execute(steps, StackLock(), force=True)
    assert calls == ["ran"]
    assert report.results[0].status == "ok"


# --------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------


def test_doctor_reports_json_with_every_section() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "doctor.py"), "--json"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stderr
    import json

    payload = json.loads(result.stdout)
    assert payload["schema"] == "bactalk.doctor-report/v1"
    sections = {finding["section"] for finding in payload["findings"]}
    for expected in ("interpreters", "pinned sources", "python packages", "environment"):
        assert expected in sections, f"doctor omits the {expected} section"
    for finding in payload["findings"]:
        assert finding["status"] in {"ready", "degraded", "missing", "blocked"}
        if finding["status"] == "missing":
            assert finding["remediation"], f"{finding['name']} is missing with no fix"


def test_doctor_never_prints_secret_values() -> None:
    """Environment findings report presence only, never the value."""
    report = doctor.Report()
    doctor.check_environment_variables(report)
    for finding in report.findings:
        assert finding.detail.startswith(("set ", "unset "))


def test_blocked_findings_do_not_fail_the_report() -> None:
    """A blocked external constraint is not a missing capability."""
    report = doctor.Report()
    report.add(doctor.Finding("licensed runtimes", "probe", doctor.BLOCKED, "external"))
    assert report.ok is True
    report.add(doctor.Finding("python packages", "probe", doctor.MISSING, "absent"))
    assert report.ok is False


# --------------------------------------------------------------------------
# test tiering
# --------------------------------------------------------------------------


def test_every_declared_requirement_kind_is_understood() -> None:
    """conftest must not carry a requirement it cannot evaluate."""
    conftest = _load_conftest()
    for module, requirements in conftest.MODULE_REQUIREMENTS.items():
        for requirement in requirements:
            kind = requirement.split(":", 1)[0]
            assert kind in {"vendor", "venv", "node", "file", "tool", "module"}, (
                f"{module} declares an unknown requirement kind: {requirement}"
            )
            # Must evaluate without raising, whatever this machine has.
            conftest._missing(requirement)


def test_requirements_reference_real_test_modules() -> None:
    """A requirement for a module that no longer exists is dead configuration."""
    conftest = _load_conftest()
    present = {path.stem for path in (ROOT / "tests").glob("test_*.py")}
    unknown = set(conftest.MODULE_REQUIREMENTS) - present
    assert unknown == set(), f"requirements declared for missing test modules: {unknown}"
    unknown_minimal = conftest.MINIMAL_MODULES - present
    assert unknown_minimal == set()


def test_strict_mode_is_off_by_default() -> None:
    """A partially bootstrapped machine skips; only strict mode fails."""
    conftest = _load_conftest()
    import os

    previous = os.environ.pop("BACTALK_REQUIRE_FULL_STACK", None)
    try:
        assert conftest._require_full_stack() is False
        for value in ("1", "true", "YES"):
            os.environ["BACTALK_REQUIRE_FULL_STACK"] = value
            assert conftest._require_full_stack() is True
        os.environ["BACTALK_REQUIRE_FULL_STACK"] = "0"
        assert conftest._require_full_stack() is False
    finally:
        os.environ.pop("BACTALK_REQUIRE_FULL_STACK", None)
        if previous is not None:
            os.environ["BACTALK_REQUIRE_FULL_STACK"] = previous


def _load_conftest():
    spec = importlib.util.spec_from_file_location(
        "bactalk_tests_conftest", ROOT / "tests" / "conftest.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
