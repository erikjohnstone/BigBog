from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bactalk.api import create_app
from bactalk.compiler import NiagaraCompiler
from bactalk.domain import ControlGraph
from bactalk.integrations.g36_library import G36RequiredParametersError
from bactalk.integrations.plant_controls_library import PlantControlsLibrary

CONTROLLER = "Utilities.HoldReal"
PLANT_RESET = "Setpoints.PlantReset"
PLANT_RESET_PARAMETERS = {
    "nSenDpRem": 2,
    "dpSet_max": [100000.0, 120000.0],
    "TSup_nominal": 279.15,
    "TSupSetLim": 285.15,
    "dtDel": 0.001,
    "dtRes": 10.0,
    "dtHol": 25.0,
}
MINIMUM_FLOW_PARAMETERS = {
    "nEqu": 3,
    "V_flow_nominal": [0.1, 0.2, 0.3],
    "V_flow_min": [0.02, 0.06, 0.09],
}
DUAL_MINIMUM_FLOW_PARAMETERS = {
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
}
SAMPLES = [
    {"time": 0, "inputs": {"u": 10.0, "u1": False}},
    {"time": 1, "inputs": {"u": 20.0, "u1": True}},
    {"time": 2, "inputs": {"u": 30.0, "u1": False}},
    {"time": 3, "inputs": {"u": 40.0, "u1": False}},
    {"time": 4, "inputs": {"u": 50.0, "u1": False}},
    {"time": 5, "inputs": {"u": 60.0, "u1": False}},
]
DISABLE_DEDICATED = "Pumps.Primary.DisableDedicated"
FAILSAFE_CONDITION = "StagingRotation.FailsafeCondition"
HRC_ENABLE_PARAMETERS = {
    "TChiWatSup_min": 280.0,
    "THeaWatSup_max": 330.0,
    "capCoo_min": 10.0,
    "capHea_min": 10.0,
    "dtRun": 2.0,
    "dtLoa": 2.0,
    "dtTem1": 2.0,
    "dtTem2": 1.0,
}
HRC_CONTROLLER_PARAMETERS = {
    "have_reqFlo": False,
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
}
AIR_TO_WATER_PARAMETERS = {
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


def _values(execution: dict) -> list[float]:
    output_id = execution["interface"]["outputs"][0]["id"]
    return [row["outputs"][output_id]["value"] for row in execution["trace"]["trace"]]


def test_catalog_separates_source_presence_from_product_support() -> None:
    catalog = PlantControlsLibrary().catalog()

    assert catalog["schema"] == "bactalk.plant-controls-library/v1"
    assert catalog["production_control_model_count"] == 38
    assert catalog["proven_controller_count"] == 38
    controller = next(item for item in catalog["controllers"] if item["id"] == CONTROLLER)
    assert controller["product_status"] == "exact_ir_generated_program_source"
    plant_reset = next(
        item for item in catalog["controllers"] if item["id"] == PLANT_RESET
    )
    assert plant_reset["product_status"] == "exact_ir_generated_program_source"
    air_to_water = next(
        item for item in catalog["controllers"] if item["id"] == "HeatPumps.AirToWater"
    )
    assert air_to_water["product_status"] == "exact_ir_generated_program_source"
    assert catalog["licensed_niagara_runtime_qualified"] is False


def test_hold_real_translates_executes_and_targets_niagara_source() -> None:
    library = PlantControlsLibrary()
    translation = library.translate(CONTROLLER)

    assert translation["schema"] == "bactalk.plant-controls-translation/v1"
    assert translation["lowering"]["translatable"] is True
    assert translation["engine_report"]["engine"] == "open-control-engine"
    assert set(translation["lowering"]["niagara_unsupported_classes"]) == {
        "Buildings.Controls.OBC.CDL.Discrete.TriggeredSampler",
        "Buildings.Controls.OBC.CDL.Logical.TrueFalseHold",
    }
    assert library.assess_niagara_source_target(translation) == {
        "complete": True,
        "delivery_mode": "generated_program_source",
        "generated_program_count": 2,
        "blocker": None,
        "runtime_qualified": False,
        "licensed_workbench_compile_required": True,
    }

    execution = library.execute(CONTROLLER, parameters={"dtHol": 3.0}, samples=SAMPLES)
    assert execution["schema"] == "bactalk.plant-controls-execution/v1"
    assert execution["runtime"] == "Open Control Engine"
    assert _values(execution) == [10.0, 20.0, 20.0, 20.0, 50.0, 60.0]


def test_hold_real_program_package_preserves_graph_and_wiring() -> None:
    content, filename = PlantControlsLibrary().niagara_program_package(
        CONTROLLER,
        parameters={"dtHol": 3.0},
    )

    assert filename == "Utilities.HoldReal-niagara-programs.zip"
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        graph = json.loads(archive.read("control-graph.json"))
        wiring = json.loads(archive.read("wiring-plan.json"))
    assert len(manifest["programs"]) == 2
    assert len(graph["blocks"]) == 6
    assert len(wiring["links"]) == len(graph["links"])
    assert {
        item["behavior_kind"]
        for item in wiring["components"]
        if item["behavior_kind"]
        not in {"numeric_input", "boolean_input", "numeric_output"}
    } == {
        "numeric_latch",
        "boolean_true_false_hold",
        "numeric_switch",
    }


def test_configured_controller_emits_exact_contractor_job_template() -> None:
    template = PlantControlsLibrary().job_template(
        CONTROLLER,
        parameters={"dtHol": 3.0},
    )

    assert template["schema"] == "bactalk.plant-controller-job-template/v1"
    assert template["sequence"] == {
        "family": "LBNL_PLANT_CONTROLLER",
        "version": "Pinned LBNL Modelica Buildings source",
        "library": "plant_controls",
        "controller_id": CONTROLLER,
        "execution_profile": "modelica_exact",
        "parameters": {"dtHol": 3.0},
    }
    assert template["target_assessment"]["delivery_mode"] == "generated_program_source"
    assert [point["name"] for point in template["points"]] == ["u", "u1", "y"]
    assert template["acceptance_output_targets"] == [
        {"target": "y", "data_type": "numeric", "required": True}
    ]
    assert template["points_csv"].splitlines()[0] == (
        "name,label,data_type,role,default,required"
    )


def test_parameterized_plant_reset_lowers_hold_logic_and_array_outputs() -> None:
    library = PlantControlsLibrary()
    translation = library.translate(PLANT_RESET, parameters=PLANT_RESET_PARAMETERS)

    assert translation["lowering"]["translatable"] is True
    assert translation["product_status"] == "exact_ir_generated_program_source"
    assert translation["engine_report"]["engine"] == "bactalk-reviewed-composite-lowering"
    graph = translation["typed_ir"]
    reset = next(block for block in graph["blocks"] if block["id"] == "triRes")
    assert reset["kind"] == "trim_and_respond_hold"
    assert reset["config"]["hold_duration_seconds"] == 25.0
    assert {port["label"] for port in translation["interface"]["outputs"]} == {
        "TSupSet",
        "dpSet__1",
        "dpSet__2",
    }
    assert library.assess_niagara_source_target(translation)[
        "generated_program_count"
    ] == 1

    samples = [
        {
            "time": timestamp,
            "inputs": {
                "nReqRes": 0,
                "u1Ena": True,
                "u1StaPro": 25 <= timestamp < 35,
            },
        }
        for timestamp in range(0, 56, 5)
    ]
    execution = library.execute(
        PLANT_RESET,
        parameters=PLANT_RESET_PARAMETERS,
        samples=samples,
        collect=["TSupSet"],
    )
    output_id = execution["interface"]["outputs"][0]["id"]
    assert [
        row["outputs"][output_id]["value"] for row in execution["trace"]["trace"]
    ] == [
        279.15,
        279.15,
        279.15,
        279.39,
        279.39,
        279.39,
        279.39,
        279.39,
        279.39,
        279.39,
        279.63,
        279.63,
    ]


def test_connector_sized_minimum_flow_executes_unequal_equipment_case() -> None:
    library = PlantControlsLibrary()
    translation = library.translate(
        "MinimumFlow.Setpoint",
        parameters=MINIMUM_FLOW_PARAMETERS,
    )

    assert translation["product_status"] == "exact_ir_stock_niagara"
    assert translation["lowering"]["component_count"] == 23
    assert translation["lowering"]["niagara_translatable"] is True
    assert library.assess_niagara_source_target(translation) == {
        "complete": True,
        "delivery_mode": "qualified_stock_components",
        "generated_program_count": 0,
        "blocker": None,
    }
    execution = library.execute(
        "MinimumFlow.Setpoint",
        parameters=MINIMUM_FLOW_PARAMETERS,
        samples=[
            {
                "time": 0,
                "inputs": {"u1__1": True, "u1__2": False, "u1__3": True},
            }
        ],
    )
    output_id = execution["interface"]["outputs"][0]["id"]
    assert execution["trace"]["trace"][0]["outputs"][output_id]["value"] == 0.12


@pytest.mark.parametrize(
    ("have_inlet", "have_outlet", "active_input"),
    [
        (False, False, "u1PumPri_actual__1"),
        (True, False, "u1ValInlIso__1"),
        (False, True, "u1ValOutIso__1"),
        (True, True, "u1ValOutIso__1"),
    ],
)
def test_full_minimum_flow_controller_executes_every_enable_topology(
    have_inlet: bool,
    have_outlet: bool,
    active_input: str,
) -> None:
    library = PlantControlsLibrary()
    parameters = {
        **MINIMUM_FLOW_PARAMETERS,
        "nEna": 2,
        "have_valInlIso": have_inlet,
        "have_valOutIso": have_outlet,
        "k": 1.0,
        "Ti": 1.0,
    }
    translation = library.translate("MinimumFlow.Controller", parameters=parameters)
    input_labels = {port["label"] for port in translation["interface"]["inputs"]}
    expected_enable_prefixes = []
    if have_inlet:
        expected_enable_prefixes.append("u1ValInlIso")
    if have_outlet:
        expected_enable_prefixes.append("u1ValOutIso")
    if not expected_enable_prefixes:
        expected_enable_prefixes.append("u1PumPri_actual")
    assert translation["product_status"] == "exact_ir_generated_program_source"
    assert translation["lowering"]["translatable"] is True
    assert translation["lowering"]["niagara_unsupported_classes"] == [
        "Buildings.Controls.OBC.CDL.Reals.PIDWithReset"
    ]
    actual_enable_inputs = {
        name
        for name in input_labels
        if name.startswith("u1Val") or name.startswith("u1Pum")
    }
    assert actual_enable_inputs == {
        f"{prefix}__{index}"
        for prefix in expected_enable_prefixes
        for index in (1, 2)
    }

    base_inputs = {
        "VPri_flow": 0.3,
        "u1Equ__1": True,
        "u1Equ__2": False,
        "u1Equ__3": True,
        **{
            name: False
            for name in input_labels
            if name.startswith("u1Val") or name.startswith("u1Pum")
        },
    }
    samples = []
    for timestamp in range(4):
        inputs = dict(base_inputs)
        if timestamp > 0:
            inputs[active_input] = True
        samples.append({"time": timestamp, "inputs": inputs})
    execution = library.execute(
        "MinimumFlow.Controller",
        parameters=parameters,
        samples=samples,
    )
    outputs = {port["label"]: port["id"] for port in execution["interface"]["outputs"]}
    assert [
        row["outputs"][outputs["VPriSet_flow"]]["value"]
        for row in execution["trace"]["trace"]
    ] == [0.12, 0.12, 0.12, 0.12]
    assert [
        row["outputs"][outputs["y"]]["value"]
        for row in execution["trace"]["trace"]
    ] == pytest.approx([1.0, 1.0, 1.0, 0.82])
    assert library.assess_niagara_source_target(translation)[
        "generated_program_count"
    ] == 1


def test_full_minimum_flow_controller_rejects_unsafe_dimensions() -> None:
    library = PlantControlsLibrary()
    parameters = {
        **MINIMUM_FLOW_PARAMETERS,
        "nEna": 2,
        "have_valInlIso": False,
        "have_valOutIso": False,
    }
    with pytest.raises(ValueError, match="length must equal nEqu"):
        library.translate(
            "MinimumFlow.Controller",
            parameters={**parameters, "V_flow_min": [0.02, 0.06]},
        )
    with pytest.raises(ValueError, match="must not exceed nominal"):
        library.translate(
            "MinimumFlow.Controller",
            parameters={**parameters, "V_flow_min": [0.2, 0.06, 0.09]},
        )


@pytest.mark.parametrize(
    ("parameters", "expected_inputs", "program_count"),
    [
        (
            {
                "have_heaWat": True,
                "have_chiWat": False,
                "have_pumChiWatPri": False,
                "have_valInlIso": False,
                "have_valOutIso": False,
                "nEqu": 3,
                "nEnaHeaWat": 2,
                "VHeaWat_flow_nominal": [0.1, 0.2, 0.3],
                "VHeaWat_flow_min": [0.02, 0.06, 0.09],
            },
            {"VHeaWatPri_flow", "u1PumHeaWatPri_actual__1"},
            1,
        ),
        (
            {
                "have_heaWat": False,
                "have_chiWat": True,
                "have_pumChiWatPri": True,
                "have_valInlIso": False,
                "have_valOutIso": False,
                "nEqu": 3,
                "nEnaChiWat": 2,
                "VChiWat_flow_nominal": [0.1, 0.2, 0.3],
                "VChiWat_flow_min": [0.01, 0.04, 0.06],
            },
            {"VChiWatPri_flow", "u1PumChiWatPri_actual__1"},
            1,
        ),
        (
            {
                **DUAL_MINIMUM_FLOW_PARAMETERS,
                "have_pumChiWatPri": True,
                "have_valInlIso": True,
                "have_valOutIso": True,
                "nEnaHeaWat": 2,
                "nEnaChiWat": 2,
            },
            {
                "VHeaWatPri_flow",
                "VChiWatPri_flow",
                "u1HeaEqu__1",
                "u1ValHeaWatInlIso__1",
                "u1ValHeaWatOutIso__1",
                "u1ValChiWatInlIso__1",
                "u1ValChiWatOutIso__1",
            },
            2,
        ),
    ],
)
def test_dual_mode_minimum_flow_topology_matrix_compiles_complete_packages(
    parameters: dict,
    expected_inputs: set[str],
    program_count: int,
) -> None:
    library = PlantControlsLibrary()
    translation = library.translate(
        "MinimumFlow.ControllerDualMode",
        parameters=parameters,
    )

    input_labels = {port["label"] for port in translation["interface"]["inputs"]}
    assert expected_inputs <= input_labels
    assert translation["product_status"] == "exact_ir_generated_program_source"
    assert translation["lowering"]["translatable"] is True
    assert translation["lowering"]["niagara_unsupported_classes"] == [
        "Buildings.Controls.OBC.CDL.Reals.PIDWithReset"
    ]
    target = library.assess_niagara_source_target(translation)
    assert target["complete"] is True
    assert target["generated_program_count"] == program_count


def test_dual_mode_minimum_flow_common_pumps_are_filtered_by_equipment_mode() -> None:
    library = PlantControlsLibrary()
    pump_states = [
        (False, False, False),
        (True, False, False),
        (True, False, False),
        (True, False, False),
        (False, True, False),
        (False, True, False),
        (False, True, False),
    ]
    execution = library.execute(
        "MinimumFlow.ControllerDualMode",
        parameters=DUAL_MINIMUM_FLOW_PARAMETERS,
        samples=[
            {
                "time": timestamp,
                "inputs": {
                    "VHeaWatPri_flow": 0.3,
                    "VChiWatPri_flow": 0.1,
                    "u1Equ__1": True,
                    "u1Equ__2": True,
                    "u1Equ__3": True,
                    "u1HeaEqu__1": True,
                    "u1HeaEqu__2": False,
                    "u1HeaEqu__3": True,
                    **{
                        f"u1PumHeaWatPri_actual__{index}": value
                        for index, value in enumerate(states, start=1)
                    },
                },
            }
            for timestamp, states in enumerate(pump_states)
        ],
    )
    outputs = {port["label"]: port["id"] for port in execution["interface"]["outputs"]}
    trace = execution["trace"]["trace"]
    assert [
        row["outputs"][outputs["VHeaWatPriSet_flow"]]["value"] for row in trace
    ] == pytest.approx([0.12] * len(pump_states))
    assert [
        row["outputs"][outputs["VChiWatPriSet_flow"]]["value"] for row in trace
    ] == pytest.approx([0.04] * len(pump_states))
    assert [
        row["outputs"][outputs["yValHeaWatMinByp"]]["value"] for row in trace
    ] == pytest.approx([1.0, 1.0, 1.0, 0.82, 1.0, 1.0, 1.0])
    assert [
        row["outputs"][outputs["yValChiWatMinByp"]]["value"] for row in trace
    ] == pytest.approx([1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.94])

    package, _ = library.niagara_program_package(
        "MinimumFlow.ControllerDualMode",
        parameters=DUAL_MINIMUM_FLOW_PARAMETERS,
    )
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        wiring = json.loads(archive.read("wiring-plan.json"))
    assert len(manifest["programs"]) == 2
    assert len(wiring["links"]) > 80


def test_dual_mode_minimum_flow_rejects_impossible_or_mismatched_plants() -> None:
    library = PlantControlsLibrary()
    with pytest.raises(ValueError, match="requires heating, chilled water, or both"):
        library.translate(
            "MinimumFlow.ControllerDualMode",
            parameters={
                "have_heaWat": False,
                "have_chiWat": False,
                "have_valInlIso": False,
                "have_valOutIso": False,
                "nEqu": 3,
            },
        )
    with pytest.raises(ValueError, match="must equal nEqu=3"):
        library.translate(
            "MinimumFlow.ControllerDualMode",
            parameters={**DUAL_MINIMUM_FLOW_PARAMETERS, "nEnaChiWat": 2},
        )


@pytest.mark.parametrize(
    ("have_heating", "have_cooling", "expected_inputs", "expected_outputs"),
    [
        (True, False, {"u1Ava", "u1EnaHea"}, {"y1Hea"}),
        (False, True, {"u1Ava", "u1EnaCoo"}, {"y1Coo"}),
        (
            True,
            True,
            {"u1Ava", "u1EnaHea", "u1EnaCoo"},
            {"y1Hea", "y1Coo"},
        ),
    ],
)
def test_equipment_availability_topology_matrix_has_complete_program_source(
    have_heating: bool,
    have_cooling: bool,
    expected_inputs: set[str],
    expected_outputs: set[str],
) -> None:
    library = PlantControlsLibrary()
    translation = library.translate(
        "StagingRotation.EquipmentAvailability",
        parameters={
            "have_heaWat": have_heating,
            "have_chiWat": have_cooling,
            "dtOff": 3.0,
        },
    )

    assert {port["label"] for port in translation["interface"]["inputs"]} == (
        expected_inputs
    )
    assert {port["label"] for port in translation["interface"]["outputs"]} == (
        expected_outputs
    )
    assert translation["product_status"] == "exact_ir_generated_program_source"
    state = next(
        block
        for block in translation["typed_ir"]["blocks"]
        if block["kind"] == "plant_equipment_availability"
    )
    assert state["config"]["off_time_seconds"] == 3.0
    target = library.assess_niagara_source_target(translation)
    assert target["complete"] is True
    assert target["generated_program_count"] == 1


def test_equipment_availability_enforces_mode_exclusion_off_time_and_recovery() -> None:
    library = PlantControlsLibrary()
    inputs = [
        (False, False, True),
        (True, False, True),
        (True, False, True),
        (False, False, True),
        (False, True, True),
        (False, True, True),
        (False, True, True),
        (False, True, True),
        (False, True, False),
        (False, True, True),
    ]
    parameters = {"have_heaWat": True, "have_chiWat": True, "dtOff": 3.0}
    execution = library.execute(
        "StagingRotation.EquipmentAvailability",
        parameters=parameters,
        samples=[
            {
                "time": timestamp,
                "inputs": {
                    "u1EnaHea": heating,
                    "u1EnaCoo": cooling,
                    "u1Ava": available,
                },
            }
            for timestamp, (heating, cooling, available) in enumerate(inputs)
        ],
    )
    outputs = {port["label"]: port["id"] for port in execution["interface"]["outputs"]}
    trace = execution["trace"]["trace"]
    assert [row["outputs"][outputs["y1Hea"]]["value"] for row in trace] == [
        True,
        True,
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
    ]
    assert [row["outputs"][outputs["y1Coo"]]["value"] for row in trace] == [
        True,
        False,
        False,
        False,
        False,
        False,
        True,
        True,
        False,
        True,
    ]

    package, _ = library.niagara_program_package(
        "StagingRotation.EquipmentAvailability",
        parameters=parameters,
    )
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        slots = json.loads(
            archive.read("programs/availability_state/slots.json")
        )
    assert manifest["programs"][0]["behavior_kind"] == (
        "plant_equipment_availability"
    )
    assert {slot["name"] for slot in slots["slots"]} == {
        "enableHeating",
        "enableCooling",
        "available",
        "heatingAvailable",
        "coolingAvailable",
    }


def test_equipment_availability_rejects_no_loop_and_negative_off_time() -> None:
    library = PlantControlsLibrary()
    with pytest.raises(ValueError, match="requires at least one loop"):
        library.translate(
            "StagingRotation.EquipmentAvailability",
            parameters={"have_heaWat": False, "have_chiWat": False},
        )
    with pytest.raises(ValueError, match="finite and non-negative"):
        library.translate(
            "StagingRotation.EquipmentAvailability",
            parameters={"have_heaWat": True, "have_chiWat": False, "dtOff": -1},
        )


@pytest.mark.parametrize(
    ("application", "external_schedule", "expected_inputs"),
    [
        ("Heating", False, {"TOut", "nReqPla"}),
        ("Heating", True, {"TOut", "nReqPla", "u1Sch"}),
        ("Cooling", False, {"TOut", "nReqPla"}),
        ("Cooling", True, {"TOut", "nReqPla", "u1Sch"}),
    ],
)
def test_plant_enable_topologies_have_typed_inputs_and_complete_source(
    application: str,
    external_schedule: bool,
    expected_inputs: set[str],
) -> None:
    library = PlantControlsLibrary()
    translation = library.translate(
        "Enabling.Enable",
        parameters={
            "typ": (
                "Buildings.Templates.Plants.Controls.Types.Application."
                f"{application}"
            ),
            "have_inpSch": external_schedule,
            "TOutLck": 290.0,
            "dTOutLck": 1.0,
            "nReqIgn": 0,
            "dtRun": 2.0,
            "dtReq": 2.0,
        },
    )

    inputs = {port["label"]: port["type"] for port in translation["interface"]["inputs"]}
    assert set(inputs) == expected_inputs
    assert inputs["nReqPla"] == "S231:IntegerInput"
    assert inputs["TOut"] == "S231:RealInput"
    assert translation["product_status"] == "exact_ir_generated_program_source"
    assert library.assess_niagara_source_target(translation)["complete"] is True


def test_plant_enable_enforces_requests_dwell_low_request_and_lockout() -> None:
    library = PlantControlsLibrary()
    parameters = {
        "typ": "Heating",
        "have_inpSch": True,
        "TOutLck": 290.0,
        "dTOutLck": 1.0,
        "nReqIgn": 0,
        "dtRun": 2.0,
        "dtReq": 2.0,
    }
    regimes = [
        (True, 1, 285.0),
        (True, 1, 285.0),
        (True, 1, 285.0),
        (True, 0, 285.0),
        (True, 0, 285.0),
        (True, 0, 285.0),
        (True, 1, 285.0),
        (True, 1, 285.0),
        (True, 1, 285.0),
        (True, 1, 292.0),
        (True, 1, 292.0),
        (True, 1, 292.0),
    ]
    execution = library.execute(
        "Enabling.Enable",
        parameters=parameters,
        samples=[
            {
                "time": timestamp,
                "inputs": {"u1Sch": schedule, "nReqPla": requests, "TOut": oat},
            }
            for timestamp, (schedule, requests, oat) in enumerate(regimes)
        ],
    )
    output_id = execution["interface"]["outputs"][0]["id"]
    assert [row["outputs"][output_id]["value"] for row in execution["trace"]["trace"]] == [
        False,
        False,
        True,
        True,
        True,
        False,
        False,
        True,
        True,
        False,
        False,
        False,
    ]


def test_plant_enable_internal_daily_schedule_is_executable_and_packaged() -> None:
    library = PlantControlsLibrary()
    parameters = {
        "typ": "Cooling",
        "have_inpSch": False,
        "sch": [[0, 0], [2, 1], [5, 0], [10, 0]],
        "TOutLck": 290.0,
        "dTOutLck": 1.0,
        "nReqIgn": 0,
        "dtRun": 0.0,
        "dtReq": 0.0,
    }
    execution = library.execute(
        "Enabling.Enable",
        parameters=parameters,
        samples=[
            {"time": timestamp, "inputs": {"nReqPla": 1, "TOut": 295.0}}
            for timestamp in range(7)
        ],
    )
    output_id = execution["interface"]["outputs"][0]["id"]
    assert [row["outputs"][output_id]["value"] for row in execution["trace"]["trace"]] == [
        False,
        False,
        True,
        True,
        True,
        False,
        False,
    ]
    package, _ = library.niagara_program_package(
        "Enabling.Enable",
        parameters=parameters,
    )
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        slots = json.loads(archive.read("programs/plant_enable/slots.json"))
    assert manifest["programs"][0]["behavior_kind"] == "plant_enable"
    assert [slot["name"] for slot in slots["slots"]] == [
        "scheduleEnabled",
        "requestCount",
        "outdoorTemperature",
        "out",
    ]


def test_plant_enable_rejects_invalid_application_and_schedule() -> None:
    library = PlantControlsLibrary()
    with pytest.raises(ValueError, match="Heating or Cooling"):
        library.translate("Enabling.Enable", parameters={"typ": "Ventilation"})
    with pytest.raises(ValueError, match="values must be 0 or 1"):
        library.translate(
            "Enabling.Enable",
            parameters={"typ": "Heating", "sch": [[0, 0], [86400, 0.5]]},
        )


def test_hrc_enable_qualifies_load_then_pulses_mode_before_delayed_enable() -> None:
    library = PlantControlsLibrary()
    samples = [
        {
            "time": timestamp,
            "inputs": {
                "u1Coo": True,
                "u1Hea": True,
                "u1Hrc_actual": False,
                "QChiWatReq_flow": 20.0,
                "QHeaWatReq_flow": 20.0,
                "TChiWatHrcLvg": 285.0,
                "THeaWatHrcLvg": 320.0,
                "u1CooHrc": False,
            },
        }
        for timestamp in range(12)
    ]
    execution = library.execute(
        "HeatRecoveryChillers.Enable",
        parameters=HRC_ENABLE_PARAMETERS,
        samples=samples,
    )
    outputs = {port["label"]: port["id"] for port in execution["interface"]["outputs"]}
    trace = execution["trace"]["trace"]
    assert [row["outputs"][outputs["y1SetMod"]]["value"] for row in trace] == [
        False,
        False,
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
    ]
    assert [row["outputs"][outputs["y1"]]["value"] for row in trace] == [
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        True,
        True,
        True,
        True,
        True,
    ]
    translation = library.translate(
        "HeatRecoveryChillers.Enable",
        parameters=HRC_ENABLE_PARAMETERS,
    )
    assert translation["product_status"] == "exact_ir_generated_program_source"
    target = library.assess_niagara_source_target(translation)
    assert target["complete"] is True
    assert target["generated_program_count"] == 1
    package, _ = library.niagara_program_package(
        "HeatRecoveryChillers.Enable",
        parameters=HRC_ENABLE_PARAMETERS,
    )
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["programs"][0]["behavior_kind"] == "plant_hrc_enable"
    assert "QChiWatReq_flow" in manifest["programs"][0]["source_contract"][
        "source_connection_note"
    ]


@pytest.mark.parametrize(
    ("cooling_mode", "chilled_temperature", "heating_temperature", "trip_time"),
    [
        (False, 280.5, 320.0, 10),
        (False, 279.9, 320.0, 9),
        (True, 285.0, 329.0, 10),
        (True, 285.0, 330.1, 9),
    ],
)
def test_hrc_enable_applies_mode_specific_timed_temperature_shutdowns(
    cooling_mode: bool,
    chilled_temperature: float,
    heating_temperature: float,
    trip_time: int,
) -> None:
    samples = []
    for timestamp in range(12):
        samples.append(
            {
                "time": timestamp,
                "inputs": {
                    "u1Coo": True,
                    "u1Hea": True,
                    "u1Hrc_actual": True,
                    "QChiWatReq_flow": 20.0,
                    "QHeaWatReq_flow": 20.0,
                    "TChiWatHrcLvg": (
                        chilled_temperature if timestamp >= 8 else 285.0
                    ),
                    "THeaWatHrcLvg": (
                        heating_temperature if timestamp >= 8 else 320.0
                    ),
                    "u1CooHrc": cooling_mode,
                },
            }
        )
    execution = PlantControlsLibrary().execute(
        "HeatRecoveryChillers.Enable",
        parameters=HRC_ENABLE_PARAMETERS,
        samples=samples,
    )
    output = next(
        port["id"] for port in execution["interface"]["outputs"] if port["label"] == "y1"
    )
    values = [row["outputs"][output]["value"] for row in execution["trace"]["trace"]]
    assert values[7] is True
    assert values[trip_time - 1] is True
    assert values[trip_time] is False


def test_hrc_enable_preserves_exact_low_load_source_connection_and_boundaries() -> None:
    parameters = {**HRC_ENABLE_PARAMETERS, "capCoo_min": 10_000.0, "capHea_min": 10_000.0}
    loads_and_status = [
        *((20_000.0, False) for _ in range(8)),
        (9_999.5, True),
        (10_001.0, False),
        (20_000.0, True),
        (9_999.5, False),
    ]
    samples = [
        {
            "time": timestamp,
            "inputs": {
                "u1Coo": True,
                "u1Hea": True,
                "u1Hrc_actual": status,
                "QChiWatReq_flow": load,
                # The pinned low-load link ignores this input; keep it high to prove it.
                "QHeaWatReq_flow": 20_000.0,
                "TChiWatHrcLvg": 285.0,
                "THeaWatHrcLvg": 320.0,
                "u1CooHrc": False,
            },
        }
        for timestamp, (load, status) in enumerate(loads_and_status)
    ]
    execution = PlantControlsLibrary().execute(
        "HeatRecoveryChillers.Enable",
        parameters=parameters,
        samples=samples,
    )
    output = next(
        port["id"] for port in execution["interface"]["outputs"] if port["label"] == "y1"
    )
    values = [row["outputs"][output]["value"] for row in execution["trace"]["trace"]]
    assert values[7:12] == [True, True, True, True, False]


def test_hrc_enable_requires_job_design_limits_and_rejects_invalid_values() -> None:
    library = PlantControlsLibrary()
    schema = library.parameter_schema("HeatRecoveryChillers.Enable")
    assert schema["parameterization"]["remaining_required_parameters"] == [
        "TChiWatSup_min",
        "THeaWatSup_max",
        "capCoo_min",
        "capHea_min",
    ]
    with pytest.raises(G36RequiredParametersError):
        library.translate("HeatRecoveryChillers.Enable")
    with pytest.raises(ValueError, match="capCoo_min"):
        library.translate(
            "HeatRecoveryChillers.Enable",
            parameters={**HRC_ENABLE_PARAMETERS, "capCoo_min": -1.0},
        )


def test_hrc_controller_executes_complete_load_enable_mode_and_pump_chain() -> None:
    samples = [
        {
            "time": timestamp,
            "inputs": {
                "TChiWatRetUpsHrc": 283.0,
                "TChiWatSupSet": 280.0,
                "VChiWatLoa_flow": 0.01,
                "THeaWatRetUpsHrc": 315.0,
                "THeaWatSupSet": 320.0,
                "VHeaWatLoa_flow": 0.01,
                "TChiWatHrcLvg": 285.0,
                "THeaWatHrcLvg": 320.0,
                "u1Coo": True,
                "u1Hea": True,
                "u1Hrc_actual": False,
            },
        }
        for timestamp in range(12)
    ]
    library = PlantControlsLibrary()
    execution = library.execute(
        "HeatRecoveryChillers.Controller",
        parameters=HRC_CONTROLLER_PARAMETERS,
        samples=samples,
    )
    outputs = {port["label"]: port["id"] for port in execution["interface"]["outputs"]}
    trajectories = {
        name: [
            row["outputs"][outputs[name]]["value"]
            for row in execution["trace"]["trace"]
        ]
        for name in outputs
    }
    assert trajectories["y1"] == [False] * 8 + [True] * 4
    assert trajectories["y1Coo"] == [False] * 3 + [True] * 9
    assert trajectories["TSupSet"] == [320.0] * 3 + [280.0] * 9
    assert trajectories["y1PumChiWat"] == [False] * 8 + [True] * 4
    assert trajectories["y1PumHeaWat"] == [False] * 8 + [True] * 4

    translation = library.translate(
        "HeatRecoveryChillers.Controller",
        parameters=HRC_CONTROLLER_PARAMETERS,
    )
    assert translation["product_status"] == "exact_ir_generated_program_source"
    assert "guarded_pre_equivalence" in translation["typed_ir"]["metadata"]
    target = library.assess_niagara_source_target(translation)
    assert target["complete"] is True
    assert target["generated_program_count"] == 11
    package, _ = library.niagara_program_package(
        "HeatRecoveryChillers.Controller",
        parameters=HRC_CONTROLLER_PARAMETERS,
    )
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        graph = json.loads(archive.read("control-graph.json"))
        wiring = json.loads(archive.read("wiring-plan.json"))
    assert len(manifest["programs"]) == 11
    assert len(wiring["links"]) == len(graph["links"])
    assert graph["metadata"]["guarded_pre_equivalence"].startswith("Mode can change")


def test_hrc_controller_flow_requests_hold_each_pump_until_its_request_clears() -> None:
    parameters = {**HRC_CONTROLLER_PARAMETERS, "have_reqFlo": True}
    samples = [
        {
            "time": timestamp,
            "inputs": {
                "TChiWatRetUpsHrc": 283.0,
                "TChiWatSupSet": 280.0,
                "VChiWatLoa_flow": 0.01,
                "THeaWatRetUpsHrc": 315.0,
                "THeaWatSupSet": 320.0,
                "VHeaWatLoa_flow": 0.01,
                "TChiWatHrcLvg": 285.0,
                "THeaWatHrcLvg": 320.0,
                "u1Coo": timestamp < 10,
                "u1Hea": timestamp < 10,
                "u1Hrc_actual": True,
                "u1ReqFloChiWat": timestamp < 11,
                "u1ReqFloConWat": timestamp < 12,
            },
        }
        for timestamp in range(13)
    ]
    execution = PlantControlsLibrary().execute(
        "HeatRecoveryChillers.Controller",
        parameters=parameters,
        samples=samples,
    )
    outputs = {port["label"]: port["id"] for port in execution["interface"]["outputs"]}
    trace = execution["trace"]["trace"]
    assert [
        row["outputs"][outputs["y1PumChiWat"]]["value"] for row in trace[8:]
    ] == [True, True, True, False, False]
    assert [
        row["outputs"][outputs["y1PumHeaWat"]]["value"] for row in trace[8:]
    ] == [True, True, True, True, False]


def test_hrc_controller_requires_all_designer_parameters() -> None:
    library = PlantControlsLibrary()
    schema = library.parameter_schema("HeatRecoveryChillers.Controller")
    assert set(schema["parameterization"]["remaining_required_parameters"]) == {
        "TChiWatSup_min",
        "THeaWatSup_max",
        "COPHea_nominal",
        "capCoo_min",
        "capHea_min",
        "cp_default",
        "rho_default",
    }
    with pytest.raises(G36RequiredParametersError):
        library.translate("HeatRecoveryChillers.Controller")
    with pytest.raises(ValueError, match="dtMea"):
        library.translate(
            "HeatRecoveryChillers.Controller",
            parameters={**HRC_CONTROLLER_PARAMETERS, "dtMea": 0.0},
        )


def test_stage_completion_tracks_progress_and_emits_single_completion_pulse() -> None:
    rows = [
        (0, [False, False, False], [False, False, False]),
        (1, [True, True, False], [False, False, False]),
        (1, [True, True, False], [False, False, False]),
        (1, [True, True, False], [True, False, False]),
        (1, [True, True, False], [True, True, False]),
        (1, [True, True, False], [True, True, False]),
        (2, [True, True, True], [True, True, False]),
        (2, [True, True, True], [True, True, False]),
        (2, [True, True, True], [True, True, True]),
    ]
    samples = []
    for timestamp, (stage, commands, statuses) in enumerate(rows):
        inputs: dict[str, int | bool] = {"uSta": stage}
        inputs.update(
            {f"u1__{index}": value for index, value in enumerate(commands, start=1)}
        )
        inputs.update(
            {
                f"u1_actual__{index}": value
                for index, value in enumerate(statuses, start=1)
            }
        )
        samples.append({"time": timestamp, "inputs": inputs})
    library = PlantControlsLibrary()
    execution = library.execute(
        "StagingRotation.StageCompletion",
        parameters={"nin": 3},
        samples=samples,
    )
    outputs = {port["label"]: port["id"] for port in execution["interface"]["outputs"]}
    trace = execution["trace"]["trace"]
    assert [row["outputs"][outputs["y1"]]["value"] for row in trace] == [
        False,
        True,
        True,
        True,
        False,
        False,
        True,
        True,
        False,
    ]
    assert [row["outputs"][outputs["y1End"]]["value"] for row in trace] == [
        False,
        False,
        False,
        False,
        True,
        False,
        False,
        False,
        True,
    ]
    translation = library.translate(
        "StagingRotation.StageCompletion",
        parameters={"nin": 3},
    )
    assert translation["typed_ir"]["metadata"]["vector_encoding"] == (
        "lossless_integer_bitmask"
    )
    target = library.assess_niagara_source_target(translation)
    assert target["complete"] is True
    assert target["generated_program_count"] == 1


def test_stage_completion_rejects_unbounded_or_non_integer_vector_sizes() -> None:
    library = PlantControlsLibrary()
    with pytest.raises(G36RequiredParametersError):
        library.translate("StagingRotation.StageCompletion")
    for value in (0, 53, True, 2.5):
        with pytest.raises(ValueError, match="1 through 52"):
            library.translate(
                "StagingRotation.StageCompletion",
                parameters={"nin": value},
            )


def test_equipment_enable_selects_holds_and_replaces_runtime_ordered_equipment() -> None:
    library = PlantControlsLibrary()
    parameters = {
        "staEqu": [
            [1.0, 0.0, 0.0],
            [1.0, 0.5, 0.5],
            [1.0, 1.0, 1.0],
        ]
    }
    rows = [
        (0, [2, 3], [True, True, True]),
        (1, [2, 3], [True, True, True]),
        (2, [2, 3], [True, True, True]),
        # A runtime-order change alone must not churn the active lineup.
        (2, [3, 2], [True, True, True]),
        # Loss of the enabled alternate forces an immediate replacement.
        (2, [3, 2], [True, False, True]),
        (2, [3, 2], [True, False, True]),
        (3, [3, 2], [True, True, True]),
    ]
    samples = []
    for timestamp, (stage, order, availability) in enumerate(rows):
        inputs: dict[str, int | bool] = {"uSta": stage}
        inputs.update(
            {
                f"uIdxAltSor__{rank}": equipment
                for rank, equipment in enumerate(order, start=1)
            }
        )
        inputs.update(
            {
                f"u1Ava__{equipment}": available
                for equipment, available in enumerate(availability, start=1)
            }
        )
        samples.append({"time": timestamp, "inputs": inputs})
    execution = library.execute(
        "StagingRotation.EquipmentEnable",
        parameters=parameters,
        samples=samples,
    )
    output_ids = {
        port["label"]: port["id"] for port in execution["interface"]["outputs"]
    }
    assert [
        [
            row["outputs"][output_ids[f"y1__{equipment}"]]["value"]
            for equipment in range(1, 4)
        ]
        for row in execution["trace"]["trace"]
    ] == [
        [False, False, False],
        [True, False, False],
        [True, True, False],
        [True, True, False],
        [True, False, True],
        [True, False, True],
        [True, True, True],
    ]
    translation = library.translate(
        "StagingRotation.EquipmentEnable",
        parameters=parameters,
    )
    assert translation["typed_ir"]["metadata"]["alternate_count"] == 2
    assert translation["typed_ir"]["metadata"]["equipment_count"] == 3
    target = library.assess_niagara_source_target(translation)
    assert target["complete"] is True
    assert target["generated_program_count"] == 4


def test_equipment_enable_rejects_invalid_design_and_runtime_indices() -> None:
    library = PlantControlsLibrary()
    with pytest.raises(G36RequiredParametersError):
        library.translate("StagingRotation.EquipmentEnable")
    with pytest.raises(ValueError, match="cannot be smaller"):
        library.translate(
            "StagingRotation.EquipmentEnable",
            parameters={"staEqu": [[0.5, 0.5]], "nEquAlt": 1 - 1},
        )
    parameters = {"staEqu": [[1.0, 0.0, 0.0], [1.0, 0.5, 0.5]]}
    inputs = {
        "uSta": 2,
        "uIdxAltSor__1": 2,
        "uIdxAltSor__2": 2,
        "u1Ava__1": True,
        "u1Ava__2": True,
        "u1Ava__3": True,
    }
    with pytest.raises(ValueError, match="must be unique"):
        library.execute(
            "StagingRotation.EquipmentEnable",
            parameters=parameters,
            samples=[{"time": 0, "inputs": inputs}],
        )
    with pytest.raises(ValueError, match="uSta must be from 0 through 2"):
        library.execute(
            "StagingRotation.EquipmentEnable",
            parameters=parameters,
            samples=[
                {
                    "time": 0,
                    "inputs": {
                        **inputs,
                        "uSta": 3,
                        "uIdxAltSor__2": 3,
                    },
                }
            ],
        )


def test_stage_index_enforces_runtime_and_skips_unavailable_stages() -> None:
    library = PlantControlsLibrary()
    parameters = {"nSta": 4, "dtRun": 3.0, "have_inpAva": True}
    rows = [
        (0, False, False, False, [True, False, True, True]),
        (1, True, False, False, [True, False, True, True]),
        # Stage-up is blocked before the minimum runtime expires.
        (2, True, True, False, [True, False, True, True]),
        # Stage 2 is unavailable, so the next available higher stage is 3.
        (4, True, True, False, [True, False, True, True]),
        # Loss of the active stage bypasses the runtime and advances to 4.
        (5, True, False, False, [True, False, False, True]),
        (6, True, False, True, [True, False, False, True]),
        # A stage-down skips unavailable stages 3 and 2.
        (8, True, False, True, [True, False, False, True]),
        (9, False, False, False, [True, False, False, True]),
        (11, False, False, False, [True, False, False, True]),
    ]
    samples = []
    for timestamp, lead, up, down, availability in rows:
        inputs = {"u1Lea": lead, "u1Up": up, "u1Dow": down}
        inputs.update(
            {
                f"u1AvaSta__{stage}": available
                for stage, available in enumerate(availability, start=1)
            }
        )
        samples.append({"time": timestamp, "inputs": inputs})
    execution = library.execute(
        "Utilities.StageIndex",
        parameters=parameters,
        samples=samples,
    )
    output_id = execution["interface"]["outputs"][0]["id"]
    assert [
        row["outputs"][output_id]["value"] for row in execution["trace"]["trace"]
    ] == [0, 1, 1, 3, 4, 4, 1, 1, 0]
    assert execution["interface"]["outputs"][0]["type"] == "S231:IntegerOutput"
    translation = library.translate("Utilities.StageIndex", parameters=parameters)
    assert translation["typed_ir"]["metadata"]["vector_encoding"] == (
        "lossless_integer_bitmask"
    )
    target = library.assess_niagara_source_target(translation)
    assert target["complete"] is True
    assert target["generated_program_count"] == 1


def test_stage_index_supports_always_available_topology_and_rejects_bad_sizes() -> None:
    library = PlantControlsLibrary()
    execution = library.execute(
        "Utilities.StageIndex",
        parameters={"nSta": 3, "dtRun": 0.0, "have_inpAva": False},
        samples=[
            {
                "time": 0,
                "inputs": {"u1Lea": True, "u1Up": False, "u1Dow": False},
            },
            {
                "time": 1,
                "inputs": {"u1Lea": True, "u1Up": True, "u1Dow": False},
            },
            {
                "time": 2,
                "inputs": {"u1Lea": True, "u1Up": False, "u1Dow": True},
            },
        ],
    )
    output_id = execution["interface"]["outputs"][0]["id"]
    assert [
        row["outputs"][output_id]["value"] for row in execution["trace"]["trace"]
    ] == [1, 2, 1]
    assert {port["label"] for port in execution["interface"]["inputs"]} == {
        "u1Lea",
        "u1Up",
        "u1Dow",
    }
    with pytest.raises(G36RequiredParametersError):
        library.translate("Utilities.StageIndex")
    for value in (0, 53, True, 2.5):
        with pytest.raises(ValueError, match="1 through 52"):
            library.translate("Utilities.StageIndex", parameters={"nSta": value})


def test_sort_runtime_orders_running_off_and_unavailable_alternates() -> None:
    library = PlantControlsLibrary()
    parameters = {
        "nin": 4,
        "idxEquAlt": [2, 3, 4],
        "runTim_start": [2.0, 3.0, 4.0],
    }
    rows = [
        (0, [False, False, False, False], [True, True, True, True]),
        (1, [False, False, False, True], [True, True, True, True]),
        (3, [False, False, False, True], [True, True, True, True]),
        (4, [False, True, False, True], [True, True, True, True]),
        (5, [False, True, False, True], [True, False, True, True]),
        (6, [False, True, False, True], [True, False, False, True]),
    ]
    samples = []
    for timestamp, running, available in rows:
        inputs = {
            f"u1Run__{index}": value
            for index, value in enumerate(running, start=1)
        }
        inputs.update(
            {
                f"u1Ava__{index}": value
                for index, value in enumerate(available, start=1)
            }
        )
        samples.append({"time": timestamp, "inputs": inputs})
    execution = library.execute(
        "StagingRotation.SortRuntime",
        parameters=parameters,
        samples=samples,
    )
    output_ids = {
        port["label"]: port["id"] for port in execution["interface"]["outputs"]
    }
    assert [
        [
            row["outputs"][output_ids[f"yIdx__{rank}"]]["value"]
            for rank in range(1, 4)
        ]
        for row in execution["trace"]["trace"]
    ] == [
        [2, 3, 4],
        [4, 2, 3],
        [4, 2, 3],
        [2, 4, 3],
        [4, 3, 2],
        [4, 2, 3],
    ]
    assert [
        [
            row["outputs"][output_ids[f"yRunTimSta__{position}"]]["value"]
            for position in range(1, 4)
        ]
        for row in execution["trace"]["trace"]
    ] == [
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 2.0],
        [0.0, 0.0, 3.0],
        [1.0, 0.0, 4.0],
        [2.0, 0.0, 5.0],
    ]
    assert all(
        port["type"] == "S231:IntegerOutput"
        for port in execution["interface"]["outputs"]
        if port["label"].startswith("yIdx__")
    )
    translation = library.translate(
        "StagingRotation.SortRuntime",
        parameters=parameters,
    )
    assert translation["typed_ir"]["metadata"]["sort_algorithm"] == (
        "exact_unrolled_modelica_vectors_shellsort"
    )
    target = library.assess_niagara_source_target(translation)
    assert target["complete"] is True
    assert target["generated_program_count"] == 9


