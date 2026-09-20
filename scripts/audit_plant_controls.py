from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bactalk.integrations.plant_controls_library import PlantControlsLibrary

PROVEN_PARAMETERS: dict[str, dict[str, Any]] = {
    "HeatRecoveryChillers.Controller": {
        "have_reqFlo": True,
        "TChiWatSup_min": 280.0,
        "THeaWatSup_max": 330.0,
        "COPHea_nominal": 4.0,
        "capCoo_min": 10_000.0,
        "capHea_min": 12_000.0,
        "cp_default": 4_180.0,
        "rho_default": 1_000.0,
        "dtMea": 3.0,
        "dtRun": 2.0,
        "dtLoa": 2.0,
        "dtTem1": 2.0,
        "dtTem2": 1.0,
    },
    "Enabling.Enable": {
        "typ": "Buildings.Templates.Plants.Controls.Types.Application.Heating",
        "have_inpSch": True,
        "TOutLck": 290.0,
        "dTOutLck": 1.0,
        "nReqIgn": 0,
        "dtRun": 2.0,
        "dtReq": 2.0,
    },
    "HeatRecoveryChillers.ModeControl": {"COPHea_nominal": 4.0},
    "HeatRecoveryChillers.Enable": {
        "TChiWatSup_min": 280.0,
        "THeaWatSup_max": 330.0,
        "capCoo_min": 10_000.0,
        "capHea_min": 12_000.0,
        "dtRun": 2.0,
        "dtLoa": 2.0,
        "dtTem1": 2.0,
        "dtTem2": 1.0,
    },
    "Utilities.HoldReal": {"dtHol": 3.0},
    "MinimumFlow.Setpoint": {
        "nEqu": 3,
        "V_flow_nominal": [0.1, 0.2, 0.3],
        "V_flow_min": [0.02, 0.06, 0.09],
    },
    "MinimumFlow.Controller": {
        "nEqu": 3,
        "nEna": 2,
        "V_flow_nominal": [0.1, 0.2, 0.3],
        "V_flow_min": [0.02, 0.06, 0.09],
        "have_valInlIso": False,
        "have_valOutIso": False,
        "k": 1.0,
        "Ti": 1.0,
    },
    "MinimumFlow.ControllerDualMode": {
        "have_heaWat": True,
        "have_chiWat": True,
        "have_pumChiWatPri": False,
        "have_valInlIso": False,
        "have_valOutIso": False,
        "nEqu": 3,
        "nEnaHeaWat": 3,
        "nEnaChiWat": 3,
        "VHeaWat_flow_nominal": [0.1, 0.2, 0.3],
        "VHeaWat_flow_min": [0.02, 0.06, 0.09],
        "VChiWat_flow_nominal": [0.1, 0.2, 0.3],
        "VChiWat_flow_min": [0.01, 0.04, 0.06],
        "k": 1.0,
        "Ti": 1.0,
    },
    "Setpoints.PlantReset": {
        "nSenDpRem": 2,
        "dpSet_max": [100000.0, 120000.0],
        "TSup_nominal": 279.15,
        "TSupSetLim": 285.15,
        "dtDel": 0.001,
        "dtRes": 10.0,
        "dtHol": 25.0,
    },
    "Pumps.Generic.ResetLocalDifferentialPressure": {
        "dpLocSet_min": 30000.0,
        "dpLocSet_max": 100000.0,
        "k": 1.0,
        "Ti": 60.0,
    },
    "Pumps.Generic.ControlDifferentialPressure": {
        "have_senDpRemWir": False,
        "nPum": 2,
        "nSenDpRem": 2,
        "k": 1.0,
        "Ti": 10.0,
    },
    "Utilities.CountTrue": {"nin": 4},
    "Pumps.Primary.DisableDedicated": {"have_reqFlo": False, "dtOff": 3.0},
    "StagingRotation.FailsafeCondition": {
        "typ": "Buildings.Templates.Plants.Controls.Types.Application.Heating",
        "have_pumSec": False,
        "dT": 2.0,
        "dtPri": 3.0,
    },
    "StagingRotation.StageCompletion": {"nin": 3},
    "StagingRotation.SortRuntime": {
        "nin": 4,
        "idxEquAlt": [2, 3, 4],
        "runTim_start": [2.0, 3.0, 4.0],
    },
    "Pumps.Generic.StagingHeaderedDeltaP": {
        "nPum": 3,
        "nSenDp": 2,
        "V_flow_nominal": 3.0,
        "dtRun": 2.0,
        "dtRunFaiSaf": 2.0,
        "dtRunFaiSafLowY": 2.0,
        "dVOffUp": 0.03,
        "dVOffDow": 0.03,
        "dpOff": 10.0,
        "yUp": 0.9,
        "yDow": 0.4,
    },
    "StagingRotation.StageChangeCommand": {
        "typ": "Buildings.Templates.Plants.Controls.Types.Application.Heating",
        "have_pumSec": True,
        "have_inpPlrSta": False,
        "plrSta": 0.8,
        "staEqu": [[1.0, 0.0], [1.0, 1.0]],
        "capEqu": [100.0, 100.0],
        "dtRun": 2.0,
        "dtMea": 0.001,
        "cp_default": 1.0,
        "rho_default": 1.0,
        "dT": 2.0,
        "dtPri": 2.0,
        "dtSec": 2.0,
    },
    "Pumps.Generic.StagingHeadered": {
        "is_pri": True,
        "is_hdr": True,
        "is_ctlDp": True,
        "have_valInlIso": True,
        "have_valOutIso": False,
        "nEqu": 2,
        "nPum": 2,
        "nSenDp": 1,
        "V_flow_nominal": 2.0,
        "dtRun": 2.0,
        "dtRunFaiSaf": 2.0,
        "dtRunFaiSafLowY": 2.0,
        "dVOffUp": 0.03,
        "dVOffDow": 0.03,
        "dpOff": 10.0,
        "yUp": 0.9,
        "yDow": 0.4,
    },
    "Pumps.Primary.VariableSpeed": {
        "have_heaWat": True,
        "have_chiWat": True,
        "have_pumPriCtlDp": True,
        "have_pumPriHdr": True,
        "nEqu": 2,
        "nPumHeaWatPri": 2,
        "nPumChiWatPri": 2,
        "nSenDpHeaWatRem": 1,
        "nSenDpChiWatRem": 1,
        "have_senDpHeaWatRemWir": False,
        "have_senDpChiWatRemWir": True,
        "kCtlDpHeaWat": 1.0,
        "TiCtlDpHeaWat": 10.0,
        "kCtlDpChiWat": 1.0,
        "TiCtlDpChiWat": 10.0,
    },
    "HeatPumps.AirToWater": {
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
    },
    "StagingRotation.EquipmentEnable": {
        "staEqu": [
            [1.0, 0.0, 0.0],
            [1.0, 0.5, 0.5],
            [1.0, 1.0, 1.0],
        ]
    },
    "Utilities.FirstTrueIndex": {"nin": 4},
    "Utilities.LastTrueIndex": {"nin": 4},
    "Utilities.Initialization": {"yIni": False},
    "Utilities.TimerWithReset": {"t": 3.0},
    "Utilities.MultiMaxInteger": {"nin": 4},
    "Utilities.MultiMinInteger": {"nin": 4},
    "Utilities.TrueArrayConditional": {"nin": 5, "nout": 4},
    "Utilities.StageIndex": {"nSta": 4, "dtRun": 3.0, "have_inpAva": True},
    "Utilities.PlaceholderLogical": {"have_inp": True},
    "Utilities.PlaceholderReal": {"have_inp": True},
    "Utilities.PlaceholderInteger": {"have_inp": True},
    "StagingRotation.LoadAverage": {
        "typ": "Buildings.Templates.Plants.Controls.Types.Application.Heating",
        "cp_default": 4.0,
        "rho_default": 2.0,
        "dtMea": 3.0,
    },
    "Pumps.Primary.EnableLeadHeadered": {
        "typCon": (
            "Buildings.Templates.Plants.Controls.Types.EquipmentConnection.Parallel"
        ),
        "typValIso": "Buildings.Templates.Plants.Controls.Types.Actuator.TwoPosition",
        "nValIso": 3,
    },
    "StagingRotation.StageAvailability": {
        "staEqu": [
            [1.0, 0.0, 0.0],
            [1.0, 0.5, 0.5],
            [1.0, 1.0, 1.0],
        ]
    },
    "StagingRotation.EquipmentAvailability": {
        "have_heaWat": True,
        "have_chiWat": True,
        "dtOff": 3.0,
    },
    "StagingRotation.EventSequencing": {
        "have_heaWat": True,
        "have_chiWat": False,
        "have_valInlIso": True,
        "have_valOutIso": True,
        "have_pumHeaWatPri": True,
        "have_pumChiWatPri": False,
        "have_pumHeaWatSec": False,
        "have_pumChiWatSec": False,
        "dtVal": 2.0,
        "dtOff": 3.0,
    },
}


