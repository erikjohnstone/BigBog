from __future__ import annotations

import io
import json
import zipfile

from bactalk.integrations.cxf_connections import normalize_connection_sets
from bactalk.integrations.g36_library import G36Library
from bactalk.integrations.plant_controls_library import PlantControlsLibrary


def _expanded_hold_oracle() -> list[float]:
    """Execute the pinned 44-block source, not BACTalk's composite lowering."""

    library = G36Library()
    library.g36_root = (
        library.modelica_root / "Buildings/Controls/OBC/ASHRAE/G36/Generic"
    ).resolve()
    _, document = library._source_document("TrimAndRespond")
    document, parameterization = library._apply_parameter_overrides(
        document,
        {
            "have_hol": True,
            "iniSet": 10.0,
            "minSet": 0.0,
            "maxSet": 20.0,
            "delTim": 0.0,
            "samplePeriod": 10.0,
            "numIgnReq": 2,
            "triAmo": 0.1,
            "resAmo": -0.2,
            "maxRes": -0.6,
            "dtHol": 25.0,
        },
    )
    if parameterization["remaining_required_parameters"]:
        raise RuntimeError("expanded hold oracle was not fully parameterized")
    document, _ = normalize_connection_sets(document)
    base = "http://example.org#Buildings.Controls.OBC.ASHRAE.G36.Generic.TrimAndRespond"
    output_id = f"{base}.y"
    trace = library.engine.simulate_document(
        document,
        samples=[
            {
                "time": timestamp,
                "inputs": {
                    f"{base}.numOfReq": 0,
                    f"{base}.uDevSta": True,
                    f"{base}.uHol": 25 <= timestamp < 35,
                },
            }
            for timestamp in range(0, 81, 5)
        ],
        collect=[output_id],
    )
    return [row["outputs"][output_id]["value"] for row in trace["trace"]]