def test_sort_runtime_rejects_invalid_indices_and_initial_runtime_order() -> None:
    library = PlantControlsLibrary()
    with pytest.raises(G36RequiredParametersError):
        library.translate("StagingRotation.SortRuntime")
    with pytest.raises(ValueError, match="unique equipment indices"):
        library.translate(
            "StagingRotation.SortRuntime",
            parameters={"nin": 3, "idxEquAlt": [2, 2]},
        )
    with pytest.raises(ValueError, match="strictly increasing"):
        library.translate(
            "StagingRotation.SortRuntime",
            parameters={
                "nin": 3,
                "idxEquAlt": [1, 3],
                "runTim_start": [5.0, 5.0],
            },
        )


def test_hrc_mode_control_holds_mode_and_selects_setpoint_at_exact_boundaries() -> None:
    library = PlantControlsLibrary()
    parameters = {"COPHea_nominal": 4.0}
    regimes = [
        (False, 10.0, 100.0, 280.0, 320.0),
        (True, 10.0, 100.0, 280.0, 320.0),
        (False, 100.0, 100.0, 280.0, 320.0),
        (True, 100.0, 100.0, 280.0, 320.0),
        (False, 74.5, 100.0, 281.0, 321.0),
        (True, 75.5, 100.0, 281.0, 321.0),
        (True, 76.0, 100.0, 281.0, 321.0),
    ]
    execution = library.execute(
        "HeatRecoveryChillers.ModeControl",
        parameters=parameters,
        samples=[
            {
                "time": timestamp,
                "inputs": {
                    "u1SetMod": set_mode,
                    "QChiWatReq_flow": cooling_load,
                    "QHeaWatReq_flow": heating_load,
                    "TChiWatSupSet": chilled_setpoint,
                    "THeaWatSupSet": heating_setpoint,
                },
            }
            for timestamp, (
                set_mode,
                cooling_load,
                heating_load,
                chilled_setpoint,
                heating_setpoint,
            ) in enumerate(regimes)
        ],
    )
    outputs = {port["label"]: port["id"] for port in execution["interface"]["outputs"]}
    trace = execution["trace"]["trace"]
    assert [row["outputs"][outputs["y1Coo"]]["value"] for row in trace] == [
        False,
        True,
        True,
        False,
        False,
        True,
        False,
    ]
    assert [row["outputs"][outputs["TSupSet"]]["value"] for row in trace] == [
        320.0,
        280.0,
        280.0,
        320.0,
        321.0,
        281.0,
        321.0,
    ]
    translation = library.translate(
        "HeatRecoveryChillers.ModeControl",
        parameters=parameters,
    )
    target = library.assess_niagara_source_target(translation)
    assert target["complete"] is True
    assert target["generated_program_count"] == 1
    package, _ = library.niagara_program_package(
        "HeatRecoveryChillers.ModeControl",
        parameters=parameters,
    )
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["programs"][0]["behavior_kind"] == "plant_hrc_mode_control"


