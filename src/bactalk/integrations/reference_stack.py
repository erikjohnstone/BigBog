from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any


def _revision(lock: dict[str, Any], component: str) -> str | None:
    value = lock.get("components", {}).get(component, {})
    return value.get("revision") if isinstance(value, dict) else None


def _equipment_group(name: str) -> str:
    lowered = name.lower()
    if any(word in lowered for word in ("chilled", "chiller", "hotwater", "hot_water")):
        return "Central plants"
    if any(word in lowered for word in ("terminal", "vav", "zone")):
        return "Zones and terminals"
    if any(word in lowered for word in ("light", "guestroom", "guest_room")):
        return "Lighting and rooms"
    if any(word in lowered for word in ("heat rejection", "heatrejection", "wlhp")):
        return "Heat rejection"
    if any(word in lowered for word in ("air", "fan", "economizer", "freeze")):
        return "Air handlers and ventilation"
    return "Generic controls"


class ReferenceStackCatalog:
    """Read-only inventory of pinned control sources and independent oracles."""

    def __init__(
        self,
        *,
        lock_path: Path = Path("ops/stack.lock.json"),
        modelica_root: Path | None = None,
        oce_root: Path | None = None,
        constrain_root: Path | None = None,
        pybog_root: Path | None = None,
        dflexlibs_root: Path | None = None,
        open_control_library_root: Path | None = None,
        niagara_program_library_root: Path | None = None,
        cxf_manifest_path: Path | None = None,
    ):
        self.lock_path = lock_path
        self.modelica_root = modelica_root or Path(
            os.getenv("BACTALK_MODELICA_BUILDINGS", ".vendor/modelica-buildings")
        )
        self.oce_root = oce_root or Path(
            os.getenv("BACTALK_OPEN_CONTROL_ENGINE", ".vendor/open-control-engine")
        )
        self.constrain_root = constrain_root or Path(
            os.getenv("BACTALK_CONSTRAIN", ".vendor/constrain")
        )
        self.pybog_root = pybog_root or Path(os.getenv("BACTALK_PYBOG", ".vendor/pybog"))
        self.dflexlibs_root = dflexlibs_root or Path(
            os.getenv("BACTALK_DFLEXLIBS", ".vendor/dflexlibs")
        )
        self.open_control_library_root = open_control_library_root or Path(
            os.getenv("BACTALK_OPEN_CONTROL_LIBRARY", ".vendor/open-control-library")
        )
        self.niagara_program_library_root = niagara_program_library_root or Path(
            os.getenv(
                "BACTALK_NIAGARA_PROGRAM_LIBRARY",
                ".vendor/n4-hvac-optimization-blocks",
            )
        )
        self.cxf_manifest_path = cxf_manifest_path or Path(
            os.getenv("BACTALK_CXF_MANIFEST", "ops/cxf-lowering-v1.json")
        )

    def inventory(self) -> dict[str, Any]:
        lock = (
            json.loads(self.lock_path.read_text(encoding="utf-8"))
            if self.lock_path.is_file()
            else {}
        )
        modelica = self._modelica_inventory(lock)
        engine = self._oce_inventory(lock)
        verification = self._constrain_inventory(lock)
        pybog_examples = self._pybog_inventory(lock)
        demand_flex = self._dflexlibs_inventory(lock)
        fault_library = self._open_control_library_inventory(lock)
        program_library = self._niagara_program_library_inventory(lock)
        return {
            "policy": (
                "Catalog presence is not deployment support. Only artifacts explicitly marked "
                "active are on the Niagara generation path."
            ),
            "components": [
                modelica,
                engine,
                verification,
                pybog_examples,
                demand_flex,
                fault_library,
                program_library,
            ],
            "summary": {
                "modelica_control_files": modelica["artifact_count"],
                "modelica_plant_control_files": modelica["plant_control_file_count"],
                "executable_cdl_blocks": engine["block_count"],
                "g36_cxf_fixtures": engine["artifact_count"],
                "independent_verification_rules": verification["artifact_count"],
                "niagara_reference_examples": pybog_examples["artifact_count"],
                "demand_flex_control_functions": demand_flex["artifact_count"],
                "executable_fault_rules": fault_library["artifact_count"],
                "ir_vector_verified_fault_rules": fault_library["ir_verified_translation_count"],
                "niagara_vector_verified_fault_rules": fault_library[
                    "niagara_verified_translation_count"
                ],
                "niagara_program_templates": program_library["artifact_count"],
                "niagara_program_objects": program_library["program_object_count"],
            },
        }

    def _modelica_inventory(self, lock: dict[str, Any]) -> dict[str, Any]:
        root = self.modelica_root / "Buildings" / "Controls" / "OBC"
        files = sorted(root.rglob("*.mo")) if root.is_dir() else []
        groups = Counter(path.relative_to(root).parts[0] for path in files)
        plant_root = self.modelica_root / "Buildings" / "Templates" / "Plants" / "Controls"
        plant_files = sorted(plant_root.rglob("*.mo")) if plant_root.is_dir() else []
        plant_groups = Counter(path.relative_to(plant_root).parts[0] for path in plant_files)
        return {
            "id": "modelica-buildings",
            "name": "LBNL Modelica Buildings / OBC",
            "installed": bool(files),
            "integration_status": "reference-source",
            "role": "Versioned CDL and Guideline 36 source logic",
            "license": "Revised BSD-3-Clause with notices",
            "revision": _revision(lock, "modelica-buildings"),
            "artifact_count": len(files),
            "groups": dict(sorted(groups.items())),
            "plant_control_file_count": len(plant_files),
            "plant_control_groups": dict(sorted(plant_groups.items())),
            "limitations": (
                "Modelica sources must be flattened and translated before Niagara generation."
            ),
            "verified_handoff": {
                "target": "Open Control Engine",
                "source": (
                    "Buildings.Controls.OBC.ASHRAE.G36.AHUs.MultiZone.VAV.SetPoints.SupplySignals"
                ),
                "contract": "make cdl-oce-contract && make plant-controls-contract",
            },
        }

    def _oce_inventory(self, lock: dict[str, Any]) -> dict[str, Any]:
        fixture_root = self.oce_root / "crates" / "oce-cxf" / "tests" / "fixtures" / "g36"
        fixtures = (
            sorted(path.stem for path in fixture_root.glob("*.jsonld"))
            if fixture_root.is_dir()
            else []
        )
        catalog_path = self.oce_root / "crates" / "oce-api" / "contracts" / "catalog.json"
        entries: list[dict[str, Any]] = []
        if catalog_path.is_file():
            entries = json.loads(catalog_path.read_text(encoding="utf-8")).get("entries", [])
        public_entries = [entry for entry in entries if not entry.get("reserved", False)]
        stateful = sum(bool(entry.get("stateful")) for entry in public_entries)
        return {
            "id": "open-control-engine",
            "name": "Open Control Engine",
            "installed": self.oce_root.is_dir(),
            "integration_status": "validated-external-runtime",
            "role": "Deterministic CXF execution and temporal-block oracle",
            "license": "MIT OR Apache-2.0",
            "revision": _revision(lock, "open-control-engine"),
            "artifact_count": len(fixtures),
            "block_count": len(public_entries),
            "stateful_block_count": stateful,
            "artifacts": fixtures,
            "limitations": (
                "Pre-1.0; executes selected pre-flattened CXF and does not flatten arbitrary "
                "Modelica or prove universal G36 support."
            ),
        }

    def _constrain_inventory(self, lock: dict[str, Any]) -> dict[str, Any]:
        library_path = self.constrain_root / "constrain" / "schema" / "library.json"
        rules: dict[str, dict[str, Any]] = {}
        if library_path.is_file():
            rules = json.loads(library_path.read_text(encoding="utf-8"))
        rendered = [
            {
                "id": name,
                "name": item.get("description_brief", name),
                "group": _equipment_group(name + " " + item.get("description_brief", "")),
            }
            for name, item in rules.items()
        ]
        groups = Counter(item["group"] for item in rendered)
        return {
            "id": "constrain",
            "name": "PNNL ConStrain",
            "installed": bool(rules),
            "integration_status": "verification-catalog",
            "role": "Independent ASHRAE 90.1 and G36 control-performance checks",
            "license": "BSD-2-Clause",
            "revision": _revision(lock, "constrain"),
            "artifact_count": len(rendered),
            "groups": dict(sorted(groups.items())),
            "artifacts": rendered,
            "limitations": (
                "Verification rules are test oracles, not deployable controller programs."
            ),
        }

    def _pybog_inventory(self, lock: dict[str, Any]) -> dict[str, Any]:
        examples_root = self.pybog_root / "examples"
        examples = sorted(path.name for path in examples_root.glob("*.py"))
        groups: Counter[str] = Counter()
        for name in examples:
            lowered = name.lower()
            if any(word in lowered for word in ("chiller", "pump", "lead_lag")):
                groups["Plants and rotation"] += 1
            elif any(word in lowered for word in ("ahu", "vav", "g36", "gl36")):
                groups["AHU and terminal logic"] += 1
            elif "schedule" in lowered:
                groups["Schedules"] += 1
            else:
                groups["Generic control patterns"] += 1
        return {
            "id": "pybog-examples",
            "name": "pybog Niagara equipment examples",
            "installed": bool(examples),
            "integration_status": "tested-reference-catalog",
            "role": "Niagara-native starting patterns for equipment packs and temporal logic",
            "license": "MIT",
            "revision": _revision(lock, "pybog-source"),
            "artifact_count": len(examples),
            "groups": dict(sorted(groups.items())),
            "artifacts": examples,
            "limitations": (
                "Five representative examples compile in the local contract. Examples are not "
                "complete sequences, independently verified packs, or field-qualified programs."
            ),
        }

    def _dflexlibs_inventory(self, lock: dict[str, Any]) -> dict[str, Any]:
        function_root = self.dflexlibs_root / "dflexlibs" / "hvac" / "functions"
        strategy_root = self.dflexlibs_root / "dflexlibs" / "hvac" / "strategies"
        functions = sorted(
            path.stem for path in function_root.glob("*.py") if path.name != "__init__.py"
        )
        strategies = sorted(
            path.stem for path in strategy_root.glob("*.py") if path.name != "__init__.py"
        )
        return {
            "id": "dflexlibs",
            "name": "LBNL DFLEXLIBS",
            "installed": bool(functions),
            "integration_status": "tested-reference-catalog",
            "role": "Portable zone and plant demand-flexibility control strategies",
            "license": "BSD-3-Clause-style LBNL license",
            "revision": _revision(lock, "dflexlibs"),
            "artifact_count": len(functions),
            "groups": {
                "Control functions": len(functions),
                "Composed strategies": len(strategies),
            },
            "artifacts": functions,
            "limitations": (
                "Alpha research code for demand flexibility, not a general equipment sequence "
                "library. Selected functions execute as independent reference checks only."
            ),
        }

    def _open_control_library_inventory(self, lock: dict[str, Any]) -> dict[str, Any]:
        registry_path = self.open_control_library_root / "faults" / "registry.json"
        rules: list[dict[str, Any]] = []
        if registry_path.is_file():
            rules = json.loads(registry_path.read_text(encoding="utf-8")).get("rules", [])
        families = Counter(rule.get("family", "unknown") for rule in rules)
        manifest = (
            json.loads(self.cxf_manifest_path.read_text(encoding="utf-8"))
            if self.cxf_manifest_path.is_file()
            else {}
        )
        ir_verified = set(manifest.get("ir_vector_verified_rule_ids", []))
        niagara_verified = set(manifest.get("niagara_vector_verified_rule_ids", []))
        artifacts = [
            {
                "id": rule.get("id"),
                "name": rule.get("name"),
                "group": rule.get("family"),
            }
            for rule in rules
        ]
        return {
            "id": "open-control-library",
            "name": "Open Control Library",
            "installed": bool(rules),
            "integration_status": "verified-fdd-library",
            "role": "Executable CXF fault rules, test vectors, diagrams, and point semantics",
            "license": "MIT OR Apache-2.0",
            "revision": _revision(lock, "open-control-library"),
            "artifact_count": len(rules),
            "ir_verified_translation_count": len(ir_verified),
            "niagara_verified_translation_count": len(niagara_verified),
            "groups": dict(sorted(families.items())),
            "artifacts": artifacts,
            "limitations": (
                f"{len(ir_verified)} rules pass upstream vectors after CXF-to-IR lowering; "
                f"{len(niagara_verified)} also compile to Niagara. These are commissioning/FDD "
                "routines, not complete equipment control sequences; the upstream routine "
                "registry remains empty."
            ),
        }

    def _niagara_program_library_inventory(self, lock: dict[str, Any]) -> dict[str, Any]:
        from bactalk.integrations.niagara_program_library import NiagaraProgramLibrary

        try:
            catalog = NiagaraProgramLibrary(self.niagara_program_library_root).catalog()
        except (FileNotFoundError, ValueError):
            catalog = {"count": 0, "program_object_count": 0, "templates": []}
        return {
            "id": "n4-hvac-optimization-blocks",
            "name": "Niagara 4 HVAC optimization ProgramObjects",
            "installed": bool(catalog["count"]),
            "integration_status": "inspected-niagara-reference-library",
            "role": "Niagara-native G36, plant, scheduling, FDD, and optimization references",
            "license": "MIT",
            "revision": _revision(lock, "n4-hvac-optimization-blocks"),
            "artifact_count": catalog["count"],
            "program_object_count": catalog["program_object_count"],
            "artifacts": [
                {
                    "id": item["id"],
                    "name": item["filename"],
                    "group": "Niagara ProgramObject",
                }
                for item in catalog["templates"]
            ],
            "limitations": (
                "ProgramObject archives include compiled classes and source, but BACTalk does not "
                "claim source/bytecode equivalence or runtime qualification without licensed "
                "Workbench recompilation and isolated execution."
            ),
        }
