import json
from pathlib import Path

from bactalk.integrations.open_control_engine import OpenControlEngine
from bactalk.integrations.reference_stack import ReferenceStackCatalog


def test_reference_stack_distinguishes_sources_runtime_and_oracles(tmp_path: Path) -> None:
    modelica = tmp_path / "modelica"
    (modelica / "Buildings/Controls/OBC/ASHRAE").mkdir(parents=True)
    (modelica / "Buildings/Controls/OBC/ASHRAE/Controller.mo").write_text("block Controller")
    oce = tmp_path / "oce"
    fixtures = oce / "crates/oce-cxf/tests/fixtures/g36"
    fixtures.mkdir(parents=True)
    (fixtures / "economizer.jsonld").write_text("{}")
    contracts = oce / "crates/oce-api/contracts"
    contracts.mkdir(parents=True)
    (contracts / "catalog.json").write_text(
        json.dumps(
            {
                "entries": [
                    {"class_path": "CDL.Reals.Add", "reserved": False, "stateful": False},
                    {"class_path": "CDL.Reals.PID", "reserved": False, "stateful": True},
                    {"class_path": "internal", "reserved": True, "stateful": False},
                ]
            }
        )
    )
    constrain = tmp_path / "constrain/constrain/schema"
    constrain.mkdir(parents=True)
    (constrain / "library.json").write_text(
        json.dumps(
            {
                "CHWReset": {"description_brief": "Chilled water reset"},
                "ExteriorLighting": {"description_brief": "Exterior lighting off"},
            }
        )
    )

    result = ReferenceStackCatalog(
        lock_path=tmp_path / "missing-lock.json",
        modelica_root=modelica,
        oce_root=oce,
        constrain_root=tmp_path / "constrain",
        pybog_root=tmp_path / "missing-pybog",
        dflexlibs_root=tmp_path / "missing-dflexlibs",
        open_control_library_root=tmp_path / "missing-open-control-library",
        niagara_program_library_root=tmp_path / "missing-niagara-program-library",
        cxf_manifest_path=tmp_path / "missing-cxf-manifest.json",
    ).inventory()

    assert result["summary"] == {
            "modelica_control_files": 1,
            "modelica_plant_control_files": 0,
        "executable_cdl_blocks": 2,
        "g36_cxf_fixtures": 1,
        "independent_verification_rules": 2,
        "niagara_reference_examples": 0,
        "demand_flex_control_functions": 0,
        "executable_fault_rules": 0,
        "ir_vector_verified_fault_rules": 0,
        "niagara_vector_verified_fault_rules": 0,
        "niagara_program_templates": 0,
        "niagara_program_objects": 0,
    }
    assert [item["integration_status"] for item in result["components"]] == [
        "reference-source",
        "validated-external-runtime",
        "verification-catalog",
        "tested-reference-catalog",
        "tested-reference-catalog",
        "verified-fdd-library",
        "inspected-niagara-reference-library",
    ]


def test_open_control_engine_command_is_isolated(tmp_path: Path) -> None:
    checkout = tmp_path / "oce"
    (checkout / "crates/oce-api").mkdir(parents=True)
    manifest = tmp_path / "Cargo.toml"
    manifest.write_text("[package]\nname='test'\n")
    source = tmp_path / "sequence.jsonld"
    source.write_text("{}")

    command = OpenControlEngine(
        manifest,
        engine_checkout=checkout,
        cargo_binary="cargo-test",
    ).build_command(source)

    assert command[:3] == ["cargo-test", "run", "--quiet"]
    assert command[-2:] == ["inspect", str(source.resolve())]