def test_hrc_mode_control_rejects_unsafe_cop() -> None:
    with pytest.raises(ValueError, match=">= 1.1"):
        PlantControlsLibrary().translate(
            "HeatRecoveryChillers.ModeControl",
            parameters={"COPHea_nominal": 1.0},
        )


@pytest.mark.parametrize(
    "parameters",
    [
        {
            "have_heaWat": True,
            "have_chiWat": False,
            "have_valInlIso": False,
            "have_valOutIso": False,
            "have_pumHeaWatPri": False,
            "have_pumChiWatPri": False,
            "have_pumHeaWatSec": False,
            "have_pumChiWatSec": False,
        },
        {
            "have_heaWat": False,
            "have_chiWat": True,
            "have_valInlIso": False,
            "have_valOutIso": False,
            "have_pumHeaWatPri": False,
            "have_pumChiWatPri": False,
            "have_pumHeaWatSec": False,
            "have_pumChiWatSec": False,
        },
        {
            "have_heaWat": True,
            "have_chiWat": True,
            "have_valInlIso": True,
            "have_valOutIso": True,
            "have_pumHeaWatPri": True,
            "have_pumChiWatPri": True,
            "have_pumHeaWatSec": True,
            "have_pumChiWatSec": True,
        },
    ],
)
def test_event_sequencing_topology_matrix_has_complete_exact_target(
    parameters: dict[str, bool],
) -> None:
    library = PlantControlsLibrary()
    translation = library.translate(
        "StagingRotation.EventSequencing",
        parameters={**parameters, "dtVal": 2.0, "dtOff": 3.0},
    )

    assert translation["product_status"] == "exact_ir_generated_program_source"
    assert translation["lowering"]["translatable"] is True
    assert translation["lowering"]["unsupported_classes"] == []
    assert translation["engine_report"]["engine"] == "bactalk-reviewed-composite-lowering"
    target = library.assess_niagara_source_target(translation)
    assert target["complete"] is True
    assert target["generated_program_count"] >= 3


