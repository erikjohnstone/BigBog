from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import math
import re
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from bactalk.domain import BlockKind, ControlGraph
from bactalk.integrations.cdl import CdlTranslator
from bactalk.integrations.cxf_composites import (
    assemble_cxf_composites,
    flatten_cxf_topology,
)
from bactalk.integrations.cxf_connections import normalize_connection_sets
from bactalk.integrations.cxf_importer import (
    CxfImporter,
    ExecutionProfile,
    resolve_parameter_expression,
)
from bactalk.integrations.niagara_program_codegen import (
    NiagaraProgramCodegenError,
    NiagaraProgramPackageBuilder,
)
from bactalk.integrations.open_control_engine import OpenControlEngine
from bactalk.simulator import GraphInterpreter

_DECLARATION = re.compile(
    r"(?m)^\s*(?:partial\s+)?(?P<kind>block|model)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
)
_PARAMETER_DECLARATION = re.compile(
    r"(?m)^\s*(?:(?:final|replaceable|each)\s+)*parameter\s+"
    r"(?P<data_type>[A-Za-z_][A-Za-z0-9_.]*)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b"
)
_OCE_DIAGNOSTIC = re.compile(r"(?m)^(?P<severity>error|warning)\|(?P<code>[^|]+)\|")
_OCE_MISSING_CLASS = re.compile(r"no registered block class for `(?P<class>[^`]+)`")
_REVIEWED_COMPOSITE_CLASSES = frozenset(
    {
        "ASHRAE.G36.Generic.TrimAndRespond",
        "Utilities.Initialization",
        "Utilities.TimerWithReset",
        "Buildings.Templates.Plants.Controls.Utilities.TimerWithReset",
        "Utilities.PlaceholderLogical",
        "Utilities.PlaceholderReal",
        "Utilities.PlaceholderInteger",
        "Buildings.Templates.Plants.Controls.Utilities.PlaceholderLogical",
        "Buildings.Templates.Plants.Controls.Utilities.PlaceholderReal",
        "Buildings.Templates.Plants.Controls.Utilities.PlaceholderInteger",
        "Buildings.Controls.OBC.Utilities.PIDWithEnable",
        "Utilities.PIDWithEnable",
    }
)
_REVIEWED_COMPOSITE_DIAGNOSTICS = frozenset(
    {
        "class-not-found",
        "single-assignment",
        "unresolved-reference",
        "grounding-failed",
        # OCE emits this secondary warning when every driver for an output is
        # inside one of the explicitly reviewed, missing composite classes.
        "undriven-boundary-output",
    }
)
_PROGRAM_GENERATOR_CLASSES = frozenset(
    {
        "Buildings.Controls.OBC.CDL.Reals.PID",
        "Buildings.Controls.OBC.CDL.Reals.PIDWithReset",
        "Buildings.Controls.OBC.Utilities.PIDWithEnable",
        "Utilities.PIDWithEnable",
        "Buildings.Controls.OBC.CDL.Reals.Hysteresis",
        "Buildings.Controls.OBC.CDL.Logical.TrueFalseHold",
        "Buildings.Controls.OBC.CDL.Logical.TrueDelay",
        "Buildings.Controls.OBC.CDL.Logical.Latch",
        "Buildings.Controls.OBC.CDL.Logical.FallingEdge",
        "Buildings.Controls.OBC.CDL.Logical.Pre",
        "Buildings.Templates.Plants.Controls.Utilities.Initialization",
        "Utilities.Initialization",
        "Buildings.Templates.Plants.Controls.Utilities.TimerWithReset",
        "Utilities.TimerWithReset",
        "Buildings.Controls.OBC.CDL.Discrete.Sampler",
        "Buildings.Controls.OBC.CDL.Discrete.FirstOrderHold",
        "Buildings.Controls.OBC.CDL.Logical.Sources.SampleTrigger",
        "Buildings.Controls.OBC.CDL.Discrete.TriggeredSampler",
        "Buildings.Controls.OBC.CDL.Discrete.UnitDelay",
        "Buildings.Controls.OBC.CDL.Integers.Change",
        "Buildings.Controls.OBC.CDL.Reals.Change",
        "Buildings.Controls.OBC.CDL.Logical.Timer",
        "Buildings.Controls.OBC.CDL.Logical.TimerAccumulating",
        "Buildings.Controls.OBC.CDL.Reals.MovingAverage",
        "Buildings.Controls.OBC.CDL.Utilities.Assert",
        "Buildings.Controls.OBC.ASHRAE.G36.Generic.TrimAndRespond",
        ("Buildings.Templates.Plants.Controls.StagingRotation.EquipmentAvailability"),
        ("Buildings.Templates.Plants.Controls.StagingRotation.EquipmentEnable"),
        "Buildings.Templates.Plants.Controls.Enabling.Enable",
        ("Buildings.Templates.Plants.Controls.HeatRecoveryChillers.Controller"),
        ("Buildings.Templates.Plants.Controls.HeatRecoveryChillers.Enable"),
        ("Buildings.Templates.Plants.Controls.HeatRecoveryChillers.ModeControl"),
        ("Buildings.Templates.Plants.Controls.StagingRotation.StageCompletion"),
        "Buildings.Templates.Plants.Controls.Utilities.StageIndex",
        ("Buildings.Templates.Plants.Controls.StagingRotation.SortRuntime"),
        ("Buildings.Templates.Plants.Controls.Pumps.Generic.StagingHeaderedDeltaP"),
        ("Buildings.Templates.Plants.Controls.StagingRotation.StageChangeCommand"),
        "Buildings.Templates.Plants.Controls.Pumps.Generic.StagingHeadered",
        "Buildings.Templates.Plants.Controls.Pumps.Primary.VariableSpeed",
        "Buildings.Templates.Plants.Controls.HeatPumps.AirToWater",
    }
)
_STATEFUL_KINDS = frozenset(
    {
        BlockKind.BOOLEAN_DELAY,
        BlockKind.ONE_SHOT,
        BlockKind.BOOLEAN_FALLING_EDGE,
        BlockKind.MOVING_AVERAGE,
        BlockKind.NUMERIC_SAMPLER,
        BlockKind.NUMERIC_FIRST_ORDER_HOLD,
        BlockKind.BOOLEAN_SAMPLE_TRIGGER,
        BlockKind.NUMERIC_UNIT_DELAY,
        BlockKind.NUMERIC_CHANGED,
        BlockKind.NUMERIC_INCREASED,
        BlockKind.NUMERIC_DECREASED,
        BlockKind.NUMERIC_LATCH,
        BlockKind.BOOLEAN_LATCH,
        BlockKind.BOOLEAN_PRE_HOST_TICK,
        BlockKind.BOOLEAN_INITIALIZATION,
        BlockKind.BOOLEAN_SET_RESET,
        BlockKind.BOOLEAN_TRUE_FALSE_HOLD,
        BlockKind.HYSTERESIS,
        BlockKind.TIMER,
        BlockKind.TIMER_WITH_RESET,
        BlockKind.TIMER_ACCUMULATING,
        BlockKind.TRIM_AND_RESPOND,
        BlockKind.TRIM_AND_RESPOND_HOLD,
        BlockKind.PI_LOOP,
        BlockKind.PID_WITH_RESET,
        BlockKind.PLANT_EQUIPMENT_AVAILABILITY,
        BlockKind.PLANT_ENABLE,
        BlockKind.PLANT_HRC_ENABLE,
        BlockKind.PLANT_HRC_MODE_CONTROL,
        BlockKind.PLANT_STAGE_COMPLETION,
        BlockKind.PLANT_STAGE_INDEX,
    }
)

