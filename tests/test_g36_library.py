from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bactalk.api import create_app
from bactalk.compiler import NiagaraCompiler
from bactalk.domain import BlockKind, ControlGraph
from bactalk.integrations.environment_pack import EnvironmentPackManifest
from bactalk.integrations.g36_library import G36Library
from bactalk.simulator import GraphInterpreter

CONTROLLER = "AHUs.MultiZone.VAV.SetPoints.SupplySignals"

EXPANDED_CONTROLLERS = {
    "AHUs.MultiZone.VAV.SetPoints.ReliefFan": {
        "blocks": 32,
        "niagara_translatable": False,
        "niagara_unsupported": {
            "Buildings.Controls.OBC.CDL.Logical.Latch",
            "Buildings.Controls.OBC.CDL.Logical.Timer",
            "Buildings.Controls.OBC.CDL.Reals.MovingAverage",
            "Buildings.Controls.OBC.CDL.Reals.PID",
        },
    },
    "AHUs.SingleZone.VAV.SetPoints.PlantRequests": {
        "blocks": 51,
        "niagara_translatable": False,
        "niagara_unsupported": {
            "Buildings.Controls.OBC.CDL.Logical.Latch",
        },
    },
    "FanCoilUnits.Subsequences.PlantRequests": {
        "blocks": 49,
        "niagara_translatable": False,
        "niagara_unsupported": {
            "Buildings.Controls.OBC.CDL.Reals.Hysteresis",
        },
    },
    "TerminalUnits.ParallelFanVVF.Subsequences.Overrides": {
        "blocks": 34,
        "niagara_translatable": True,
        "niagara_unsupported": set(),
    },
}


def _exact_pid_environment() -> EnvironmentPackManifest:
    return EnvironmentPackManifest.model_validate(
        {
            "id": "exact-g36-runtime",
            "name": "Exact G36 Niagara Runtime",
            "version": "1.0",
            "niagara_version": "4.14",
            "modules": [
                {
                    "name": "exactG36",
                    "version": "1.0",
                    "vendor": "Contractor",
                    "preferred_symbol": "g36",
                    "runtime_profiles": ["rt", "wb"],
                    "artifact": "modules/exactG36.jar",
                    "sha256": "0" * 64,
                    "redistribution": "shop_supplied_only",
                }
            ],
            "palettes": [
                {
                    "id": "exact-g36",
                    "module": "exactG36",
                    "resource": "module://exactG36/palette/exact.palette",
                    "components": [
                        {
                            "type_spec": "exactG36:PIDWithReset",
                            "behavior_kind": "pid_with_reset",
                            "inputs": {
                                "setpoint": {
                                    "niagara_slot": "u_s",
                                    "data_type": "numeric",
                                },
                                "measurement": {
                                    "niagara_slot": "u_m",
                                    "data_type": "numeric",
                                },
                                "trigger": {
                                    "niagara_slot": "trigger",
                                    "data_type": "boolean",
                                },
                            },
                            "outputs": {"out": {"niagara_slot": "y", "data_type": "numeric"}},
                            "config_properties": {
                                "controller_type": "controllerType",
                                "k": "k",
                                "ti": "Ti",
                                "td": "Td",
                                "r": "r",
                                "ni": "Ni",
                                "nd": "Nd",
                                "y_min": "yMin",
                                "y_max": "yMax",
                                "xi_start": "xiStart",
                                "yd_start": "ydStart",
                                "y_reset": "yReset",
                                "reverse_acting": "reverseActing",
                            },
                        }
                    ],
                }
            ],
        }
    )