def test_event_sequencing_delays_enable_and_holds_hardware_through_shutdown() -> None:
    library = PlantControlsLibrary()
    parameters = {
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
    }
    execution = library.execute(
        "StagingRotation.EventSequencing",
        parameters=parameters,
        samples=[
            {
                "time": timestamp,
                "inputs": {
                    "u1Hea": 1 <= timestamp < 5,
                    "u1PumHeaWatPri_actual": 2 <= timestamp < 5,
                },
            }
            for timestamp in range(10)
        ],
    )
    outputs = {port["label"]: port["id"] for port in execution["interface"]["outputs"]}

    def trajectory(label: str) -> list[bool]:
        return [
            row["outputs"][outputs[label]]["value"]
            for row in execution["trace"]["trace"]
        ]

    assert trajectory("y1") == [
        False,
        False,
        False,
        True,
        True,
        False,
        False,
        False,
        False,
        False,
    ]
    assert trajectory("y1ValHeaWatInlIso") == [
        False,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
        False,
        False,
    ]
    assert trajectory("y1ValHeaWatOutIso") == trajectory("y1ValHeaWatInlIso")
    assert trajectory("y1PumHeaWatPri") == trajectory("y1ValHeaWatInlIso")
    translation = library.translate(
        "StagingRotation.EventSequencing",
        parameters=parameters,
    )
    assert library.assess_niagara_source_target(translation)[
        "generated_program_count"
    ] == 4


