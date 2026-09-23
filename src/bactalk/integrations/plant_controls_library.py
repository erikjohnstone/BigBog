from __future__ import annotations

import copy
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from bactalk.domain import Block, BlockKind, ControlGraph, Link
from bactalk.integrations.cxf_importer import ExecutionProfile
from bactalk.integrations.g36_library import G36Library, G36RequiredParametersError
from bactalk.integrations.open_control_engine import OpenControlEngine

_PROVEN_CONTROLLERS = {
    "Enabling.Enable": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "direct pinned enable-network qualification for heating and cooling; software-"
            "input and daily internal schedule topologies; request and outdoor-air lockout "
            "hysteresis; minimum enabled/disabled dwell and low-request delay trajectories; "
            "exact typed state-machine IR; and complete Niagara ProgramObject source"
        ),
    },
    "HeatRecoveryChillers.ModeControl": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "direct pinned COP-derived load-comparison and mode-hold qualification; exact "
            "1 W Less hysteresis boundaries, gated mode changes, heating/cooling supply-"
            "setpoint selection trajectories, exact typed IR, and complete Niagara "
            "ProgramObject source"
        ),
    },
    "HeatRecoveryChillers.Enable": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "direct pinned enable-network qualification; plant and load qualification "
            "timers; exact high/low load hysteresis; HRC falling-edge cycling shutdown; "
            "mode-specific two-level leaving-temperature trips; clear-dominant latch; "
            "mode-setting edge pulse; five-second HRC enable delay; typed state-machine "
            "IR; and complete Niagara ProgramObject source"
        ),
    },
    "HeatRecoveryChillers.Controller": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "source-specialized composition of cooling/heating rolling-load calculations, "
            "qualified HRC enable and mode recurrences, guarded previous-mode feedback, and "
            "both dedicated-pump shutdown networks; optional network flow-request topology; "
            "complete typed wiring graph; end-to-end trajectories; and deterministic Niagara "
            "ProgramObject packages"
        ),
    },
    "Utilities.HoldReal": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "modelica-json translation, Open Control Engine validation and trajectory, "
            "typed IR lowering, and Niagara ProgramObject package generation"
        ),
    },
    "Setpoints.PlantReset": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "parameter-bound array scalarization, reviewed composite lowering, expanded-source "
            "Open Control Engine hold trajectory, typed IR execution, and Niagara "
            "ProgramObject package generation"
        ),
    },
    "MinimumFlow.Setpoint": {
        "status": "exact_ir_stock_niagara",
        "evidence": (
            "connector-sized array binding, array scalarization, Open Control Engine "
            "validation and unequal-equipment execution, exact typed IR, and qualified "
            "stock Niagara target assessment"
        ),
    },
    "MinimumFlow.Controller": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "source-specialized pinned setpoint and bypass-PI block network; pump-status, "
            "inlet-valve, outlet-valve, and combined-valve enable topologies; strict unequal-"
            "equipment and connector dimensions; disable/enable/reset/modulation trajectories; "
            "and complete Niagara PIDWithReset ProgramObject package"
        ),
    },
    "MinimumFlow.ControllerDualMode": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "source-specialized composition of the pinned heating- and chilled-water "
            "minimum-flow controllers; heating-only, cooling-only, separate-pump, common-"
            "pump, and inlet/outlet isolation-valve topologies; equipment mode filtering; "
            "strict connector dimensions; independent disable/enable/reset/modulation "
            "trajectories; and complete Niagara PIDWithReset ProgramObject packages"
        ),
    },
    "Pumps.Generic.ResetLocalDifferentialPressure": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "parameter-bound Open Control Engine PI trajectory, exact typed IR, and exact "
            "PID Niagara ProgramObject package generation"
        ),
    },
    "Pumps.Generic.ControlDifferentialPressure": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "local and hardwired-remote sensor topologies, fixed pump/sensor array "
            "scalarization, exact source-composite PIDWithEnable expansion, disabled/enable/"
            "reenable and maximum-loop trajectories, and complete Niagara PIDWithReset "
            "ProgramObject packages"
        ),
    },
    "Utilities.CountTrue": {
        "status": "exact_ir_stock_niagara",
        "evidence": (
            "connector-sized Boolean array scalarization, Open Control Engine execution, "
            "exact typed IR, and qualified stock Niagara target assessment"
        ),
    },
    "Pumps.Primary.DisableDedicated": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "both optional flow-request variants, source-bound first-scan initialization, "
            "typed IR timer/latch execution trajectories, and exact Niagara ProgramObject "
            "package generation"
        ),
    },
    "StagingRotation.FailsafeCondition": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "heating/cooling enum grounding, primary-only and primary-secondary conditional "
            "topologies, source-bound placeholder and TimerWithReset lowering, typed reset/"
            "threshold trajectories, and exact Niagara ProgramObject package generation"
        ),
    },
    "Utilities.FirstTrueIndex": {
        "status": "exact_ir_stock_niagara",
        "evidence": (
            "connector-sized Boolean vector scalarization, one-based range-comprehension "
            "grounding, integer minimum reduction, Open Control Engine execution, and "
            "qualified stock Niagara target assessment"
        ),
    },
    "Utilities.LastTrueIndex": {
        "status": "exact_ir_stock_niagara",
        "evidence": (
            "connector-sized Boolean vector scalarization, one-based range-comprehension "
            "grounding, integer maximum reduction, Open Control Engine execution, and "
            "qualified stock Niagara target assessment"
        ),
    },
    "Utilities.Initialization": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "direct pinned initial() equation lowering, deterministic first-scan and "
            "pass-through trajectories, exact typed IR, and Niagara ProgramObject source"
        ),
    },
    "Utilities.TimerWithReset": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "direct pinned when-equation lowering, input/reset/threshold recurrence vectors, "
            "exact typed IR, and Niagara ProgramObject source"
        ),
    },
    "Utilities.MultiMaxInteger": {
        "status": "exact_ir_stock_niagara",
        "evidence": (
            "direct pinned max(u) equation lowering, strict integer vector validation, "
            "deterministic reduction vectors, and qualified stock Niagara target assessment"
        ),
    },
    "Utilities.MultiMinInteger": {
        "status": "exact_ir_stock_niagara",
        "evidence": (
            "direct pinned min(u) equation lowering, strict integer vector validation, "
            "deterministic reduction vectors, and qualified stock Niagara target assessment"
        ),
    },
    "Utilities.TrueArrayConditional": {
        "status": "exact_ir_stock_niagara",
        "evidence": (
            "direct pinned priority-loop algorithm lowering, strict integer input and "
            "bounded array validation, duplicate/out-of-range trajectory vectors, and "
            "qualified stock Niagara target assessment"
        ),
    },
    "Utilities.PlaceholderLogical": {
        "status": "exact_ir_stock_niagara",
        "evidence": (
            "all input, placeholder-input, and constant compile-time topology branches; "
            "strict Boolean typing; deterministic trajectories; and stock Niagara compilation"
        ),
    },
    "Utilities.PlaceholderReal": {
        "status": "exact_ir_stock_niagara",
        "evidence": (
            "all input, placeholder-input, and constant compile-time topology branches; "
            "finite Real typing; deterministic trajectories; and stock Niagara compilation"
        ),
    },
    "Utilities.PlaceholderInteger": {
        "status": "exact_ir_stock_niagara",
        "evidence": (
            "all input, placeholder-input, and constant compile-time topology branches; "
            "strict Integer typing; deterministic trajectories; and stock Niagara compilation"
        ),
    },
    "StagingRotation.LoadAverage": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "heating and cooling enum-grounded OCE trajectories, exact density/specific-"
            "heat load arithmetic, typed IR, and Niagara MovingAverage ProgramObject source"
        ),
    },
    "Pumps.Primary.EnableLeadHeadered": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "parallel/series and two-position/modulating valve topologies, enum/Boolean "
            "conditional pruning before array scalarization, OCE latch trajectories at "
            "0%/99% boundaries, exact typed IR, and Niagara Latch ProgramObject source"
        ),
    },
    "StagingRotation.StageAvailability": {
        "status": "exact_ir_stock_niagara",
        "evidence": (
            "strict staging-matrix contract, source-specialized required/alternate equipment "
            "logic, exhaustive equipment-availability truth table, exact typed IR, and "
            "stock Niagara compilation"
        ),
    },
    "StagingRotation.EventSequencing": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "compile-time heating/cooling, valve, and primary/secondary pump topology "
            "matrix; inactive placeholder-port pruning before array scalarization; valve-open/"
            "pump-prove enable delay and shutdown hold trajectories; exact typed timer/latch "
            "IR; and complete Niagara ProgramObject packages"
        ),
    },
    "StagingRotation.EquipmentAvailability": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "direct pinned StateGraph qualification for heating-only, cooling-only, and "
            "reversible heating/cooling equipment; active-mode exclusion, unavailable-state "
            "recovery, and minimum off-time trajectories; exact typed state-machine IR; "
            "and complete Niagara ProgramObject source"
        ),
    },
    "StagingRotation.StageCompletion": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "direct pinned change/pre/latch network qualification; connector-sized command "
            "and status vectors encoded losslessly as bounded masks; simultaneous and delayed "
            "command/status trajectories; exact in-progress and one-scan completion outputs; "
            "typed state-machine IR; and complete Niagara ProgramObject source"
        ),
    },
    "StagingRotation.EquipmentEnable": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "source-specialized staging-matrix row selection; fixed and lead/lag alternate "
            "equipment selection by supplied runtime order; availability-driven recompute; "
            "stage-zero, stage-change, hold, and unavailable-replacement trajectories; strict "
            "matrix/index dimensions; typed stateful IR; and complete Niagara source package"
        ),
    },
    "Utilities.StageIndex": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "direct pinned StateGraph qualification; stage-zero lead enable; minimum-runtime-"
            "gated stage-up, stage-down, and disable transitions; unavailable-stage skipping "
            "and immediate higher-stage recovery; bounded availability-mask IR; deterministic "
            "trajectories; and complete Niagara ProgramObject source"
        ),
    },
    "StagingRotation.SortRuntime": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "direct pinned runtime-weighting and Modelica shell-sort qualification; "
            "connector extraction for the declared alternate equipment; exact accumulating "
            "staging and lifetime runtimes; available-on, available-off, and unavailable "
            "ordering trajectories; strict index/initial-runtime contracts; typed IR; and "
            "complete Niagara ProgramObject source packages"
        ),
    },
    "Pumps.Generic.StagingHeaderedDeltaP": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "source-specialized headered variable-speed pump staging network; exact "
            "efficiency and differential-pressure failsafe thresholds; per-sensor and speed "
            "timers reset by pump-status changes; source latches and prior-cause feedback; "
            "one-scan up/down commands; typed arrays; deterministic trajectories; and complete "
            "Niagara source packages"
        ),
    },
    "StagingRotation.StageChangeCommand": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "source-specialized plant staging command network; exact rolling load, stage and "
            "next-lower-stage capacity selection, load hold during transitions, strict source "
            "comparison hysteresis, resettable efficiency timers, primary and optional "
            "secondary temperature failsafes, heating/cooling polarity, deterministic "
            "trajectories, and complete Niagara source packages"
        ),
    },
    "Pumps.Generic.StagingHeadered": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "source-specialized parent pump-bank composition for primary headered and "
            "differential-pressure-controlled secondary headered topologies; exact lead "
            "enable latching, status feedback, runtime rotation, staged pump selection, "
            "equipment-count and differential-pressure staging paths, conditional point "
            "interfaces, deterministic trajectories, and complete Niagara source packages"
        ),
    },
    "Pumps.Primary.VariableSpeed": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "source-specialized heating, chilled-water, and shared reversible-loop pump "
            "speed composition; fixed-speed and local/remote differential-pressure control; "
            "headered and dedicated command gating; exact common-pump mode capture and "
            "status filtering; conditional point interfaces, deterministic trajectories, "
            "and complete stock or generated Niagara targets"
        ),
    },
    "HeatPumps.AirToWater": {
        "status": "exact_ir_generated_program_source",
        "evidence": (
            "source-specialized whole-plant composition for heating-only, cooling-only, "
            "and reversible air-to-water heat-pump plants; primary-only and primary-"
            "secondary hydronic topologies; fixed and alternate equipment staging; mode "
            "enable, runtime rotation, stage completion, plant reset, valve and pump "
            "sequencing, differential-pressure control, minimum-flow bypass, and optional "
            "sidestream heat-recovery-chiller branches; strict topology/dimension contracts, "
            "deterministic end-to-end trajectories, and complete Niagara source packages"
        ),
    },
}

_SOURCE_EQUATION_CONTROLLERS = frozenset(
    {
        "Utilities.Initialization",
        "Utilities.MultiMaxInteger",
        "Utilities.MultiMinInteger",
        "Utilities.TimerWithReset",
        "Utilities.TrueArrayConditional",
        "Utilities.PlaceholderLogical",
        "Utilities.PlaceholderReal",
        "Utilities.PlaceholderInteger",
        "StagingRotation.StageAvailability",
        "MinimumFlow.Controller",
        "MinimumFlow.ControllerDualMode",
        "StagingRotation.EquipmentAvailability",
        "StagingRotation.EquipmentEnable",
        "StagingRotation.StageCompletion",
        "Utilities.StageIndex",
        "StagingRotation.SortRuntime",
        "Pumps.Generic.StagingHeaderedDeltaP",
        "StagingRotation.StageChangeCommand",
        "Pumps.Generic.StagingHeadered",
        "Pumps.Primary.VariableSpeed",
        "HeatPumps.AirToWater",
        "Enabling.Enable",
        "HeatRecoveryChillers.Controller",
        "HeatRecoveryChillers.Enable",
        "HeatRecoveryChillers.ModeControl",
    }
)

_PLACEHOLDER_CONTROLLERS = frozenset(
    {
        "Utilities.PlaceholderLogical",
        "Utilities.PlaceholderReal",
        "Utilities.PlaceholderInteger",
    }
)


class PlantControlsLibrary(G36Library):
    """Product adapter for LBNL's Buildings.Templates.Plants control corpus.

    Cataloging a source model is deliberately separate from supporting it as a
    deployable controller. ``_PROVEN_CONTROLLERS`` is the small, explicit set
    that has completed BACTalk's current translation/execution/source-package
    path; every other source remains visible for engineering work without being
    advertised as production-capable.
    """

    def __init__(
        self,
        modelica_root: Path = Path(".vendor/modelica-buildings"),
        modelica_json_root: Path = Path(".vendor/modelica-json"),
        *,
        engine: OpenControlEngine | None = None,
    ):
        super().__init__(
            modelica_root=modelica_root,
            modelica_json_root=modelica_json_root,
            engine=engine,
        )
        self.g36_root = (self.modelica_root / "Buildings/Templates/Plants/Controls").resolve()

    def catalog(self) -> dict[str, Any]:
        controllers = []
        for record in self._controllers().values():
            proof = _PROVEN_CONTROLLERS.get(record["id"])
            controllers.append(
                {
                    **record,
                    "product_status": (
                        proof["status"] if proof is not None else "source_catalog_only"
                    ),
                    "product_evidence": proof["evidence"] if proof is not None else None,
                }
            )
        family_counts = Counter(item["family"] for item in controllers)
        production_models = [item for item in controllers if not item["validation_fixture"]]
        return {
            "schema": "bactalk.plant-controls-library/v1",
            "source": "LBNL Modelica Buildings Templates.Plants.Controls",
            "license": "Revised BSD-3-Clause",
            "source_model_count": len(controllers),
            "production_control_model_count": len(production_models),
            "validation_fixture_count": sum(item["validation_fixture"] for item in controllers),
            "proven_controller_count": sum(
                item["product_status"] != "source_catalog_only" for item in production_models
            ),
            "family_counts": dict(sorted(family_counts.items())),
            "controllers": controllers,
            "execution_path": "modelica-json CXF -> Open Control Engine -> typed IR",
            "support_policy": (
                "Source presence is not deployability. Only models with a non-catalog "
                "product_status have completed the stated evidence path."
            ),
            "licensed_niagara_runtime_qualified": False,
        }

    def _source_bundle(
        self,
        controller_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
        controller, document, class_documents = super()._source_bundle(controller_id)
        # These plant utilities already have source-bound, trajectory-qualified
        # exact adapters in CxfImporter. Expanding their class boundary as well
        # duplicates parent and child connector drives in modelica-json CXF.
        # Keep them opaque here so the established adapter remains authoritative;
        # unrelated plant composites and all G36 composites still use the general
        # hierarchy assembler.
        exact_adapter_suffixes = (
            ".Utilities.Initialization",
            ".Utilities.TimerWithReset",
            ".Utilities.PlaceholderLogical",
            ".Utilities.PlaceholderReal",
            ".Utilities.PlaceholderInteger",
            ".Utilities.PIDWithEnable",
            ".ASHRAE.G36.Generic.TrimAndRespond",
        )
        retained = {
            class_id: value
            for class_id, value in class_documents.items()
            if not class_id.removeprefix("ex:").endswith(exact_adapter_suffixes)
        }
        return controller, document, retained

    def parameter_schema(self, controller_id: str) -> dict[str, Any]:
        if controller_id in _SOURCE_EQUATION_CONTROLLERS:
            return self._source_equation_parameter_schema(controller_id, {})
        result = super().parameter_schema(controller_id)
        result["schema"] = "bactalk.plant-controls-parameter-schema/v1"
        result["library"] = "LBNL Modelica Buildings Templates.Plants.Controls"
        return result

    def translate(
        self,
        controller_id: str,
        *,
        execution_profile: ExecutionProfile = "modelica_exact",
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if controller_id in _SOURCE_EQUATION_CONTROLLERS:
            return self._translate_source_equation(controller_id, parameters or {})
        result = super().translate(
            controller_id,
            execution_profile=execution_profile,
            parameters=parameters,
        )
        result["schema"] = "bactalk.plant-controls-translation/v1"
        result["library"] = "LBNL Modelica Buildings Templates.Plants.Controls"
        proof = _PROVEN_CONTROLLERS.get(controller_id)
        result["product_status"] = proof["status"] if proof is not None else "source_catalog_only"
        return result

    def execute(
        self,
        controller_id: str,
        *,
        samples: list[dict[str, Any]],
        collect: list[str] | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if controller_id in _SOURCE_EQUATION_CONTROLLERS:
            return self._execute_source_equation(
                controller_id,
                samples=samples,
                collect=collect,
                parameters=parameters or {},
            )
        result = super().execute(
            controller_id,
            samples=samples,
            collect=collect,
            parameters=parameters,
        )
        result["schema"] = "bactalk.plant-controls-execution/v1"
        result["library"] = "LBNL Modelica Buildings Templates.Plants.Controls"
        return result

    def niagara_program_package(
        self,
        controller_id: str,
        *,
        parameters: dict[str, Any] | None = None,
        execution_profile: ExecutionProfile = "modelica_exact",
    ) -> tuple[bytes, str]:
        if controller_id not in _SOURCE_EQUATION_CONTROLLERS:
            return super().niagara_program_package(
                controller_id,
                parameters=parameters,
                execution_profile=execution_profile,
            )
        translation = self._translate_source_equation(controller_id, parameters or {})
        graph = ControlGraph.model_validate(translation["typed_ir"])
        content = self.program_packages.build(
            graph,
            controller_id=controller_id,
        )
        return content, f"{controller_id}-niagara-programs.zip"

    def job_template(
        self,
        controller_id: str,
        *,
        parameters: dict[str, Any] | None = None,
        execution_profile: ExecutionProfile = "modelica_exact",
    ) -> dict[str, Any]:
        """Return an exact contractor-intake contract for a configured controller."""

        chosen = parameters or {}
        translation = self.translate(
            controller_id,
            execution_profile=execution_profile,
            parameters=chosen,
        )
        result = self._configured_job_template(
            translation,
            parameters=chosen,
            execution_profile=execution_profile,
            sequence_family="LBNL_PLANT_CONTROLLER",
            sequence_library="plant_controls",
            version="Pinned LBNL Modelica Buildings source",
        )
        result["schema"] = "bactalk.plant-controller-job-template/v1"
        return result

    def _source_equation_parameter_schema(
        self,
        controller_id: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        controller = self._controllers().get(controller_id)
        if controller is None:
            raise KeyError(controller_id)
        if controller_id == "HeatPumps.AirToWater":
            return self._air_to_water_parameter_schema(controller, parameters)
        if controller_id == "HeatRecoveryChillers.Controller":
            ordered_names = (
                "have_reqFlo",
                "TChiWatSup_min",
                "THeaWatSup_max",
                "COPHea_nominal",
                "capCoo_min",
                "capHea_min",
                "cp_default",
                "rho_default",
                "dtMea",
                "dtRun",
                "dtLoa",
                "dtTem1",
                "dtTem2",
            )
            allowed = set(ordered_names)
            unknown = sorted(set(parameters) - allowed)
            if unknown:
                raise ValueError(
                    "unknown or non-root plant source-equation parameter overrides: "
                    + ", ".join(unknown)
                )
            have_request = parameters.get("have_reqFlo", False)
            if not isinstance(have_request, bool):
                raise ValueError("plant parameter have_reqFlo requires Boolean")
            required = {
                "TChiWatSup_min",
                "THeaWatSup_max",
                "COPHea_nominal",
                "capCoo_min",
                "capHea_min",
                "cp_default",
                "rho_default",
            }
            defaults = {
                "dtMea": 300.0,
                "dtRun": 900.0,
                "dtLoa": 600.0,
                "dtTem1": 180.0,
                "dtTem2": 60.0,
            }
            values: dict[str, Any] = {"have_reqFlo": have_request}
            for name in ordered_names[1:]:
                raw = parameters.get(name, defaults.get(name))
                if raw is None:
                    values[name] = None
                    continue
                minimum = (
                    273.15
                    if name in {"TChiWatSup_min", "THeaWatSup_max"}
                    else 1.1
                    if name == "COPHea_nominal"
                    else 1e-5
                    if name == "dtMea"
                    else 0.0
                )
                if (
                    isinstance(raw, bool)
                    or not isinstance(raw, (int, float))
                    or not math.isfinite(float(raw))
                    or float(raw) < minimum
                ):
                    raise ValueError(f"plant parameter {name} must be finite and >= {minimum}")
                values[name] = float(raw)
            remaining = sorted(name for name in required if values[name] is None)
            descriptions = {
                "have_reqFlo": "HRC exposes chilled- and condenser-water flow requests",
                "TChiWatSup_min": "Minimum allowable chilled-water supply temperature",
                "THeaWatSup_max": "Maximum allowable heating-water supply temperature",
                "COPHea_nominal": "Heating COP at design heating conditions",
                "capCoo_min": "Minimum cooling capacity below which cycling occurs",
                "capHea_min": "Minimum heating capacity below which cycling occurs",
                "cp_default": "Default fluid specific heat capacity",
                "rho_default": "Default fluid density",
                "dtMea": "Rolling load measurement duration",
                "dtRun": "Minimum runtime of enabled and disabled states",
                "dtLoa": "Required duration with sufficient load before enabling",
                "dtTem1": "Duration at the first temperature trip threshold",
                "dtTem2": "Duration at the second temperature trip threshold",
            }
            parameterization = {
                "schema": "bactalk.g36-parameterization/v2",
                "available_parameters": sorted(allowed),
                "required_parameters": sorted(required),
                "remaining_required_parameters": remaining,
                "parameters": [
                    {
                        "name": name,
                        "data_type": "Boolean" if name == "have_reqFlo" else "Real",
                        "is_array": False,
                        "number_dimensions": None,
                        "size_of_dimensions": None,
                        "required": name in required,
                        "value": values[name],
                        "description": descriptions[name],
                        "unit": (
                            "unit:K"
                            if name in {"TChiWatSup_min", "THeaWatSup_max"}
                            else "unit:W"
                            if name in {"capCoo_min", "capHea_min"}
                            else "unit:SEC"
                            if name.startswith("dt")
                            else None
                        ),
                        "quantity": None,
                        "overridable": True,
                        "metadata_source": "pinned_modelica_source",
                    }
                    for name in ordered_names
                ],
                "applied": [
                    {
                        "name": name,
                        "value": values[name],
                        "data_type": "Boolean" if name == "have_reqFlo" else "Real",
                    }
                    for name in ordered_names
                    if name in parameters
                ],
            }
            return {
                "schema": "bactalk.plant-controls-parameter-schema/v1",
                "controller": controller,
                "parameterization": parameterization,
                "library": "LBNL Modelica Buildings Templates.Plants.Controls",
            }
        if controller_id == "HeatRecoveryChillers.Enable":
            ordered_names = (
                "TChiWatSup_min",
                "THeaWatSup_max",
                "capCoo_min",
                "capHea_min",
                "dtRun",
                "dtLoa",
                "dtTem1",
                "dtTem2",
            )
            allowed = set(ordered_names)
            unknown = sorted(set(parameters) - allowed)
            if unknown:
                raise ValueError(
                    "unknown or non-root plant source-equation parameter overrides: "
                    + ", ".join(unknown)
                )
            required = {
                "TChiWatSup_min",
                "THeaWatSup_max",
                "capCoo_min",
                "capHea_min",
            }
            defaults = {
                "dtRun": 900.0,
                "dtLoa": 600.0,
                "dtTem1": 180.0,
                "dtTem2": 60.0,
            }
            values: dict[str, float | None] = {}
            for name in ordered_names:
                raw = parameters.get(name, defaults.get(name))
                minimum = (
                    273.15
                    if name
                    in {
                        "TChiWatSup_min",
                        "THeaWatSup_max",
                    }
                    else 0.0
                )
                if raw is None:
                    values[name] = None
                    continue
                if (
                    isinstance(raw, bool)
                    or not isinstance(raw, (int, float))
                    or not math.isfinite(float(raw))
                    or float(raw) < minimum
                ):
                    raise ValueError(f"plant parameter {name} must be finite and >= {minimum}")
                values[name] = float(raw)
            remaining = sorted(name for name in required if values[name] is None)
            descriptions = {
                "TChiWatSup_min": "Minimum allowable chilled-water supply temperature",
                "THeaWatSup_max": "Maximum allowable heating-water supply temperature",
                "capCoo_min": "Minimum cooling capacity below which cycling occurs",
                "capHea_min": "Minimum heating capacity below which cycling occurs",
                "dtRun": "Minimum runtime of enabled and disabled states",
                "dtLoa": "Required duration with sufficient load before enabling",
                "dtTem1": "Duration at the first temperature trip threshold",
                "dtTem2": "Duration at the second temperature trip threshold",
            }
            parameterization = {
                "schema": "bactalk.g36-parameterization/v2",
                "available_parameters": sorted(allowed),
                "required_parameters": sorted(required),
                "remaining_required_parameters": remaining,
                "parameters": [
                    {
                        "name": name,
                        "data_type": "Real",
                        "is_array": False,
                        "number_dimensions": None,
                        "size_of_dimensions": None,
                        "required": name in required,
                        "value": values[name],
                        "description": descriptions[name],
                        "unit": (
                            "unit:K"
                            if name in {"TChiWatSup_min", "THeaWatSup_max"}
                            else "unit:W"
                            if name in {"capCoo_min", "capHea_min"}
                            else "unit:SEC"
                        ),
                        "quantity": None,
                        "overridable": True,
                        "metadata_source": "pinned_modelica_source",
                    }
                    for name in ordered_names
                ],
                "applied": [
                    {"name": name, "value": values[name], "data_type": "Real"}
                    for name in ordered_names
                    if name in parameters
                ],
            }
            return {
                "schema": "bactalk.plant-controls-parameter-schema/v1",
                "controller": controller,
                "parameterization": parameterization,
                "library": "LBNL Modelica Buildings Templates.Plants.Controls",
            }
        if controller_id == "HeatRecoveryChillers.ModeControl":
            unknown = sorted(set(parameters) - {"COPHea_nominal"})
            if unknown:
                raise ValueError(
                    "unknown or non-root plant source-equation parameter overrides: "
                    + ", ".join(unknown)
                )
            raw_cop = parameters.get("COPHea_nominal")
            cop = None
            if raw_cop is not None:
                if (
                    isinstance(raw_cop, bool)
                    or not isinstance(raw_cop, (int, float))
                    or not math.isfinite(float(raw_cop))
                    or float(raw_cop) < 1.1
                ):
                    raise ValueError("plant parameter COPHea_nominal must be finite and >= 1.1")
                cop = float(raw_cop)
            parameterization = {
                "schema": "bactalk.g36-parameterization/v2",
                "available_parameters": ["COPHea_nominal"],
                "required_parameters": ["COPHea_nominal"],
                "remaining_required_parameters": ([] if cop is not None else ["COPHea_nominal"]),
                "parameters": [
                    {
                        "name": "COPHea_nominal",
                        "data_type": "Real",
                        "is_array": False,
                        "number_dimensions": None,
                        "size_of_dimensions": None,
                        "required": True,
                        "value": cop,
                        "description": "Heating COP at design heating conditions",
                        "unit": None,
                        "quantity": None,
                        "overridable": True,
                        "metadata_source": "pinned_modelica_source",
                    }
                ],
                "applied": (
                    [{"name": "COPHea_nominal", "value": cop, "data_type": "Real"}]
                    if cop is not None
                    else []
                ),
            }
            return {
                "schema": "bactalk.plant-controls-parameter-schema/v1",
                "controller": controller,
                "parameterization": parameterization,
                "library": "LBNL Modelica Buildings Templates.Plants.Controls",
            }
        if controller_id == "Enabling.Enable":
            ordered_names = (
                "typ",
                "have_inpSch",
                "sch",
                "TOutLck",
                "dTOutLck",
                "nReqIgn",
                "dtRun",
                "dtReq",
            )
            allowed = set(ordered_names)
            unknown = sorted(set(parameters) - allowed)
            if unknown:
                raise ValueError(
                    "unknown or non-root plant source-equation parameter overrides: "
                    + ", ".join(unknown)
                )
            raw_application = parameters.get("typ")
            application = None
            if raw_application is not None:
                if not isinstance(raw_application, str):
                    raise ValueError("plant parameter typ requires Heating or Cooling enum")
                suffix = raw_application.rsplit(".", 1)[-1]
                if suffix not in {"Heating", "Cooling"}:
                    raise ValueError("plant parameter typ requires Heating or Cooling enum")
                application = suffix
            have_input_schedule = parameters.get("have_inpSch", False)
            if not isinstance(have_input_schedule, bool):
                raise ValueError("plant parameter have_inpSch requires Boolean")
            raw_schedule = parameters.get("sch", [[0.0, 1.0], [86400.0, 1.0]])
            if not isinstance(raw_schedule, list) or len(raw_schedule) < 2:
                raise ValueError("plant parameter sch requires at least two [time, 0|1] rows")
            schedule: list[list[float]] = []
            previous = -math.inf
            for index, row in enumerate(raw_schedule, start=1):
                if not isinstance(row, list) or len(row) != 2:
                    raise ValueError(f"plant parameter sch row {index} requires two Reals")
                if any(
                    isinstance(item, bool)
                    or not isinstance(item, (int, float))
                    or not math.isfinite(float(item))
                    for item in row
                ):
                    raise ValueError(f"plant parameter sch row {index} requires finite Reals")
                timestamp, value = map(float, row)
                if timestamp < previous:
                    raise ValueError("plant parameter sch times must be non-decreasing")
                if value not in {0.0, 1.0}:
                    raise ValueError("plant parameter sch values must be 0 or 1")
                schedule.append([timestamp, value])
                previous = timestamp
            if schedule[-1][0] <= 0:
                raise ValueError("plant parameter sch final time must be positive")
            defaults = {
                "TOutLck": 291.15 if application == "Heating" else 288.15,
                "dTOutLck": 0.5,
                "dtRun": 900.0,
                "dtReq": 180.0,
            }
            numerics: dict[str, float] = {}
            for name, default in defaults.items():
                raw = parameters.get(name, default)
                if (
                    isinstance(raw, bool)
                    or not isinstance(raw, (int, float))
                    or not math.isfinite(float(raw))
                    or float(raw) < (100.0 if name == "TOutLck" else 0.0)
                ):
                    minimum = "100" if name == "TOutLck" else "zero"
                    raise ValueError(
                        f"plant parameter {name} must be finite and at least {minimum}"
                    )
                numerics[name] = float(raw)
            ignored = parameters.get("nReqIgn", 0)
            if isinstance(ignored, bool) or not isinstance(ignored, int) or ignored < 0:
                raise ValueError("plant parameter nReqIgn must be non-negative Integer")
            values: dict[str, Any] = {
                "typ": application,
                "have_inpSch": have_input_schedule,
                "sch": schedule,
                "nReqIgn": ignored,
                **numerics,
            }
            descriptions = {
                "typ": "Heating or cooling application",
                "have_inpSch": "Use a software schedule input instead of the daily table",
                "sch": "Daily internal enable schedule [seconds, Boolean numeric]",
                "TOutLck": "Outdoor-air lockout temperature",
                "dTOutLck": "Outdoor-air lockout hysteresis",
                "nReqIgn": "Number of ignored plant requests",
                "dtRun": "Minimum enabled and disabled dwell time",
                "dtReq": "Low-request duration before disable",
            }
            data_types = {
                "typ": "Enumeration",
                "have_inpSch": "Boolean",
                "sch": "Real",
                "TOutLck": "Real",
                "dTOutLck": "Real",
                "nReqIgn": "Integer",
                "dtRun": "Real",
                "dtReq": "Real",
            }
            parameterization = {
                "schema": "bactalk.g36-parameterization/v2",
                "available_parameters": sorted(allowed),
                "required_parameters": ["typ"],
                "remaining_required_parameters": [] if application else ["typ"],
                "parameters": [
                    {
                        "name": name,
                        "data_type": data_types[name],
                        "is_array": name == "sch",
                        "number_dimensions": 2 if name == "sch" else None,
                        "size_of_dimensions": (f"({len(schedule)},2)" if name == "sch" else None),
                        "required": name == "typ",
                        "value": values[name],
                        "description": descriptions[name],
                        "unit": (
                            "unit:K"
                            if name in {"TOutLck", "dTOutLck"}
                            else "unit:SEC"
                            if name in {"dtRun", "dtReq"}
                            else None
                        ),
                        "quantity": None,
                        "overridable": True,
                        "metadata_source": "pinned_modelica_source",
                    }
                    for name in ordered_names
                ],
                "applied": [
                    {
                        "name": name,
                        "value": values[name],
                        "data_type": data_types[name],
                    }
                    for name in ordered_names
                    if name in parameters
                ],
            }
            return {
                "schema": "bactalk.plant-controls-parameter-schema/v1",
                "controller": controller,
                "parameterization": parameterization,
                "library": "LBNL Modelica Buildings Templates.Plants.Controls",
            }
        if controller_id == "Pumps.Primary.VariableSpeed":
            order = (
                "have_heaWat",
                "have_chiWat",
                "have_pumPriCtlDp",
                "have_pumChiWatPriDed",
                "have_pumPriHdr",
                "nEqu",
                "nPumHeaWatPri",
                "nPumChiWatPri",
                "yPumHeaWatPriSet",
                "yPumChiWatPriSet",
                "have_senDpHeaWatRemWir",
                "nSenDpHeaWatRem",
                "yPumHeaWatPri_min",
                "kCtlDpHeaWat",
                "TiCtlDpHeaWat",
                "have_senDpChiWatRemWir",
                "nSenDpChiWatRem",
                "yPumChiWatPri_min",
                "kCtlDpChiWat",
                "TiCtlDpChiWat",
            )
            allowed = set(order)
            unknown = sorted(set(parameters) - allowed)
            if unknown:
                raise ValueError(
                    "unknown or non-root plant source-equation parameter overrides: "
                    + ", ".join(unknown)
                )
            defaults_bool = {
                "have_pumChiWatPriDed": False,
                "have_senDpHeaWatRemWir": False,
                "have_senDpChiWatRemWir": False,
            }
            booleans: dict[str, bool | None] = {}
            for name in (
                "have_heaWat",
                "have_chiWat",
                "have_pumPriCtlDp",
                "have_pumChiWatPriDed",
                "have_pumPriHdr",
                "have_senDpHeaWatRemWir",
                "have_senDpChiWatRemWir",
            ):
                raw = parameters.get(name, defaults_bool.get(name))
                if raw is not None and not isinstance(raw, bool):
                    raise ValueError(f"plant parameter {name} requires Boolean")
                booleans[name] = raw
            have_heating = booleans["have_heaWat"]
            have_cooling = booleans["have_chiWat"]
            if have_heating is False and have_cooling is False:
                raise ValueError("Pumps.Primary.VariableSpeed requires a heating or cooling loop")
            headered = booleans["have_pumPriHdr"]
            separate_chilled = bool(have_cooling and (headered or booleans["have_pumChiWatPriDed"]))
            if have_cooling is True and not separate_chilled and have_heating is False:
                raise ValueError("cooling with common primary pumps requires the heating loop")
            required = {
                "have_heaWat",
                "have_chiWat",
                "have_pumPriCtlDp",
                "have_pumPriHdr",
                "nEqu",
            }
            if have_heating or (have_cooling and not separate_chilled):
                required.add("nPumHeaWatPri")
            if separate_chilled:
                required.add("nPumChiWatPri")
            counts: dict[str, int | None] = {}
            for name in ("nEqu", "nPumHeaWatPri", "nPumChiWatPri"):
                raw = parameters.get(name)
                if raw is not None and (
                    isinstance(raw, bool) or not isinstance(raw, int) or not 1 <= raw <= 52
                ):
                    raise ValueError(f"plant parameter {name} must be an integer from 1 through 52")
                counts[name] = raw
            if (
                have_heating is True
                and have_cooling is True
                and not separate_chilled
                and counts["nEqu"] is not None
                and counts["nPumHeaWatPri"] is not None
                and counts["nEqu"] != counts["nPumHeaWatPri"]
            ):
                raise ValueError("shared reversible dedicated pumps require nEqu=nPumHeaWatPri")
            control_dp = booleans["have_pumPriCtlDp"] is True
            numerics: dict[str, float | None] = {}
            for loop in ("HeaWat", "ChiWat"):
                active = have_heating is True if loop == "HeaWat" else have_cooling is True
                speed_name = f"yPum{loop}PriSet"
                speed = parameters.get(speed_name)
                if not control_dp and active:
                    required.add(speed_name)
                if speed is not None and (
                    isinstance(speed, bool)
                    or not isinstance(speed, (int, float))
                    or not math.isfinite(float(speed))
                    or not 0 <= float(speed) <= 2
                ):
                    raise ValueError(f"plant parameter {speed_name} must be from 0 through 2")
                numerics[speed_name] = float(speed) if speed is not None else None
                sensor_name = f"nSenDp{loop}Rem"
                sensor_count = parameters.get(sensor_name)
                if control_dp and active:
                    required.add(sensor_name)
                if sensor_count is not None and (
                    isinstance(sensor_count, bool)
                    or not isinstance(sensor_count, int)
                    or not 1 <= sensor_count <= 52
                ):
                    raise ValueError(
                        f"plant parameter {sensor_name} must be an integer from 1 through 52"
                    )
                counts[sensor_name] = sensor_count
                for name, default, lower, upper in (
                    (f"yPum{loop}Pri_min", 0.1, 0.0, 1.0),
                    (f"kCtlDp{loop}", 1.0, 1e-13, None),
                    (f"TiCtlDp{loop}", 60.0, 1e-13, None),
                ):
                    raw = parameters.get(name, default)
                    if (
                        isinstance(raw, bool)
                        or not isinstance(raw, (int, float))
                        or not math.isfinite(float(raw))
                        or float(raw) < lower
                        or (upper is not None and float(raw) > upper)
                    ):
                        raise ValueError(
                            f"plant parameter {name} must satisfy its finite source bounds"
                        )
                    numerics[name] = float(raw)
            values: dict[str, Any] = {**booleans, **counts, **numerics}
            data_types = {
                name: (
                    "Boolean" if name in booleans else "Integer" if name.startswith("n") else "Real"
                )
                for name in order
            }
            remaining = sorted(
                name for name in required if name not in parameters or values[name] is None
            )
            parameterization = {
                "schema": "bactalk.g36-parameterization/v2",
                "available_parameters": sorted(allowed),
                "required_parameters": sorted(required),
                "remaining_required_parameters": remaining,
                "parameters": [
                    {
                        "name": name,
                        "data_type": data_types[name],
                        "is_array": False,
                        "number_dimensions": None,
                        "size_of_dimensions": None,
                        "required": name in required,
                        "value": values[name],
                        "description": "Pinned primary variable-speed pump parameter",
                        "unit": "unit:SEC" if name.startswith("Ti") else None,
                        "quantity": None,
                        "overridable": True,
                        "metadata_source": "pinned_modelica_source",
                    }
                    for name in order
                ],
                "applied": [
                    {
                        "name": name,
                        "value": values[name],
                        "data_type": data_types[name],
                    }
                    for name in order
                    if name in parameters
                ],
            }
            return {
                "schema": "bactalk.plant-controls-parameter-schema/v1",
                "controller": controller,
                "parameterization": parameterization,
                "library": "LBNL Modelica Buildings Templates.Plants.Controls",
            }
        if controller_id == "Pumps.Generic.StagingHeadered":
            order = (
                "is_pri",
                "is_hdr",
                "is_ctlDp",
                "have_valInlIso",
                "have_valOutIso",
                "nEqu",
                "nPum",
                "nSenDp",
                "V_flow_nominal",
                "dtRun",
                "dtRunFaiSaf",
                "dtRunFaiSafLowY",
                "dVOffUp",
                "dVOffDow",
                "dpOff",
                "yUp",
                "yDow",
            )
            allowed = set(order)
            unknown = sorted(set(parameters) - allowed)
            if unknown:
                raise ValueError(
                    "unknown or non-root plant source-equation parameter overrides: "
                    + ", ".join(unknown)
                )
            required = {
                "is_pri",
                "is_hdr",
                "is_ctlDp",
                "have_valInlIso",
                "have_valOutIso",
                "nEqu",
                "nPum",
            }
            booleans: dict[str, bool | None] = {}
            for name in (
                "is_pri",
                "is_hdr",
                "is_ctlDp",
                "have_valInlIso",
                "have_valOutIso",
            ):
                raw = parameters.get(name)
                if raw is not None and not isinstance(raw, bool):
                    raise ValueError(f"plant parameter {name} requires Boolean")
                booleans[name] = raw
            if booleans["is_hdr"] is False:
                raise ValueError(
                    "Pumps.Generic.StagingHeadered product support requires is_hdr=true"
                )
            if booleans["is_ctlDp"] is False and booleans["is_pri"] is False:
                raise ValueError(
                    "secondary headered pumps require is_ctlDp=true in the pinned source"
                )
            if (
                booleans["is_pri"] is True
                and booleans["have_valInlIso"] is False
                and booleans["have_valOutIso"] is False
            ):
                raise ValueError(
                    "primary headered pumps require inlet or outlet isolation-valve commands"
                )
            counts: dict[str, int | None] = {}
            for name in ("nEqu", "nPum"):
                raw = parameters.get(name)
                if raw is not None and (
                    isinstance(raw, bool) or not isinstance(raw, int) or not 1 <= raw <= 52
                ):
                    raise ValueError(f"plant parameter {name} must be an integer from 1 through 52")
                counts[name] = raw
            dp_control = booleans["is_ctlDp"] is True
            if dp_control:
                required.update({"nSenDp", "V_flow_nominal"})
            sensor_count = parameters.get("nSenDp", 1 if not dp_control else None)
            if sensor_count is not None and (
                isinstance(sensor_count, bool)
                or not isinstance(sensor_count, int)
                or not 1 <= sensor_count <= 52
            ):
                raise ValueError("plant parameter nSenDp must be an integer from 1 through 52")
            flow = parameters.get("V_flow_nominal", 1e-6 if not dp_control else None)
            if flow is not None and (
                isinstance(flow, bool)
                or not isinstance(flow, (int, float))
                or not math.isfinite(float(flow))
                or float(flow) < 1e-6
            ):
                raise ValueError("plant parameter V_flow_nominal must be finite and at least 1e-6")
            defaults = {
                "dtRun": 600.0,
                "dtRunFaiSaf": 300.0,
                "dVOffUp": 0.03,
                "dpOff": 1e4,
                "yUp": 0.99,
                "yDow": 0.4,
            }
            numerics: dict[str, float | None] = {
                "V_flow_nominal": float(flow) if flow is not None else None
            }
            for name, default in defaults.items():
                raw = parameters.get(name, default)
                if (
                    isinstance(raw, bool)
                    or not isinstance(raw, (int, float))
                    or not math.isfinite(float(raw))
                    or float(raw) < 0
                    or (name == "dVOffUp" and float(raw) > 1)
                ):
                    raise ValueError(
                        f"plant parameter {name} must satisfy its finite source bounds"
                    )
                numerics[name] = float(raw)
            down_offset = parameters.get("dVOffDow", numerics["dVOffUp"])
            if (
                isinstance(down_offset, bool)
                or not isinstance(down_offset, (int, float))
                or not math.isfinite(float(down_offset))
                or not 0 <= float(down_offset) <= 1
            ):
                raise ValueError("plant parameter dVOffDow must be from 0 through 1")
            numerics["dVOffDow"] = float(down_offset)
            low_speed_time = parameters.get("dtRunFaiSafLowY", numerics["dtRun"])
            if (
                isinstance(low_speed_time, bool)
                or not isinstance(low_speed_time, (int, float))
                or not math.isfinite(float(low_speed_time))
                or float(low_speed_time) < 0
            ):
                raise ValueError("plant parameter dtRunFaiSafLowY must be non-negative finite")
            numerics["dtRunFaiSafLowY"] = float(low_speed_time)
            values: dict[str, Any] = {
                **booleans,
                **counts,
                "nSenDp": sensor_count,
                **numerics,
            }
            data_types = {
                name: (
                    "Boolean"
                    if name in booleans
                    else "Integer"
                    if name in {"nEqu", "nPum", "nSenDp"}
                    else "Real"
                )
                for name in order
            }
            remaining = sorted(
                name for name in required if name not in parameters or values[name] is None
            )
            parameterization = {
                "schema": "bactalk.g36-parameterization/v2",
                "available_parameters": sorted(allowed),
                "required_parameters": sorted(required),
                "remaining_required_parameters": remaining,
                "parameters": [
                    {
                        "name": name,
                        "data_type": data_types[name],
                        "is_array": False,
                        "number_dimensions": None,
                        "size_of_dimensions": None,
                        "required": name in required,
                        "value": values[name],
                        "description": "Pinned generic headered-pump source parameter",
                        "unit": (
                            "unit:SEC"
                            if name.startswith("dt")
                            else "unit:PA"
                            if name == "dpOff"
                            else "unit:M3-PER-SEC"
                            if name == "V_flow_nominal"
                            else None
                        ),
                        "quantity": None,
                        "overridable": True,
                        "metadata_source": "pinned_modelica_source",
                    }
                    for name in order
                ],
                "applied": [
                    {
                        "name": name,
                        "value": values[name],
                        "data_type": data_types[name],
                    }
                    for name in order
                    if name in parameters
                ],
            }
            return {
                "schema": "bactalk.plant-controls-parameter-schema/v1",
                "controller": controller,
                "parameterization": parameterization,
                "library": "LBNL Modelica Buildings Templates.Plants.Controls",
            }
        if controller_id == "StagingRotation.StageChangeCommand":
            order = (
                "typ",
                "have_pumSec",
                "have_inpPlrSta",
                "plrSta",
                "staEqu",
                "capEqu",
                "dtRun",
                "dtMea",
                "cp_default",
                "rho_default",
                "dT",
                "dtPri",
                "dtSec",
            )
            allowed = set(order)
            unknown = sorted(set(parameters) - allowed)
            if unknown:
                raise ValueError(
                    "unknown or non-root plant source-equation parameter overrides: "
                    + ", ".join(unknown)
                )
            raw_application = parameters.get("typ")
            application = None
            if raw_application is not None:
                if not isinstance(raw_application, str):
                    raise ValueError("plant parameter typ requires Heating or Cooling enum")
                application = raw_application.rsplit(".", 1)[-1]
                if application not in {"Heating", "Cooling"}:
                    raise ValueError("plant parameter typ requires Heating or Cooling enum")
            have_secondary = parameters.get("have_pumSec")
            if have_secondary is not None and not isinstance(have_secondary, bool):
                raise ValueError("plant parameter have_pumSec requires Boolean")
            have_plr_input = parameters.get("have_inpPlrSta", False)
            if not isinstance(have_plr_input, bool):
                raise ValueError("plant parameter have_inpPlrSta requires Boolean")
            matrix = (
                self._validated_staging_matrix(parameters["staEqu"])
                if "staEqu" in parameters
                else None
            )
            raw_capacities = parameters.get("capEqu")
            capacities: list[float] | None = None
            if raw_capacities is not None:
                if not isinstance(raw_capacities, list) or not raw_capacities:
                    raise ValueError("plant parameter capEqu requires a non-empty Real array")
                capacities = []
                for index, item in enumerate(raw_capacities, start=1):
                    if (
                        isinstance(item, bool)
                        or not isinstance(item, (int, float))
                        or not math.isfinite(float(item))
                        or float(item) <= 0
                    ):
                        raise ValueError(f"plant parameter capEqu[{index}] must be positive finite")
                    capacities.append(float(item))
                if matrix is not None and len(capacities) != len(matrix[0]):
                    raise ValueError(
                        "plant parameter capEqu length must equal the staEqu equipment count"
                    )
            defaults = {
                "plrSta": 0.9,
                "dtRun": 900.0,
                "dtMea": 300.0,
                "dtPri": 900.0,
                "dtSec": 600.0,
            }
            numerics: dict[str, float | None] = {}
            for name, default in defaults.items():
                raw = parameters.get(name, default)
                if (
                    isinstance(raw, bool)
                    or not isinstance(raw, (int, float))
                    or not math.isfinite(float(raw))
                    or float(raw) < 0
                    or (name == "plrSta" and float(raw) > 1)
                    or (name == "dtMea" and float(raw) <= 0)
                ):
                    raise ValueError(
                        f"plant parameter {name} must satisfy its finite source bounds"
                    )
                numerics[name] = float(raw)
            for name in ("cp_default", "rho_default", "dT"):
                raw = parameters.get(name)
                if raw is not None and (
                    isinstance(raw, bool)
                    or not isinstance(raw, (int, float))
                    or not math.isfinite(float(raw))
                    or float(raw) <= 0
                ):
                    raise ValueError(f"plant parameter {name} must be positive finite")
                numerics[name] = float(raw) if raw is not None else None
            required = {
                "typ",
                "have_pumSec",
                "staEqu",
                "capEqu",
                "cp_default",
                "rho_default",
                "dT",
            }
            values: dict[str, Any] = {
                "typ": (
                    f"Buildings.Templates.Plants.Controls.Types.Application.{application}"
                    if application
                    else None
                ),
                "have_pumSec": have_secondary,
                "have_inpPlrSta": have_plr_input,
                "staEqu": matrix,
                "capEqu": capacities,
                **numerics,
            }
            data_types = {
                name: (
                    "Enumeration"
                    if name == "typ"
                    else "Boolean"
                    if name in {"have_pumSec", "have_inpPlrSta"}
                    else "Real"
                )
                for name in order
            }
            array_dimensions = {"staEqu": 2, "capEqu": 1}
            records = []
            for name in order:
                dimensions = array_dimensions.get(name)
                if name == "staEqu" and matrix is not None:
                    size = f"({len(matrix)},{len(matrix[0])})"
                elif name == "capEqu" and capacities is not None:
                    size = f"({len(capacities)})"
                else:
                    size = None
                records.append(
                    {
                        "name": name,
                        "data_type": data_types[name],
                        "is_array": dimensions is not None,
                        "number_dimensions": dimensions,
                        "size_of_dimensions": size,
                        "required": name in required,
                        "value": values[name],
                        "description": "Pinned plant stage-change source parameter",
                        "unit": (
                            "unit:SEC"
                            if name.startswith("dt")
                            else "unit:W"
                            if name == "capEqu"
                            else "unit:J-PER-KG-K"
                            if name == "cp_default"
                            else "unit:KG-PER-M3"
                            if name == "rho_default"
                            else "unit:K"
                            if name == "dT"
                            else None
                        ),
                        "quantity": None,
                        "overridable": True,
                        "metadata_source": "pinned_modelica_source",
                    }
                )
            parameterization = {
                "schema": "bactalk.g36-parameterization/v2",
                "available_parameters": sorted(allowed),
                "required_parameters": sorted(required),
                "remaining_required_parameters": sorted(required - set(parameters)),
                "parameters": records,
                "applied": [
                    {
                        "name": name,
                        "value": values[name],
                        "data_type": data_types[name],
                    }
                    for name in order
                    if name in parameters
                ],
            }
            return {
                "schema": "bactalk.plant-controls-parameter-schema/v1",
                "controller": controller,
                "parameterization": parameterization,
                "library": "LBNL Modelica Buildings Templates.Plants.Controls",
            }
        if controller_id == "Pumps.Generic.StagingHeaderedDeltaP":
            allowed = {
                "nPum",
                "nSenDp",
                "V_flow_nominal",
                "dtRun",
                "dtRunFaiSaf",
                "dtRunFaiSafLowY",
                "dVOffUp",
                "dVOffDow",
                "dpOff",
                "yUp",
                "yDow",
            }
            unknown = sorted(set(parameters) - allowed)
            if unknown:
                raise ValueError(
                    "unknown or non-root plant source-equation parameter overrides: "
                    + ", ".join(unknown)
                )
            counts: dict[str, int | None] = {}
            for name in ("nPum", "nSenDp"):
                raw = parameters.get(name)
                if raw is not None and (
                    isinstance(raw, bool) or not isinstance(raw, int) or not 1 <= raw <= 52
                ):
                    raise ValueError(f"plant parameter {name} must be an integer from 1 through 52")
                counts[name] = raw
            defaults = {
                "dtRun": 600.0,
                "dtRunFaiSaf": 300.0,
                "dVOffUp": 0.03,
                "dpOff": 1e4,
                "yUp": 0.99,
                "yDow": 0.4,
            }
            numerics: dict[str, float | None] = {}
            flow = parameters.get("V_flow_nominal")
            if flow is not None and (
                isinstance(flow, bool)
                or not isinstance(flow, (int, float))
                or not math.isfinite(float(flow))
                or float(flow) < 1e-6
            ):
                raise ValueError("plant parameter V_flow_nominal must be finite and at least 1e-6")
            numerics["V_flow_nominal"] = float(flow) if flow is not None else None
            for name, default in defaults.items():
                raw = parameters.get(name, default)
                if (
                    isinstance(raw, bool)
                    or not isinstance(raw, (int, float))
                    or not math.isfinite(float(raw))
                    or float(raw) < 0
                    or (name in {"dVOffUp"} and float(raw) > 1)
                ):
                    raise ValueError(f"plant parameter {name} must be non-negative finite")
                numerics[name] = float(raw)
            down_offset = parameters.get("dVOffDow", numerics["dVOffUp"])
            if (
                isinstance(down_offset, bool)
                or not isinstance(down_offset, (int, float))
                or not math.isfinite(float(down_offset))
                or not 0 <= float(down_offset) <= 1
            ):
                raise ValueError("plant parameter dVOffDow must be from 0 through 1")
            numerics["dVOffDow"] = float(down_offset)
            low_speed_time = parameters.get("dtRunFaiSafLowY", numerics["dtRun"])
            if (
                isinstance(low_speed_time, bool)
                or not isinstance(low_speed_time, (int, float))
                or not math.isfinite(float(low_speed_time))
                or float(low_speed_time) < 0
            ):
                raise ValueError("plant parameter dtRunFaiSafLowY must be non-negative finite")
            numerics["dtRunFaiSafLowY"] = float(low_speed_time)
            values: dict[str, Any] = {**counts, **numerics}
            required = {"nPum", "nSenDp", "V_flow_nominal"}
            data_types = {name: "Integer" if name in counts else "Real" for name in allowed}
            order = (
                "nPum",
                "nSenDp",
                "V_flow_nominal",
                "dtRun",
                "dtRunFaiSaf",
                "dtRunFaiSafLowY",
                "dVOffUp",
                "dVOffDow",
                "dpOff",
                "yUp",
                "yDow",
            )
            parameterization = {
                "schema": "bactalk.g36-parameterization/v2",
                "available_parameters": sorted(allowed),
                "required_parameters": sorted(required),
                "remaining_required_parameters": sorted(required - set(parameters)),
                "parameters": [
                    {
                        "name": name,
                        "data_type": data_types[name],
                        "is_array": False,
                        "number_dimensions": None,
                        "size_of_dimensions": None,
                        "required": name in required,
                        "value": values[name],
                        "description": "Pinned headered-pump staging parameter",
                        "unit": (
                            "unit:SEC"
                            if name.startswith("dt")
                            else "unit:PA"
                            if name == "dpOff"
                            else "unit:M3-PER-SEC"
                            if name == "V_flow_nominal"
                            else None
                        ),
                        "quantity": None,
                        "overridable": True,
                        "metadata_source": "pinned_modelica_source",
                    }
                    for name in order
                ],
                "applied": [
                    {
                        "name": name,
                        "value": values[name],
                        "data_type": data_types[name],
                    }
                    for name in order
                    if name in parameters
                ],
            }
            return {
                "schema": "bactalk.plant-controls-parameter-schema/v1",
                "controller": controller,
                "parameterization": parameterization,
                "library": "LBNL Modelica Buildings Templates.Plants.Controls",
            }
        if controller_id == "StagingRotation.SortRuntime":
            allowed = {"nin", "idxEquAlt", "runTim_start"}
            unknown = sorted(set(parameters) - allowed)
            if unknown:
                raise ValueError(
                    "unknown or non-root plant source-equation parameter overrides: "
                    + ", ".join(unknown)
                )
            input_count = parameters.get("nin")
            if input_count is not None and (
                isinstance(input_count, bool)
                or not isinstance(input_count, int)
                or not 1 <= input_count <= 52
            ):
                raise ValueError("plant parameter nin must be an integer from 1 through 52")
            raw_indices = parameters.get("idxEquAlt")
            indices: list[int] | None = None
            if input_count is not None:
                raw_indices = (
                    raw_indices if raw_indices is not None else list(range(1, input_count + 1))
                )
                if (
                    not isinstance(raw_indices, list)
                    or not raw_indices
                    or any(
                        isinstance(value, bool)
                        or not isinstance(value, int)
                        or not 1 <= value <= input_count
                        for value in raw_indices
                    )
                    or len(set(raw_indices)) != len(raw_indices)
                ):
                    raise ValueError(
                        "plant parameter idxEquAlt must be a non-empty list of unique "
                        f"equipment indices from 1 through {input_count}"
                    )
                indices = list(raw_indices)
            elif raw_indices is not None:
                raise ValueError("plant parameter idxEquAlt requires nin")
            raw_starts = parameters.get("runTim_start")
            starts: list[float] | None = None
            if indices is not None:
                raw_starts = (
                    raw_starts
                    if raw_starts is not None
                    else [float(60 + position) for position in range(1, len(indices) + 1)]
                )
                if (
                    not isinstance(raw_starts, list)
                    or len(raw_starts) != len(indices)
                    or any(
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not math.isfinite(float(value))
                        or float(value) < 0
                        for value in raw_starts
                    )
                ):
                    raise ValueError(
                        "plant parameter runTim_start must contain one non-negative finite "
                        "value per alternate equipment"
                    )
                starts = [float(value) for value in raw_starts]
                if any(right <= left for left, right in zip(starts, starts[1:], strict=False)):
                    raise ValueError("plant parameter runTim_start must be strictly increasing")
            elif raw_starts is not None:
                raise ValueError("plant parameter runTim_start requires nin")
            values = {
                "nin": input_count,
                "idxEquAlt": indices,
                "runTim_start": starts,
            }
            data_types = {
                "nin": "Integer",
                "idxEquAlt": "Integer",
                "runTim_start": "Real",
            }
            parameterization = {
                "schema": "bactalk.g36-parameterization/v2",
                "available_parameters": sorted(allowed),
                "required_parameters": ["nin"],
                "remaining_required_parameters": [] if input_count is not None else ["nin"],
                "parameters": [
                    {
                        "name": name,
                        "data_type": data_types[name],
                        "is_array": name != "nin",
                        "number_dimensions": 1 if name != "nin" else None,
                        "size_of_dimensions": (
                            f"({len(indices)},)" if name != "nin" and indices is not None else None
                        ),
                        "required": name == "nin",
                        "value": values[name],
                        "description": (
                            "Number of equipment inputs"
                            if name == "nin"
                            else "Indices of lead/lag alternate equipment"
                            if name == "idxEquAlt"
                            else "Strictly increasing initial staging runtimes"
                        ),
                        "unit": "unit:SEC" if name == "runTim_start" else None,
                        "quantity": None,
                        "overridable": True,
                        "metadata_source": "pinned_modelica_source",
                    }
                    for name in ("nin", "idxEquAlt", "runTim_start")
                ],
                "applied": [
                    {
                        "name": name,
                        "value": values[name],
                        "data_type": data_types[name],
                    }
                    for name in ("nin", "idxEquAlt", "runTim_start")
                    if name in parameters
                ],
            }
            return {
                "schema": "bactalk.plant-controls-parameter-schema/v1",
                "controller": controller,
                "parameterization": parameterization,
                "library": "LBNL Modelica Buildings Templates.Plants.Controls",
            }
        if controller_id == "Utilities.StageIndex":
            allowed = {"have_inpAva", "nSta", "dtRun"}
            unknown = sorted(set(parameters) - allowed)
            if unknown:
                raise ValueError(
                    "unknown or non-root plant source-equation parameter overrides: "
                    + ", ".join(unknown)
                )
            have_input = parameters.get("have_inpAva", True)
            if not isinstance(have_input, bool):
                raise ValueError("plant parameter have_inpAva requires Boolean")
            stage_count = parameters.get("nSta")
            if stage_count is not None and (
                isinstance(stage_count, bool)
                or not isinstance(stage_count, int)
                or not 1 <= stage_count <= 52
            ):
                raise ValueError("plant parameter nSta must be an integer from 1 through 52")
            minimum_runtime = parameters.get("dtRun", 0.0)
            if (
                isinstance(minimum_runtime, bool)
                or not isinstance(minimum_runtime, (int, float))
                or not math.isfinite(float(minimum_runtime))
                or float(minimum_runtime) < 0
            ):
                raise ValueError("plant parameter dtRun must be non-negative finite numeric")
            values = {
                "have_inpAva": have_input,
                "nSta": stage_count,
                "dtRun": float(minimum_runtime),
            }
            data_types = {
                "have_inpAva": "Boolean",
                "nSta": "Integer",
                "dtRun": "Real",
            }
            parameterization = {
                "schema": "bactalk.g36-parameterization/v2",
                "available_parameters": sorted(allowed),
                "required_parameters": ["nSta"],
                "remaining_required_parameters": [] if stage_count is not None else ["nSta"],
                "parameters": [
                    {
                        "name": name,
                        "data_type": data_types[name],
                        "is_array": False,
                        "number_dimensions": None,
                        "size_of_dimensions": None,
                        "required": name == "nSta",
                        "value": values[name],
                        "description": (
                            "Use stage-availability input vector"
                            if name == "have_inpAva"
                            else "Number of plant stages"
                            if name == "nSta"
                            else "Minimum runtime of each active stage"
                        ),
                        "unit": "unit:SEC" if name == "dtRun" else None,
                        "quantity": None,
                        "overridable": True,
                        "metadata_source": "pinned_modelica_source",
                    }
                    for name in ("have_inpAva", "nSta", "dtRun")
                ],
                "applied": [
                    {
                        "name": name,
                        "value": values[name],
                        "data_type": data_types[name],
                    }
                    for name in ("have_inpAva", "nSta", "dtRun")
                    if name in parameters
                ],
            }
            return {
                "schema": "bactalk.plant-controls-parameter-schema/v1",
                "controller": controller,
                "parameterization": parameterization,
                "library": "LBNL Modelica Buildings Templates.Plants.Controls",
            }
        if controller_id == "StagingRotation.EquipmentEnable":
            allowed = {"staEqu", "nEquAlt"}
            unknown = sorted(set(parameters) - allowed)
            if unknown:
                raise ValueError(
                    "unknown or non-root plant source-equation parameter overrides: "
                    + ", ".join(unknown)
                )
            matrix = (
                self._validated_staging_matrix(parameters["staEqu"])
                if "staEqu" in parameters
                else None
            )
            derived_alternates: int | None = None
            if matrix is not None:
                equipment_count = len(matrix[0])
                derived_alternates = (
                    1
                    if equipment_count == 1
                    else max(sum(0.0 < coefficient < 1.0 for coefficient in row) for row in matrix)
                )
            raw_alternates = parameters.get("nEquAlt", derived_alternates)
            if raw_alternates is not None and (
                isinstance(raw_alternates, bool)
                or not isinstance(raw_alternates, int)
                or raw_alternates < 0
                or (matrix is not None and raw_alternates > len(matrix[0]))
            ):
                raise ValueError(
                    "plant parameter nEquAlt must be a non-negative integer no larger "
                    "than the equipment count"
                )
            if (
                raw_alternates is not None
                and derived_alternates is not None
                and raw_alternates < derived_alternates
            ):
                raise ValueError(
                    "plant parameter nEquAlt cannot be smaller than the staging matrix's "
                    "maximum alternate-equipment requirement"
                )
            values = {"staEqu": matrix, "nEquAlt": raw_alternates}
            remaining = [] if matrix is not None else ["staEqu"]
            parameterization = {
                "schema": "bactalk.g36-parameterization/v2",
                "available_parameters": sorted(allowed),
                "required_parameters": ["staEqu"],
                "remaining_required_parameters": remaining,
                "parameters": [
                    {
                        "name": "staEqu",
                        "data_type": "Real",
                        "is_array": True,
                        "number_dimensions": 2,
                        "size_of_dimensions": (
                            f"({len(matrix)},{len(matrix[0])})" if matrix is not None else None
                        ),
                        "required": True,
                        "value": matrix,
                        "description": "Stage-by-equipment requirement matrix",
                        "unit": None,
                        "quantity": None,
                        "overridable": True,
                        "metadata_source": "pinned_modelica_source",
                    },
                    {
                        "name": "nEquAlt",
                        "data_type": "Integer",
                        "is_array": False,
                        "number_dimensions": None,
                        "size_of_dimensions": None,
                        "required": False,
                        "value": raw_alternates,
                        "description": "Number of runtime-sorted lead/lag alternates",
                        "unit": None,
                        "quantity": None,
                        "overridable": True,
                        "metadata_source": "pinned_modelica_source",
                    },
                ],
                "applied": [
                    {
                        "name": name,
                        "value": values[name],
                        "data_type": "Real" if name == "staEqu" else "Integer",
                    }
                    for name in ("staEqu", "nEquAlt")
                    if name in parameters
                ],
            }
            return {
                "schema": "bactalk.plant-controls-parameter-schema/v1",
                "controller": controller,
                "parameterization": parameterization,
                "library": "LBNL Modelica Buildings Templates.Plants.Controls",
            }
        if controller_id == "StagingRotation.StageCompletion":
            unknown = sorted(set(parameters) - {"nin"})
            if unknown:
                raise ValueError(
                    "unknown or non-root plant source-equation parameter overrides: "
                    + ", ".join(unknown)
                )
            count = parameters.get("nin")
            if count is not None and (
                isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 52
            ):
                raise ValueError("plant parameter nin must be an integer from 1 through 52")
            parameterization = {
                "schema": "bactalk.g36-parameterization/v2",
                "available_parameters": ["nin"],
                "required_parameters": ["nin"],
                "remaining_required_parameters": [] if count is not None else ["nin"],
                "parameters": [
                    {
                        "name": "nin",
                        "data_type": "Integer",
                        "is_array": False,
                        "number_dimensions": None,
                        "size_of_dimensions": None,
                        "required": True,
                        "value": count,
                        "description": "Number of equipment command/status pairs",
                        "unit": None,
                        "quantity": None,
                        "overridable": True,
                        "metadata_source": "pinned_modelica_source",
                    }
                ],
                "applied": (
                    [{"name": "nin", "value": count, "data_type": "Integer"}]
                    if count is not None
                    else []
                ),
            }
            return {
                "schema": "bactalk.plant-controls-parameter-schema/v1",
                "controller": controller,
                "parameterization": parameterization,
                "library": "LBNL Modelica Buildings Templates.Plants.Controls",
            }
        if controller_id == "StagingRotation.EquipmentAvailability":
            allowed = {"have_heaWat", "have_chiWat", "dtOff"}
            unknown = sorted(set(parameters) - allowed)
            if unknown:
                raise ValueError(
                    "unknown or non-root plant source-equation parameter overrides: "
                    + ", ".join(unknown)
                )
            for name in ("have_heaWat", "have_chiWat"):
                if name in parameters and not isinstance(parameters[name], bool):
                    raise ValueError(f"plant parameter {name} requires Boolean")
            have_heating = parameters.get("have_heaWat")
            have_cooling = parameters.get("have_chiWat")
            if have_heating is False and have_cooling is False:
                raise ValueError("StagingRotation.EquipmentAvailability requires at least one loop")
            duration = parameters.get("dtOff", 900.0)
            if (
                isinstance(duration, bool)
                or not isinstance(duration, (int, float))
                or not math.isfinite(float(duration))
                or float(duration) < 0
            ):
                raise ValueError("plant parameter dtOff must be finite and non-negative")
            duration = float(duration)
            required = {"have_heaWat", "have_chiWat"}
            values = {
                "have_heaWat": have_heating,
                "have_chiWat": have_cooling,
                "dtOff": duration,
            }
            parameterization = {
                "schema": "bactalk.g36-parameterization/v2",
                "available_parameters": sorted(allowed),
                "required_parameters": sorted(required),
                "remaining_required_parameters": sorted(required - set(parameters)),
                "parameters": [
                    {
                        "name": name,
                        "data_type": "Boolean" if name != "dtOff" else "Real",
                        "is_array": False,
                        "number_dimensions": None,
                        "size_of_dimensions": None,
                        "required": name in required,
                        "value": values[name],
                        "description": (
                            "Plant provides a heating-water loop"
                            if name == "have_heaWat"
                            else "Plant provides a chilled-water loop"
                            if name == "have_chiWat"
                            else "Off time before equipment becomes available again"
                        ),
                        "unit": "unit:SEC" if name == "dtOff" else None,
                        "quantity": None,
                        "overridable": True,
                        "metadata_source": "pinned_modelica_source",
                    }
                    for name in ("have_heaWat", "have_chiWat", "dtOff")
                ],
                "applied": [
                    {
                        "name": name,
                        "value": values[name],
                        "data_type": "Boolean" if name != "dtOff" else "Real",
                    }
                    for name in ("have_heaWat", "have_chiWat", "dtOff")
                    if name in parameters
                ],
            }
            return {
                "schema": "bactalk.plant-controls-parameter-schema/v1",
                "controller": controller,
                "parameterization": parameterization,
                "library": "LBNL Modelica Buildings Templates.Plants.Controls",
            }
        if controller_id == "StagingRotation.StageAvailability":
            unknown = sorted(set(parameters) - {"staEqu"})
            if unknown:
                raise ValueError(
                    "unknown or non-root plant source-equation parameter overrides: "
                    + ", ".join(unknown)
                )
            matrix = (
                self._validated_staging_matrix(parameters["staEqu"])
                if "staEqu" in parameters
                else None
            )
            dimensions = f"({len(matrix)},{len(matrix[0])})" if matrix is not None else None
            parameterization = {
                "schema": "bactalk.g36-parameterization/v2",
                "available_parameters": ["staEqu"],
                "required_parameters": ["staEqu"],
                "remaining_required_parameters": [] if matrix is not None else ["staEqu"],
                "parameters": [
                    {
                        "name": "staEqu",
                        "data_type": "Real",
                        "is_array": True,
                        "number_dimensions": 2,
                        "size_of_dimensions": dimensions,
                        "required": True,
                        "value": matrix,
                        "description": "Stage-by-equipment requirement matrix",
                        "unit": None,
                        "quantity": None,
                        "overridable": True,
                        "metadata_source": "pinned_modelica_source",
                    }
                ],
                "applied": (
                    [{"name": "staEqu", "value": matrix, "data_type": "Real"}]
                    if matrix is not None
                    else []
                ),
            }
            return {
                "schema": "bactalk.plant-controls-parameter-schema/v1",
                "controller": controller,
                "parameterization": parameterization,
                "library": "LBNL Modelica Buildings Templates.Plants.Controls",
            }
        if controller_id == "MinimumFlow.ControllerDualMode":
            ordered_names = (
                "have_heaWat",
                "have_chiWat",
                "have_pumChiWatPri",
                "have_valInlIso",
                "have_valOutIso",
                "nEqu",
                "nEnaHeaWat",
                "nEnaChiWat",
                "VHeaWat_flow_nominal",
                "VHeaWat_flow_min",
                "VChiWat_flow_nominal",
                "VChiWat_flow_min",
                "k",
                "Ti",
            )
            allowed = set(ordered_names)
            unknown = sorted(set(parameters) - allowed)
            if unknown:
                raise ValueError(
                    "unknown or non-root plant source-equation parameter overrides: "
                    + ", ".join(unknown)
                )

            boolean_names = (
                "have_heaWat",
                "have_chiWat",
                "have_pumChiWatPri",
                "have_valInlIso",
                "have_valOutIso",
            )
            for name in boolean_names:
                if name in parameters and not isinstance(parameters[name], bool):
                    raise ValueError(f"plant parameter {name} requires Boolean")
            have_heating = parameters.get("have_heaWat")
            have_cooling = parameters.get("have_chiWat")
            if have_heating is False and have_cooling is False:
                raise ValueError(
                    "MinimumFlow.ControllerDualMode requires heating, chilled water, or both"
                )
            have_inlet = parameters.get("have_valInlIso")
            have_outlet = parameters.get("have_valOutIso")
            have_chilled_primary = parameters.get(
                "have_pumChiWatPri",
                (not have_heating) if isinstance(have_heating, bool) else None,
            )

            sizes: dict[str, int | None] = {}
            for name in ("nEqu", "nEnaHeaWat", "nEnaChiWat"):
                value = parameters.get(name)
                if value is not None and (
                    isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 64
                ):
                    raise ValueError(f"plant parameter {name} must be an integer from 0 through 64")
                sizes[name] = value
            if sizes["nEqu"] == 0:
                raise ValueError("plant parameter nEqu must be an integer from 1 through 64")
            for mode, name in (
                (have_heating, "nEnaHeaWat"),
                (have_cooling, "nEnaChiWat"),
            ):
                if mode is True and sizes[name] == 0:
                    raise ValueError(
                        f"plant parameter {name} must be an integer from 1 through 64 "
                        "when that loop is present"
                    )

            array_names = (
                "VHeaWat_flow_nominal",
                "VHeaWat_flow_min",
                "VChiWat_flow_nominal",
                "VChiWat_flow_min",
            )
            arrays: dict[str, list[float] | None] = {}
            for name in array_names:
                raw = parameters.get(name)
                if raw is None:
                    arrays[name] = None
                    continue
                if not isinstance(raw, list) or not raw:
                    raise ValueError(f"plant parameter {name} requires a non-empty Real array")
                normalized: list[float] = []
                for index, item in enumerate(raw, start=1):
                    if (
                        isinstance(item, bool)
                        or not isinstance(item, (int, float))
                        or not math.isfinite(float(item))
                    ):
                        raise ValueError(f"plant parameter {name}[{index}] requires finite Real")
                    normalized.append(float(item))
                if sizes["nEqu"] is not None and len(normalized) != sizes["nEqu"]:
                    raise ValueError(
                        f"plant parameter {name} length must equal nEqu={sizes['nEqu']}"
                    )
                arrays[name] = normalized
            for prefix in ("VHeaWat", "VChiWat"):
                nominal = arrays[f"{prefix}_flow_nominal"]
                minimum = arrays[f"{prefix}_flow_min"]
                if nominal is not None and any(value <= 0 for value in nominal):
                    raise ValueError(
                        f"plant parameter {prefix}_flow_nominal values must be positive"
                    )
                if minimum is not None and any(value < 0 for value in minimum):
                    raise ValueError(
                        f"plant parameter {prefix}_flow_min values must be non-negative"
                    )
                if nominal is not None and minimum is not None:
                    for index, (minimum_value, nominal_value) in enumerate(
                        zip(minimum, nominal, strict=True),
                        start=1,
                    ):
                        if minimum_value > nominal_value:
                            raise ValueError(
                                f"plant parameter {prefix}_flow_min[{index}] must not "
                                "exceed nominal flow"
                            )

            gains: dict[str, float] = {}
            for name, default in (("k", 1.0), ("Ti", 0.5)):
                raw = parameters.get(name, default)
                if (
                    isinstance(raw, bool)
                    or not isinstance(raw, (int, float))
                    or not math.isfinite(float(raw))
                    or float(raw) < 1e-13
                ):
                    raise ValueError(f"plant parameter {name} must be finite and >= 1e-13")
                gains[name] = float(raw)

            required = {
                "have_heaWat",
                "have_chiWat",
                "have_valInlIso",
                "have_valOutIso",
                "nEqu",
            }
            if have_heating is True:
                required.update(
                    {
                        "nEnaHeaWat",
                        "VHeaWat_flow_nominal",
                        "VHeaWat_flow_min",
                    }
                )
            if have_cooling is True:
                required.update(
                    {
                        "nEnaChiWat",
                        "VChiWat_flow_nominal",
                        "VChiWat_flow_min",
                    }
                )
            common_primary_pumps = (
                have_heating is True
                and have_cooling is True
                and have_chilled_primary is False
                and have_inlet is False
                and have_outlet is False
            )
            if common_primary_pumps and sizes["nEqu"] is not None:
                for name in ("nEnaHeaWat", "nEnaChiWat"):
                    if sizes[name] is not None and sizes[name] != sizes["nEqu"]:
                        raise ValueError(
                            f"plant parameter {name} must equal nEqu={sizes['nEqu']} "
                            "for common heating/chilled-water primary pumps"
                        )

            values: dict[str, Any] = {
                "have_heaWat": have_heating,
                "have_chiWat": have_cooling,
                "have_pumChiWatPri": have_chilled_primary,
                "have_valInlIso": have_inlet,
                "have_valOutIso": have_outlet,
                "nEqu": sizes["nEqu"],
                "nEnaHeaWat": sizes["nEnaHeaWat"] or 0,
                "nEnaChiWat": sizes["nEnaChiWat"] or 0,
                **arrays,
                **gains,
            }
            data_types = {
                **{name: "Boolean" for name in boolean_names},
                "nEqu": "Integer",
                "nEnaHeaWat": "Integer",
                "nEnaChiWat": "Integer",
                **{name: "Real" for name in array_names},
                "k": "Real",
                "Ti": "Real",
            }
            descriptions = {
                "have_heaWat": "Plant provides a heating-water loop",
                "have_chiWat": "Plant provides a chilled-water loop",
                "have_pumChiWatPri": "Plant has separate primary chilled-water pumps",
                "have_valInlIso": "Use inlet isolation-valve commands to enable each loop",
                "have_valOutIso": "Use outlet isolation-valve commands to enable each loop",
                "nEqu": "Number of reversible or single-mode plant equipment units",
                "nEnaHeaWat": "Heating-loop valve-command or pump-status signal count",
                "nEnaChiWat": "Chilled-loop valve-command or pump-status signal count",
                "VHeaWat_flow_nominal": "Design heating-water flow for each equipment unit",
                "VHeaWat_flow_min": "Minimum heating-water flow for each equipment unit",
                "VChiWat_flow_nominal": "Design chilled-water flow for each equipment unit",
                "VChiWat_flow_min": "Minimum chilled-water flow for each equipment unit",
                "k": "Reverse-acting PI gain for both loops",
                "Ti": "PI integral time constant for both loops",
            }
            records = []
            for name in ordered_names:
                is_array = name in array_names
                records.append(
                    {
                        "name": name,
                        "data_type": data_types[name],
                        "is_array": is_array,
                        "number_dimensions": 1 if is_array else None,
                        "size_of_dimensions": (
                            f"({sizes['nEqu']})" if is_array and sizes["nEqu"] else None
                        ),
                        "required": name in required,
                        "value": values[name],
                        "description": descriptions[name],
                        "unit": "unit:M3-PER-SEC" if is_array else None,
                        "quantity": None,
                        "overridable": True,
                        "metadata_source": "pinned_modelica_source",
                    }
                )
            parameterization = {
                "schema": "bactalk.g36-parameterization/v2",
                "available_parameters": sorted(allowed),
                "required_parameters": sorted(required),
                "remaining_required_parameters": sorted(required - set(parameters)),
                "parameters": records,
                "applied": [
                    {
                        "name": name,
                        "value": values[name],
                        "data_type": data_types[name],
                    }
                    for name in ordered_names
                    if name in parameters
                ],
            }
            return {
                "schema": "bactalk.plant-controls-parameter-schema/v1",
                "controller": controller,
                "parameterization": parameterization,
                "library": "LBNL Modelica Buildings Templates.Plants.Controls",
            }
        if controller_id == "MinimumFlow.Controller":
            allowed = {
                "have_valInlIso",
                "have_valOutIso",
                "nEqu",
                "nEna",
                "V_flow_nominal",
                "V_flow_min",
                "k",
                "Ti",
            }
            unknown = sorted(set(parameters) - allowed)
            if unknown:
                raise ValueError(
                    "unknown or non-root plant source-equation parameter overrides: "
                    + ", ".join(unknown)
                )

            required = {
                "have_valInlIso",
                "have_valOutIso",
                "nEqu",
                "nEna",
                "V_flow_nominal",
                "V_flow_min",
            }
            remaining = sorted(required - set(parameters))
            have_inlet = parameters.get("have_valInlIso")
            have_outlet = parameters.get("have_valOutIso")
            for name, value in (
                ("have_valInlIso", have_inlet),
                ("have_valOutIso", have_outlet),
            ):
                if name in parameters and not isinstance(value, bool):
                    raise ValueError(f"plant parameter {name} requires Boolean")
            sizes: dict[str, int | None] = {}
            for name in ("nEqu", "nEna"):
                value = parameters.get(name)
                if value is not None and (
                    isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 64
                ):
                    raise ValueError(f"plant parameter {name} must be an integer from 1 through 64")
                sizes[name] = value
            arrays: dict[str, list[float] | None] = {}
            for name in ("V_flow_nominal", "V_flow_min"):
                raw = parameters.get(name)
                if raw is None:
                    arrays[name] = None
                    continue
                if not isinstance(raw, list) or not raw:
                    raise ValueError(f"plant parameter {name} requires a non-empty Real array")
                normalized = []
                for index, item in enumerate(raw, start=1):
                    if (
                        isinstance(item, bool)
                        or not isinstance(item, (int, float))
                        or not math.isfinite(float(item))
                    ):
                        raise ValueError(f"plant parameter {name}[{index}] requires finite Real")
                    normalized.append(float(item))
                if sizes["nEqu"] is not None and len(normalized) != sizes["nEqu"]:
                    raise ValueError(
                        f"plant parameter {name} length must equal nEqu={sizes['nEqu']}"
                    )
                arrays[name] = normalized
            if arrays["V_flow_nominal"] is not None and any(
                value <= 0 for value in arrays["V_flow_nominal"]
            ):
                raise ValueError("plant parameter V_flow_nominal values must be positive")
            if arrays["V_flow_min"] is not None and any(
                value < 0 for value in arrays["V_flow_min"]
            ):
                raise ValueError("plant parameter V_flow_min values must be non-negative")
            if arrays["V_flow_min"] is not None and arrays["V_flow_nominal"] is not None:
                for index, (minimum, nominal) in enumerate(
                    zip(
                        arrays["V_flow_min"],
                        arrays["V_flow_nominal"],
                        strict=True,
                    ),
                    start=1,
                ):
                    if minimum > nominal:
                        raise ValueError(
                            f"plant parameter V_flow_min[{index}] must not exceed nominal flow"
                        )
            gains: dict[str, float] = {}
            for name, default in (("k", 1.0), ("Ti", 0.5)):
                raw = parameters.get(name, default)
                if (
                    isinstance(raw, bool)
                    or not isinstance(raw, (int, float))
                    or not math.isfinite(float(raw))
                    or float(raw) < 1e-13
                ):
                    raise ValueError(f"plant parameter {name} must be finite and >= 1e-13")
                gains[name] = float(raw)

            values: dict[str, Any] = {
                "have_valInlIso": have_inlet,
                "have_valOutIso": have_outlet,
                "nEqu": sizes["nEqu"],
                "nEna": sizes["nEna"],
                "V_flow_nominal": arrays["V_flow_nominal"],
                "V_flow_min": arrays["V_flow_min"],
                **gains,
            }
            data_types = {
                "have_valInlIso": "Boolean",
                "have_valOutIso": "Boolean",
                "nEqu": "Integer",
                "nEna": "Integer",
                "V_flow_nominal": "Real",
                "V_flow_min": "Real",
                "k": "Real",
                "Ti": "Real",
            }
            descriptions = {
                "have_valInlIso": "Use inlet isolation-valve commands to enable the loop",
                "have_valOutIso": "Use outlet isolation-valve commands to enable the loop",
                "nEqu": "Number of plant equipment units",
                "nEna": "Number of valve-command or pump-status enable signals",
                "V_flow_nominal": "Design flow rate for each equipment unit",
                "V_flow_min": "Minimum flow rate for each equipment unit",
                "k": "Reverse-acting PI gain",
                "Ti": "PI integral time constant",
            }
            records = []
            for name in (
                "have_valInlIso",
                "have_valOutIso",
                "nEqu",
                "nEna",
                "V_flow_nominal",
                "V_flow_min",
                "k",
                "Ti",
            ):
                is_array = name in {"V_flow_nominal", "V_flow_min"}
                records.append(
                    {
                        "name": name,
                        "data_type": data_types[name],
                        "is_array": is_array,
                        "number_dimensions": 1 if is_array else None,
                        "size_of_dimensions": (
                            f"({sizes['nEqu']})" if is_array and sizes["nEqu"] else None
                        ),
                        "required": name in required,
                        "value": values[name],
                        "description": descriptions[name],
                        "unit": "unit:M3-PER-SEC" if is_array else None,
                        "quantity": None,
                        "overridable": True,
                        "metadata_source": "pinned_modelica_source",
                    }
                )
            parameterization = {
                "schema": "bactalk.g36-parameterization/v2",
                "available_parameters": sorted(allowed),
                "required_parameters": sorted(required),
                "remaining_required_parameters": remaining,
                "parameters": records,
                "applied": [
                    {
                        "name": name,
                        "value": values[name],
                        "data_type": data_types[name],
                    }
                    for name in sorted(parameters)
                ],
            }
            return {
                "schema": "bactalk.plant-controls-parameter-schema/v1",
                "controller": controller,
                "parameterization": parameterization,
                "library": "LBNL Modelica Buildings Templates.Plants.Controls",
            }
        if controller_id in _PLACEHOLDER_CONTROLLERS:
            unknown = sorted(set(parameters) - {"have_inp", "have_inpPh", "u_internal"})
            if unknown:
                raise ValueError(
                    "unknown or non-root plant source-equation parameter overrides: "
                    + ", ".join(unknown)
                )
            have_input = parameters.get("have_inp", True)
            have_placeholder_input = parameters.get("have_inpPh", False)
            if not isinstance(have_input, bool):
                raise ValueError("plant parameter have_inp requires Boolean")
            if not isinstance(have_placeholder_input, bool):
                raise ValueError("plant parameter have_inpPh requires Boolean")
            requires_internal = not have_input and not have_placeholder_input
            internal = parameters.get("u_internal")
            if internal is not None:
                if controller_id == "Utilities.PlaceholderLogical":
                    if not isinstance(internal, bool):
                        raise ValueError("plant parameter u_internal requires Boolean")
                elif controller_id == "Utilities.PlaceholderInteger":
                    if isinstance(internal, bool) or not isinstance(internal, int):
                        raise ValueError("plant parameter u_internal requires Integer")
                else:
                    if (
                        isinstance(internal, bool)
                        or not isinstance(internal, (int, float))
                        or not math.isfinite(float(internal))
                    ):
                        raise ValueError("plant parameter u_internal requires finite Real")
                    internal = float(internal)
            remaining = ["u_internal"] if requires_internal and internal is None else []
            internal_type = (
                "Boolean"
                if controller_id == "Utilities.PlaceholderLogical"
                else "Integer"
                if controller_id == "Utilities.PlaceholderInteger"
                else "Real"
            )
            parameterization = {
                "schema": "bactalk.g36-parameterization/v2",
                "available_parameters": ["have_inp", "have_inpPh", "u_internal"],
                "required_parameters": remaining,
                "remaining_required_parameters": remaining,
                "parameters": [
                    {
                        "name": "have_inp",
                        "data_type": "Boolean",
                        "is_array": False,
                        "number_dimensions": None,
                        "size_of_dimensions": None,
                        "required": False,
                        "value": have_input,
                        "description": "Use the primary input connector",
                        "unit": None,
                        "quantity": None,
                        "overridable": True,
                        "metadata_source": "pinned_modelica_source",
                    },
                    {
                        "name": "have_inpPh",
                        "data_type": "Boolean",
                        "is_array": False,
                        "number_dimensions": None,
                        "size_of_dimensions": None,
                        "required": False,
                        "value": have_placeholder_input,
                        "description": "Use a placeholder input connector",
                        "unit": None,
                        "quantity": None,
                        "overridable": True,
                        "metadata_source": "pinned_modelica_source",
                    },
                    {
                        "name": "u_internal",
                        "data_type": internal_type,
                        "is_array": False,
                        "number_dimensions": None,
                        "size_of_dimensions": None,
                        "required": requires_internal,
                        "value": internal,
                        "description": "Constant placeholder value when no input exists",
                        "unit": None,
                        "quantity": None,
                        "overridable": True,
                        "metadata_source": "pinned_modelica_source",
                    },
                ],
                "applied": [
                    {
                        "name": name,
                        "value": parameters[name],
                        "data_type": (
                            "Boolean" if name in {"have_inp", "have_inpPh"} else internal_type
                        ),
                    }
                    for name in ("have_inp", "have_inpPh", "u_internal")
                    if name in parameters
                ],
            }
            return {
                "schema": "bactalk.plant-controls-parameter-schema/v1",
                "controller": controller,
                "parameterization": parameterization,
                "library": "LBNL Modelica Buildings Templates.Plants.Controls",
            }
        if controller_id == "Utilities.TrueArrayConditional":
            unknown = sorted(set(parameters) - {"nin", "nout"})
            if unknown:
                raise ValueError(
                    "unknown or non-root plant source-equation parameter overrides: "
                    + ", ".join(unknown)
                )

            def bounded_size(name: str, value: Any, *, supplied: bool) -> int:
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError(f"plant parameter {name} requires Integer")
                if supplied and not 1 <= value <= 64:
                    raise ValueError(f"plant parameter {name} must be an integer from 1 through 64")
                return value

            nin = bounded_size("nin", parameters.get("nin", 0), supplied="nin" in parameters)
            nout = bounded_size(
                "nout",
                parameters.get("nout", nin),
                supplied="nout" in parameters,
            )
            if nin > 0 and nout > 0 and nin * nout > 4096:
                raise ValueError("TrueArrayConditional product nin*nout must not exceed 4096")
            parameterization = {
                "schema": "bactalk.g36-parameterization/v2",
                "available_parameters": ["nin", "nout"],
                "required_parameters": ["nin"],
                "remaining_required_parameters": [] if "nin" in parameters else ["nin"],
                "parameters": [
                    {
                        "name": "nin",
                        "data_type": "Integer",
                        "is_array": False,
                        "number_dimensions": None,
                        "size_of_dimensions": None,
                        "required": True,
                        "value": nin,
                        "description": "Size of input priority array",
                        "unit": None,
                        "quantity": None,
                        "overridable": True,
                        "metadata_source": "pinned_modelica_source",
                    },
                    {
                        "name": "nout",
                        "data_type": "Integer",
                        "is_array": False,
                        "number_dimensions": None,
                        "size_of_dimensions": None,
                        "required": False,
                        "value": nout,
                        "description": "Size of output Boolean array; defaults to nin",
                        "unit": None,
                        "quantity": None,
                        "overridable": True,
                        "metadata_source": "pinned_modelica_source",
                    },
                ],
                "applied": [
                    {"name": name, "value": parameters[name], "data_type": "Integer"}
                    for name in ("nin", "nout")
                    if name in parameters
                ],
            }
            return {
                "schema": "bactalk.plant-controls-parameter-schema/v1",
                "controller": controller,
                "parameterization": parameterization,
                "library": "LBNL Modelica Buildings Templates.Plants.Controls",
            }
        specifications: dict[str, tuple[str, Any, bool]] = {
            "Utilities.Initialization": ("yIni", False, False),
            "Utilities.MultiMaxInteger": ("nin", 0, True),
            "Utilities.MultiMinInteger": ("nin", 0, True),
            "Utilities.TimerWithReset": ("t", 0.0, False),
        }
        name, default, required = specifications[controller_id]
        unknown = sorted(set(parameters) - {name})
        if unknown:
            raise ValueError(
                "unknown or non-root plant source-equation parameter overrides: "
                + ", ".join(unknown)
            )
        value = parameters.get(name, default)
        if name == "yIni":
            if not isinstance(value, bool):
                raise ValueError("plant parameter yIni requires Boolean")
            data_type = "Boolean"
        elif name == "nin":
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or (name in parameters and not 1 <= value <= 512)
            ):
                raise ValueError("plant parameter nin must be an integer from 1 through 512")
            data_type = "Integer"
        else:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise ValueError("plant parameter t requires finite numeric")
            value = float(value)
            data_type = "Real"
        remaining = [name] if required and name not in parameters else []
        parameterization = {
            "schema": "bactalk.g36-parameterization/v2",
            "available_parameters": [name],
            "required_parameters": [name] if required else [],
            "remaining_required_parameters": remaining,
            "parameters": [
                {
                    "name": name,
                    "data_type": data_type,
                    "is_array": False,
                    "number_dimensions": None,
                    "size_of_dimensions": None,
                    "required": required,
                    "value": value,
                    "description": "Pinned Modelica source-equation parameter",
                    "unit": "unit:SEC" if name == "t" else None,
                    "quantity": None,
                    "overridable": True,
                    "metadata_source": "pinned_modelica_source",
                }
            ],
            "applied": (
                [{"name": name, "value": value, "data_type": data_type}]
                if name in parameters
                else []
            ),
        }
        return {
            "schema": "bactalk.plant-controls-parameter-schema/v1",
            "controller": controller,
            "parameterization": parameterization,
            "library": "LBNL Modelica Buildings Templates.Plants.Controls",
        }

    def _air_to_water_parameter_schema(
        self,
        controller: dict[str, Any],
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate the compile-time topology of the pinned AWHP plant supervisor."""

        order = (
            "have_heaWat",
            "have_chiWat",
            "is_priOnl",
            "have_hrc_select",
            "have_inpSch",
            "have_valHpInlIso",
            "have_valHpOutIso",
            "have_pumPriHdr",
            "have_pumChiWatPriDed_select",
            "have_pumHeaWatPriVar_select",
            "have_pumChiWatPriVar_select",
            "have_senDpHeaWatRemWir",
            "have_senDpChiWatRemWir",
            "nHp",
            "nPumHeaWatPri",
            "nPumChiWatPri",
            "nPumHeaWatSec",
            "nPumChiWatSec",
            "nSenDpHeaWatRem",
            "nSenDpChiWatRem",
            "staEqu",
            "idxEquAlt",
            "capHeaHp_nominal",
            "capCooHp_nominal",
            "VHeaWatHp_flow_nominal",
            "VHeaWatHp_flow_min",
            "VChiWatHp_flow_nominal",
            "VChiWatHp_flow_min",
            "VHeaWatPri_flow_nominal",
            "VChiWatPri_flow_nominal",
            "VHeaWatSec_flow_nominal",
            "VChiWatSec_flow_nominal",
            "dpHeaWatRemSet_max",
            "dpChiWatRemSet_max",
            "dpHeaWatRemSet_min",
            "dpChiWatRemSet_min",
            "THeaWatSup_nominal",
            "THeaWatSupSet_min",
            "TChiWatSup_nominal",
            "TChiWatSupSet_max",
            "TOutHeaWatLck",
            "TOutChiWatLck",
            "dTOutLck",
            "yPumHeaWatPriSet",
            "yPumChiWatPriSet",
            "yPumHeaWatPri_min",
            "yPumChiWatPri_min",
            "yPumHeaWatSec_min",
            "yPumChiWatSec_min",
            "plrSta",
            "cp_default",
            "rho_default",
            "dTHea",
            "dTCoo",
            "kCtlDpHeaWat",
            "TiCtlDpHeaWat",
            "kCtlDpChiWat",
            "TiCtlDpChiWat",
            "kValMinByp",
            "TiValMinByp",
            "dtRunEna",
            "dtReqDis",
            "dtRunSta",
            "dtOff",
            "dtOffHp",
            "dtVal",
            "dtPri",
            "dtSec",
            "dtRunPumSta",
            "dtRunFaiSafPumSta",
            "dtRunFaiSafLowYPumSta",
            "dVOffUpPumSta",
            "dVOffDowPumSta",
            "dpOffPumSta",
            "yUpPumSta",
            "yDowPumSta",
            "dtDel",
            "dtHol",
            "dtResHeaWat",
            "dtResChiWat",
            "nReqIgnHeaWat",
            "nReqIgnChiWat",
            "nReqResIgnHeaWat",
            "nReqResIgnChiWat",
            "resDpHeaWat_max",
            "resDpChiWat_max",
            "resTHeaWatSup_min",
            "resTChiWatSup_min",
            "res_init",
            "res_min",
            "res_max",
            "rspHeaWat",
            "rspHeaWat_max",
            "rspChiWat",
            "rspChiWat_max",
            "triHeaWat",
            "triChiWat",
            "COPHeaHrc_nominal",
            "TChiWatSupHrc_min",
            "THeaWatSupHrc_max",
            "capCooHrc_min",
            "capHeaHrc_min",
            "have_reqFloHrc",
            "dtLoaHrc",
            "dtTem1Hrc",
            "dtTem2Hrc",
        )
        unknown = sorted(set(parameters) - set(order))
        if unknown:
            raise ValueError(
                "unknown or non-root plant source-equation parameter overrides: "
                + ", ".join(unknown)
            )

        boolean_names = {
            "have_heaWat",
            "have_chiWat",
            "is_priOnl",
            "have_hrc_select",
            "have_inpSch",
            "have_valHpInlIso",
            "have_valHpOutIso",
            "have_pumPriHdr",
            "have_pumChiWatPriDed_select",
            "have_pumHeaWatPriVar_select",
            "have_pumChiWatPriVar_select",
            "have_senDpHeaWatRemWir",
            "have_senDpChiWatRemWir",
            "have_reqFloHrc",
        }
        boolean_defaults = {
            "is_priOnl": False,
            "have_hrc_select": False,
            "have_inpSch": True,
            "have_pumChiWatPriDed_select": False,
            "have_pumHeaWatPriVar_select": True,
            "have_pumChiWatPriVar_select": True,
            "have_senDpHeaWatRemWir": False,
            "have_senDpChiWatRemWir": False,
            "have_reqFloHrc": False,
        }
        values: dict[str, Any] = {}
        for name in boolean_names:
            raw = parameters.get(name, boolean_defaults.get(name))
            if raw is not None and not isinstance(raw, bool):
                raise ValueError(f"plant parameter {name} requires Boolean")
            values[name] = raw
        have_heating = values["have_heaWat"] is True
        have_cooling = values["have_chiWat"] is True
        primary_only = values["is_priOnl"] is True
        if values["have_heaWat"] is False and values["have_chiWat"] is False:
            raise ValueError("HeatPumps.AirToWater requires a heating or cooling loop")
        if values["have_hrc_select"] is True and not (have_heating and have_cooling):
            raise ValueError("sidestream HRC requires both heating and cooling loops")
        if values["have_hrc_select"] is True and primary_only:
            raise ValueError("sidestream HRC is qualified only for primary-secondary plants")
        if (
            values["have_pumPriHdr"] is True
            and values["have_valHpInlIso"] is False
            and values["have_valHpOutIso"] is False
        ):
            raise ValueError("headered primary pumps require heat-pump isolation valves")

        integer_names = {
            "nHp",
            "nPumHeaWatPri",
            "nPumChiWatPri",
            "nPumHeaWatSec",
            "nPumChiWatSec",
            "nSenDpHeaWatRem",
            "nSenDpChiWatRem",
            "nReqIgnHeaWat",
            "nReqIgnChiWat",
            "nReqResIgnHeaWat",
            "nReqResIgnChiWat",
        }
        n_hp = parameters.get("nHp")
        if n_hp is not None and (
            isinstance(n_hp, bool) or not isinstance(n_hp, int) or not 1 <= n_hp <= 24
        ):
            raise ValueError("plant parameter nHp must be an integer from 1 through 24")
        values["nHp"] = n_hp
        integer_defaults = {
            "nPumHeaWatPri": n_hp,
            "nPumChiWatPri": n_hp,
            "nPumHeaWatSec": n_hp,
            "nPumChiWatSec": n_hp,
            "nSenDpHeaWatRem": 1,
            "nSenDpChiWatRem": 1,
            "nReqIgnHeaWat": 0,
            "nReqIgnChiWat": 0,
            "nReqResIgnHeaWat": 2,
            "nReqResIgnChiWat": 2,
        }
        for name, default in integer_defaults.items():
            raw = parameters.get(name, default)
            upper = 24 if name.startswith("nPum") else 52
            lower = 0 if name.startswith("nReq") else 1
            if raw is not None and (
                isinstance(raw, bool) or not isinstance(raw, int) or not lower <= raw <= upper
            ):
                raise ValueError(
                    f"plant parameter {name} must be an integer from {lower} through {upper}"
                )
            values[name] = raw
        if n_hp is not None and values["have_pumPriHdr"] is False:
            if have_heating and values["nPumHeaWatPri"] != n_hp:
                raise ValueError("dedicated heating primary pumps require nPumHeaWatPri=nHp")
            separate_cooling = bool(have_cooling and values["have_pumChiWatPriDed_select"])
            if separate_cooling and values["nPumChiWatPri"] != n_hp:
                raise ValueError("dedicated chilled-water primary pumps require nPumChiWatPri=nHp")

        matrix = (
            self._validated_staging_matrix(parameters["staEqu"]) if "staEqu" in parameters else None
        )
        if matrix is not None and n_hp is not None and len(matrix[0]) != n_hp:
            raise ValueError("plant parameter staEqu width must equal nHp")
        values["staEqu"] = matrix
        alternate_indices: list[int] | None = None
        if matrix is not None:
            derived = [
                index
                for index in range(1, len(matrix[0]) + 1)
                if any(0.0 < row[index - 1] < 1.0 for row in matrix)
            ]
            if len(matrix[0]) == 1:
                derived = [1]
            raw_indices = parameters.get("idxEquAlt", derived)
            if (
                not isinstance(raw_indices, list)
                or any(
                    isinstance(item, bool)
                    or not isinstance(item, int)
                    or not 1 <= item <= len(matrix[0])
                    for item in raw_indices
                )
                or len(raw_indices) != len(set(raw_indices))
            ):
                raise ValueError("plant parameter idxEquAlt requires unique in-range integers")
            if set(raw_indices) != set(derived):
                raise ValueError(
                    "plant parameter idxEquAlt must identify every fractional staging column"
                )
            alternate_indices = list(raw_indices)
        values["idxEquAlt"] = alternate_indices

        array_names = {
            "capHeaHp_nominal",
            "capCooHp_nominal",
            "VHeaWatHp_flow_nominal",
            "VHeaWatHp_flow_min",
            "VChiWatHp_flow_nominal",
            "VChiWatHp_flow_min",
            "dpHeaWatRemSet_max",
            "dpChiWatRemSet_max",
        }
        positive_arrays = {
            "capHeaHp_nominal",
            "capCooHp_nominal",
            "VHeaWatHp_flow_nominal",
            "VChiWatHp_flow_nominal",
            "dpHeaWatRemSet_max",
            "dpChiWatRemSet_max",
        }
        expected_lengths = {
            "capHeaHp_nominal": n_hp,
            "capCooHp_nominal": n_hp,
            "VHeaWatHp_flow_nominal": n_hp,
            "VHeaWatHp_flow_min": n_hp,
            "VChiWatHp_flow_nominal": n_hp,
            "VChiWatHp_flow_min": n_hp,
            "dpHeaWatRemSet_max": values["nSenDpHeaWatRem"],
            "dpChiWatRemSet_max": values["nSenDpChiWatRem"],
        }
        array_defaults: dict[str, Any] = {
            "VHeaWatHp_flow_nominal": [1.0] * n_hp if n_hp else None,
            "VHeaWatHp_flow_min": [0.1] * n_hp if n_hp else None,
            "VChiWatHp_flow_nominal": [1.0] * n_hp if n_hp else None,
            "VChiWatHp_flow_min": [0.1] * n_hp if n_hp else None,
            "dpHeaWatRemSet_max": [100_000.0] * int(values["nSenDpHeaWatRem"] or 0),
            "dpChiWatRemSet_max": [100_000.0] * int(values["nSenDpChiWatRem"] or 0),
        }
        for name in array_names:
            raw = parameters.get(name, array_defaults.get(name))
            if raw is None:
                values[name] = None
                continue
            if not isinstance(raw, list) or not raw:
                raise ValueError(f"plant parameter {name} requires a non-empty Real array")
            expected = expected_lengths[name]
            if expected is not None and len(raw) != expected:
                raise ValueError(f"plant parameter {name} length must be {expected}")
            normalized: list[float] = []
            for index, item in enumerate(raw, start=1):
                if (
                    isinstance(item, bool)
                    or not isinstance(item, (int, float))
                    or not math.isfinite(float(item))
                    or (float(item) <= 0 if name in positive_arrays else float(item) < 0)
                ):
                    relation = "positive" if name in positive_arrays else "non-negative"
                    raise ValueError(f"plant parameter {name}[{index}] must be {relation} finite")
                normalized.append(float(item))
            values[name] = normalized
        for water in ("HeaWat", "ChiWat"):
            nominal = values[f"V{water}Hp_flow_nominal"]
            minimum = values[f"V{water}Hp_flow_min"]
            if (
                nominal is not None
                and minimum is not None
                and any(low > design for low, design in zip(minimum, nominal, strict=True))
            ):
                raise ValueError(f"V{water}Hp_flow_min cannot exceed nominal flow")

        numeric_defaults = {
            "VHeaWatPri_flow_nominal": None,
            "VChiWatPri_flow_nominal": None,
            "VHeaWatSec_flow_nominal": 1.0,
            "VChiWatSec_flow_nominal": 1.0,
            "dpHeaWatRemSet_min": 34_470.0,
            "dpChiWatRemSet_min": 34_470.0,
            "THeaWatSup_nominal": 323.15,
            "THeaWatSupSet_min": 298.15,
            "TChiWatSup_nominal": 280.15,
            "TChiWatSupSet_max": 288.15,
            "TOutHeaWatLck": 294.15,
            "TOutChiWatLck": 289.15,
            "dTOutLck": 0.5,
            "yPumHeaWatPriSet": 1.0,
            "yPumChiWatPriSet": 1.0,
            "yPumHeaWatPri_min": 0.1,
            "yPumChiWatPri_min": 0.1,
            "yPumHeaWatSec_min": 0.1,
            "yPumChiWatSec_min": 0.1,
            "plrSta": 0.9,
            "cp_default": 4184.0,
            "rho_default": 996.0,
            "dTHea": 2.5,
            "dTCoo": 1.0,
            "kCtlDpHeaWat": 1.0,
            "TiCtlDpHeaWat": 60.0,
            "kCtlDpChiWat": 1.0,
            "TiCtlDpChiWat": 60.0,
            "kValMinByp": 1.0,
            "TiValMinByp": 60.0,
            "dtRunEna": 900.0,
            "dtReqDis": 180.0,
            "dtRunSta": 900.0,
            "dtOff": 900.0,
            "dtOffHp": 180.0,
            "dtVal": 90.0,
            "dtPri": 900.0,
            "dtSec": 600.0,
            "dtRunPumSta": 600.0,
            "dtRunFaiSafPumSta": 300.0,
            "dtRunFaiSafLowYPumSta": 600.0,
            "dVOffUpPumSta": 0.03,
            "dVOffDowPumSta": 0.03,
            "dpOffPumSta": 10_000.0,
            "yUpPumSta": 0.99,
            "yDowPumSta": 0.4,
            "dtDel": 900.0,
            "dtHol": 900.0,
            "dtResHeaWat": 300.0,
            "dtResChiWat": 300.0,
            "resDpHeaWat_max": 0.5,
            "resDpChiWat_max": 0.5,
            "resTHeaWatSup_min": 0.5,
            "resTChiWatSup_min": 0.5,
            "res_init": 1.0,
            "res_min": 0.0,
            "res_max": 1.0,
            "rspHeaWat": 0.03,
            "rspHeaWat_max": 0.07,
            "rspChiWat": 0.03,
            "rspChiWat_max": 0.07,
            "triHeaWat": -0.02,
            "triChiWat": -0.02,
            "COPHeaHrc_nominal": 4.0,
            "TChiWatSupHrc_min": 277.15,
            "THeaWatSupHrc_max": 333.15,
            "capCooHrc_min": 0.0,
            "capHeaHrc_min": 0.0,
            "dtLoaHrc": 600.0,
            "dtTem1Hrc": 180.0,
            "dtTem2Hrc": 60.0,
        }
        if n_hp:
            for water in ("HeaWat", "ChiWat"):
                key = f"V{water}Pri_flow_nominal"
                numeric_defaults[key] = sum(values[f"V{water}Hp_flow_nominal"] or [])
        bounded_zero_one = {
            "yPumHeaWatPri_min",
            "yPumChiWatPri_min",
            "yPumHeaWatSec_min",
            "yPumChiWatSec_min",
            "plrSta",
            "dVOffUpPumSta",
            "dVOffDowPumSta",
            "yUpPumSta",
            "yDowPumSta",
            "resDpHeaWat_max",
            "resDpChiWat_max",
            "resTHeaWatSup_min",
            "resTChiWatSup_min",
            "res_init",
            "res_min",
            "res_max",
        }
        positive_names = {
            "cp_default",
            "rho_default",
            "dTHea",
            "dTCoo",
            "kCtlDpHeaWat",
            "TiCtlDpHeaWat",
            "kCtlDpChiWat",
            "TiCtlDpChiWat",
            "kValMinByp",
            "TiValMinByp",
            "COPHeaHrc_nominal",
        }
        temperature_names = {
            "THeaWatSup_nominal",
            "THeaWatSupSet_min",
            "TChiWatSup_nominal",
            "TChiWatSupSet_max",
            "TOutHeaWatLck",
            "TOutChiWatLck",
            "TChiWatSupHrc_min",
            "THeaWatSupHrc_max",
        }
        for name, default in numeric_defaults.items():
            raw = parameters.get(name, default)
            if raw is None:
                values[name] = None
                continue
            invalid = (
                isinstance(raw, bool)
                or not isinstance(raw, (int, float))
                or not math.isfinite(float(raw))
                or (name in positive_names and float(raw) <= 0)
                or (name in temperature_names and float(raw) < 273.15)
                or (name in bounded_zero_one and not 0 <= float(raw) <= 1)
                or (
                    name not in positive_names
                    and name not in temperature_names
                    and name not in bounded_zero_one
                    and not name.startswith(("tri", "rsp"))
                    and float(raw) < 0
                )
            )
            if invalid:
                raise ValueError(f"plant parameter {name} violates its finite source bounds")
            values[name] = float(raw)
        for name in ("yPumHeaWatPriSet", "yPumChiWatPriSet"):
            if not 0 <= values[name] <= 2:
                raise ValueError(f"plant parameter {name} must be from 0 through 2")
        for name in ("triHeaWat", "triChiWat"):
            if values[name] > 0:
                raise ValueError(f"plant parameter {name} must be non-positive")
        for name in ("rspHeaWat", "rspHeaWat_max", "rspChiWat", "rspChiWat_max"):
            if values[name] < 0:
                raise ValueError(f"plant parameter {name} must be non-negative")
        if values["COPHeaHrc_nominal"] < 1.1:
            raise ValueError("plant parameter COPHeaHrc_nominal must be at least 1.1")
        if values["dtDel"] <= 0 or values["dtResHeaWat"] < 0.001 or values["dtResChiWat"] < 0.001:
            raise ValueError("plant reset sampling times must satisfy their source minima")
        if values["yDowPumSta"] > values["yUpPumSta"]:
            raise ValueError("pump staging yDowPumSta cannot exceed yUpPumSta")
        for water in ("HeaWat", "ChiWat"):
            if values[f"dp{water}RemSet_min"] > min(values[f"dp{water}RemSet_max"]):
                raise ValueError(f"dp{water}RemSet_min cannot exceed any remote setpoint maximum")
        if values["THeaWatSupSet_min"] > values["THeaWatSup_nominal"]:
            raise ValueError("THeaWatSupSet_min cannot exceed THeaWatSup_nominal")
        if values["TChiWatSupSet_max"] < values["TChiWatSup_nominal"]:
            raise ValueError("TChiWatSupSet_max cannot be below TChiWatSup_nominal")
        if values["res_min"] > values["res_init"] or values["res_init"] > values["res_max"]:
            raise ValueError("plant reset bounds require res_min <= res_init <= res_max")

        required = {
            "have_heaWat",
            "have_chiWat",
            "have_valHpInlIso",
            "have_valHpOutIso",
            "have_pumPriHdr",
            "nHp",
            "staEqu",
        }
        if have_heating:
            required.add("capHeaHp_nominal")
        if have_cooling:
            required.add("capCooHp_nominal")
        remaining = sorted(
            name for name in required if name not in parameters or values.get(name) is None
        )
        array_dimensions = {
            **{name: 1 for name in array_names},
            "idxEquAlt": 1,
            "staEqu": 2,
        }
        records = []
        for name in order:
            value = values.get(name)
            dimensions = array_dimensions.get(name)
            if name == "staEqu" and matrix is not None:
                size = f"({len(matrix)},{len(matrix[0])})"
            elif dimensions == 1 and isinstance(value, list):
                size = f"({len(value)})"
            else:
                size = None
            data_type = (
                "Boolean"
                if name in boolean_names
                else "Integer"
                if name in integer_names or name == "idxEquAlt"
                else "Real"
            )
            records.append(
                {
                    "name": name,
                    "data_type": data_type,
                    "is_array": dimensions is not None,
                    "number_dimensions": dimensions,
                    "size_of_dimensions": size,
                    "required": name in required,
                    "value": value,
                    "description": "Pinned air-to-water heat-pump plant parameter",
                    "unit": "unit:SEC" if name.startswith("dt") or name.startswith("Ti") else None,
                    "quantity": None,
                    "overridable": True,
                    "metadata_source": "pinned_modelica_source",
                }
            )
        parameterization = {
            "schema": "bactalk.g36-parameterization/v2",
            "available_parameters": sorted(order),
            "required_parameters": sorted(required),
            "remaining_required_parameters": remaining,
            "parameters": records,
            "applied": [
                {
                    "name": name,
                    "value": values.get(name),
                    "data_type": (
                        "Boolean"
                        if name in boolean_names
                        else "Integer"
                        if name in integer_names or name == "idxEquAlt"
                        else "Real"
                    ),
                }
                for name in order
                if name in parameters
            ],
        }
        return {
            "schema": "bactalk.plant-controls-parameter-schema/v1",
            "controller": controller,
            "parameterization": parameterization,
            "library": "LBNL Modelica Buildings Templates.Plants.Controls",
        }

    def _source_equation_graph(
        self,
        controller_id: str,
        parameters: dict[str, Any],
    ) -> tuple[ControlGraph, dict[str, Any]]:
        parameter_schema = self._source_equation_parameter_schema(controller_id, parameters)
        parameterization = parameter_schema["parameterization"]
        if parameterization["remaining_required_parameters"]:
            raise G36RequiredParametersError(controller_id, parameterization)
        parameter_values = {item["name"]: item["value"] for item in parameterization["parameters"]}
        value = parameterization["parameters"][0]["value"]
        if controller_id == "Utilities.Initialization":
            graph = ControlGraph(
                name="PlantUtilitiesInitialization",
                blocks=[
                    Block(id="u", kind=BlockKind.BOOLEAN_INPUT, label="u"),
                    Block(
                        id="initialization",
                        kind=BlockKind.BOOLEAN_INITIALIZATION,
                        label="Initialization",
                        config={
                            "initial": value,
                            "semantic_contract": (
                                "Buildings.Templates.Plants.Controls.Utilities.Initialization"
                            ),
                        },
                    ),
                    Block(id="y", kind=BlockKind.BOOLEAN_OUTPUT, label="y"),
                ],
                links=[
                    Link(source="u", target="initialization", target_slot="in"),
                    Link(source="initialization", target="y", target_slot="in"),
                ],
            )
        elif controller_id == "Utilities.TimerWithReset":
            graph = ControlGraph(
                name="PlantUtilitiesTimerWithReset",
                blocks=[
                    Block(id="u", kind=BlockKind.BOOLEAN_INPUT, label="u"),
                    Block(id="reset", kind=BlockKind.BOOLEAN_INPUT, label="reset"),
                    Block(
                        id="timer",
                        kind=BlockKind.TIMER_WITH_RESET,
                        label="Timer with reset",
                        config={
                            "threshold_seconds": value,
                            "semantic_contract": (
                                "Buildings.Templates.Plants.Controls.Utilities.TimerWithReset"
                            ),
                        },
                    ),
                    Block(id="y", kind=BlockKind.NUMERIC_OUTPUT, label="y"),
                    Block(id="passed", kind=BlockKind.BOOLEAN_OUTPUT, label="passed"),
                ],
                links=[
                    Link(source="u", target="timer", target_slot="in"),
                    Link(source="reset", target="timer", target_slot="reset"),
                    Link(source="timer", source_slot="elapsed", target="y", target_slot="in"),
                    Link(
                        source="timer",
                        source_slot="passed",
                        target="passed",
                        target_slot="in",
                    ),
                ],
            )
        elif controller_id in _PLACEHOLDER_CONTROLLERS:
            is_boolean = controller_id == "Utilities.PlaceholderLogical"
            is_integer = controller_id == "Utilities.PlaceholderInteger"
            have_input = bool(parameter_values["have_inp"])
            have_placeholder_input = bool(parameter_values["have_inpPh"])
            output_kind = BlockKind.BOOLEAN_OUTPUT if is_boolean else BlockKind.NUMERIC_OUTPUT
            blocks: list[Block]
            links: list[Link]
            if have_input:
                blocks = [
                    Block(
                        id="u",
                        kind=(BlockKind.BOOLEAN_INPUT if is_boolean else BlockKind.NUMERIC_INPUT),
                        label="u",
                    ),
                    Block(id="y", kind=output_kind, label="y"),
                ]
                links = [Link(source="u", target="y", target_slot="in")]
            elif have_placeholder_input:
                blocks = [
                    Block(
                        id="uPh",
                        kind=(BlockKind.BOOLEAN_INPUT if is_boolean else BlockKind.NUMERIC_INPUT),
                        label="uPh",
                    ),
                    Block(id="y", kind=output_kind, label="y"),
                ]
                links = [Link(source="uPh", target="y", target_slot="in")]
            else:
                internal = parameter_values["u_internal"]
                blocks = [
                    Block(
                        id="ph",
                        kind=(BlockKind.BOOLEAN_CONST if is_boolean else BlockKind.NUMERIC_CONST),
                        label="Internal placeholder",
                        config={"value": internal},
                    ),
                    Block(id="y", kind=output_kind, label="y"),
                ]
                links = [Link(source="ph", target="y", target_slot="in")]
            graph = ControlGraph(
                name=(
                    "PlantUtilitiesPlaceholderLogical"
                    if is_boolean
                    else "PlantUtilitiesPlaceholderInteger"
                    if is_integer
                    else "PlantUtilitiesPlaceholderReal"
                ),
                blocks=blocks,
                links=links,
            )
        elif controller_id == "StagingRotation.StageAvailability":
            graph = self._stage_availability_graph(parameter_values["staEqu"])
        elif controller_id == "Utilities.StageIndex":
            graph = self._stage_index_graph(parameter_values)
        elif controller_id == "StagingRotation.SortRuntime":
            graph = self._sort_runtime_graph(parameter_values)
        elif controller_id == "Pumps.Generic.StagingHeaderedDeltaP":
            graph = self._staging_headered_delta_p_graph(parameter_values)
        elif controller_id == "StagingRotation.StageChangeCommand":
            graph = self._stage_change_command_graph(parameter_values)
        elif controller_id == "Pumps.Generic.StagingHeadered":
            graph = self._staging_headered_graph(parameter_values)
        elif controller_id == "Pumps.Primary.VariableSpeed":
            graph = self._primary_variable_speed_graph(parameter_values)
        elif controller_id == "HeatPumps.AirToWater":
            graph = self._air_to_water_graph(parameter_values)
        elif controller_id == "StagingRotation.EquipmentEnable":
            graph = self._equipment_enable_graph(
                parameter_values["staEqu"],
                int(parameter_values["nEquAlt"]),
            )
        elif controller_id == "StagingRotation.StageCompletion":
            graph = self._stage_completion_graph(int(parameter_values["nin"]))
        elif controller_id == "Enabling.Enable":
            graph = self._plant_enable_graph(parameter_values)
        elif controller_id == "HeatRecoveryChillers.Controller":
            graph = self._hrc_controller_graph(parameter_values)
        elif controller_id == "HeatRecoveryChillers.Enable":
            graph = self._hrc_enable_graph(parameter_values)
        elif controller_id == "HeatRecoveryChillers.ModeControl":
            graph = self._hrc_mode_control_graph(parameter_values)
        elif controller_id == "StagingRotation.EquipmentAvailability":
            graph = self._equipment_availability_graph(parameter_values)
        elif controller_id == "MinimumFlow.Controller":
            graph = self._minimum_flow_controller_graph(parameter_values)
        elif controller_id == "MinimumFlow.ControllerDualMode":
            graph = self._minimum_flow_dual_mode_graph(parameter_values)
        elif controller_id == "Utilities.TrueArrayConditional":
            graph = self._true_array_conditional_graph(
                nin=int(parameter_values["nin"]),
                nout=int(parameter_values["nout"]),
            )
        else:
            count = int(value)
            kind = (
                BlockKind.MAXIMUM
                if controller_id == "Utilities.MultiMaxInteger"
                else BlockKind.MINIMUM
            )
            blocks = [
                Block(id=f"u__{index}", kind=BlockKind.NUMERIC_INPUT, label=f"u__{index}")
                for index in range(1, count + 1)
            ]
            links: list[Link] = []
            previous = "u__1"
            for index in range(2, count + 1):
                fold = f"fold_{index}"
                blocks.append(Block(id=fold, kind=kind, label=f"Fold {index}"))
                links.extend(
                    [
                        Link(source=previous, target=fold, target_slot="a"),
                        Link(source=f"u__{index}", target=fold, target_slot="b"),
                    ]
                )
                previous = fold
            blocks.append(Block(id="y", kind=BlockKind.NUMERIC_OUTPUT, label="y"))
            links.append(Link(source=previous, target="y", target_slot="in"))
            graph = ControlGraph(
                name=(
                    "PlantUtilitiesMultiMaxInteger"
                    if kind == BlockKind.MAXIMUM
                    else "PlantUtilitiesMultiMinInteger"
                ),
                blocks=blocks,
                links=links,
            )
        return graph, parameterization

    def _air_to_water_graph(self, parameters: dict[str, Any]) -> ControlGraph:
        """Compose the pinned AWHP supervisor from its qualified child controllers."""

        have_heating = bool(parameters["have_heaWat"])
        have_cooling = bool(parameters["have_chiWat"])
        primary_only = bool(parameters["is_priOnl"])
        headered_primary = bool(parameters["have_pumPriHdr"])
        separate_chilled = bool(
            have_cooling and (headered_primary or bool(parameters["have_pumChiWatPriDed_select"]))
        )
        have_hrc = bool(parameters["have_hrc_select"])
        n_hp = int(parameters["nHp"])
        matrix = parameters["staEqu"]
        n_stage = len(matrix)
        alternate_indices = list(parameters["idxEquAlt"])
        blocks: list[Block] = [
            Block(
                id="always_true",
                kind=BlockKind.BOOLEAN_CONST,
                label="True",
                config={"value": True},
            ),
            Block(
                id="always_false",
                kind=BlockKind.BOOLEAN_CONST,
                label="False",
                config={"value": False},
            ),
            Block(id="zero", kind=BlockKind.NUMERIC_CONST, label="Zero", config={"value": 0.0}),
        ]
        links: list[Link] = []
        block_ids = {block.id for block in blocks}
        relay_ids: set[str] = set()

        def external(identifier: str, *, boolean: bool) -> tuple[str, str]:
            if identifier not in block_ids:
                blocks.append(
                    Block(
                        id=identifier,
                        kind=BlockKind.BOOLEAN_INPUT if boolean else BlockKind.NUMERIC_INPUT,
                        label=identifier,
                    )
                )
                block_ids.add(identifier)
            return identifier, "out"

        def boolean_relay(identifier: str) -> tuple[str, str]:
            blocks.append(
                Block(
                    id=identifier,
                    kind=BlockKind.BOOLEAN_PRE_HOST_TICK,
                    label=identifier,
                    config={
                        "initial": False,
                        "semantic_contract": "CDL.Logical.Pre",
                        "execution_profile": "host_tick_v1",
                    },
                )
            )
            block_ids.add(identifier)
            relay_ids.add(identifier)
            return identifier, "out"

        def numeric_relay(identifier: str) -> tuple[str, str]:
            blocks.append(
                Block(
                    id=identifier,
                    kind=BlockKind.NUMERIC_UNIT_DELAY,
                    label=identifier,
                    config={
                        "sample_period_seconds": 0.001,
                        "initial": 0.0,
                        "semantic_contract": "CDL.Discrete.UnitDelay",
                    },
                )
            )
            block_ids.add(identifier)
            relay_ids.add(identifier)
            return identifier, "out"

        def feed(source: tuple[str, str], target: str, slot: str = "a") -> None:
            if target in relay_ids and slot == "a":
                slot = "in"
            links.append(
                Link(
                    source=source[0],
                    source_slot=source[1],
                    target=target,
                    target_slot=slot,
                )
            )

        def merge_graph(
            child: ControlGraph,
            prefix: str,
            input_map: dict[str, tuple[str, str]],
        ) -> dict[str, tuple[str, str]]:
            id_map: dict[str, str] = {}
            input_blocks = {
                block.id: block
                for block in child.blocks
                if block.kind in {BlockKind.BOOLEAN_INPUT, BlockKind.NUMERIC_INPUT}
            }
            output_ids = {
                block.id
                for block in child.blocks
                if block.kind in {BlockKind.BOOLEAN_OUTPUT, BlockKind.NUMERIC_OUTPUT}
            }
            missing = sorted(set(input_blocks) - set(input_map))
            if missing:
                raise ValueError(
                    f"internal {prefix} composition omitted inputs: {', '.join(missing)}"
                )
            for block in child.blocks:
                if block.id in input_blocks or block.id in output_ids:
                    continue
                identifier = f"{prefix}__{block.id}"
                if identifier in block_ids:
                    raise ValueError(f"duplicate internal AWHP component {identifier}")
                id_map[block.id] = identifier
                blocks.append(
                    Block(
                        id=identifier,
                        kind=block.kind,
                        label=f"{prefix}: {block.label}",
                        config=dict(block.config),
                        x=block.x,
                        y=block.y,
                    )
                )
                block_ids.add(identifier)
            outputs: dict[str, tuple[str, str]] = {}
            for link in child.links:
                if link.source in input_map:
                    source, source_slot = input_map[link.source]
                else:
                    source = id_map[link.source]
                    source_slot = link.source_slot
                if link.target in output_ids:
                    outputs[link.target] = (source, source_slot)
                    continue
                links.append(
                    Link(
                        source=source,
                        source_slot=source_slot,
                        target=id_map[link.target],
                        target_slot=link.target_slot,
                    )
                )
            if set(outputs) != output_ids:
                raise ValueError(f"internal {prefix} composition omitted outputs")
            return outputs

        def child_graph(controller_id: str, child_parameters: dict[str, Any]) -> ControlGraph:
            translation = self.translate(controller_id, parameters=child_parameters)
            return ControlGraph.model_validate(translation["typed_ir"])

        def expose(
            name: str,
            source: tuple[str, str],
            *,
            boolean: bool,
        ) -> None:
            if name in block_ids:
                raise ValueError(f"duplicate AWHP output {name}")
            blocks.append(
                Block(
                    id=name,
                    kind=BlockKind.BOOLEAN_OUTPUT if boolean else BlockKind.NUMERIC_OUTPUT,
                    label=name,
                )
            )
            block_ids.add(name)
            feed(source, name, "in")

        def input_map_for(
            child: ControlGraph,
            explicit: dict[str, tuple[str, str]],
        ) -> dict[str, tuple[str, str]]:
            result = dict(explicit)
            for block in child.blocks:
                if block.kind not in {BlockKind.BOOLEAN_INPUT, BlockKind.NUMERIC_INPUT}:
                    continue
                if block.id not in result:
                    result[block.id] = external(
                        block.id,
                        boolean=block.kind == BlockKind.BOOLEAN_INPUT,
                    )
            return result

        external("TOut", boolean=False)
        for equipment in range(1, n_hp + 1):
            external(f"u1Hp_actual__{equipment}", boolean=True)

        mode_names = [
            name for name, active in (("HeaWat", have_heating), ("ChiWat", have_cooling)) if active
        ]
        mode_enabled: dict[str, tuple[str, str]] = {}
        equipment_command_relay: dict[str, list[tuple[str, str]]] = {}
        equipment_available: dict[str, list[tuple[str, str]]] = {mode: [] for mode in mode_names}
        stage_available: dict[str, list[tuple[str, str]]] = {}
        stage_index: dict[str, tuple[str, str]] = {}
        stage_complete: dict[str, tuple[str, str]] = {}
        supply_setpoint: dict[str, tuple[str, str]] = {}
        event_outputs: dict[int, dict[str, tuple[str, str]]] = {}

        for water in mode_names:
            heating = water == "HeaWat"
            application = "Heating" if heating else "Cooling"
            child = child_graph(
                "Enabling.Enable",
                {
                    "typ": application,
                    "have_inpSch": bool(parameters["have_inpSch"]),
                    "TOutLck": parameters[f"TOut{water}Lck"],
                    "dTOutLck": parameters["dTOutLck"],
                    "nReqIgn": parameters[f"nReqIgn{water}"],
                    "dtRun": parameters["dtRunEna"],
                    "dtReq": parameters["dtReqDis"],
                },
            )
            mapping = {
                "TOut": ("TOut", "out"),
                "nReqPla": external(f"nReqPla{water}", boolean=False),
            }
            if bool(parameters["have_inpSch"]):
                mapping["u1Sch"] = external("u1SchHea" if heating else "u1SchCoo", boolean=True)
            outputs = merge_graph(child, f"enable_{water}", mapping)
            mode_enabled[water] = outputs["y1"]
            equipment_command_relay[water] = [
                boolean_relay(f"{water}_equipment_command_relay_{index}")
                for index in range(1, n_hp + 1)
            ]

        # Equipment availability is the cross-mode mutual-exclusion state machine.
        for equipment in range(1, n_hp + 1):
            child = child_graph(
                "StagingRotation.EquipmentAvailability",
                {
                    "have_heaWat": have_heating,
                    "have_chiWat": have_cooling,
                    "dtOff": parameters["dtOff"],
                },
            )
            mapping = {"u1Ava": ("always_true", "out")}
            if have_heating:
                mapping["u1EnaHea"] = equipment_command_relay["HeaWat"][equipment - 1]
            if have_cooling:
                mapping["u1EnaCoo"] = equipment_command_relay["ChiWat"][equipment - 1]
            outputs = merge_graph(child, f"availability_hp_{equipment}", mapping)
            if have_heating:
                equipment_available["HeaWat"].append(outputs["y1Hea"])
            if have_cooling:
                equipment_available["ChiWat"].append(outputs["y1Coo"])

        stage_up_relays: dict[str, tuple[str, str]] = {}
        stage_down_relays: dict[str, tuple[str, str]] = {}
        equipment_commands: dict[str, list[tuple[str, str]]] = {}
        runtime_order: dict[str, list[tuple[str, str]]] = {}
        for water in mode_names:
            heating = water == "HeaWat"
            availability_graph = child_graph(
                "StagingRotation.StageAvailability", {"staEqu": matrix}
            )
            availability_map = {
                f"u1Ava__{index}": equipment_available[water][index - 1]
                for index in range(1, n_hp + 1)
            }
            availability_outputs = merge_graph(
                availability_graph,
                f"stage_availability_{water}",
                availability_map,
            )
            stage_available[water] = [
                availability_outputs[f"y1__{index}"] for index in range(1, n_stage + 1)
            ]
            stage_up_relays[water] = boolean_relay(f"{water}_stage_up_relay")
            stage_down_relays[water] = boolean_relay(f"{water}_stage_down_relay")
            index_graph = child_graph(
                "Utilities.StageIndex",
                {
                    "nSta": n_stage,
                    "dtRun": parameters["dtRunSta"],
                    "have_inpAva": True,
                },
            )
            index_map = {
                "u1Lea": mode_enabled[water],
                "u1Up": stage_up_relays[water],
                "u1Dow": stage_down_relays[water],
                **{
                    f"u1AvaSta__{index}": stage_available[water][index - 1]
                    for index in range(1, n_stage + 1)
                },
            }
            index_outputs = merge_graph(index_graph, f"stage_index_{water}", index_map)
            stage_index[water] = index_outputs["y"]

            if alternate_indices:
                sort_graph = child_graph(
                    "StagingRotation.SortRuntime",
                    {"nin": n_hp, "idxEquAlt": alternate_indices},
                )
                sort_map = {}
                for index in range(1, n_hp + 1):
                    sort_map[f"u1Ava__{index}"] = equipment_available[water][index - 1]
                    sort_map[f"u1Run__{index}"] = (
                        f"u1Hp_actual__{index}",
                        "out",
                    )
                sort_outputs = merge_graph(sort_graph, f"runtime_{water}", sort_map)
                runtime_order[water] = [
                    sort_outputs[f"yIdx__{rank}"] for rank in range(1, len(alternate_indices) + 1)
                ]
            else:
                runtime_order[water] = []

            enable_graph = child_graph("StagingRotation.EquipmentEnable", {"staEqu": matrix})
            enable_map = {
                "uSta": stage_index[water],
                **{
                    f"u1Ava__{index}": equipment_available[water][index - 1]
                    for index in range(1, n_hp + 1)
                },
                **{
                    f"uIdxAltSor__{rank}": runtime_order[water][rank - 1]
                    for rank in range(1, len(alternate_indices) + 1)
                },
            }
            enable_outputs = merge_graph(enable_graph, f"equipment_enable_{water}", enable_map)
            equipment_commands[water] = [
                enable_outputs[f"y1__{index}"] for index in range(1, n_hp + 1)
            ]
            for index, command in enumerate(equipment_commands[water], start=1):
                feed(command, f"{water}_equipment_command_relay_{index}")

        # Pump-prove inputs to each event sequencer are relayed from the pump-bank
        # compositions below, matching the parent Modelica feedback topology.
        event_pump_status_relays: dict[tuple[int, str, str], tuple[str, str]] = {}
        for equipment in range(1, n_hp + 1):
            for water in mode_names:
                if water == "HeaWat" or separate_chilled:
                    event_pump_status_relays[(equipment, water, "Pri")] = boolean_relay(
                        f"event_hp_{equipment}_{water}_primary_pump_status"
                    )
                if not primary_only:
                    event_pump_status_relays[(equipment, water, "Sec")] = boolean_relay(
                        f"event_hp_{equipment}_{water}_secondary_pump_status"
                    )
            child = child_graph(
                "StagingRotation.EventSequencing",
                {
                    "have_heaWat": have_heating,
                    "have_chiWat": have_cooling,
                    "have_valInlIso": bool(parameters["have_valHpInlIso"]),
                    "have_valOutIso": bool(parameters["have_valHpOutIso"]),
                    "have_pumHeaWatPri": have_heating,
                    "have_pumChiWatPri": separate_chilled,
                    "have_pumHeaWatSec": have_heating and not primary_only,
                    "have_pumChiWatSec": have_cooling and not primary_only,
                    "dtVal": parameters["dtVal"],
                    "dtOff": parameters["dtOffHp"],
                },
            )
            mapping: dict[str, tuple[str, str]] = {}
            if have_heating:
                mapping["u1Hea"] = equipment_commands["HeaWat"][equipment - 1]
                mapping["u1PumHeaWatPri_actual"] = event_pump_status_relays[
                    (equipment, "HeaWat", "Pri")
                ]
                if not primary_only:
                    mapping["u1PumHeaWatSec_actual"] = event_pump_status_relays[
                        (equipment, "HeaWat", "Sec")
                    ]
            if have_cooling:
                mapping["u1Coo"] = equipment_commands["ChiWat"][equipment - 1]
                if separate_chilled:
                    mapping["u1PumChiWatPri_actual"] = event_pump_status_relays[
                        (equipment, "ChiWat", "Pri")
                    ]
                if not primary_only:
                    mapping["u1PumChiWatSec_actual"] = event_pump_status_relays[
                        (equipment, "ChiWat", "Sec")
                    ]
            event_outputs[equipment] = merge_graph(child, f"event_hp_{equipment}", mapping)
            expose(f"y1Hp__{equipment}", event_outputs[equipment]["y1"], boolean=True)
            if have_heating and have_cooling:
                expose(
                    f"y1HeaHp__{equipment}",
                    event_outputs[equipment]["y1Hea"],
                    boolean=True,
                )
            for water in mode_names:
                for position, suffix in (("Inl", "InlIso"), ("Out", "OutIso")):
                    if not bool(parameters[f"have_valHp{position}Iso"]):
                        continue
                    child_name = f"y1Val{water}{suffix}"
                    expose(
                        f"y1Val{water}Hp{suffix}__{equipment}",
                        event_outputs[equipment][child_name],
                        boolean=True,
                    )

        # Stage-completion feedback closes the command/status transaction.
        completion_outputs: dict[str, dict[str, tuple[str, str]]] = {}
        for water in mode_names:
            child = child_graph("StagingRotation.StageCompletion", {"nin": n_hp})
            mapping = {"uSta": stage_index[water]}
            for equipment in range(1, n_hp + 1):
                mapping[f"u1__{equipment}"] = event_outputs[equipment]["y1"]
                mapping[f"u1_actual__{equipment}"] = (
                    f"u1Hp_actual__{equipment}",
                    "out",
                )
            completion_outputs[water] = merge_graph(child, f"stage_completion_{water}", mapping)
            stage_complete[water] = completion_outputs[water]["y1"]

        reset_outputs: dict[str, dict[str, tuple[str, str]]] = {}
        for water in mode_names:
            heating = water == "HeaWat"
            child = child_graph(
                "Setpoints.PlantReset",
                {
                    "nSenDpRem": parameters[f"nSenDp{water}Rem"],
                    "dpSet_max": parameters[f"dp{water}RemSet_max"],
                    "dpSet_min": parameters[f"dp{water}RemSet_min"],
                    "TSup_nominal": parameters[f"T{water}Sup_nominal"],
                    "TSupSetLim": parameters[
                        "THeaWatSupSet_min" if heating else "TChiWatSupSet_max"
                    ],
                    "dtDel": parameters["dtDel"],
                    "dtRes": parameters[f"dtRes{water}"],
                    "dtHol": parameters["dtHol"],
                    "nReqResIgn": parameters[f"nReqResIgn{water}"],
                    "resDp_max": parameters[f"resDp{water}_max"],
                    "resTSup_min": parameters[f"resT{water}Sup_min"],
                    "res_init": parameters["res_init"],
                    "res_min": parameters["res_min"],
                    "res_max": parameters["res_max"],
                    "rsp": parameters[f"rsp{water}"],
                    "rsp_max": parameters[f"rsp{water}_max"],
                    "tri": parameters[f"tri{water}"],
                },
            )
            mapping = {
                "nReqRes": external(f"nReqRes{water}", boolean=False),
                "u1Ena": mode_enabled[water],
                "u1StaPro": stage_complete[water],
            }
            reset_outputs[water] = merge_graph(child, f"reset_{water}", mapping)
            supply_setpoint[water] = reset_outputs[water]["TSupSet"]
            expose(f"T{water}SupSet", supply_setpoint[water], boolean=False)
            for equipment in range(1, n_hp + 1):
                expose(
                    f"T{water}SupHpSet__{equipment}",
                    supply_setpoint[water],
                    boolean=False,
                )
            for sensor in range(1, int(parameters[f"nSenDp{water}Rem"]) + 1):
                expose(
                    f"dp{water}RemSet__{sensor}",
                    reset_outputs[water][f"dpSet__{sensor}"],
                    boolean=False,
                )

        # The staging command uses actual load, held load during transitions,
        # source-exact capacity thresholds, and primary/secondary temperature failsafes.
        for water in mode_names:
            heating = water == "HeaWat"
            child = child_graph(
                "StagingRotation.StageChangeCommand",
                {
                    "typ": "Heating" if heating else "Cooling",
                    "have_pumSec": not primary_only,
                    "have_inpPlrSta": False,
                    "plrSta": parameters["plrSta"],
                    "staEqu": matrix,
                    "capEqu": parameters["capHeaHp_nominal" if heating else "capCooHp_nominal"],
                    "dtRun": parameters["dtRunSta"],
                    "cp_default": parameters["cp_default"],
                    "rho_default": parameters["rho_default"],
                    "dT": parameters["dTHea" if heating else "dTCoo"],
                    "dtPri": parameters["dtPri"],
                    "dtSec": parameters["dtSec"],
                },
            )
            mapping = {
                "uSta": stage_index[water],
                "u1StaPro": stage_complete[water],
                "TRet": external(f"T{water}{'Pri' if primary_only else 'Sec'}Ret", boolean=False),
                "TSupSet": supply_setpoint[water],
                "V_flow": external(
                    f"V{water}{'Pri' if primary_only else 'Sec'}_flow", boolean=False
                ),
                "TPriSup": external(f"T{water}PriSup", boolean=False),
                **{
                    f"u1AvaSta__{index}": stage_available[water][index - 1]
                    for index in range(1, n_stage + 1)
                },
            }
            if not primary_only:
                mapping["TSecSup"] = external(f"T{water}SecSup", boolean=False)
            outputs = merge_graph(child, f"stage_change_{water}", mapping)
            feed(outputs["y1Up"], f"{water}_stage_up_relay")
            feed(outputs["y1Dow"], f"{water}_stage_down_relay")

        primary_commands: dict[str, list[tuple[str, str]]] = {}
        primary_status: dict[str, list[tuple[str, str]]] = {}
        primary_speed_relays: dict[str, tuple[str, str]] = {}
        primary_local_setpoint_relays: dict[str, tuple[str, str]] = {}
        for water in mode_names:
            heating = water == "HeaWat"
            if water == "ChiWat" and not separate_chilled:
                continue
            count = int(parameters[f"nPum{water}Pri"])
            actual_root = f"u1Pum{water}Pri_actual"
            primary_status[water] = [
                external(f"{actual_root}__{pump}", boolean=True) for pump in range(1, count + 1)
            ]
            event_request_name = f"y1Pum{water}Pri"
            requests = [
                event_outputs[equipment][event_request_name] for equipment in range(1, n_hp + 1)
            ]
            if headered_primary:
                if primary_only:
                    primary_speed_relays[water] = numeric_relay(f"{water}_primary_speed_relay")
                    if not bool(parameters[f"have_senDp{water}RemWir"]):
                        primary_local_setpoint_relays[water] = numeric_relay(
                            f"{water}_primary_local_dp_setpoint_relay"
                        )
                sensor_count = (
                    int(parameters[f"nSenDp{water}Rem"])
                    if bool(parameters[f"have_senDp{water}RemWir"])
                    else 1
                )
                child_parameters = {
                    "is_pri": True,
                    "is_hdr": True,
                    "is_ctlDp": primary_only,
                    "have_valInlIso": bool(parameters["have_valHpInlIso"]),
                    "have_valOutIso": bool(parameters["have_valHpOutIso"]),
                    "nEqu": n_hp,
                    "nPum": count,
                    "nSenDp": sensor_count,
                    "V_flow_nominal": parameters[f"V{water}Pri_flow_nominal"],
                    "dtRun": parameters["dtRunPumSta"],
                    "dtRunFaiSaf": parameters["dtRunFaiSafPumSta"],
                    "dtRunFaiSafLowY": parameters["dtRunFaiSafLowYPumSta"],
                    "dVOffUp": parameters["dVOffUpPumSta"],
                    "dVOffDow": parameters["dVOffDowPumSta"],
                    "dpOff": parameters["dpOffPumSta"],
                    "yUp": parameters["yUpPumSta"],
                    "yDow": parameters["yDowPumSta"],
                }
                child = child_graph("Pumps.Generic.StagingHeadered", child_parameters)
                mapping = {
                    **{
                        f"u1Pum_actual__{pump}": primary_status[water][pump - 1]
                        for pump in range(1, count + 1)
                    },
                    **{
                        f"u1Pum__{equipment}": requests[equipment - 1]
                        for equipment in range(1, n_hp + 1)
                    },
                }
                if bool(parameters["have_valHpInlIso"]):
                    mapping.update(
                        {
                            f"u1ValInlIso__{equipment}": event_outputs[equipment][
                                f"y1Val{water}InlIso"
                            ]
                            for equipment in range(1, n_hp + 1)
                        }
                    )
                if bool(parameters["have_valHpOutIso"]):
                    mapping.update(
                        {
                            f"u1ValOutIso__{equipment}": event_outputs[equipment][
                                f"y1Val{water}OutIso"
                            ]
                            for equipment in range(1, n_hp + 1)
                        }
                    )
                if primary_only:
                    mapping["V_flow"] = external(f"V{water}Pri_flow", boolean=False)
                    mapping["y"] = primary_speed_relays[water]
                    remote = bool(parameters[f"have_senDp{water}RemWir"])
                    for sensor in range(1, sensor_count + 1):
                        mapping[f"dp__{sensor}"] = external(
                            f"dp{water}{'Rem__' + str(sensor) if remote else 'Loc'}",
                            boolean=False,
                        )
                        mapping[f"dpSet__{sensor}"] = (
                            reset_outputs[water][f"dpSet__{sensor}"]
                            if remote
                            else primary_local_setpoint_relays[water]
                        )
                outputs = merge_graph(child, f"primary_pumps_{water}", mapping)
                primary_commands[water] = [outputs[f"y1__{pump}"] for pump in range(1, count + 1)]
                for equipment in range(1, n_hp + 1):
                    feed(
                        outputs[f"y1_actual__{equipment}"],
                        f"event_hp_{equipment}_{water}_primary_pump_status",
                    )
            else:
                primary_commands[water] = requests
                for equipment in range(1, n_hp + 1):
                    status_water = water if water == "HeaWat" or separate_chilled else "HeaWat"
                    status = primary_status[status_water][equipment - 1]
                    feed(
                        status,
                        f"event_hp_{equipment}_{water}_primary_pump_status",
                    )
            for pump, command in enumerate(primary_commands[water], start=1):
                expose(f"y1Pum{water}Pri__{pump}", command, boolean=True)

        variable_parameters = {
            "have_heaWat": have_heating,
            "have_chiWat": have_cooling,
            "have_pumPriCtlDp": primary_only,
            "have_pumChiWatPriDed": separate_chilled and not headered_primary,
            "have_pumPriHdr": headered_primary,
            "nEqu": n_hp,
            "nPumHeaWatPri": parameters["nPumHeaWatPri"],
            "nPumChiWatPri": parameters["nPumChiWatPri"],
            "yPumHeaWatPriSet": parameters["yPumHeaWatPriSet"],
            "yPumChiWatPriSet": parameters["yPumChiWatPriSet"],
            "have_senDpHeaWatRemWir": parameters["have_senDpHeaWatRemWir"],
            "nSenDpHeaWatRem": parameters["nSenDpHeaWatRem"],
            "yPumHeaWatPri_min": parameters["yPumHeaWatPri_min"],
            "kCtlDpHeaWat": parameters["kCtlDpHeaWat"],
            "TiCtlDpHeaWat": parameters["TiCtlDpHeaWat"],
            "have_senDpChiWatRemWir": parameters["have_senDpChiWatRemWir"],
            "nSenDpChiWatRem": parameters["nSenDpChiWatRem"],
            "yPumChiWatPri_min": parameters["yPumChiWatPri_min"],
            "kCtlDpChiWat": parameters["kCtlDpChiWat"],
            "TiCtlDpChiWat": parameters["TiCtlDpChiWat"],
        }
        variable_graph = child_graph("Pumps.Primary.VariableSpeed", variable_parameters)
        variable_map: dict[str, tuple[str, str]] = {}
        for water in mode_names:
            command_water = water if water == "HeaWat" or separate_chilled else "HeaWat"
            for pump, command in enumerate(primary_commands[command_water], start=1):
                child_name = f"u1Pum{water}Pri__{pump}"
                if any(block.id == child_name for block in variable_graph.blocks):
                    variable_map[child_name] = command
            for pump, status in enumerate(primary_status[command_water], start=1):
                child_name = f"u1Pum{water}Pri_actual__{pump}"
                if any(block.id == child_name for block in variable_graph.blocks):
                    variable_map[child_name] = status
            if have_heating and have_cooling and not separate_chilled:
                for equipment in range(1, n_hp + 1):
                    variable_map[f"u1Hea__{equipment}"] = event_outputs[equipment]["y1Hea"]
            remote = bool(parameters[f"have_senDp{water}RemWir"])
            if primary_only:
                if remote:
                    for sensor in range(1, int(parameters[f"nSenDp{water}Rem"]) + 1):
                        variable_map[f"dp{water}Rem__{sensor}"] = external(
                            f"dp{water}Rem__{sensor}", boolean=False
                        )
                        variable_map[f"dp{water}RemSet__{sensor}"] = reset_outputs[water][
                            f"dpSet__{sensor}"
                        ]
                else:
                    variable_map[f"dp{water}Loc"] = external(f"dp{water}Loc", boolean=False)
                    for sensor in range(1, int(parameters[f"nSenDp{water}Rem"]) + 1):
                        variable_map[f"dp{water}LocSet__{sensor}"] = external(
                            f"dp{water}LocSet__{sensor}", boolean=False
                        )
        variable_outputs = merge_graph(
            variable_graph,
            "primary_variable_speed",
            input_map_for(variable_graph, variable_map),
        )
        for water in mode_names:
            if water == "ChiWat" and not separate_chilled:
                continue
            if primary_only:
                speed_name = f"yPum{water}PriHdr" if headered_primary else f"yPum{water}PriDed__1"
                speed_ref = variable_outputs[speed_name]
                if water in primary_speed_relays:
                    feed(speed_ref, f"{water}_primary_speed_relay")
                local_name = f"dp{water}LocSetMax"
                if water in primary_local_setpoint_relays and local_name in variable_outputs:
                    feed(
                        variable_outputs[local_name],
                        f"{water}_primary_local_dp_setpoint_relay",
                    )
            variable_selected = (
                bool(
                    parameters[
                        "have_pumHeaWatPriVar_select"
                        if water == "HeaWat"
                        else "have_pumChiWatPriVar_select"
                    ]
                )
                or primary_only
            )
            if not variable_selected:
                continue
            if headered_primary:
                expose(
                    f"yPum{water}PriHdr",
                    variable_outputs[f"yPum{water}PriHdr"],
                    boolean=False,
                )
            else:
                output_water = water if water == "HeaWat" or separate_chilled else "HeaWat"
                for pump in range(1, int(parameters[f"nPum{output_water}Pri"]) + 1):
                    key = f"yPum{output_water}PriDed__{pump}"
                    public_key = f"yPum{water}PriDed__{pump}"
                    if key in variable_outputs and public_key not in block_ids:
                        expose(public_key, variable_outputs[key], boolean=False)

        secondary_commands: dict[str, list[tuple[str, str]]] = {}
        if not primary_only:
            for water in mode_names:
                count = int(parameters[f"nPum{water}Sec"])
                remote = bool(parameters[f"have_senDp{water}RemWir"])
                sensor_count = int(parameters[f"nSenDp{water}Rem"])
                statuses = [
                    external(f"u1Pum{water}Sec_actual__{pump}", boolean=True)
                    for pump in range(1, count + 1)
                ]
                control_graph = child_graph(
                    "Pumps.Generic.ControlDifferentialPressure",
                    {
                        "have_senDpRemWir": remote,
                        "nPum": count,
                        "nSenDpRem": sensor_count,
                        "y_min": parameters[f"yPum{water}Sec_min"],
                        "k": parameters[f"kCtlDp{water}"],
                        "Ti": parameters[f"TiCtlDp{water}"],
                    },
                )
                control_map = {
                    f"y1_actual__{pump}": statuses[pump - 1] for pump in range(1, count + 1)
                }
                if remote:
                    for sensor in range(1, sensor_count + 1):
                        control_map[f"dpRem__{sensor}"] = external(
                            f"dp{water}Rem__{sensor}", boolean=False
                        )
                        control_map[f"dpRemSet__{sensor}"] = reset_outputs[water][
                            f"dpSet__{sensor}"
                        ]
                else:
                    control_map["dpLoc"] = external(f"dp{water}Loc", boolean=False)
                    for sensor in range(1, sensor_count + 1):
                        control_map[f"dpLocSet__{sensor}"] = external(
                            f"dp{water}LocSet__{sensor}", boolean=False
                        )
                control_outputs = merge_graph(control_graph, f"secondary_dp_{water}", control_map)
                stage_sensor_count = sensor_count if remote else 1
                stage_graph = child_graph(
                    "Pumps.Generic.StagingHeadered",
                    {
                        "is_pri": False,
                        "is_hdr": True,
                        "is_ctlDp": True,
                        "have_valInlIso": False,
                        "have_valOutIso": False,
                        "nEqu": n_hp,
                        "nPum": count,
                        "nSenDp": stage_sensor_count,
                        "V_flow_nominal": parameters[f"V{water}Sec_flow_nominal"],
                        "dtRun": parameters["dtRunPumSta"],
                        "dtRunFaiSaf": parameters["dtRunFaiSafPumSta"],
                        "dtRunFaiSafLowY": parameters["dtRunFaiSafLowYPumSta"],
                        "dVOffUp": parameters["dVOffUpPumSta"],
                        "dVOffDow": parameters["dVOffDowPumSta"],
                        "dpOff": parameters["dpOffPumSta"],
                        "yUp": parameters["yUpPumSta"],
                        "yDow": parameters["yDowPumSta"],
                    },
                )
                stage_map = {
                    "u1Pla": mode_enabled[water],
                    "V_flow": external(f"V{water}Sec_flow", boolean=False),
                    "y": control_outputs["y"],
                    **{f"u1Pum_actual__{pump}": statuses[pump - 1] for pump in range(1, count + 1)},
                }
                for sensor in range(1, stage_sensor_count + 1):
                    stage_map[f"dp__{sensor}"] = external(
                        f"dp{water}{'Rem__' + str(sensor) if remote else 'Loc'}",
                        boolean=False,
                    )
                    stage_map[f"dpSet__{sensor}"] = (
                        reset_outputs[water][f"dpSet__{sensor}"]
                        if remote
                        else control_outputs["dpLocSetMax"]
                    )
                stage_outputs = merge_graph(stage_graph, f"secondary_pumps_{water}", stage_map)
                secondary_commands[water] = [
                    stage_outputs[f"y1__{pump}"] for pump in range(1, count + 1)
                ]
                for equipment in range(1, n_hp + 1):
                    feed(
                        stage_outputs[f"y1_actual__{equipment}"],
                        f"event_hp_{equipment}_{water}_secondary_pump_status",
                    )
                for pump, command in enumerate(secondary_commands[water], start=1):
                    expose(f"y1Pum{water}Sec__{pump}", command, boolean=True)
                expose(f"yPum{water}Sec", control_outputs["y"], boolean=False)

        if primary_only:
            minimum_parameters = {
                "have_heaWat": have_heating,
                "have_chiWat": have_cooling,
                "have_pumChiWatPri": separate_chilled,
                "have_valInlIso": bool(parameters["have_valHpInlIso"]),
                "have_valOutIso": bool(parameters["have_valHpOutIso"]),
                "nEqu": n_hp,
                "nEnaHeaWat": n_hp,
                "nEnaChiWat": n_hp,
                "VHeaWat_flow_nominal": parameters["VHeaWatHp_flow_nominal"],
                "VHeaWat_flow_min": parameters["VHeaWatHp_flow_min"],
                "VChiWat_flow_nominal": parameters["VChiWatHp_flow_nominal"],
                "VChiWat_flow_min": parameters["VChiWatHp_flow_min"],
                "k": parameters["kValMinByp"],
                "Ti": parameters["TiValMinByp"],
            }
            minimum_graph = child_graph("MinimumFlow.ControllerDualMode", minimum_parameters)
            minimum_map: dict[str, tuple[str, str]] = {}
            for equipment in range(1, n_hp + 1):
                minimum_map[f"u1Equ__{equipment}"] = event_outputs[equipment]["y1"]
                if have_heating and have_cooling:
                    minimum_map[f"u1HeaEqu__{equipment}"] = event_outputs[equipment]["y1Hea"]
                for water in mode_names:
                    for _position, suffix in (("Inl", "InlIso"), ("Out", "OutIso")):
                        child_name = f"u1Val{water}{suffix}__{equipment}"
                        if any(block.id == child_name for block in minimum_graph.blocks):
                            minimum_map[child_name] = event_outputs[equipment][
                                f"y1Val{water}{suffix}"
                            ]
            for water in mode_names:
                minimum_map[f"V{water}Pri_flow"] = external(f"V{water}Pri_flow", boolean=False)
                status_water = water if water == "HeaWat" or separate_chilled else "HeaWat"
                for pump, status in enumerate(primary_status[status_water], start=1):
                    child_name = f"u1Pum{water}Pri_actual__{pump}"
                    if any(block.id == child_name for block in minimum_graph.blocks):
                        minimum_map[child_name] = status
            minimum_outputs = merge_graph(
                minimum_graph,
                "minimum_flow",
                input_map_for(minimum_graph, minimum_map),
            )
            for water in mode_names:
                expose(
                    f"yVal{water}MinByp",
                    minimum_outputs[f"yVal{water}MinByp"],
                    boolean=False,
                )

        if have_hrc:
            hrc_graph = child_graph(
                "HeatRecoveryChillers.Controller",
                {
                    "have_reqFlo": bool(parameters["have_reqFloHrc"]),
                    "TChiWatSup_min": parameters["TChiWatSupHrc_min"],
                    "THeaWatSup_max": parameters["THeaWatSupHrc_max"],
                    "COPHea_nominal": parameters["COPHeaHrc_nominal"],
                    "capCoo_min": parameters["capCooHrc_min"],
                    "capHea_min": parameters["capHeaHrc_min"],
                    "cp_default": parameters["cp_default"],
                    "rho_default": parameters["rho_default"],
                    "dtRun": parameters["dtRunEna"],
                    "dtLoa": parameters["dtLoaHrc"],
                    "dtTem1": parameters["dtTem1Hrc"],
                    "dtTem2": parameters["dtTem2Hrc"],
                },
            )
            hrc_map = {
                "u1Hea": mode_enabled["HeaWat"],
                "u1Coo": mode_enabled["ChiWat"],
                "u1Hrc_actual": external("u1Hrc_actual", boolean=True),
                "THeaWatSupSet": supply_setpoint["HeaWat"],
                "TChiWatSupSet": supply_setpoint["ChiWat"],
                "THeaWatRetUpsHrc": external("THeaWatRetUpsHrc", boolean=False),
                "TChiWatRetUpsHrc": external("TChiWatRetUpsHrc", boolean=False),
                "THeaWatHrcLvg": external("THeaWatSecRet", boolean=False),
                "TChiWatHrcLvg": external("TChiWatSecRet", boolean=False),
                "VHeaWatLoa_flow": external("VHeaWatSec_flow", boolean=False),
                "VChiWatLoa_flow": external("VChiWatSec_flow", boolean=False),
            }
            if bool(parameters["have_reqFloHrc"]):
                hrc_map["u1ReqFloChiWat"] = external("u1ReqFloChiWat", boolean=True)
                hrc_map["u1ReqFloConWat"] = external("u1ReqFloConWat", boolean=True)
            hrc_outputs = merge_graph(hrc_graph, "heat_recovery_chiller", hrc_map)
            for name in ("y1", "y1Coo", "y1PumChiWat", "y1PumHeaWat"):
                expose(
                    {
                        "y1": "y1Hrc",
                        "y1Coo": "y1CooHrc",
                        "y1PumChiWat": "y1PumChiWatHrc",
                        "y1PumHeaWat": "y1PumHeaWatHrc",
                    }[name],
                    hrc_outputs[name],
                    boolean=True,
                )
            expose("THeaWatSupHrcSet", supply_setpoint["HeaWat"], boolean=False)
            expose("TChiWatSupHrcSet", supply_setpoint["ChiWat"], boolean=False)

        return ControlGraph(
            name=(
                f"PlantAirToWater_{n_hp}HP_"
                f"{'PrimaryOnly' if primary_only else 'PrimarySecondary'}_"
                f"{''.join('H' if item == 'HeaWat' else 'C' for item in mode_names)}"
            ),
            blocks=blocks,
            links=links,
            metadata={
                "semantic_contract": ("Buildings.Templates.Plants.Controls.HeatPumps.AirToWater"),
                "source_composition": [
                    "Enabling.Enable",
                    "StagingRotation.EquipmentAvailability",
                    "StagingRotation.StageAvailability",
                    "Utilities.StageIndex",
                    "StagingRotation.EquipmentEnable",
                    "StagingRotation.EventSequencing",
                    "StagingRotation.StageCompletion",
                    "StagingRotation.StageChangeCommand",
                    "Setpoints.PlantReset",
                    "Pumps.Generic.StagingHeadered",
                    "Pumps.Primary.VariableSpeed",
                    *(
                        ["MinimumFlow.ControllerDualMode"]
                        if primary_only
                        else ["Pumps.Generic.ControlDifferentialPressure"]
                    ),
                    *(["HeatRecoveryChillers.Controller"] if have_hrc else []),
                ],
            },
        )

    def _primary_variable_speed_graph(self, parameters: dict[str, Any]) -> ControlGraph:
        have_heating = bool(parameters["have_heaWat"])
        have_cooling = bool(parameters["have_chiWat"])
        control_dp = bool(parameters["have_pumPriCtlDp"])
        headered = bool(parameters["have_pumPriHdr"])
        separate_chilled = bool(
            have_cooling and (headered or bool(parameters["have_pumChiWatPriDed"]))
        )
        common_reversible = have_heating and have_cooling and not separate_chilled
        heating_count = (
            int(parameters["nPumHeaWatPri"]) if parameters["nPumHeaWatPri"] is not None else 0
        )
        cooling_count = int(parameters["nPumChiWatPri"]) if separate_chilled else heating_count
        blocks: list[Block] = [
            Block(
                id="zero",
                kind=BlockKind.NUMERIC_CONST,
                label="Zero speed",
                config={"value": 0.0},
            )
        ]
        links: list[Link] = []

        def merge_graph(
            child: ControlGraph,
            prefix: str,
            input_map: dict[str, tuple[str, str]],
        ) -> dict[str, tuple[str, str]]:
            id_map: dict[str, str] = {}
            output_ids = {
                block.id
                for block in child.blocks
                if block.kind in {BlockKind.BOOLEAN_OUTPUT, BlockKind.NUMERIC_OUTPUT}
            }
            input_ids = {
                block.id
                for block in child.blocks
                if block.kind in {BlockKind.BOOLEAN_INPUT, BlockKind.NUMERIC_INPUT}
            }
            missing = sorted(input_ids - set(input_map))
            if missing:
                raise ValueError(
                    f"internal {prefix} composition omitted inputs: {', '.join(missing)}"
                )
            for block in child.blocks:
                if block.id in input_ids or block.id in output_ids:
                    continue
                identifier = f"{prefix}__{block.id}"
                id_map[block.id] = identifier
                blocks.append(
                    Block(
                        id=identifier,
                        kind=block.kind,
                        label=f"{prefix}: {block.label}",
                        config=dict(block.config),
                        x=block.x,
                        y=block.y,
                    )
                )
            output_refs: dict[str, tuple[str, str]] = {}
            for link in child.links:
                if link.source in input_map:
                    source, source_slot = input_map[link.source]
                else:
                    source = id_map[link.source]
                    source_slot = link.source_slot
                if link.target in output_ids:
                    output_refs[link.target] = (source, source_slot)
                    continue
                links.append(
                    Link(
                        source=source,
                        source_slot=source_slot,
                        target=id_map[link.target],
                        target_slot=link.target_slot,
                    )
                )
            if set(output_refs) != output_ids:
                raise ValueError(f"internal {prefix} composition omitted outputs")
            return output_refs

        def fold_or(sources: list[str], prefix: str) -> str:
            previous = sources[0]
            for index, source in enumerate(sources[1:], start=2):
                identifier = f"{prefix}_{index}"
                blocks.append(Block(id=identifier, kind=BlockKind.OR, label=identifier))
                links.extend(
                    [
                        Link(source=previous, target=identifier, target_slot="a"),
                        Link(source=source, target=identifier, target_slot="b"),
                    ]
                )
                previous = identifier
            return previous

        heating_commands: list[str] = []
        if have_heating or common_reversible:
            for pump in range(1, heating_count + 1):
                identifier = f"u1PumHeaWatPri__{pump}"
                blocks.append(Block(id=identifier, kind=BlockKind.BOOLEAN_INPUT, label=identifier))
                heating_commands.append(identifier)
        cooling_commands: list[str] = []
        if separate_chilled:
            for pump in range(1, cooling_count + 1):
                identifier = f"u1PumChiWatPri__{pump}"
                blocks.append(Block(id=identifier, kind=BlockKind.BOOLEAN_INPUT, label=identifier))
                cooling_commands.append(identifier)

        heating_status: list[tuple[str, str]] = []
        cooling_status: list[tuple[str, str]] = []
        heating_mode_latches: list[str] = []
        if control_dp or common_reversible:
            if common_reversible:
                for pump in range(1, heating_count + 1):
                    status = f"u1PumHeaWatPri_actual__{pump}"
                    mode = f"u1Hea__{pump}"
                    edge = f"common_pump_enable_edge_{pump}"
                    cooling_mode = f"common_cooling_mode_{pump}"
                    heat_edge = f"common_heat_enable_edge_{pump}"
                    cool_edge = f"common_cool_enable_edge_{pump}"
                    heat_latch = f"common_heat_latch_{pump}"
                    cool_latch = f"common_cool_latch_{pump}"
                    heat_status = f"common_heat_status_{pump}"
                    cool_status = f"common_cool_status_{pump}"
                    blocks.extend(
                        [
                            Block(id=mode, kind=BlockKind.BOOLEAN_INPUT, label=mode),
                            Block(
                                id=edge,
                                kind=BlockKind.ONE_SHOT,
                                label=edge,
                                config={"initial": False},
                            ),
                            Block(id=cooling_mode, kind=BlockKind.NOT, label=cooling_mode),
                            Block(id=heat_edge, kind=BlockKind.AND, label=heat_edge),
                            Block(id=cool_edge, kind=BlockKind.AND, label=cool_edge),
                            Block(
                                id=heat_latch,
                                kind=BlockKind.BOOLEAN_SET_RESET,
                                label=heat_latch,
                                config={"semantic_contract": "CDL.Logical.Latch"},
                            ),
                            Block(
                                id=cool_latch,
                                kind=BlockKind.BOOLEAN_SET_RESET,
                                label=cool_latch,
                                config={"semantic_contract": "CDL.Logical.Latch"},
                            ),
                        ]
                    )
                    links.extend(
                        [
                            Link(
                                source=heating_commands[pump - 1],
                                target=edge,
                                target_slot="in",
                            ),
                            Link(source=mode, target=cooling_mode, target_slot="in"),
                            Link(source=edge, target=heat_edge, target_slot="a"),
                            Link(source=mode, target=heat_edge, target_slot="b"),
                            Link(source=edge, target=cool_edge, target_slot="a"),
                            Link(
                                source=cooling_mode,
                                target=cool_edge,
                                target_slot="b",
                            ),
                            Link(
                                source=heat_edge,
                                target=heat_latch,
                                target_slot="set",
                            ),
                            Link(
                                source=cool_edge,
                                target=heat_latch,
                                target_slot="clear",
                            ),
                            Link(
                                source=cool_edge,
                                target=cool_latch,
                                target_slot="set",
                            ),
                            Link(
                                source=heat_edge,
                                target=cool_latch,
                                target_slot="clear",
                            ),
                        ]
                    )
                    heating_mode_latches.append(heat_latch)
                    if control_dp:
                        blocks.extend(
                            [
                                Block(
                                    id=status,
                                    kind=BlockKind.BOOLEAN_INPUT,
                                    label=status,
                                ),
                                Block(
                                    id=heat_status,
                                    kind=BlockKind.AND,
                                    label=heat_status,
                                ),
                                Block(
                                    id=cool_status,
                                    kind=BlockKind.AND,
                                    label=cool_status,
                                ),
                            ]
                        )
                        links.extend(
                            [
                                Link(
                                    source=status,
                                    target=heat_status,
                                    target_slot="a",
                                ),
                                Link(
                                    source=heat_latch,
                                    target=heat_status,
                                    target_slot="b",
                                ),
                                Link(
                                    source=status,
                                    target=cool_status,
                                    target_slot="a",
                                ),
                                Link(
                                    source=cool_latch,
                                    target=cool_status,
                                    target_slot="b",
                                ),
                            ]
                        )
                        heating_status.append((heat_status, "out"))
                        cooling_status.append((cool_status, "out"))
            else:
                if have_heating and control_dp:
                    for pump in range(1, heating_count + 1):
                        identifier = f"u1PumHeaWatPri_actual__{pump}"
                        blocks.append(
                            Block(
                                id=identifier,
                                kind=BlockKind.BOOLEAN_INPUT,
                                label=identifier,
                            )
                        )
                        heating_status.append((identifier, "out"))
                if have_cooling and control_dp:
                    root = "u1PumChiWatPri_actual"
                    for pump in range(1, cooling_count + 1):
                        identifier = f"{root}__{pump}"
                        blocks.append(
                            Block(
                                id=identifier,
                                kind=BlockKind.BOOLEAN_INPUT,
                                label=identifier,
                            )
                        )
                        cooling_status.append((identifier, "out"))

        def add_loop_controller(
            *,
            heating: bool,
            count: int,
            statuses: list[tuple[str, str]],
        ) -> tuple[str, str]:
            water = "HeaWat" if heating else "ChiWat"
            prefix = "heating_dp" if heating else "cooling_dp"
            if not control_dp:
                constant = f"{prefix}_fixed_speed"
                blocks.append(
                    Block(
                        id=constant,
                        kind=BlockKind.NUMERIC_CONST,
                        label=f"{water} fixed pump speed",
                        config={"value": float(parameters[f"yPum{water}PriSet"])},
                    )
                )
                return constant, "out"
            remote = bool(parameters[f"have_senDp{water}RemWir"])
            sensor_count = int(parameters[f"nSenDp{water}Rem"])
            child_parameters = {
                "have_senDpRemWir": remote,
                "nPum": count,
                "nSenDpRem": sensor_count,
                "k": float(parameters[f"kCtlDp{water}"]),
                "Ti": float(parameters[f"TiCtlDp{water}"]),
                "y_min": float(parameters[f"yPum{water}Pri_min"]),
            }
            child_translation = self.translate(
                "Pumps.Generic.ControlDifferentialPressure",
                parameters=child_parameters,
            )
            child = ControlGraph.model_validate(child_translation["typed_ir"])
            input_map = {
                f"y1_actual__{index}": statuses[index - 1] for index in range(1, count + 1)
            }
            if remote:
                for sensor in range(1, sensor_count + 1):
                    for child_root, parent_root in (
                        ("dpRem", f"dp{water}Rem"),
                        ("dpRemSet", f"dp{water}RemSet"),
                    ):
                        child_id = f"{child_root}__{sensor}"
                        parent_id = f"{parent_root}__{sensor}"
                        blocks.append(
                            Block(
                                id=parent_id,
                                kind=BlockKind.NUMERIC_INPUT,
                                label=parent_id,
                            )
                        )
                        input_map[child_id] = (parent_id, "out")
            else:
                local = f"dp{water}Loc"
                blocks.append(Block(id=local, kind=BlockKind.NUMERIC_INPUT, label=local))
                input_map["dpLoc"] = (local, "out")
                for sensor in range(1, sensor_count + 1):
                    child_id = f"dpLocSet__{sensor}"
                    parent_id = f"dp{water}LocSet__{sensor}"
                    blocks.append(
                        Block(
                            id=parent_id,
                            kind=BlockKind.NUMERIC_INPUT,
                            label=parent_id,
                        )
                    )
                    input_map[child_id] = (parent_id, "out")
            outputs = merge_graph(child, prefix, input_map)
            if not remote:
                output_id = f"dp{water}LocSetMax"
                blocks.append(Block(id=output_id, kind=BlockKind.NUMERIC_OUTPUT, label=output_id))
                source, source_slot = outputs["dpLocSetMax"]
                links.append(
                    Link(
                        source=source,
                        source_slot=source_slot,
                        target=output_id,
                        target_slot="in",
                    )
                )
            return outputs["y"]

        heating_speed: tuple[str, str] | None = None
        cooling_speed: tuple[str, str] | None = None
        if have_heating:
            heating_speed = add_loop_controller(
                heating=True,
                count=heating_count,
                statuses=heating_status,
            )
        if have_cooling:
            cooling_speed = add_loop_controller(
                heating=False,
                count=cooling_count,
                statuses=cooling_status,
            )

        def add_outputs(
            *,
            water: str,
            commands: list[str],
            speed: tuple[str, str],
        ) -> None:
            if headered:
                enabled = fold_or(commands, f"any_{water}_pump_enabled")
                selection = f"{water}_headered_speed_selection"
                output = f"yPum{water}PriHdr"
                blocks.extend(
                    [
                        Block(
                            id=selection,
                            kind=BlockKind.NUMERIC_SWITCH,
                            label=selection,
                        ),
                        Block(id=output, kind=BlockKind.NUMERIC_OUTPUT, label=output),
                    ]
                )
                links.extend(
                    [
                        Link(source=enabled, target=selection, target_slot="selector"),
                        Link(
                            source=speed[0],
                            source_slot=speed[1],
                            target=selection,
                            target_slot="when_true",
                        ),
                        Link(source="zero", target=selection, target_slot="when_false"),
                        Link(source=selection, target=output, target_slot="in"),
                    ]
                )
                return
            for index, command in enumerate(commands, start=1):
                selection = f"{water}_dedicated_speed_selection_{index}"
                output = f"yPum{water}PriDed__{index}"
                blocks.extend(
                    [
                        Block(
                            id=selection,
                            kind=BlockKind.NUMERIC_SWITCH,
                            label=selection,
                        ),
                        Block(id=output, kind=BlockKind.NUMERIC_OUTPUT, label=output),
                    ]
                )
                links.extend(
                    [
                        Link(source=command, target=selection, target_slot="selector"),
                        Link(
                            source=speed[0],
                            source_slot=speed[1],
                            target=selection,
                            target_slot="when_true",
                        ),
                        Link(source="zero", target=selection, target_slot="when_false"),
                        Link(source=selection, target=output, target_slot="in"),
                    ]
                )

        if common_reversible:
            assert heating_speed is not None and cooling_speed is not None
            for pump, command in enumerate(heating_commands, start=1):
                mode_speed = f"common_mode_speed_{pump}"
                selection = f"common_dedicated_speed_selection_{pump}"
                output = f"yPumHeaWatPriDed__{pump}"
                blocks.extend(
                    [
                        Block(
                            id=mode_speed,
                            kind=BlockKind.NUMERIC_SWITCH,
                            label=mode_speed,
                        ),
                        Block(
                            id=selection,
                            kind=BlockKind.NUMERIC_SWITCH,
                            label=selection,
                        ),
                        Block(id=output, kind=BlockKind.NUMERIC_OUTPUT, label=output),
                    ]
                )
                links.extend(
                    [
                        Link(
                            source=heating_mode_latches[pump - 1],
                            target=mode_speed,
                            target_slot="selector",
                        ),
                        Link(
                            source=heating_speed[0],
                            source_slot=heating_speed[1],
                            target=mode_speed,
                            target_slot="when_true",
                        ),
                        Link(
                            source=cooling_speed[0],
                            source_slot=cooling_speed[1],
                            target=mode_speed,
                            target_slot="when_false",
                        ),
                        Link(source=command, target=selection, target_slot="selector"),
                        Link(
                            source=mode_speed,
                            target=selection,
                            target_slot="when_true",
                        ),
                        Link(source="zero", target=selection, target_slot="when_false"),
                        Link(source=selection, target=output, target_slot="in"),
                    ]
                )
        else:
            if have_heating and heating_speed is not None:
                add_outputs(
                    water="HeaWat",
                    commands=heating_commands,
                    speed=heating_speed,
                )
            if have_cooling and cooling_speed is not None:
                add_outputs(
                    water="ChiWat",
                    commands=cooling_commands,
                    speed=cooling_speed,
                )
        return ControlGraph(
            name=(
                f"PlantPrimaryVariableSpeed_{int(have_heating)}{int(have_cooling)}_"
                f"{int(headered)}{int(control_dp)}"
            ),
            blocks=blocks,
            links=links,
            metadata={
                "semantic_contract": (
                    "Buildings.Templates.Plants.Controls.Pumps.Primary.VariableSpeed"
                ),
                "heating": have_heating,
                "cooling": have_cooling,
                "headered": headered,
                "differential_pressure_control": control_dp,
                "separate_chilled_water_pumps": separate_chilled,
                "common_reversible_pumps": common_reversible,
            },
        )

    @classmethod
    def _staging_headered_graph(cls, parameters: dict[str, Any]) -> ControlGraph:
        primary = bool(parameters["is_pri"])
        differential_pressure = bool(parameters["is_ctlDp"])
        have_inlet = bool(parameters["have_valInlIso"])
        have_outlet = bool(parameters["have_valOutIso"])
        equipment_count = int(parameters["nEqu"])
        pump_count = int(parameters["nPum"])
        blocks: list[Block] = [
            Block(
                id="true",
                kind=BlockKind.BOOLEAN_CONST,
                label="Always available",
                config={"value": True},
            ),
            Block(
                id="zero",
                kind=BlockKind.NUMERIC_CONST,
                label="Zero",
                config={"value": 0.0},
            ),
            Block(
                id="one",
                kind=BlockKind.NUMERIC_CONST,
                label="One",
                config={"value": 1.0},
            ),
        ]
        links: list[Link] = []
        for pump in range(1, pump_count + 1):
            blocks.extend(
                [
                    Block(
                        id=f"u1Pum_actual__{pump}",
                        kind=BlockKind.BOOLEAN_INPUT,
                        label=f"u1Pum_actual__{pump}",
                    ),
                    Block(
                        id=f"pump_index_{pump}",
                        kind=BlockKind.NUMERIC_CONST,
                        label=f"Pump {pump}",
                        config={"value": float(pump)},
                    ),
                ]
            )

        def merge_graph(
            child: ControlGraph,
            prefix: str,
            input_map: dict[str, tuple[str, str]],
        ) -> dict[str, tuple[str, str]]:
            id_map: dict[str, str] = {}
            output_ids = {
                block.id
                for block in child.blocks
                if block.kind in {BlockKind.BOOLEAN_OUTPUT, BlockKind.NUMERIC_OUTPUT}
            }
            input_ids = {
                block.id
                for block in child.blocks
                if block.kind in {BlockKind.BOOLEAN_INPUT, BlockKind.NUMERIC_INPUT}
            }
            missing = sorted(input_ids - set(input_map))
            if missing:
                raise ValueError(
                    f"internal {prefix} composition omitted inputs: {', '.join(missing)}"
                )
            for block in child.blocks:
                if block.id in input_ids or block.id in output_ids:
                    continue
                identifier = f"{prefix}__{block.id}"
                id_map[block.id] = identifier
                blocks.append(
                    Block(
                        id=identifier,
                        kind=block.kind,
                        label=f"{prefix}: {block.label}",
                        config=dict(block.config),
                        x=block.x,
                        y=block.y,
                    )
                )
            output_refs: dict[str, tuple[str, str]] = {}
            for link in child.links:
                if link.source in input_map:
                    source, source_slot = input_map[link.source]
                else:
                    source = id_map[link.source]
                    source_slot = link.source_slot
                if link.target in output_ids:
                    output_refs[link.target] = (source, source_slot)
                    continue
                links.append(
                    Link(
                        source=source,
                        source_slot=source_slot,
                        target=id_map[link.target],
                        target_slot=link.target_slot,
                    )
                )
            if set(output_refs) != output_ids:
                missing_outputs = sorted(output_ids - set(output_refs))
                raise ValueError(
                    f"internal {prefix} composition omitted outputs: " + ", ".join(missing_outputs)
                )
            return output_refs

        def fold(sources: list[str], kind: BlockKind, prefix: str) -> str:
            previous = sources[0]
            for index, source in enumerate(sources[1:], start=2):
                identifier = f"{prefix}_{index}"
                blocks.append(Block(id=identifier, kind=kind, label=identifier))
                links.extend(
                    [
                        Link(source=previous, target=identifier, target_slot="a"),
                        Link(source=source, target=identifier, target_slot="b"),
                    ]
                )
                previous = identifier
            return previous

        sort_inputs: dict[str, tuple[str, str]] = {}
        for pump in range(1, pump_count + 1):
            sort_inputs[f"u1Run__{pump}"] = (f"u1Pum_actual__{pump}", "out")
            sort_inputs[f"u1Ava__{pump}"] = ("true", "out")
        sort_outputs = merge_graph(
            cls._sort_runtime_graph(
                {
                    "nin": pump_count,
                    "idxEquAlt": list(range(1, pump_count + 1)),
                    "runTim_start": [float(60 + index) for index in range(1, pump_count + 1)],
                }
            ),
            "runtime_sort",
            sort_inputs,
        )
        lead_index, lead_index_slot = sort_outputs["yIdx__1"]
        lead_status = "u1Pum_actual__1"
        for pump in range(2, pump_count + 1):
            match = f"lead_is_pump_{pump}"
            select = f"select_lead_status_{pump}"
            blocks.extend(
                [
                    Block(id=match, kind=BlockKind.EQUAL, label=match),
                    Block(id=select, kind=BlockKind.BOOLEAN_SWITCH, label=select),
                ]
            )
            links.extend(
                [
                    Link(
                        source=lead_index,
                        source_slot=lead_index_slot,
                        target=match,
                        target_slot="a",
                    ),
                    Link(
                        source=f"pump_index_{pump}",
                        target=match,
                        target_slot="b",
                    ),
                    Link(source=match, target=select, target_slot="selector"),
                    Link(
                        source=f"u1Pum_actual__{pump}",
                        target=select,
                        target_slot="when_true",
                    ),
                    Link(source=lead_status, target=select, target_slot="when_false"),
                ]
            )
            lead_status = select

        if primary:
            inlet_sources: list[str] = []
            outlet_sources: list[str] = []
            if have_inlet:
                for equipment in range(1, equipment_count + 1):
                    identifier = f"u1ValInlIso__{equipment}"
                    blocks.append(
                        Block(
                            id=identifier,
                            kind=BlockKind.BOOLEAN_INPUT,
                            label=identifier,
                        )
                    )
                    inlet_sources.append(identifier)
            if have_outlet:
                for equipment in range(1, equipment_count + 1):
                    identifier = f"u1ValOutIso__{equipment}"
                    blocks.append(
                        Block(
                            id=identifier,
                            kind=BlockKind.BOOLEAN_INPUT,
                            label=identifier,
                        )
                    )
                    outlet_sources.append(identifier)
            if not inlet_sources:
                inlet_sources = list(outlet_sources)
            if not outlet_sources:
                outlet_sources = list(inlet_sources)
            valve_sources = inlet_sources + outlet_sources
            open_valve = fold(valve_sources, BlockKind.OR, "any_valve_open")
            closed_sources = []
            for index, source in enumerate(valve_sources, start=1):
                closed = f"valve_closed_{index}"
                blocks.append(Block(id=closed, kind=BlockKind.NOT, label=closed))
                links.append(Link(source=source, target=closed, target_slot="in"))
                closed_sources.append(closed)
            all_valves_closed = fold(closed_sources, BlockKind.AND, "all_valves_closed")
            blocks.append(
                Block(
                    id="lead_enable_latch",
                    kind=BlockKind.BOOLEAN_SET_RESET,
                    label="Lead primary pump enable",
                    config={"semantic_contract": "CDL.Logical.Latch"},
                )
            )
            links.extend(
                [
                    Link(
                        source=open_valve,
                        target="lead_enable_latch",
                        target_slot="set",
                    ),
                    Link(
                        source=all_valves_closed,
                        target="lead_enable_latch",
                        target_slot="clear",
                    ),
                ]
            )
            lead_enable = ("lead_enable_latch", "out")
        else:
            blocks.append(Block(id="u1Pla", kind=BlockKind.BOOLEAN_INPUT, label="u1Pla"))
            lead_enable = ("u1Pla", "out")

        if differential_pressure:
            blocks.extend(
                [
                    Block(id="V_flow", kind=BlockKind.NUMERIC_INPUT, label="V_flow"),
                    Block(id="y", kind=BlockKind.NUMERIC_INPUT, label="y"),
                ]
            )
            dp_inputs: dict[str, tuple[str, str]] = {
                "V_flow": ("V_flow", "out"),
                "y": ("y", "out"),
            }
            for pump in range(1, pump_count + 1):
                dp_inputs[f"u1_actual__{pump}"] = (
                    f"u1Pum_actual__{pump}",
                    "out",
                )
            for sensor in range(1, int(parameters["nSenDp"]) + 1):
                for root in ("dp", "dpSet"):
                    identifier = f"{root}__{sensor}"
                    blocks.append(
                        Block(
                            id=identifier,
                            kind=BlockKind.NUMERIC_INPUT,
                            label=identifier,
                        )
                    )
                    dp_inputs[identifier] = (identifier, "out")
            delta_outputs = merge_graph(
                cls._staging_headered_delta_p_graph(parameters),
                "delta_p_staging",
                dp_inputs,
            )
            stage_inputs = {
                "u1Lea": lead_enable,
                "u1Up": delta_outputs["y1Up"],
                "u1Dow": delta_outputs["y1Dow"],
            }
            stage_outputs = merge_graph(
                cls._stage_index_graph({"have_inpAva": False, "nSta": pump_count, "dtRun": 0.0}),
                "pump_stage_index",
                stage_inputs,
            )
            stage_source = stage_outputs["y"]
        else:
            count_sources: list[str] = []
            for equipment in range(1, equipment_count + 1):
                command = f"u1Pum__{equipment}"
                number = f"pump_request_number_{equipment}"
                blocks.extend(
                    [
                        Block(
                            id=command,
                            kind=BlockKind.BOOLEAN_INPUT,
                            label=command,
                        ),
                        Block(id=number, kind=BlockKind.NUMERIC_SWITCH, label=number),
                    ]
                )
                links.extend(
                    [
                        Link(source=command, target=number, target_slot="selector"),
                        Link(source="one", target=number, target_slot="when_true"),
                        Link(source="zero", target=number, target_slot="when_false"),
                    ]
                )
                count_sources.append(number)
            requested_count = fold(count_sources, BlockKind.ADD, "requested_pump_count")
            blocks.extend(
                [
                    Block(
                        id="lead_enable_number",
                        kind=BlockKind.NUMERIC_SWITCH,
                        label="Lead enable as number",
                    ),
                    Block(
                        id="enabled_requested_count",
                        kind=BlockKind.MULTIPLY,
                        label="Requested pump count while lead enabled",
                    ),
                ]
            )
            links.extend(
                [
                    Link(
                        source=lead_enable[0],
                        source_slot=lead_enable[1],
                        target="lead_enable_number",
                        target_slot="selector",
                    ),
                    Link(source="one", target="lead_enable_number", target_slot="when_true"),
                    Link(source="zero", target="lead_enable_number", target_slot="when_false"),
                    Link(
                        source=requested_count,
                        target="enabled_requested_count",
                        target_slot="a",
                    ),
                    Link(
                        source="lead_enable_number",
                        target="enabled_requested_count",
                        target_slot="b",
                    ),
                ]
            )
            stage_source = ("enabled_requested_count", "out")

        pump_matrix = [
            [float(stage) / float(pump_count) for _ in range(pump_count)]
            for stage in range(1, pump_count + 1)
        ]
        enable_inputs: dict[str, tuple[str, str]] = {"uSta": stage_source}
        for pump in range(1, pump_count + 1):
            enable_inputs[f"u1Ava__{pump}"] = ("true", "out")
            enable_inputs[f"uIdxAltSor__{pump}"] = sort_outputs[f"yIdx__{pump}"]
        enable_outputs = merge_graph(
            cls._equipment_enable_graph(pump_matrix, pump_count),
            "pump_enable",
            enable_inputs,
        )
        for pump in range(1, pump_count + 1):
            output = f"y1__{pump}"
            blocks.append(Block(id=output, kind=BlockKind.BOOLEAN_OUTPUT, label=output))
            source, source_slot = enable_outputs[output]
            links.append(
                Link(
                    source=source,
                    source_slot=source_slot,
                    target=output,
                    target_slot="in",
                )
            )
        for equipment in range(1, equipment_count + 1):
            output = f"y1_actual__{equipment}"
            blocks.append(Block(id=output, kind=BlockKind.BOOLEAN_OUTPUT, label=output))
            links.append(Link(source=lead_status, target=output, target_slot="in"))
        return ControlGraph(
            name=(
                f"PlantStagingHeadered_{int(primary)}_{int(differential_pressure)}_"
                f"{equipment_count}_{pump_count}"
            ),
            blocks=blocks,
            links=links,
            metadata={
                "semantic_contract": (
                    "Buildings.Templates.Plants.Controls.Pumps.Generic.StagingHeadered"
                ),
                "primary": primary,
                "differential_pressure_control": differential_pressure,
                "equipment_count": equipment_count,
                "pump_count": pump_count,
                "composition": [
                    "StagingRotation.SortRuntime",
                    "StagingRotation.EquipmentEnable",
                    *(
                        [
                            "Pumps.Generic.StagingHeaderedDeltaP",
                            "Utilities.StageIndex",
                        ]
                        if differential_pressure
                        else []
                    ),
                ],
            },
        )

    @staticmethod
    def _staging_headered_delta_p_graph(parameters: dict[str, Any]) -> ControlGraph:
        pump_count = int(parameters["nPum"])
        sensor_count = int(parameters["nSenDp"])
        blocks: list[Block] = [
            Block(id="V_flow", kind=BlockKind.NUMERIC_INPUT, label="V_flow"),
            Block(id="y", kind=BlockKind.NUMERIC_INPUT, label="y"),
            Block(
                id="zero",
                kind=BlockKind.NUMERIC_CONST,
                label="Zero",
                config={"value": 0.0},
            ),
            Block(
                id="one",
                kind=BlockKind.NUMERIC_CONST,
                label="One",
                config={"value": 1.0},
            ),
            Block(
                id="false",
                kind=BlockKind.BOOLEAN_CONST,
                label="False",
                config={"value": False},
            ),
        ]
        links: list[Link] = []

        def numeric_constant(identifier: str, value: float) -> str:
            blocks.append(
                Block(
                    id=identifier,
                    kind=BlockKind.NUMERIC_CONST,
                    label=identifier,
                    config={"value": float(value)},
                )
            )
            return identifier

        flow_nominal = numeric_constant("flow_nominal", parameters["V_flow_nominal"])
        pump_count_constant = numeric_constant("pump_count", float(pump_count))
        up_offset = numeric_constant("up_offset", parameters["dVOffUp"])
        down_offset = numeric_constant(
            "down_offset",
            1.0 / pump_count + float(parameters["dVOffDow"]),
        )
        high_speed_threshold = numeric_constant("high_speed_threshold", parameters["yUp"])
        low_speed_threshold = numeric_constant("low_speed_threshold", parameters["yDow"])
        pressure_threshold = numeric_constant("pressure_threshold", -parameters["dpOff"])

        blocks.extend(
            [
                Block(id="flow_ratio", kind=BlockKind.DIVIDE, label="Flow ratio"),
                Block(
                    id="operating_pump_ratio",
                    kind=BlockKind.DIVIDE,
                    label="Operating pump ratio",
                ),
                Block(
                    id="stage_up_flow_point",
                    kind=BlockKind.SUBTRACT,
                    label="Stage-up flow point",
                ),
                Block(
                    id="stage_down_flow_point",
                    kind=BlockKind.SUBTRACT,
                    label="Stage-down flow point",
                ),
                Block(id="high_flow", kind=BlockKind.GREATER_THAN, label="High flow"),
                Block(id="low_flow", kind=BlockKind.LESS_THAN, label="Low flow"),
                Block(id="high_speed", kind=BlockKind.GREATER_THAN, label="High speed"),
                Block(id="low_speed", kind=BlockKind.LESS_THAN, label="Low speed"),
            ]
        )
        links.extend(
            [
                Link(source="V_flow", target="flow_ratio", target_slot="a"),
                Link(source=flow_nominal, target="flow_ratio", target_slot="b"),
                Link(
                    source="operating_pump_ratio",
                    target="stage_up_flow_point",
                    target_slot="a",
                ),
                Link(source=up_offset, target="stage_up_flow_point", target_slot="b"),
                Link(
                    source="operating_pump_ratio",
                    target="stage_down_flow_point",
                    target_slot="a",
                ),
                Link(
                    source=down_offset,
                    target="stage_down_flow_point",
                    target_slot="b",
                ),
                Link(source="flow_ratio", target="high_flow", target_slot="a"),
                Link(
                    source="stage_up_flow_point",
                    target="high_flow",
                    target_slot="b",
                ),
                Link(source="flow_ratio", target="low_flow", target_slot="a"),
                Link(
                    source="stage_down_flow_point",
                    target="low_flow",
                    target_slot="b",
                ),
                Link(source="y", target="high_speed", target_slot="a"),
                Link(
                    source=high_speed_threshold,
                    target="high_speed",
                    target_slot="b",
                ),
                Link(source="y", target="low_speed", target_slot="a"),
                Link(
                    source=low_speed_threshold,
                    target="low_speed",
                    target_slot="b",
                ),
            ]
        )

        def fold(
            sources: list[str],
            kind: BlockKind,
            prefix: str,
            *,
            source_slot: str = "out",
        ) -> str:
            previous = sources[0]
            previous_slot = source_slot
            for index, source in enumerate(sources[1:], start=2):
                identifier = f"{prefix}_{index}"
                blocks.append(Block(id=identifier, kind=kind, label=identifier))
                links.extend(
                    [
                        Link(
                            source=previous,
                            source_slot=previous_slot,
                            target=identifier,
                            target_slot="a",
                        ),
                        Link(
                            source=source,
                            source_slot=source_slot,
                            target=identifier,
                            target_slot="b",
                        ),
                    ]
                )
                previous = identifier
                previous_slot = "out"
            return previous

        status_numeric: list[str] = []
        status_changes: list[str] = []
        for pump in range(1, pump_count + 1):
            status = f"u1_actual__{pump}"
            status_number = f"status_number_{pump}"
            previous_status = f"previous_status_{pump}"
            status_change = f"status_change_{pump}"
            blocks.extend(
                [
                    Block(id=status, kind=BlockKind.BOOLEAN_INPUT, label=status),
                    Block(
                        id=status_number,
                        kind=BlockKind.NUMERIC_SWITCH,
                        label=status_number,
                    ),
                    Block(
                        id=previous_status,
                        kind=BlockKind.BOOLEAN_PRE_HOST_TICK,
                        label=previous_status,
                        config={
                            "initial": False,
                            "semantic_contract": "CDL.Logical.Pre",
                            "execution_profile": "host_tick_v1",
                        },
                    ),
                    Block(id=status_change, kind=BlockKind.XOR, label=status_change),
                ]
            )
            links.extend(
                [
                    Link(source=status, target=status_number, target_slot="selector"),
                    Link(source="one", target=status_number, target_slot="when_true"),
                    Link(source="zero", target=status_number, target_slot="when_false"),
                    Link(source=status, target=previous_status, target_slot="in"),
                    Link(source=status, target=status_change, target_slot="a"),
                    Link(source=previous_status, target=status_change, target_slot="b"),
                ]
            )
            status_numeric.append(status_number)
            status_changes.append(status_change)
        operating_count = fold(status_numeric, BlockKind.ADD, "operating_count")
        any_status_change = fold(status_changes, BlockKind.OR, "any_status_change")
        links.extend(
            [
                Link(
                    source=operating_count,
                    target="operating_pump_ratio",
                    target_slot="a",
                ),
                Link(
                    source=pump_count_constant,
                    target="operating_pump_ratio",
                    target_slot="b",
                ),
            ]
        )

        def timer(identifier: str, source: str, threshold: float) -> str:
            blocks.append(
                Block(
                    id=identifier,
                    kind=BlockKind.TIMER_WITH_RESET,
                    label=identifier,
                    config={
                        "threshold_seconds": float(threshold),
                        "semantic_contract": (
                            "Buildings.Templates.Plants.Controls.Utilities.TimerWithReset"
                        ),
                    },
                )
            )
            links.extend(
                [
                    Link(source=source, target=identifier, target_slot="in"),
                    Link(
                        source=any_status_change,
                        target=identifier,
                        target_slot="reset",
                    ),
                ]
            )
            return identifier

        high_flow_timer = timer("high_flow_timer", "high_flow", parameters["dtRun"])
        low_flow_timer = timer("low_flow_timer", "low_flow", parameters["dtRun"])
        high_speed_timer = timer("high_speed_timer", "high_speed", parameters["dtRunFaiSaf"])
        low_speed_timer = timer("low_speed_timer", "low_speed", parameters["dtRunFaiSafLowY"])
        low_pressure_timers: list[str] = []
        high_pressure_timers: list[str] = []
        for sensor in range(1, sensor_count + 1):
            measurement = f"dp__{sensor}"
            setpoint = f"dpSet__{sensor}"
            error = f"pressure_error_{sensor}"
            low_pressure = f"low_pressure_{sensor}"
            high_pressure = f"high_pressure_{sensor}"
            blocks.extend(
                [
                    Block(
                        id=measurement,
                        kind=BlockKind.NUMERIC_INPUT,
                        label=measurement,
                    ),
                    Block(id=setpoint, kind=BlockKind.NUMERIC_INPUT, label=setpoint),
                    Block(id=error, kind=BlockKind.SUBTRACT, label=error),
                    Block(id=low_pressure, kind=BlockKind.LESS_THAN, label=low_pressure),
                    Block(
                        id=high_pressure,
                        kind=BlockKind.GREATER_THAN,
                        label=high_pressure,
                    ),
                ]
            )
            links.extend(
                [
                    Link(source=measurement, target=error, target_slot="a"),
                    Link(source=setpoint, target=error, target_slot="b"),
                    Link(source=error, target=low_pressure, target_slot="a"),
                    Link(
                        source=pressure_threshold,
                        target=low_pressure,
                        target_slot="b",
                    ),
                    Link(source=error, target=high_pressure, target_slot="a"),
                    Link(
                        source=pressure_threshold,
                        target=high_pressure,
                        target_slot="b",
                    ),
                ]
            )
            low_pressure_timers.append(
                timer(
                    f"low_pressure_timer_{sensor}",
                    low_pressure,
                    parameters["dtRunFaiSaf"],
                )
            )
            high_pressure_timers.append(
                timer(
                    f"high_pressure_timer_{sensor}",
                    high_pressure,
                    parameters["dtRunFaiSaf"],
                )
            )
        all_low_pressure = fold(
            low_pressure_timers,
            BlockKind.AND,
            "all_low_pressure",
            source_slot="passed",
        )
        all_high_pressure = fold(
            high_pressure_timers,
            BlockKind.AND,
            "all_high_pressure",
            source_slot="passed",
        )
        blocks.extend(
            [
                Block(
                    id="failsafe_up",
                    kind=BlockKind.AND,
                    label="Failsafe stage up",
                ),
                Block(id="stage_up_condition", kind=BlockKind.OR, label="Stage up"),
                Block(
                    id="efficiency_latch",
                    kind=BlockKind.BOOLEAN_SET_RESET,
                    label="Efficiency cause latch",
                    config={"semantic_contract": "CDL.Logical.Latch"},
                ),
                Block(
                    id="failsafe_latch",
                    kind=BlockKind.BOOLEAN_SET_RESET,
                    label="Failsafe cause latch",
                    config={"semantic_contract": "CDL.Logical.Latch"},
                ),
                Block(
                    id="previous_efficiency_cause",
                    kind=BlockKind.BOOLEAN_PRE_HOST_TICK,
                    label="Previous efficiency cause",
                    config={
                        "initial": False,
                        "semantic_contract": "CDL.Logical.Pre",
                        "execution_profile": "host_tick_v1",
                    },
                ),
                Block(
                    id="previous_failsafe_cause",
                    kind=BlockKind.BOOLEAN_PRE_HOST_TICK,
                    label="Previous failsafe cause",
                    config={
                        "initial": False,
                        "semantic_contract": "CDL.Logical.Pre",
                        "execution_profile": "host_tick_v1",
                    },
                ),
                Block(
                    id="efficiency_down",
                    kind=BlockKind.AND,
                    label="Efficiency stage down",
                ),
                Block(
                    id="failsafe_down_speed_cause",
                    kind=BlockKind.AND,
                    label="Failsafe down speed and cause",
                ),
                Block(
                    id="failsafe_down",
                    kind=BlockKind.AND,
                    label="Failsafe stage down",
                ),
                Block(id="stage_down_condition", kind=BlockKind.OR, label="Stage down"),
                Block(id="stage_up_edge", kind=BlockKind.ONE_SHOT, label="Stage-up edge"),
                Block(
                    id="stage_down_edge",
                    kind=BlockKind.ONE_SHOT,
                    label="Stage-down edge",
                ),
                Block(id="y1Up", kind=BlockKind.BOOLEAN_OUTPUT, label="y1Up"),
                Block(id="y1Dow", kind=BlockKind.BOOLEAN_OUTPUT, label="y1Dow"),
            ]
        )
        links.extend(
            [
                Link(
                    source=high_speed_timer,
                    source_slot="passed",
                    target="failsafe_up",
                    target_slot="a",
                ),
                Link(
                    source=all_low_pressure,
                    source_slot="passed" if sensor_count == 1 else "out",
                    target="failsafe_up",
                    target_slot="b",
                ),
                Link(
                    source=high_flow_timer,
                    source_slot="passed",
                    target="stage_up_condition",
                    target_slot="a",
                ),
                Link(
                    source="failsafe_up",
                    target="stage_up_condition",
                    target_slot="b",
                ),
                Link(
                    source=high_flow_timer,
                    source_slot="passed",
                    target="efficiency_latch",
                    target_slot="set",
                ),
                Link(
                    source="failsafe_up",
                    target="efficiency_latch",
                    target_slot="clear",
                ),
                Link(
                    source="failsafe_up",
                    target="failsafe_latch",
                    target_slot="set",
                ),
                Link(
                    source=high_flow_timer,
                    source_slot="passed",
                    target="failsafe_latch",
                    target_slot="clear",
                ),
                Link(
                    source="efficiency_latch",
                    target="previous_efficiency_cause",
                    target_slot="in",
                ),
                Link(
                    source="failsafe_latch",
                    target="previous_failsafe_cause",
                    target_slot="in",
                ),
                Link(
                    source=low_flow_timer,
                    source_slot="passed",
                    target="efficiency_down",
                    target_slot="a",
                ),
                Link(
                    source="previous_efficiency_cause",
                    target="efficiency_down",
                    target_slot="b",
                ),
                Link(
                    source=low_speed_timer,
                    source_slot="passed",
                    target="failsafe_down_speed_cause",
                    target_slot="a",
                ),
                Link(
                    source="previous_failsafe_cause",
                    target="failsafe_down_speed_cause",
                    target_slot="b",
                ),
                Link(
                    source="failsafe_down_speed_cause",
                    target="failsafe_down",
                    target_slot="a",
                ),
                Link(
                    source=all_high_pressure,
                    source_slot="passed" if sensor_count == 1 else "out",
                    target="failsafe_down",
                    target_slot="b",
                ),
                Link(
                    source="efficiency_down",
                    target="stage_down_condition",
                    target_slot="a",
                ),
                Link(
                    source="failsafe_down",
                    target="stage_down_condition",
                    target_slot="b",
                ),
                Link(
                    source="stage_up_condition",
                    target="stage_up_edge",
                    target_slot="in",
                ),
                Link(source="stage_up_edge", target="y1Up", target_slot="in"),
                Link(
                    source="stage_down_condition",
                    target="stage_down_edge",
                    target_slot="in",
                ),
                Link(source="stage_down_edge", target="y1Dow", target_slot="in"),
            ]
        )
        return ControlGraph(
            name=f"PlantStagingHeaderedDeltaP_{pump_count}_{sensor_count}",
            blocks=blocks,
            links=links,
            metadata={
                "semantic_contract": (
                    "Buildings.Templates.Plants.Controls.Pumps.Generic.StagingHeaderedDeltaP"
                ),
                "pump_count": pump_count,
                "sensor_count": sensor_count,
                "pre_equivalence": (
                    "Status Change and cause-memory Pre blocks observe prior sampled inputs; "
                    "their feedback only gates timer resets or subsequent stage-down events."
                ),
            },
        )

    @staticmethod
    def _stage_change_command_graph(parameters: dict[str, Any]) -> ControlGraph:
        staging_matrix = parameters["staEqu"]
        capacities = [float(value) for value in parameters["capEqu"]]
        stage_count = len(staging_matrix)
        have_secondary = bool(parameters["have_pumSec"])
        have_plr_input = bool(parameters["have_inpPlrSta"])
        application = str(parameters["typ"]).rsplit(".", 1)[-1]
        polarity = -1.0 if application == "Cooling" else 1.0
        stage_capacities = [
            sum(
                float(coefficient) * capacity
                for coefficient, capacity in zip(row, capacities, strict=True)
            )
            for row in staging_matrix
        ]
        comparison_hysteresis = 1e-4 * min(capacities)
        blocks: list[Block] = [
            Block(id="u1StaPro", kind=BlockKind.BOOLEAN_INPUT, label="u1StaPro"),
            Block(id="uSta", kind=BlockKind.NUMERIC_INPUT, label="uSta"),
            Block(id="TRet", kind=BlockKind.NUMERIC_INPUT, label="TRet"),
            Block(id="TSupSet", kind=BlockKind.NUMERIC_INPUT, label="TSupSet"),
            Block(id="V_flow", kind=BlockKind.NUMERIC_INPUT, label="V_flow"),
            Block(id="TPriSup", kind=BlockKind.NUMERIC_INPUT, label="TPriSup"),
            Block(
                id="zero",
                kind=BlockKind.NUMERIC_CONST,
                label="Zero",
                config={"value": 0.0},
            ),
            Block(
                id="one",
                kind=BlockKind.NUMERIC_CONST,
                label="One",
                config={"value": 1.0},
            ),
        ]
        links: list[Link] = []
        if have_secondary:
            blocks.append(Block(id="TSecSup", kind=BlockKind.NUMERIC_INPUT, label="TSecSup"))
        if have_plr_input:
            blocks.append(Block(id="uPlrSta", kind=BlockKind.NUMERIC_INPUT, label="uPlrSta"))
            plr_source = "uPlrSta"
        else:
            blocks.append(
                Block(
                    id="plr_parameter",
                    kind=BlockKind.NUMERIC_CONST,
                    label="Staging part-load ratio",
                    config={"value": float(parameters["plrSta"])},
                )
            )
            plr_source = "plr_parameter"

        for stage in range(1, stage_count + 1):
            blocks.extend(
                [
                    Block(
                        id=f"u1AvaSta__{stage}",
                        kind=BlockKind.BOOLEAN_INPUT,
                        label=f"u1AvaSta__{stage}",
                    ),
                    Block(
                        id=f"stage_index_{stage}",
                        kind=BlockKind.NUMERIC_CONST,
                        label=f"Stage {stage}",
                        config={"value": float(stage)},
                    ),
                    Block(
                        id=f"stage_capacity_{stage}",
                        kind=BlockKind.NUMERIC_CONST,
                        label=f"Stage {stage} design capacity",
                        config={"value": stage_capacities[stage - 1]},
                    ),
                ]
            )

        blocks.extend(
            [
                Block(id="load_delta_t", kind=BlockKind.SUBTRACT, label="Load delta T"),
                Block(
                    id="capacity_factor",
                    kind=BlockKind.NUMERIC_CONST,
                    label="Fluid capacity factor",
                    config={
                        "value": float(parameters["rho_default"]) * float(parameters["cp_default"])
                    },
                ),
                Block(
                    id="load_capacity_flow",
                    kind=BlockKind.MULTIPLY,
                    label="Load capacity flow",
                ),
                Block(id="raw_load", kind=BlockKind.MULTIPLY, label="Raw load"),
                Block(
                    id="load_polarity",
                    kind=BlockKind.NUMERIC_CONST,
                    label="Heating/cooling polarity",
                    config={"value": polarity},
                ),
                Block(id="signed_load", kind=BlockKind.MULTIPLY, label="Signed load"),
                Block(
                    id="average_load",
                    kind=BlockKind.MOVING_AVERAGE,
                    label="Rolling required capacity",
                    config={
                        "window_seconds": float(parameters["dtMea"]),
                        "semantic_contract": "CDL.Reals.MovingAverage",
                    },
                ),
                Block(
                    id="held_load_sample",
                    kind=BlockKind.NUMERIC_LATCH,
                    label="Load at stage-transition start",
                    config={
                        "initial": 0.0,
                        "semantic_contract": "CDL.Discrete.TriggeredSampler",
                    },
                ),
                Block(
                    id="stage_process_hold",
                    kind=BlockKind.BOOLEAN_TRUE_FALSE_HOLD,
                    label="Minimum load-hold duration",
                    config={
                        "true_hold_seconds": float(parameters["dtRun"]),
                        "false_hold_seconds": 0.0,
                    },
                ),
                Block(
                    id="held_or_live_load",
                    kind=BlockKind.NUMERIC_SWITCH,
                    label="Held or live required capacity",
                ),
            ]
        )
        links.extend(
            [
                Link(source="TSupSet", target="load_delta_t", target_slot="a"),
                Link(source="TRet", target="load_delta_t", target_slot="b"),
                Link(source="V_flow", target="load_capacity_flow", target_slot="a"),
                Link(
                    source="capacity_factor",
                    target="load_capacity_flow",
                    target_slot="b",
                ),
                Link(source="load_delta_t", target="raw_load", target_slot="a"),
                Link(
                    source="load_capacity_flow",
                    target="raw_load",
                    target_slot="b",
                ),
                Link(source="raw_load", target="signed_load", target_slot="a"),
                Link(source="load_polarity", target="signed_load", target_slot="b"),
                Link(source="signed_load", target="average_load", target_slot="in"),
                Link(
                    source="average_load",
                    target="held_load_sample",
                    target_slot="in",
                ),
                Link(
                    source="u1StaPro",
                    target="held_load_sample",
                    target_slot="clock",
                ),
                Link(
                    source="u1StaPro",
                    target="stage_process_hold",
                    target_slot="in",
                ),
                Link(
                    source="stage_process_hold",
                    target="held_or_live_load",
                    target_slot="selector",
                ),
                Link(
                    source="held_load_sample",
                    target="held_or_live_load",
                    target_slot="when_true",
                ),
                Link(
                    source="average_load",
                    target="held_or_live_load",
                    target_slot="when_false",
                ),
            ]
        )

        blocks.append(Block(id="active_stage", kind=BlockKind.MAXIMUM, label="Active stage or one"))
        links.extend(
            [
                Link(source="uSta", target="active_stage", target_slot="a"),
                Link(source="one", target="active_stage", target_slot="b"),
            ]
        )

        def select_stage_capacity(prefix: str, selector: str) -> str:
            selected = "stage_capacity_1"
            for stage in range(2, stage_count + 1):
                match = f"{prefix}_is_stage_{stage}"
                switch = f"{prefix}_select_stage_{stage}"
                blocks.extend(
                    [
                        Block(id=match, kind=BlockKind.EQUAL, label=match),
                        Block(id=switch, kind=BlockKind.NUMERIC_SWITCH, label=switch),
                    ]
                )
                links.extend(
                    [
                        Link(source=selector, target=match, target_slot="a"),
                        Link(
                            source=f"stage_index_{stage}",
                            target=match,
                            target_slot="b",
                        ),
                        Link(source=match, target=switch, target_slot="selector"),
                        Link(
                            source=f"stage_capacity_{stage}",
                            target=switch,
                            target_slot="when_true",
                        ),
                        Link(source=selected, target=switch, target_slot="when_false"),
                    ]
                )
                selected = switch
            return selected

        active_capacity = select_stage_capacity("active", "active_stage")
        lower_index = "zero"
        for stage in range(1, stage_count + 1):
            below = f"stage_{stage}_below_active"
            available_below = f"stage_{stage}_available_below"
            choose = f"choose_lower_stage_{stage}"
            blocks.extend(
                [
                    Block(id=below, kind=BlockKind.LESS_THAN, label=below),
                    Block(id=available_below, kind=BlockKind.AND, label=available_below),
                    Block(id=choose, kind=BlockKind.NUMERIC_SWITCH, label=choose),
                ]
            )
            links.extend(
                [
                    Link(source=f"stage_index_{stage}", target=below, target_slot="a"),
                    Link(source="uSta", target=below, target_slot="b"),
                    Link(source=below, target=available_below, target_slot="a"),
                    Link(
                        source=f"u1AvaSta__{stage}",
                        target=available_below,
                        target_slot="b",
                    ),
                    Link(source=available_below, target=choose, target_slot="selector"),
                    Link(
                        source=f"stage_index_{stage}",
                        target=choose,
                        target_slot="when_true",
                    ),
                    Link(source=lower_index, target=choose, target_slot="when_false"),
                ]
            )
            lower_index = choose
        blocks.extend(
            [
                Block(
                    id="lower_stage_or_one",
                    kind=BlockKind.MAXIMUM,
                    label="Next lower stage or one",
                ),
                Block(
                    id="lower_stage_present",
                    kind=BlockKind.MINIMUM,
                    label="One if lower stage exists",
                ),
            ]
        )
        links.extend(
            [
                Link(source=lower_index, target="lower_stage_or_one", target_slot="a"),
                Link(source="one", target="lower_stage_or_one", target_slot="b"),
                Link(source=lower_index, target="lower_stage_present", target_slot="a"),
                Link(source="one", target="lower_stage_present", target_slot="b"),
            ]
        )
        lower_capacity_base = select_stage_capacity("lower", "lower_stage_or_one")
        blocks.append(
            Block(
                id="lower_stage_capacity",
                kind=BlockKind.MULTIPLY,
                label="Available next-lower-stage capacity",
            )
        )
        links.extend(
            [
                Link(
                    source=lower_capacity_base,
                    target="lower_stage_capacity",
                    target_slot="a",
                ),
                Link(
                    source="lower_stage_present",
                    target="lower_stage_capacity",
                    target_slot="b",
                ),
            ]
        )

        blocks.extend(
            [
                Block(
                    id="active_capacity_at_plr",
                    kind=BlockKind.MULTIPLY,
                    label="Active-stage staging threshold",
                ),
                Block(
                    id="lower_capacity_at_plr",
                    kind=BlockKind.MULTIPLY,
                    label="Lower-stage staging threshold",
                ),
                Block(
                    id="up_capacity_margin",
                    kind=BlockKind.SUBTRACT,
                    label="Load above active-stage threshold",
                ),
                Block(
                    id="down_capacity_margin",
                    kind=BlockKind.SUBTRACT,
                    label="Lower-stage threshold above load",
                ),
            ]
        )
        links.extend(
            [
                Link(source=plr_source, target="active_capacity_at_plr", target_slot="a"),
                Link(
                    source=active_capacity,
                    target="active_capacity_at_plr",
                    target_slot="b",
                ),
                Link(source=plr_source, target="lower_capacity_at_plr", target_slot="a"),
                Link(
                    source="lower_stage_capacity",
                    target="lower_capacity_at_plr",
                    target_slot="b",
                ),
                Link(source="held_or_live_load", target="up_capacity_margin", target_slot="a"),
                Link(
                    source="active_capacity_at_plr",
                    target="up_capacity_margin",
                    target_slot="b",
                ),
                Link(
                    source="lower_capacity_at_plr",
                    target="down_capacity_margin",
                    target_slot="a",
                ),
                Link(source="held_or_live_load", target="down_capacity_margin", target_slot="b"),
            ]
        )

        def add_strict_hysteresis(identifier: str, margin: str) -> str:
            if comparison_hysteresis < 1e-10:
                blocks.append(Block(id=identifier, kind=BlockKind.GREATER_THAN, label=identifier))
                links.extend(
                    [
                        Link(source=margin, target=identifier, target_slot="a"),
                        Link(source="zero", target=identifier, target_slot="b"),
                    ]
                )
            else:
                blocks.append(
                    Block(
                        id=identifier,
                        kind=BlockKind.HYSTERESIS,
                        label=identifier,
                        config={
                            "u_low": math.nextafter(-comparison_hysteresis, math.inf),
                            "u_high": 0.0,
                            "initial": False,
                            "semantic_contract": "CDL.Reals.Greater",
                        },
                    )
                )
                links.append(Link(source=margin, target=identifier, target_slot="in"))
            return identifier

        efficiency_up = add_strict_hysteresis("efficiency_up", "up_capacity_margin")
        efficiency_down = add_strict_hysteresis("efficiency_down", "down_capacity_margin")
        blocks.extend(
            [
                Block(
                    id="stage_process_ended",
                    kind=BlockKind.BOOLEAN_FALLING_EDGE,
                    label="Stage process completed",
                    config={"pre_u_start": False},
                ),
                Block(
                    id="efficiency_up_timer",
                    kind=BlockKind.TIMER_WITH_RESET,
                    label="Efficiency stage-up timer",
                    config={
                        "threshold_seconds": float(parameters["dtRun"]),
                        "semantic_contract": (
                            "Buildings.Templates.Plants.Controls.Utilities.TimerWithReset"
                        ),
                    },
                ),
                Block(
                    id="efficiency_down_timer",
                    kind=BlockKind.TIMER_WITH_RESET,
                    label="Efficiency stage-down timer",
                    config={
                        "threshold_seconds": float(parameters["dtRun"]),
                        "semantic_contract": (
                            "Buildings.Templates.Plants.Controls.Utilities.TimerWithReset"
                        ),
                    },
                ),
            ]
        )
        links.extend(
            [
                Link(
                    source="u1StaPro",
                    target="stage_process_ended",
                    target_slot="in",
                ),
                Link(
                    source=efficiency_up,
                    target="efficiency_up_timer",
                    target_slot="in",
                ),
                Link(
                    source="stage_process_ended",
                    target="efficiency_up_timer",
                    target_slot="reset",
                ),
                Link(
                    source=efficiency_down,
                    target="efficiency_down_timer",
                    target_slot="in",
                ),
                Link(
                    source="stage_process_ended",
                    target="efficiency_down_timer",
                    target_slot="reset",
                ),
            ]
        )

        blocks.extend(
            [
                Block(
                    id="negative_delta_t",
                    kind=BlockKind.NUMERIC_CONST,
                    label="Negative failsafe delta T",
                    config={"value": -float(parameters["dT"])},
                ),
                Block(
                    id="failsafe_polarity",
                    kind=BlockKind.NUMERIC_CONST,
                    label="Failsafe application polarity",
                    config={"value": polarity},
                ),
            ]
        )

        def add_temperature_failsafe(
            identifier: str,
            minuend: str,
            subtrahend: str,
            duration: float,
        ) -> str:
            delta = f"{identifier}_delta"
            signed = f"{identifier}_signed"
            below = f"{identifier}_below"
            timer = f"{identifier}_timer"
            blocks.extend(
                [
                    Block(id=delta, kind=BlockKind.SUBTRACT, label=delta),
                    Block(id=signed, kind=BlockKind.MULTIPLY, label=signed),
                    Block(id=below, kind=BlockKind.LESS_THAN, label=below),
                    Block(
                        id=timer,
                        kind=BlockKind.TIMER_WITH_RESET,
                        label=timer,
                        config={
                            "threshold_seconds": float(duration),
                            "semantic_contract": (
                                "Buildings.Templates.Plants.Controls.Utilities.TimerWithReset"
                            ),
                        },
                    ),
                ]
            )
            links.extend(
                [
                    Link(source=minuend, target=delta, target_slot="a"),
                    Link(source=subtrahend, target=delta, target_slot="b"),
                    Link(source=delta, target=signed, target_slot="a"),
                    Link(
                        source="failsafe_polarity",
                        target=signed,
                        target_slot="b",
                    ),
                    Link(source=signed, target=below, target_slot="a"),
                    Link(source="negative_delta_t", target=below, target_slot="b"),
                    Link(source=below, target=timer, target_slot="in"),
                    Link(
                        source="stage_process_ended",
                        target=timer,
                        target_slot="reset",
                    ),
                ]
            )
            return timer

        primary_failsafe = add_temperature_failsafe(
            "primary_setpoint",
            "TPriSup",
            "TSupSet",
            float(parameters["dtPri"]),
        )
        failsafe = primary_failsafe
        failsafe_slot = "passed"
        if have_secondary:
            secondary_primary = add_temperature_failsafe(
                "secondary_primary",
                "TSecSup",
                "TPriSup",
                float(parameters["dtSec"]),
            )
            secondary_setpoint = add_temperature_failsafe(
                "secondary_setpoint",
                "TSecSup",
                "TSupSet",
                float(parameters["dtSec"]),
            )
            blocks.extend(
                [
                    Block(
                        id="secondary_failsafe",
                        kind=BlockKind.AND,
                        label="Secondary failsafe",
                    ),
                    Block(
                        id="any_failsafe",
                        kind=BlockKind.OR,
                        label="Any staging failsafe",
                    ),
                ]
            )
            links.extend(
                [
                    Link(
                        source=secondary_primary,
                        source_slot="passed",
                        target="secondary_failsafe",
                        target_slot="a",
                    ),
                    Link(
                        source=secondary_setpoint,
                        source_slot="passed",
                        target="secondary_failsafe",
                        target_slot="b",
                    ),
                    Link(
                        source=primary_failsafe,
                        source_slot="passed",
                        target="any_failsafe",
                        target_slot="a",
                    ),
                    Link(
                        source="secondary_failsafe",
                        target="any_failsafe",
                        target_slot="b",
                    ),
                ]
            )
            failsafe = "any_failsafe"
            failsafe_slot = "out"

        blocks.extend(
            [
                Block(id="stage_up", kind=BlockKind.OR, label="Stage-up command"),
                Block(id="not_failsafe", kind=BlockKind.NOT, label="No failsafe"),
                Block(id="stage_down", kind=BlockKind.AND, label="Stage-down command"),
                Block(id="y1Up", kind=BlockKind.BOOLEAN_OUTPUT, label="y1Up"),
                Block(id="y1Dow", kind=BlockKind.BOOLEAN_OUTPUT, label="y1Dow"),
            ]
        )
        links.extend(
            [
                Link(
                    source="efficiency_up_timer",
                    source_slot="passed",
                    target="stage_up",
                    target_slot="a",
                ),
                Link(
                    source=failsafe,
                    source_slot=failsafe_slot,
                    target="stage_up",
                    target_slot="b",
                ),
                Link(
                    source=failsafe,
                    source_slot=failsafe_slot,
                    target="not_failsafe",
                    target_slot="in",
                ),
                Link(
                    source="efficiency_down_timer",
                    source_slot="passed",
                    target="stage_down",
                    target_slot="a",
                ),
                Link(source="not_failsafe", target="stage_down", target_slot="b"),
                Link(source="stage_up", target="y1Up", target_slot="in"),
                Link(source="stage_down", target="y1Dow", target_slot="in"),
            ]
        )
        return ControlGraph(
            name=(f"PlantStageChangeCommand_{application}_{stage_count}_{int(have_secondary)}"),
            blocks=blocks,
            links=links,
            metadata={
                "semantic_contract": (
                    "Buildings.Templates.Plants.Controls.StagingRotation.StageChangeCommand"
                ),
                "stage_count": stage_count,
                "equipment_count": len(capacities),
                "comparison_hysteresis": comparison_hysteresis,
                "strict_binary64_lower_boundary": math.nextafter(-comparison_hysteresis, math.inf),
            },
        )

    @staticmethod
    def _sort_runtime_graph(parameters: dict[str, Any]) -> ControlGraph:
        input_count = int(parameters["nin"])
        alternate_indices = [int(value) for value in parameters["idxEquAlt"]]
        initial_runtimes = [float(value) for value in parameters["runTim_start"]]
        blocks: list[Block] = [
            Block(
                id="false",
                kind=BlockKind.BOOLEAN_CONST,
                label="False",
                config={"value": False},
            ),
            Block(
                id="true",
                kind=BlockKind.BOOLEAN_CONST,
                label="True",
                config={"value": True},
            ),
            Block(
                id="zero",
                kind=BlockKind.NUMERIC_CONST,
                label="Zero",
                config={"value": 0.0},
            ),
            Block(
                id="one",
                kind=BlockKind.NUMERIC_CONST,
                label="One",
                config={"value": 1.0},
            ),
            Block(
                id="off_weight",
                kind=BlockKind.NUMERIC_CONST,
                label="Available off-equipment weight",
                config={"value": 1e10},
            ),
            Block(
                id="unavailable_weight",
                kind=BlockKind.NUMERIC_CONST,
                label="Unavailable equipment weight",
                config={"value": 1e20},
            ),
            Block(
                id="negative_one",
                kind=BlockKind.NUMERIC_CONST,
                label="Negative one",
                config={"value": -1.0},
            ),
        ]
        links: list[Link] = []
        for equipment in range(1, input_count + 1):
            blocks.extend(
                [
                    Block(
                        id=f"u1Run__{equipment}",
                        kind=BlockKind.BOOLEAN_INPUT,
                        label=f"u1Run__{equipment}",
                    ),
                    Block(
                        id=f"u1Ava__{equipment}",
                        kind=BlockKind.BOOLEAN_INPUT,
                        label=f"u1Ava__{equipment}",
                    ),
                ]
            )

        weighted_sources: list[str] = []
        index_sources: list[str] = []
        for position, (equipment, initial_runtime) in enumerate(
            zip(alternate_indices, initial_runtimes, strict=True),
            start=1,
        ):
            run_input = f"u1Run__{equipment}"
            available_input = f"u1Ava__{equipment}"
            stage_timer = f"staging_runtime_{position}"
            lifetime_timer = f"lifetime_runtime_{position}"
            off = f"off_{position}"
            off_available = f"off_available_{position}"
            off_weight_select = f"off_weight_select_{position}"
            initial_runtime_id = f"initial_runtime_{position}"
            initialized_runtime = f"initialized_runtime_{position}"
            available_weighted_runtime = f"available_weighted_runtime_{position}"
            unavailable = f"unavailable_{position}"
            available_multiplier = f"available_multiplier_{position}"
            available_runtime = f"available_runtime_{position}"
            unavailable_timer = f"unavailable_timer_{position}"
            unavailable_opposite = f"unavailable_opposite_{position}"
            unavailable_rank = f"unavailable_rank_{position}"
            unavailable_multiplier = f"unavailable_multiplier_{position}"
            unavailable_component = f"unavailable_component_{position}"
            weighted = f"weighted_runtime_{position}"
            equipment_index = f"equipment_index_{position}"
            blocks.extend(
                [
                    Block(
                        id=stage_timer,
                        kind=BlockKind.TIMER_ACCUMULATING,
                        label=stage_timer,
                        config={
                            "threshold_seconds": 0.0,
                            "semantic_contract": (
                                "Buildings.Controls.OBC.CDL.Logical.TimerAccumulating"
                            ),
                        },
                    ),
                    Block(
                        id=lifetime_timer,
                        kind=BlockKind.TIMER_ACCUMULATING,
                        label=lifetime_timer,
                        config={
                            "threshold_seconds": 0.0,
                            "semantic_contract": (
                                "Buildings.Controls.OBC.CDL.Logical.TimerAccumulating"
                            ),
                        },
                    ),
                    Block(id=off, kind=BlockKind.NOT, label=off),
                    Block(id=off_available, kind=BlockKind.AND, label=off_available),
                    Block(
                        id=off_weight_select,
                        kind=BlockKind.NUMERIC_SWITCH,
                        label=off_weight_select,
                    ),
                    Block(
                        id=initial_runtime_id,
                        kind=BlockKind.NUMERIC_CONST,
                        label=initial_runtime_id,
                        config={"value": initial_runtime},
                    ),
                    Block(
                        id=initialized_runtime,
                        kind=BlockKind.MAXIMUM,
                        label=initialized_runtime,
                    ),
                    Block(
                        id=available_weighted_runtime,
                        kind=BlockKind.MULTIPLY,
                        label=available_weighted_runtime,
                    ),
                    Block(id=unavailable, kind=BlockKind.NOT, label=unavailable),
                    Block(
                        id=available_multiplier,
                        kind=BlockKind.NUMERIC_SWITCH,
                        label=available_multiplier,
                    ),
                    Block(
                        id=available_runtime,
                        kind=BlockKind.MULTIPLY,
                        label=available_runtime,
                    ),
                    Block(
                        id=unavailable_timer,
                        kind=BlockKind.TIMER,
                        label=unavailable_timer,
                        config={
                            "threshold_seconds": 0.0,
                            "semantic_contract": "CDL.Logical.Timer",
                        },
                    ),
                    Block(
                        id=unavailable_opposite,
                        kind=BlockKind.MULTIPLY,
                        label=unavailable_opposite,
                    ),
                    Block(
                        id=unavailable_rank,
                        kind=BlockKind.ADD,
                        label=unavailable_rank,
                    ),
                    Block(
                        id=unavailable_multiplier,
                        kind=BlockKind.NUMERIC_SWITCH,
                        label=unavailable_multiplier,
                    ),
                    Block(
                        id=unavailable_component,
                        kind=BlockKind.MULTIPLY,
                        label=unavailable_component,
                    ),
                    Block(id=weighted, kind=BlockKind.ADD, label=weighted),
                    Block(
                        id=equipment_index,
                        kind=BlockKind.NUMERIC_CONST,
                        label=equipment_index,
                        config={"value": float(equipment)},
                    ),
                    Block(
                        id=f"yRunTimSta__{position}",
                        kind=BlockKind.NUMERIC_OUTPUT,
                        label=f"yRunTimSta__{position}",
                    ),
                    Block(
                        id=f"yRunTimLif__{position}",
                        kind=BlockKind.NUMERIC_OUTPUT,
                        label=f"yRunTimLif__{position}",
                    ),
                ]
            )
            links.extend(
                [
                    Link(source=run_input, target=stage_timer, target_slot="in"),
                    Link(source="false", target=stage_timer, target_slot="reset"),
                    Link(source=run_input, target=lifetime_timer, target_slot="in"),
                    Link(source="false", target=lifetime_timer, target_slot="reset"),
                    Link(source=run_input, target=off, target_slot="in"),
                    Link(source=off, target=off_available, target_slot="a"),
                    Link(
                        source=available_input,
                        target=off_available,
                        target_slot="b",
                    ),
                    Link(
                        source=off_available,
                        target=off_weight_select,
                        target_slot="selector",
                    ),
                    Link(
                        source="off_weight",
                        target=off_weight_select,
                        target_slot="when_true",
                    ),
                    Link(
                        source="one",
                        target=off_weight_select,
                        target_slot="when_false",
                    ),
                    Link(
                        source=initial_runtime_id,
                        target=initialized_runtime,
                        target_slot="a",
                    ),
                    Link(
                        source=stage_timer,
                        source_slot="elapsed",
                        target=initialized_runtime,
                        target_slot="b",
                    ),
                    Link(
                        source=off_weight_select,
                        target=available_weighted_runtime,
                        target_slot="a",
                    ),
                    Link(
                        source=initialized_runtime,
                        target=available_weighted_runtime,
                        target_slot="b",
                    ),
                    Link(source=available_input, target=unavailable, target_slot="in"),
                    Link(
                        source=unavailable,
                        target=available_multiplier,
                        target_slot="selector",
                    ),
                    Link(
                        source="zero",
                        target=available_multiplier,
                        target_slot="when_true",
                    ),
                    Link(
                        source="one",
                        target=available_multiplier,
                        target_slot="when_false",
                    ),
                    Link(
                        source=available_weighted_runtime,
                        target=available_runtime,
                        target_slot="a",
                    ),
                    Link(
                        source=available_multiplier,
                        target=available_runtime,
                        target_slot="b",
                    ),
                    Link(
                        source=unavailable,
                        target=unavailable_timer,
                        target_slot="in",
                    ),
                    Link(
                        source=unavailable_timer,
                        source_slot="elapsed",
                        target=unavailable_opposite,
                        target_slot="a",
                    ),
                    Link(
                        source="negative_one",
                        target=unavailable_opposite,
                        target_slot="b",
                    ),
                    Link(
                        source=unavailable_opposite,
                        target=unavailable_rank,
                        target_slot="a",
                    ),
                    Link(
                        source="unavailable_weight",
                        target=unavailable_rank,
                        target_slot="b",
                    ),
                    Link(
                        source=available_input,
                        target=unavailable_multiplier,
                        target_slot="selector",
                    ),
                    Link(
                        source="zero",
                        target=unavailable_multiplier,
                        target_slot="when_true",
                    ),
                    Link(
                        source="one",
                        target=unavailable_multiplier,
                        target_slot="when_false",
                    ),
                    Link(
                        source=unavailable_rank,
                        target=unavailable_component,
                        target_slot="a",
                    ),
                    Link(
                        source=unavailable_multiplier,
                        target=unavailable_component,
                        target_slot="b",
                    ),
                    Link(source=available_runtime, target=weighted, target_slot="a"),
                    Link(
                        source=unavailable_component,
                        target=weighted,
                        target_slot="b",
                    ),
                    Link(
                        source=stage_timer,
                        source_slot="elapsed",
                        target=f"yRunTimSta__{position}",
                        target_slot="in",
                    ),
                    Link(
                        source=lifetime_timer,
                        source_slot="elapsed",
                        target=f"yRunTimLif__{position}",
                        target_slot="in",
                    ),
                ]
            )
            weighted_sources.append(weighted)
            index_sources.append(equipment_index)

        values = list(weighted_sources)
        indices = list(index_sources)
        operation = 0
        gap = len(values) // 2
        while gap > 0:
            for right_position in range(gap, len(values)):
                left_position = right_position - gap
                active_source = "true"
                while left_position >= 0:
                    operation += 1
                    greater = f"sort_greater_{operation}"
                    swap = f"sort_swap_{operation}"
                    left_value = f"sort_left_value_{operation}"
                    right_value = f"sort_right_value_{operation}"
                    left_index = f"sort_left_index_{operation}"
                    right_index = f"sort_right_index_{operation}"
                    blocks.extend(
                        [
                            Block(id=greater, kind=BlockKind.GREATER_THAN, label=greater),
                            Block(id=swap, kind=BlockKind.AND, label=swap),
                            Block(
                                id=left_value,
                                kind=BlockKind.NUMERIC_SWITCH,
                                label=left_value,
                            ),
                            Block(
                                id=right_value,
                                kind=BlockKind.NUMERIC_SWITCH,
                                label=right_value,
                            ),
                            Block(
                                id=left_index,
                                kind=BlockKind.NUMERIC_SWITCH,
                                label=left_index,
                            ),
                            Block(
                                id=right_index,
                                kind=BlockKind.NUMERIC_SWITCH,
                                label=right_index,
                            ),
                        ]
                    )
                    links.extend(
                        [
                            Link(
                                source=values[left_position],
                                target=greater,
                                target_slot="a",
                            ),
                            Link(
                                source=values[left_position + gap],
                                target=greater,
                                target_slot="b",
                            ),
                            Link(source=active_source, target=swap, target_slot="a"),
                            Link(source=greater, target=swap, target_slot="b"),
                            Link(source=swap, target=left_value, target_slot="selector"),
                            Link(
                                source=values[left_position + gap],
                                target=left_value,
                                target_slot="when_true",
                            ),
                            Link(
                                source=values[left_position],
                                target=left_value,
                                target_slot="when_false",
                            ),
                            Link(source=swap, target=right_value, target_slot="selector"),
                            Link(
                                source=values[left_position],
                                target=right_value,
                                target_slot="when_true",
                            ),
                            Link(
                                source=values[left_position + gap],
                                target=right_value,
                                target_slot="when_false",
                            ),
                            Link(source=swap, target=left_index, target_slot="selector"),
                            Link(
                                source=indices[left_position + gap],
                                target=left_index,
                                target_slot="when_true",
                            ),
                            Link(
                                source=indices[left_position],
                                target=left_index,
                                target_slot="when_false",
                            ),
                            Link(source=swap, target=right_index, target_slot="selector"),
                            Link(
                                source=indices[left_position],
                                target=right_index,
                                target_slot="when_true",
                            ),
                            Link(
                                source=indices[left_position + gap],
                                target=right_index,
                                target_slot="when_false",
                            ),
                        ]
                    )
                    values[left_position] = left_value
                    values[left_position + gap] = right_value
                    indices[left_position] = left_index
                    indices[left_position + gap] = right_index
                    active_source = swap
                    left_position -= gap
            gap //= 2

        for rank, index_source in enumerate(indices, start=1):
            output_id = f"yIdx__{rank}"
            blocks.append(Block(id=output_id, kind=BlockKind.NUMERIC_OUTPUT, label=output_id))
            links.append(Link(source=index_source, target=output_id, target_slot="in"))
        return ControlGraph(
            name=f"PlantSortRuntime_{input_count}_{len(alternate_indices)}",
            blocks=blocks,
            links=links,
            metadata={
                "semantic_contract": (
                    "Buildings.Templates.Plants.Controls.StagingRotation.SortRuntime"
                ),
                "input_count": input_count,
                "alternate_indices": alternate_indices,
                "sort_algorithm": "exact_unrolled_modelica_vectors_shellsort",
            },
        )

    @staticmethod
    def _stage_index_graph(parameters: dict[str, Any]) -> ControlGraph:
        stage_count = int(parameters["nSta"])
        have_availability_input = bool(parameters["have_inpAva"])
        blocks: list[Block] = [
            Block(id="u1Lea", kind=BlockKind.BOOLEAN_INPUT, label="u1Lea"),
            Block(id="u1Up", kind=BlockKind.BOOLEAN_INPUT, label="u1Up"),
            Block(id="u1Dow", kind=BlockKind.BOOLEAN_INPUT, label="u1Dow"),
        ]
        links: list[Link] = []
        if have_availability_input:
            blocks.append(
                Block(
                    id="availability_zero",
                    kind=BlockKind.NUMERIC_CONST,
                    label="Zero availability mask",
                    config={"value": 0.0},
                )
            )
            selections: list[str] = []
            for stage in range(1, stage_count + 1):
                input_id = f"u1AvaSta__{stage}"
                bit_id = f"availability_bit_{stage}"
                selection_id = f"availability_select_{stage}"
                blocks.extend(
                    [
                        Block(
                            id=input_id,
                            kind=BlockKind.BOOLEAN_INPUT,
                            label=input_id,
                        ),
                        Block(
                            id=bit_id,
                            kind=BlockKind.NUMERIC_CONST,
                            label=f"Stage {stage} mask bit",
                            config={"value": float(1 << (stage - 1))},
                        ),
                        Block(
                            id=selection_id,
                            kind=BlockKind.NUMERIC_SWITCH,
                            label=selection_id,
                        ),
                    ]
                )
                links.extend(
                    [
                        Link(
                            source=input_id,
                            target=selection_id,
                            target_slot="selector",
                        ),
                        Link(
                            source=bit_id,
                            target=selection_id,
                            target_slot="when_true",
                        ),
                        Link(
                            source="availability_zero",
                            target=selection_id,
                            target_slot="when_false",
                        ),
                    ]
                )
                selections.append(selection_id)
            availability_mask = selections[0]
            for stage, selection_id in enumerate(selections[1:], start=2):
                sum_id = f"availability_sum_{stage}"
                blocks.append(Block(id=sum_id, kind=BlockKind.ADD, label=sum_id))
                links.extend(
                    [
                        Link(source=availability_mask, target=sum_id, target_slot="a"),
                        Link(source=selection_id, target=sum_id, target_slot="b"),
                    ]
                )
                availability_mask = sum_id
        else:
            availability_mask = "all_stages_available"
            blocks.append(
                Block(
                    id=availability_mask,
                    kind=BlockKind.NUMERIC_CONST,
                    label="All stages available",
                    config={"value": float((1 << stage_count) - 1)},
                )
            )
        blocks.extend(
            [
                Block(
                    id="stage_index",
                    kind=BlockKind.PLANT_STAGE_INDEX,
                    label="Plant stage index",
                    config={
                        "stage_count": stage_count,
                        "minimum_runtime_seconds": float(parameters["dtRun"]),
                        "semantic_contract": (
                            "Buildings.Templates.Plants.Controls.Utilities.StageIndex"
                        ),
                    },
                ),
                Block(id="y", kind=BlockKind.NUMERIC_OUTPUT, label="y"),
            ]
        )
        links.extend(
            [
                Link(source="u1Lea", target="stage_index", target_slot="leadEnable"),
                Link(source="u1Up", target="stage_index", target_slot="stageUp"),
                Link(source="u1Dow", target="stage_index", target_slot="stageDown"),
                Link(
                    source=availability_mask,
                    target="stage_index",
                    target_slot="availabilityMask",
                ),
                Link(
                    source="stage_index",
                    source_slot="stage",
                    target="y",
                    target_slot="in",
                ),
            ]
        )
        return ControlGraph(
            name=f"PlantStageIndex_{stage_count}",
            blocks=blocks,
            links=links,
            metadata={
                "vector_encoding": "lossless_integer_bitmask",
                "stage_count": stage_count,
                "have_availability_input": have_availability_input,
            },
        )

    @staticmethod
    def _equipment_enable_graph(
        staging_matrix: list[list[float]],
        alternate_count: int,
    ) -> ControlGraph:
        """Lower the pinned EquipmentEnable network into scalar, typed IR.

        ``Pre`` occurs only in the feedback that holds the last enable vector.
        At an input event, the source either holds that vector or atomically
        replaces it.  A deferred host-tick update therefore observes the same
        prior vector for every output element while the new vector is computed.
        """

        stage_count = len(staging_matrix)
        equipment_count = len(staging_matrix[0])
        blocks: list[Block] = [
            Block(id="uSta", kind=BlockKind.NUMERIC_INPUT, label="uSta"),
            Block(
                id="zero",
                kind=BlockKind.NUMERIC_CONST,
                label="Zero",
                config={"value": 0.0},
            ),
            Block(
                id="one",
                kind=BlockKind.NUMERIC_CONST,
                label="One",
                config={"value": 1.0},
            ),
            Block(
                id="alternate_lower_threshold",
                kind=BlockKind.NUMERIC_CONST,
                label="Alternate lower threshold",
                config={"value": 1e-4},
            ),
            Block(
                id="alternate_upper_threshold",
                kind=BlockKind.NUMERIC_CONST,
                label="Alternate upper threshold",
                config={"value": 0.9999},
            ),
            Block(
                id="fixed_threshold",
                kind=BlockKind.NUMERIC_CONST,
                label="Fixed equipment threshold",
                config={"value": 0.99},
            ),
            Block(
                id="false",
                kind=BlockKind.BOOLEAN_CONST,
                label="False",
                config={"value": False},
            ),
            Block(
                id="stage_changed",
                kind=BlockKind.NUMERIC_CHANGED,
                label="Stage changed",
                config={
                    "initial": 0.0,
                    "semantic_contract": "Buildings.Controls.OBC.CDL.Integers.Change",
                },
            ),
        ]
        links: list[Link] = [Link(source="uSta", target="stage_changed", target_slot="in")]
        for rank in range(1, alternate_count + 1):
            blocks.append(
                Block(
                    id=f"uIdxAltSor__{rank}",
                    kind=BlockKind.NUMERIC_INPUT,
                    label=f"uIdxAltSor__{rank}",
                )
            )
        for equipment in range(1, equipment_count + 1):
            blocks.append(
                Block(
                    id=f"u1Ava__{equipment}",
                    kind=BlockKind.BOOLEAN_INPUT,
                    label=f"u1Ava__{equipment}",
                )
            )

        def fold(sources: list[str], kind: BlockKind, prefix: str) -> str:
            if not sources:
                return "false" if kind in {BlockKind.AND, BlockKind.OR} else "zero"
            previous = sources[0]
            for index, source in enumerate(sources[1:], start=2):
                identifier = f"{prefix}_{index}"
                blocks.append(Block(id=identifier, kind=kind, label=identifier))
                links.extend(
                    [
                        Link(source=previous, target=identifier, target_slot="a"),
                        Link(source=source, target=identifier, target_slot="b"),
                    ]
                )
                previous = identifier
            return previous

        selected_coefficients: list[str] = []
        fixed_required: list[str] = []
        fixed_available: list[str] = []
        alternate_available: list[str] = []
        for equipment in range(1, equipment_count + 1):
            row_selections: list[str] = []
            for stage in range(1, stage_count + 1):
                stage_constant = f"stage_{stage}"
                if equipment == 1:
                    blocks.append(
                        Block(
                            id=stage_constant,
                            kind=BlockKind.NUMERIC_CONST,
                            label=f"Stage {stage}",
                            config={"value": float(stage)},
                        )
                    )
                coefficient = f"coefficient_{equipment}_{stage}"
                stage_match = f"stage_match_{equipment}_{stage}"
                selection = f"coefficient_select_{equipment}_{stage}"
                blocks.extend(
                    [
                        Block(
                            id=coefficient,
                            kind=BlockKind.NUMERIC_CONST,
                            label=f"Equipment {equipment} stage {stage} coefficient",
                            config={"value": staging_matrix[stage - 1][equipment - 1]},
                        ),
                        Block(id=stage_match, kind=BlockKind.EQUAL, label=stage_match),
                        Block(
                            id=selection,
                            kind=BlockKind.NUMERIC_SWITCH,
                            label=selection,
                        ),
                    ]
                )
                links.extend(
                    [
                        Link(source="uSta", target=stage_match, target_slot="a"),
                        Link(
                            source=stage_constant,
                            target=stage_match,
                            target_slot="b",
                        ),
                        Link(
                            source=stage_match,
                            target=selection,
                            target_slot="selector",
                        ),
                        Link(
                            source=coefficient,
                            target=selection,
                            target_slot="when_true",
                        ),
                        Link(
                            source="zero",
                            target=selection,
                            target_slot="when_false",
                        ),
                    ]
                )
                row_selections.append(selection)
            selected = fold(
                row_selections,
                BlockKind.ADD,
                f"coefficient_sum_{equipment}",
            )
            selected_coefficients.append(selected)
            fixed = f"fixed_required_{equipment}"
            fixed_and_available = f"fixed_available_{equipment}"
            possible_alternate_lower = f"alternate_lower_{equipment}"
            possible_alternate_upper = f"alternate_upper_{equipment}"
            possible_alternate = f"alternate_possible_{equipment}"
            possible_and_available = f"alternate_available_{equipment}"
            blocks.extend(
                [
                    Block(id=fixed, kind=BlockKind.GREATER_THAN, label=fixed),
                    Block(
                        id=fixed_and_available,
                        kind=BlockKind.AND,
                        label=fixed_and_available,
                    ),
                    Block(
                        id=possible_alternate_lower,
                        kind=BlockKind.GREATER_THAN,
                        label=possible_alternate_lower,
                    ),
                    Block(
                        id=possible_alternate_upper,
                        kind=BlockKind.LESS_THAN,
                        label=possible_alternate_upper,
                    ),
                    Block(
                        id=possible_alternate,
                        kind=BlockKind.AND,
                        label=possible_alternate,
                    ),
                    Block(
                        id=possible_and_available,
                        kind=BlockKind.AND,
                        label=possible_and_available,
                    ),
                ]
            )
            links.extend(
                [
                    Link(source=selected, target=fixed, target_slot="a"),
                    Link(source="fixed_threshold", target=fixed, target_slot="b"),
                    Link(source=fixed, target=fixed_and_available, target_slot="a"),
                    Link(
                        source=f"u1Ava__{equipment}",
                        target=fixed_and_available,
                        target_slot="b",
                    ),
                    Link(
                        source=selected,
                        target=possible_alternate_lower,
                        target_slot="a",
                    ),
                    Link(
                        source="alternate_lower_threshold",
                        target=possible_alternate_lower,
                        target_slot="b",
                    ),
                    Link(
                        source=selected,
                        target=possible_alternate_upper,
                        target_slot="a",
                    ),
                    Link(
                        source="alternate_upper_threshold",
                        target=possible_alternate_upper,
                        target_slot="b",
                    ),
                    Link(
                        source=possible_alternate_lower,
                        target=possible_alternate,
                        target_slot="a",
                    ),
                    Link(
                        source=possible_alternate_upper,
                        target=possible_alternate,
                        target_slot="b",
                    ),
                    Link(
                        source=possible_alternate,
                        target=possible_and_available,
                        target_slot="a",
                    ),
                    Link(
                        source=f"u1Ava__{equipment}",
                        target=possible_and_available,
                        target_slot="b",
                    ),
                ]
            )
            fixed_required.append(fixed)
            fixed_available.append(fixed_and_available)
            alternate_available.append(possible_and_available)

        total_required = fold(
            selected_coefficients,
            BlockKind.ADD,
            "total_required",
        )

        def boolean_count(sources: list[str], prefix: str) -> str:
            numeric_sources: list[str] = []
            for index, source in enumerate(sources, start=1):
                selection = f"{prefix}_select_{index}"
                blocks.append(Block(id=selection, kind=BlockKind.NUMERIC_SWITCH, label=selection))
                links.extend(
                    [
                        Link(source=source, target=selection, target_slot="selector"),
                        Link(source="one", target=selection, target_slot="when_true"),
                        Link(source="zero", target=selection, target_slot="when_false"),
                    ]
                )
                numeric_sources.append(selection)
            return fold(numeric_sources, BlockKind.ADD, f"{prefix}_sum")

        fixed_count = boolean_count(fixed_required, "fixed_count")
        blocks.append(
            Block(
                id="alternates_required",
                kind=BlockKind.SUBTRACT,
                label="Alternates required",
            )
        )
        links.extend(
            [
                Link(source=total_required, target="alternates_required", target_slot="a"),
                Link(source=fixed_count, target="alternates_required", target_slot="b"),
            ]
        )

        new_commands: list[str] = []
        previous_available: list[str] = []
        for equipment in range(1, equipment_count + 1):
            ranked_matches: list[str] = []
            for rank in range(1, alternate_count + 1):
                rank_constant = f"rank_{rank}"
                if equipment == 1:
                    blocks.append(
                        Block(
                            id=rank_constant,
                            kind=BlockKind.NUMERIC_CONST,
                            label=f"Rank {rank}",
                            config={"value": float(rank)},
                        )
                    )
                equipment_constant = f"equipment_{equipment}"
                if rank == 1:
                    blocks.append(
                        Block(
                            id=equipment_constant,
                            kind=BlockKind.NUMERIC_CONST,
                            label=f"Equipment {equipment}",
                            config={"value": float(equipment)},
                        )
                    )
                rank_active = f"rank_active_{equipment}_{rank}"
                index_matches = f"index_match_{equipment}_{rank}"
                ranked_match = f"ranked_match_{equipment}_{rank}"
                blocks.extend(
                    [
                        Block(
                            id=rank_active,
                            kind=BlockKind.GREATER_THAN_OR_EQUAL,
                            label=rank_active,
                        ),
                        Block(
                            id=index_matches,
                            kind=BlockKind.EQUAL,
                            label=index_matches,
                        ),
                        Block(id=ranked_match, kind=BlockKind.AND, label=ranked_match),
                    ]
                )
                links.extend(
                    [
                        Link(
                            source="alternates_required",
                            target=rank_active,
                            target_slot="a",
                        ),
                        Link(
                            source=rank_constant,
                            target=rank_active,
                            target_slot="b",
                        ),
                        Link(
                            source=f"uIdxAltSor__{rank}",
                            target=index_matches,
                            target_slot="a",
                        ),
                        Link(
                            source=equipment_constant,
                            target=index_matches,
                            target_slot="b",
                        ),
                        Link(
                            source=rank_active,
                            target=ranked_match,
                            target_slot="a",
                        ),
                        Link(
                            source=index_matches,
                            target=ranked_match,
                            target_slot="b",
                        ),
                    ]
                )
                ranked_matches.append(ranked_match)
            selected_alternate = fold(
                ranked_matches,
                BlockKind.OR,
                f"selected_alternate_{equipment}",
            )
            selected_and_available = f"selected_available_{equipment}"
            new_command = f"new_command_{equipment}"
            previous = f"previous_command_{equipment}"
            previous_and_available = f"previous_available_{equipment}"
            blocks.extend(
                [
                    Block(
                        id=selected_and_available,
                        kind=BlockKind.AND,
                        label=selected_and_available,
                    ),
                    Block(id=new_command, kind=BlockKind.OR, label=new_command),
                    Block(
                        id=previous,
                        kind=BlockKind.BOOLEAN_PRE_HOST_TICK,
                        label=previous,
                        config={
                            "initial": False,
                            "semantic_contract": "CDL.Logical.Pre",
                            "execution_profile": "host_tick_v1",
                        },
                    ),
                    Block(
                        id=previous_and_available,
                        kind=BlockKind.AND,
                        label=previous_and_available,
                    ),
                ]
            )
            links.extend(
                [
                    Link(
                        source=selected_alternate,
                        target=selected_and_available,
                        target_slot="a",
                    ),
                    Link(
                        source=alternate_available[equipment - 1],
                        target=selected_and_available,
                        target_slot="b",
                    ),
                    Link(
                        source=fixed_available[equipment - 1],
                        target=new_command,
                        target_slot="a",
                    ),
                    Link(
                        source=selected_and_available,
                        target=new_command,
                        target_slot="b",
                    ),
                    Link(
                        source=previous,
                        target=previous_and_available,
                        target_slot="a",
                    ),
                    Link(
                        source=f"u1Ava__{equipment}",
                        target=previous_and_available,
                        target_slot="b",
                    ),
                ]
            )
            new_commands.append(new_command)
            previous_available.append(previous_and_available)

        previous_available_count = boolean_count(
            previous_available,
            "previous_available_count",
        )
        blocks.extend(
            [
                Block(
                    id="insufficient_available",
                    kind=BlockKind.LESS_THAN,
                    label="Previously enabled available count is insufficient",
                ),
                Block(
                    id="recompute",
                    kind=BlockKind.OR,
                    label="Recompute enable vector",
                ),
            ]
        )
        links.extend(
            [
                Link(
                    source=previous_available_count,
                    target="insufficient_available",
                    target_slot="a",
                ),
                Link(
                    source=total_required,
                    target="insufficient_available",
                    target_slot="b",
                ),
                Link(source="stage_changed", target="recompute", target_slot="a"),
                Link(
                    source="insufficient_available",
                    target="recompute",
                    target_slot="b",
                ),
            ]
        )
        for equipment in range(1, equipment_count + 1):
            output_switch = f"output_switch_{equipment}"
            output = f"y1__{equipment}"
            blocks.extend(
                [
                    Block(
                        id=output_switch,
                        kind=BlockKind.BOOLEAN_SWITCH,
                        label=output_switch,
                    ),
                    Block(id=output, kind=BlockKind.BOOLEAN_OUTPUT, label=output),
                ]
            )
            links.extend(
                [
                    Link(source="recompute", target=output_switch, target_slot="selector"),
                    Link(
                        source=new_commands[equipment - 1],
                        target=output_switch,
                        target_slot="when_true",
                    ),
                    Link(
                        source=f"previous_command_{equipment}",
                        target=output_switch,
                        target_slot="when_false",
                    ),
                    Link(source=output_switch, target=output, target_slot="in"),
                    Link(
                        source=output_switch,
                        target=f"previous_command_{equipment}",
                        target_slot="in",
                    ),
                ]
            )
        return ControlGraph(
            name=f"PlantEquipmentEnable_{stage_count}_{equipment_count}",
            blocks=blocks,
            links=links,
            metadata={
                "semantic_contract": (
                    "Buildings.Templates.Plants.Controls.StagingRotation.EquipmentEnable"
                ),
                "stage_count": stage_count,
                "equipment_count": equipment_count,
                "alternate_count": alternate_count,
                "pre_equivalence": (
                    "Each prior-output block feeds only the hold/recompute decision and "
                    "all feedback states update after the output vector is evaluated; this "
                    "preserves the pinned Pre network at sampled input events."
                ),
            },
        )

    @staticmethod
    def _stage_completion_graph(equipment_count: int) -> ControlGraph:
        blocks: list[Block] = [
            Block(id="uSta", kind=BlockKind.NUMERIC_INPUT, label="uSta"),
            Block(
                id="mask_zero",
                kind=BlockKind.NUMERIC_CONST,
                label="Zero mask",
                config={"value": 0.0},
            ),
        ]
        links: list[Link] = []

        def add_mask(prefix: str, label_prefix: str) -> str:
            selections: list[str] = []
            for index in range(1, equipment_count + 1):
                input_id = f"{label_prefix}__{index}"
                bit_id = f"{prefix}_bit_{index}"
                selection_id = f"{prefix}_select_{index}"
                blocks.extend(
                    [
                        Block(
                            id=input_id,
                            kind=BlockKind.BOOLEAN_INPUT,
                            label=input_id,
                        ),
                        Block(
                            id=bit_id,
                            kind=BlockKind.NUMERIC_CONST,
                            label=f"{prefix} bit {index}",
                            config={"value": float(1 << (index - 1))},
                        ),
                        Block(
                            id=selection_id,
                            kind=BlockKind.NUMERIC_SWITCH,
                            label=f"{prefix} mask bit {index}",
                        ),
                    ]
                )
                links.extend(
                    [
                        Link(
                            source=input_id,
                            target=selection_id,
                            target_slot="selector",
                        ),
                        Link(
                            source=bit_id,
                            target=selection_id,
                            target_slot="when_true",
                        ),
                        Link(
                            source="mask_zero",
                            target=selection_id,
                            target_slot="when_false",
                        ),
                    ]
                )
                selections.append(selection_id)
            previous = selections[0]
            for index, selection_id in enumerate(selections[1:], start=2):
                add_id = f"{prefix}_add_{index}"
                blocks.append(Block(id=add_id, kind=BlockKind.ADD, label=f"{prefix} mask sum"))
                links.extend(
                    [
                        Link(source=previous, target=add_id, target_slot="a"),
                        Link(source=selection_id, target=add_id, target_slot="b"),
                    ]
                )
                previous = add_id
            return previous

        command_mask = add_mask("command", "u1")
        status_mask = add_mask("status", "u1_actual")
        blocks.extend(
            [
                Block(
                    id="stage_completion",
                    kind=BlockKind.PLANT_STAGE_COMPLETION,
                    label="Stage completion state",
                    config={
                        "equipment_count": equipment_count,
                        "semantic_contract": (
                            "Buildings.Templates.Plants.Controls.StagingRotation.StageCompletion"
                        ),
                    },
                ),
                Block(id="y1", kind=BlockKind.BOOLEAN_OUTPUT, label="y1"),
                Block(id="y1End", kind=BlockKind.BOOLEAN_OUTPUT, label="y1End"),
            ]
        )
        links.extend(
            [
                Link(
                    source=command_mask,
                    target="stage_completion",
                    target_slot="commandMask",
                ),
                Link(
                    source=status_mask,
                    target="stage_completion",
                    target_slot="statusMask",
                ),
                Link(source="uSta", target="stage_completion", target_slot="stage"),
                Link(
                    source="stage_completion",
                    source_slot="inProgress",
                    target="y1",
                    target_slot="in",
                ),
                Link(
                    source="stage_completion",
                    source_slot="completed",
                    target="y1End",
                    target_slot="in",
                ),
            ]
        )
        return ControlGraph(
            name=f"PlantStageCompletion_{equipment_count}",
            blocks=blocks,
            links=links,
            metadata={
                "vector_encoding": "lossless_integer_bitmask",
                "maximum_equipment_count": 52,
            },
        )

    @staticmethod
    def _hrc_controller_graph(parameters: dict[str, Any]) -> ControlGraph:
        have_request = bool(parameters["have_reqFlo"])
        input_definitions = [
            ("TChiWatRetUpsHrc", BlockKind.NUMERIC_INPUT),
            ("TChiWatSupSet", BlockKind.NUMERIC_INPUT),
            ("VChiWatLoa_flow", BlockKind.NUMERIC_INPUT),
            ("THeaWatRetUpsHrc", BlockKind.NUMERIC_INPUT),
            ("THeaWatSupSet", BlockKind.NUMERIC_INPUT),
            ("VHeaWatLoa_flow", BlockKind.NUMERIC_INPUT),
            ("TChiWatHrcLvg", BlockKind.NUMERIC_INPUT),
            ("THeaWatHrcLvg", BlockKind.NUMERIC_INPUT),
            ("u1Coo", BlockKind.BOOLEAN_INPUT),
            ("u1Hea", BlockKind.BOOLEAN_INPUT),
            ("u1Hrc_actual", BlockKind.BOOLEAN_INPUT),
        ]
        if have_request:
            input_definitions.extend(
                [
                    ("u1ReqFloChiWat", BlockKind.BOOLEAN_INPUT),
                    ("u1ReqFloConWat", BlockKind.BOOLEAN_INPUT),
                ]
            )
        blocks = [Block(id=name, kind=kind, label=name) for name, kind in input_definitions]
        links: list[Link] = []

        def add_load_average(
            prefix: str,
            supply: str,
            return_temperature: str,
            flow: str,
            polarity: float,
        ) -> str:
            capacity = float(parameters["rho_default"]) * float(parameters["cp_default"])
            blocks.extend(
                [
                    Block(
                        id=f"{prefix}_capacity",
                        kind=BlockKind.NUMERIC_CONST,
                        label=f"{prefix} capacity factor",
                        config={"value": capacity},
                    ),
                    Block(
                        id=f"{prefix}_polarity",
                        kind=BlockKind.NUMERIC_CONST,
                        label=f"{prefix} polarity",
                        config={"value": polarity},
                    ),
                    Block(
                        id=f"{prefix}_delta",
                        kind=BlockKind.SUBTRACT,
                        label=f"{prefix} delta temperature",
                    ),
                    Block(
                        id=f"{prefix}_capacity_flow",
                        kind=BlockKind.MULTIPLY,
                        label=f"{prefix} capacity flow",
                    ),
                    Block(
                        id=f"{prefix}_raw_load",
                        kind=BlockKind.MULTIPLY,
                        label=f"{prefix} raw load",
                    ),
                    Block(
                        id=f"{prefix}_signed_load",
                        kind=BlockKind.MULTIPLY,
                        label=f"{prefix} signed load",
                    ),
                    Block(
                        id=f"{prefix}_load_average",
                        kind=BlockKind.MOVING_AVERAGE,
                        label=f"{prefix} rolling load",
                        config={
                            "window_seconds": float(parameters["dtMea"]),
                            "semantic_contract": "CDL.Reals.MovingAverage",
                        },
                    ),
                ]
            )
            links.extend(
                [
                    Link(source=supply, target=f"{prefix}_delta", target_slot="a"),
                    Link(
                        source=return_temperature,
                        target=f"{prefix}_delta",
                        target_slot="b",
                    ),
                    Link(
                        source=flow,
                        target=f"{prefix}_capacity_flow",
                        target_slot="a",
                    ),
                    Link(
                        source=f"{prefix}_capacity",
                        target=f"{prefix}_capacity_flow",
                        target_slot="b",
                    ),
                    Link(
                        source=f"{prefix}_delta",
                        target=f"{prefix}_raw_load",
                        target_slot="a",
                    ),
                    Link(
                        source=f"{prefix}_capacity_flow",
                        target=f"{prefix}_raw_load",
                        target_slot="b",
                    ),
                    Link(
                        source=f"{prefix}_raw_load",
                        target=f"{prefix}_signed_load",
                        target_slot="a",
                    ),
                    Link(
                        source=f"{prefix}_polarity",
                        target=f"{prefix}_signed_load",
                        target_slot="b",
                    ),
                    Link(
                        source=f"{prefix}_signed_load",
                        target=f"{prefix}_load_average",
                        target_slot="in",
                    ),
                ]
            )
            return f"{prefix}_load_average"

        cooling_load = add_load_average(
            "cooling",
            "TChiWatSupSet",
            "TChiWatRetUpsHrc",
            "VChiWatLoa_flow",
            -1.0,
        )
        heating_load = add_load_average(
            "heating",
            "THeaWatSupSet",
            "THeaWatRetUpsHrc",
            "VHeaWatLoa_flow",
            1.0,
        )
        blocks.extend(
            [
                Block(
                    id="hrc_enable",
                    kind=BlockKind.PLANT_HRC_ENABLE,
                    label="Heat-recovery chiller enable",
                    config={
                        "minimum_chilled_supply_temperature": parameters["TChiWatSup_min"],
                        "maximum_heating_supply_temperature": parameters["THeaWatSup_max"],
                        "minimum_cooling_capacity": parameters["capCoo_min"],
                        "minimum_heating_capacity": parameters["capHea_min"],
                        "minimum_state_time_seconds": parameters["dtRun"],
                        "sufficient_load_time_seconds": parameters["dtLoa"],
                        "temperature_limit_1_time_seconds": parameters["dtTem1"],
                        "temperature_limit_2_time_seconds": parameters["dtTem2"],
                        "semantic_contract": (
                            "Buildings.Templates.Plants.Controls.HeatRecoveryChillers.Enable"
                        ),
                    },
                ),
                Block(
                    id="hrc_mode",
                    kind=BlockKind.PLANT_HRC_MODE_CONTROL,
                    label="Heat-recovery chiller mode",
                    config={
                        "heating_cop": parameters["COPHea_nominal"],
                        "semantic_contract": (
                            "Buildings.Templates.Plants.Controls.HeatRecoveryChillers.ModeControl"
                        ),
                    },
                ),
                Block(
                    id="previous_mode",
                    kind=BlockKind.BOOLEAN_PRE_HOST_TICK,
                    label="Previous mode setting",
                    config={
                        "initial": False,
                        "semantic_contract": "CDL.Logical.Pre",
                        "execution_profile": "host_tick_v1",
                    },
                ),
            ]
        )
        links.extend(
            [
                Link(
                    source="u1Coo",
                    target="hrc_enable",
                    target_slot="coolingPlantEnable",
                ),
                Link(
                    source="u1Hea",
                    target="hrc_enable",
                    target_slot="heatingPlantEnable",
                ),
                Link(
                    source="u1Hrc_actual",
                    target="hrc_enable",
                    target_slot="hrcStatus",
                ),
                Link(
                    source=cooling_load,
                    target="hrc_enable",
                    target_slot="coolingLoad",
                ),
                Link(
                    source=heating_load,
                    target="hrc_enable",
                    target_slot="heatingLoad",
                ),
                Link(
                    source="TChiWatHrcLvg",
                    target="hrc_enable",
                    target_slot="chilledLeavingTemperature",
                ),
                Link(
                    source="THeaWatHrcLvg",
                    target="hrc_enable",
                    target_slot="heatingLeavingTemperature",
                ),
                Link(
                    source="previous_mode",
                    target="hrc_enable",
                    target_slot="coolingMode",
                ),
                Link(
                    source="hrc_enable",
                    source_slot="setMode",
                    target="hrc_mode",
                    target_slot="setMode",
                ),
                Link(
                    source=cooling_load,
                    target="hrc_mode",
                    target_slot="coolingLoad",
                ),
                Link(
                    source=heating_load,
                    target="hrc_mode",
                    target_slot="heatingLoad",
                ),
                Link(
                    source="TChiWatSupSet",
                    target="hrc_mode",
                    target_slot="chilledSetpoint",
                ),
                Link(
                    source="THeaWatSupSet",
                    target="hrc_mode",
                    target_slot="heatingSetpoint",
                ),
                Link(
                    source="hrc_mode",
                    source_slot="coolingMode",
                    target="previous_mode",
                    target_slot="in",
                ),
            ]
        )

        def add_dedicated_pump(prefix: str, request_input: str | None) -> str:
            timer_seconds = 600.0 if have_request else 180.0
            blocks.extend(
                [
                    Block(id=f"{prefix}_disabled", kind=BlockKind.NOT, label="Disabled"),
                    Block(id=f"{prefix}_off", kind=BlockKind.NOT, label="Proven off"),
                    Block(
                        id=f"{prefix}_off_timer",
                        kind=BlockKind.TIMER,
                        label="Off timer",
                        config={
                            "threshold_seconds": timer_seconds,
                            "semantic_contract": "CDL.Logical.Timer",
                        },
                    ),
                    Block(
                        id=f"{prefix}_off_or_no_request",
                        kind=BlockKind.OR,
                        label="Off or no request",
                    ),
                    Block(
                        id=f"{prefix}_disable_condition",
                        kind=BlockKind.AND,
                        label="Disable condition",
                    ),
                    Block(
                        id=f"{prefix}_disable_edge",
                        kind=BlockKind.ONE_SHOT,
                        label="Disable edge",
                        config={"initial": False},
                    ),
                    Block(
                        id=f"{prefix}_initialization",
                        kind=BlockKind.BOOLEAN_INITIALIZATION,
                        label="First-scan initialization",
                        config={
                            "initial": False,
                            "semantic_contract": (
                                "Buildings.Templates.Plants.Controls.Utilities.Initialization"
                            ),
                        },
                    ),
                    Block(
                        id=f"{prefix}_latch",
                        kind=BlockKind.BOOLEAN_SET_RESET,
                        label="Pump enable latch",
                        config={"semantic_contract": "CDL.Logical.Latch"},
                    ),
                ]
            )
            if request_input is None:
                request_source = f"{prefix}_false"
                blocks.append(
                    Block(
                        id=request_source,
                        kind=BlockKind.BOOLEAN_CONST,
                        label="No request placeholder",
                        config={"value": False},
                    )
                )
            else:
                request_source = f"{prefix}_no_request"
                blocks.append(Block(id=request_source, kind=BlockKind.NOT, label="No request"))
                links.append(Link(source=request_input, target=request_source, target_slot="in"))
            links.extend(
                [
                    Link(
                        source="hrc_enable",
                        source_slot="enable",
                        target=f"{prefix}_disabled",
                        target_slot="in",
                    ),
                    Link(
                        source="u1Hrc_actual",
                        target=f"{prefix}_off",
                        target_slot="in",
                    ),
                    Link(
                        source=f"{prefix}_off",
                        target=f"{prefix}_off_timer",
                        target_slot="in",
                    ),
                    Link(
                        source=f"{prefix}_off_timer",
                        source_slot="passed",
                        target=f"{prefix}_off_or_no_request",
                        target_slot="a",
                    ),
                    Link(
                        source=request_source,
                        target=f"{prefix}_off_or_no_request",
                        target_slot="b",
                    ),
                    Link(
                        source=f"{prefix}_disabled",
                        target=f"{prefix}_disable_condition",
                        target_slot="a",
                    ),
                    Link(
                        source=f"{prefix}_off_or_no_request",
                        target=f"{prefix}_disable_condition",
                        target_slot="b",
                    ),
                    Link(
                        source=f"{prefix}_disable_condition",
                        target=f"{prefix}_disable_edge",
                        target_slot="in",
                    ),
                    Link(
                        source=f"{prefix}_disable_edge",
                        target=f"{prefix}_initialization",
                        target_slot="in",
                    ),
                    Link(
                        source=f"{prefix}_initialization",
                        target=f"{prefix}_latch",
                        target_slot="clear",
                    ),
                    Link(
                        source="hrc_enable",
                        source_slot="enable",
                        target=f"{prefix}_latch",
                        target_slot="set",
                    ),
                ]
            )
            return f"{prefix}_latch"

        chilled_pump = add_dedicated_pump(
            "chilled_pump", "u1ReqFloChiWat" if have_request else None
        )
        heating_pump = add_dedicated_pump(
            "heating_pump", "u1ReqFloConWat" if have_request else None
        )
        for name, kind in (
            ("y1", BlockKind.BOOLEAN_OUTPUT),
            ("y1Coo", BlockKind.BOOLEAN_OUTPUT),
            ("y1PumChiWat", BlockKind.BOOLEAN_OUTPUT),
            ("y1PumHeaWat", BlockKind.BOOLEAN_OUTPUT),
            ("TSupSet", BlockKind.NUMERIC_OUTPUT),
        ):
            blocks.append(Block(id=name, kind=kind, label=name))
        links.extend(
            [
                Link(
                    source="hrc_enable",
                    source_slot="enable",
                    target="y1",
                    target_slot="in",
                ),
                Link(
                    source="hrc_mode",
                    source_slot="coolingMode",
                    target="y1Coo",
                    target_slot="in",
                ),
                Link(source=chilled_pump, target="y1PumChiWat", target_slot="in"),
                Link(source=heating_pump, target="y1PumHeaWat", target_slot="in"),
                Link(
                    source="hrc_mode",
                    source_slot="supplySetpoint",
                    target="TSupSet",
                    target_slot="in",
                ),
            ]
        )
        return ControlGraph(
            name=f"PlantHeatRecoveryChillerController_{int(have_request)}",
            blocks=blocks,
            links=links,
            metadata={
                "guarded_pre_equivalence": (
                    "Mode can change only on the enable block's set-mode pulse while the "
                    "five-second HRC output delay is false; temperature trips are gated by "
                    "the prior enabled output, so host-tick previous-mode storage is "
                    "observationally equivalent for this source topology."
                )
            },
        )

    @staticmethod
    def _hrc_enable_graph(parameters: dict[str, Any]) -> ControlGraph:
        inputs = (
            ("u1Coo", BlockKind.BOOLEAN_INPUT, "coolingPlantEnable"),
            ("u1Hea", BlockKind.BOOLEAN_INPUT, "heatingPlantEnable"),
            ("u1Hrc_actual", BlockKind.BOOLEAN_INPUT, "hrcStatus"),
            ("QChiWatReq_flow", BlockKind.NUMERIC_INPUT, "coolingLoad"),
            ("QHeaWatReq_flow", BlockKind.NUMERIC_INPUT, "heatingLoad"),
            (
                "TChiWatHrcLvg",
                BlockKind.NUMERIC_INPUT,
                "chilledLeavingTemperature",
            ),
            (
                "THeaWatHrcLvg",
                BlockKind.NUMERIC_INPUT,
                "heatingLeavingTemperature",
            ),
            ("u1CooHrc", BlockKind.BOOLEAN_INPUT, "coolingMode"),
        )
        return ControlGraph(
            name="PlantHeatRecoveryChillerEnable",
            blocks=[
                *(Block(id=name, kind=kind, label=name) for name, kind, _ in inputs),
                Block(
                    id="hrc_enable",
                    kind=BlockKind.PLANT_HRC_ENABLE,
                    label="Heat-recovery chiller enable",
                    config={
                        "minimum_chilled_supply_temperature": parameters["TChiWatSup_min"],
                        "maximum_heating_supply_temperature": parameters["THeaWatSup_max"],
                        "minimum_cooling_capacity": parameters["capCoo_min"],
                        "minimum_heating_capacity": parameters["capHea_min"],
                        "minimum_state_time_seconds": parameters["dtRun"],
                        "sufficient_load_time_seconds": parameters["dtLoa"],
                        "temperature_limit_1_time_seconds": parameters["dtTem1"],
                        "temperature_limit_2_time_seconds": parameters["dtTem2"],
                        "semantic_contract": (
                            "Buildings.Templates.Plants.Controls.HeatRecoveryChillers.Enable"
                        ),
                    },
                ),
                Block(id="y1", kind=BlockKind.BOOLEAN_OUTPUT, label="y1"),
                Block(
                    id="y1SetMod",
                    kind=BlockKind.BOOLEAN_OUTPUT,
                    label="y1SetMod",
                ),
            ],
            links=[
                *(
                    Link(source=name, target="hrc_enable", target_slot=slot)
                    for name, _, slot in inputs
                ),
                Link(
                    source="hrc_enable",
                    source_slot="enable",
                    target="y1",
                    target_slot="in",
                ),
                Link(
                    source="hrc_enable",
                    source_slot="setMode",
                    target="y1SetMod",
                    target_slot="in",
                ),
            ],
        )

    @staticmethod
    def _hrc_mode_control_graph(parameters: dict[str, Any]) -> ControlGraph:
        input_blocks = [
            Block(id="u1SetMod", kind=BlockKind.BOOLEAN_INPUT, label="u1SetMod"),
            *(
                Block(id=name, kind=BlockKind.NUMERIC_INPUT, label=name)
                for name in (
                    "QChiWatReq_flow",
                    "QHeaWatReq_flow",
                    "TChiWatSupSet",
                    "THeaWatSupSet",
                )
            ),
        ]
        return ControlGraph(
            name="PlantHeatRecoveryChillerModeControl",
            blocks=[
                *input_blocks,
                Block(
                    id="mode_control",
                    kind=BlockKind.PLANT_HRC_MODE_CONTROL,
                    label="Heat-recovery chiller mode control",
                    config={
                        "heating_cop": parameters["COPHea_nominal"],
                        "semantic_contract": (
                            "Buildings.Templates.Plants.Controls.HeatRecoveryChillers.ModeControl"
                        ),
                    },
                ),
                Block(id="y1Coo", kind=BlockKind.BOOLEAN_OUTPUT, label="y1Coo"),
                Block(id="TSupSet", kind=BlockKind.NUMERIC_OUTPUT, label="TSupSet"),
            ],
            links=[
                Link(source="u1SetMod", target="mode_control", target_slot="setMode"),
                Link(
                    source="QChiWatReq_flow",
                    target="mode_control",
                    target_slot="coolingLoad",
                ),
                Link(
                    source="QHeaWatReq_flow",
                    target="mode_control",
                    target_slot="heatingLoad",
                ),
                Link(
                    source="TChiWatSupSet",
                    target="mode_control",
                    target_slot="chilledSetpoint",
                ),
                Link(
                    source="THeaWatSupSet",
                    target="mode_control",
                    target_slot="heatingSetpoint",
                ),
                Link(
                    source="mode_control",
                    source_slot="coolingMode",
                    target="y1Coo",
                    target_slot="in",
                ),
                Link(
                    source="mode_control",
                    source_slot="supplySetpoint",
                    target="TSupSet",
                    target_slot="in",
                ),
            ],
        )

    @staticmethod
    def _plant_enable_graph(parameters: dict[str, Any]) -> ControlGraph:
        have_input_schedule = bool(parameters["have_inpSch"])
        schedule_source = "u1Sch" if have_input_schedule else "internal_schedule"
        blocks = [
            Block(id="nReqPla", kind=BlockKind.NUMERIC_INPUT, label="nReqPla"),
            Block(id="TOut", kind=BlockKind.NUMERIC_INPUT, label="TOut"),
            Block(
                id=schedule_source,
                kind=(BlockKind.BOOLEAN_INPUT if have_input_schedule else BlockKind.BOOLEAN_CONST),
                label=schedule_source,
                config={} if have_input_schedule else {"value": True},
            ),
            Block(
                id="plant_enable",
                kind=BlockKind.PLANT_ENABLE,
                label="Plant enable state",
                config={
                    "application": parameters["typ"],
                    "have_input_schedule": have_input_schedule,
                    "schedule": parameters["sch"],
                    "outdoor_lockout": parameters["TOutLck"],
                    "outdoor_lockout_hysteresis": parameters["dTOutLck"],
                    "ignored_requests": parameters["nReqIgn"],
                    "minimum_state_time_seconds": parameters["dtRun"],
                    "low_request_time_seconds": parameters["dtReq"],
                    "semantic_contract": ("Buildings.Templates.Plants.Controls.Enabling.Enable"),
                },
            ),
            Block(id="y1", kind=BlockKind.BOOLEAN_OUTPUT, label="y1"),
        ]
        return ControlGraph(
            name=f"PlantEnable_{parameters['typ']}_{int(have_input_schedule)}",
            blocks=blocks,
            links=[
                Link(
                    source=schedule_source,
                    target="plant_enable",
                    target_slot="scheduleEnabled",
                ),
                Link(
                    source="nReqPla",
                    target="plant_enable",
                    target_slot="requestCount",
                ),
                Link(
                    source="TOut",
                    target="plant_enable",
                    target_slot="outdoorTemperature",
                ),
                Link(source="plant_enable", target="y1", target_slot="in"),
            ],
        )

    @staticmethod
    def _equipment_availability_graph(parameters: dict[str, Any]) -> ControlGraph:
        have_heating = bool(parameters["have_heaWat"])
        have_cooling = bool(parameters["have_chiWat"])
        blocks: list[Block] = [
            Block(id="u1Ava", kind=BlockKind.BOOLEAN_INPUT, label="u1Ava"),
            Block(
                id="availability_state",
                kind=BlockKind.PLANT_EQUIPMENT_AVAILABILITY,
                label="Equipment availability state graph",
                config={
                    "off_time_seconds": float(parameters["dtOff"]),
                    "have_heating": have_heating,
                    "have_cooling": have_cooling,
                    "semantic_contract": (
                        "Buildings.Templates.Plants.Controls.StagingRotation.EquipmentAvailability"
                    ),
                },
            ),
        ]
        links: list[Link] = [
            Link(source="u1Ava", target="availability_state", target_slot="available")
        ]
        for mode, present, input_name, target_slot, output_name, source_slot in (
            (
                "heating",
                have_heating,
                "u1EnaHea",
                "enableHeating",
                "y1Hea",
                "heatingAvailable",
            ),
            (
                "cooling",
                have_cooling,
                "u1EnaCoo",
                "enableCooling",
                "y1Coo",
                "coolingAvailable",
            ),
        ):
            if present:
                blocks.extend(
                    [
                        Block(
                            id=input_name,
                            kind=BlockKind.BOOLEAN_INPUT,
                            label=input_name,
                        ),
                        Block(
                            id=output_name,
                            kind=BlockKind.BOOLEAN_OUTPUT,
                            label=output_name,
                        ),
                    ]
                )
                links.extend(
                    [
                        Link(
                            source=input_name,
                            target="availability_state",
                            target_slot=target_slot,
                        ),
                        Link(
                            source="availability_state",
                            source_slot=source_slot,
                            target=output_name,
                            target_slot="in",
                        ),
                    ]
                )
            else:
                constant = f"{mode}_disabled"
                blocks.append(
                    Block(
                        id=constant,
                        kind=BlockKind.BOOLEAN_CONST,
                        label=f"{mode.title()} loop absent",
                        config={"value": False},
                    )
                )
                links.append(
                    Link(
                        source=constant,
                        target="availability_state",
                        target_slot=target_slot,
                    )
                )
        return ControlGraph(
            name=(f"PlantEquipmentAvailability_{int(have_heating)}{int(have_cooling)}"),
            blocks=blocks,
            links=links,
        )

    @staticmethod
    def _minimum_flow_controller_graph(parameters: dict[str, Any]) -> ControlGraph:
        """Compile the pinned minimum-flow setpoint and bypass PI block network."""

        n_equipment = int(parameters["nEqu"])
        n_enable = int(parameters["nEna"])
        nominal = [float(value) for value in parameters["V_flow_nominal"]]
        minimum = [float(value) for value in parameters["V_flow_min"]]
        have_inlet = bool(parameters["have_valInlIso"])
        have_outlet = bool(parameters["have_valOutIso"])
        blocks: list[Block] = [
            Block(id="VPri_flow", kind=BlockKind.NUMERIC_INPUT, label="VPri_flow"),
            Block(id="zero", kind=BlockKind.NUMERIC_CONST, label="0", config={"value": 0.0}),
            Block(id="one", kind=BlockKind.NUMERIC_CONST, label="1", config={"value": 1.0}),
        ]
        links: list[Link] = []
        blocks.extend(
            Block(
                id=f"u1Equ__{index}",
                kind=BlockKind.BOOLEAN_INPUT,
                label=f"u1Equ__{index}",
            )
            for index in range(1, n_equipment + 1)
        )

        ratio_sources: list[str] = []
        design_sources: list[str] = []
        for index, (design_flow, minimum_flow) in enumerate(
            zip(nominal, minimum, strict=True),
            start=1,
        ):
            design = f"design__{index}"
            minimum_id = f"minimum__{index}"
            enabled = f"enabled_numeric__{index}"
            enabled_minimum = f"enabled_minimum__{index}"
            ratio = f"minimum_ratio__{index}"
            enabled_design = f"enabled_design__{index}"
            blocks.extend(
                [
                    Block(
                        id=design,
                        kind=BlockKind.NUMERIC_CONST,
                        label=f"Design flow {index}",
                        config={"value": design_flow},
                    ),
                    Block(
                        id=minimum_id,
                        kind=BlockKind.NUMERIC_CONST,
                        label=f"Minimum flow {index}",
                        config={"value": minimum_flow},
                    ),
                    Block(
                        id=enabled,
                        kind=BlockKind.NUMERIC_SWITCH,
                        label=f"Equipment {index} enabled numeric",
                    ),
                    Block(
                        id=enabled_minimum,
                        kind=BlockKind.MULTIPLY,
                        label=f"Enabled minimum flow {index}",
                    ),
                    Block(
                        id=ratio,
                        kind=BlockKind.DIVIDE,
                        label=f"Minimum flow ratio {index}",
                    ),
                    Block(
                        id=enabled_design,
                        kind=BlockKind.MULTIPLY,
                        label=f"Enabled design flow {index}",
                    ),
                ]
            )
            links.extend(
                [
                    Link(
                        source=f"u1Equ__{index}",
                        target=enabled,
                        target_slot="selector",
                    ),
                    Link(source="one", target=enabled, target_slot="when_true"),
                    Link(source="zero", target=enabled, target_slot="when_false"),
                    Link(source=minimum_id, target=enabled_minimum, target_slot="a"),
                    Link(source=enabled, target=enabled_minimum, target_slot="b"),
                    Link(source=enabled_minimum, target=ratio, target_slot="a"),
                    Link(source=design, target=ratio, target_slot="b"),
                    Link(source=enabled, target=enabled_design, target_slot="a"),
                    Link(source=design, target=enabled_design, target_slot="b"),
                ]
            )
            ratio_sources.append(ratio)
            design_sources.append(enabled_design)

        def fold(sources: list[str], kind: BlockKind, prefix: str) -> str:
            previous = sources[0]
            for index, source in enumerate(sources[1:], start=2):
                identifier = f"{prefix}__{index}"
                blocks.append(Block(id=identifier, kind=kind, label=identifier))
                links.extend(
                    [
                        Link(source=previous, target=identifier, target_slot="a"),
                        Link(source=source, target=identifier, target_slot="b"),
                    ]
                )
                previous = identifier
            return previous

        maximum_ratio = fold(ratio_sources, BlockKind.MAXIMUM, "maximum_ratio")
        design_sum = fold(design_sources, BlockKind.ADD, "design_sum")
        blocks.extend(
            [
                Block(
                    id="minimum_flow_setpoint",
                    kind=BlockKind.MULTIPLY,
                    label="Minimum flow setpoint",
                ),
                Block(
                    id="VPriSet_flow",
                    kind=BlockKind.NUMERIC_OUTPUT,
                    label="VPriSet_flow",
                ),
            ]
        )
        links.extend(
            [
                Link(
                    source=maximum_ratio,
                    target="minimum_flow_setpoint",
                    target_slot="a",
                ),
                Link(
                    source=design_sum,
                    target="minimum_flow_setpoint",
                    target_slot="b",
                ),
                Link(
                    source="minimum_flow_setpoint",
                    target="VPriSet_flow",
                    target_slot="in",
                ),
            ]
        )

        enable_sources: list[str] = []
        for prefix, enabled_topology in (
            ("u1ValInlIso", have_inlet),
            ("u1ValOutIso", have_outlet),
            ("u1PumPri_actual", not have_inlet and not have_outlet),
        ):
            if not enabled_topology:
                continue
            for index in range(1, n_enable + 1):
                identifier = f"{prefix}__{index}"
                blocks.append(Block(id=identifier, kind=BlockKind.BOOLEAN_INPUT, label=identifier))
                enable_sources.append(identifier)
        enable = fold(enable_sources, BlockKind.OR, "enable_any")

        blocks.extend(
            [
                Block(
                    id="enabled_setpoint",
                    kind=BlockKind.NUMERIC_SWITCH,
                    label="Enabled setpoint",
                ),
                Block(
                    id="bypass_pid",
                    kind=BlockKind.PID_WITH_RESET,
                    label="Minimum-flow bypass PI",
                    config={
                        "controller_type": "PI",
                        "k": float(parameters["k"]),
                        "ti": float(parameters["Ti"]),
                        "td": 0.1,
                        "r": 1.0,
                        "y_min": 0.0,
                        "y_max": 1.0,
                        "ni": 0.9,
                        "nd": 10.0,
                        "xi_start": 0.0,
                        "yd_start": 0.0,
                        "y_reset": 1.0,
                        "reverse_acting": True,
                    },
                ),
                Block(
                    id="enable_edge",
                    kind=BlockKind.ONE_SHOT,
                    label="Enable edge",
                    config={"initial": False},
                ),
                Block(
                    id="same_event_reset",
                    kind=BlockKind.NUMERIC_SWITCH,
                    label="Same-event reset output",
                ),
                Block(
                    id="enabled_output",
                    kind=BlockKind.NUMERIC_SWITCH,
                    label="Enabled bypass output",
                ),
                Block(id="y", kind=BlockKind.NUMERIC_OUTPUT, label="y"),
            ]
        )
        links.extend(
            [
                Link(source=enable, target="enabled_setpoint", target_slot="selector"),
                Link(
                    source="minimum_flow_setpoint",
                    target="enabled_setpoint",
                    target_slot="when_true",
                ),
                Link(
                    source="VPri_flow",
                    target="enabled_setpoint",
                    target_slot="when_false",
                ),
                Link(
                    source="enabled_setpoint",
                    target="bypass_pid",
                    target_slot="setpoint",
                ),
                Link(
                    source="VPri_flow",
                    target="bypass_pid",
                    target_slot="measurement",
                ),
                Link(source=enable, target="bypass_pid", target_slot="trigger"),
                Link(source=enable, target="enable_edge", target_slot="in"),
                Link(
                    source="enable_edge",
                    target="same_event_reset",
                    target_slot="selector",
                ),
                Link(source="one", target="same_event_reset", target_slot="when_true"),
                Link(
                    source="bypass_pid",
                    target="same_event_reset",
                    target_slot="when_false",
                ),
                Link(source=enable, target="enabled_output", target_slot="selector"),
                Link(
                    source="same_event_reset",
                    target="enabled_output",
                    target_slot="when_true",
                ),
                Link(source="one", target="enabled_output", target_slot="when_false"),
                Link(source="enabled_output", target="y", target_slot="in"),
            ]
        )
        return ControlGraph(
            name=f"PlantMinimumFlowController_{n_equipment}x{n_enable}",
            blocks=blocks,
            links=links,
        )

    @classmethod
    def _minimum_flow_dual_mode_graph(cls, parameters: dict[str, Any]) -> ControlGraph:
        """Compile the pinned CHW/HW wrapper around independent minimum-flow loops."""

        have_heating = bool(parameters["have_heaWat"])
        have_cooling = bool(parameters["have_chiWat"])
        have_inlet = bool(parameters["have_valInlIso"])
        have_outlet = bool(parameters["have_valOutIso"])
        separate_chilled_pumps = bool(parameters["have_pumChiWatPri"])
        n_equipment = int(parameters["nEqu"])
        common_primary_pumps = (
            have_heating
            and have_cooling
            and not separate_chilled_pumps
            and not have_inlet
            and not have_outlet
        )
        blocks: list[Block] = [
            Block(
                id=f"u1Equ__{index}",
                kind=BlockKind.BOOLEAN_INPUT,
                label=f"u1Equ__{index}",
            )
            for index in range(1, n_equipment + 1)
        ]
        links: list[Link] = []
        heating_mode_sources: dict[int, str] = {}
        cooling_mode_sources: dict[int, str] = {}
        if have_heating and have_cooling:
            for index in range(1, n_equipment + 1):
                mode = f"u1HeaEqu__{index}"
                cooling = f"cooling_mode__{index}"
                blocks.extend(
                    [
                        Block(id=mode, kind=BlockKind.BOOLEAN_INPUT, label=mode),
                        Block(
                            id=cooling,
                            kind=BlockKind.NOT,
                            label=f"Equipment {index} cooling mode",
                        ),
                    ]
                )
                links.append(Link(source=mode, target=cooling, target_slot="in"))
                heating_mode_sources[index] = mode
                cooling_mode_sources[index] = cooling
        else:
            blocks.append(
                Block(
                    id="active_mode",
                    kind=BlockKind.BOOLEAN_CONST,
                    label="Active single-loop mode",
                    config={"value": True},
                )
            )
            for index in range(1, n_equipment + 1):
                heating_mode_sources[index] = "active_mode"
                cooling_mode_sources[index] = "active_mode"

        if common_primary_pumps:
            blocks.extend(
                Block(
                    id=f"u1PumHeaWatPri_actual__{index}",
                    kind=BlockKind.BOOLEAN_INPUT,
                    label=f"u1PumHeaWatPri_actual__{index}",
                )
                for index in range(1, n_equipment + 1)
            )

        def merge_loop(*, heating: bool) -> None:
            prefix = "heating" if heating else "cooling"
            water = "HeaWat" if heating else "ChiWat"
            enable_count = int(parameters["nEnaHeaWat" if heating else "nEnaChiWat"])
            child_parameters = {
                "nEqu": n_equipment,
                "nEna": enable_count,
                "V_flow_nominal": parameters[
                    "VHeaWat_flow_nominal" if heating else "VChiWat_flow_nominal"
                ],
                "V_flow_min": parameters["VHeaWat_flow_min" if heating else "VChiWat_flow_min"],
                "have_valInlIso": have_inlet,
                "have_valOutIso": have_outlet,
                "k": parameters["k"],
                "Ti": parameters["Ti"],
            }
            child = cls._minimum_flow_controller_graph(child_parameters)
            id_map: dict[str, str] = {}
            internal_equipment: dict[int, str] = {}
            common_pump_enable: dict[int, str] = {}
            for block in child.blocks:
                if block.id == "VPri_flow":
                    identifier = f"V{water}Pri_flow"
                elif block.id == "VPriSet_flow":
                    identifier = f"V{water}PriSet_flow"
                elif block.id == "y":
                    identifier = f"yVal{water}MinByp"
                elif block.id.startswith("u1Equ__"):
                    index = int(block.id.rsplit("__", 1)[1])
                    identifier = f"{prefix}_equipment_enabled__{index}"
                    internal_equipment[index] = identifier
                elif block.id.startswith("u1ValInlIso__"):
                    identifier = block.id.replace("u1ValInlIso", f"u1Val{water}InlIso")
                elif block.id.startswith("u1ValOutIso__"):
                    identifier = block.id.replace("u1ValOutIso", f"u1Val{water}OutIso")
                elif block.id.startswith("u1PumPri_actual__"):
                    index = int(block.id.rsplit("__", 1)[1])
                    if common_primary_pumps:
                        identifier = f"{prefix}_pump_enabled__{index}"
                        common_pump_enable[index] = identifier
                    else:
                        identifier = block.id.replace("u1PumPri_actual", f"u1Pum{water}Pri_actual")
                else:
                    identifier = f"{prefix}__{block.id}"
                id_map[block.id] = identifier
                kind = block.kind
                label = block.label
                config = dict(block.config)
                if block.id.startswith("u1Equ__") or (
                    common_primary_pumps and block.id.startswith("u1PumPri_actual__")
                ):
                    kind = BlockKind.AND
                    label = identifier
                    config = {}
                blocks.append(
                    Block(
                        id=identifier,
                        kind=kind,
                        label=label,
                        config=config,
                        x=block.x,
                        y=block.y,
                    )
                )
            links.extend(
                Link(
                    source=id_map[link.source],
                    source_slot=link.source_slot,
                    target=id_map[link.target],
                    target_slot=link.target_slot,
                )
                for link in child.links
            )
            mode_sources = heating_mode_sources if heating else cooling_mode_sources
            for index, target in internal_equipment.items():
                links.extend(
                    [
                        Link(source=f"u1Equ__{index}", target=target, target_slot="a"),
                        Link(source=mode_sources[index], target=target, target_slot="b"),
                    ]
                )
            for index, target in common_pump_enable.items():
                links.extend(
                    [
                        Link(
                            source=f"u1PumHeaWatPri_actual__{index}",
                            target=target,
                            target_slot="a",
                        ),
                        Link(source=mode_sources[index], target=target, target_slot="b"),
                    ]
                )

        if have_heating:
            merge_loop(heating=True)
        if have_cooling:
            merge_loop(heating=False)
        return ControlGraph(
            name=(
                f"PlantMinimumFlowControllerDualMode_{n_equipment}_"
                f"{int(have_heating)}{int(have_cooling)}"
            ),
            blocks=blocks,
            links=links,
        )

    @staticmethod
    def _validated_staging_matrix(value: Any) -> list[list[float]]:
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(row, list) and row for row in value)
        ):
            raise ValueError("plant parameter staEqu requires a non-empty two-dimensional array")
        width = len(value[0])
        if len(value) > 64 or width > 64 or len(value) * width > 4096:
            raise ValueError("plant parameter staEqu exceeds the 64x64/4096-element bound")
        if any(len(row) != width for row in value):
            raise ValueError("plant parameter staEqu must be rectangular")
        matrix: list[list[float]] = []
        required_counts: list[int] = []
        for row_index, row in enumerate(value, start=1):
            normalized: list[float] = []
            for column_index, item in enumerate(row, start=1):
                if (
                    isinstance(item, bool)
                    or not isinstance(item, (int, float))
                    or not math.isfinite(float(item))
                    or not 0.0 <= float(item) <= 1.0
                ):
                    raise ValueError(
                        "plant parameter staEqu values must be finite Reals from 0 through 1; "
                        f"invalid element at ({row_index},{column_index})"
                    )
                normalized.append(float(item))
            row_sum = sum(normalized)
            rounded = round(row_sum)
            if not math.isclose(row_sum, rounded, abs_tol=1e-9):
                raise ValueError(f"plant parameter staEqu row {row_index} must sum to an integer")
            matrix.append(normalized)
            required_counts.append(int(rounded))
        if required_counts != sorted(required_counts):
            raise ValueError(
                "plant parameter staEqu required-equipment count must be non-decreasing by stage"
            )
        return matrix

    @classmethod
    def _stage_availability_graph(cls, value: Any) -> ControlGraph:
        matrix = cls._validated_staging_matrix(value)
        stage_count = len(matrix)
        equipment_count = len(matrix[0])
        blocks: list[Block] = [
            Block(id="zero", kind=BlockKind.NUMERIC_CONST, label="0", config={"value": 0}),
            Block(id="one", kind=BlockKind.NUMERIC_CONST, label="1", config={"value": 1}),
        ]
        blocks.extend(
            Block(
                id=f"u1Ava__{index}",
                kind=BlockKind.BOOLEAN_INPUT,
                label=f"u1Ava__{index}",
            )
            for index in range(1, equipment_count + 1)
        )
        links: list[Link] = []

        def boolean_and(sources: list[str], *, prefix: str) -> str:
            if not sources:
                constant = f"{prefix}__true"
                blocks.append(
                    Block(
                        id=constant,
                        kind=BlockKind.BOOLEAN_CONST,
                        label=f"{prefix} true",
                        config={"value": True},
                    )
                )
                return constant
            previous = sources[0]
            for fold_index, source in enumerate(sources[1:], start=2):
                fold = f"{prefix}__and_{fold_index}"
                blocks.append(Block(id=fold, kind=BlockKind.AND, label=fold))
                links.extend(
                    [
                        Link(source=previous, target=fold, target_slot="a"),
                        Link(source=source, target=fold, target_slot="b"),
                    ]
                )
                previous = fold
            return previous

        for stage_index, row in enumerate(matrix, start=1):
            fixed_sources = [
                f"u1Ava__{equipment_index}"
                for equipment_index, coefficient in enumerate(row, start=1)
                if coefficient > 0.99
            ]
            fixed_available = boolean_and(
                fixed_sources,
                prefix=f"stage_{stage_index}__fixed_available",
            )
            possible_sources = [
                f"u1Ava__{equipment_index}"
                for equipment_index, coefficient in enumerate(row, start=1)
                if coefficient > 0.0
            ]
            numeric_sources: list[str] = []
            for candidate_index, source in enumerate(possible_sources, start=1):
                conversion = f"stage_{stage_index}__available_{candidate_index}"
                blocks.append(
                    Block(
                        id=conversion,
                        kind=BlockKind.NUMERIC_SWITCH,
                        label=conversion,
                    )
                )
                links.extend(
                    [
                        Link(source=source, target=conversion, target_slot="selector"),
                        Link(source="one", target=conversion, target_slot="when_true"),
                        Link(source="zero", target=conversion, target_slot="when_false"),
                    ]
                )
                numeric_sources.append(conversion)
            available_count = "zero"
            if numeric_sources:
                available_count = numeric_sources[0]
                for fold_index, source in enumerate(numeric_sources[1:], start=2):
                    fold = f"stage_{stage_index}__count_{fold_index}"
                    blocks.append(Block(id=fold, kind=BlockKind.ADD, label=fold))
                    links.extend(
                        [
                            Link(source=available_count, target=fold, target_slot="a"),
                            Link(source=source, target=fold, target_slot="b"),
                        ]
                    )
                    available_count = fold
            required = f"stage_{stage_index}__required"
            enough = f"stage_{stage_index}__enough"
            result = f"stage_{stage_index}__available"
            output = f"y1__{stage_index}"
            blocks.extend(
                [
                    Block(
                        id=required,
                        kind=BlockKind.NUMERIC_CONST,
                        label=required,
                        config={"value": round(sum(row))},
                    ),
                    Block(id=enough, kind=BlockKind.GREATER_THAN_OR_EQUAL, label=enough),
                    Block(id=result, kind=BlockKind.AND, label=result),
                    Block(id=output, kind=BlockKind.BOOLEAN_OUTPUT, label=output),
                ]
            )
            links.extend(
                [
                    Link(source=available_count, target=enough, target_slot="a"),
                    Link(source=required, target=enough, target_slot="b"),
                    Link(source=fixed_available, target=result, target_slot="a"),
                    Link(source=enough, target=result, target_slot="b"),
                    Link(source=result, target=output, target_slot="in"),
                ]
            )

        return ControlGraph(
            name=f"PlantStageAvailability_{stage_count}x{equipment_count}",
            blocks=blocks,
            links=links,
        )

    @staticmethod
    def _true_array_conditional_graph(*, nin: int, nout: int) -> ControlGraph:
        """Lower the pinned priority-loop algorithm into stock typed primitives.

        A valid priority-array entry consumes one requested-true position even when it
        duplicates a previous index. Invalid entries do not consume a position. This
        distinction is easy to lose in a set-based implementation and is retained here.
        """

        blocks: list[Block] = [
            Block(id="u", kind=BlockKind.NUMERIC_INPUT, label="u"),
            Block(id="zero", kind=BlockKind.NUMERIC_CONST, label="0", config={"value": 0}),
            Block(id="one", kind=BlockKind.NUMERIC_CONST, label="1", config={"value": 1}),
            Block(
                id="nout_limit",
                kind=BlockKind.NUMERIC_CONST,
                label="nout",
                config={"value": nout},
            ),
        ]
        blocks.extend(
            Block(
                id=f"index__{index}",
                kind=BlockKind.NUMERIC_CONST,
                label=f"Index {index}",
                config={"value": index},
            )
            for index in range(1, nout + 1)
        )
        blocks.extend(
            Block(
                id=f"uIdx__{position}",
                kind=BlockKind.NUMERIC_INPUT,
                label=f"uIdx__{position}",
            )
            for position in range(1, nin + 1)
        )
        links: list[Link] = []
        selected_by_output: dict[int, list[str]] = {index: [] for index in range(1, nout + 1)}
        prefix = "zero"
        for position in range(1, nin + 1):
            input_id = f"uIdx__{position}"
            at_least_one = f"valid_low__{position}"
            at_most_nout = f"valid_high__{position}"
            valid = f"valid__{position}"
            budget = f"budget__{position}"
            active = f"active__{position}"
            valid_numeric = f"valid_numeric__{position}"
            blocks.extend(
                [
                    Block(
                        id=at_least_one,
                        kind=BlockKind.GREATER_THAN_OR_EQUAL,
                        label=f"uIdx[{position}] >= 1",
                    ),
                    Block(
                        id=at_most_nout,
                        kind=BlockKind.LESS_THAN_OR_EQUAL,
                        label=f"uIdx[{position}] <= nout",
                    ),
                    Block(id=valid, kind=BlockKind.AND, label=f"Valid index {position}"),
                    Block(
                        id=budget,
                        kind=BlockKind.LESS_THAN,
                        label=f"Requested position {position}",
                    ),
                    Block(
                        id=active,
                        kind=BlockKind.AND,
                        label=f"Selected priority position {position}",
                    ),
                    Block(
                        id=valid_numeric,
                        kind=BlockKind.NUMERIC_SWITCH,
                        label=f"Valid count {position}",
                    ),
                ]
            )
            links.extend(
                [
                    Link(source=input_id, target=at_least_one, target_slot="a"),
                    Link(source="one", target=at_least_one, target_slot="b"),
                    Link(source=input_id, target=at_most_nout, target_slot="a"),
                    Link(source="nout_limit", target=at_most_nout, target_slot="b"),
                    Link(source=at_least_one, target=valid, target_slot="a"),
                    Link(source=at_most_nout, target=valid, target_slot="b"),
                    Link(source=prefix, target=budget, target_slot="a"),
                    Link(source="u", target=budget, target_slot="b"),
                    Link(source=valid, target=active, target_slot="a"),
                    Link(source=budget, target=active, target_slot="b"),
                    Link(source=valid, target=valid_numeric, target_slot="selector"),
                    Link(source="one", target=valid_numeric, target_slot="when_true"),
                    Link(source="zero", target=valid_numeric, target_slot="when_false"),
                ]
            )
            for output_index in range(1, nout + 1):
                matches = f"matches__{position}__{output_index}"
                selected = f"selected__{position}__{output_index}"
                blocks.extend(
                    [
                        Block(
                            id=matches,
                            kind=BlockKind.EQUAL,
                            label=f"uIdx[{position}] == {output_index}",
                        ),
                        Block(
                            id=selected,
                            kind=BlockKind.AND,
                            label=f"Select output {output_index} from {position}",
                        ),
                    ]
                )
                links.extend(
                    [
                        Link(source=input_id, target=matches, target_slot="a"),
                        Link(
                            source=f"index__{output_index}",
                            target=matches,
                            target_slot="b",
                        ),
                        Link(source=active, target=selected, target_slot="a"),
                        Link(source=matches, target=selected, target_slot="b"),
                    ]
                )
                selected_by_output[output_index].append(selected)
            if position < nin:
                next_prefix = f"prefix__{position}"
                blocks.append(
                    Block(
                        id=next_prefix,
                        kind=BlockKind.ADD,
                        label=f"Valid prefix count {position}",
                    )
                )
                links.extend(
                    [
                        Link(source=prefix, target=next_prefix, target_slot="a"),
                        Link(source=valid_numeric, target=next_prefix, target_slot="b"),
                    ]
                )
                prefix = next_prefix

        for output_index, selected_ids in selected_by_output.items():
            previous = selected_ids[0]
            for fold_index, selected in enumerate(selected_ids[1:], start=2):
                fold = f"output_or__{output_index}__{fold_index}"
                blocks.append(
                    Block(
                        id=fold,
                        kind=BlockKind.OR,
                        label=f"Output {output_index} priority OR {fold_index}",
                    )
                )
                links.extend(
                    [
                        Link(source=previous, target=fold, target_slot="a"),
                        Link(source=selected, target=fold, target_slot="b"),
                    ]
                )
                previous = fold
            output_id = f"y1__{output_index}"
            blocks.append(
                Block(
                    id=output_id,
                    kind=BlockKind.BOOLEAN_OUTPUT,
                    label=output_id,
                )
            )
            links.append(Link(source=previous, target=output_id, target_slot="in"))

        return ControlGraph(
            name="PlantUtilitiesTrueArrayConditional",
            blocks=blocks,
            links=links,
        )

    def _source_equation_interface(
        self,
        controller_id: str,
        graph: ControlGraph,
    ) -> dict[str, Any]:
        base = f"urn:bactalk:plant-source:{controller_id}"
        inputs = []
        outputs = []
        for block in graph.blocks:
            if block.kind in {BlockKind.BOOLEAN_INPUT, BlockKind.NUMERIC_INPUT}:
                integer = (
                    controller_id
                    in {
                        "Utilities.MultiMaxInteger",
                        "Utilities.MultiMinInteger",
                        "Utilities.TrueArrayConditional",
                        "Utilities.PlaceholderInteger",
                    }
                    or (controller_id == "Enabling.Enable" and block.id == "nReqPla")
                    or (controller_id == "StagingRotation.StageCompletion" and block.id == "uSta")
                    or (
                        controller_id == "StagingRotation.EquipmentEnable"
                        and (block.id == "uSta" or block.id.startswith("uIdxAltSor__"))
                    )
                    or (
                        controller_id == "StagingRotation.StageChangeCommand" and block.id == "uSta"
                    )
                )
                inputs.append(
                    {
                        "label": block.id,
                        "id": f"{base}.{block.id}",
                        "type": (
                            "S231:BooleanInput"
                            if block.kind == BlockKind.BOOLEAN_INPUT
                            else "S231:IntegerInput"
                            if integer
                            else "S231:RealInput"
                        ),
                        "description": "Pinned Modelica source-equation input",
                    }
                )
            elif block.kind in {BlockKind.BOOLEAN_OUTPUT, BlockKind.NUMERIC_OUTPUT}:
                integer = controller_id in {
                    "Utilities.MultiMaxInteger",
                    "Utilities.MultiMinInteger",
                    "Utilities.PlaceholderInteger",
                    "Utilities.StageIndex",
                } or (
                    controller_id == "StagingRotation.SortRuntime" and block.id.startswith("yIdx__")
                )
                outputs.append(
                    {
                        "label": block.id,
                        "id": f"{base}.{block.id}",
                        "type": (
                            "S231:BooleanOutput"
                            if block.kind == BlockKind.BOOLEAN_OUTPUT
                            else "S231:IntegerOutput"
                            if integer
                            else "S231:RealOutput"
                        ),
                        "description": "Pinned Modelica source-equation output",
                    }
                )
        return {
            "controller_id": base,
            "inputs": sorted(inputs, key=lambda item: item["label"]),
            "outputs": sorted(outputs, key=lambda item: item["label"]),
        }

    def _translate_source_equation(
        self,
        controller_id: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        graph, parameterization = self._source_equation_graph(controller_id, parameters)
        controller = self._controllers()[controller_id]
        interface = self._source_equation_interface(controller_id, graph)
        generated = controller_id in {
            "Utilities.Initialization",
            "Utilities.TimerWithReset",
            "MinimumFlow.Controller",
            "MinimumFlow.ControllerDualMode",
            "StagingRotation.EquipmentAvailability",
            "StagingRotation.EquipmentEnable",
            "Utilities.StageIndex",
            "StagingRotation.SortRuntime",
            "Pumps.Generic.StagingHeaderedDeltaP",
            "StagingRotation.StageChangeCommand",
            "Pumps.Generic.StagingHeadered",
            "Pumps.Primary.VariableSpeed",
            "HeatPumps.AirToWater",
            "Enabling.Enable",
            "HeatRecoveryChillers.Controller",
            "HeatRecoveryChillers.Enable",
            "HeatRecoveryChillers.ModeControl",
            "StagingRotation.StageCompletion",
        }
        if controller_id == "Pumps.Primary.VariableSpeed":
            generated = any(
                block.kind
                in {
                    BlockKind.PID_WITH_RESET,
                    BlockKind.BOOLEAN_SET_RESET,
                }
                for block in graph.blocks
            )
        class_name = (
            "Buildings.Templates.Plants.Controls.Enabling.Enable"
            if controller_id == "Enabling.Enable"
            else ("Buildings.Templates.Plants.Controls.HeatRecoveryChillers.Controller")
            if controller_id == "HeatRecoveryChillers.Controller"
            else ("Buildings.Templates.Plants.Controls.HeatRecoveryChillers.Enable")
            if controller_id == "HeatRecoveryChillers.Enable"
            else ("Buildings.Templates.Plants.Controls.HeatRecoveryChillers.ModeControl")
            if controller_id == "HeatRecoveryChillers.ModeControl"
            else "Buildings.Templates.Plants.Controls.Utilities.Initialization"
            if controller_id == "Utilities.Initialization"
            else "Buildings.Templates.Plants.Controls.Utilities.TimerWithReset"
            if controller_id == "Utilities.TimerWithReset"
            else "Buildings.Templates.Plants.Controls.Utilities.TrueArrayConditional"
            if controller_id == "Utilities.TrueArrayConditional"
            else f"Buildings.Templates.Plants.Controls.{controller_id}"
            if controller_id in _PLACEHOLDER_CONTROLLERS
            else "Buildings.Templates.Plants.Controls.StagingRotation.StageAvailability"
            if controller_id == "StagingRotation.StageAvailability"
            else "Buildings.Templates.Plants.Controls.MinimumFlow.Controller"
            if controller_id == "MinimumFlow.Controller"
            else "Buildings.Templates.Plants.Controls.MinimumFlow.ControllerDualMode"
            if controller_id == "MinimumFlow.ControllerDualMode"
            else ("Buildings.Templates.Plants.Controls.StagingRotation.EquipmentAvailability")
            if controller_id == "StagingRotation.EquipmentAvailability"
            else ("Buildings.Templates.Plants.Controls.StagingRotation.EquipmentEnable")
            if controller_id == "StagingRotation.EquipmentEnable"
            else ("Buildings.Templates.Plants.Controls.StagingRotation.StageCompletion")
            if controller_id == "StagingRotation.StageCompletion"
            else "Buildings.Templates.Plants.Controls.Utilities.StageIndex"
            if controller_id == "Utilities.StageIndex"
            else ("Buildings.Templates.Plants.Controls.StagingRotation.SortRuntime")
            if controller_id == "StagingRotation.SortRuntime"
            else ("Buildings.Templates.Plants.Controls.Pumps.Generic.StagingHeaderedDeltaP")
            if controller_id == "Pumps.Generic.StagingHeaderedDeltaP"
            else ("Buildings.Templates.Plants.Controls.StagingRotation.StageChangeCommand")
            if controller_id == "StagingRotation.StageChangeCommand"
            else ("Buildings.Templates.Plants.Controls.Pumps.Generic.StagingHeadered")
            if controller_id == "Pumps.Generic.StagingHeadered"
            else "Buildings.Templates.Plants.Controls.Pumps.Primary.VariableSpeed"
            if controller_id == "Pumps.Primary.VariableSpeed"
            else "Buildings.Templates.Plants.Controls.HeatPumps.AirToWater"
            if controller_id == "HeatPumps.AirToWater"
            else "Buildings.Controls.OBC.CDL.Integers.Max"
            if controller_id == "Utilities.MultiMaxInteger"
            else "Buildings.Controls.OBC.CDL.Integers.Min"
        )
        internal_count = len(graph.blocks) - len(interface["inputs"]) - len(interface["outputs"])
        coverage = {
            "schema": "bactalk-cxf-lowering/v4",
            "execution_profile": "modelica_exact",
            "source_sha256": controller["source_sha256"],
            "root_id": interface["controller_id"],
            "root_label": controller["name"],
            "component_count": internal_count,
            "boundary_inputs": len(interface["inputs"]),
            "boundary_outputs": len(interface["outputs"]),
            "class_counts": {class_name: max(1, internal_count)},
            "supported_class_count": max(1, internal_count),
            "unsupported_classes": [],
            "niagara_unsupported_classes": (
                ["Buildings.Controls.OBC.CDL.Reals.PIDWithReset"]
                if controller_id
                in {
                    "MinimumFlow.Controller",
                    "MinimumFlow.ControllerDualMode",
                }
                else [class_name]
                if generated
                else []
            ),
            "missing_components": [],
            "exactness_blockers": [],
            "niagara_exactness_blockers": [],
            "translatable": True,
            "niagara_translatable": not generated,
        }
        proof = _PROVEN_CONTROLLERS.get(controller_id)
        return {
            "schema": "bactalk.plant-controls-translation/v1",
            "controller": controller,
            "translator": "BACTalk pinned Modelica source-equation lowering",
            "runtime": "BACTalk typed-IR interpreter",
            "execution_profile": "modelica_exact",
            "interface": interface,
            "cxf_document": None,
            "engine_report": {
                "engine": "bactalk-source-equation-lowering",
                "validation_scope": "pinned-source-equation-and-typed-ir",
                "oce_validation_succeeded": False,
                "block_count": internal_count,
                "typed_ir_block_count": len(graph.blocks),
                "stateful_blocks": sum(
                    block.kind == BlockKind.PID_WITH_RESET for block in graph.blocks
                )
                if controller_id in {"MinimumFlow.Controller", "MinimumFlow.ControllerDualMode"}
                else int(generated),
                "point_count": len(interface["inputs"]) + len(interface["outputs"]),
                "warning_count": 0,
                "qualification": (
                    "The reviewed source definition is lowered directly from its pinned "
                    "Modelica equation, algorithm, or compile-time-specialized block network; "
                    "it is covered by deterministic recurrence/reduction/truth-table vectors."
                ),
            },
            "connection_normalization": {
                "schema": "bactalk.source-equation-normalization/v1",
                "applied": True,
                "source_equation_controller": controller_id,
            },
            "parameterization": parameterization,
            "typed_ir": graph.model_dump(mode="json"),
            "lowering": coverage,
            "niagara_lowering_complete": not generated,
            "niagara_target": self._niagara_target(coverage),
            "library": "LBNL Modelica Buildings Templates.Plants.Controls",
            "product_status": proof["status"] if proof else "source_catalog_only",
        }

    def _execute_source_equation(
        self,
        controller_id: str,
        *,
        samples: list[dict[str, Any]],
        collect: list[str] | None,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        translation = self._translate_source_equation(controller_id, parameters)
        graph = ControlGraph.model_validate(translation["typed_ir"])
        interface = translation["interface"]
        input_labels = {port["label"] for port in interface["inputs"]}
        input_types = {port["label"]: port["type"] for port in interface["inputs"]}
        output_labels = {port["label"] for port in interface["outputs"]}
        if not samples:
            raise ValueError("at least one sample is required")
        effective_inputs: dict[str, Any] = {}
        for index, sample in enumerate(samples):
            raw_inputs = sample.get("inputs")
            if not isinstance(raw_inputs, dict):
                raise ValueError(f"sample {index} inputs must be an object")
            unknown = sorted(set(raw_inputs) - input_labels)
            if unknown:
                raise ValueError(
                    f"sample {index} contains non-public controller inputs: " + ", ".join(unknown)
                )
            invalid_boolean = sorted(
                name
                for name, value in raw_inputs.items()
                if input_types[name] == "S231:BooleanInput" and not isinstance(value, bool)
            )
            if invalid_boolean:
                raise ValueError(
                    "Boolean source-algorithm inputs must be Boolean: " + ", ".join(invalid_boolean)
                )
            invalid_integer = sorted(
                name
                for name, value in raw_inputs.items()
                if input_types[name] == "S231:IntegerInput"
                and (isinstance(value, bool) or not isinstance(value, int))
            )
            if invalid_integer:
                raise ValueError(
                    "integer source-algorithm inputs must be integers: "
                    + ", ".join(invalid_integer)
                )
            invalid_real = sorted(
                name
                for name, value in raw_inputs.items()
                if input_types[name] == "S231:RealInput"
                and (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                )
            )
            if invalid_real:
                raise ValueError(
                    "Real source-algorithm inputs must be finite numeric: "
                    + ", ".join(invalid_real)
                )
            effective_inputs.update(raw_inputs)
            if controller_id == "StagingRotation.EquipmentEnable":
                stage_count = int(graph.metadata["stage_count"])
                equipment_count = int(graph.metadata["equipment_count"])
                alternate_count = int(graph.metadata["alternate_count"])
                if "uSta" in effective_inputs and not (
                    0 <= int(effective_inputs["uSta"]) <= stage_count
                ):
                    raise ValueError(f"sample {index} uSta must be from 0 through {stage_count}")
                alternate_names = [f"uIdxAltSor__{rank}" for rank in range(1, alternate_count + 1)]
                if all(name in effective_inputs for name in alternate_names):
                    alternate_indices = [int(effective_inputs[name]) for name in alternate_names]
                    if any(not 1 <= value <= equipment_count for value in alternate_indices):
                        raise ValueError(
                            f"sample {index} alternate equipment indices must be from "
                            f"1 through {equipment_count}"
                        )
                    if len(set(alternate_indices)) != len(alternate_indices):
                        raise ValueError(
                            f"sample {index} alternate equipment indices must be unique"
                        )
        missing = sorted(input_labels - set(samples[0]["inputs"]))
        if missing:
            raise ValueError(
                "first sample must initialize every public controller input; missing: "
                + ", ".join(missing)
            )
        selected = collect or sorted(output_labels)
        unknown_outputs = sorted(set(selected) - output_labels)
        if unknown_outputs:
            raise ValueError(
                "requested non-public controller outputs: " + ", ".join(unknown_outputs)
            )
        trace = self._simulate_typed_graph(
            graph,
            interface=interface,
            samples=samples,
            collect=selected,
        )
        return {
            "schema": "bactalk.plant-controls-execution/v1",
            "controller": translation["controller"],
            "translator": translation["translator"],
            "runtime": "BACTalk typed-IR interpreter",
            "execution_profile": "modelica_exact",
            "execution_profile_limitation": (
                "Direct pinned source-equation lowering; licensed Niagara runtime parity "
                "remains required."
            ),
            "interface": interface,
            "engine_report": translation["engine_report"],
            "connection_normalization": translation["connection_normalization"],
            "parameterization": translation["parameterization"],
            "trace": trace,
            "niagara_lowering_complete": translation["niagara_lowering_complete"],
            "library": "LBNL Modelica Buildings Templates.Plants.Controls",
        }


_CDL_SUBSTITUTES = Path(__file__).with_name("cdl_substitutes")


def cdl_substitute_documents() -> dict[str, dict[str, Any]]:
    """BACTalk's CDL block diagrams for LBNL utilities written as equations, by the class
    identifier they replace (docs/decisions/016; scripts/build_cdl_substitutes.py)."""

    manifest = json.loads((_CDL_SUBSTITUTES / "manifest.json").read_text(encoding="utf-8"))
    return {
        "ex:" + entry["replaces"]: json.loads(
            (_CDL_SUBSTITUTES / f"{name}.jsonld").read_text(encoding="utf-8")
        )
        for name, entry in sorted(manifest.items())
    }


class PlantControlsCdlLibrary(PlantControlsLibrary):
    """LBNL ``Templates.Plants.Controls`` through the plain CDL lane (Tier 2b).

    :class:`PlantControlsLibrary` keeps some utilities opaque and replaces several
    controllers with hand-written graphs, because its source-package lane has exact
    adapters for them. The native lane's Tier 2b rows need the other thing: LBNL's
    complete CDL translated like every Tier 2 controller, and the Open Control Engine
    executing that same CDL as the reference. This adapter keeps every class document
    and always takes the CXF path.

    LBNL writes five utilities as Modelica equations or an algorithm, which the engine
    cannot execute. Their places are taken by BACTalk's CDL block diagrams with the same
    interface and outputs (``cdl_substitutes``), so the engine runs the rest of the
    controller as LBNL wrote it; every translation names the substitutes it used.
    """

    def _source_bundle(
        self,
        controller_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
        substitutes = cdl_substitute_documents()
        root = "ex:Buildings.Templates.Plants.Controls." + controller_id
        if root in substitutes:
            controller = self._controllers().get(controller_id)
            if controller is None:
                raise KeyError(controller_id)
            return controller, copy.deepcopy(substitutes[root]), {}
        controller, document, class_documents = G36Library._source_bundle(self, controller_id)
        # LBNL's equation classes emit no block diagram, so the bundle holds none of
        # them; a substitute is offered only where some class instantiates it, so a
        # controller without one translates exactly as before.
        referenced = {
            str(node.get("@type", "")).removeprefix("ex:")
            for graph_document in (document, *class_documents.values(), *substitutes.values())
            for node in graph_document.get("@graph", [])
            if isinstance(node, dict)
        }
        used = {
            class_id: substitute
            for class_id, substitute in substitutes.items()
            if any(
                name
                and (class_id.removeprefix("ex:") == name or class_id.endswith("." + name))
                for name in referenced
            )
        }
        return controller, document, {**class_documents, **used}

    @staticmethod
    def _substitutes_used(controller_id: str, result: dict[str, Any]) -> list[str]:
        substitutes = set(cdl_substitute_documents())
        root = "ex:Buildings.Templates.Plants.Controls." + controller_id
        if root in substitutes:
            return [root.removeprefix("ex:")]
        assembly = (result.get("connection_normalization") or {}).get("composite_assembly") or {}
        expanded = {str(item.get("class_id")) for item in assembly.get("instances", [])}
        return sorted(item.removeprefix("ex:") for item in expanded & substitutes)

    def parameter_schema(self, controller_id: str) -> dict[str, Any]:
        result = G36Library.parameter_schema(self, controller_id)
        result["library"] = "LBNL Modelica Buildings Templates.Plants.Controls"
        return result

    def translate(
        self,
        controller_id: str,
        *,
        execution_profile: ExecutionProfile = "modelica_exact",
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = G36Library.translate(
            self,
            controller_id,
            execution_profile=execution_profile,
            parameters=parameters,
        )
        result["library"] = "LBNL Modelica Buildings Templates.Plants.Controls"
        result["cdl_substitutes"] = self._substitutes_used(controller_id, result)
        return result

    def execute(
        self,
        controller_id: str,
        *,
        samples: list[dict[str, Any]],
        collect: list[str] | None = None,
        parameters: dict[str, Any] | None = None,
        absent_inputs: list[str] | None = None,
    ) -> dict[str, Any]:
        result = G36Library.execute(
            self,
            controller_id,
            samples=samples,
            collect=collect,
            parameters=parameters,
            absent_inputs=absent_inputs,
        )
        result["library"] = "LBNL Modelica Buildings Templates.Plants.Controls"
        result["cdl_substitutes"] = self._substitutes_used(controller_id, result)
        return result
