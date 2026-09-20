from __future__ import annotations

import json
from pathlib import Path

from bactalk.integrations.g36_audit import AUDIT_SCHEMA, G36CoverageAuditor

CONTROLLERS = [
    "AHUs.MultiZone.VAV.SetPoints.SupplySignals",
    "TerminalUnits.ParallelFanVVF.Subsequences.Overrides",
]


def test_g36_coverage_audit_is_source_bound_and_resumable(tmp_path: Path) -> None:
    output = tmp_path / "g36-audit.json"
    auditor = G36CoverageAuditor()

    first = auditor.run(output, controller_ids=CONTROLLERS, workers=2)
    second = auditor.run(output, controller_ids=CONTROLLERS, workers=2)

    assert first["schema"] == AUDIT_SCHEMA
    assert first["summary"] == {
        "selected_controller_count": 2,
        "completed_controller_count": 2,
        "complete": True,
        "validation_fixture_count": 0,
        "production_scope": {
            "selected_controller_count": 2,
            "completed_controller_count": 2,
            "status_counts": {
                "niagara_native_complete": 1,
                "typed_ir_complete": 1,
            },
            "typed_ir_complete_count": 2,
            "niagara_native_complete_count": 1,
            "niagara_source_target_complete_count": 2,
            "generated_program_source_complete_count": 1,
            "job_parameter_required_controller_count": 0,
            "oce_validated_count": 2,
            "reviewed_composite_count": 0,
        },
        "validation_scope": {
            "selected_controller_count": 0,
            "completed_controller_count": 0,
            "status_counts": {},
            "typed_ir_complete_count": 0,
            "niagara_native_complete_count": 0,
            "niagara_source_target_complete_count": 0,
            "generated_program_source_complete_count": 0,
            "job_parameter_required_controller_count": 0,
            "oce_validated_count": 0,
            "reviewed_composite_count": 0,
        },
        "status_counts": {
            "niagara_native_complete": 1,
            "typed_ir_complete": 1,
        },
        "typed_ir_complete_count": 2,
        "niagara_native_complete_count": 1,
        "niagara_source_target_complete_count": 2,
        "generated_program_source_complete_count": 1,
        "job_parameter_required_controller_count": 0,
        "required_job_parameter_counts": {},
        "oce_validated_count": 2,
        "validation_path_counts": {"open-control-engine": 2},
        "ir_blocker_counts": {},
        "ir_exactness_blocker_counts": {},
        "niagara_blocker_counts": {
            "Buildings.Controls.OBC.CDL.Reals.PIDWithReset": 1,
        },
        "niagara_exactness_blocker_counts": {},
        "pipeline_error_counts": {},
        "pipeline_error_stage_counts": {},
        "pipeline_diagnostic_counts": {},
    }
    assert len(first["pipeline"]["fingerprint"]) == 64
    assert first["pipeline"]["controllers"] == second["pipeline"]["controllers"]
    assert second["summary"] == first["summary"]
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["summary"]["complete"] is True
    assert [item["controller_id"] for item in persisted["controllers"]] == sorted(CONTROLLERS)
    assert all(item["niagara_source_target_complete"] for item in persisted["controllers"])


def test_g36_coverage_audit_classifies_oce_diagnostics() -> None:
    class FakeControllerError(RuntimeError):
        pass

    exc = FakeControllerError(
        "Open Control Engine rejected request: CXF validation failed\n"
        "error|grounding-failed|urn:test|parameter has no value\n"
        "error|grounding-failed|urn:test2|parameter has no value\n"
        "warning|undriven-boundary-output|urn:test3|missing driver"
    )
    record = G36CoverageAuditor._failure(
        {
            "id": "Synthetic.Controller",
            "family": "Synthetic",
            "validation_fixture": False,
            "source_sha256": "0" * 64,
        },
        exc,
        duration_seconds=0.1,
    )

    assert record["pipeline_stage"] == "cxf_validation"
    assert record["error"]["diagnostic_counts"] == {
        "error:grounding-failed": 2,
        "warning:undriven-boundary-output": 1,
    }


def test_g36_audit_separates_missing_job_values_from_pipeline_errors(
    tmp_path: Path,
) -> None:
    result = G36CoverageAuditor().run(
        tmp_path / "parameters.json",
        controller_ids=["AHUs.MultiZone.VAV.SetPoints.ReturnFanAirflowTracking"],
        resume=False,
    )

    record = result["controllers"][0]
    assert record["status"] == "job_parameters_required"
    assert record["required_job_parameters"] == ["difFloSet"]
    assert record["required_job_parameter_definitions"][0]["unit"] == "unit:M3-PER-SEC"
    assert result["summary"]["pipeline_error_counts"] == {}
    assert result["summary"]["job_parameter_required_controller_count"] == 1