def test_connector_sized_array_rejects_shape_mismatch() -> None:
    parameters = {
        **MINIMUM_FLOW_PARAMETERS,
        "V_flow_min": [0.02, 0.06],
    }
    with pytest.raises(ValueError, match="does not match declared shape"):
        PlantControlsLibrary().translate("MinimumFlow.Setpoint", parameters=parameters)


def test_local_differential_pressure_reset_executes_and_generates_exact_pid() -> None:
    library = PlantControlsLibrary()
    controller_id = "Pumps.Generic.ResetLocalDifferentialPressure"
    parameters = {
        "dpLocSet_min": 30000.0,
        "dpLocSet_max": 100000.0,
        "k": 1.0,
        "Ti": 60.0,
    }
    translation = library.translate(controller_id, parameters=parameters)

    assert translation["product_status"] == "exact_ir_generated_program_source"
    assert translation["engine_report"]["engine"] == "open-control-engine"
    assert library.assess_niagara_source_target(translation)[
        "generated_program_count"
    ] == 1
    execution = library.execute(
        controller_id,
        parameters=parameters,
        samples=[
            {"time": 0, "inputs": {"dpRemSet": 50000.0, "dpRem": 50000.0}},
            {"time": 10, "inputs": {"dpRemSet": 50000.0, "dpRem": 49000.0}},
            {"time": 20, "inputs": {"dpRemSet": 50000.0, "dpRem": 49000.0}},
            {"time": 30, "inputs": {"dpRemSet": 50000.0, "dpRem": 51000.0}},
        ],
    )
    output_id = execution["interface"]["outputs"][0]["id"]
    assert [
        row["outputs"][output_id]["value"] for row in execution["trace"]["trace"]
    ] == [30000.0, 30700.0, 30816.666666666668, 30000.0]

    package, _ = library.niagara_program_package(controller_id, parameters=parameters)
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert len(manifest["programs"]) == 1
    assert manifest["programs"][0]["behavior_kind"] == "pid_with_reset"


@pytest.mark.parametrize("remote", [False, True])
def test_pump_differential_pressure_control_expands_pid_with_enable_exactly(
    remote: bool,
) -> None:
    library = PlantControlsLibrary()
    controller_id = "Pumps.Generic.ControlDifferentialPressure"
    parameters = {
        "have_senDpRemWir": remote,
        "nPum": 2,
        "nSenDpRem": 2,
        "k": 1.0,
        "Ti": 10.0,
    }
    translation = library.translate(controller_id, parameters=parameters)

    assert translation["product_status"] == "exact_ir_generated_program_source"
    assert translation["lowering"]["translatable"] is True
    assert translation["engine_report"]["engine"] == "bactalk-reviewed-composite-lowering"
    assert translation["engine_report"]["oce_missing_classes"] == [
        "Utilities.PIDWithEnable"
    ]
    assert translation["connection_normalization"]["array_scalarization"][
        "applied"
    ] is True
    assert library.assess_niagara_source_target(translation)[
        "generated_program_count"
    ] == (2 if remote else 1)

    statuses = [(False, False), (True, False), (True, False), (False, False),
                (False, True), (False, True)]
    samples = []
    for timestamp, (first, second) in enumerate(statuses):
        inputs = {
            "y1_actual__1": first,
            "y1_actual__2": second,
        }
        if remote:
            inputs.update(
                {
                    "dpRemSet__1": 5000.0,
                    "dpRemSet__2": 7000.0,
                    "dpRem__1": 4000.0,
                    "dpRem__2": 6000.0,
                }
            )
        else:
            inputs.update(
                {
                    "dpLocSet__1": 5000.0,
                    "dpLocSet__2": 7000.0,
                    "dpLoc": 6000.0,
                }
            )
        samples.append({"time": timestamp, "inputs": inputs})

    execution = library.execute(
        controller_id,
        parameters=parameters,
        samples=samples,
        collect=["y"],
    )
    output_id = execution["interface"]["outputs"][-1]["id"]
    assert [
        row["outputs"][output_id]["value"] for row in execution["trace"]["trace"]
    ] == pytest.approx([0.0, 0.1, 0.1, 0.0, 0.1, 0.1])

    package, _ = library.niagara_program_package(
        controller_id,
        parameters=parameters,
    )
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        graph = json.loads(archive.read("control-graph.json"))
    assert len(manifest["programs"]) == (2 if remote else 1)
    assert {program["behavior_kind"] for program in manifest["programs"]} == {
        "pid_with_reset"
    }
    assert sum(block["kind"] == "one_shot" for block in graph["blocks"]) == (
        2 if remote else 1
    )


def test_count_true_connector_array_executes_and_has_stock_target() -> None:
    library = PlantControlsLibrary()
    translation = library.translate("Utilities.CountTrue", parameters={"nin": 4})

    assert translation["product_status"] == "exact_ir_stock_niagara"
    assert translation["lowering"]["component_count"] == 7
    assert translation["lowering"]["niagara_translatable"] is True
    execution = library.execute(
        "Utilities.CountTrue",
        parameters={"nin": 4},
        samples=[
            {
                "time": 0,
                "inputs": {
                    "u1__1": True,
                    "u1__2": False,
                    "u1__3": True,
                    "u1__4": True,
                },
            }
        ],
    )
    output_id = execution["interface"]["outputs"][0]["id"]
    assert execution["trace"]["trace"][0]["outputs"][output_id] == {
        "type": "integer",
        "value": 3,
    }


def test_dedicated_primary_pump_disable_executes_both_flow_request_variants() -> None:
    library = PlantControlsLibrary()
    parameters = {"have_reqFlo": False, "dtOff": 3.0}
    translation = library.translate(DISABLE_DEDICATED, parameters=parameters)

    assert translation["product_status"] == "exact_ir_generated_program_source"
    assert translation["engine_report"]["engine"] == (
        "bactalk-reviewed-composite-lowering"
    )
    assert translation["engine_report"]["oce_missing_classes"] == [
        "Utilities.Initialization"
    ]
    assert {port["label"] for port in translation["interface"]["inputs"]} == {
        "u1",
        "u1Equ",
        "u1Equ_actual",
    }
    execution = library.execute(
        DISABLE_DEDICATED,
        parameters=parameters,
        samples=[
            {
                "time": timestamp,
                "inputs": {
                    "u1": True,
                    "u1Equ": timestamp == 0,
                    "u1Equ_actual": timestamp == 0,
                },
            }
            for timestamp in range(7)
        ],
    )
    output_id = execution["interface"]["outputs"][0]["id"]
    assert [
        row["outputs"][output_id]["value"] for row in execution["trace"]["trace"]
    ] == [True, True, True, True, False, False, False]

    with_flow = {"have_reqFlo": True, "dtOff": 3.0}
    flow_translation = library.translate(DISABLE_DEDICATED, parameters=with_flow)
    assert {port["label"] for port in flow_translation["interface"]["inputs"]} == {
        "u1",
        "u1Equ",
        "u1Equ_actual",
        "u1ReqFlo",
    }
    flow_execution = library.execute(
        DISABLE_DEDICATED,
        parameters=with_flow,
        samples=[
            {
                "time": 0,
                "inputs": {
                    "u1": True,
                    "u1Equ": True,
                    "u1Equ_actual": True,
                    "u1ReqFlo": True,
                },
            },
            {
                "time": 1,
                "inputs": {
                    "u1": True,
                    "u1Equ": False,
                    "u1Equ_actual": True,
                    "u1ReqFlo": False,
                },
            },
            {
                "time": 2,
                "inputs": {
                    "u1": True,
                    "u1Equ": False,
                    "u1Equ_actual": True,
                    "u1ReqFlo": False,
                },
            },
        ],
    )
    flow_output_id = flow_execution["interface"]["outputs"][0]["id"]
    assert [
        row["outputs"][flow_output_id]["value"]
        for row in flow_execution["trace"]["trace"]
    ] == [True, False, False]

    package, _ = library.niagara_program_package(
        DISABLE_DEDICATED,
        parameters=parameters,
    )
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert {program["behavior_kind"] for program in manifest["programs"]} == {
        "boolean_initialization",
        "boolean_set_reset",
        "timer",
    }
    assert library.assess_niagara_source_target(translation) == {
        "complete": True,
        "delivery_mode": "generated_program_source",
        "generated_program_count": 3,
        "blocker": None,
        "runtime_qualified": False,
        "licensed_workbench_compile_required": True,
    }


def test_staging_failsafe_executes_heating_and_cooling_topologies() -> None:
    library = PlantControlsLibrary()
    heating_parameters = {
        "typ": "Buildings.Templates.Plants.Controls.Types.Application.Heating",
        "have_pumSec": False,
        "dT": 2.0,
        "dtPri": 3.0,
    }
    heating = library.translate(
        FAILSAFE_CONDITION,
        parameters=heating_parameters,
    )

    assert heating["product_status"] == "exact_ir_generated_program_source"
    assert heating["lowering"]["translatable"] is True
    assert heating["engine_report"]["engine"] == "bactalk-reviewed-composite-lowering"
    assert heating["lowering"]["class_counts"]["Utilities.TimerWithReset"] == 1
    heating_execution = library.execute(
        FAILSAFE_CONDITION,
        parameters=heating_parameters,
        samples=[
            {
                "time": timestamp,
                "inputs": {
                    "TPriSup": 295.0 if timestamp == 0 else 290.0,
                    "TSupSet": 295.0,
                    "reset": timestamp == 5,
                },
            }
            for timestamp in range(6)
        ],
    )
    heating_output = heating_execution["interface"]["outputs"][0]["id"]
    assert [
        row["outputs"][heating_output]["value"]
        for row in heating_execution["trace"]["trace"]
    ] == [False, False, False, False, True, False]
    assert library.assess_niagara_source_target(heating)["generated_program_count"] == 1

    cooling_parameters = {
        "typ": "Buildings.Templates.Plants.Controls.Types.Application.Cooling",
        "have_pumSec": True,
        "dT": 2.0,
        "dtPri": 3.0,
        "dtSec": 2.0,
    }
    cooling = library.translate(
        FAILSAFE_CONDITION,
        parameters=cooling_parameters,
    )
    assert {port["label"] for port in cooling["interface"]["inputs"]} == {
        "TPriSup",
        "TSecSup",
        "TSupSet",
        "reset",
    }
    cooling_execution = library.execute(
        FAILSAFE_CONDITION,
        parameters=cooling_parameters,
        samples=[
            {
                "time": timestamp,
                "inputs": {
                    "TPriSup": 295.0 if timestamp == 0 else 298.0,
                    "TSecSup": 295.0 if timestamp == 0 else 301.0,
                    "TSupSet": 295.0,
                    "reset": False,
                },
            }
            for timestamp in range(5)
        ],
    )
    cooling_output = cooling_execution["interface"]["outputs"][0]["id"]
    assert [
        row["outputs"][cooling_output]["value"]
        for row in cooling_execution["trace"]["trace"]
    ] == [False, False, False, True, True]
    assert library.assess_niagara_source_target(cooling)["generated_program_count"] == 3

    package, _ = library.niagara_program_package(
        FAILSAFE_CONDITION,
        parameters=heating_parameters,
    )
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert {program["behavior_kind"] for program in manifest["programs"]} == {
        "timer_with_reset"
    }


def test_headered_delta_p_staging_executes_efficiency_and_failsafe_paths() -> None:
    library = PlantControlsLibrary()
    stage_index_schema = library.parameter_schema("Utilities.StageIndex")
    assert stage_index_schema["parameterization"]["remaining_required_parameters"] == [
        "nSta"
    ]
    parameters = {
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
    }
    translation = library.translate(
        "Pumps.Generic.StagingHeaderedDeltaP", parameters=parameters
    )

    assert translation["product_status"] == "exact_ir_generated_program_source"
    assert translation["lowering"]["translatable"] is True
    assert len(translation["typed_ir"]["blocks"]) == 70
    assert library.assess_niagara_source_target(translation) == {
        "complete": True,
        "delivery_mode": "generated_program_source",
        "generated_program_count": 15,
        "blocker": None,
        "runtime_qualified": False,
        "licensed_workbench_compile_required": True,
    }

    def samples(*, failsafe: bool) -> list[dict[str, object]]:
        result = []
        for timestamp in range(6):
            statuses = [True, False, False] if timestamp < 3 else [True, True, False]
            inputs: dict[str, object] = {
                "V_flow": (
                    0.8
                    if failsafe
                    else 1.5
                    if timestamp < 3
                    else 0.3
                ),
                "y": 1.0 if failsafe and timestamp < 3 else 0.2 if failsafe else 0.5,
            }
            inputs.update(
                {
                    f"u1_actual__{index}": value
                    for index, value in enumerate(statuses, start=1)
                }
            )
            inputs.update(
                {
                    f"dp__{index}": (
                        80.0 if failsafe and timestamp < 3 else 100.0
                    )
                    for index in range(1, 3)
                }
            )
            inputs.update({f"dpSet__{index}": 100.0 for index in range(1, 3)})
            result.append({"time": timestamp, "inputs": inputs})
        return result

    for failsafe in (False, True):
        execution = library.execute(
            "Pumps.Generic.StagingHeaderedDeltaP",
            parameters=parameters,
            samples=samples(failsafe=failsafe),
        )
        output_ids = {
            port["label"]: port["id"] for port in execution["interface"]["outputs"]
        }
        assert [
            (
                row["outputs"][output_ids["y1Up"]]["value"],
                row["outputs"][output_ids["y1Dow"]]["value"],
            )
            for row in execution["trace"]["trace"]
        ] == [
            (False, False),
            (False, False),
            (True, False),
            (False, False),
            (False, False),
            (False, True),
        ]

    package, _ = library.niagara_program_package(
        "Pumps.Generic.StagingHeaderedDeltaP", parameters=parameters
    )
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert len(manifest["programs"]) == 15