_NIAGARA_TARGET_BLOCKERS: dict[str, dict[str, Any]] = {
    "Buildings.Controls.OBC.CDL.Reals.PID": {
        "reason": (
            "Niagara kitControl:LoopPoint is not behaviorally equivalent to the CDL PID "
            "controller across controller type, Ni anti-windup, and Nd derivative filtering."
        ),
        "unsafe_substitution": "kitControl:LoopPoint",
        "resolution": (
            "Supply one exact typed component in the contractor environment pack, or "
            "download BACTalk's exact ProgramObject source package and compile it in "
            "licensed Workbench, then pass trajectory parity tests."
        ),
    },
    "Buildings.Controls.OBC.CDL.Reals.PIDWithReset": {
        "reason": (
            "Niagara kitControl:LoopPoint is not behaviorally equivalent to CDL "
            "PIDWithReset: reset targets, anti-windup back-calculation (Ni), and the "
            "filtered derivative (Nd) have different contracts."
        ),
        "unsafe_substitution": "kitControl:LoopPoint",
        "resolution": (
            "Supply one exact typed component in the contractor environment pack, or "
            "download BACTalk's exact ProgramObject source package and compile it in "
            "licensed Workbench, then "
            "pass trajectory and reset-event parity tests."
        ),
    },
    "Buildings.Controls.OBC.Utilities.PIDWithEnable": {
        "reason": (
            "PIDWithEnable is a pinned source composite around the exact CDL "
            "PIDWithReset recurrence and enable/neutral selectors; no single stock "
            "Niagara block has that complete contract."
        ),
        "unsafe_substitution": "kitControl:LoopPoint",
        "resolution": (
            "Use the exact expanded graph and generated PIDWithReset ProgramObject, "
            "compile it in licensed Workbench, and replay enable/reset trajectories."
        ),
    },
    "Utilities.PIDWithEnable": {
        "reason": (
            "PIDWithEnable is a pinned source composite around the exact CDL "
            "PIDWithReset recurrence and enable/neutral selectors; no single stock "
            "Niagara block has that complete contract."
        ),
        "unsafe_substitution": "kitControl:LoopPoint",
        "resolution": (
            "Use the exact expanded graph and generated PIDWithReset ProgramObject, "
            "compile it in licensed Workbench, and replay enable/reset trajectories."
        ),
    },
    "Buildings.Controls.OBC.CDL.Reals.Hysteresis": {
        "reason": (
            "BACTalk has not qualified a stock Niagara hysteresis block with the exact CDL "
            "strict-boundary and initial-state contract."
        ),
        "unsafe_substitution": None,
        "resolution": (
            "Use the generated exact Hysteresis ProgramObject package, compile it in licensed "
            "Workbench, and replay the boundary trajectory."
        ),
    },
    "Buildings.Controls.OBC.CDL.Logical.TrueFalseHold": {
        "reason": (
            "The minimum true/false dwell contract is stateful and has no qualified stock "
            "Niagara substitution."
        ),
        "unsafe_substitution": None,
        "resolution": (
            "Use the generated exact TrueFalseHold ProgramObject package, compile it in "
            "licensed Workbench, and replay the dwell trajectory."
        ),
    },
    "Buildings.Controls.OBC.CDL.Logical.Latch": {
        "reason": (
            "The CDL latch is clear-dominant and responds only to a rising set edge; no "
            "stock Niagara substitution has been qualified for that full contract."
        ),
        "unsafe_substitution": None,
        "resolution": (
            "Use the generated exact Latch ProgramObject package, compile it in licensed "
            "Workbench, and replay the set/clear edge trajectory."
        ),
    },
    "Buildings.Controls.OBC.CDL.Logical.Timer": {
        "reason": (
            "The CDL timer exposes both elapsed time and an edge-sensitive threshold latch; "
            "no stock Niagara substitution has been qualified for both outputs."
        ),
        "unsafe_substitution": None,
        "resolution": (
            "Use the generated exact Timer ProgramObject package, compile it in licensed "
            "Workbench, and replay elapsed/threshold edge trajectories."
        ),
    },
    "Buildings.Controls.OBC.CDL.Reals.MovingAverage": {
        "reason": (
            "The CDL moving average requires variable-step delayed-integral history and "
            "startup semantics that have no qualified stock Niagara substitution."
        ),
        "unsafe_substitution": None,
        "resolution": (
            "Use the generated exact MovingAverage ProgramObject package, compile it in "
            "licensed Workbench, and replay startup, steady-window, and overflow vectors."
        ),
    },
    "Buildings.Controls.OBC.CDL.Utilities.Assert": {
        "reason": (
            "CDL Assert is a zero-output warning sink that emits on every false evaluation; "
            "no stock Niagara wire-sheet block has that exact diagnostics contract."
        ),
        "unsafe_substitution": None,
        "resolution": (
            "Use the generated AssertWarning ProgramObject source package, compile it in "
            "licensed Workbench, and verify repeated false-condition warning records."
        ),
    },
    "Buildings.Controls.OBC.CDL.Logical.FallingEdge": {
        "reason": (
            "The initial pre(u) seed is part of the CDL FallingEdge contract and is not "
            "qualified against a stock Niagara pulse block."
        ),
        "unsafe_substitution": "kitControl:OneShot",
        "resolution": (
            "Use the generated exact FallingEdge ProgramObject source, compile it in licensed "
            "Workbench, and replay initialization plus true-to-false edge vectors."
        ),
    },
    "Buildings.Controls.OBC.CDL.Logical.Pre": {
        "reason": (
            "CDL Pre is available only through the explicit host_tick_v1 sampled-scan "
            "projection; it is not represented as Modelica same-time event iteration."
        ),
        "unsafe_substitution": None,
        "resolution": (
            "Select host_tick_v1 explicitly, use the generated BooleanPreHostTick "
            "ProgramObject source, and qualify the exact Niagara scan period and restart state."
        ),
    },
    "Buildings.Templates.Plants.Controls.Utilities.Initialization": {
        "reason": (
            "The plant Initialization block forces yIni only on the first evaluation "
            "after runtime start and then becomes a pass-through; no stock Niagara "
            "substitution has been qualified for that restart contract."
        ),
        "unsafe_substitution": None,
        "resolution": (
            "Use the generated exact plant Initialization ProgramObject source, compile "
            "it in licensed Workbench, and replay first-scan and restart vectors."
        ),
    },
    "Utilities.Initialization": {
        "reason": (
            "The plant Initialization block forces yIni only on the first evaluation "
            "after runtime start and then becomes a pass-through; no stock Niagara "
            "substitution has been qualified for that restart contract."
        ),
        "unsafe_substitution": None,
        "resolution": (
            "Use the generated exact plant Initialization ProgramObject source, compile "
            "it in licensed Workbench, and replay first-scan and restart vectors."
        ),
    },
    "Buildings.Templates.Plants.Controls.Utilities.TimerWithReset": {
        "reason": (
            "The plant TimerWithReset has a reset-edge recurrence and two coupled outputs; "
            "no stock Niagara substitution has been qualified for its complete contract."
        ),
        "unsafe_substitution": None,
        "resolution": (
            "Use the generated exact plant TimerWithReset ProgramObject source, compile "
            "it in licensed Workbench, and replay input/reset/threshold trajectories."
        ),
    },
    "Utilities.TimerWithReset": {
        "reason": (
            "The plant TimerWithReset has a reset-edge recurrence and two coupled outputs; "
            "no stock Niagara substitution has been qualified for its complete contract."
        ),
        "unsafe_substitution": None,
        "resolution": (
            "Use the generated exact plant TimerWithReset ProgramObject source, compile "
            "it in licensed Workbench, and replay input/reset/threshold trajectories."
        ),
    },
    "Buildings.Controls.OBC.ASHRAE.G36.Generic.TrimAndRespond": {
        "reason": (
            "The reviewed G36 TrimAndRespond recurrence combines delayed enable, sampled "
            "requests, unit-delay feedback, bounded trim/respond, and device-off reset; no "
            "stock Niagara block has that complete contract."
        ),
        "unsafe_substitution": None,
        "resolution": (
            "Supply one exact typed component in the contractor environment pack, or "
            "download BACTalk's exact have_hol=false ProgramObject source package, compile "
            "it in licensed Workbench, and pass trajectory/timing parity tests."
        ),
    },
}


class G36RequiredParametersError(RuntimeError):
    def __init__(self, controller_id: str, parameterization: dict[str, Any]):
        self.controller_id = controller_id
        self.parameterization = parameterization
        required = parameterization["remaining_required_parameters"]
        super().__init__(f"{controller_id} requires job parameter values: " + ", ".join(required))