def _trim_respond_environment() -> EnvironmentPackManifest:
    return EnvironmentPackManifest.model_validate(
        {
            "id": "exact-trim-respond-runtime",
            "name": "Exact G36 Trim and Respond Runtime",
            "version": "1.0",
            "niagara_version": "4.14",
            "modules": [
                {
                    "name": "exactG36",
                    "version": "1.0",
                    "vendor": "Contractor",
                    "preferred_symbol": "g36",
                    "runtime_profiles": ["rt", "wb"],
                    "artifact": "modules/exactG36.jar",
                    "sha256": "0" * 64,
                    "redistribution": "shop_supplied_only",
                }
            ],
            "palettes": [
                {
                    "id": "exact-g36",
                    "module": "exactG36",
                    "resource": "module://exactG36/palette/exact.palette",
                    "components": [
                        {
                            "type_spec": "exactG36:TrimAndRespond",
                            "behavior_kind": "trim_and_respond",
                            "inputs": {
                                "request_count": {
                                    "niagara_slot": "numOfReq",
                                    "data_type": "numeric",
                                },
                                "device_on": {
                                    "niagara_slot": "uDevSta",
                                    "data_type": "boolean",
                                },
                            },
                            "outputs": {"out": {"niagara_slot": "y", "data_type": "numeric"}},
                            "config_properties": {
                                "initial_setpoint": "iniSet",
                                "minimum_setpoint": "minSet",
                                "maximum_setpoint": "maxSet",
                                "delay_seconds": "delTim",
                                "sample_period_seconds": "samplePeriod",
                                "ignored_requests": "numIgnReq",
                                "trim_amount": "triAmo",
                                "respond_amount": "resAmo",
                                "maximum_response": "maxRes",
                                "hold_enabled": "haveHol",
                            },
                        }
                    ],
                }
            ],
        }
    )


def test_g36_catalog_exposes_allowlisted_equipment_families() -> None:
    catalog = G36Library().catalog()

    assert catalog["controller_count"] == 241
    assert catalog["non_validation_controller_count"] > 100
    assert catalog["family_counts"] == {
        "AHUs": 84,
        "FanCoilUnits": 8,
        "Generic": 7,
        "TerminalUnits": 120,
        "ThermalZones": 8,
        "VentilationZones": 4,
        "ZoneGroups": 10,
    }
    selected = next(item for item in catalog["controllers"] if item["id"] == CONTROLLER)
    assert selected["relative_path"].endswith("SupplySignals.mo")
    assert selected["validation_fixture"] is False
    assert len(selected["source_sha256"]) == 64
    assert catalog["niagara_lowering_complete"] is False


def test_g36_translation_api_runs_modelica_json_and_oce(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))

    response = client.post(f"/api/library/g36/controllers/{CONTROLLER}/translate")

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["controller"]["id"] == CONTROLLER
    assert result["translator"] == "LBNL modelica-json"
    assert result["runtime"] == "Open Control Engine"
    assert result["engine_report"]["block_count"] == 9
    assert result["engine_report"]["stateful_blocks"] == 1
    assert result["engine_report"]["warning_count"] == 0
    assert result["connection_normalization"]["rewritten_connection_set_count"] == 0
    assert [port["label"] for port in result["interface"]["inputs"]] == [
        "TAirSup",
        "TAirSupSet",
        "u1SupFan",
    ]
    assert [port["label"] for port in result["interface"]["outputs"]] == [
        "uTSup",
        "yCooCoi",
        "yHeaCoi",
    ]
    assert result["cxf_document"]["@graph"]
    graph = ControlGraph.model_validate(result["typed_ir"])
    assert result["lowering"]["translatable"] is True
    assert result["lowering"]["niagara_translatable"] is False
    assert sum(block.kind == BlockKind.PID_WITH_RESET for block in graph.blocks) == 1
    assert len(graph.blocks) == 29
    assert result["niagara_lowering_complete"] is False
    target = result["niagara_target"]
    assert target["status"] == "contractor_component_required"
    assert target["typed_environment_component_lane"] is True
    assert target["blockers"] == [
        {
            "class": "Buildings.Controls.OBC.CDL.Reals.PIDWithReset",
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
        }
    ]

    job_template = client.post(
        f"/api/library/g36/controllers/{CONTROLLER}/job-template",
        json={"parameters": {}},
    )
    assert job_template.status_code == 200, job_template.text
    template = job_template.json()
    assert template["sequence"]["family"] == "LBNL_G36_CONTROLLER"
    assert template["sequence"]["library"] == "g36"
    assert [point["name"] for point in template["points"]] == [
        "TAirSup",
        "TAirSupSet",
        "u1SupFan",
        "uTSup",
        "yCooCoi",
        "yHeaCoi",
    ]
    assert template["target_assessment"]["generated_program_count"] == 1


def test_g36_translation_api_rejects_non_allowlisted_path(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))

    response = client.post("/api/library/g36/controllers/..%2F..%2Fetc.passwd/translate")

    assert response.status_code in {404, 405}


def test_g36_translation_selects_source_qualified_artifact_when_names_collide() -> None:
    library = G36Library()
    controller = library._controllers()["AHUs.MultiZone.VAV.Controller"]

    try:
        library._translate(controller["id"])
    except RuntimeError as exc:
        # The composite is not expected to pass OCE yet, but artifact selection must
        # advance to that real hierarchy/grounding gate instead of rejecting the two
        # generated Controller.jsonld files by basename alone.
        assert "did not emit the source-qualified CXF artifact" not in str(exc)


