from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Every component in ops/stack.lock.json must have an explicit use and proof.
# Adding a pin without adding a binding makes the audit fail closed.
_BINDINGS: dict[str, dict[str, str]] = {
    "aixocat": {
        "mode": "product-api-and-compiler-input",
        "product_path": (
            "GET/POST /api/library/aixocat/patterns; typed Structured Text interface catalog "
            "and reviewed pattern -> typed IR -> Niagara .bog"
        ),
        "proof": "make aixocat-contract",
    },
    "pybog-source": {
        "mode": "runtime-product",
        "product_path": (
            "NiagaraCompiler -> every stock/custom-lowered .bog; template analyzer/comparator; "
            "stateful plant jobs route to the separate ProgramObject source-package target"
        ),
        "proof": "pytest -q tests/test_service.py tests/test_api.py",
    },
    "n4-hvac-optimization-blocks": {
        "mode": "reference-with-product-api",
        "product_path": (
            "GET /api/library/niagara-programs with typed slot interfaces, source/accessor "
            "closure, and external-capability exclusion"
        ),
        "proof": "make n4-hvac-library-contract",
    },
    "boptest": {
        "mode": "isolated-executable-boundary",
        "product_path": "BoptestClient REST adapter; simulator-only override boundary",
        "proof": "make boptest-contract",
    },
    "modelica-buildings": {
        "mode": "product-api-and-build-input",
        "product_path": (
            "GET/POST /api/library/g36/controllers and /api/library/plant-controls/controllers; "
            "allowlisted G36 and plant-control source -> modelica-json CXF -> OCE -> typed IR; "
            "configured plant controllers also enter the contractor job/test/approval/export lane"
        ),
        "proof": (
            "make cdl-oce-contract && make plant-controls-contract && make plant-job-contract"
        ),
    },
    "modelica-json": {
        "mode": "isolated-build-tool",
        "product_path": (
            "G36Library/PlantControlsLibrary -> bounded CdlTranslator subprocess boundary for "
            "CDL, plant controls, and reviewed annotated Modelica-container extraction"
        ),
        "proof": "make cdl-oce-contract && make plant-controls-contract",
    },
    "ctrl-flow": {
        "mode": "product-api-and-upstream-interpreter",
        "product_path": (
            "GET /api/library/ctrl-flow/templates plus schema/configure endpoints; pinned "
            "Linkage Schema -> upstream conditional-option interpreter -> configuration digest "
            "-> exact controller, point, scenario, capability, and release-gate programming "
            "brief -> fail-closed contractor point reconciliation -> source-hashed sequence "
            "facet coverage with excerpt evidence -> unapproved temporal/math/action candidates "
            "with ambiguity retention and mandatory engineer review"
        ),
        "proof": "make ctrl-flow-contract",
    },
    "modelica-standard-library": {
        "mode": "isolated-build-input",
        "product_path": "Rumoca G36 flattening source root",
        "proof": "make rumoca-contract",
    },
    "rumoca": {
        "mode": "product-api-and-isolated-build-tool",
        "product_path": (
            "POST /api/library/g36/controllers/{id}/flatten; allowlisted Modelica source -> "
            "resolved and flattened JSON IR"
        ),
        "proof": "make rumoca-contract",
    },
    "open-control-engine": {
        "mode": "isolated-executable-boundary",
        "product_path": (
            "POST /api/execute/cxf plus G36/plant translation validation and trajectory oracle"
        ),
        "proof": "make oce-contract && make cdl-oce-contract && make plant-controls-contract",
    },
    "open-control-library": {
        "mode": "product-api-and-compiler-input",
        "product_path": "GET/POST /api/library/open-control/faults; CXF -> typed IR -> .bog",
        "proof": "make open-control-library-contract",
    },
    "constrain": {
        "mode": "product-api",
        "product_path": "POST /api/verify/constrain",
        "proof": "make constrain-contract",
    },
    "buildingmotif": {
        "mode": "product-api",
        "product_path": "GET/POST /api/semantics/buildingmotif/*",
        "proof": "make buildingmotif-contract",
    },
    "alfalfa": {
        "mode": "isolated-executable-boundary",
        "product_path": "Alfalfa service/client virtual-building contract",
        "proof": "make alfalfa-contract",
    },
    "alfalfa-client": {
        "mode": "isolated-executable-boundary",
        "product_path": "Pinned AlfalfaClient API boundary",
        "proof": "make alfalfa-contract",
    },
    "dflexlibs": {
        "mode": "executable-reference",
        "product_path": "Demand-flex feasibility oracle; excluded from automatic Niagara lowering",
        "proof": "make dflexlibs-contract",
    },
    "volttron": {
        "mode": "runtime-product",
        "product_path": "Signed read-only Platform Driver artifacts on every scanned run",
        "proof": "make volttron-contract",
    },
    "volttron-core": {
        "mode": "runtime-product",
        "product_path": "Isolated VOLTTRON message-bus/runtime contract",
        "proof": "make volttron-contract",
    },
    "volttron-platform-driver": {
        "mode": "runtime-product",
        "product_path": "Generated device and registry configuration",
        "proof": "make volttron-contract",
    },
    "volttron-bacnet-driver": {
        "mode": "runtime-product",
        "product_path": "Generated BACnet driver configuration, forced read-only",
        "proof": "make volttron-contract",
    },
    "volttron-fake-driver": {
        "mode": "isolated-test-runtime",
        "product_path": "VOLTTRON contract fixture for simulated points",
        "proof": "make volttron-contract",
    },
    "bacpypes3": {
        "mode": "runtime-product",
        "product_path": "Generated loopback BACnet device lab and UDP protocol runtime",
        "proof": "make bacnet-lab-contract",
    },
    "bac0": {
        "mode": "independent-lab-client",
        "product_path": "Generated BAC0 probe reads every mapped virtual point",
        "proof": "make bacnet-lab-contract",
    },
    "bacnet-simulator": {
        "mode": "independent-lab-runtime",
        "product_path": (
            "Every BACnet lab export includes independent simulator device/settings files and "
            "a loopback launcher"
        ),
        "proof": "make independent-bacnet-simulator-contract",
    },
    "openpyxl": {
        "mode": "runtime-product",
        "product_path": "Contractor XLSX point-list ingestion",
        "proof": "pytest -q tests/test_intake.py tests/test_api.py -k xlsx",
    },
    "pypdf": {
        "mode": "runtime-product",
        "product_path": "Bounded contractor PDF sequence extraction",
        "proof": "pytest -q tests/test_intake.py",
    },
    "python-docx": {
        "mode": "runtime-product",
        "product_path": "Contractor DOCX sequence text/table extraction",
        "proof": "pytest -q tests/test_intake.py",
    },
    "tzdata": {
        "mode": "runtime-product",
        "product_path": "IANA schedule timezone validation and portable schedule lowering",
        "proof": "pytest -q tests/test_niagara_schedules.py",
    },
    "nhaystack": {
        "mode": "runtime-product-artifact",
        "product_path": "Signed read-only Zinc/readback/install package on every run",
        "proof": "make nhaystack-contract",
    },
    "am8x-control": {
        "mode": "source-pattern-to-product-artifact",
        "product_path": "Generic Niagara alarm plan, generated Java, and readback contract",
        "proof": "make niagara-alarm-contract",
    },
}