def test_headered_delta_p_staging_rejects_unsafe_dimensions_and_offsets() -> None:
    library = PlantControlsLibrary()
    with pytest.raises(ValueError, match="nPum"):
        library.translate(
            "Pumps.Generic.StagingHeaderedDeltaP",
            parameters={"nPum": 0, "nSenDp": 1, "V_flow_nominal": 1.0},
        )
    with pytest.raises(ValueError, match="dVOffDow"):
        library.translate(
            "Pumps.Generic.StagingHeaderedDeltaP",
            parameters={
                "nPum": 1,
                "nSenDp": 1,
                "V_flow_nominal": 1.0,
                "dVOffDow": 1.1,
            },
        )


def test_stage_change_command_executes_load_hold_capacity_and_failsafe_paths() -> None:
    library = PlantControlsLibrary()
    parameters = {
        "typ": "Buildings.Templates.Plants.Controls.Types.Application.Heating",
        "have_pumSec": False,
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
    }
    translation = library.translate(
        "StagingRotation.StageChangeCommand", parameters=parameters
    )
    assert translation["product_status"] == "exact_ir_generated_program_source"
    assert len(translation["typed_ir"]["blocks"]) == 59
    assert library.assess_niagara_source_target(translation)[
        "generated_program_count"
    ] == 9

    samples = []
    for timestamp in range(10):
        high_load = timestamp < 4
        samples.append(
            {
                "time": timestamp,
                "inputs": {
                    "uSta": 1 if high_load else 2,
                    "u1StaPro": timestamp == 3,
                    "TRet": 0.0 if high_load else 15.0,
                    "TSupSet": 20.0,
                    "V_flow": 10.0,
                    "TPriSup": 20.0,
                    "u1AvaSta__1": True,
                    "u1AvaSta__2": True,
                },
            }
        )
    execution = library.execute(
        "StagingRotation.StageChangeCommand",
        parameters=parameters,
        samples=samples,
    )
    output_ids = {
        port["label"]: port["id"] for port in execution["interface"]["outputs"]
    }
    assert [
        (
            row["outputs"][output_ids["y1Up"]]["value"],
            row["outputs"][output_ids["y1Dow"]]["value"],
        )
        for row in execution["trace"]["trace"]
    ] == [
        (False, False),
        (False, False),
        (False, False),
        (True, False),
        (False, False),
        (False, False),
        (False, False),
        (False, True),
        (False, True),
        (False, True),
    ]

    secondary_parameters = {
        **parameters,
        "have_pumSec": True,
        "staEqu": [[1.0]],
        "capEqu": [100.0],
    }
    secondary = library.execute(
        "StagingRotation.StageChangeCommand",
        parameters=secondary_parameters,
        samples=[
            {
                "time": timestamp,
                "inputs": {
                    "uSta": 1,
                    "u1StaPro": False,
                    "TRet": 20.0,
                    "TSupSet": 20.0,
                    "V_flow": 0.0,
                    "TPriSup": 20.0,
                    "TSecSup": 17.0,
                    "u1AvaSta__1": True,
                },
            }
            for timestamp in range(4)
        ],
    )
    secondary_ids = {
        port["label"]: port["id"] for port in secondary["interface"]["outputs"]
    }
    assert [
        row["outputs"][secondary_ids["y1Up"]]["value"]
        for row in secondary["trace"]["trace"]
    ] == [False, False, True, True]
    secondary_target = library.assess_niagara_source_target(
        library.translate(
            "StagingRotation.StageChangeCommand",
            parameters=secondary_parameters,
        )
    )
    assert secondary_target["generated_program_count"] == 11

    package, _ = library.niagara_program_package(
        "StagingRotation.StageChangeCommand", parameters=secondary_parameters
    )
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert len(manifest["programs"]) == 11


def test_stage_change_command_rejects_mismatched_or_nonpositive_capacities() -> None:
    library = PlantControlsLibrary()
    base = {
        "typ": "Heating",
        "have_pumSec": False,
        "staEqu": [[1.0, 0.0], [1.0, 1.0]],
        "cp_default": 1.0,
        "rho_default": 1.0,
        "dT": 2.0,
    }
    with pytest.raises(ValueError, match="length"):
        library.translate(
            "StagingRotation.StageChangeCommand",
            parameters={**base, "capEqu": [100.0]},
        )
    with pytest.raises(ValueError, match="positive finite"):
        library.translate(
            "StagingRotation.StageChangeCommand",
            parameters={**base, "capEqu": [100.0, 0.0]},
        )


def test_headered_pump_parent_composes_rotation_staging_and_status_feedback() -> None:
    library = PlantControlsLibrary()
    parameters = {
        "is_pri": True,
        "is_hdr": True,
        "is_ctlDp": False,
        "have_valInlIso": True,
        "have_valOutIso": False,
        "nEqu": 2,
        "nPum": 2,
    }
    samples = [
        {
            "time": timestamp,
            "inputs": {
                "u1Pum_actual__1": False,
                "u1Pum_actual__2": True,
                "u1ValInlIso__1": timestamp in {1, 2},
                "u1ValInlIso__2": False,
                "u1Pum__1": timestamp >= 1,
                "u1Pum__2": timestamp == 2,
            },
        }
        for timestamp in range(4)
    ]
    execution = library.execute(
        "Pumps.Generic.StagingHeadered",
        parameters=parameters,
        samples=samples,
    )
    output_ids = {
        port["label"]: port["id"] for port in execution["interface"]["outputs"]
    }
    assert [
        [
            row["outputs"][output_ids[f"y1__{pump}"]]["value"]
            for pump in range(1, 3)
        ]
        for row in execution["trace"]["trace"]
    ] == [
        [False, False],
        [False, True],
        [True, True],
        [False, False],
    ]
    assert [
        [
            row["outputs"][output_ids[f"y1_actual__{equipment}"]]["value"]
            for equipment in range(1, 3)
        ]
        for row in execution["trace"]["trace"]
    ] == [[True, True]] * 4
    target = library.assess_niagara_source_target(
        library.translate("Pumps.Generic.StagingHeadered", parameters=parameters)
    )
    assert target["complete"] is True
    assert target["generated_program_count"] == 10


def test_headered_pump_parent_executes_primary_and_secondary_delta_p_topologies() -> None:
    library = PlantControlsLibrary()
    common = {
        "is_hdr": True,
        "is_ctlDp": True,
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
    }
    for primary, expected_programs in ((True, 23), (False, 22)):
        parameters = {
            **common,
            "is_pri": primary,
            "have_valInlIso": primary,
        }
        samples = []
        for timestamp in range(6):
            inputs: dict[str, object] = {
                "u1Pum_actual__1": True,
                "u1Pum_actual__2": timestamp >= 3,
                "V_flow": 1.2 if timestamp < 3 else 0.3,
                "y": 0.5,
                "dp__1": 100.0,
                "dpSet__1": 100.0,
            }
            if primary:
                inputs.update(
                    {
                        "u1ValInlIso__1": timestamp < 5,
                        "u1ValInlIso__2": False,
                    }
                )
            else:
                inputs["u1Pla"] = timestamp < 5
            samples.append({"time": timestamp, "inputs": inputs})
        execution = library.execute(
            "Pumps.Generic.StagingHeadered",
            parameters=parameters,
            samples=samples,
        )
        output_ids = {
            port["label"]: port["id"] for port in execution["interface"]["outputs"]
        }
        assert [
            [
                row["outputs"][output_ids[f"y1__{pump}"]]["value"]
                for pump in range(1, 3)
            ]
            for row in execution["trace"]["trace"]
        ] == [
            [True, False],
            [True, False],
            [True, True],
            [True, True],
            [True, True],
            [False, False],
        ]
        translation = library.translate(
            "Pumps.Generic.StagingHeadered", parameters=parameters
        )
        assert library.assess_niagara_source_target(translation)[
            "generated_program_count"
        ] == expected_programs
        package, _ = library.niagara_program_package(
            "Pumps.Generic.StagingHeadered", parameters=parameters
        )
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        assert len(manifest["programs"]) == expected_programs


def test_headered_pump_parent_rejects_unwired_source_topologies() -> None:
    library = PlantControlsLibrary()
    base = {
        "is_pri": True,
        "is_ctlDp": False,
        "have_valInlIso": True,
        "have_valOutIso": False,
        "nEqu": 2,
        "nPum": 2,
    }
    with pytest.raises(ValueError, match="is_hdr=true"):
        library.translate(
            "Pumps.Generic.StagingHeadered",
            parameters={**base, "is_hdr": False},
        )
    with pytest.raises(ValueError, match="require is_ctlDp=true"):
        library.translate(
            "Pumps.Generic.StagingHeadered",
            parameters={
                **base,
                "is_pri": False,
                "is_hdr": True,
                "have_valInlIso": False,
            },
        )


def test_primary_variable_speed_executes_fixed_and_common_reversible_topologies() -> None:
    library = PlantControlsLibrary()
    fixed_headered = {
        "have_heaWat": True,
        "have_chiWat": False,
        "have_pumPriCtlDp": False,
        "have_pumPriHdr": True,
        "nEqu": 2,
        "nPumHeaWatPri": 2,
        "yPumHeaWatPriSet": 0.8,
    }
    execution = library.execute(
        "Pumps.Primary.VariableSpeed",
        parameters=fixed_headered,
        samples=[
            {
                "time": timestamp,
                "inputs": {
                    "u1PumHeaWatPri__1": timestamp == 1,
                    "u1PumHeaWatPri__2": False,
                },
            }
            for timestamp in range(3)
        ],
    )
    output_id = execution["interface"]["outputs"][0]["id"]
    assert [
        row["outputs"][output_id]["value"] for row in execution["trace"]["trace"]
    ] == [0.0, 0.8, 0.0]
    assert library.assess_niagara_source_target(
        library.translate("Pumps.Primary.VariableSpeed", parameters=fixed_headered)
    )["delivery_mode"] == "qualified_stock_components"

    common = {
        "have_heaWat": True,
        "have_chiWat": True,
        "have_pumPriCtlDp": False,
        "have_pumPriHdr": False,
        "have_pumChiWatPriDed": False,
        "nEqu": 2,
        "nPumHeaWatPri": 2,
        "yPumHeaWatPriSet": 0.8,
        "yPumChiWatPriSet": 0.6,
    }
    common_execution = library.execute(
        "Pumps.Primary.VariableSpeed",
        parameters=common,
        samples=[
            {
                "time": timestamp,
                "inputs": {
                    "u1PumHeaWatPri__1": timestamp in {1, 2, 4},
                    "u1PumHeaWatPri__2": False,
                    "u1Hea__1": timestamp < 2,
                    "u1Hea__2": True,
                },
            }
            for timestamp in range(5)
        ],
    )
    common_ids = {
        port["label"]: port["id"]
        for port in common_execution["interface"]["outputs"]
    }
    assert [
        row["outputs"][common_ids["yPumHeaWatPriDed__1"]]["value"]
        for row in common_execution["trace"]["trace"]
    ] == [0.0, 0.8, 0.8, 0.0, 0.6]
    target = library.assess_niagara_source_target(
        library.translate("Pumps.Primary.VariableSpeed", parameters=common)
    )
    assert target["generated_program_count"] == 4


def test_primary_variable_speed_composes_local_and_remote_delta_p_loops() -> None:
    library = PlantControlsLibrary()
    parameters = {
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
    }
    execution = library.execute(
        "Pumps.Primary.VariableSpeed",
        parameters=parameters,
        samples=[
            {
                "time": timestamp,
                "inputs": {
                    "u1PumHeaWatPri__1": True,
                    "u1PumHeaWatPri__2": False,
                    "u1PumChiWatPri__1": True,
                    "u1PumChiWatPri__2": False,
                    "u1PumHeaWatPri_actual__1": True,
                    "u1PumHeaWatPri_actual__2": False,
                    "u1PumChiWatPri_actual__1": True,
                    "u1PumChiWatPri_actual__2": False,
                    "dpHeaWatLoc": 50.0,
                    "dpHeaWatLocSet__1": 100.0,
                    "dpChiWatRem__1": 50.0,
                    "dpChiWatRemSet__1": 100.0,
                },
            }
            for timestamp in range(3)
        ],
    )
    output_ids = {
        port["label"]: port["id"] for port in execution["interface"]["outputs"]
    }
    assert [
        row["outputs"][output_ids["yPumHeaWatPriHdr"]]["value"]
        for row in execution["trace"]["trace"]
    ] == [0.1, 0.1, 0.1005]
    assert [
        row["outputs"][output_ids["yPumChiWatPriHdr"]]["value"]
        for row in execution["trace"]["trace"]
    ] == [0.1, 0.1, 0.1005]
    assert [
        row["outputs"][output_ids["dpHeaWatLocSetMax"]]["value"]
        for row in execution["trace"]["trace"]
    ] == [100.0, 100.0, 100.0]
    target = library.assess_niagara_source_target(
        library.translate("Pumps.Primary.VariableSpeed", parameters=parameters)
    )
    assert target["generated_program_count"] == 2
    package, _ = library.niagara_program_package(
        "Pumps.Primary.VariableSpeed", parameters=parameters
    )
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert len(manifest["programs"]) == 2


