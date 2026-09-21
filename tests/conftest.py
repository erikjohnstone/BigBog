"""Test tiering: what each test needs, and what happens when it is absent.

BACTalk supports two legitimate install states, and the suite has to behave
correctly in both:

* **Minimal** (``make install``) -- base dependencies only, no vendored
  upstream sources. Tests that need an upstream checkout or an optional extra
  are skipped with a message naming the exact remediation. The suite must not
  error, and it must not silently pass either.
* **Full** (``make bootstrap-full``) -- every pinned source and extra present.
  Here the same tests **must execute**. A skip in this state would hide a real
  regression behind a missing dependency, so the suite refuses to skip: set
  ``BACTALK_REQUIRE_FULL_STACK=1`` (what ``make test-integration`` does after a
  bootstrap) and an absent requirement becomes a failure instead.

Requirements are declared per test module below. A module with no entry runs
everywhere, which is the right default for the pure IR, compiler, intake, and
domain tests.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / ".vendor"


def _vendor(name: str) -> Path:
    return VENDOR / name


# Test module -> the resources it needs before it can run.
#
# "vendor:<dir>"  a pinned upstream checkout under .vendor/
# "venv:<dir>"    an isolated Python environment at the repository root
# "node:<path>"   an installed node toolchain
# "tool:<name>"   an executable on PATH
# "file:<path>"   a built artifact
MODULE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "test_g36_library": (
        "vendor:modelica-buildings",
        "file:ops/open-control-engine-runner/target/release/bactalk-oce-runner",
    ),
    "test_g36_audit": ("vendor:modelica-buildings",),
    "test_plant_controls_library": ("vendor:modelica-buildings",),
    "test_cxf_importer": ("vendor:open-control-library",),
    "test_cxf_connections": ("vendor:open-control-library",),
    "test_oce_execution_api": ("vendor:open-control-engine",),
    "test_reference_stack": ("vendor:open-control-engine",),
    "test_cdl": ("vendor:modelica-json",),
    "test_rumoca": ("file:.vendor/bin/rumoca",),
    "test_ctrl_flow": ("vendor:ctrl-flow-dev",),
    "test_ctrl_flow_sequence": ("vendor:ctrl-flow-dev",),
    "test_ctrl_flow_reconciliation": ("vendor:ctrl-flow-dev",),
    "test_ctrl_flow_point_repository": ("vendor:ctrl-flow-dev",),
    "test_sequence_oracles": ("vendor:ctrl-flow-dev",),
    "test_sequence_requirement_review": ("vendor:ctrl-flow-dev",),
    "test_sequence_candidate": ("vendor:ctrl-flow-dev", "vendor:modelica-buildings"),
    "test_aixocat_library": ("vendor:aixocat",),
    "test_buildingmotif": ("venv:.buildingmotif-venv",),
    "test_external_verifiers": ("node:ops/haxall/node_modules",),
    "test_semantics": (),
    "test_niagara_program_codegen": ("tool:javac",),
    "test_api": ("module:bacpypes3", "module:BAC0"),
    "test_bacnet_lab": ("module:bacpypes3", "module:BAC0"),
    "test_bacnet_scale": ("module:bacpypes3",),
    "test_bacnet_libraries": ("module:bacpypes3", "module:BAC0"),
    "test_virtual_actuator": ("module:bacpypes3",),
    "test_alfalfa_qualification": ("module:bacpypes3",),
    "test_alfalfa_graph": (),
    "test_funnel": ("module:pyfunnel",),
    "test_boptest_qualification": ("module:pyfunnel",),
    "test_boptest": ("module:pyfunnel",),
    "test_boptest_scale": ("module:pyfunnel",),
    "test_alfalfa_runtime": ("module:pyfunnel",),
    "test_volttron": (),
}

# Individual tests that need an upstream while the rest of their module does
# not. Keyed by "<module>::<test name>" so a mostly-pure module is not pushed
# wholesale into the integration tier.
TEST_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "test_service::test_plant_library_job_runs_tests_and_exports_signed_program_source_package": (
        "vendor:modelica-buildings",
    ),
    "test_service::test_g36_library_controller_enters_the_same_human_gated_job_lane": (
        "vendor:modelica-buildings",
    ),
    "test_ai_chat::test_library_chat_changes_parameters_then_rebuilds_and_retests": (
        "vendor:modelica-buildings",
    ),
}

# Modules that exercise only the base install and must run everywhere.
MINIMAL_MODULES = {
    "test_minimal_install",
    "test_stack_lock",
    "test_bootstrap",
    "test_approval_digest_binding",
}


def _module_available(module: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _missing(requirement: str) -> str | None:
    """Return a human-readable reason when a requirement is not satisfied."""
    kind, _, value = requirement.partition(":")
    if kind == "vendor":
        path = _vendor(value)
        if not (path / ".git").exists():
            return (
                f"pinned upstream '{value}' is not checked out at .vendor/{value} "
                f"(run: make bootstrap-full)"
            )
        return None
    if kind == "venv":
        if not (ROOT / value / "bin" / "python").exists():
            return f"isolated environment {value} is absent (run: make bootstrap-full)"
        return None
    if kind == "node":
        if not (ROOT / value).is_dir():
            return f"node toolchain {value} is not installed (run: make bootstrap-full)"
        return None
    if kind == "file":
        if not (ROOT / value).exists():
            return f"built artifact {value} is absent (run: make bootstrap-full)"
        return None
    if kind == "tool":
        if shutil.which(value) is None:
            return f"required tool '{value}' is not on PATH"
        return None
    if kind == "module":
        if not _module_available(value):
            return (
                f"optional package '{value}' is not installed "
                f"(run: pip install -e '.[suite]' or make bootstrap-full)"
            )
        return None
    raise ValueError(f"unknown requirement kind in {requirement!r}")


def _require_full_stack() -> bool:
    return os.getenv("BACTALK_REQUIRE_FULL_STACK", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    """Mark each test with its tier and resolve unmet requirements."""
    strict = _require_full_stack()

    for item in items:
        module_name = Path(str(item.fspath)).stem

        # A per-test requirement wins over the module default, so one
        # upstream-dependent case does not drag its whole module out of the
        # minimal tier.
        # originalname is the un-parametrized name on a Function item; fall
        # back to name for item types that do not carry it.
        base_name = getattr(item, "originalname", None) or item.name
        test_key = f"{module_name}::{base_name}"
        requirements = TEST_REQUIREMENTS.get(test_key)

        if requirements is None:
            if module_name in MINIMAL_MODULES:
                item.add_marker(pytest.mark.minimal)
                continue
            requirements = MODULE_REQUIREMENTS.get(module_name)

        if not requirements:
            # No declared external requirement: runs on a base install.
            item.add_marker(pytest.mark.minimal)
            continue

        item.add_marker(pytest.mark.integration)
        reasons = [reason for req in requirements if (reason := _missing(req))]
        if not reasons:
            continue

        detail = "; ".join(reasons)
        if strict:
            # After a full bootstrap a skip would hide a regression, so record
            # the gap and let pytest_runtest_setup turn it into a failure.
            item.user_properties.append(("unmet_requirement", detail))
        else:
            item.add_marker(pytest.mark.skip(reason=detail))


def pytest_runtest_setup(item):
    """Fail, rather than skip, an unmet requirement under a full-stack run."""
    if not _require_full_stack():
        return
    unmet = [value for key, value in item.user_properties if key == "unmet_requirement"]
    if unmet:
        pytest.fail(
            "BACTALK_REQUIRE_FULL_STACK is set, so this test must execute rather "
            f"than skip, but {unmet[0]}",
            pytrace=False,
        )


def pytest_report_header(config):  # noqa: ARG001
    """State which install tier the suite is running against."""
    installed = sum(
        1
        for name in ("modelica-buildings", "open-control-engine", "ctrl-flow-dev")
        if (_vendor(name) / ".git").exists()
    )
    tier = "full (bootstrapped)" if installed == 3 else "minimal or partial"
    strict = " [strict: unmet requirements fail]" if _require_full_stack() else ""
    return f"bactalk install tier: {tier}{strict}"