def test_g36_supply_signals_target_compiles_with_exact_contractor_pid(
    tmp_path: Path,
) -> None:
    translated = G36Library().translate(CONTROLLER)
    graph = ControlGraph.model_validate(translated["typed_ir"])
    destination = tmp_path / "g36-supply-signals.bog"

    NiagaraCompiler().compile(
        graph,
        destination,
        environment=_exact_pid_environment(),
    )

    with zipfile.ZipFile(destination) as archive:
        xml = archive.read("file.xml").decode()
    assert 't="g36:PIDWithReset"' in xml
    assert 'm="g36=exactG36"' in xml
    assert '<p n="controllerType" v="PI"' in xml
    assert '<p n="k" v="0.05"' in xml
    assert '<p n="Ti" v="600.0"' in xml
    assert xml.count('t="kitControl:Divide"') >= 2
    assert xml.count('t="kitControl:NumericSwitch"') >= 1


def test_g36_expanded_controller_families_lower_without_hidden_unsupported_classes(
    tmp_path: Path,
) -> None:
    library = G36Library()
    translated = {
        controller_id: library.translate(controller_id) for controller_id in EXPANDED_CONTROLLERS
    }

    for controller_id, expectation in EXPANDED_CONTROLLERS.items():
        result = translated[controller_id]
        lowering = result["lowering"]
        assert lowering["translatable"] is True
        assert lowering["unsupported_classes"] == []
        assert lowering["niagara_translatable"] is expectation["niagara_translatable"]
        assert set(lowering["niagara_unsupported_classes"]) == expectation["niagara_unsupported"]
        assert len(result["typed_ir"]["blocks"]) == expectation["blocks"]

    stock_controller = "TerminalUnits.ParallelFanVVF.Subsequences.Overrides"
    graph = ControlGraph.model_validate(translated[stock_controller]["typed_ir"])
    destination = NiagaraCompiler().compile(
        graph,
        tmp_path / "parallel-fan-vvf-overrides.bog",
    )
    with zipfile.ZipFile(destination) as archive:
        xml = archive.read("file.xml")
    assert b"kitControl:NumericSwitch" in xml
    assert b"kitControl:BooleanSwitch" in xml


def test_g36_modelica_connection_set_is_exactly_canonicalized() -> None:
    result = G36Library().translate("AHUs.SingleZone.VAV.Economizers.Subsequences.Modulation")

    normalization = result["connection_normalization"]
    assert normalization["rewritten_connection_set_count"] == 1
    assert normalization["rewrites"][0]["source"].endswith(".uTSup.y")
    assert {
        sink.rsplit(".", 2)[-2] + "." + sink.rsplit(".", 1)[-1]
        for sink in normalization["rewrites"][0]["sinks"]
    } == {"HeaCoi.u", "outDamPos.u", "retDamPos.u"}
    assert result["lowering"]["translatable"] is True
    assert result["lowering"]["unsupported_classes"] == []
    assert result["lowering"]["niagara_unsupported_classes"] == [
        "Buildings.Controls.OBC.CDL.Reals.PIDWithReset"
    ]


def test_g36_inactive_conditional_wire_is_pruned_and_hold_lowers_exactly() -> None:
    result = G36Library().translate("AHUs.MultiZone.VAV.Economizers.Subsequences.Enable")

    pruning = result["connection_normalization"]["conditional_pruning"]
    assert pruning["inactive_component_count"] == 1
    assert pruning["pruned_connection_count"] == 1
    assert pruning["inactive_components"][0].endswith(".entSubst1")
    assert result["engine_report"]["block_count"] == 20
    assert result["lowering"]["translatable"] is True
    graph = ControlGraph.model_validate(result["typed_ir"])
    hold = next(block for block in graph.blocks if block.kind == BlockKind.BOOLEAN_TRUE_FALSE_HOLD)
    assert hold.config == {
        "true_hold_seconds": 600.0,
        "false_hold_seconds": 600.0,
    }


