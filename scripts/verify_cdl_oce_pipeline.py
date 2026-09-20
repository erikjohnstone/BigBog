import io
import json
import tempfile
import zipfile
from pathlib import Path

from bactalk.integrations.cdl import CdlTranslator
from bactalk.integrations.g36_library import G36Library

CONTROLLER = "AHUs.MultiZone.VAV.SetPoints.SupplySignals"


def main() -> None:
    root = Path.cwd()
    library = G36Library(
        root / ".vendor/modelica-buildings",
        root / ".vendor/modelica-json",
    )
    catalog = library.catalog()
    translated = library.translate(CONTROLLER)
    report = translated["engine_report"]
    program_package, _ = library.niagara_program_package(CONTROLLER)
    with zipfile.ZipFile(io.BytesIO(program_package)) as archive:
        program_manifest = json.loads(archive.read("manifest.json"))

    assert catalog["controller_count"] == 241
    assert catalog["family_counts"]["AHUs"] == 84
    assert catalog["family_counts"]["TerminalUnits"] == 120
    assert translated["controller"]["id"] == CONTROLLER
    assert report["warning_count"] == 0
    assert report["block_count"] == 9
    assert report["stateful_blocks"] == 1
    assert report["point_count"] == 24
    assert translated["lowering"]["translatable"] is True
    assert len(translated["typed_ir"]["blocks"]) == 29
    assert translated["niagara_target"]["status"] == "contractor_component_required"
    assert program_manifest["programs"][0]["behavior_kind"] == "pid_with_reset"
    assert program_manifest["runtime_qualified"] is False
    translator = CdlTranslator(root / ".vendor/modelica-json")
    with tempfile.TemporaryDirectory(prefix="bactalk-modelica-mode-") as directory:
        generated = translator.translate(
            root
            / ".vendor/modelica-json/test/ModelicaMode/ModelWithControlsBlock.mo",
            Path(directory),
            mode="modelica",
            timeout=30.0,
        )
        modelica_mode_artifacts = {
            path.name for path in generated if path.suffix == ".jsonld"
        }
    assert modelica_mode_artifacts == {
        "ModelWithControlsBlock.jsonld",
        "SubControllerForControlsExport.jsonld",
    }
    print(
        "CDL -> CXF -> Open Control Engine: OK "
        f"({catalog['controller_count']} allowlisted G36 controllers; "
        f"selected {report['block_count']} blocks, {report['stateful_blocks']} stateful, "
        f"{report['point_count']} points, {report['warning_count']} warnings; "
        "29-block exact IR, gated Niagara ProgramObject source package, and "
        "bounded Modelica-container control extraction)"
    )


if __name__ == "__main__":
    main()