def main() -> int:
    library = PlantControlsLibrary()
    catalog = library.catalog()
    controller_id = "Utilities.HoldReal"
    translation = library.translate(controller_id)
    target = library.assess_niagara_source_target(translation)
    samples = [
        {"time": 0, "inputs": {"u": 10.0, "u1": False}},
        {"time": 1, "inputs": {"u": 20.0, "u1": True}},
        {"time": 2, "inputs": {"u": 30.0, "u1": False}},
        {"time": 3, "inputs": {"u": 40.0, "u1": False}},
        {"time": 4, "inputs": {"u": 50.0, "u1": False}},
        {"time": 5, "inputs": {"u": 60.0, "u1": False}},
    ]
    execution = library.execute(
        controller_id,
        parameters={"dtHol": 3.0},
        samples=samples,
    )
    output_id = execution["interface"]["outputs"][0]["id"]
    actual = [
        row["outputs"][output_id]["value"] for row in execution["trace"]["trace"]
    ]
    expected = [10.0, 20.0, 20.0, 20.0, 50.0, 60.0]
    package, _ = library.niagara_program_package(
        controller_id,
        parameters={"dtHol": 3.0},
    )
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        graph = json.loads(archive.read("control-graph.json"))
        wiring = json.loads(archive.read("wiring-plan.json"))
    expanded_hold = _expanded_hold_oracle()
    expected_hold = [
        10.0,
        10.0,
        10.1,
        10.1,
        10.2,
        10.2,
        10.2,
        10.2,
        10.2,
        10.2,
        10.299999999999999,
        10.299999999999999,
        10.399999999999999,
        10.399999999999999,
        10.499999999999998,
        10.499999999999998,
        10.599999999999998,
    ]
    plant_parameters = {
        "nSenDpRem": 2,
        "dpSet_max": [100000.0, 120000.0],
        "TSup_nominal": 279.15,
        "TSupSetLim": 285.15,
        "dtDel": 0.001,
        "dtRes": 10.0,
        "dtHol": 25.0,
    }
    plant_reset = library.translate("Setpoints.PlantReset", parameters=plant_parameters)
    plant_target = library.assess_niagara_source_target(plant_reset)
    minimum_flow_parameters = {
        "nEqu": 3,
        "V_flow_nominal": [0.1, 0.2, 0.3],
        "V_flow_min": [0.02, 0.06, 0.09],
    }
    minimum_flow = library.translate(
        "MinimumFlow.Setpoint",
        parameters=minimum_flow_parameters,
    )
    minimum_execution = library.execute(
        "MinimumFlow.Setpoint",
        parameters=minimum_flow_parameters,
        samples=[
            {
                "time": 0,
                "inputs": {"u1__1": True, "u1__2": False, "u1__3": True},
            }
        ],
    )
    minimum_output_id = minimum_execution["interface"]["outputs"][0]["id"]
    minimum_flow_value = minimum_execution["trace"]["trace"][0]["outputs"][
        minimum_output_id
    ]["value"]
    minimum_controller_parameters = {
        **minimum_flow_parameters,
        "nEna": 2,
        "have_valInlIso": False,
        "have_valOutIso": False,
        "k": 1.0,
        "Ti": 1.0,
    }
    minimum_controller = library.translate(
        "MinimumFlow.Controller",
        parameters=minimum_controller_parameters,
    )
    minimum_controller_execution = library.execute(
        "MinimumFlow.Controller",
        parameters=minimum_controller_parameters,
        samples=[
            {
                "time": timestamp,
                "inputs": {
                    "VPri_flow": 0.3,
                    "u1Equ__1": True,
                    "u1Equ__2": False,
                    "u1Equ__3": True,
                    "u1PumPri_actual__1": timestamp > 0,
                    "u1PumPri_actual__2": False,
                },
            }
            for timestamp in range(4)
        ],
    )
    minimum_controller_outputs = {
        port["label"]: port["id"]
        for port in minimum_controller_execution["interface"]["outputs"]
    }
    minimum_controller_trajectory = [
        row["outputs"][minimum_controller_outputs["y"]]["value"]
        for row in minimum_controller_execution["trace"]["trace"]
    ]
    minimum_controller_setpoints = [
        row["outputs"][minimum_controller_outputs["VPriSet_flow"]]["value"]
        for row in minimum_controller_execution["trace"]["trace"]
    ]
    minimum_controller_target = library.assess_niagara_source_target(
        minimum_controller
    )
    dual_minimum_parameters = {
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
    dual_pump_states = [
        (False, False, False),
        (True, False, False),
        (True, False, False),
        (True, False, False),
        (False, True, False),
        (False, True, False),
        (False, True, False),
    ]
    dual_execution = library.execute(
        "MinimumFlow.ControllerDualMode",
        parameters=dual_minimum_parameters,
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
            for timestamp, states in enumerate(dual_pump_states)
        ],
    )
    dual_outputs = {
        port["label"]: port["id"] for port in dual_execution["interface"]["outputs"]
    }
    dual_trajectories = {
        name: [
            row["outputs"][dual_outputs[name]]["value"]
            for row in dual_execution["trace"]["trace"]
        ]
        for name in (
            "VHeaWatPriSet_flow",
            "VChiWatPriSet_flow",
            "yValHeaWatMinByp",
            "yValChiWatMinByp",
        )
    }
    dual_target = library.assess_niagara_source_target(
        library.translate(
            "MinimumFlow.ControllerDualMode",
            parameters=dual_minimum_parameters,
        )
    )
    differential_pressure_trajectories: dict[str, list[float]] = {}
    differential_pressure_program_counts: dict[str, int] = {}
    for remote in (False, True):
        differential_parameters = {
            "have_senDpRemWir": remote,
            "nPum": 2,
            "nSenDpRem": 2,
            "k": 1.0,
            "Ti": 10.0,
        }
        differential_samples = []
        for timestamp, statuses in enumerate(
            [(False, False), (True, False), (True, False),
             (False, False), (False, True), (False, True)]
        ):
            differential_inputs = {
                "y1_actual__1": statuses[0],
                "y1_actual__2": statuses[1],
            }
            if remote:
                differential_inputs.update(
                    {
                        "dpRemSet__1": 5000.0,
                        "dpRemSet__2": 7000.0,
                        "dpRem__1": 4000.0,
                        "dpRem__2": 6000.0,
                    }
                )
            else:
                differential_inputs.update(
                    {
                        "dpLocSet__1": 5000.0,
                        "dpLocSet__2": 7000.0,
                        "dpLoc": 6000.0,
                    }
                )
            differential_samples.append(
                {"time": timestamp, "inputs": differential_inputs}
            )
        differential_execution = library.execute(
            "Pumps.Generic.ControlDifferentialPressure",
            parameters=differential_parameters,
            samples=differential_samples,
            collect=["y"],
        )
        differential_output_id = differential_execution["interface"]["outputs"][-1][
            "id"
        ]
        topology = "remote" if remote else "local"
        differential_pressure_trajectories[topology] = [
            row["outputs"][differential_output_id]["value"]
            for row in differential_execution["trace"]["trace"]
        ]
        differential_translation = library.translate(
            "Pumps.Generic.ControlDifferentialPressure",
            parameters=differential_parameters,
        )
        differential_target = library.assess_niagara_source_target(
            differential_translation
        )
        differential_pressure_program_counts[topology] = differential_target[
            "generated_program_count"
        ]
    disable_parameters = {"have_reqFlo": False, "dtOff": 3.0}
    disable_translation = library.translate(
        "Pumps.Primary.DisableDedicated",
        parameters=disable_parameters,
    )
    disable_execution = library.execute(
        "Pumps.Primary.DisableDedicated",
        parameters=disable_parameters,
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
    disable_output_id = disable_execution["interface"]["outputs"][0]["id"]
    disable_trajectory = [
        row["outputs"][disable_output_id]["value"]
        for row in disable_execution["trace"]["trace"]
    ]
    disable_target = library.assess_niagara_source_target(disable_translation)
    failsafe_parameters = {
        "typ": "Buildings.Templates.Plants.Controls.Types.Application.Heating",
        "have_pumSec": False,
        "dT": 2.0,
        "dtPri": 3.0,
    }
    failsafe_translation = library.translate(
        "StagingRotation.FailsafeCondition",
        parameters=failsafe_parameters,
    )
    failsafe_execution = library.execute(
        "StagingRotation.FailsafeCondition",
        parameters=failsafe_parameters,
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
    failsafe_output_id = failsafe_execution["interface"]["outputs"][0]["id"]
    failsafe_trajectory = [
        row["outputs"][failsafe_output_id]["value"]
        for row in failsafe_execution["trace"]["trace"]
    ]
    failsafe_target = library.assess_niagara_source_target(failsafe_translation)
    first_true = library.execute(
        "Utilities.FirstTrueIndex",
        parameters={"nin": 4},
        samples=[
            {
                "time": 0,
                "inputs": {
                    "u1__1": False,
                    "u1__2": True,
                    "u1__3": False,
                    "u1__4": True,
                },
            }
        ],
    )
    first_true_output_id = first_true["interface"]["outputs"][0]["id"]
    first_true_value = first_true["trace"]["trace"][0]["outputs"][
        first_true_output_id
    ]["value"]
    integer_max = library.execute(
        "Utilities.MultiMaxInteger",
        parameters={"nin": 4},
        samples=[
            {
                "time": 0,
                "inputs": {"u__1": 2, "u__2": 9, "u__3": -1, "u__4": 5},
            }
        ],
    )
    integer_max_output_id = integer_max["interface"]["outputs"][0]["id"]
    integer_max_value = integer_max["trace"]["trace"][0]["outputs"][
        integer_max_output_id
    ]["value"]
    true_array = library.execute(
        "Utilities.TrueArrayConditional",
        parameters={"nin": 5, "nout": 4},
        samples=[
            {
                "time": 0,
                "inputs": {
                    "u": 3,
                    "uIdx__1": 0,
                    "uIdx__2": 4,
                    "uIdx__3": 4,
                    "uIdx__4": 9,
                    "uIdx__5": 2,
                },
            }
        ],
    )
    true_array_outputs = {
        port["label"]: port["id"] for port in true_array["interface"]["outputs"]
    }
    true_array_value = [
        true_array["trace"]["trace"][0]["outputs"][
            true_array_outputs[f"y1__{index}"]
        ]["value"]
        for index in range(1, 5)
    ]
    placeholder_values: dict[str, list[object]] = {}
    for placeholder_id, primary, alternate, constant in [
        ("Utilities.PlaceholderLogical", True, False, True),
        ("Utilities.PlaceholderReal", 12.5, -4.25, 7.75),
        ("Utilities.PlaceholderInteger", 12, -4, 7),
    ]:
        values = []
        for placeholder_parameters, placeholder_inputs in [
            ({"have_inp": True}, {"u": primary}),
            ({"have_inp": False, "have_inpPh": True}, {"uPh": alternate}),
            (
                {
                    "have_inp": False,
                    "have_inpPh": False,
                    "u_internal": constant,
                },
                {},
            ),
        ]:
            placeholder_execution = library.execute(
                placeholder_id,
                parameters=placeholder_parameters,
                samples=[{"time": 0, "inputs": placeholder_inputs}],
            )
            placeholder_output_id = placeholder_execution["interface"]["outputs"][0][
                "id"
            ]
            values.append(
                placeholder_execution["trace"]["trace"][0]["outputs"][
                    placeholder_output_id
                ]["value"]
            )
        placeholder_values[placeholder_id] = values
    load_average_values: dict[str, float] = {}
    for application, return_temperature, supply_setpoint in [
        ("Heating", 300.0, 310.0),
        ("Cooling", 300.0, 290.0),
    ]:
        load_parameters = {
            "typ": (
                "Buildings.Templates.Plants.Controls.Types.Application."
                + application
            ),
            "cp_default": 4.0,
            "rho_default": 2.0,
            "dtMea": 3.0,
        }
        load_execution = library.execute(
            "StagingRotation.LoadAverage",
            parameters=load_parameters,
            samples=[
                {
                    "time": timestamp,
                    "inputs": {
                        "TRet": return_temperature,
                        "TSupSet": supply_setpoint,
                        "V_flow": 1.5,
                    },
                }
                for timestamp in range(4)
            ],
        )
        load_output_id = load_execution["interface"]["outputs"][0]["id"]
        load_average_values[application] = load_execution["trace"]["trace"][-1][
            "outputs"
        ][load_output_id]["value"]
    load_translation = library.translate(
        "StagingRotation.LoadAverage",
        parameters={
            "typ": "Buildings.Templates.Plants.Controls.Types.Application.Heating",
            "cp_default": 4.0,
            "rho_default": 2.0,
            "dtMea": 3.0,
        },
    )
    load_target = library.assess_niagara_source_target(load_translation)
    lead_pump_trajectories: dict[str, list[bool]] = {}
    plant_types = "Buildings.Templates.Plants.Controls.Types"
    for connection, actuator, rows in [
        (
            "Parallel",
            "TwoPosition",
            [(False, False, False), (True, False, False), (False, False, False)],
        ),
        (
            "Series",
            "TwoPosition",
            [(True, True, True), (True, False, True), (True, True, True)],
        ),
        (
            "Parallel",
            "Modulating",
            [(0.0, 0.0, 0.0), (0.1, 0.0, 0.0), (0.0, 0.0, 0.0)],
        ),
        (
            "Series",
            "Modulating",
            [(1.0, 1.0, 1.0), (1.0, 0.98, 1.0), (0.99, 1.0, 1.0)],
        ),
    ]:
        lead_parameters = {
            "typCon": f"{plant_types}.EquipmentConnection.{connection}",
            "typValIso": f"{plant_types}.Actuator.{actuator}",
            "nValIso": 3,
        }
        prefix = "u1ValIso" if actuator == "TwoPosition" else "uValIso"
        lead_execution = library.execute(
            "Pumps.Primary.EnableLeadHeadered",
            parameters=lead_parameters,
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
        lead_output_id = lead_execution["interface"]["outputs"][0]["id"]
        lead_pump_trajectories[f"{connection}_{actuator}"] = [
            row["outputs"][lead_output_id]["value"]
            for row in lead_execution["trace"]["trace"]
        ]
    lead_translation = library.translate(
        "Pumps.Primary.EnableLeadHeadered",
        parameters={
            "typCon": f"{plant_types}.EquipmentConnection.Parallel",
            "typValIso": f"{plant_types}.Actuator.TwoPosition",
            "nValIso": 3,
        },
    )
    lead_target = library.assess_niagara_source_target(lead_translation)
    stage_matrix = [
        [1.0, 0.0, 0.0],
        [1.0, 0.5, 0.5],
        [1.0, 1.0, 1.0],
    ]
    stage_availability = library.execute(
        "StagingRotation.StageAvailability",
        parameters={"staEqu": stage_matrix},
        samples=[
            {
                "time": mask,
                "inputs": {
                    f"u1Ava__{index + 1}": bool(mask & (1 << index))
                    for index in range(3)
                },
            }
            for mask in range(8)
        ],
    )
    stage_output_ids = {
        port["label"]: port["id"]
        for port in stage_availability["interface"]["outputs"]
    }
    stage_availability_table = [
        [
            row["outputs"][stage_output_ids[f"y1__{index}"]]["value"]
            for index in range(1, 4)
        ]
        for row in stage_availability["trace"]["trace"]
    ]
    sort_runtime_parameters = {
        "nin": 4,
        "idxEquAlt": [2, 3, 4],
        "runTim_start": [2.0, 3.0, 4.0],
    }
    sort_runtime_rows = [
        (0, [False, False, False, False], [True, True, True, True]),
        (1, [False, False, False, True], [True, True, True, True]),
        (3, [False, False, False, True], [True, True, True, True]),
        (4, [False, True, False, True], [True, True, True, True]),
        (5, [False, True, False, True], [True, False, True, True]),
        (6, [False, True, False, True], [True, False, False, True]),
    ]
    sort_runtime_samples = []
    for timestamp, running, available in sort_runtime_rows:
        sort_inputs = {
            f"u1Run__{index}": value
            for index, value in enumerate(running, start=1)
        }
        sort_inputs.update(
            {
                f"u1Ava__{index}": value
                for index, value in enumerate(available, start=1)
            }
        )
        sort_runtime_samples.append({"time": timestamp, "inputs": sort_inputs})
    sort_runtime = library.execute(
        "StagingRotation.SortRuntime",
        parameters=sort_runtime_parameters,
        samples=sort_runtime_samples,
    )
    sort_runtime_outputs = {
        port["label"]: port["id"] for port in sort_runtime["interface"]["outputs"]
    }
    sort_runtime_order = [
        [
            row["outputs"][sort_runtime_outputs[f"yIdx__{rank}"]]["value"]
            for rank in range(1, 4)
        ]
        for row in sort_runtime["trace"]["trace"]
    ]
    sort_runtime_target = library.assess_niagara_source_target(
        library.translate(
            "StagingRotation.SortRuntime",
            parameters=sort_runtime_parameters,
        )
    )
    headered_delta_p_parameters = {
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
    headered_delta_p_trajectories: dict[str, list[tuple[bool, bool]]] = {}
    for mode in ("efficiency", "failsafe"):
        samples = []
        for timestamp in range(6):
            statuses = (
                [True, False, False] if timestamp < 3 else [True, True, False]
            )
            inputs: dict[str, bool | float] = {
                "V_flow": (
                    0.8
                    if mode == "failsafe"
                    else 1.5
                    if timestamp < 3
                    else 0.3
                ),
                "y": (
                    1.0
                    if mode == "failsafe" and timestamp < 3
                    else 0.2
                    if mode == "failsafe"
                    else 0.5
                ),
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
                        80.0
                        if mode == "failsafe" and timestamp < 3
                        else 100.0
                    )
                    for index in range(1, 3)
                }
            )
            inputs.update({f"dpSet__{index}": 100.0 for index in range(1, 3)})
            samples.append({"time": timestamp, "inputs": inputs})
        execution = library.execute(
            "Pumps.Generic.StagingHeaderedDeltaP",
            parameters=headered_delta_p_parameters,
            samples=samples,
        )
        outputs = {
            port["label"]: port["id"] for port in execution["interface"]["outputs"]
        }
        headered_delta_p_trajectories[mode] = [
            (
                row["outputs"][outputs["y1Up"]]["value"],
                row["outputs"][outputs["y1Dow"]]["value"],
            )
            for row in execution["trace"]["trace"]
        ]
    headered_delta_p_target = library.assess_niagara_source_target(
        library.translate(
            "Pumps.Generic.StagingHeaderedDeltaP",
            parameters=headered_delta_p_parameters,
        )
    )
    stage_change_parameters = {
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
    stage_change = library.execute(
        "StagingRotation.StageChangeCommand",
        parameters=stage_change_parameters,
        samples=[
            {
                "time": timestamp,
                "inputs": {
                    "uSta": 1 if timestamp < 4 else 2,
                    "u1StaPro": timestamp == 3,
                    "TRet": 0.0 if timestamp < 4 else 15.0,
                    "TSupSet": 20.0,
                    "V_flow": 10.0,
                    "TPriSup": 20.0,
                    "u1AvaSta__1": True,
                    "u1AvaSta__2": True,
                },
            }
            for timestamp in range(10)
        ],
    )
    stage_change_outputs = {
        port["label"]: port["id"] for port in stage_change["interface"]["outputs"]
    }
    stage_change_trajectory = [
        (
            row["outputs"][stage_change_outputs["y1Up"]]["value"],
            row["outputs"][stage_change_outputs["y1Dow"]]["value"],
        )
        for row in stage_change["trace"]["trace"]
    ]
    stage_change_target = library.assess_niagara_source_target(
        library.translate(
            "StagingRotation.StageChangeCommand",
            parameters=stage_change_parameters,
        )
    )
    headered_pump_parameters = {
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
    }
    headered_pump = library.execute(
        "Pumps.Generic.StagingHeadered",
        parameters=headered_pump_parameters,
        samples=[
            {
                "time": timestamp,
                "inputs": {
                    "u1Pum_actual__1": True,
                    "u1Pum_actual__2": timestamp >= 3,
                    "u1ValInlIso__1": timestamp < 5,
                    "u1ValInlIso__2": False,
                    "V_flow": 1.2 if timestamp < 3 else 0.3,
                    "y": 0.5,
                    "dp__1": 100.0,
                    "dpSet__1": 100.0,
                },
            }
            for timestamp in range(6)
        ],
    )
    headered_pump_outputs = {
        port["label"]: port["id"] for port in headered_pump["interface"]["outputs"]
    }
    headered_pump_trajectory = [
        [
            row["outputs"][headered_pump_outputs[f"y1__{pump}"]]["value"]
            for pump in range(1, 3)
        ]
        for row in headered_pump["trace"]["trace"]
    ]
    headered_pump_target = library.assess_niagara_source_target(
        library.translate(
            "Pumps.Generic.StagingHeadered",
            parameters=headered_pump_parameters,
        )
    )
    variable_speed_parameters = {
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
    variable_speed = library.execute(
        "Pumps.Primary.VariableSpeed",
        parameters=variable_speed_parameters,
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
    variable_speed_outputs = {
        port["label"]: port["id"] for port in variable_speed["interface"]["outputs"]
    }
    variable_speed_trajectory = [
        row["outputs"][variable_speed_outputs["yPumHeaWatPriDed__1"]]["value"]
        for row in variable_speed["trace"]["trace"]
    ]
    variable_speed_target = library.assess_niagara_source_target(
        library.translate(
            "Pumps.Primary.VariableSpeed",
            parameters=variable_speed_parameters,
        )
    )
    air_to_water_parameters = {
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
    air_to_water = library.execute(
        "HeatPumps.AirToWater",
        parameters=air_to_water_parameters,
        samples=[
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
            for timestamp in range(8)
        ],
    )
    air_to_water_outputs = {
        port["label"]: port["id"] for port in air_to_water["interface"]["outputs"]
    }
    air_to_water_pump_trajectory = [
        row["outputs"][air_to_water_outputs["y1PumHeaWatPri__1"]]["value"]
        for row in air_to_water["trace"]["trace"]
    ]
    air_to_water_equipment_trajectory = [
        row["outputs"][air_to_water_outputs["y1Hp__1"]]["value"]
        for row in air_to_water["trace"]["trace"]
    ]
    air_to_water_target = library.assess_niagara_source_target(
        library.translate(
            "HeatPumps.AirToWater",
            parameters=air_to_water_parameters,
        )
    )
    equipment_enable_rows = [
        (0, [2, 3], [True, True, True]),
        (1, [2, 3], [True, True, True]),
        (2, [2, 3], [True, True, True]),
        (2, [3, 2], [True, True, True]),
        (2, [3, 2], [True, False, True]),
        (2, [3, 2], [True, False, True]),
        (3, [3, 2], [True, True, True]),
    ]
    equipment_enable_samples = []
    for timestamp, (stage, order, availability) in enumerate(equipment_enable_rows):
        equipment_enable_inputs: dict[str, int | bool] = {"uSta": stage}
        equipment_enable_inputs.update(
            {
                f"uIdxAltSor__{rank}": equipment
                for rank, equipment in enumerate(order, start=1)
            }
        )
        equipment_enable_inputs.update(
            {
                f"u1Ava__{equipment}": available
                for equipment, available in enumerate(availability, start=1)
            }
        )
        equipment_enable_samples.append(
            {"time": timestamp, "inputs": equipment_enable_inputs}
        )
    equipment_enable = library.execute(
        "StagingRotation.EquipmentEnable",
        parameters={"staEqu": stage_matrix},
        samples=equipment_enable_samples,
    )
    equipment_enable_outputs = {
        port["label"]: port["id"] for port in equipment_enable["interface"]["outputs"]
    }
    equipment_enable_trajectory = [
        [
            row["outputs"][equipment_enable_outputs[f"y1__{equipment}"]]["value"]
            for equipment in range(1, 4)
        ]
        for row in equipment_enable["trace"]["trace"]
    ]
    equipment_enable_target = library.assess_niagara_source_target(
        library.translate(
            "StagingRotation.EquipmentEnable",
            parameters={"staEqu": stage_matrix},
        )
    )
    equipment_availability_parameters = {
        "have_heaWat": True,
        "have_chiWat": True,
        "dtOff": 3.0,
    }
    equipment_availability_inputs = [
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
    equipment_availability = library.execute(
        "StagingRotation.EquipmentAvailability",
        parameters=equipment_availability_parameters,
        samples=[
            {
                "time": timestamp,
                "inputs": {
                    "u1EnaHea": heating,
                    "u1EnaCoo": cooling,
                    "u1Ava": available,
                },
            }
            for timestamp, (heating, cooling, available) in enumerate(
                equipment_availability_inputs
            )
        ],
    )
    equipment_availability_outputs = {
        port["label"]: port["id"]
        for port in equipment_availability["interface"]["outputs"]
    }
    equipment_availability_trajectories = {
        name: [
            row["outputs"][equipment_availability_outputs[name]]["value"]
            for row in equipment_availability["trace"]["trace"]
        ]
        for name in ("y1Hea", "y1Coo")
    }
    equipment_availability_target = library.assess_niagara_source_target(
        library.translate(
            "StagingRotation.EquipmentAvailability",
            parameters=equipment_availability_parameters,
        )
    )
    plant_enable_parameters = {
        "typ": "Buildings.Templates.Plants.Controls.Types.Application.Heating",
        "have_inpSch": True,
        "TOutLck": 290.0,
        "dTOutLck": 1.0,
        "nReqIgn": 0,
        "dtRun": 2.0,
        "dtReq": 2.0,
    }
    plant_enable_regimes = [
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
    plant_enable = library.execute(
        "Enabling.Enable",
        parameters=plant_enable_parameters,
        samples=[
            {
                "time": timestamp,
                "inputs": {"u1Sch": schedule, "nReqPla": requests, "TOut": oat},
            }
            for timestamp, (schedule, requests, oat) in enumerate(
                plant_enable_regimes
            )
        ],
    )
    plant_enable_output = plant_enable["interface"]["outputs"][0]["id"]
    plant_enable_trajectory = [
        row["outputs"][plant_enable_output]["value"]
        for row in plant_enable["trace"]["trace"]
    ]
    plant_enable_target = library.assess_niagara_source_target(
        library.translate("Enabling.Enable", parameters=plant_enable_parameters)
    )
    hrc_enable_parameters = {
        "TChiWatSup_min": 280.0,
        "THeaWatSup_max": 330.0,
        "capCoo_min": 10.0,
        "capHea_min": 10.0,
        "dtRun": 2.0,
        "dtLoa": 2.0,
        "dtTem1": 2.0,
        "dtTem2": 1.0,
    }
    hrc_enable = library.execute(
        "HeatRecoveryChillers.Enable",
        parameters=hrc_enable_parameters,
        samples=[
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
        ],
    )
    hrc_enable_outputs = {
        port["label"]: port["id"] for port in hrc_enable["interface"]["outputs"]
    }
    hrc_enable_trajectories = {
        name: [
            row["outputs"][hrc_enable_outputs[name]]["value"]
            for row in hrc_enable["trace"]["trace"]
        ]
        for name in ("y1", "y1SetMod")
    }
    hrc_enable_target = library.assess_niagara_source_target(
        library.translate(
            "HeatRecoveryChillers.Enable",
            parameters=hrc_enable_parameters,
        )
    )
    hrc_controller_parameters = {
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
    }
    hrc_controller = library.execute(
        "HeatRecoveryChillers.Controller",
        parameters=hrc_controller_parameters,
        samples=[
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
        ],
    )
    hrc_controller_outputs = {
        port["label"]: port["id"]
        for port in hrc_controller["interface"]["outputs"]
    }
    hrc_controller_trajectories = {
        name: [
            row["outputs"][hrc_controller_outputs[name]]["value"]
            for row in hrc_controller["trace"]["trace"]
        ]
        for name in ("y1", "y1Coo", "y1PumChiWat", "y1PumHeaWat", "TSupSet")
    }
    hrc_controller_target = library.assess_niagara_source_target(
        library.translate(
            "HeatRecoveryChillers.Controller",
            parameters=hrc_controller_parameters,
        )
    )
    hrc_mode_parameters = {"COPHea_nominal": 4.0}
    hrc_mode_regimes = [
        (False, 10.0, 100.0, 280.0, 320.0),
        (True, 10.0, 100.0, 280.0, 320.0),
        (False, 100.0, 100.0, 280.0, 320.0),
        (True, 100.0, 100.0, 280.0, 320.0),
        (False, 74.5, 100.0, 281.0, 321.0),
        (True, 75.5, 100.0, 281.0, 321.0),
        (True, 76.0, 100.0, 281.0, 321.0),
    ]
    hrc_mode = library.execute(
        "HeatRecoveryChillers.ModeControl",
        parameters=hrc_mode_parameters,
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
            ) in enumerate(hrc_mode_regimes)
        ],
    )
    hrc_mode_outputs = {
        port["label"]: port["id"] for port in hrc_mode["interface"]["outputs"]
    }
    hrc_mode_trajectories = {
        name: [
            row["outputs"][hrc_mode_outputs[name]]["value"]
            for row in hrc_mode["trace"]["trace"]
        ]
        for name in ("y1Coo", "TSupSet")
    }
    hrc_mode_target = library.assess_niagara_source_target(
        library.translate(
            "HeatRecoveryChillers.ModeControl",
            parameters=hrc_mode_parameters,
        )
    )
    stage_index_rows = [
        (0, False, False, False, [True, False, True, True]),
        (1, True, False, False, [True, False, True, True]),
        (2, True, True, False, [True, False, True, True]),
        (4, True, True, False, [True, False, True, True]),
        (5, True, False, False, [True, False, False, True]),
        (6, True, False, True, [True, False, False, True]),
        (8, True, False, True, [True, False, False, True]),
        (9, False, False, False, [True, False, False, True]),
        (11, False, False, False, [True, False, False, True]),
    ]
    stage_index_samples = []
    for timestamp, lead, up, down, availability in stage_index_rows:
        stage_index_inputs = {"u1Lea": lead, "u1Up": up, "u1Dow": down}
        stage_index_inputs.update(
            {
                f"u1AvaSta__{stage}": available
                for stage, available in enumerate(availability, start=1)
            }
        )
        stage_index_samples.append(
            {"time": timestamp, "inputs": stage_index_inputs}
        )
    stage_index = library.execute(
        "Utilities.StageIndex",
        parameters={"nSta": 4, "dtRun": 3.0, "have_inpAva": True},
        samples=stage_index_samples,
    )
    stage_index_output = stage_index["interface"]["outputs"][0]["id"]
    stage_index_trajectory = [
        row["outputs"][stage_index_output]["value"]
        for row in stage_index["trace"]["trace"]
    ]
    stage_index_target = library.assess_niagara_source_target(
        library.translate(
            "Utilities.StageIndex",
            parameters={"nSta": 4, "dtRun": 3.0, "have_inpAva": True},
        )
    )
    stage_completion_rows = [
        (0, [False, False, False], [False, False, False]),
        (1, [True, True, False], [False, False, False]),
        (1, [True, True, False], [False, False, False]),
        (1, [True, True, False], [True, False, False]),
        (1, [True, True, False], [True, True, False]),
        (1, [True, True, False], [True, True, False]),
    ]
    stage_completion_samples = []
    for timestamp, (stage, commands, statuses) in enumerate(stage_completion_rows):
        stage_inputs: dict[str, int | bool] = {"uSta": stage}
        stage_inputs.update(
            {f"u1__{index}": value for index, value in enumerate(commands, start=1)}
        )
        stage_inputs.update(
            {
                f"u1_actual__{index}": value
                for index, value in enumerate(statuses, start=1)
            }
        )
        stage_completion_samples.append({"time": timestamp, "inputs": stage_inputs})
    stage_completion = library.execute(
        "StagingRotation.StageCompletion",
        parameters={"nin": 3},
        samples=stage_completion_samples,
    )
    stage_completion_outputs = {
        port["label"]: port["id"]
        for port in stage_completion["interface"]["outputs"]
    }
    stage_completion_trajectories = {
        name: [
            row["outputs"][stage_completion_outputs[name]]["value"]
            for row in stage_completion["trace"]["trace"]
        ]
        for name in ("y1", "y1End")
    }
    stage_completion_target = library.assess_niagara_source_target(
        library.translate(
            "StagingRotation.StageCompletion",
            parameters={"nin": 3},
        )
    )
    event_parameters = {
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
    event_execution = library.execute(
        "StagingRotation.EventSequencing",
        parameters=event_parameters,
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
    event_outputs = {
        port["label"]: port["id"] for port in event_execution["interface"]["outputs"]
    }
    event_enable_trajectory = [
        row["outputs"][event_outputs["y1"]]["value"]
        for row in event_execution["trace"]["trace"]
    ]
    event_valve_trajectory = [
        row["outputs"][event_outputs["y1ValHeaWatInlIso"]]["value"]
        for row in event_execution["trace"]["trace"]
    ]
    event_target = library.assess_niagara_source_target(
        library.translate(
            "StagingRotation.EventSequencing",
            parameters=event_parameters,
        )
    )
    passed = all(
        (
            catalog["production_control_model_count"] == 38,
            catalog["proven_controller_count"] == 38,
            translation["lowering"]["translatable"] is True,
            translation["engine_report"]["engine"] == "open-control-engine",
            target["complete"] is True,
            target["generated_program_count"] == 2,
            actual == expected,
            len(manifest["programs"]) == 2,
            len(wiring["links"]) == len(graph["links"]),
            expanded_hold == expected_hold,
            plant_reset["lowering"]["translatable"] is True,
            plant_target["complete"] is True,
            plant_target["generated_program_count"] == 1,
            minimum_flow["lowering"]["niagara_translatable"] is True,
            minimum_flow_value == 0.12,
            minimum_controller_setpoints == [0.12, 0.12, 0.12, 0.12],
            minimum_controller_trajectory == [1.0, 1.0, 1.0, 0.8200000000000001],
            minimum_controller_target["complete"] is True,
            minimum_controller_target["generated_program_count"] == 1,
            dual_trajectories["VHeaWatPriSet_flow"] == [0.12] * 7,
            dual_trajectories["VChiWatPriSet_flow"] == [0.04] * 7,
            dual_trajectories["yValHeaWatMinByp"]
            == [1.0, 1.0, 1.0, 0.8200000000000001, 1.0, 1.0, 1.0],
            dual_trajectories["yValChiWatMinByp"]
            == [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.94],
            dual_target["complete"] is True,
            dual_target["generated_program_count"] == 2,
            all(
                trajectory == [0.0, 0.1, 0.1, 0.0, 0.1, 0.1]
                for trajectory in differential_pressure_trajectories.values()
            ),
            differential_pressure_program_counts == {"local": 1, "remote": 2},
            disable_translation["engine_report"]["engine"]
            == "bactalk-reviewed-composite-lowering",
            disable_trajectory == [True, True, True, True, False, False, False],
            disable_target["complete"] is True,
            disable_target["generated_program_count"] == 3,
            failsafe_translation["lowering"]["translatable"] is True,
            failsafe_trajectory == [False, False, False, False, True, False],
            failsafe_target["complete"] is True,
            failsafe_target["generated_program_count"] == 1,
            first_true_value == 2,
            integer_max_value == 9,
            true_array_value == [False, True, False, True],
            placeholder_values
            == {
                "Utilities.PlaceholderLogical": [True, False, True],
                "Utilities.PlaceholderReal": [12.5, -4.25, 7.75],
                "Utilities.PlaceholderInteger": [12, -4, 7],
            },
            load_average_values == {"Heating": 120.0, "Cooling": 120.0},
            load_target["complete"] is True,
            load_target["generated_program_count"] == 1,
            all(
                trajectory == [False, True, False]
                for trajectory in lead_pump_trajectories.values()
            ),
            len(lead_pump_trajectories) == 4,
            lead_target["complete"] is True,
            lead_target["generated_program_count"] == 1,
            stage_availability_table
            == [
                [False, False, False],
                [True, False, False],
                [False, False, False],
                [True, True, False],
                [False, False, False],
                [True, True, False],
                [False, False, False],
                [True, True, True],
            ],
            sort_runtime_order
            == [
                [2, 3, 4],
                [4, 2, 3],
                [4, 2, 3],
                [2, 4, 3],
                [4, 3, 2],
                [4, 2, 3],
            ],
            sort_runtime_target["complete"] is True,
            sort_runtime_target["generated_program_count"] == 9,
            all(
                trajectory
                == [
                    (False, False),
                    (False, False),
                    (True, False),
                    (False, False),
                    (False, False),
                    (False, True),
                ]
                for trajectory in headered_delta_p_trajectories.values()
            ),
            set(headered_delta_p_trajectories) == {"efficiency", "failsafe"},
            headered_delta_p_target["complete"] is True,
            headered_delta_p_target["generated_program_count"] == 15,
            stage_change_trajectory
            == [
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
            ],
            stage_change_target["complete"] is True,
            stage_change_target["generated_program_count"] == 9,
            headered_pump_trajectory
            == [
                [True, False],
                [True, False],
                [True, True],
                [True, True],
                [True, True],
                [False, False],
            ],
            headered_pump_target["complete"] is True,
            headered_pump_target["generated_program_count"] == 23,
            variable_speed_trajectory == [0.0, 0.8, 0.8, 0.0, 0.6],
            variable_speed_target["complete"] is True,
            variable_speed_target["generated_program_count"] == 4,
            air_to_water_pump_trajectory
            == [False, False, True, True, True, True, True, True],
            air_to_water_equipment_trajectory
            == [False, False, False, False, False, True, True, True],
            air_to_water_target["complete"] is True,
            air_to_water_target["generated_program_count"] == 59,
            equipment_enable_trajectory
            == [
                [False, False, False],
                [True, False, False],
                [True, True, False],
                [True, True, False],
                [True, False, True],
                [True, False, True],
                [True, True, True],
            ],
            equipment_enable_target["complete"] is True,
            equipment_enable_target["generated_program_count"] == 4,
            equipment_availability_trajectories["y1Hea"]
            == [True, True, True, False, False, False, False, False, False, False],
            equipment_availability_trajectories["y1Coo"]
            == [True, False, False, False, False, False, True, True, False, True],
            equipment_availability_target["complete"] is True,
            equipment_availability_target["generated_program_count"] == 1,
            plant_enable_trajectory
            == [
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
            ],
            plant_enable_target["complete"] is True,
            plant_enable_target["generated_program_count"] == 1,
            hrc_enable_trajectories["y1"]
            == [
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
            ],
            hrc_enable_trajectories["y1SetMod"]
            == [
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
            ],
            hrc_enable_target["complete"] is True,
            hrc_enable_target["generated_program_count"] == 1,
            hrc_controller_trajectories["y1"]
            == [False] * 8 + [True, True] + [False] * 3,
            hrc_controller_trajectories["y1Coo"]
            == [False] * 3 + [True] * 10,
            hrc_controller_trajectories["TSupSet"]
            == [320.0] * 3 + [280.0] * 10,
            hrc_controller_trajectories["y1PumChiWat"]
            == [False] * 8 + [True, True, True, False, False],
            hrc_controller_trajectories["y1PumHeaWat"]
            == [False] * 8 + [True, True, True, True, False],
            hrc_controller_target["complete"] is True,
            hrc_controller_target["generated_program_count"] == 11,
            hrc_mode_trajectories["y1Coo"]
            == [False, True, True, False, False, True, False],
            hrc_mode_trajectories["TSupSet"]
            == [320.0, 280.0, 280.0, 320.0, 321.0, 281.0, 321.0],
            hrc_mode_target["complete"] is True,
            hrc_mode_target["generated_program_count"] == 1,
            stage_index_trajectory == [0, 1, 1, 3, 4, 4, 1, 1, 0],
            stage_index_target["complete"] is True,
            stage_index_target["generated_program_count"] == 1,
            stage_completion_trajectories["y1"]
            == [False, True, True, True, False, False],
            stage_completion_trajectories["y1End"]
            == [False, False, False, False, True, False],
            stage_completion_target["complete"] is True,
            stage_completion_target["generated_program_count"] == 1,
            event_enable_trajectory
            == [False, False, False, True, True, False, False, False, False, False],
            event_valve_trajectory
            == [False, True, True, True, True, True, True, True, False, False],
            event_target["complete"] is True,
            event_target["generated_program_count"] == 4,
        )
    )
    print(
        json.dumps(
            {
                "schema": "bactalk.plant-controls-contract/v1",
                "passed": passed,
                "source_model_count": catalog["source_model_count"],
                "production_control_model_count": catalog[
                    "production_control_model_count"
                ],
                "proven_controller_count": catalog["proven_controller_count"],
                "headered_delta_p_trajectories": headered_delta_p_trajectories,
                "headered_delta_p_generated_program_count": (
                    headered_delta_p_target["generated_program_count"]
                ),
                "stage_change_trajectory": stage_change_trajectory,
                "stage_change_generated_program_count": stage_change_target[
                    "generated_program_count"
                ],
                "headered_pump_trajectory": headered_pump_trajectory,
                "headered_pump_generated_program_count": headered_pump_target[
                    "generated_program_count"
                ],
                "variable_speed_trajectory": variable_speed_trajectory,
                "variable_speed_generated_program_count": variable_speed_target[
                    "generated_program_count"
                ],
                "air_to_water_pump_trajectory": air_to_water_pump_trajectory,
                "air_to_water_equipment_trajectory": (
                    air_to_water_equipment_trajectory
                ),
                "air_to_water_generated_program_count": air_to_water_target[
                    "generated_program_count"
                ],
                "controller": controller_id,
                "runtime": execution["runtime"],
                "expected_trajectory": expected,
                "actual_trajectory": actual,
                "generated_program_count": len(manifest["programs"]),
                "graph_block_count": len(graph["blocks"]),
                "graph_link_count": len(graph["links"]),
                "expanded_hold_oracle_block_count": 44,
                "expanded_hold_oracle_trajectory": expanded_hold,
                "plant_reset_generated_program_count": plant_target[
                    "generated_program_count"
                ],
                "minimum_flow_value": minimum_flow_value,
                "minimum_flow_controller_setpoints": minimum_controller_setpoints,
                "minimum_flow_controller_trajectory": minimum_controller_trajectory,
                "minimum_flow_controller_generated_program_count": (
                    minimum_controller_target["generated_program_count"]
                ),
                "dual_minimum_flow_trajectories": dual_trajectories,
                "dual_minimum_flow_generated_program_count": dual_target[
                    "generated_program_count"
                ],
                "minimum_flow_stock_niagara_target": minimum_flow["lowering"][
                    "niagara_translatable"
                ],
                "differential_pressure_trajectories": (
                    differential_pressure_trajectories
                ),
                "differential_pressure_generated_program_counts": (
                    differential_pressure_program_counts
                ),
                "dedicated_primary_pump_disable_trajectory": disable_trajectory,
                "dedicated_primary_pump_generated_program_count": disable_target[
                    "generated_program_count"
                ],
                "staging_failsafe_trajectory": failsafe_trajectory,
                "staging_failsafe_generated_program_count": failsafe_target[
                    "generated_program_count"
                ],
                "first_true_index_value": first_true_value,
                "integer_max_value": integer_max_value,
                "true_array_conditional_value": true_array_value,
                "placeholder_branch_values": placeholder_values,
                "load_average_values": load_average_values,
                "load_average_generated_program_count": load_target[
                    "generated_program_count"
                ],
                "lead_headered_pump_trajectories": lead_pump_trajectories,
                "lead_headered_pump_generated_program_count": lead_target[
                    "generated_program_count"
                ],
                "stage_availability_truth_table": stage_availability_table,
                "sort_runtime_order": sort_runtime_order,
                "sort_runtime_generated_program_count": sort_runtime_target[
                    "generated_program_count"
                ],
                "equipment_enable_trajectory": equipment_enable_trajectory,
                "equipment_enable_generated_program_count": (
                    equipment_enable_target["generated_program_count"]
                ),
                "equipment_availability_trajectories": (
                    equipment_availability_trajectories
                ),
                "equipment_availability_generated_program_count": (
                    equipment_availability_target["generated_program_count"]
                ),
                "plant_enable_trajectory": plant_enable_trajectory,
                "plant_enable_generated_program_count": plant_enable_target[
                    "generated_program_count"
                ],
                "hrc_enable_trajectories": hrc_enable_trajectories,
                "hrc_enable_generated_program_count": hrc_enable_target[
                    "generated_program_count"
                ],
                "hrc_controller_trajectories": hrc_controller_trajectories,
                "hrc_controller_generated_program_count": hrc_controller_target[
                    "generated_program_count"
                ],
                "hrc_mode_trajectories": hrc_mode_trajectories,
                "hrc_mode_generated_program_count": hrc_mode_target[
                    "generated_program_count"
                ],
                "stage_index_trajectory": stage_index_trajectory,
                "stage_index_generated_program_count": stage_index_target[
                    "generated_program_count"
                ],
                "stage_completion_trajectories": stage_completion_trajectories,
                "stage_completion_generated_program_count": (
                    stage_completion_target["generated_program_count"]
                ),
                "event_sequencing_enable_trajectory": event_enable_trajectory,
                "event_sequencing_valve_trajectory": event_valve_trajectory,
                "event_sequencing_generated_program_count": event_target[
                    "generated_program_count"
                ],
                "licensed_niagara_runtime_qualified": False,
            },
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