def test_g36_root_parameter_bounds_and_operation_mode_constants_are_grounded() -> None:
    library = G36Library()
    enable = library.translate("AHUs.SingleZone.VAV.Economizers.Subsequences.Enable")
    limits = library.translate("AHUs.MultiZone.VAV.Economizers.Subsequences.Limits.Common")

    assert (
        enable["connection_normalization"]["root_parameter_bound_grounding"]["grounded_bound_count"]
        == 4
    )
    assert (
        limits["connection_normalization"]["root_parameter_bound_grounding"]["grounded_bound_count"]
        == 10
    )
    assert enable["lowering"]["translatable"] is True
    assert limits["lowering"]["translatable"] is True
    graph = ControlGraph.model_validate(limits["typed_ir"])
    occupied = next(block for block in graph.blocks if block.label == "conInt1")
    assert occupied.kind == BlockKind.NUMERIC_CONST
    assert occupied.config["value"] == 1.0


def test_g36_missing_enum_metadata_is_recovered_and_complex_guards_are_grounded() -> None:
    controller_id = "Generic.AirEconomizerHighLimits"
    library = G36Library()
    schema = library.parameter_schema(controller_id)["parameterization"]

    assert schema["remaining_required_parameters"] == ["ecoHigLimCon", "eneStd"]
    energy_standard = next(item for item in schema["parameters"] if item["name"] == "eneStd")
    assert energy_standard["data_type"].endswith("Types.EnergyStandard")
    assert energy_standard["metadata_source"] == "modelica_source_recovery"
    with pytest.raises(ValueError, match="member of .*EnergyStandard"):
        library.translate(
            controller_id,
            parameters={
                "eneStd": "not.the.declared.enum.Bad",
                "ecoHigLimCon": (
                    "Buildings.Controls.OBC.ASHRAE.G36.Types.ControlEconomizer.FixedDryBulb"
                ),
            },
        )

    result = library.translate(
        controller_id,
        parameters={
            "eneStd": ("Buildings.Controls.OBC.ASHRAE.G36.Types.EnergyStandard.ASHRAE90_1"),
            "ecoHigLimCon": (
                "Buildings.Controls.OBC.ASHRAE.G36.Types.ControlEconomizer.FixedDryBulb"
            ),
        },
    )

    pruning = result["connection_normalization"]["conditional_pruning"]
    assert pruning["active_component_count"] > 0
    assert pruning["inactive_component_count"] > 0
    assert pruning["unresolved_guard_count"] == 0
    assert result["engine_report"]["block_count"] == 81
    assert len(result["typed_ir"]["blocks"]) == 82
    assert library.assess_niagara_source_target(result)["generated_program_count"] == 3


def test_g36_alarm_assertions_are_oce_validated_and_preserved_in_typed_ir() -> None:
    library = G36Library()
    parameters = {
        "VCooMax_flow": 1.0,
        "damPosHys": 0.005,
        "floHys": 0.01,
        "staPreMul": 1.0,
    }
    result = library.translate(
        "TerminalUnits.CoolingOnly.Subsequences.Alarms",
        parameters=parameters,
    )

    assert result["engine_report"]["block_count"] == 47
    assert (
        result["connection_normalization"]["assert_message_normalization"][
            "normalized_message_count"
        ]
        == 4
    )
    assert result["lowering"]["translatable"] is True
    assert result["lowering"]["niagara_translatable"] is False
    assert result["lowering"]["niagara_unsupported_classes"] == [
        "Buildings.Controls.OBC.CDL.Utilities.Assert",
    ]
    graph = ControlGraph.model_validate(result["typed_ir"])
    assertions = [block for block in graph.blocks if block.kind == BlockKind.BOOLEAN_ASSERT_WARNING]
    assert len(assertions) == 4
    assert assertions[0].config["semantic_contract"] == "CDL.Utilities.Assert"
    assert assertions[0].config["repeat_while_false"] is True
    assert "50%" in assertions[0].config["message"]
    assessment = library.assess_niagara_source_target(result)
    assert assessment["complete"] is True
    assert assessment["delivery_mode"] == "generated_program_source"
    assert assessment["generated_program_count"] == 10
    package, _ = library.niagara_program_package(
        "TerminalUnits.CoolingOnly.Subsequences.Alarms",
        parameters=parameters,
    )
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert {program["behavior_kind"] for program in manifest["programs"]} == {
        "boolean_assert_warning",
        "boolean_delay",
    }