class G36Library:
    """Allowlisted LBNL G36 source catalog with real CDL→CXF→OCE translation."""

    def __init__(
        self,
        modelica_root: Path = Path(".vendor/modelica-buildings"),
        modelica_json_root: Path = Path(".vendor/modelica-json"),
        *,
        engine: OpenControlEngine | None = None,
    ):
        self.modelica_root = modelica_root.resolve()
        self.g36_root = (self.modelica_root / "Buildings/Controls/OBC/ASHRAE/G36").resolve()
        self.translator = CdlTranslator(
            modelica_json_root.resolve(),
            modelica_path=self.modelica_root,
        )
        self.engine = engine or OpenControlEngine()
        self.importer = CxfImporter()
        self.program_packages = NiagaraProgramPackageBuilder()

    def catalog(self) -> dict[str, Any]:
        controllers = list(self._controllers().values())
        family_counts = Counter(item["family"] for item in controllers)
        return {
            "schema": "bactalk.g36-library/v1",
            "source": "LBNL Modelica Buildings Library",
            "license": "Revised BSD-3-Clause",
            "controller_count": len(controllers),
            "non_validation_controller_count": sum(
                not item["validation_fixture"] for item in controllers
            ),
            "family_counts": dict(sorted(family_counts.items())),
            "controllers": controllers,
            "execution_path": "modelica-json CXF -> Open Control Engine",
            "niagara_lowering_complete": False,
        }

    def parameter_schema(self, controller_id: str) -> dict[str, Any]:
        controller, document = self._source_document(controller_id)
        _, parameterization = self._apply_parameter_overrides(document, {})
        return {
            "schema": "bactalk.g36-parameter-schema/v1",
            "controller": controller,
            "parameterization": parameterization,
        }

    def translate(
        self,
        controller_id: str,
        *,
        execution_profile: ExecutionProfile = "modelica_exact",
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        controller, document, engine_report, normalization, parameterization = self._translate(
            controller_id,
            parameters=parameters,
            execution_profile=execution_profile,
        )
        interface = self._interface(document)
        coverage = self.importer.inspect(
            document,
            execution_profile=execution_profile,
        )
        graph = (
            self.importer.import_graph(
                document,
                execution_profile=execution_profile,
            )
            if coverage["translatable"]
            else None
        )
        target = self._niagara_target(coverage)
        return {
            "schema": "bactalk.g36-translation/v1",
            "controller": controller,
            "translator": "LBNL modelica-json",
            "runtime": "Open Control Engine",
            "execution_profile": execution_profile,
            "interface": interface,
            "cxf_document": document,
            "engine_report": engine_report,
            "connection_normalization": normalization,
            "parameterization": parameterization,
            "typed_ir": graph.model_dump(mode="json") if graph is not None else None,
            "lowering": coverage,
            "niagara_lowering_complete": coverage["niagara_translatable"],
            "niagara_target": target,
        }

    def execute(
        self,
        controller_id: str,
        *,
        samples: list[dict[str, Any]],
        collect: list[str] | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Translate and execute one allowlisted controller by public port name.

        The controller-specific route deliberately admits only public controller
        inputs and outputs. Internal block ports remain available through the
        lower-level CXF endpoint for engineering/debugging, but cannot be
        accidentally treated as the stable product interface here.
        """

        controller, document, engine_report, normalization, parameterization = self._translate(
            controller_id, parameters=parameters
        )
        interface = self._interface(document)
        input_ids = {port["label"]: port["id"] for port in interface["inputs"]}
        output_ids = {port["label"]: port["id"] for port in interface["outputs"]}
        output_labels_by_id = {identifier: label for label, identifier in output_ids.items()}
        input_aliases = {**input_ids, **{value: value for value in input_ids.values()}}
        output_aliases = {**output_ids, **{value: value for value in output_ids.values()}}

        normalized_samples: list[dict[str, Any]] = []
        for index, sample in enumerate(samples):
            raw_inputs = sample.get("inputs")
            if not isinstance(raw_inputs, dict):
                raise ValueError(f"sample {index} inputs must be an object")
            unknown = sorted(set(raw_inputs) - set(input_aliases))
            if unknown:
                raise ValueError(
                    f"sample {index} contains non-public controller inputs: " + ", ".join(unknown)
                )
            normalized_samples.append(
                {
                    "time": sample.get("time"),
                    "inputs": {input_aliases[name]: value for name, value in raw_inputs.items()},
                }
            )

        supplied_first = set(normalized_samples[0]["inputs"])
        missing_first = sorted(set(input_ids.values()) - supplied_first)
        if missing_first:
            missing_labels = [label for label, path in input_ids.items() if path in missing_first]
            raise ValueError(
                "first sample must initialize every public controller input; missing: "
                + ", ".join(missing_labels)
            )

        requested_outputs = collect or list(output_ids)
        unknown_outputs = sorted(set(requested_outputs) - set(output_aliases))
        if unknown_outputs:
            raise ValueError(
                "requested non-public controller outputs: " + ", ".join(unknown_outputs)
            )
        normalized_outputs = [output_aliases[name] for name in requested_outputs]
        requested_output_labels = [
            name if name in output_ids else output_labels_by_id[name] for name in requested_outputs
        ]
        if engine_report.get("oce_validation_succeeded", True):
            trace = self.engine.simulate_document(
                document,
                samples=normalized_samples,
                collect=normalized_outputs,
            )
            runtime = "Open Control Engine"
            execution_profile = "host_tick_v1"
            profile_limitation = (
                "CDL.Logical.Pre, when present, advances once per host call and is not "
                "Modelica same-time event iteration."
            )
        else:
            graph = self.importer.import_graph(document)
            trace = self._simulate_typed_graph(
                graph,
                interface=interface,
                samples=samples,
                collect=requested_output_labels,
            )
            runtime = "BACTalk typed-IR interpreter"
            execution_profile = "typed_ir_scan_v1"
            profile_limitation = (
                "The reviewed composite lowering is source-bound and golden-tested, but "
                "Open Control Engine did not validate the authored parent CXF."
            )
        return {
            "schema": "bactalk.g36-execution/v1",
            "controller": controller,
            "translator": "LBNL modelica-json",
            "runtime": runtime,
            "execution_profile": execution_profile,
            "execution_profile_limitation": profile_limitation,
            "interface": interface,
            "engine_report": engine_report,
            "connection_normalization": normalization,
            "parameterization": parameterization,
            "trace": trace,
            "niagara_lowering_complete": False,
        }

    def niagara_program_package(
        self,
        controller_id: str,
        *,
        parameters: dict[str, Any] | None = None,
        execution_profile: ExecutionProfile = "modelica_exact",
    ) -> tuple[bytes, str]:
        controller, document, _, _, _ = self._translate(
            controller_id,
            parameters=parameters,
            execution_profile=execution_profile,
        )
        coverage = self.importer.inspect(document, execution_profile=execution_profile)
        if not coverage["translatable"]:
            raise NiagaraProgramCodegenError(
                "controller must lower completely to typed IR before ProgramObject generation"
            )
        unsupported = set(coverage["niagara_unsupported_classes"])
        unhandled = sorted(unsupported - _PROGRAM_GENERATOR_CLASSES)
        if unhandled:
            raise NiagaraProgramCodegenError(
                "ProgramObject generator does not cover Niagara target classes: "
                + ", ".join(unhandled)
            )
        exactness_blockers = [
            reason
            for reason in coverage.get("niagara_exactness_blockers", [])
            if "delayOnInit=false is not equivalent" not in reason
        ]
        if exactness_blockers:
            raise NiagaraProgramCodegenError(
                "ProgramObject generator does not cover Niagara exactness blockers: "
                + "; ".join(exactness_blockers)
            )
        graph = self.importer.import_graph(
            document,
            execution_profile=execution_profile,
        )
        content = self.program_packages.build(
            graph,
            controller_id=controller["id"],
        )
        filename = re.sub(r"[^A-Za-z0-9_.-]+", "-", controller["id"])
        return content, f"{filename}-niagara-programs.zip"

    def job_template(
        self,
        controller_id: str,
        *,
        parameters: dict[str, Any] | None = None,
        execution_profile: ExecutionProfile = "modelica_exact",
    ) -> dict[str, Any]:
        translation = self.translate(
            controller_id,
            execution_profile=execution_profile,
            parameters=parameters,
        )
        assessment = self.assess_niagara_source_target(translation)
        if not assessment["complete"]:
            raise NiagaraProgramCodegenError(
                f"controller has no complete Niagara target: {assessment['blocker']}"
            )
        return self._configured_job_template(
            translation,
            parameters=parameters or {},
            execution_profile=execution_profile,
            sequence_family="LBNL_G36_CONTROLLER",
            sequence_library="g36",
            version="Pinned LBNL Modelica Buildings G36 source",
        )

    def _configured_job_template(
        self,
        translation: dict[str, Any],
        *,
        parameters: dict[str, Any],
        execution_profile: ExecutionProfile,
        sequence_family: str,
        sequence_library: str,
        version: str,
    ) -> dict[str, Any]:
        """Build an exact intake contract from a translated public interface."""

        graph = ControlGraph.model_validate(translation["typed_ir"])
        boundary_ids = {
            block.id
            for block in graph.blocks
            if block.kind
            in {
                BlockKind.NUMERIC_INPUT,
                BlockKind.BOOLEAN_INPUT,
                BlockKind.NUMERIC_OUTPUT,
                BlockKind.BOOLEAN_OUTPUT,
            }
        }
        points: list[dict[str, Any]] = []
        for direction in ("inputs", "outputs"):
            for port in translation["interface"][direction]:
                point_name = next(
                    (
                        candidate
                        for candidate in (port["label"], port["id"])
                        if candidate in boundary_ids
                    ),
                    None,
                )
                if point_name is None:
                    raise ValueError(
                        f"controller interface port {port['label']!r} has no typed-IR boundary"
                    )
                is_boolean = "Boolean" in str(port["type"])
                points.append(
                    {
                        "name": point_name,
                        "label": port["label"],
                        "data_type": "boolean" if is_boolean else "numeric",
                        "role": "sensor" if direction == "inputs" else "command",
                        "default": False if is_boolean else 0.0,
                        "required": True,
                        "source_interface_id": port["id"],
                        "source_interface_direction": (
                            "input" if direction == "inputs" else "output"
                        ),
                        "source_interface_type": port["type"],
                    }
                )
        target = io.StringIO(newline="")
        writer = csv.DictWriter(
            target,
            fieldnames=["name", "label", "data_type", "role", "default", "required"],
        )
        writer.writeheader()
        for point in points:
            writer.writerow({name: point[name] for name in writer.fieldnames})
        return {
            "schema": "bactalk.library-controller-job-template/v1",
            "sequence": {
                "family": sequence_family,
                "version": version,
                "library": sequence_library,
                "controller_id": translation["controller"]["id"],
                "execution_profile": execution_profile,
                "parameters": parameters,
            },
            "product_status": translation.get("product_status", "source_target_complete"),
            "target_assessment": self.assess_niagara_source_target(translation),
            "points": points,
            "points_csv": target.getvalue(),
            "acceptance_output_targets": [
                {
                    "target": point["name"],
                    "data_type": point["data_type"],
                    "required": True,
                }
                for point in points
                if point["source_interface_direction"] == "output"
            ],
            "instructions": (
                "Map every interface row to the contractor points/BACnet scan, then replace "
                "defaults and author independent acceptance timelines that observe every "
                "output. Do not use placeholder values as a test oracle."
            ),
        }

    def assess_niagara_source_target(self, translation: dict[str, Any]) -> dict[str, Any]:
        """Prove stock or generated-source completion without claiming runtime qualification."""

        coverage = translation["lowering"]
        if not coverage["translatable"]:
            return {
                "complete": False,
                "delivery_mode": None,
                "generated_program_count": 0,
                "blocker": "typed IR lowering is incomplete",
            }
        if coverage["niagara_translatable"]:
            return {
                "complete": True,
                "delivery_mode": "qualified_stock_components",
                "generated_program_count": 0,
                "blocker": None,
            }
        unsupported = set(coverage["niagara_unsupported_classes"])
        unhandled = sorted(unsupported - _PROGRAM_GENERATOR_CLASSES)
        exactness_blockers = [
            reason
            for reason in coverage.get("niagara_exactness_blockers", [])
            if "delayOnInit=false is not equivalent" not in reason
        ]
        blockers = [
            *(f"unhandled target class: {class_name}" for class_name in unhandled),
            *(f"unhandled target exactness: {reason}" for reason in exactness_blockers),
        ]
        if blockers:
            return {
                "complete": False,
                "delivery_mode": None,
                "generated_program_count": 0,
                "blocker": "; ".join(blockers),
            }
        typed_ir = translation.get("typed_ir")
        if typed_ir is None:
            return {
                "complete": False,
                "delivery_mode": None,
                "generated_program_count": 0,
                "blocker": "translation omitted typed IR",
            }
        try:
            content = self.program_packages.build(
                ControlGraph.model_validate(typed_ir),
                controller_id=translation["controller"]["id"],
            )
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                manifest = json.loads(archive.read("manifest.json"))
        except (NiagaraProgramCodegenError, ValueError, KeyError, zipfile.BadZipFile) as exc:
            return {
                "complete": False,
                "delivery_mode": None,
                "generated_program_count": 0,
                "blocker": str(exc),
            }
        return {
            "complete": True,
            "delivery_mode": "generated_program_source",
            "generated_program_count": len(manifest["programs"]),
            "blocker": None,
            "runtime_qualified": False,
            "licensed_workbench_compile_required": True,
        }

    @staticmethod
    def _niagara_target(coverage: dict[str, Any]) -> dict[str, Any]:
        unsupported = list(coverage.get("niagara_unsupported_classes", []))
        blockers = []
        for class_name in unsupported:
            detail = _NIAGARA_TARGET_BLOCKERS.get(
                class_name,
                {
                    "reason": "No exact stock Niagara lowering is currently qualified.",
                    "unsafe_substitution": None,
                    "resolution": (
                        "Supply a behaviorally exact typed component through the contractor "
                        "environment pack and qualify it in the licensed runtime matrix."
                    ),
                },
            )
            blockers.append({"class": class_name, **detail})
        for reason in coverage.get("niagara_exactness_blockers", []):
            blockers.append(
                {
                    "class": "Buildings.Controls.OBC.CDL.Logical.TrueDelay",
                    "reason": reason,
                    "unsafe_substitution": "kitControl:BooleanDelay",
                    "resolution": (
                        "Use an exact typed environment component or generated temporal "
                        "ProgramObject and pass initial-condition trajectory parity."
                    ),
                }
            )
        if coverage.get("niagara_translatable"):
            status = "native_lowering_complete"
        elif coverage.get("translatable"):
            status = "contractor_component_required"
        else:
            status = "typed_ir_incomplete"
        return {
            "status": status,
            "native_lowering_complete": bool(coverage.get("niagara_translatable")),
            "typed_environment_component_lane": bool(
                coverage.get("translatable")
                and (unsupported or coverage.get("niagara_exactness_blockers"))
            ),
            "blockers": blockers,
            "exactness_policy": (
                "BACTalk rejects behaviorally different stock substitutions; target "
                "completion requires declared slot/config mappings and runtime parity evidence."
            ),
        }

    def _apply_parameter_overrides(
        self,
        document: dict[str, Any],
        overrides: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if len(overrides) > 128:
            raise ValueError("at most 128 G36 parameter overrides are allowed")
        parameterized = copy.deepcopy(document)
        graph = parameterized.get("@graph")
        if not isinstance(graph, list):
            raise ValueError("CXF document is missing its JSON-LD graph")
        nodes = {
            node["@id"]: node
            for node in graph
            if isinstance(node, dict) and isinstance(node.get("@id"), str)
        }
        roots = [
            node for node in graph if isinstance(node, dict) and node.get("S231:containsBlock")
        ]
        if len(roots) != 1:
            raise ValueError(
                f"CXF must have exactly one root with containsBlock; found {len(roots)}"
            )
        root = roots[0]
        references: list[str] = []
        for key in ("S231:hasParameter", "S231:hasInstance"):
            raw = root.get(key)
            values = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
            references.extend(
                value["@id"]
                for value in values
                if isinstance(value, dict) and isinstance(value.get("@id"), str)
            )

        available: dict[str, dict[str, Any]] = {}
        for identifier in references:
            node = nodes.get(identifier)
            if node is None:
                continue
            node_type = node.get("@type")
            type_values = node_type if isinstance(node_type, list) else [node_type]
            if not any(
                isinstance(value, str)
                and value.rsplit("#", 1)[-1] in {"S231:Parameter", "Parameter"}
                for value in type_values
            ):
                continue
            label = node.get("S231:label")
            if not isinstance(label, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", label):
                label = identifier.rsplit(".", 1)[-1]
            if label in available:
                raise ValueError(f"ambiguous root G36 parameter label: {label}")
            available[label] = node

        unknown = sorted(set(overrides) - set(available))
        if unknown:
            raise ValueError("unknown or non-root G36 parameter overrides: " + ", ".join(unknown))

        required = sorted(name for name, node in available.items() if "S231:value" not in node)
        applied: list[dict[str, Any]] = []

        def scalar_literal(name: str, data_type_name: str, value: Any) -> str:
            if data_type_name == "Boolean":
                if not isinstance(value, bool):
                    raise ValueError(f"G36 parameter {name} requires Boolean array values")
                return str(value).lower()
            if data_type_name == "Integer":
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError(f"G36 parameter {name} requires Integer array values")
                return str(value)
            if data_type_name == "Real":
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                ):
                    raise ValueError(f"G36 parameter {name} requires finite Real array values")
                return repr(float(value))
            raise ValueError(f"G36 array parameter {name} has unsupported type {data_type_name!r}")

        def array_literal(
            name: str,
            data_type_name: str,
            value: Any,
            *,
            depth: int = 0,
        ) -> tuple[str, tuple[int, ...], int]:
            if depth > 4:
                raise ValueError(f"G36 array parameter {name} exceeds four dimensions")
            if not isinstance(value, list):
                return scalar_literal(name, data_type_name, value), (), 1
            if not value:
                raise ValueError(f"G36 array parameter {name} cannot contain an empty dimension")
            children = [
                array_literal(name, data_type_name, item, depth=depth + 1) for item in value
            ]
            child_shapes = {child[1] for child in children}
            if len(child_shapes) != 1:
                raise ValueError(f"G36 array parameter {name} must be rectangular")
            shape = (len(value), *children[0][1])
            count = sum(child[2] for child in children)
            if count > 4_096:
                raise ValueError(f"G36 array parameter {name} exceeds 4096 scalar values")
            return "{" + ",".join(child[0] for child in children) + "}", shape, count

        def declared_shape(name: str, node: dict[str, Any]) -> tuple[int, ...]:
            raw = node.get("S231:sizeOfDimensions")
            if raw is None:
                number_dimensions = node.get("S231:numberDimensions")
                if number_dimensions not in {1, "1"}:
                    raise ValueError(
                        f"G36 array parameter {name} has an unsupported unsized "
                        "multi-dimensional declaration"
                    )
                # Modelica's connector-sizing idiom declares plant design arrays as ``[:]``
                # and binds the surrounding component arrays with ``nEqu``. The CXF therefore
                # has no sizeOfDimensions on the parameter itself. Admit only that explicit,
                # integer, already-bound root dimension contract; do not infer from the value.
                dimension_node = available.get("nEqu")
                dimension_value = (
                    dimension_node.get("S231:value") if dimension_node is not None else None
                )
                if (
                    isinstance(dimension_value, bool)
                    or not isinstance(dimension_value, int)
                    or not 1 <= dimension_value <= 512
                ):
                    raise ValueError(
                        f"G36 unsized array parameter {name} requires Integer root "
                        "dimension nEqu to be supplied first (1 through 512)"
                    )
                return (dimension_value,)
            if not isinstance(raw, str) or not re.fullmatch(
                r"\(\s*[A-Za-z0-9_]+(?:\s*,\s*[A-Za-z0-9_]+)*\s*\)", raw
            ):
                raise ValueError(
                    f"G36 array parameter {name} has an unsupported dimension declaration"
                )
            dimensions: list[int] = []
            for token in (item.strip() for item in raw[1:-1].split(",")):
                if token.isdigit():
                    dimension = int(token)
                else:
                    dimension_node = available.get(token)
                    dimension_value = (
                        dimension_node.get("S231:value") if dimension_node is not None else None
                    )
                    if isinstance(dimension_value, bool) or not isinstance(dimension_value, int):
                        raise ValueError(
                            f"G36 array parameter {name} requires Integer dimension "
                            f"parameter {token} to be supplied first"
                        )
                    dimension = dimension_value
                if not 1 <= dimension <= 512:
                    raise ValueError(
                        f"G36 array parameter {name} dimension {token} must be 1 through 512"
                    )
                dimensions.append(dimension)
            return tuple(dimensions)

        ordered_names = sorted(
            overrides,
            key=lambda name: (available[name].get("S231:isArray") is True, name),
        )
        for name in ordered_names:
            node = available[name]
            if node.get("S231:isFinal") is True:
                raise ValueError(f"G36 parameter {name} is final and cannot be overridden")
            value = overrides[name]
            type_ref = node.get("S231:isOfDataType")
            data_type = type_ref.get("@id") if isinstance(type_ref, dict) else type_ref
            data_type_name = str(data_type).rsplit("#", 1)[-1].rsplit(":", 1)[-1]
            is_array = node.get("S231:isArray") is True
            cxf_value: Any = value
            if is_array:
                if not isinstance(value, list):
                    raise ValueError(f"G36 parameter {name} requires a JSON array value")
                cxf_value, actual_shape, _ = array_literal(name, data_type_name, value)
                expected_shape = declared_shape(name, node)
                if actual_shape != expected_shape:
                    raise ValueError(
                        f"G36 array parameter {name} shape {actual_shape} does not match "
                        f"declared shape {expected_shape}"
                    )
            elif data_type_name == "Boolean":
                if not isinstance(value, bool):
                    raise ValueError(f"G36 parameter {name} requires a Boolean value")
            elif data_type_name == "Integer":
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError(f"G36 parameter {name} requires an Integer value")
            elif data_type_name == "Real":
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                ):
                    raise ValueError(f"G36 parameter {name} requires a finite Real value")
                value = float(value)
            elif data_type_name == "String":
                if not isinstance(value, str) or not 1 <= len(value) <= 500:
                    raise ValueError(f"G36 parameter {name} requires a bounded String value")
                cxf_value = json.dumps(value, ensure_ascii=False)
            elif isinstance(value, str) and "." in data_type_name:
                if (
                    len(value) > 500
                    or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", value)
                    or not value.startswith(data_type_name + ".")
                ):
                    raise ValueError(f"G36 parameter {name} requires a member of {data_type_name}")
            else:
                raise ValueError(f"G36 parameter {name} has unsupported type {data_type_name!r}")
            if not is_array:
                if data_type_name != "String":
                    cxf_value = value
            previous = node.get("S231:value")
            node["S231:value"] = cxf_value
            applied.append(
                {
                    "name": name,
                    "data_type": data_type_name,
                    "previous_value": previous,
                    "value": value,
                    "cxf_value": cxf_value,
                }
            )

        def reference_value(parameter_node: dict[str, Any], key: str) -> str | None:
            raw = parameter_node.get(key)
            value = raw.get("@id") if isinstance(raw, dict) else raw
            return value if isinstance(value, str) else None

        parameter_records = []
        for name in sorted(available):
            node = available[name]
            type_ref = node.get("S231:isOfDataType")
            data_type = type_ref.get("@id") if isinstance(type_ref, dict) else type_ref
            data_type_name = str(data_type).rsplit("#", 1)[-1].rsplit(":", 1)[-1]

            parameter_records.append(
                {
                    "name": name,
                    "data_type": data_type_name,
                    "is_array": node.get("S231:isArray") is True,
                    "number_dimensions": node.get("S231:numberDimensions"),
                    "size_of_dimensions": node.get("S231:sizeOfDimensions"),
                    "required": name in required,
                    "value": node.get("S231:value"),
                    "description": node.get("S231:description"),
                    "unit": reference_value(node, "qudt:hasUnit"),
                    "quantity": reference_value(node, "qudt:hasQuantityKind"),
                    "overridable": node.get("S231:isFinal") is not True,
                    "metadata_source": (
                        "modelica_source_recovery"
                        if "_bactalk_recovered_parameter_type" in node
                        else "cxf"
                    ),
                }
            )
        for node in available.values():
            node.pop("_bactalk_recovered_parameter_type", None)
        return parameterized, {
            "schema": "bactalk.g36-parameterization/v2",
            "available_parameters": sorted(available),
            "required_parameters": required,
            "remaining_required_parameters": sorted(
                name for name, node in available.items() if "S231:value" not in node
            ),
            "parameters": parameter_records,
            "applied": applied,
        }

    def _source_document(
        self,
        controller_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        controller, document, _ = self._source_bundle(controller_id)
        return controller, document

    def _source_bundle(
        self,
        controller_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
        """Translate one controller and retain every emitted composite class.

        modelica-json writes referenced non-primitive classes as adjacent CXF
        documents. Keeping those documents is required to instantiate a concrete
        hierarchy before independent runtime validation; selecting only the root
        silently discards the implementation of every nested controller.
        """

        controller = self._controllers().get(controller_id)
        if controller is None:
            raise KeyError(controller_id)
        source = self.g36_root / controller["relative_path"]
        # modelica-json takes minutes on a large controller and its output depends only
        # on the pinned source, so one translation per (controller, source digest) is
        # kept for the life of this library instance; callers get their own copy.
        cache: dict[tuple[str, str], tuple[Any, Any, Any]] = self.__dict__.setdefault(
            "_source_bundle_cache", {}
        )
        key = (controller_id, str(controller["source_sha256"]))
        if key in cache:
            return copy.deepcopy(cache[key])
        bundle = self._source_bundle_uncached(controller, source)
        cache[key] = copy.deepcopy(bundle)
        return bundle

    def _source_bundle_uncached(
        self, controller: dict[str, Any], source: Path
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
        with tempfile.TemporaryDirectory(prefix="bactalk-g36-") as directory:
            output = Path(directory).resolve()
            artifacts = self.translator.translate(source, output)
            relative_source = source.relative_to(self.modelica_root).with_suffix(".jsonld")
            cxf_root = output / "cxf"
            expected = cxf_root / relative_source
            exact = [path for path in artifacts if path.resolve() == expected]
            if len(exact) != 1:
                names = ", ".join(path.name for path in artifacts[:20])
                raise RuntimeError(
                    "G36 translation did not emit the source-qualified CXF artifact "
                    f"{relative_source.as_posix()}; "
                    f"generated: {names}"
                )
            documents: dict[str, dict[str, Any]] = {}
            selected_id: str | None = None
            for path in artifacts:
                if path.suffix != ".jsonld" or not path.resolve().is_relative_to(cxf_root):
                    continue
                translated = json.loads(path.read_text(encoding="utf-8"))
                graph = translated.get("@graph")
                if not isinstance(graph, list):
                    if path.resolve() == expected:
                        raise RuntimeError(f"translated root CXF class has no graph: {path}")
                    # modelica-json emits enum/type documents alongside class
                    # documents. They intentionally have no instantiable graph.
                    continue
                roots = [
                    node
                    for node in graph
                    if isinstance(node, dict) and node.get("S231:containsBlock")
                ]
                if len(roots) != 1 or not isinstance(roots[0].get("@id"), str):
                    if path.resolve() == expected:
                        raise RuntimeError(
                            f"translated root CXF has no unique composite root: {path}"
                        )
                    # modelica-json also emits enum/type CXF documents. They are
                    # dependencies, but not instantiable composite classes.
                    continue
                class_id = roots[0]["@id"]
                if class_id in documents:
                    raise RuntimeError(f"duplicate translated CXF class: {class_id}")
                relative = path.resolve().relative_to(cxf_root).with_suffix(".mo")
                modelica_source = self.modelica_root / relative
                if modelica_source.is_file():
                    self._recover_root_parameter_metadata(
                        translated,
                        modelica_source.read_text(encoding="utf-8"),
                    )
                documents[class_id] = translated
                if path.resolve() == expected:
                    selected_id = class_id
            if selected_id is None:
                raise RuntimeError("translated root CXF was not retained in the class bundle")
            document = documents.pop(selected_id)
        return controller, document, documents

    @staticmethod
    def _ground_compile_time_enum_parameters(
        document: dict[str, Any],
    ) -> dict[str, Any]:
        """Ground enum-dependent scalar expressions before OCE ingestion.

        modelica-json emits the plant application enum as a symbolic root parameter and may leave
        numeric child parameters as Modelica ``if`` expressions. OCE does not currently
        ground that enum form. We resolve only finite scalar expressions, prove that the
        enum is no longer referenced, and then remove the compile-time-only enum node.
        Any residual dependency fails closed instead of changing runtime semantics.
        """

        graph = document.get("@graph")
        if not isinstance(graph, list):
            raise ValueError("CXF document is missing its JSON-LD graph")
        roots = [
            node for node in graph if isinstance(node, dict) and node.get("S231:containsBlock")
        ]
        if len(roots) != 1:
            raise ValueError(
                f"CXF must have exactly one root with containsBlock; found {len(roots)}"
            )
        root = roots[0]
        nodes = {
            node["@id"]: node
            for node in graph
            if isinstance(node, dict) and isinstance(node.get("@id"), str)
        }
        raw_parameters = root.get("S231:hasParameter")
        references = (
            raw_parameters
            if isinstance(raw_parameters, list)
            else [raw_parameters]
            if isinstance(raw_parameters, dict)
            else []
        )
        groundable_enum_types = {
            "Buildings.Templates.Plants.Controls.Types.Application",
            "Buildings.Templates.Plants.Controls.Types.Actuator",
            "Buildings.Templates.Plants.Controls.Types.EquipmentConnection",
        }
        enum_parameters: dict[str, dict[str, Any]] = {}
        values: dict[str, float | bool | str] = {}
        for reference in references:
            identifier = reference.get("@id") if isinstance(reference, dict) else None
            node = nodes.get(identifier) if isinstance(identifier, str) else None
            if node is None or "S231:value" not in node:
                continue
            label = node.get("S231:label")
            if not isinstance(label, str):
                label = str(identifier).rsplit(".", 1)[-1]
            value = node["S231:value"]
            if isinstance(value, (bool, int, float, str)):
                values[label] = value
            type_ref = node.get("S231:isOfDataType")
            data_type = type_ref.get("@id") if isinstance(type_ref, dict) else type_ref
            type_name = str(data_type).rsplit("#", 1)[-1].rsplit(":", 1)[-1]
            if type_name in groundable_enum_types:
                if (
                    not isinstance(value, str)
                    or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", value)
                    or not value.startswith(type_name + ".")
                ):
                    raise ValueError(
                        f"compile-time enum parameter {label} has an invalid member value"
                    )
                enum_parameters[str(identifier)] = {
                    "label": label,
                    "data_type": type_name,
                    "value": value,
                }

        if not enum_parameters:
            return {
                "applied": False,
                "resolved_parameter_values": [],
                "stripped_enum_parameters": [],
            }

        for _ in range(max(1, len(values))):
            changed = False
            for name, value in list(values.items()):
                resolved = resolve_parameter_expression(value, values)
                if resolved != value:
                    values[name] = resolved
                    changed = True
            if not changed:
                break

        resolved_values: list[dict[str, Any]] = []
        for node in graph:
            if not isinstance(node, dict) or "S231:value" not in node:
                continue
            previous = node["S231:value"]
            resolved = resolve_parameter_expression(previous, values)
            if resolved == previous or not isinstance(resolved, (bool, int, float)):
                continue
            if isinstance(resolved, float) and not math.isfinite(resolved):
                raise ValueError("grounded CXF parameter expression must be finite")
            node["S231:value"] = resolved
            resolved_values.append(
                {
                    "id": node.get("@id"),
                    "previous_value": previous,
                    "value": resolved,
                }
            )

        enum_ids = set(enum_parameters)
        for node in graph:
            if not isinstance(node, dict) or node.get("@id") in enum_ids:
                continue
            value = node.get("S231:value")
            if not isinstance(value, str):
                continue
            for enum in enum_parameters.values():
                if (
                    re.search(rf"\b{re.escape(enum['label'])}\b", value)
                    or enum["data_type"] in value
                ):
                    raise ValueError(
                        "compile-time enum grounding left an unresolved dependency in "
                        f"{node.get('@id')}: {enum['label']}"
                    )

        remaining_references = [
            reference
            for reference in references
            if not (
                isinstance(reference, dict)
                and isinstance(reference.get("@id"), str)
                and reference["@id"] in enum_ids
            )
        ]
        if remaining_references:
            root["S231:hasParameter"] = remaining_references
        else:
            root.pop("S231:hasParameter", None)
        graph[:] = [
            node for node in graph if not (isinstance(node, dict) and node.get("@id") in enum_ids)
        ]
        return {
            "applied": True,
            "resolved_parameter_values": resolved_values,
            "stripped_enum_parameters": [
                {"id": identifier, **enum_parameters[identifier]}
                for identifier in sorted(enum_parameters)
            ],
        }

    @staticmethod
    def _recover_root_parameter_metadata(
        document: dict[str, Any],
        source_text: str,
    ) -> None:
        """Recover parameter types that modelica-json omits for enum declarations.

        The recovery is deliberately limited to declarations in the exact source
        block and identifiers already listed by the translated root's
        ``hasParameter`` relation. It neither invents parameters nor evaluates
        defaults.
        """

        graph = document.get("@graph")
        if not isinstance(graph, list):
            return
        roots = [
            node for node in graph if isinstance(node, dict) and node.get("S231:containsBlock")
        ]
        if len(roots) != 1:
            return
        declarations = {
            match.group("name"): match.group("data_type")
            for match in _PARAMETER_DECLARATION.finditer(source_text)
        }

        def qualify_type(data_type: str) -> str:
            # G36 sources frequently spell the shared enum package as ``Types.*`` from
            # deep AHU/terminal namespaces. CXF omitted the declaration metadata that
            # would normally preserve Modelica's resolved absolute type. Recover that
            # exact library namespace here so validated job values and conditional guards
            # use the same enum identity.
            if data_type.startswith("Types.") and (
                "within Buildings.Controls.OBC.ASHRAE.G36" in source_text
            ):
                return f"Buildings.Controls.OBC.ASHRAE.G36.{data_type}"
            return data_type

        nodes = {
            node.get("@id"): node
            for node in graph
            if isinstance(node, dict) and isinstance(node.get("@id"), str)
        }
        raw = roots[0].get("S231:hasParameter")
        references = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
        primitive_types = {
            "Boolean": "S231:Boolean",
            "Integer": "S231:Integer",
            "Real": "S231:Real",
            "String": "S231:String",
        }
        for reference in references:
            identifier = reference.get("@id") if isinstance(reference, dict) else None
            if not isinstance(identifier, str):
                continue
            node = nodes.get(identifier)
            if node is None or node.get("@type") is not None:
                continue
            label = node.get("S231:label")
            name = label if isinstance(label, str) else identifier.rsplit(".", 1)[-1]
            declared_type = declarations.get(name)
            data_type = qualify_type(declared_type) if declared_type is not None else None
            if data_type is None:
                continue
            node["@type"] = "S231:Parameter"
            node["S231:isOfDataType"] = {"@id": primitive_types.get(data_type, f"ex:{data_type}")}
            node["_bactalk_recovered_parameter_type"] = data_type

    def _translate(
        self,
        controller_id: str,
        *,
        parameters: dict[str, Any] | None = None,
        execution_profile: ExecutionProfile = "modelica_exact",
    ) -> tuple[
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
    ]:
        controller, translated, class_documents = self._source_bundle(controller_id)
        parameterized, parameterization = self._apply_parameter_overrides(
            translated,
            parameters or {},
        )
        if parameterization["remaining_required_parameters"]:
            raise G36RequiredParametersError(controller_id, parameterization)
        document, normalization = normalize_connection_sets(parameterized)
        parameter_grounding = self._ground_compile_time_enum_parameters(document)
        normalization["compile_time_enum_grounding"] = parameter_grounding
        if class_documents:
            assembled, composite_assembly = assemble_cxf_composites(
                document,
                class_documents,
            )
            if not composite_assembly["complete"]:
                normalized_missing = {
                    item.removeprefix("ex:") for item in composite_assembly["missing_classes"]
                }
                if not normalized_missing <= _REVIEWED_COMPOSITE_CLASSES:
                    raise RuntimeError(
                        "CXF composite assembly is incomplete; missing classes: "
                        + ", ".join(composite_assembly["missing_classes"])
                    )
                normalization["composite_assembly"] = composite_assembly
            else:
                resolved = self.engine.inspect_document(assembled)
                try:
                    engine_flattening = self.engine.flatten_document(assembled)
                except RuntimeError as exc:
                    if "CXF flattening was incomplete" not in str(exc):
                        raise
                    engine_flattening = {
                        "schema": "bactalk.oce-resolved-topology/v1",
                        "engine": resolved["engine"],
                        "source_model_id": resolved["model_id"],
                        "source_block_count": resolved["block_count"],
                        "source_warning_count": resolved["warning_count"],
                        "export_deferred": True,
                    }
                else:
                    engine_flattening.pop("document")
                    engine_flattening["export_deferred"] = False
                document, topology_flattening = flatten_cxf_topology(
                    assembled,
                    resolved,
                    root_id=composite_assembly["root_id"],
                )
                engine_flattening["topology_projection"] = topology_flattening
                normalization["composite_assembly"] = composite_assembly
                normalization["composite_flattening"] = engine_flattening
        try:
            engine_report = self.engine.inspect_document(document)
        except RuntimeError as exc:
            engine_report = self._reviewed_composite_report(
                document,
                exc,
                execution_profile=execution_profile,
            )
        return controller, document, engine_report, normalization, parameterization

    def _reviewed_composite_report(
        self,
        document: dict[str, Any],
        exc: RuntimeError,
        *,
        execution_profile: ExecutionProfile = "modelica_exact",
    ) -> dict[str, Any]:
        message = str(exc)
        diagnostics = list(_OCE_DIAGNOSTIC.finditer(message))
        codes = {match.group("code") for match in diagnostics}
        missing_classes = set(_OCE_MISSING_CLASS.findall(message))
        if (
            not diagnostics
            or not missing_classes
            or not missing_classes <= _REVIEWED_COMPOSITE_CLASSES
            or not codes <= _REVIEWED_COMPOSITE_DIAGNOSTICS
        ):
            raise exc
        coverage = self.importer.inspect(
            document,
            execution_profile=execution_profile,
        )
        if not coverage["translatable"]:
            raise exc
        graph = self.importer.import_graph(
            document,
            execution_profile=execution_profile,
        )
        qualification_by_class = {
            "ASHRAE.G36.Generic.TrimAndRespond": (
                "The exact reviewed TrimAndRespond lowering is source-bound and checked "
                "against an independent Open Control Engine expanded-source trajectory."
            ),
            "Utilities.Initialization": (
                "The exact reviewed Initialization lowering is source-bound to the "
                "one-line Modelica initial() equation and checked with deterministic "
                "first-scan, pass-through, and restart vectors."
            ),
            "Utilities.TimerWithReset": (
                "The exact reviewed TimerWithReset lowering is source-bound to the pinned "
                "Modelica when-equation recurrence and checked with deterministic input, "
                "reset, falling-edge, and threshold vectors."
            ),
            "Buildings.Templates.Plants.Controls.Utilities.TimerWithReset": (
                "The exact reviewed TimerWithReset lowering is source-bound to the pinned "
                "Modelica when-equation recurrence and checked with deterministic input, "
                "reset, falling-edge, and threshold vectors."
            ),
            "Utilities.PlaceholderLogical": (
                "The reviewed logical placeholder lowering resolves its compile-time "
                "availability mode to an identity or constant from the pinned source."
            ),
            "Utilities.PlaceholderReal": (
                "The reviewed real placeholder lowering resolves its compile-time "
                "availability mode to an identity or constant from the pinned source."
            ),
            "Utilities.PlaceholderInteger": (
                "The reviewed integer placeholder lowering resolves its compile-time "
                "availability mode to an identity or constant from the pinned source."
            ),
            "Buildings.Templates.Plants.Controls.Utilities.PlaceholderLogical": (
                "The reviewed logical placeholder lowering resolves its compile-time "
                "availability mode to an identity or constant from the pinned source."
            ),
            "Buildings.Templates.Plants.Controls.Utilities.PlaceholderReal": (
                "The reviewed real placeholder lowering resolves its compile-time "
                "availability mode to an identity or constant from the pinned source."
            ),
            "Buildings.Templates.Plants.Controls.Utilities.PlaceholderInteger": (
                "The reviewed integer placeholder lowering resolves its compile-time "
                "availability mode to an identity or constant from the pinned source."
            ),
            "Buildings.Controls.OBC.Utilities.PIDWithEnable": (
                "The exact reviewed PIDWithEnable lowering expands the pinned composite "
                "into its input selector, PIDWithReset recurrence, neutral constant, and "
                "output selector without changing its enable-edge behavior."
            ),
            "Utilities.PIDWithEnable": (
                "The exact reviewed PIDWithEnable lowering expands the pinned composite "
                "into its input selector, PIDWithReset recurrence, neutral constant, and "
                "output selector without changing its enable-edge behavior."
            ),
        }
        qualification = " ".join(
            qualification_by_class[class_name] for class_name in sorted(missing_classes)
        )
        return {
            "engine": "bactalk-reviewed-composite-lowering",
            "validation_scope": "typed-ir-structure-and-source-bound-behavior",
            "oce_validation_succeeded": False,
            "oce_diagnostic_codes": sorted(codes),
            "oce_missing_classes": sorted(missing_classes),
            "block_count": coverage["component_count"],
            "typed_ir_block_count": len(graph.blocks),
            "stateful_blocks": sum(block.kind in _STATEFUL_KINDS for block in graph.blocks),
            "point_count": coverage["boundary_inputs"] + coverage["boundary_outputs"],
            "warning_count": sum(match.group("severity") == "warning" for match in diagnostics),
            "qualification": (
                "Open Control Engine cannot ingest the authored composite class. "
                f"{qualification} This is not OCE validation of the parent CXF."
            ),
        }

    @staticmethod
    def _simulate_typed_graph(
        graph: ControlGraph,
        *,
        interface: dict[str, Any],
        samples: list[dict[str, Any]],
        collect: list[str],
    ) -> dict[str, Any]:
        interpreter = GraphInterpreter(graph)
        input_labels = {port["label"] for port in interface["inputs"]}
        output_ids = {port["label"]: port["id"] for port in interface["outputs"]}
        output_types = {port["label"]: port.get("type") for port in interface["outputs"]}
        previous_time: float | None = None
        rows = []
        for index, sample in enumerate(samples):
            timestamp = sample.get("time")
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
                raise ValueError(f"sample {index} time must be numeric")
            timestamp = float(timestamp)
            if previous_time is not None and timestamp < previous_time:
                raise ValueError("sample times must be non-decreasing")
            step = 0.0 if previous_time is None else timestamp - previous_time
            raw_inputs = sample["inputs"]
            values = interpreter.evaluate(
                {name: raw_inputs[name] for name in input_labels if name in raw_inputs},
                step_seconds=step,
            )
            outputs = {}
            for name in collect:
                value = values[name]
                value_type = output_types[name]
                if isinstance(value_type, str) and "IntegerOutput" in value_type:
                    if isinstance(value, bool) or not float(value).is_integer():
                        raise ValueError(
                            f"typed IR output {name} violated its IntegerOutput contract"
                        )
                    value = int(value)
                outputs[output_ids[name]] = {
                    "type": (
                        "boolean"
                        if isinstance(value, bool)
                        else "integer"
                        if isinstance(value_type, str) and "IntegerOutput" in value_type
                        else "real"
                    ),
                    "value": value,
                }
            rows.append({"time": timestamp, "outputs": outputs})
            previous_time = timestamp
        return {
            "schema": "bactalk.typed-ir-trace/v1",
            "engine": "bactalk-typed-ir",
            "sample_count": len(rows),
            "collect": [output_ids[name] for name in collect],
            "trace": rows,
        }

    @staticmethod
    def _interface(document: dict[str, Any]) -> dict[str, Any]:
        graph = document.get("@graph")
        context = document.get("@context")
        if not isinstance(graph, list) or not isinstance(context, dict):
            raise ValueError("translated G36 CXF is missing its JSON-LD graph/context")
        prefixes = {
            key: value
            for key, value in context.items()
            if isinstance(key, str) and isinstance(value, str)
        }

        def expand(identifier: str) -> str:
            prefix, separator, remainder = identifier.partition(":")
            if separator and prefix in prefixes:
                return f"{prefixes[prefix]}{remainder}"
            return identifier

        roots = [
            node
            for node in graph
            if isinstance(node, dict)
            and node.get("@type") == "S231:Block"
            and (node.get("S231:hasInput") or node.get("S231:hasOutput"))
        ]
        if len(roots) != 1:
            raise ValueError(
                f"translated G36 CXF has {len(roots)} public controller roots; expected 1"
            )
        root = roots[0]
        nodes = {
            expand(node["@id"]): node
            for node in graph
            if isinstance(node, dict) and isinstance(node.get("@id"), str)
        }

        def ports(field: str) -> list[dict[str, Any]]:
            references = root.get(field, [])
            if isinstance(references, dict):
                references = [references]
            result: list[dict[str, Any]] = []
            for reference in references:
                if not isinstance(reference, dict) or not isinstance(reference.get("@id"), str):
                    raise ValueError(f"invalid {field} reference in translated G36 CXF")
                identifier = expand(reference["@id"])
                node = nodes.get(identifier, {})
                label = node.get("S231:label")
                if not isinstance(label, str):
                    label = identifier.rsplit(".", 1)[-1]
                result.append(
                    {
                        "label": label,
                        "id": identifier,
                        "type": node.get("@type"),
                        "description": node.get("S231:description"),
                    }
                )
            return sorted(result, key=lambda item: item["label"])

        return {
            "controller_id": expand(str(root["@id"])),
            "inputs": ports("S231:hasInput"),
            "outputs": ports("S231:hasOutput"),
        }

    def _controllers(self) -> dict[str, dict[str, Any]]:
        if not self.g36_root.is_dir():
            raise FileNotFoundError("LBNL G36 Modelica source library is not installed")
        controllers: dict[str, dict[str, Any]] = {}
        for path in sorted(self.g36_root.rglob("*.mo")):
            if path.name == "package.mo":
                continue
            source = path.read_text(encoding="utf-8")
            declaration = _DECLARATION.search(source)
            if declaration is None:
                continue
            relative = path.relative_to(self.g36_root)
            parts = relative.with_suffix("").parts
            controller_id = ".".join(parts)
            record = {
                "id": controller_id,
                "name": declaration.group("name"),
                "declaration": declaration.group("kind"),
                "family": parts[0],
                "relative_path": relative.as_posix(),
                "validation_fixture": "Validation" in parts,
                "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                "source_bytes": len(source.encode("utf-8")),
            }
            if controller_id in controllers:
                raise RuntimeError(f"duplicate G36 controller id: {controller_id}")
            controllers[controller_id] = record
        return controllers
