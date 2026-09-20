from __future__ import annotations

import io
import json
import tempfile
import zipfile
from pathlib import Path

from bactalk.domain import (
    AcceptanceCase,
    DataType,
    JobSpec,
    OutputExpectation,
    PointRole,
    PointSpec,
    RunStatus,
    SequenceSpec,
    TargetArtifactKind,
)
from bactalk.integrations.plant_controls_library import PlantControlsLibrary
from bactalk.repository import RunRepository
from bactalk.service import ApprovalRequiredError, WorkbenchService

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = ROOT / ".bactalk/plant-job-evidence.json"

PARAMETERS = {
    "have_heaWat": True,
    "have_chiWat": False,
    "is_priOnl": True,
    "have_valHpInlIso": True,
    "have_valHpOutIso": False,
    "have_pumPriHdr": True,
    "nHp": 2,
    "staEqu": [[1.0, 0.0], [1.0, 1.0]],
    "capHeaHp_nominal": [100.0, 100.0],
    "nSenDpHeaWatRem": 1,
    "have_senDpHeaWatRemWir": False,
    "cp_default": 1.0,
    "rho_default": 1.0,
    "dTHea": 2.0,
    "dtRunEna": 2.0,
    "dtReqDis": 2.0,
    "dtRunSta": 2.0,
    "dtOff": 2.0,
    "dtOffHp": 1.0,
    "dtVal": 1.0,
    "dtPri": 2.0,
    "dtSec": 2.0,
    "dtRunPumSta": 2.0,
    "dtRunFaiSafPumSta": 2.0,
    "dtRunFaiSafLowYPumSta": 2.0,
    "dtDel": 0.001,
    "dtHol": 2.0,
    "dtResHeaWat": 2.0,
    "TiCtlDpHeaWat": 10.0,
    "TiValMinByp": 1.0,
}

INPUTS = {
    "THeaWatPriRet": 0.0,
    "THeaWatPriSup": 20.0,
    "TOut": 280.0,
    "VHeaWatPri_flow": 10.0,
    "dpHeaWatLoc": 50.0,
    "dpHeaWatLocSet__1": 100.0,
    "nReqPlaHeaWat": 1.0,
    "nReqResHeaWat": 0.0,
    "u1Hp_actual__1": False,
    "u1Hp_actual__2": False,
    "u1PumHeaWatPri_actual__1": False,
    "u1PumHeaWatPri_actual__2": False,
    "u1SchHea": True,
}

EXPECTED_OUTPUTS = {
    "THeaWatSupHpSet__1": 323.15,
    "THeaWatSupHpSet__2": 323.15,
    "THeaWatSupSet": 323.15,
    "dpHeaWatRemSet__1": 100_000.0,
    "y1Hp__1": False,
    "y1Hp__2": False,
    "y1PumHeaWatPri__1": False,
    "y1PumHeaWatPri__2": False,
    "y1ValHeaWatHpInlIso__1": False,
    "y1ValHeaWatHpInlIso__2": False,
    "yPumHeaWatPriHdr": 0.0,
    "yValHeaWatMinByp": 1.0,
}


def _job() -> JobSpec:
    template = PlantControlsLibrary().job_template(
        "HeatPumps.AirToWater",
        parameters=PARAMETERS,
    )
    points = [
        PointSpec(
            name=item["name"],
            label=item["label"],
            data_type=DataType(item["data_type"]),
            role=(
                PointRole.SENSOR
                if item["source_interface_direction"] == "input"
                else PointRole.COMMAND
            ),
            default=item["default"],
            required=True,
        )
        for item in template["points"]
    ]
    expectations = [
        OutputExpectation(
            target=name,
            value=value,
            tolerance=1e-9 if not isinstance(value, bool) else 0.0,
        )
        for name, value in EXPECTED_OUTPUTS.items()
    ]
    return JobSpec(
        name="Air-to-water plant workbench contract",
        site="Isolated qualification lab",
        equipment_name="AWHP_Plant",
        sequence=SequenceSpec(
            family="LBNL_PLANT_CONTROLLER",
            version="Pinned LBNL Modelica Buildings source",
            library="plant_controls",
            controller_id="HeatPumps.AirToWater",
            parameters=PARAMETERS,
        ),
        points=points,
        acceptance_tests=[
            AcceptanceCase(
                name="safe first-scan plant state",
                inputs=INPUTS,
                expectations=expectations,
            )
        ],
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="bactalk-plant-job-") as temporary:
        service = WorkbenchService(RunRepository(Path(temporary) / "runs"))
        record = service.create_run(_job())
        assert record.status == RunStatus.READY_FOR_REVIEW
        assert record.target_artifact_kind == (
            TargetArtifactKind.NIAGARA_PROGRAM_SOURCE_PACKAGE
        )
        assert record.bog_path is None
        assert record.program_package_path == record.target_artifact_path
        assert record.program_package_path is not None
        try:
            service.export_path(record.id)
        except ApprovalRequiredError:
            approval_gate_passed = True
        else:
            raise AssertionError("unapproved plant package was exportable")

        package_bytes = Path(record.program_package_path).read_bytes()
        with zipfile.ZipFile(io.BytesIO(package_bytes)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            graph = json.loads(archive.read("control-graph.json"))
            wiring = json.loads(archive.read("wiring-plan.json"))
        assert manifest["controller_id"] == "HeatPumps.AirToWater"
        assert manifest["licensed_workbench_compile_required"] is True
        assert manifest["runtime_qualified"] is False
        assert manifest["live_deployment_allowed"] is False
        assert len(manifest["programs"]) == 59
        assert len(graph["blocks"]) == 480
        assert len(wiring["links"]) == len(graph["links"])

        approved = service.approve(record.id, "Plant contract harness")
        exported = service.export_path(record.id)
        assert approved.status == RunStatus.APPROVED
        assert exported.read_bytes() == package_bytes

        evidence = {
            "schema": "bactalk.plant-job-evidence/v1",
            "passed": True,
            "controller_id": "HeatPumps.AirToWater",
            "run_status_before_approval": "ready_for_review",
            "approval_gate_passed": approval_gate_passed,
            "target_artifact_kind": record.target_artifact_kind.value,
            "artifact_sha256": record.artifact_sha256,
            "point_count": len(record.job.points),
            "acceptance_output_count": len(EXPECTED_OUTPUTS),
            "acceptance_passed": True,
            "typed_block_count": len(graph["blocks"]),
            "typed_link_count": len(graph["links"]),
            "generated_program_count": len(manifest["programs"]),
            "licensed_workbench_compile_required": True,
            "runtime_qualified": False,
            "live_deployment_allowed": False,
        }
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