def test_g36_freeze_protection_enum_guards_compile_without_discarding_pre_blocker() -> None:
    library = G36Library()
    multi_zone = library.translate("AHUs.MultiZone.VAV.SetPoints.FreezeProtection")
    single_zone = library.translate("AHUs.SingleZone.VAV.SetPoints.FreezeProtection")

    assert multi_zone["engine_report"]["block_count"] == 61
    assert multi_zone["lowering"]["translatable"] is True
    assert library.assess_niagara_source_target(multi_zone)["generated_program_count"] == 14
    assert single_zone["engine_report"]["block_count"] == 61
    assert single_zone["typed_ir"] is None
    assert single_zone["lowering"]["unsupported_classes"] == []
    assert single_zone["lowering"]["exactness_blockers"] == [
        "CDL.Logical.Pre requires same-time Modelica event iteration; select the explicit "
        "host_tick_v1 profile only when a one-call memory projection is acceptable"
    ]


def test_g36_required_root_parameter_is_typed_and_product_wired(tmp_path: Path) -> None:
    controller_id = "AHUs.MultiZone.VAV.SetPoints.ReturnFanAirflowTracking"
    library = G36Library()

    with pytest.raises(RuntimeError, match="difFloSet"):
        library.translate(controller_id)
    with pytest.raises(ValueError, match="unknown or non-root"):
        library.translate(controller_id, parameters={"notAParameter": 2.5})
    with pytest.raises(ValueError, match="finite Real"):
        library.translate(controller_id, parameters={"difFloSet": True})

    translated = library.translate(controller_id, parameters={"difFloSet": 2.5})
    assert translated["lowering"]["translatable"] is True
    assert translated["parameterization"]["required_parameters"] == ["difFloSet"]
    assert translated["parameterization"]["remaining_required_parameters"] == []
    assert translated["parameterization"]["applied"] == [
        {
            "name": "difFloSet",
            "data_type": "Real",
            "previous_value": None,
            "value": 2.5,
            "cxf_value": 2.5,
        }
    ]

    executed = library.execute(
        controller_id,
        parameters={"difFloSet": 2.5},
        samples=[
            {
                "time": 0.0,
                "inputs": {
                    "VAirRet_flow": 7.0,
                    "VAirSup_flow": 10.0,
                    "u1SupFan": True,
                },
            }
        ],
        collect=["yRetFan", "y1RetFan"],
    )
    assert executed["parameterization"]["applied"][0]["value"] == 2.5
    assert len(executed["trace"]["trace"]) == 1

    client = TestClient(create_app(tmp_path / "runs"))
    translated_response = client.post(
        f"/api/library/g36/controllers/{controller_id}/translate",
        json={"parameters": {"difFloSet": 2.5}},
    )
    parameter_response = client.get(f"/api/library/g36/controllers/{controller_id}/parameters")
    package_response = client.post(
        f"/api/library/g36/controllers/{controller_id}/niagara-program-package",
        json={"parameters": {"difFloSet": 2.5}},
    )
    execute_response = client.post(
        f"/api/library/g36/controllers/{controller_id}/execute",
        json={
            "parameters": {"difFloSet": 2.5},
            "samples": [
                {
                    "time": 0.0,
                    "inputs": {
                        "VAirRet_flow": 7.0,
                        "VAirSup_flow": 10.0,
                        "u1SupFan": True,
                    },
                }
            ],
            "collect": ["yRetFan", "y1RetFan"],
        },
    )
    assert translated_response.status_code == 200, translated_response.text
    assert parameter_response.status_code == 200, parameter_response.text
    parameter = next(
        item
        for item in parameter_response.json()["parameterization"]["parameters"]
        if item["name"] == "difFloSet"
    )
    assert parameter["required"] is True
    assert parameter["data_type"] == "Real"
    assert parameter["unit"] == "unit:M3-PER-SEC"
    assert package_response.status_code == 200, package_response.text
    assert execute_response.status_code == 200, execute_response.text