def test_primary_variable_speed_rejects_invalid_common_pump_dimensions() -> None:
    with pytest.raises(ValueError, match="nEqu=nPumHeaWatPri"):
        PlantControlsLibrary().translate(
            "Pumps.Primary.VariableSpeed",
            parameters={
                "have_heaWat": True,
                "have_chiWat": True,
                "have_pumPriCtlDp": False,
                "have_pumPriHdr": False,
                "have_pumChiWatPriDed": False,
                "nEqu": 3,
                "nPumHeaWatPri": 2,
                "yPumHeaWatPriSet": 0.8,
                "yPumChiWatPriSet": 0.6,
            },
        )


def test_air_to_water_executes_primary_only_startup_and_packages_complete_plant() -> None:
    library = PlantControlsLibrary()
    translation = library.translate(
        "HeatPumps.AirToWater", parameters=AIR_TO_WATER_PARAMETERS
    )
    assert translation["product_status"] == "exact_ir_generated_program_source"
    assert len(translation["typed_ir"]["blocks"]) == 480
    target = library.assess_niagara_source_target(translation)
    assert target["complete"] is True
    assert target["generated_program_count"] == 59

    samples = []
    for timestamp in range(8):
        samples.append(
            {
                "time": timestamp,
                "inputs": {
                    "THeaWatPriRet": 0.0,
                    "THeaWatPriSup": 20.0,
                    "TOut": 280.0,
                    "VHeaWatPri_flow": 10.0,
                    "dpHeaWatLoc": 50.0,
                    "dpHeaWatLocSet__1": 100.0,
                    "nReqPlaHeaWat": 1,
                    "nReqResHeaWat": 0,
                    "u1Hp_actual__1": timestamp >= 7,
                    "u1Hp_actual__2": False,
                    "u1PumHeaWatPri_actual__1": timestamp >= 4,
                    "u1PumHeaWatPri_actual__2": False,
                    "u1SchHea": True,
                },
            }
        )
    execution = library.execute(
        "HeatPumps.AirToWater",
        parameters=AIR_TO_WATER_PARAMETERS,
        samples=samples,
    )
    output_ids = {
        port["label"]: port["id"] for port in execution["interface"]["outputs"]
    }
    assert [
        row["outputs"][output_ids["y1PumHeaWatPri__1"]]["value"]
        for row in execution["trace"]["trace"]
    ] == [False, False, True, True, True, True, True, True]
    assert [
        row["outputs"][output_ids["y1Hp__1"]]["value"]
        for row in execution["trace"]["trace"]
    ] == [False, False, False, False, False, True, True, True]
    assert [
        row["outputs"][output_ids["yPumHeaWatPriHdr"]]["value"]
        for row in execution["trace"]["trace"]
    ] == [0.0, 0.0, 0.0, 0.0, 0.1, 0.1, 0.1005, 0.101]

    package, _ = library.niagara_program_package(
        "HeatPumps.AirToWater", parameters=AIR_TO_WATER_PARAMETERS
    )
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        graph = json.loads(archive.read("control-graph.json"))
    assert len(manifest["programs"]) == 59
    assert len(graph["blocks"]) == 480

    job_template = library.job_template(
        "HeatPumps.AirToWater",
        parameters=AIR_TO_WATER_PARAMETERS,
    )
    assert job_template["points"][0]["name"] == "THeaWatPriRet"
    assert all("urn:" not in point["name"] for point in job_template["points"])
    assert len(job_template["acceptance_output_targets"]) == 12


def test_air_to_water_builds_primary_secondary_hrc_and_alternate_rotation() -> None:
    library = PlantControlsLibrary()
    primary_secondary = {
        **AIR_TO_WATER_PARAMETERS,
        "have_chiWat": True,
        "is_priOnl": False,
        "have_hrc_select": True,
        "capCooHp_nominal": [90.0, 90.0],
        "have_senDpChiWatRemWir": True,
        "nSenDpChiWatRem": 1,
        "dtResChiWat": 2.0,
        "TiCtlDpChiWat": 10.0,
    }
    translation = library.translate(
        "HeatPumps.AirToWater", parameters=primary_secondary
    )
    target = library.assess_niagara_source_target(translation)
    assert target["complete"] is True
    assert target["generated_program_count"] == 143
    output_labels = {port["label"] for port in translation["interface"]["outputs"]}
    assert {
        "y1Hrc",
        "y1PumHeaWatSec__1",
        "y1PumChiWatSec__1",
        "y1HeaHp__1",
        "THeaWatSupHrcSet",
        "TChiWatSupHrcSet",
    } <= output_labels

    alternates = {
        **AIR_TO_WATER_PARAMETERS,
        "is_priOnl": False,
        "nHp": 3,
        "nPumHeaWatPri": 3,
        "nPumHeaWatSec": 3,
        "staEqu": [[1.0, 0.0, 0.0], [1.0, 0.5, 0.5], [1.0, 1.0, 1.0]],
        "capHeaHp_nominal": [100.0, 100.0, 100.0],
        "VHeaWatHp_flow_nominal": [1.0, 1.0, 1.0],
        "VHeaWatHp_flow_min": [0.1, 0.1, 0.1],
    }
    alternate_translation = library.translate(
        "HeatPumps.AirToWater", parameters=alternates
    )
    assert alternate_translation["parameterization"]["parameters"][21]["value"] == [
        2,
        3,
    ]
    assert library.assess_niagara_source_target(alternate_translation)["complete"] is True


def test_air_to_water_rejects_unsafe_or_incoherent_topologies() -> None:
    library = PlantControlsLibrary()
    with pytest.raises(ValueError, match="heating or cooling"):
        library.translate(
            "HeatPumps.AirToWater",
            parameters={
                **AIR_TO_WATER_PARAMETERS,
                "have_heaWat": False,
                "have_chiWat": False,
            },
        )
    with pytest.raises(ValueError, match="isolation valves"):
        library.translate(
            "HeatPumps.AirToWater",
            parameters={
                **AIR_TO_WATER_PARAMETERS,
                "have_valHpInlIso": False,
            },
        )
    with pytest.raises(ValueError, match="width must equal nHp"):
        library.translate(
            "HeatPumps.AirToWater",
            parameters={
                **AIR_TO_WATER_PARAMETERS,
                "nHp": 3,
            },
        )


@pytest.mark.parametrize(
    ("controller_id", "expected"),
    [
        ("Utilities.FirstTrueIndex", [0, 2, 1]),
        ("Utilities.LastTrueIndex", [0, 4, 3]),
    ],
)
def test_true_index_utilities_execute_vector_reductions_with_stock_target(
    controller_id: str,
    expected: list[int],
) -> None:
    library = PlantControlsLibrary()
    translation = library.translate(controller_id, parameters={"nin": 4})

    assert translation["product_status"] == "exact_ir_stock_niagara"
    assert translation["engine_report"]["engine"] == "open-control-engine"
    assert translation["lowering"]["translatable"] is True
    assert translation["lowering"]["niagara_translatable"] is True
    samples = [
        (False, False, False, False),
        (False, True, False, True),
        (True, False, True, False),
    ]
    execution = library.execute(
        controller_id,
        parameters={"nin": 4},
        samples=[
            {
                "time": index,
                "inputs": {
                    f"u1__{position + 1}": value
                    for position, value in enumerate(values)
                },
            }
            for index, values in enumerate(samples)
        ],
    )
    output_id = execution["interface"]["outputs"][0]["id"]
    assert [
        row["outputs"][output_id]["value"] for row in execution["trace"]["trace"]
    ] == expected
    assert library.assess_niagara_source_target(translation) == {
        "complete": True,
        "delivery_mode": "qualified_stock_components",
        "generated_program_count": 0,
        "blocker": None,
    }


@pytest.mark.parametrize(
    ("controller_id", "expected"),
    [
        ("Utilities.MultiMaxInteger", 9),
        ("Utilities.MultiMinInteger", -1),
    ],
)
def test_direct_integer_source_equations_execute_and_target_stock_niagara(
    controller_id: str,
    expected: int,
) -> None:
    library = PlantControlsLibrary()
    translation = library.translate(controller_id, parameters={"nin": 4})
    execution = library.execute(
        controller_id,
        parameters={"nin": 4},
        samples=[
            {
                "time": 0,
                "inputs": {"u__1": 2, "u__2": 9, "u__3": -1, "u__4": 5},
            }
        ],
    )

    assert translation["product_status"] == "exact_ir_stock_niagara"
    assert translation["engine_report"]["engine"] == "bactalk-source-equation-lowering"
    output_id = execution["interface"]["outputs"][0]["id"]
    assert execution["trace"]["trace"][0]["outputs"][output_id] == {
        "type": "integer",
        "value": expected,
    }
    assert library.assess_niagara_source_target(translation) == {
        "complete": True,
        "delivery_mode": "qualified_stock_components",
        "generated_program_count": 0,
        "blocker": None,
    }
    with pytest.raises(ValueError, match="integer source-algorithm inputs"):
        library.execute(
            controller_id,
            parameters={"nin": 4},
            samples=[
                {
                    "time": 0,
                    "inputs": {"u__1": 2, "u__2": 9.5, "u__3": -1, "u__4": 5},
                }
            ],
        )


def test_true_array_conditional_preserves_priority_invalid_and_duplicate_semantics(
    tmp_path: Path,
) -> None:
    library = PlantControlsLibrary()
    parameters = {"nin": 5, "nout": 4}
    translation = library.translate(
        "Utilities.TrueArrayConditional",
        parameters=parameters,
    )

    assert translation["product_status"] == "exact_ir_stock_niagara"
    assert translation["engine_report"]["engine"] == "bactalk-source-equation-lowering"
    assert {port["label"] for port in translation["interface"]["inputs"]} == {
        "u",
        "uIdx__1",
        "uIdx__2",
        "uIdx__3",
        "uIdx__4",
        "uIdx__5",
    }
    assert library.assess_niagara_source_target(translation) == {
        "complete": True,
        "delivery_mode": "qualified_stock_components",
        "generated_program_count": 0,
        "blocker": None,
    }
    artifact = NiagaraCompiler().compile(
        ControlGraph.model_validate(translation["typed_ir"]),
        tmp_path / "true-array-conditional.bog",
    )
    with zipfile.ZipFile(artifact) as archive:
        xml = archive.read("file.xml")
    assert b"kitControl:NumericSwitch" in xml
    assert b"kitControl:GreaterThanEqual" in xml
    assert b"kitControl:LessThanEqual" in xml
    assert b"kitControl:Equal" in xml

    priority = [0, 4, 4, 9, 2]
    requested = [-1, 0, 1, 2, 3, 99]
    execution = library.execute(
        "Utilities.TrueArrayConditional",
        parameters=parameters,
        samples=[
            {
                "time": sample_index,
                "inputs": {
                    "u": count,
                    **{
                        f"uIdx__{index + 1}": value
                        for index, value in enumerate(priority)
                    },
                },
            }
            for sample_index, count in enumerate(requested)
        ],
    )
    output_ids = {
        port["label"]: port["id"] for port in execution["interface"]["outputs"]
    }
    assert [
        [
            row["outputs"][output_ids[f"y1__{index}"]]["value"]
            for index in range(1, 5)
        ]
        for row in execution["trace"]["trace"]
    ] == [
        [False, False, False, False],
        [False, False, False, False],
        [False, False, False, True],
        [False, False, False, True],
        [False, True, False, True],
        [False, True, False, True],
    ]

    with pytest.raises(ValueError, match="integer source-algorithm inputs"):
        library.execute(
            "Utilities.TrueArrayConditional",
            parameters=parameters,
            samples=[
                {
                    "time": 0,
                    "inputs": {
                        "u": 2.5,
                        "uIdx__1": 1,
                        "uIdx__2": 2,
                        "uIdx__3": 3,
                        "uIdx__4": 4,
                        "uIdx__5": 1,
                    },
                }
            ],
        )


def test_true_array_conditional_parameter_contract_is_bounded_and_defaults_nout() -> None:
    library = PlantControlsLibrary()
    schema = library.parameter_schema("Utilities.TrueArrayConditional")
    assert schema["parameterization"]["remaining_required_parameters"] == ["nin"]

    translation = library.translate(
        "Utilities.TrueArrayConditional",
        parameters={"nin": 3},
    )
    values = {
        item["name"]: item["value"]
        for item in translation["parameterization"]["parameters"]
    }
    assert values == {"nin": 3, "nout": 3}
    assert len(translation["interface"]["outputs"]) == 3

    with pytest.raises(ValueError, match="nin must be an integer from 1 through 64"):
        library.translate(
            "Utilities.TrueArrayConditional",
            parameters={"nin": 65},
        )


@pytest.mark.parametrize(
    ("controller_id", "primary", "placeholder", "constant", "trace_type"),
    [
        ("Utilities.PlaceholderLogical", True, False, True, "boolean"),
        ("Utilities.PlaceholderReal", 12.5, -4.25, 7.75, "real"),
        ("Utilities.PlaceholderInteger", 12, -4, 7, "integer"),
    ],
)
def test_placeholder_utilities_execute_and_compile_all_conditional_topologies(
    controller_id: str,
    primary: bool | float | int,
    placeholder: bool | float | int,
    constant: bool | float | int,
    trace_type: str,
    tmp_path: Path,
) -> None:
    library = PlantControlsLibrary()
    cases = [
        ({"have_inp": True, "have_inpPh": False}, {"u": primary}, primary),
        (
            {"have_inp": False, "have_inpPh": True},
            {"uPh": placeholder},
            placeholder,
        ),
        (
            {"have_inp": False, "have_inpPh": False, "u_internal": constant},
            {},
            constant,
        ),
    ]
    for case_index, (parameters, inputs, expected) in enumerate(cases):
        translation = library.translate(controller_id, parameters=parameters)
        assert translation["product_status"] == "exact_ir_stock_niagara"
        assert library.assess_niagara_source_target(translation) == {
            "complete": True,
            "delivery_mode": "qualified_stock_components",
            "generated_program_count": 0,
            "blocker": None,
        }
        execution = library.execute(
            controller_id,
            parameters=parameters,
            samples=[{"time": 0, "inputs": inputs}],
        )
        output_id = execution["interface"]["outputs"][0]["id"]
        assert execution["trace"]["trace"][0]["outputs"][output_id] == {
            "type": trace_type,
            "value": expected,
        }
        artifact = NiagaraCompiler().compile(
            ControlGraph.model_validate(translation["typed_ir"]),
            tmp_path / f"{controller_id.rsplit('.', 1)[-1]}-{case_index}.bog",
        )
        assert artifact.is_file()


