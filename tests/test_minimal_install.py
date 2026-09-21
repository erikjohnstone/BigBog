"""A base install must boot the API and degrade optional capabilities cleanly.

``make install`` deliberately installs only the base dependency set. These
tests pin the contract that no optional extra is required to import the
package, create the app, or run the core contractor workflow, and that a
capability whose extra is missing answers with an explicit remediation rather
than crashing the application.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from bactalk.api import create_app
from bactalk.optional_dependencies import (
    ALFALFA_CLIENT,
    BACPYPES3,
    OPTIONAL_DEPENDENCIES,
    OptionalDependency,
    OptionalDependencyError,
    optional_dependency_status,
)

pytestmark = pytest.mark.minimal


BASE_MODULES = [
    "bactalk.agent",
    "bactalk.ai",
    "bactalk.api",
    "bactalk.capabilities",
    "bactalk.cli",
    "bactalk.compiler",
    "bactalk.demo",
    "bactalk.domain",
    "bactalk.intake",
    "bactalk.projects",
    "bactalk.qualification_jobs",
    "bactalk.service",
    "bactalk.simulator",
]


@pytest.mark.parametrize("module_name", BASE_MODULES)
def test_core_modules_import_without_optional_extras(module_name: str) -> None:
    """Every core module imports with only the base dependency set installed."""
    assert importlib.import_module(module_name) is not None


def test_optional_dependencies_never_imported_at_module_scope() -> None:
    """No core module may import an optional distribution at module scope.

    A top-level import of an optional package is what previously made one
    missing extra break the whole API, so this asserts the lazy contract
    directly against the source text.
    """
    import pathlib

    package_root = pathlib.Path(importlib.import_module("bactalk").__file__).parent
    optional_modules = {dependency.module.split(".")[0] for dependency in OPTIONAL_DEPENDENCIES}
    # bactalk.optional_dependencies names them in data, never imports them.
    offenders: list[str] = []
    for source in package_root.rglob("*.py"):
        if source.name == "optional_dependencies.py":
            continue
        for lineno, line in enumerate(source.read_text().splitlines(), start=1):
            stripped = line.strip()
            if not (stripped.startswith("import ") or stripped.startswith("from ")):
                continue
            if line.startswith((" ", "\t")):
                continue  # function-scope import: that is the lazy pattern
            for module in optional_modules:
                if stripped.startswith(f"import {module}") or stripped.startswith(
                    f"from {module}"
                ):
                    offenders.append(f"{source.name}:{lineno}: {stripped}")
    assert offenders == [], f"optional packages imported at module scope: {offenders}"


def test_app_boots_and_serves_core_endpoints(tmp_path) -> None:
    """The base install serves health, readiness, and the demo build."""
    client = TestClient(create_app(tmp_path / "runs"))
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/system/readiness").status_code == 200
    assert client.get("/api/capability-packs").status_code == 200
    assert client.post("/api/runs/demo").status_code == 201


def test_optional_capabilities_endpoint_reports_every_extra(tmp_path) -> None:
    """The UI can read which extras are installed and how to add the rest."""
    client = TestClient(create_app(tmp_path / "runs"))
    body = client.get("/api/system/optional-capabilities").json()
    assert body["schema"] == "bactalk.optional-capabilities/v1"
    assert body["bootstrap_command"] == "make bootstrap-full"
    reported = {item["distribution"] for item in body["dependencies"]}
    assert reported == {dependency.distribution for dependency in OPTIONAL_DEPENDENCIES}
    for item in body["dependencies"]:
        # An uninstalled extra must always carry its own remediation.
        assert item["installed"] or item["remediation"]


def test_missing_optional_dependency_raises_with_remediation() -> None:
    """A capability with no package names the exact install command."""
    absent = OptionalDependency(
        distribution="bactalk-not-a-real-package",
        module="bactalk_not_a_real_module",
        extra="suite",
        capability="Synthetic capability",
    )
    assert absent.available() is False
    assert absent.version() is None
    with pytest.raises(OptionalDependencyError) as excinfo:
        absent.load()
    assert "Synthetic capability" in str(excinfo.value)
    assert "pip install -e '.[suite]'" in excinfo.value.remediation


def test_alfalfa_capability_is_declared_not_imported() -> None:
    """Alfalfa is described as an optional capability with a real extra."""
    assert ALFALFA_CLIENT.extra == "alfalfa"
    assert ALFALFA_CLIENT.module == "alfalfa_client"
    status = {item["distribution"]: item for item in optional_dependency_status()}
    assert "alfalfa-client" in status


def test_capability_without_its_extra_answers_503_with_remediation(tmp_path) -> None:
    """A capability whose package is absent reports how to install it.

    The BACnet loopback probe needs the bacnet-lab extra. On a base install it
    must answer 503 naming the capability, the distribution, and the exact pip
    command, rather than a 500 that reads like a product defect or a 409 that
    reads like bad input.
    """
    if BACPYPES3.available():
        pytest.skip("bacpypes3 is installed; this asserts the absent-extra path")

    client = TestClient(create_app(tmp_path / "runs"))
    run = client.post("/api/runs/demo").json()
    response = client.post(f"/api/runs/{run['id']}/bacnet-lab/probe")
    assert response.status_code == 503
    body = response.json()
    assert body["distribution"] == "bacpypes3"
    assert body["extra"] == "bacnet-lab"
    assert "pip install" in body["remediation"]
    assert body["capability"]