def test_g36_matrix_parameters_are_bounded_typed_and_dimension_checked() -> None:
    controller_id = "AHUs.MultiZone.VAV.SetPoints.OutdoorAirFlow.ASHRAE62_1.SumZone"
    library = G36Library()
    schema = library.parameter_schema(controller_id)["parameterization"]
    matrix = next(item for item in schema["parameters"] if item["name"] == "zonGroMat")

    assert matrix["is_array"] is True
    assert matrix["number_dimensions"] == 2
    assert matrix["size_of_dimensions"] == "(nGro,nZon)"

    _, document = library._source_document(controller_id)
    _, parameterization = library._apply_parameter_overrides(
        document,
        {
            "nGro": 1,
            "nZon": 2,
            "zonGroMat": [[1, 1]],
            "zonGroMatTra": [[1], [1]],
        },
    )
    applied = {item["name"]: item for item in parameterization["applied"]}
    assert applied["zonGroMat"]["cxf_value"] == "{{1,1}}"
    assert applied["zonGroMatTra"]["cxf_value"] == "{{1},{1}}"
    assert parameterization["remaining_required_parameters"] == []

    with pytest.raises(ValueError, match="shape .* declared shape"):
        library._apply_parameter_overrides(
            document,
            {
                "nGro": 1,
                "nZon": 2,
                "zonGroMat": [[1], [1]],
                "zonGroMatTra": [[1], [1]],
            },
        )
    with pytest.raises(ValueError, match="must be rectangular"):
        library._apply_parameter_overrides(
            document,
            {
                "nGro": 2,
                "nZon": 2,
                "zonGroMat": [[1, 0], [1]],
                "zonGroMatTra": [[1, 1], [0, 1]],
            },
        )


def test_g36_pre_semantics_are_profiled_and_match_oce_host_ticks() -> None:
    library = G36Library()
    controller_id = "Generic.TimeSuppression"
    exact = library.translate(controller_id)
    assert exact["execution_profile"] == "modelica_exact"
    assert exact["lowering"]["translatable"] is False
    assert exact["typed_ir"] is None
    assert exact["lowering"]["exactness_blockers"] == [
        "CDL.Logical.Pre requires same-time Modelica event iteration; select the explicit "
        "host_tick_v1 profile only when a one-call memory projection is acceptable"
    ]

    host_tick = library.translate(controller_id, execution_profile="host_tick_v1")
    graph = ControlGraph.model_validate(host_tick["typed_ir"])
    interpreter = GraphInterpreter(graph)
    samples = [
        (0.0, 295.0),
        (120.0, 295.0),
        (240.0, 297.0),
        (360.0, 297.0),
        (480.0, 297.0),
        (600.0, 297.0),
        (720.0, 297.0),
        (840.0, 297.0),
        (960.0, 297.0),
        (1080.0, 297.0),
        (1200.0, 297.0),
        (1320.0, 297.0),
        (1440.0, 297.0),
    ]
    actual = []
    for index, (timestamp, setpoint) in enumerate(samples):
        values = interpreter.evaluate(
            {"TSet": setpoint, "TZon": 295.0},
            step_seconds=0.0 if index == 0 else timestamp - samples[index - 1][0],
        )
        actual.append(values["yAftSup"])
    assert actual == [
        True,
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
        False,
        True,
    ]


def test_g36_supply_temperature_uses_reviewed_composite_lowering(
    tmp_path: Path,
) -> None:
    library = G36Library()
    controller_id = "AHUs.MultiZone.VAV.SetPoints.SupplyTemperature"
    result = library.translate(controller_id)

    assert result["lowering"]["translatable"] is True
    assert result["engine_report"]["oce_validation_succeeded"] is False
    assert result["engine_report"]["oce_missing_classes"] == ["ASHRAE.G36.Generic.TrimAndRespond"]
    graph = ControlGraph.model_validate(result["typed_ir"])
    reset = next(block for block in graph.blocks if block.kind == BlockKind.TRIM_AND_RESPOND)
    assert reset.config == {
        "initial_setpoint": 291.15,
        "minimum_setpoint": 285.15,
        "maximum_setpoint": 291.15,
        "delay_seconds": 600.0,
        "sample_period_seconds": 120.0,
        "ignored_requests": 2.0,
        "trim_amount": 0.1,
        "respond_amount": -0.2,
        "maximum_response": -0.6,
        "hold_enabled": False,
    }
    execution = library.execute(
        controller_id,
        samples=[
            {
                "time": 0.0,
                "inputs": {
                    "TOut": 300.15,
                    "u1SupFan": True,
                    "uOpeMod": 1,
                    "uZonTemResReq": 0,
                },
            }
        ],
        collect=["TAirSupSet"],
    )
    assert execution["runtime"] == "BACTalk typed-IR interpreter"
    assert execution["execution_profile"] == "typed_ir_scan_v1"
    output = execution["trace"]["trace"][0]["outputs"]
    assert abs(next(iter(output.values()))["value"] - 285.15) < 1e-9

    destination = NiagaraCompiler().compile(
        graph,
        tmp_path / "supply-temperature.bog",
        environment=_trim_respond_environment(),
    )
    with zipfile.ZipFile(destination) as archive:
        xml = archive.read("file.xml").decode()
    assert 't="g36:TrimAndRespond"' in xml
    assert '<p n="iniSet" v="291.15"' in xml
    assert '<p n="samplePeriod" v="120"' in xml