class IntegrationUseAudit:
    def __init__(self, root: Path = Path(".")):
        self.root = root.resolve()

    def report(self) -> dict[str, Any]:
        lock_path = self.root / "ops/stack.lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        components = lock.get("components", {})
        pinned = set(components)
        bound = set(_BINDINGS)
        missing = sorted(pinned - bound)
        stale = sorted(bound - pinned)
        rows = []
        for component_id in sorted(pinned):
            binding = _BINDINGS.get(component_id)
            source = components[component_id]
            rows.append(
                {
                    "id": component_id,
                    "license": source.get("license"),
                    "revision_or_package": source.get("revision")
                    or source.get("release")
                    or source.get("package"),
                    "bound": binding is not None,
                    **(binding or {}),
                }
            )
        passed = not missing and not stale and all(
            row.get("product_path") and row.get("proof") for row in rows
        )
        return {
            "schema": "bactalk.integration-use-audit/v1",
            "passed": passed,
            "policy": (
                "A pinned component must name its exact product/build/test boundary and an "
                "executable proof command. Presence in .vendor or a package environment is not use."
            ),
            "pinned_component_count": len(pinned),
            "bound_component_count": sum(row["bound"] for row in rows),
            "missing_bindings": missing,
            "stale_bindings": stale,
            "components": rows,
        }

    def assert_complete(self) -> dict[str, Any]:
        report = self.report()
        if not report["passed"]:
            raise RuntimeError(
                "integration use audit failed: "
                f"missing={report['missing_bindings']}, stale={report['stale_bindings']}"
            )
        return report
