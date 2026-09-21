from __future__ import annotations

import importlib.util
import json
import shutil
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

STAGES = (
    "discovered",
    "installed",
    "executable",
    "product-wired",
    "target-compiled",
    "verified",
    "field-qualified",
    "production-supported",
)


def _package_version(distribution: str, module: str | None = None) -> str | None:
    try:
        if module and importlib.util.find_spec(module) is None:
            return None
        return metadata.version(distribution)
    except (metadata.PackageNotFoundError, ModuleNotFoundError, ValueError):
        return None


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _component(
    component_id: str,
    name: str,
    *,
    stage: str,
    installed: bool,
    version: str | None,
    license_name: str,
    role: str,
    product_path: str | None,
    evidence_command: str | None,
    blocker: str | None = None,
    selected: bool = True,
) -> dict[str, Any]:
    if stage not in STAGES:
        raise ValueError(f"unknown capability stage: {stage}")
    return {
        "id": component_id,
        "name": name,
        "selected": selected,
        "installed": installed,
        "version": version,
        "license": license_name,
        "stage": stage,
        "role": role,
        "product_path": product_path,
        "evidence_command": evidence_command,
        "blocker": blocker,
        "production_ready": stage == "production-supported",
    }


class IntegrationReadiness:
    """Machine-readable, deliberately conservative integration capability ledger."""

    def __init__(self, root: Path = Path(".")):
        self.root = root.resolve()

    def report(self) -> dict[str, Any]:
        lock_path = self.root / "ops/stack.lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8")) if lock_path.is_file() else {}
        revisions = {
            key: value.get("revision")
            for key, value in lock.get("components", {}).items()
            if isinstance(value, dict)
        }
        haxall_package = self.root / "ops/haxall/node_modules/@haxall/haxall/package.json"
        constrain_python = self.root / ".constrain-venv/bin/python"
        buildingmotif_python = self.root / ".buildingmotif-venv/bin/python"
        volttron_python = self.root / ".volttron-venv/bin/python"
        docker = shutil.which("docker") or shutil.which("podman")
        alfalfa_evidence = _load_json_object(
            self.root / ".bactalk/alfalfa-runtime-evidence.json"
        )
        alfalfa_graph_evidence = _load_json_object(
            self.root / ".bactalk/alfalfa-graph-evidence.json"
        )
        alfalfa_product_evidence = _load_json_object(
            self.root / ".bactalk/alfalfa-product-evidence.json"
        )
        boptest_product_evidence = _load_json_object(
            self.root / ".bactalk/boptest-graph-runtime-evidence.json"
        )
        alfalfa_runtime_pass = (
            alfalfa_evidence.get("schema") == "bactalk.alfalfa-runtime-evidence/v1"
            and alfalfa_evidence.get("status") == "pass"
            and alfalfa_evidence.get("results", {}).get("clean_stop") is True
            and alfalfa_evidence.get("results", {}).get("changed_output_count", 0) > 0
        )
        alfalfa_graph_trajectory = alfalfa_graph_evidence.get("trajectory", [])
        alfalfa_graph_pass = (
            alfalfa_graph_evidence.get("schema") == "bactalk.alfalfa-graph-run/v1"
            and alfalfa_graph_evidence.get("status") == "pass"
            and alfalfa_graph_evidence.get("clean_stop") is True
            and isinstance(alfalfa_graph_trajectory, list)
            and len(alfalfa_graph_trajectory) > 0
            and all(
                isinstance(sample, dict)
                and isinstance(sample.get("command_echoes"), dict)
                and bool(sample["command_echoes"])
                and all(
                    isinstance(echo, dict) and echo.get("matched") is True
                    for echo in sample["command_echoes"].values()
                )
                for sample in alfalfa_graph_trajectory
            )
        )
        alfalfa_product_runtime = alfalfa_product_evidence.get("runtime_evidence", {})
        alfalfa_product_oracles = (
            alfalfa_product_runtime.get("oracles", [])
            if isinstance(alfalfa_product_runtime, dict)
            else []
        )
        alfalfa_product_oracle_pass = (
            alfalfa_product_evidence.get("schema")
            == "bactalk.alfalfa-product-workflow/v1"
            and alfalfa_product_evidence.get("status") == "pass"
            and alfalfa_product_runtime.get("status") == "pass"
            and alfalfa_product_runtime.get("approval_allowed") is True
            and isinstance(alfalfa_product_oracles, list)
            and bool(alfalfa_product_oracles)
            and all(
                isinstance(oracle, dict)
                and oracle.get("completed") is True
                and oracle.get("passed") is True
                for oracle in alfalfa_product_oracles
            )
        )
        qualification_job = alfalfa_product_evidence.get("qualification_job", {})
        alfalfa_durable_qualification_pass = (
            isinstance(qualification_job, dict)
            and qualification_job.get("status") == "succeeded"
            and qualification_job.get("schema_version")
            == "bactalk.qualification-job/v3"
            and qualification_job.get("qualification_passed") is True
            and isinstance(qualification_job.get("worker_id"), str)
            and bool(qualification_job["worker_id"])
            and qualification_job.get("progress", {}).get("percent") == 100.0
            and isinstance(qualification_job.get("input_sha256"), str)
            and len(qualification_job["input_sha256"]) == 64
            and isinstance(
                qualification_job.get("candidate_artifact_sha256"), str
            )
            and len(qualification_job["candidate_artifact_sha256"]) == 64
            and isinstance(qualification_job.get("result_artifact_sha256"), str)
            and len(qualification_job["result_artifact_sha256"]) == 64
        )
        boptest_qualification_job = boptest_product_evidence.get(
            "qualification_job", {}
        )
        boptest_durable_qualification_pass = (
            boptest_product_evidence.get("schema")
            == "bactalk.boptest-contractor-e2e/v2"
            and boptest_product_evidence.get("status") == "pass"
            and boptest_product_evidence.get("room_temperature_changed") is True
            and isinstance(boptest_qualification_job, dict)
            and boptest_qualification_job.get("kind") == "boptest"
            and boptest_qualification_job.get("status") == "succeeded"
            and boptest_qualification_job.get("schema_version")
            == "bactalk.qualification-job/v3"
            and boptest_qualification_job.get("qualification_passed") is True
            and isinstance(boptest_qualification_job.get("worker_id"), str)
            and bool(boptest_qualification_job["worker_id"])
            and boptest_qualification_job.get("progress", {}).get("percent") == 100.0
            and isinstance(
                boptest_qualification_job.get("candidate_artifact_sha256"), str
            )
            and len(boptest_qualification_job["candidate_artifact_sha256"]) == 64
            and isinstance(boptest_qualification_job.get("input_sha256"), str)
            and len(boptest_qualification_job["input_sha256"]) == 64
            and isinstance(
                boptest_qualification_job.get("result_artifact_sha256"), str
            )
            and len(boptest_qualification_job["result_artifact_sha256"]) == 64
        )
        durable_qualification_pass = (
            alfalfa_durable_qualification_pass
            and boptest_durable_qualification_pass
        )
        rq_version = _package_version("rq", "rq")
        redis_version = _package_version("redis", "redis")
        qualification_queue_installed = (
            rq_version is not None
            and redis_version is not None
            and (self.root / "ops/qualification-queue.compose.yml").is_file()
        )
        components = [
            _component(
                "aixocat",
                "RWTH-EBC AixOCAT",
                stage="target-compiled",
                installed=(self.root / ".vendor/aixocat/LICENSE").is_file(),
                version=revisions.get("aixocat"),
                license_name="MIT",
                role=(
                    "IEC 61131-3 control primitives and real heat-pump, hydronic, pump, valve, "
                    "sensor, alarm, and interlock implementation references"
                ),
                product_path=(
                    "211-pattern typed source catalog; six reviewed scaling, heating-curve, "
                    "manual, deadband/dead-zone, and timed-interlock patterns lower to "
                    "behavior-verified IR and Niagara .bog"
                ),
                evidence_command="make aixocat-contract",
                blocker=(
                    "205 patterns remain source-only; TwinCAT/CODESYS source is not itself "
                    "Niagara runtime qualification. Vendor compiled libraries are excluded."
                ),
            ),
            _component(
                "pybog",
                "pybog",
                stage="target-compiled",
                installed=_package_version("pybog", "bog_builder") is not None,
                version=_package_version("pybog", "bog_builder"),
                license_name="MIT",
                role="Niagara .bog generation, analysis, and comparison",
                product_path=(
                    "Every stock/custom-lowered run plus optional template diff; stateful "
                    "plant jobs use the separate ProgramObject source-package target"
                ),
                evidence_command="pytest -q tests/test_service.py tests/test_api.py",
                blocker="Licensed Niagara import/runtime qualification is still required.",
            ),
            _component(
                "pybog-examples",
                "pybog equipment/control examples",
                stage="executable",
                installed=(self.root / ".vendor/pybog/examples").is_dir(),
                version=revisions.get("pybog-source"),
                license_name="MIT",
                role="Niagara-native pack research and regression fixtures",
                product_path=(
                    "Reference catalog; selected patterns are being translated into IR packs"
                ),
                evidence_command="make pybog-examples-contract",
                blocker=(
                    "Examples compile but are not complete, independently verified, or field-"
                    "qualified equipment packs."
                ),
            ),
            _component(
                "contractor-niagara-environments",
                "Contractor Niagara environment packs",
                stage="product-wired",
                installed=True,
                version="1.0",
                license_name="Internal format; each asset retains its declared license",
                role=(
                    "Safe ingestion and typed compilation for shop modules, palettes, and "
                    "graphics templates"
                ),
                product_path=(
                    "POST /api/runs/import environment_pack; generated environment manifest; "
                    "NiagaraCompiler custom component contracts"
                ),
                evidence_command="make environment-pack-contract",
                blocker=(
                    "Uploaded Java is not executed. Exact module dependencies, Niagara versions, "
                    "Workbench import/restart behavior, and graphics rendering require a licensed "
                    "runtime matrix."
                ),
            ),
            _component(
                "niagara-point-bindings",
                "Exact Niagara point binding",
                stage="product-wired",
                installed=True,
                version="1.0",
                license_name="Internal generator; Apache-2.0 source pattern",
                role=(
                    "Bind existing Niagara proxy points to compiled logic with exact ORDs and "
                    "declared command priorities"
                ),
                product_path=(
                    "Signed niagara-point-bindings.json, readback contract, and generated "
                    "collision-denying SDK installer on every run"
                ),
                evidence_command="make niagara-binding-contract",
                blocker=(
                    "Exact licensed-SDK compilation and disposable-station link/type/value-flow "
                    "readback are required before target qualification."
                ),
            ),
            _component(
                "modelica-buildings",
                "LBNL Modelica Buildings/OBC",
                stage="verified",
                installed=(
                    self.root / ".vendor/modelica-buildings/Buildings/Controls/OBC"
                ).is_dir(),
                version=revisions.get("modelica-buildings"),
                license_name="Revised BSD-3-Clause",
                role="Versioned CDL and Guideline 36 executable source library",
                product_path=(
                    "Allowlisted 241-controller G36 API; CDL translation, OCE validation, and "
                    "configured source-target-complete controller jobs through the normal "
                    "test/review/approval/export workflow"
                ),
                evidence_command="make cdl-oce-contract",
                blocker=(
                    "All 116 non-validation controllers are classified: 28 lower to exact IR, "
                    "84 require job design parameters, and zero currently fail the translation "
                    "pipeline. Licensed Niagara runtime and field qualification remain."
                ),
            ),
            _component(
                "modelica-json",
                "LBNL modelica-json",
                stage="verified",
                installed=(self.root / ".vendor/modelica-json/node_modules").is_dir(),
                version=revisions.get("modelica-json"),
                license_name="BSD-3-Clause",
                role="Modelica/CDL to JSON/CXF translation",
                product_path=(
                    "G36Library allowlist and reviewed annotated Modelica containers -> "
                    "bounded CdlTranslator -> CXF"
                ),
                evidence_command="make cdl-oce-contract",
                blocker=(
                    "The local null-type guard is digest-pinned and contract-tested; full "
                    "configured AHU elaboration still exceeds the bounded translation window."
                ),
            ),
            _component(
                "ctrl-flow",
                "LBNL ctrl-flow",
                stage="product-wired",
                installed=(
                    self.root
                    / ".vendor/ctrl-flow-dev/client/src/interpreter/interpreter.ts"
                ).is_file()
                and (self.root / ".vendor/ctrl-flow-dev/client/node_modules/ts-node").is_dir(),
                version=revisions.get("ctrl-flow"),
                license_name="BSD-3-Clause-style LBNL license with notices",
                role=(
                    "System-level HVAC design configuration, conditional option semantics, "
                    "and auditable engineering decisions"
                ),
                product_path=(
                    "Template catalog/schema/configure APIs invoke the pinned upstream Linkage "
                    "Schema interpreter; the programming-brief API binds approved choices to "
                    "components, points, scenarios, exact G36 controllers, and release gates; "
                    "point reconciliation blocks missing, ambiguous, duplicate, mistyped, or "
                    "unit-invalid contractor I/O; sequence reconciliation maps every selected "
                    "scenario to deterministic facet evidence, exposes omitted language, and "
                    "extracts unapproved thresholds, timing, actions, policies, and bindings; "
                    "approver review re-derives source/digests and emits non-executable oracles"
                ),
                evidence_command="make ctrl-flow-contract",
                blocker=(
                    "The current upstream snapshot has three templates (multizone VAV AHU, "
                    "cooling-only VAV, and VAV reheat). The generated brief still requires the "
                    "phrase evidence to be converted into approved executable requirements, "
                    "independent oracle approval, target completion, and licensed Niagara "
                    "qualification."
                ),
            ),
            _component(
                "modelica-plant-controls",
                "LBNL Modelica Buildings plant controls",
                stage="product-wired",
                installed=(
                    self.root
                    / ".vendor/modelica-buildings/Buildings/Templates/Plants/Controls"
                ).is_dir(),
                version=revisions.get("modelica-buildings"),
                license_name="Revised BSD-3-Clause",
                role=(
                    "Plant enabling, heat-pump, heat-recovery chiller, minimum-flow, pump, "
                    "setpoint, staging/rotation, and plant utility control source"
                ),
                product_path=(
                    "PlantControlsLibrary catalog/translate/execute APIs and exact Niagara "
                    "ProgramObject package download, plus the contractor job/test/review/export "
                    "workflow for LBNL_PLANT_CONTROLLER jobs"
                ),
                evidence_command="make plant-controls-contract",
                blocker=(
                    "All 38 non-validation control models pass the retained parameterization, "
                    "translation, execution, and Niagara target-package audit. Stateful models "
                    "still require licensed Workbench compilation, runtime parity, hardware-in-"
                    "loop, and field qualification before deployment."
                ),
            ),
            _component(
                "rumoca",
                "Rumoca Modelica compiler",
                stage="product-wired",
                installed=(self.root / ".vendor/bin/rumoca").is_file(),
                version=revisions.get("rumoca"),
                license_name="Apache-2.0",
                role="Resolve, instantiate, and flatten allowlisted Modelica/G36 classes",
                product_path=(
                    "POST /api/library/g36/controllers/{id}/flatten and isolated compiler adapter"
                ),
                evidence_command="make rumoca-contract",
                blocker=(
                    "Selected G36 logic flattens; full composite VAV currently stops at "
                    "parameter-derived conditional instantiation. Flat IR is not yet lowered "
                    "into BACTalk IR."
                ),
            ),
            _component(
                "modelica-standard-library",
                "Modelica Standard Library",
                stage="verified",
                installed=(
                    self.root / ".vendor/modelica-standard-library/Modelica/package.mo"
                ).is_file(),
                version=revisions.get("modelica-standard-library"),
                license_name="BSD-3-Clause",
                role="Pinned language types and package dependencies for Modelica elaboration",
                product_path="Rumoca compiler source root",
                evidence_command="make rumoca-contract",
                blocker="Build dependency only; it is not equipment control logic by itself.",
            ),
            _component(
                "open-control-engine",
                "Open Control Engine",
                stage="verified",
                installed=(self.root / ".vendor/open-control-engine").is_dir(),
                version=revisions.get("open-control-engine"),
                license_name="MIT OR Apache-2.0",
                role="Executable CXF/CDL block and stateful trajectory oracle",
                product_path="POST /api/execute/cxf, G36Library, and isolated Rust runner",
                evidence_command="make oce-contract && make cdl-oce-contract",
                blocker="Pre-1.0 and not yet the full Niagara lowering source of truth.",
            ),
            _component(
                "constrain",
                "PNNL ConStrain",
                stage="product-wired",
                installed=constrain_python.is_file(),
                version=revisions.get("constrain"),
                license_name="BSD-2-Clause",
                role="Independent G36/90.1 time-series verification",
                product_path="POST /api/verify/constrain",
                evidence_command="make constrain-contract",
                blocker="Rules require explicit applicability and point mappings per pack.",
            ),
            _component(
                "buildingmotif",
                "BuildingMOTIF",
                stage="product-wired",
                installed=buildingmotif_python.is_file(),
                version="0.4.0" if buildingmotif_python.is_file() else None,
                license_name="BSD-3-Clause",
                role="Semantic equipment templates, topology generation, and validation",
                product_path="BuildingMotifAdapter and /api/semantics/buildingmotif endpoints",
                evidence_command="make buildingmotif-contract",
                blocker=(
                    "Semantic templates describe equipment and required metadata; they are not "
                    "deployable Niagara control programs."
                ),
            ),
            _component(
                "boptest",
                "IBPSA BOPTEST",
                stage="product-wired",
                installed=(self.root / ".vendor/boptest").is_dir(),
                version=revisions.get("boptest"),
                license_name="Revised BSD-3-Clause with notices",
                role="Dynamic building simulation and KPI oracle",
                product_path=(
                    "BoptestGraphRunner maps every typed graph boundary explicitly, enforces "
                    "advertised actuator bounds, runs closed-loop FMU trajectories through "
                    "the durable qualification worker plane, retains progress/cancellation, "
                    "KPIs, and grades the command trace with pyfunnel"
                ),
                evidence_command="make boptest-graph-runtime",
                blocker=(
                    "Install Docker/Podman to execute locally. " if not docker else ""
                )
                + (
                    "Run the retained queued BOPTEST product qualification on this host. "
                    if not boptest_durable_qualification_pass
                    else ""
                )
                + (
                    "Production equipment packs still need authoritative BOPTEST point maps, "
                    "long-horizon scenario oracles, failure minimization, and licensed "
                    "Niagara-to-BOPTEST BACnet qualification."
                ),
            ),
            _component(
                "alfalfa",
                "Alfalfa virtual building service",
                stage="product-wired" if alfalfa_runtime_pass else "executable",
                installed=(self.root / ".vendor/alfalfa").is_dir(),
                version=revisions.get("alfalfa"),
                license_name="BSD-3-Clause",
                role="EnergyPlus/OpenStudio/FMU virtual-building runtime",
                product_path=(
                    "Digest-pinned isolated service plus hardened scalar-output worker; "
                    "external-clock FMU lifecycle and typed graph coupling retain signal, "
                    "command/echo, trajectory, clean-stop, and independent pyfunnel oracle "
                    "evidence; the contractor lane "
                    "can close every graph input/output through fresh-port, loopback-only "
                    "BACnet/IP reads, priority writes, and readbacks"
                ),
                evidence_command=(
                    "make alfalfa-runtime-up alfalfa-runtime-smoke alfalfa-graph-smoke "
                    "alfalfa-product-smoke"
                ),
                blocker=(
                    (
                        "Docker/Compose is required and is absent on this host. "
                        if not docker
                        else ""
                    )
                    + (
                        "Run the retained FMU qualification on this host. "
                        if not alfalfa_runtime_pass
                        else ""
                    )
                    + (
                        "Run the typed graph-to-FMU qualification on this host. "
                        if not alfalfa_graph_pass
                        else ""
                    )
                    + (
                        "Run the signed Alfalfa/BACnet product qualification with at least "
                        "one passing independent trajectory oracle. "
                        if not alfalfa_product_oracle_pass
                        else ""
                    )
                    + (
                        "Production Linux capacity, job-specific model/map authority, "
                        "licensed Niagara controller attachment, external-controller HIL, "
                        "HA, and field qualification remain."
                    )
                ),
            ),
            _component(
                "alfalfa-client",
                "Alfalfa Python client",
                stage="product-wired" if alfalfa_runtime_pass else "executable",
                installed=_package_version("alfalfa-client", "alfalfa_client") is not None,
                version=_package_version("alfalfa-client", "alfalfa_client"),
                license_name="BSD-3-Clause",
                role="Client API for Alfalfa virtual buildings",
                product_path=(
                    "AlfalfaClient-backed retained FMU and typed-graph qualification with "
                    "independent pyfunnel trajectory acceptance"
                ),
                evidence_command=(
                    "make alfalfa-runtime-smoke alfalfa-graph-smoke alfalfa-product-smoke"
                ),
                blocker=(
                    "Needs a pinned running Alfalfa service and retained trajectory evidence."
                    if not alfalfa_runtime_pass
                    else (
                        "Production Linux capacity, job-specific model/map authority, "
                        "licensed Niagara controller coupling, HA, and field qualification "
                        "remain."
                    )
                ),
            ),
            _component(
                "qualification-job-plane",
                "RQ / Valkey qualification job plane",
                stage=(
                    "product-wired"
                    if qualification_queue_installed and durable_qualification_pass
                    else "executable" if qualification_queue_installed else "discovered"
                ),
                installed=qualification_queue_installed,
                version=(
                    f"RQ {rq_version} / redis-py {redis_version} / Valkey 8.1.10"
                    if qualification_queue_installed
                    else None
                ),
                license_name="BSD-2-Clause / MIT / BSD-3-Clause",
                role=(
                    "Durable external execution, progress, cancellation, and retained state "
                    "for long-running building-physics qualifications"
                ),
                product_path=(
                    "Alfalfa and BOPTEST qualification submissions persist digest-bound "
                    "requests (plus the exact FMU for Alfalfa) against the exact submitted "
                    "candidate before JSON-only RQ dispatch; a separate SpawnWorker refuses "
                    "changed candidates and updates progress and terminal evidence while the UI "
                    "polls or requests cancellation"
                ),
                evidence_command=(
                    "make qualification-queue-up alfalfa-product-smoke "
                    "boptest-graph-runtime"
                ),
                blocker=(
                    (
                        "Run the retained queued Alfalfa whole-building product workflow. "
                        if not alfalfa_durable_qualification_pass
                        else ""
                    )
                    + (
                        "Run the retained queued BOPTEST product workflow. "
                        if not boptest_durable_qualification_pass
                        else ""
                    )
                    + (
                        "Production shared artifact storage, broker HA/TLS, worker autoscaling, "
                        "broker-loss recovery drills, backup/restore qualification, and Linux "
                        "capacity evidence remain."
                    )
                ),
            ),
            _component(
                "dflexlibs",
                "LBNL DFLEXLIBS",
                stage="executable",
                installed=(self.root / ".vendor/dflexlibs/dflexlibs/hvac").is_dir(),
                version=revisions.get("dflexlibs"),
                license_name="BSD-3-Clause-style LBNL license",
                role="Zone and plant demand-flexibility control reference library",
                product_path="Pinned reference catalog; not on the Niagara generation path",
                evidence_command="make dflexlibs-contract",
                blocker=(
                    "Alpha research code covers demand flexibility rather than general HVAC "
                    "equipment programming; translation and independent qualification remain."
                ),
            ),
            _component(
                "open-control-library",
                "Open Control Library",
                stage="verified",
                installed=(
                    self.root / ".vendor/open-control-library/faults/registry.json"
                ).is_file(),
                version=revisions.get("open-control-library"),
                license_name="MIT OR Apache-2.0",
                role=(
                    "Executable CXF fault detection, commissioning vectors, diagrams, and "
                    "semantic point dictionaries across 14 equipment families"
                ),
                product_path=(
                    "Catalog/API plus 137 manifest-qualified CXF -> typed IR -> upstream vector "
                    "executions; 113 also compile to Niagara .bog"
                ),
                evidence_command="make open-control-library-contract",
                blocker=(
                    "The 137 entries are fault rules, not complete deployable equipment control "
                    "sequences; 24 use exact IR temporal primitives without a qualified Niagara "
                    "lowering, and pack applicability/point-role mapping is still required."
                ),
            ),
            _component(
                "n4-hvac-optimization-blocks",
                "Niagara 4 HVAC optimization ProgramObjects",
                stage="product-wired",
                installed=(self.root / ".vendor/n4-hvac-optimization-blocks/bog_files").is_dir(),
                version=revisions.get("n4-hvac-optimization-blocks"),
                license_name="MIT",
                role=(
                    "Niagara-native ProgramObject references for G36, plant logic, scheduling, "
                    "FDD, and optimization"
                ),
                product_path=(
                    "Read-only catalog and source inspection API; immutable templates remain "
                    "provenance-tracked"
                ),
                evidence_command="make n4-hvac-library-contract",
                blocker=(
                    "Generated or modified ProgramObjects require licensed Workbench compilation, "
                    "runtime simulation, compatibility qualification, and human approval."
                ),
            ),
            _component(
                "niagara-program-codegen",
                "Exact Niagara ProgramObject source generation",
                stage="product-wired",
                installed=True,
                version="3.2",
                license_name="Internal generated source",
                role=(
                    "Exact non-stock source lowering for CDL PID/PIDWithReset, Hysteresis, "
                    "TrueDelay/TrueFalseHold/Latch/Timer/MovingAverage/FallingEdge, Sampler, "
                    "TriggeredSampler, UnitDelay, Assert, plant first-scan Initialization, "
                    "plant TimerWithReset, "
                    "and common G36 TrimAndRespond; "
                    "explicit host-tick-only Pre projection"
                ),
                product_path=(
                    "G36 API download containing deterministic ProgramObject source, typed "
                    "slots, provenance manifest, and standalone Java parity kernel"
                ),
                evidence_command="make niagara-program-codegen-contract",
                blocker=(
                    "The package is source, not compiled Niagara bytecode. Exact licensed "
                    "Workbench compilation and runtime trajectory parity are mandatory."
                ),
            ),
            _component(
                "pyfunnel",
                "pyfunnel",
                stage="executable",
                installed=_package_version("pyfunnel", "pyfunnel") is not None,
                version=_package_version("pyfunnel", "pyfunnel"),
                license_name="BSD-3-Clause",
                role="Reference/test trajectory tolerance scoring",
                product_path="FunnelScorer adapter",
                evidence_command="pytest -q tests/test_funnel.py",
                blocker="Not yet retained in every applicable run report.",
            ),
            _component(
                "brick",
                "Brick Schema",
                stage="product-wired",
                installed=_package_version("brickschema", "brickschema") is not None,
                version=_package_version("brickschema", "brickschema"),
                license_name="BSD-3-Clause",
                role="Building topology and point semantics",
                product_path="Every run emits and SHACL-validates semantic-model.ttl",
                evidence_command="pytest -q tests/test_semantics.py",
                blocker=(
                    "Current JobSpec models one equipment object, not a complete building graph."
                ),
            ),
            _component(
                "haxall",
                "Haxall/Xeto",
                stage="product-wired",
                installed=haxall_package.is_file(),
                version="4.0.4" if haxall_package.is_file() else None,
                license_name="AFL-3.0",
                role="Haystack/Xeto type and required-point validation",
                product_path="POST /api/verify/haxall",
                evidence_command="make haxall-contract",
                blocker="Automatic Brick↔Xeto point/spec mapping is incomplete.",
            ),
            _component(
                "phable",
                "Phable",
                stage="product-wired",
                installed=_package_version("phable", "phable") is not None,
                version=_package_version("phable", "phable"),
                license_name="MIT",
                role="Haystack serialization and Haxall response decoding",
                product_path="HaxallValidator",
                evidence_command="pytest -q tests/test_external_verifiers.py -k haxall",
                blocker=None,
            ),
            _component(
                "bacpypes3",
                "BACpypes3",
                stage="product-wired",
                installed=_package_version("bacpypes3", "bacpypes3") is not None,
                version=_package_version("bacpypes3", "bacpypes3"),
                license_name="MIT",
                role="BACnet protocol primitives and isolated virtual-device runtime",
                product_path=(
                    "Every scanned run emits loopback device configs, launcher, point map, and "
                    "acceptance-scenario contract"
                ),
                evidence_command="make bacnet-lab-contract",
                blocker=(
                    "Exact MS/TP serial timing/router behavior and physical Niagara execution "
                    "remain hardware-in-loop qualification gates."
                ),
            ),
            _component(
                "bac0",
                "BAC0",
                stage="product-wired",
                installed=_package_version("BAC0", "BAC0") is not None,
                version=_package_version("BAC0", "BAC0"),
                license_name="LGPL-3.0",
                role="Independent BAS-facing BACnet lab client and out_of_service test path",
                product_path=(
                    "Generated BAC0 probe reads all mapped points from the virtual devices"
                ),
                evidence_command="make bacnet-lab-contract",
                blocker=(
                    "Hardware profile and LGPL distribution notices remain required before "
                    "shipping the optional lab dependency."
                ),
            ),
            _component(
                "bacnet-simulator",
                "Independent BACnet Simulator",
                stage="product-wired",
                installed=(self.root / ".vendor/bacnet-simulator/LICENSE").is_file(),
                version="0.1.0",
                license_name="MIT",
                role=(
                    "Independent BACnet/IP device, priority-array, relinquish, COV, scenario, "
                    "offline-recovery, and REST-observation oracle"
                ),
                product_path=(
                    "Every scanned run emits a second compatible loopback device set and "
                    "launcher under independent-simulator"
                ),
                evidence_command="make independent-bacnet-simulator-contract",
                blocker=(
                    "It is a beta laboratory simulator without BTL certification, BACnet/SC, "
                    "routing/BBMD, or native BACnet alarm notifications; licensed Niagara and "
                    "serial MS/TP qualification remain separate."
                ),
            ),
            _component(
                "open-fdd",
                "Open-FDD",
                stage="product-wired",
                installed=_package_version("open-fdd", "open_fdd") is not None,
                version=_package_version("open-fdd", "open_fdd"),
                license_name="MIT",
                role="Independent HVAC fault-detection and commissioning analytics",
                product_path="POST /api/verify/open-fdd",
                evidence_command="make open-fdd-contract",
                blocker="Rules require pack-specific logical-role mappings and operational gates.",
            ),
            _component(
                "volttron",
                "Eclipse VOLTTRON",
                stage="product-wired",
                installed=volttron_python.is_file(),
                version=revisions.get("volttron-core"),
                license_name="Apache-2.0",
                role="Read-only edge data-plane export and driver validation",
                product_path="Every scanned run emits read-only Platform Driver artifacts",
                evidence_command="make volttron-contract",
                blocker="Modular runtime needs Linux; native macOS abstract IPC is unsupported.",
            ),
            _component(
                "nhaystack",
                "nHaystack Niagara module",
                stage="product-wired",
                installed=(self.root / ".vendor/nhaystack/nhaystack-rt").is_dir(),
                version=revisions.get("nhaystack"),
                license_name="AFL-3.0",
                role=("Niagara-native semantic-tag installation plus current/history readback"),
                product_path=(
                    "Every run emits signed exact-ORD tag-installer source plus a read-only "
                    "nHaystack Zinc/readback package; "
                    "GET /api/runs/{id}/nhaystack-manifest"
                ),
                evidence_command="make nhaystack-contract",
                blocker=(
                    "Generated source is collision-denying and passes a compiled stub harness, "
                    "but still requires the exact shop-approved module/SDK, licensed Niagara "
                    "runtime, cache rebuild, and captured readback."
                ),
            ),
            _component(
                "am8x-alarm-pattern",
                "Niagara alarm SDK pattern (am8x source)",
                stage="product-wired",
                installed=(self.root / ".vendor/am8x-control/LICENSE").is_file(),
                version=revisions.get("am8x-control"),
                license_name="Apache-2.0",
                role="Generic BAlarmClass and BAlarmSourceExt automation pattern",
                product_path=(
                    "Every run emits a deterministic alarm execution plan, Niagara Java source, "
                    "and readback contract; GET /api/runs/{id}/niagara-alarm-plan"
                ),
                evidence_command="make niagara-alarm-contract",
                blocker=(
                    "Licensed-SDK compilation, AlarmService policy binding, and disposable-"
                    "station transition/routing qualification remain required."
                ),
            ),
            _component(
                "niagara-px-template-compiler",
                "Niagara PX template compiler",
                stage="target-compiled",
                installed=True,
                version="1",
                license_name="BACTalk code; contractor templates retain their own license",
                role="Bind contractor-standard PX views to exact generated Niagara point ORDs",
                product_path=(
                    "Environment-pack PX templates compile into signed deliverable PX files "
                    "and a complete binding plan"
                ),
                evidence_command="make niagara-graphics-contract",
                blocker=(
                    "Well-formedness and complete binding are verified offline; exact Niagara "
                    "version/module rendering, navigation, and live-value readback remain required."
                ),
            ),
            _component(
                "niagara-station-assembler",
                "Niagara station BOG assembler",
                stage="target-compiled",
                installed=True,
                version="1",
                license_name="BACTalk code",
                role=(
                    "Insert or explicitly replace one or many generated programs in contractor "
                    "station templates without mutating live stations"
                ),
                product_path=(
                    "Run and project builds support guarded assembly; approved exports return "
                    "the assembled BOG and retain a signed assembly manifest"
                ),
                evidence_command="make niagara-station-contract",
                blocker=(
                    "Structural analysis is offline; exact Workbench import, dependency "
                    "resolution, compile/restart, installer execution, and readback remain "
                    "required."
                ),
            ),
            _component(
                "openmodelica",
                "OpenModelica",
                stage="discovered" if shutil.which("omc") is None else "installed",
                installed=shutil.which("omc") is not None,
                version=None,
                license_name="GPL-3.0 or OSMC Public License; component-specific options",
                role="Optional isolated Modelica flattening/build tool",
                product_path=None,
                evidence_command=None,
                blocker=(
                    "Not installed; legal/package boundary review is required before distribution."
                ),
            ),
            _component(
                "bacnet-stack",
                "bacnet-stack (C)",
                stage="discovered",
                installed=False,
                version=None,
                license_name="GPL with linking exception",
                role="Potential embedded/edge BACnet runtime",
                product_path=None,
                evidence_command=None,
                blocker="Not selected: Python/VOLTTRON lanes cover the current server product.",
                selected=False,
            ),
            _component(
                "niagara-runtime",
                "Licensed Niagara Workbench/runtime",
                stage="discovered",
                installed=False,
                version=None,
                license_name="Proprietary",
                role="Final import, compile, restart, and runtime qualification",
                product_path=None,
                evidence_command=None,
                blocker=(
                    "A licensed isolated Niagara lab and supported-version fixtures are required."
                ),
            ),
        ]
        production_ready = all(item["production_ready"] for item in components if item["selected"])
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "production_ready": production_ready,
            "stage_order": list(STAGES),
            "policy": (
                "A component is production-ready only at production-supported. Installed source, "
                "a package import, or a mock contract does not imply field support."
            ),
            "components": components,
        }