def audit() -> dict[str, Any]:
    library = PlantControlsLibrary()
    catalog = library.catalog()
    records = []
    for controller in catalog["controllers"]:
        if controller["validation_fixture"]:
            continue
        controller_id = controller["id"]
        parameters = PROVEN_PARAMETERS.get(controller_id)
        if parameters is not None:
            try:
                translation = library.translate(controller_id, parameters=parameters)
                target = library.assess_niagara_source_target(translation)
                status = "proven"
                detail = {
                    "product_status": translation["product_status"],
                    "typed_ir_block_count": len(translation["typed_ir"]["blocks"]),
                    "engine": translation["engine_report"]["engine"],
                    "target": target,
                    "parameter_names": sorted(parameters),
                }
            except Exception as exc:  # fail closed in retained audit evidence
                status = "proven_configuration_failed"
                detail = {"error_type": type(exc).__name__, "error": str(exc)}
        else:
            try:
                parameter_schema = library.parameter_schema(controller_id)
                parameterization = parameter_schema["parameterization"]
                required = list(parameterization["remaining_required_parameters"])
                connector_dimensions = [
                    parameter["name"]
                    for parameter in parameterization["parameters"]
                    if parameter["name"] in {"nEqu", "nin"}
                    and parameter["value"] == 0
                    and parameter["overridable"]
                ]
                required.extend(
                    name for name in connector_dimensions if name not in required
                )
                if required:
                    status = "job_parameters_required"
                    detail = {
                        "required_parameters": sorted(required),
                        "connector_sizing_parameters": sorted(connector_dimensions),
                    }
                else:
                    translation = library.translate(controller_id)
                    status = "translatable_not_product_qualified"
                    detail = {
                        "typed_ir_complete": translation["lowering"]["translatable"],
                        "target": library.assess_niagara_source_target(translation),
                    }
            except Exception as exc:
                status = "pipeline_gap"
                detail = {"error_type": type(exc).__name__, "error": str(exc)}
        records.append(
            {
                "id": controller_id,
                "family": controller["family"],
                "source_sha256": controller["source_sha256"],
                "status": status,
                **detail,
            }
        )
    counts = Counter(item["status"] for item in records)
    passed = counts["proven_configuration_failed"] == 0
    return {
        "schema": "bactalk.plant-controls-audit/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "passed": passed,
        "policy": (
            "Only status=proven is a current product claim. Parameter-required, unqualified, "
            "and pipeline-gap models remain non-deployable source references."
        ),
        "source": catalog["source"],
        "license": catalog["license"],
        "production_control_model_count": len(records),
        "status_counts": dict(sorted(counts.items())),
        "records": records,
        "licensed_niagara_runtime_qualified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".bactalk/plant-controls-audit.json"),
    )
    arguments = parser.parse_args()
    report = audit()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = arguments.output.with_suffix(arguments.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(arguments.output)
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "output": str(arguments.output),
                "production_control_model_count": report[
                    "production_control_model_count"
                ],
                "status_counts": report["status_counts"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