def test_placeholder_utilities_require_and_type_only_the_selected_source() -> None:
    library = PlantControlsLibrary()
    with pytest.raises(
        G36RequiredParametersError,
        match="requires job parameter values.*u_internal",
    ):
        library.translate(
            "Utilities.PlaceholderReal",
            parameters={"have_inp": False, "have_inpPh": False},
        )
    with pytest.raises(ValueError, match="u_internal requires Integer"):
        library.translate(
            "Utilities.PlaceholderInteger",
            parameters={
                "have_inp": False,
                "have_inpPh": False,
                "u_internal": 1.5,
            },
        )
    with pytest.raises(ValueError, match="Boolean source-algorithm inputs"):
        library.execute(
            "Utilities.PlaceholderLogical",
            parameters={"have_inp": True},
            samples=[{"time": 0, "inputs": {"u": 1}}],
        )


@pytest.mark.parametrize(
    ("application", "return_temperature", "supply_setpoint", "polarity"),
    [
        ("Heating", 300.0, 310.0, 1.0),
        ("Cooling", 300.0, 290.0, -1.0),
    ],
)
def test_load_average_executes_heating_and_cooling_and_packages_moving_average(
    application: str,
    return_temperature: float,
    supply_setpoint: float,
    polarity: float,
) -> None:
    library = PlantControlsLibrary()
    parameters = {
        "typ": f"Buildings.Templates.Plants.Controls.Types.Application.{application}",
        "cp_default": 4.0,
        "rho_default": 2.0,
        "dtMea": 3.0,
    }
    translation = library.translate(
        "StagingRotation.LoadAverage",
        parameters=parameters,
    )

    assert translation["product_status"] == "exact_ir_generated_program_source"
    assert translation["engine_report"]["engine"] == "open-control-engine"
    grounding = translation["connection_normalization"]["compile_time_enum_grounding"]
    assert grounding["applied"] is True
    assert grounding["stripped_enum_parameters"][0]["label"] == "typ"
    resolved = {
        item["id"].rsplit(".", 1)[-1]: item["value"]
        for item in grounding["resolved_parameter_values"]
    }
    assert resolved == {"k": polarity, "delta": 3.0}
    assert library.assess_niagara_source_target(translation) == {
        "complete": True,
        "delivery_mode": "generated_program_source",
        "generated_program_count": 1,
        "blocker": None,
        "runtime_qualified": False,
        "licensed_workbench_compile_required": True,
    }

    execution = library.execute(
        "StagingRotation.LoadAverage",
        parameters=parameters,
        samples=[
            {
                "time": timestamp,
                "inputs": {
                    "TRet": return_temperature,
                    "TSupSet": supply_setpoint,
                    "V_flow": 1.5,
                },
            }
            for timestamp in range(6)
        ],
    )
    output_id = execution["interface"]["outputs"][0]["id"]
    values = [
        row["outputs"][output_id]["value"] for row in execution["trace"]["trace"]
    ]
    assert values == pytest.approx(
        [0.0, 119.88011988011989, 119.9400299850075, 120.0, 120.0, 120.0]
    )

    package, _ = library.niagara_program_package(
        "StagingRotation.LoadAverage",
        parameters=parameters,
    )
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert [program["behavior_kind"] for program in manifest["programs"]] == [
        "moving_average"
    ]


@pytest.mark.parametrize(
    ("connection", "actuator", "rows"),
    [
        (
            "Parallel",
            "TwoPosition",
            [
                (False, False, False),
                (True, False, False),
                (False, False, False),
                (False, True, False),
                (False, False, False),
            ],
        ),
        (
            "Series",
            "TwoPosition",
            [
                (True, True, True),
                (True, False, True),
                (True, True, True),
                (False, True, True),
                (True, True, True),
            ],
        ),
        (
            "Parallel",
            "Modulating",
            [
                (0.0, 0.0, 0.0),
                (0.1, 0.0, 0.0),
                (0.0, 0.0, 0.0),
                (0.0, 0.5, 0.0),
                (0.0, 0.0, 0.0),
            ],
        ),
        (
            "Series",
            "Modulating",
            [
                (1.0, 1.0, 1.0),
                (1.0, 0.98, 1.0),
                (1.0, 1.0, 1.0),
                (0.5, 1.0, 1.0),
                (0.99, 1.0, 1.0),
            ],
        ),
    ],
)
def test_lead_headered_pump_enable_executes_all_connection_and_valve_topologies(
    connection: str,
    actuator: str,
    rows: list[tuple[bool, bool, bool]] | list[tuple[float, float, float]],
) -> None:
    library = PlantControlsLibrary()
    namespace = "Buildings.Templates.Plants.Controls.Types"
    parameters = {
        "typCon": f"{namespace}.EquipmentConnection.{connection}",
        "typValIso": f"{namespace}.Actuator.{actuator}",
        "nValIso": 3,
    }
    translation = library.translate(
        "Pumps.Primary.EnableLeadHeadered",
        parameters=parameters,
    )

    assert translation["product_status"] == "exact_ir_generated_program_source"
    assert translation["engine_report"]["engine"] == "open-control-engine"
    pruning = translation["connection_normalization"]["conditional_pruning"]
    assert pruning["unresolved_guard_count"] == 0
    assert pruning["inactive_component_count"] in {6, 7}
    grounding = translation["connection_normalization"]["compile_time_enum_grounding"]
    assert {item["label"] for item in grounding["stripped_enum_parameters"]} == {
        "typCon",
        "typValIso",
    }
    assert library.assess_niagara_source_target(translation) == {
        "complete": True,
        "delivery_mode": "generated_program_source",
        "generated_program_count": 1,
        "blocker": None,
        "runtime_qualified": False,
        "licensed_workbench_compile_required": True,
    }

    prefix = "u1ValIso" if actuator == "TwoPosition" else "uValIso"
    execution = library.execute(
        "Pumps.Primary.EnableLeadHeadered",
        parameters=parameters,
        samples=[
            {
                "time": timestamp,
                "inputs": {
                    f"{prefix}__{index + 1}": value
                    for index, value in enumerate(row)
                },
            }
            for timestamp, row in enumerate(rows)
        ],
    )
    output_id = execution["interface"]["outputs"][0]["id"]
    assert [
        row["outputs"][output_id]["value"] for row in execution["trace"]["trace"]
    ] == [False, True, False, True, False]

    package, _ = library.niagara_program_package(
        "Pumps.Primary.EnableLeadHeadered",
        parameters=parameters,
    )
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert [program["behavior_kind"] for program in manifest["programs"]] == [
        "boolean_set_reset"
    ]


def test_stage_availability_exhausts_required_and_alternate_equipment_truth_table(
    tmp_path: Path,
) -> None:
    library = PlantControlsLibrary()
    matrix = [
        [1.0, 0.0, 0.0],
        [1.0, 0.5, 0.5],
        [1.0, 1.0, 1.0],
    ]
    parameters = {"staEqu": matrix}
    translation = library.translate(
        "StagingRotation.StageAvailability",
        parameters=parameters,
    )

    assert translation["product_status"] == "exact_ir_stock_niagara"
    assert translation["engine_report"]["engine"] == "bactalk-source-equation-lowering"
    assert library.assess_niagara_source_target(translation) == {
        "complete": True,
        "delivery_mode": "qualified_stock_components",
        "generated_program_count": 0,
        "blocker": None,
    }
    artifact = NiagaraCompiler().compile(
        ControlGraph.model_validate(translation["typed_ir"]),
        tmp_path / "stage-availability.bog",
    )
    with zipfile.ZipFile(artifact) as archive:
        xml = archive.read("file.xml")
    assert b"kitControl:NumericSwitch" in xml
    assert b"kitControl:GreaterThanEqual" in xml

    availability_vectors = [
        tuple(bool(mask & (1 << index)) for index in range(3)) for mask in range(8)
    ]
    execution = library.execute(
        "StagingRotation.StageAvailability",
        parameters=parameters,
        samples=[
            {
                "time": sample_index,
                "inputs": {
                    f"u1Ava__{index + 1}": value
                    for index, value in enumerate(availability)
                },
            }
            for sample_index, availability in enumerate(availability_vectors)
        ],
    )
    output_ids = {
        port["label"]: port["id"] for port in execution["interface"]["outputs"]
    }

    def expected(row: list[float], availability: tuple[bool, ...]) -> bool:
        fixed_available = all(
            coefficient <= 0.99 or availability[index]
            for index, coefficient in enumerate(row)
        )
        candidate_count = sum(
            coefficient > 0.0 and availability[index]
            for index, coefficient in enumerate(row)
        )
        return fixed_available and candidate_count >= round(sum(row))

    assert [
        [
            row["outputs"][output_ids[f"y1__{stage_index + 1}"]]["value"]
            for stage_index in range(len(matrix))
        ]
        for row in execution["trace"]["trace"]
    ] == [
        [expected(stage, availability) for stage in matrix]
        for availability in availability_vectors
    ]


@pytest.mark.parametrize(
    ("matrix", "message"),
    [
        ([[1.0, 0.25]], "row 1 must sum to an integer"),
        ([[1.0, 1.0], [1.0, 0.0]], "non-decreasing"),
        ([[1.0, True]], "finite Reals from 0 through 1"),
        ([[1.0, 1.1]], "finite Reals from 0 through 1"),
    ],
)
def test_stage_availability_rejects_invalid_staging_matrices(
    matrix: list[list[float | bool]],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        PlantControlsLibrary().translate(
            "StagingRotation.StageAvailability",
            parameters={"staEqu": matrix},
        )


def test_direct_initialization_and_resettable_timer_source_equations_package() -> None:
    library = PlantControlsLibrary()
    initialization = library.execute(
        "Utilities.Initialization",
        parameters={"yIni": False},
        samples=[
            {"time": 0, "inputs": {"u": True}},
            {"time": 1, "inputs": {"u": True}},
            {"time": 2, "inputs": {"u": False}},
        ],
    )
    initialization_output = initialization["interface"]["outputs"][0]["id"]
    assert [
        row["outputs"][initialization_output]["value"]
        for row in initialization["trace"]["trace"]
    ] == [False, True, False]

    timer = library.execute(
        "Utilities.TimerWithReset",
        parameters={"t": 3.0},
        samples=[
            {"time": 0, "inputs": {"u": True, "reset": False}},
            {"time": 3, "inputs": {"u": True, "reset": False}},
            {"time": 4, "inputs": {"u": True, "reset": True}},
        ],
    )
    output_ids = {port["label"]: port["id"] for port in timer["interface"]["outputs"]}
    assert [
        (
            row["outputs"][output_ids["y"]]["value"],
            row["outputs"][output_ids["passed"]]["value"],
        )
        for row in timer["trace"]["trace"]
    ] == [(0.0, False), (3.0, True), (0.0, False)]

    for controller_id, parameters, behavior in [
        ("Utilities.Initialization", {"yIni": False}, "boolean_initialization"),
        ("Utilities.TimerWithReset", {"t": 3.0}, "timer_with_reset"),
    ]:
        translation = library.translate(controller_id, parameters=parameters)
        assert translation["product_status"] == "exact_ir_generated_program_source"
        package, _ = library.niagara_program_package(
            controller_id,
            parameters=parameters,
        )
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        assert [program["behavior_kind"] for program in manifest["programs"]] == [
            behavior
        ]


def test_plant_controls_api_is_executable_and_downloadable(tmp_path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))

    catalog = client.get("/api/library/plant-controls/controllers")
    assert catalog.status_code == 200
    assert catalog.json()["proven_controller_count"] == 38

    translated = client.post(
        f"/api/library/plant-controls/controllers/{CONTROLLER}/translate"
    )
    assert translated.status_code == 200
    assert translated.json()["lowering"]["translatable"] is True

    template = client.post(
        f"/api/library/plant-controls/controllers/{CONTROLLER}/job-template",
        json={"parameters": {"dtHol": 3.0}},
    )
    assert template.status_code == 200, template.text
    assert [point["name"] for point in template.json()["points"]] == ["u", "u1", "y"]

    execution = client.post(
        f"/api/library/plant-controls/controllers/{CONTROLLER}/execute",
        json={"parameters": {"dtHol": 3.0}, "samples": SAMPLES},
    )
    assert execution.status_code == 200
    assert _values(execution.json()) == [10.0, 20.0, 20.0, 20.0, 50.0, 60.0]

    package = client.post(
        f"/api/library/plant-controls/controllers/{CONTROLLER}/niagara-program-package",
        json={"parameters": {"dtHol": 3.0}},
    )
    assert package.status_code == 200
    assert package.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        assert len(json.loads(archive.read("manifest.json"))["programs"]) == 2


def test_parameterized_plant_controller_fails_closed_until_job_values_are_supplied(
    tmp_path,
) -> None:
    client = TestClient(create_app(tmp_path / "runs"))

    response = client.post(
        "/api/library/plant-controls/controllers/Setpoints.PlantReset/translate"
    )

    assert response.status_code == 422
    assert "requires job parameter values" in response.json()["detail"]