def test_g36_execution_api_accepts_only_public_named_ports(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))

    response = client.post(
        f"/api/library/g36/controllers/{CONTROLLER}/execute",
        json={
            "samples": [
                {
                    "time": 0,
                    "inputs": {
                        "TAirSup": 292.15,
                        "TAirSupSet": 290.15,
                        "u1SupFan": True,
                    },
                },
                {"time": 60, "inputs": {"TAirSup": 291.15}},
            ]
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["schema"] == "bactalk.g36-execution/v1"
    assert result["controller"]["id"] == CONTROLLER
    assert result["trace"]["sample_count"] == 2
    assert len(result["trace"]["trace"]) == 2
    assert set(result["trace"]["trace"][0]["outputs"]) == {
        port["id"] for port in result["interface"]["outputs"]
    }


def test_g36_flatten_api_returns_source_bound_rumoca_ir(tmp_path: Path) -> None:
    response = TestClient(create_app(tmp_path / "runs")).post(
        f"/api/library/g36/controllers/{CONTROLLER}/flatten",
        json={"parameters": {}},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["schema"] == "bactalk.rumoca-flatten/v1"
    assert result["variable_count"] == 125
    assert result["equation_count"] == 76
    assert result["provenance"]["source_sha256"] == result["controller"]["source_sha256"]
    assert isinstance(result["flat_ir"]["variables"], dict)


def test_g36_execution_api_rejects_internal_ports_and_partial_initialization(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(tmp_path / "runs"))

    partial = client.post(
        f"/api/library/g36/controllers/{CONTROLLER}/execute",
        json={"samples": [{"time": 0, "inputs": {"TAirSup": 292.15}}]},
    )
    internal = client.post(
        f"/api/library/g36/controllers/{CONTROLLER}/execute",
        json={
            "samples": [
                {
                    "time": 0,
                    "inputs": {
                        "TAirSup": 292.15,
                        "TAirSupSet": 290.15,
                        "u1SupFan": True,
                        "conTSup.u_s": 290.15,
                    },
                }
            ]
        },
    )

    assert partial.status_code == 422
    assert "initialize every public controller input" in partial.json()["detail"]
    assert internal.status_code == 422
    assert "non-public controller inputs" in internal.json()["detail"]


def test_g36_zone_status_duplicator_fixed_arrays_are_exactly_scalarized(
    tmp_path: Path,
) -> None:
    library = G36Library()
    result = library.translate(
        "ZoneGroups.ZoneStatusDuplicator",
        parameters={"nZon": 2, "nZonGro": 3},
    )

    scalarization = result["connection_normalization"]["array_scalarization"]
    assert scalarization["applied"] is True
    assert scalarization["source_component_count"] == 15
    assert scalarization["scalar_connector_count"] == 120
    assert scalarization["scalar_component_count"] == 144
    assert result["engine_report"]["warning_count"] == 0
    assert result["lowering"]["translatable"] is True
    assert result["niagara_target"]["native_lowering_complete"] is True

    graph = ControlGraph.model_validate(result["typed_ir"])
    outputs = GraphInterpreter(graph).evaluate(
        {
            "TZon__1": 290.0,
            "TZon__2": 301.0,
            "u1Occ__1": False,
            "u1Occ__2": True,
        }
    )
    for group in range(1, 4):
        assert outputs[f"yTZon__{group}_1"] == 290.0
        assert outputs[f"yTZon__{group}_2"] == 301.0
        assert outputs[f"y1Occ__{group}_1"] is False
        assert outputs[f"y1Occ__{group}_2"] is True

    artifact = NiagaraCompiler().compile(graph, tmp_path / "zone-status-duplicator.bog")
    assert artifact.stat().st_size > 0


def test_g36_group_status_filters_and_reductions_are_exactly_scalarized() -> None:
    library = G36Library()
    result = library.translate(
        "ZoneGroups.GroupStatus",
        parameters={
            "nBuiZon": 3,
            "nGroZon": 2,
            "zonGroMsk": [True, False, True],
        },
    )

    scalarization = result["connection_normalization"]["array_scalarization"]
    assert scalarization["applied"] is True
    assert scalarization["vector_filter_count"] == 15
    assert scalarization["reduction_count"] == 17
    assert result["engine_report"]["warning_count"] == 0
    assert result["lowering"]["translatable"] is True
    assert library.assess_niagara_source_target(result)["complete"] is True

    graph = ControlGraph.model_validate(result["typed_ir"])
    outputs = GraphInterpreter(graph).evaluate(
        {
            "zonOcc__1": False,
            "zonOcc__2": True,
            "zonOcc__3": False,
            "u1Occ__1": False,
            "u1Occ__2": True,
            "u1Occ__3": False,
            "tNexOcc__1": 100.0,
            "tNexOcc__2": 1.0,
            "tNexOcc__3": 50.0,
            "uCooTim__1": 5.0,
            "uCooTim__2": 99.0,
            "uCooTim__3": 7.0,
            "uWarTim__1": 2.0,
            "uWarTim__2": 100.0,
            "uWarTim__3": 3.0,
            "u1OccHeaHig__1": False,
            "u1OccHeaHig__2": True,
            "u1OccHeaHig__3": False,
            "TZon__1": 290.0,
            "TZon__2": 999.0,
            "TZon__3": 300.0,
            "u1Win__1": False,
            "u1Win__2": False,
            "u1Win__3": True,
        }
    )
    assert outputs["uGroOcc"] is False
    assert outputs["nexOcc"] == 50.0
    assert outputs["yCooTim"] == 7.0
    assert outputs["yWarTim"] == 3.0
    assert outputs["yOccHeaHig"] is False
    assert outputs["TZonMax"] == 300.0
    assert outputs["TZonMin"] == 290.0
    assert outputs["yOpeWin"] == 1.0

    with pytest.raises(ValueError, match="selects 2 values but nout=1"):
        library.translate(
            "ZoneGroups.GroupStatus",
            parameters={
                "nBuiZon": 3,
                "nGroZon": 1,
                "zonGroMsk": [True, False, True],
            },
        )


@pytest.mark.parametrize(
    "controller_id",
    [
        "AHUs.MultiZone.VAV.SetPoints.ReliefFanGroup",
        "AHUs.SingleZone.VAV.SetPoints.ReliefFanGroup",
    ],
)
def test_g36_relief_fan_group_array_network_is_scalarized_and_profiled(
    controller_id: str,
) -> None:
    library = G36Library()
    exact = library.translate(controller_id)
    scalarization = exact["connection_normalization"]["array_scalarization"]

    assert scalarization["applied"] is True
    assert scalarization["matrix_gain_count"] == 1
    assert scalarization["scalar_replicator_count"] == 8
    assert scalarization["reduction_count"] == 8
    assert scalarization["limiter_count"] == 1
    assert exact["engine_report"]["warning_count"] == 0
    assert exact["lowering"]["translatable"] is False
    assert exact["lowering"]["exactness_blockers"] == [
        "CDL.Logical.Pre requires same-time Modelica event iteration; select the explicit "
        "host_tick_v1 profile only when a one-call memory projection is acceptable"
    ]

    sampled = library.translate(controller_id, execution_profile="host_tick_v1")
    graph = ControlGraph.model_validate(sampled["typed_ir"])
    assessment = library.assess_niagara_source_target(sampled)
    assert assessment["complete"] is True
    assert assessment["generated_program_count"] == 18

    interface = sampled["interface"]
    values: dict[str, float | int | bool] = {}
    for port in interface["inputs"]:
        port_type = str(port["type"])
        values[port["label"]] = (
            False if "Boolean" in port_type else 0 if "Integer" in port_type else 0.0
        )
    values["u1SupFan__1"] = True
    values["u1SupFan__2"] = True
    samples = [
        {"time": 0.0, "inputs": values},
        {"time": 500.0, "inputs": {}},
        {"time": 1000.0, "inputs": {}},
    ]
    input_ids = {port["label"]: port["id"] for port in interface["inputs"]}
    output_ids = [port["id"] for port in interface["outputs"]]
    oce = library.engine.simulate_document(
        sampled["cxf_document"],
        samples=[
            {
                "time": sample["time"],
                "inputs": {input_ids[name]: value for name, value in sample["inputs"].items()},
            }
            for sample in samples
        ],
        collect=output_ids,
    )
    typed = library._simulate_typed_graph(
        graph,
        interface=interface,
        samples=samples,
        collect=[port["label"] for port in interface["outputs"]],
    )
    assert [row["outputs"] for row in typed["trace"]] == [row["outputs"] for row in oce["trace"]]
