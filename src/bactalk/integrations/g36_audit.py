from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from collections import Counter
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bactalk.integrations.g36_library import G36Library, G36RequiredParametersError

AUDIT_SCHEMA = "bactalk.g36-coverage-audit/v4"

_OCE_DIAGNOSTIC = re.compile(r"(?m)^(?P<severity>error|warning)\|(?P<code>[^|\r\n]+)\|")


def _classify_pipeline_failure(exc: Exception) -> tuple[str, dict[str, int]]:
    """Return a stable pipeline stage and structured OCE diagnostic counts."""

    message = str(exc)
    diagnostics = Counter(
        f"{match.group('severity')}:{match.group('code')}"
        for match in _OCE_DIAGNOSTIC.finditer(message)
    )
    error_type = type(exc).__name__
    if diagnostics or "Open Control Engine" in message or "CXF validation" in message:
        stage = "cxf_validation"
    elif error_type == "CxfImportError":
        stage = "typed_ir_lowering"
    elif (
        "translation" in message.lower()
        or "modelica-json" in message.lower()
        or "CXF artifact" in message
    ):
        stage = "modelica_to_cxf"
    else:
        stage = "pipeline_unknown"
    return stage, dict(sorted(diagnostics.items()))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head(path: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return "unavailable"
    return result.stdout.strip()


def _git_worktree_sha256(path: Path) -> str:
    """Bind evidence to tracked local patches as well as the upstream revision."""

    try:
        result = subprocess.run(
            ["git", "-C", str(path), "diff", "--binary", "--no-ext-diff", "HEAD"],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return "unavailable"
    return hashlib.sha256(result.stdout).hexdigest()


class G36CoverageAuditor:
    """Produce resumable, source-bound evidence for every selected G36 controller."""

    def __init__(self, library: G36Library | None = None):
        self.library = library or G36Library()

    def run(
        self,
        output_path: Path,
        *,
        controller_ids: Iterable[str] | None = None,
        include_validation: bool = True,
        workers: int = 1,
        resume: bool = True,
    ) -> dict[str, Any]:
        if workers < 1 or workers > 16:
            raise ValueError("workers must be between 1 and 16")
        catalog = self.library.catalog()
        available = {item["id"]: item for item in catalog["controllers"]}
        if controller_ids is None:
            selected = [
                item
                for item in catalog["controllers"]
                if include_validation or not item["validation_fixture"]
            ]
        else:
            requested = list(dict.fromkeys(controller_ids))
            missing = sorted(set(requested) - set(available))
            if missing:
                raise ValueError("unknown G36 controllers: " + ", ".join(missing))
            selected = [available[controller_id] for controller_id in requested]
        if not selected:
            raise ValueError("G36 audit selection is empty")

        pipeline = self._pipeline_identity(selected)
        records = self._resume_records(output_path, pipeline) if resume else {}
        selected_ids = {item["id"] for item in selected}
        records = {
            controller_id: record
            for controller_id, record in records.items()
            if controller_id in selected_ids
            and record.get("source_sha256") == available[controller_id]["source_sha256"]
        }
        pending = [item for item in selected if item["id"] not in records]

        if workers == 1:
            for item in pending:
                records[item["id"]] = self._audit_one(item)
                self._write(output_path, pipeline, selected, records)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(self._audit_one, item): item for item in pending}
                for future in as_completed(futures):
                    item = futures[future]
                    try:
                        record = future.result()
                    except Exception as exc:  # defensive boundary around worker transport
                        record = self._failure(item, exc, duration_seconds=0.0)
                    records[item["id"]] = record
                    self._write(output_path, pipeline, selected, records)

        return self._write(output_path, pipeline, selected, records)

    def _audit_one(self, controller: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        try:
            translated = self.library.translate(controller["id"])
        except G36RequiredParametersError as exc:
            return self._parameters_required(
                controller,
                exc,
                duration_seconds=time.monotonic() - started,
            )
        except Exception as exc:
            return self._failure(
                controller,
                exc,
                duration_seconds=time.monotonic() - started,
            )
        lowering = translated["lowering"]
        typed_ir_complete = bool(lowering["translatable"])
        niagara_native_complete = bool(lowering["niagara_translatable"])
        if niagara_native_complete:
            status = "niagara_native_complete"
        elif typed_ir_complete:
            status = "typed_ir_complete"
        else:
            status = "typed_ir_incomplete"
        typed_ir = translated.get("typed_ir")
        interface = translated["interface"]
        source_target = self.library.assess_niagara_source_target(translated)
        return {
            "controller_id": controller["id"],
            "family": controller["family"],
            "validation_fixture": controller["validation_fixture"],
            "source_sha256": controller["source_sha256"],
            "status": status,
            "translation_succeeded": True,
            "oce_inspection_succeeded": bool(
                translated["engine_report"].get("oce_validation_succeeded", True)
            ),
            "validation_path": translated["engine_report"].get("engine", "unknown"),
            "typed_ir_complete": typed_ir_complete,
            "niagara_native_complete": niagara_native_complete,
            "niagara_source_target_complete": source_target["complete"],
            "niagara_source_delivery_mode": source_target["delivery_mode"],
            "generated_program_count": source_target["generated_program_count"],
            "niagara_source_target_blocker": source_target["blocker"],
            "engine_block_count": translated["engine_report"].get("block_count"),
            "typed_ir_block_count": len(typed_ir["blocks"]) if typed_ir else None,
            "public_input_count": len(interface["inputs"]),
            "public_output_count": len(interface["outputs"]),
            "required_job_parameters": [],
            "required_job_parameter_definitions": [],
            "unsupported_classes": lowering.get("unsupported_classes", []),
            "ir_exactness_blockers": lowering.get("exactness_blockers", []),
            "niagara_unsupported_classes": lowering.get("niagara_unsupported_classes", []),
            "niagara_exactness_blockers": lowering.get("niagara_exactness_blockers", []),
            "niagara_target_blockers": translated["niagara_target"]["blockers"],
            "duration_seconds": round(time.monotonic() - started, 3),
            "error": None,
        }

    @staticmethod
    def _parameters_required(
        controller: dict[str, Any],
        exc: G36RequiredParametersError,
        *,
        duration_seconds: float,
    ) -> dict[str, Any]:
        parameterization = exc.parameterization
        required = set(parameterization["remaining_required_parameters"])
        definitions = [
            parameter
            for parameter in parameterization["parameters"]
            if parameter["name"] in required
        ]
        return {
            "controller_id": controller["id"],
            "family": controller["family"],
            "validation_fixture": controller["validation_fixture"],
            "source_sha256": controller["source_sha256"],
            "status": "job_parameters_required",
            "translation_succeeded": True,
            "oce_inspection_succeeded": False,
            "validation_path": None,
            "typed_ir_complete": False,
            "niagara_native_complete": False,
            "niagara_source_target_complete": False,
            "niagara_source_delivery_mode": None,
            "generated_program_count": 0,
            "niagara_source_target_blocker": "job parameter values are required",
            "engine_block_count": None,
            "typed_ir_block_count": None,
            "public_input_count": None,
            "public_output_count": None,
            "required_job_parameters": sorted(required),
            "required_job_parameter_definitions": definitions,
            "unsupported_classes": [],
            "ir_exactness_blockers": [],
            "niagara_unsupported_classes": [],
            "niagara_exactness_blockers": [],
            "niagara_target_blockers": [],
            "duration_seconds": round(duration_seconds, 3),
            "error": None,
        }

    @staticmethod
    def _failure(
        controller: dict[str, Any],
        exc: Exception,
        *,
        duration_seconds: float,
    ) -> dict[str, Any]:
        pipeline_stage, diagnostic_counts = _classify_pipeline_failure(exc)
        return {
            "controller_id": controller["id"],
            "family": controller["family"],
            "validation_fixture": controller["validation_fixture"],
            "source_sha256": controller["source_sha256"],
            "status": "pipeline_error",
            "translation_succeeded": False,
            "oce_inspection_succeeded": False,
            "validation_path": None,
            "typed_ir_complete": False,
            "niagara_native_complete": False,
            "niagara_source_target_complete": False,
            "niagara_source_delivery_mode": None,
            "generated_program_count": 0,
            "niagara_source_target_blocker": "translation pipeline failed",
            "engine_block_count": None,
            "typed_ir_block_count": None,
            "public_input_count": None,
            "public_output_count": None,
            "required_job_parameters": [],
            "required_job_parameter_definitions": [],
            "unsupported_classes": [],
            "ir_exactness_blockers": [],
            "niagara_unsupported_classes": [],
            "niagara_exactness_blockers": [],
            "niagara_target_blockers": [],
            "duration_seconds": round(duration_seconds, 3),
            "pipeline_stage": pipeline_stage,
            "error": {
                "type": type(exc).__name__,
                "message": str(exc)[:8_000],
                "diagnostic_counts": diagnostic_counts,
            },
        }

    def _pipeline_identity(self, selected: list[dict[str, Any]]) -> dict[str, Any]:
        package_root = Path(__file__).resolve().parent
        code_paths = [
            package_root.parent / "domain.py",
            package_root.parent / "simulator.py",
            package_root / "g36_audit.py",
            package_root / "g36_library.py",
            package_root / "niagara_program_codegen.py",
            package_root / "cxf_importer.py",
            package_root / "cxf_connections.py",
            package_root / "cdl.py",
            package_root / "open_control_engine.py",
        ]
        payload = {
            "mapping_version": self.library.importer.mapping_version,
            "modelica_buildings_revision": _git_head(self.library.modelica_root),
            "modelica_buildings_worktree_sha256": _git_worktree_sha256(self.library.modelica_root),
            "modelica_json_revision": _git_head(self.library.translator.checkout),
            "modelica_json_worktree_sha256": _git_worktree_sha256(self.library.translator.checkout),
            "open_control_engine_revision": _git_head(self.library.engine.engine_checkout),
            "open_control_engine_worktree_sha256": _git_worktree_sha256(
                self.library.engine.engine_checkout
            ),
            "code_sha256": {path.name: _sha256(path) for path in code_paths},
            "controllers": {
                item["id"]: item["source_sha256"]
                for item in sorted(selected, key=lambda value: value["id"])
            },
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return {**payload, "fingerprint": hashlib.sha256(canonical).hexdigest()}

    @staticmethod
    def _resume_records(output_path: Path, pipeline: dict[str, Any]) -> dict[str, dict[str, Any]]:
        if not output_path.is_file():
            return {}
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if (
            existing.get("schema") != AUDIT_SCHEMA
            or existing.get("pipeline", {}).get("fingerprint") != pipeline["fingerprint"]
        ):
            return {}
        return {
            item["controller_id"]: item
            for item in existing.get("controllers", [])
            if isinstance(item, dict) and isinstance(item.get("controller_id"), str)
        }

    @staticmethod
    def _summary(
        selected: list[dict[str, Any]], records: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        def scope(validation_fixture: bool) -> dict[str, Any]:
            selected_ids = {
                item["id"]
                for item in selected
                if bool(item["validation_fixture"]) is validation_fixture
            }
            scoped = [
                record for controller_id, record in records.items() if controller_id in selected_ids
            ]
            scoped_statuses = Counter(record["status"] for record in scoped)
            return {
                "selected_controller_count": len(selected_ids),
                "completed_controller_count": len(scoped),
                "status_counts": dict(sorted(scoped_statuses.items())),
                "typed_ir_complete_count": sum(
                    bool(record["typed_ir_complete"]) for record in scoped
                ),
                "niagara_native_complete_count": sum(
                    bool(record["niagara_native_complete"]) for record in scoped
                ),
                "niagara_source_target_complete_count": sum(
                    bool(record["niagara_source_target_complete"]) for record in scoped
                ),
                "generated_program_source_complete_count": sum(
                    record.get("niagara_source_delivery_mode") == "generated_program_source"
                    for record in scoped
                ),
                "job_parameter_required_controller_count": sum(
                    record["status"] == "job_parameters_required" for record in scoped
                ),
                "oce_validated_count": sum(
                    bool(record["oce_inspection_succeeded"]) for record in scoped
                ),
                "reviewed_composite_count": sum(
                    record.get("validation_path") == "bactalk-reviewed-composite-lowering"
                    for record in scoped
                ),
            }

        status_counts = Counter(record["status"] for record in records.values())
        ir_blockers: Counter[str] = Counter()
        ir_exactness_blockers: Counter[str] = Counter()
        niagara_blockers: Counter[str] = Counter()
        niagara_exactness_blockers: Counter[str] = Counter()
        errors: Counter[str] = Counter()
        error_stages: Counter[str] = Counter()
        diagnostics: Counter[str] = Counter()
        required_job_parameters: Counter[str] = Counter()
        validation_paths: Counter[str] = Counter()
        for record in records.values():
            ir_blockers.update(record["unsupported_classes"])
            ir_exactness_blockers.update(record["ir_exactness_blockers"])
            niagara_blockers.update(record["niagara_unsupported_classes"])
            niagara_exactness_blockers.update(record["niagara_exactness_blockers"])
            required_job_parameters.update(record.get("required_job_parameters", []))
            if record.get("validation_path"):
                validation_paths[record["validation_path"]] += 1
            if record["error"]:
                errors[record["error"]["type"]] += 1
                error_stages[record.get("pipeline_stage", "pipeline_unknown")] += 1
                diagnostics.update(record["error"].get("diagnostic_counts", {}))
        selected_count = len(selected)
        completed_count = len(records)
        return {
            "selected_controller_count": selected_count,
            "completed_controller_count": completed_count,
            "complete": completed_count == selected_count,
            "validation_fixture_count": sum(bool(item["validation_fixture"]) for item in selected),
            "production_scope": scope(False),
            "validation_scope": scope(True),
            "status_counts": dict(sorted(status_counts.items())),
            "typed_ir_complete_count": sum(
                bool(record["typed_ir_complete"]) for record in records.values()
            ),
            "niagara_native_complete_count": sum(
                bool(record["niagara_native_complete"]) for record in records.values()
            ),
            "niagara_source_target_complete_count": sum(
                bool(record["niagara_source_target_complete"]) for record in records.values()
            ),
            "generated_program_source_complete_count": sum(
                record.get("niagara_source_delivery_mode") == "generated_program_source"
                for record in records.values()
            ),
            "job_parameter_required_controller_count": sum(
                record["status"] == "job_parameters_required" for record in records.values()
            ),
            "required_job_parameter_counts": dict(sorted(required_job_parameters.items())),
            "oce_validated_count": sum(
                bool(record["oce_inspection_succeeded"]) for record in records.values()
            ),
            "validation_path_counts": dict(sorted(validation_paths.items())),
            "ir_blocker_counts": dict(sorted(ir_blockers.items())),
            "ir_exactness_blocker_counts": dict(sorted(ir_exactness_blockers.items())),
            "niagara_blocker_counts": dict(sorted(niagara_blockers.items())),
            "niagara_exactness_blocker_counts": dict(sorted(niagara_exactness_blockers.items())),
            "pipeline_error_counts": dict(sorted(errors.items())),
            "pipeline_error_stage_counts": dict(sorted(error_stages.items())),
            "pipeline_diagnostic_counts": dict(sorted(diagnostics.items())),
        }

    @classmethod
    def _write(
        cls,
        output_path: Path,
        pipeline: dict[str, Any],
        selected: list[dict[str, Any]],
        records: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        document = {
            "schema": AUDIT_SCHEMA,
            "generated_at": datetime.now(UTC).isoformat(),
            "policy": (
                "This audit proves translation and target coverage against the pinned source "
                "pipeline. Niagara-native completion is not licensed-runtime qualification."
            ),
            "pipeline": pipeline,
            "summary": cls._summary(selected, records),
            "controllers": sorted(records.values(), key=lambda item: item["controller_id"]),
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_suffix(output_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(output_path)
        return document
