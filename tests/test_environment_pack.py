from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bactalk.api import create_app
from bactalk.compiler import NiagaraCompiler
from bactalk.demo import demo_job
from bactalk.domain import Block, BlockKind, ControlGraph, Link
from bactalk.integrations.environment_pack import inspect_environment_pack
from bactalk.repository import RunRepository
from bactalk.service import ArtifactChangedError, WorkbenchService

EXAMPLES = Path(__file__).parents[1] / "examples"


def _zip(entries: dict[str, bytes]) -> bytes:
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return target.getvalue()


def example_environment_pack() -> bytes:
    module = _zip(
        {
            "META-INF/MANIFEST.MF": b"Manifest-Version: 1.0\n",
            "com/acme/controls/BReset.class": b"not-executed-test-bytecode",
        }
    )
    point_names = [point.name for point in demo_job().points]
    bindings = "".join(
        (
            f'<BoundLabel point="{name}" '
            f'ord="{{{{BACTALK:POINT_ORD:{name}}}}}" '
            f'text="{{{{BACTALK:POINT_LABEL:{name}}}}}"/>'
        )
        for name in point_names
    )
    graphic = (
        '<Px version="1.0" title="{{BACTALK:VIEW_TITLE}}" '
        'equipment="{{BACTALK:EQUIPMENT_NAME}}">'
        + bindings
        + "</Px>"
    ).encode()
    descriptor = {
        "schema_version": "1.0",
        "id": "acme-standard",
        "name": "Acme Niagara Standard",
        "version": "2026.09",
        "niagara_version": "4.14.0.162",
        "modules": [
            {
                "name": "acmeControls",
                "version": "3.2.1",
                "vendor": "Acme Controls",
                "preferred_symbol": "acme",
                "runtime_profiles": ["rt", "wb"],
                "artifact": "modules/acmeControls-rt.jar",
                "sha256": hashlib.sha256(module).hexdigest(),
                "license_spdx": "LicenseRef-Acme-Proprietary",
                "redistribution": "shop_supplied_only",
                "required": True,
            }
        ],
        "palettes": [
            {
                "id": "acme-hvac",
                "module": "acmeControls",
                "resource": "module://acmeControls/palette/acme-hvac.palette",
                "component_types": ["acmeControls:Reset", "acmeControls:LeadLag"],
                "components": [
                    {
                        "type_spec": "acmeControls:Add",
                        "behavior_kind": "add",
                        "inputs": {
                            "a": {"niagara_slot": "inputLeft", "data_type": "numeric"},
                            "b": {"niagara_slot": "inputRight", "data_type": "numeric"},
                        },
                        "outputs": {
                            "out": {"niagara_slot": "sum", "data_type": "numeric"}
                        },
                        "properties": {"precision": 2},
                    }
                ],
            }
        ],
        "graphics_templates": [
            {
                "id": "ExampleVavOverview",
                "artifact": "graphics/ahu-overview.px",
                "sha256": hashlib.sha256(graphic).hexdigest(),
                "media_type": "application/vnd.tridium.px",
            }
        ],
    }
    return _zip(
        {
            "environment.json": json.dumps(descriptor).encode(),
            "modules/acmeControls-rt.jar": module,
            "graphics/ahu-overview.px": graphic,
        }
    )


def exact_pid_environment_pack() -> bytes:
    with zipfile.ZipFile(io.BytesIO(example_environment_pack())) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    descriptor = json.loads(entries["environment.json"])
    descriptor["palettes"][0]["components"].append(
        {
            "type_spec": "acmeControls:G36PidWithReset",
            "behavior_kind": "pid_with_reset",
            "inputs": {
                "setpoint": {"niagara_slot": "u_s", "data_type": "numeric"},
                "measurement": {"niagara_slot": "u_m", "data_type": "numeric"},
                "trigger": {"niagara_slot": "trigger", "data_type": "boolean"},
            },
            "outputs": {"out": {"niagara_slot": "y", "data_type": "numeric"}},
            "properties": {},
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
            "contract_version": "G36-PIDWithReset-2026.1",
        }
    )
    entries["environment.json"] = json.dumps(descriptor).encode()
    return _zip(entries)


def test_environment_pack_is_hash_verified_and_never_executed() -> None:
    export = inspect_environment_pack(example_environment_pack())

    assert export.manifest["environment"]["niagara_version"] == "4.14.0.162"
    assert export.manifest["custom_component_types"] == [
        "acmeControls:Add",
        "acmeControls:LeadLag",
        "acmeControls:Reset",
    ]
    module = export.manifest["environment"]["modules"][0]
    assert module["static_inventory"]["class_count"] == 1
    assert module["static_inventory"]["executed_during_ingest"] is False
    assert export.manifest["safety"]["declared_artifact_hashes_verified"] is True
    assert export.manifest["compatibility"]["runtime_qualified"] is False
    assert {item.relative_path for item in export.artifacts} >= {
        "assets/modules/acmeControls-rt.jar",
        "assets/graphics/ahu-overview.px",
    }


def test_environment_pack_rejects_hash_mismatch_and_undeclared_files() -> None:
    original = example_environment_pack()
    with zipfile.ZipFile(io.BytesIO(original)) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    entries["graphics/ahu-overview.px"] = b"tampered"
    with pytest.raises(ValueError, match="hash mismatch"):
        inspect_environment_pack(_zip(entries))

    entries = {
        name: content
        for name, content in entries.items()
        if name != "graphics/ahu-overview.px"
    }
    descriptor = json.loads(entries["environment.json"])
    descriptor["graphics_templates"] = []
    entries["environment.json"] = json.dumps(descriptor).encode()
    entries["surprise.sh"] = b"echo should-not-be-present"
    with pytest.raises(ValueError, match="undeclared files"):
        inspect_environment_pack(_zip(entries))


def test_environment_pack_rejects_path_traversal() -> None:
    with pytest.raises(ValueError, match="unsafe environment-pack path"):
        inspect_environment_pack(
            _zip(
                {
                    "environment.json": json.dumps(
                        {
                            "id": "unsafe",
                            "name": "Unsafe",
                            "version": "1",
                            "niagara_version": "4.14",
                        }
                    ).encode(),
                    "../escape.jar": b"bad",
                }
            )
        )


def test_environment_pack_closes_custom_module_and_palette_types() -> None:
    template = _zip(
        {
            "file.xml": (
                b'<?xml version="1.0"?><bajaObjectGraph><p t="b:UnrestrictedFolder" '
                b'm="b=baja"><p n="Reset" t="acme:Reset" '
                b'm="acme=acmeControls"/></p></bajaObjectGraph>'
            )
        }
    )

    export = inspect_environment_pack(
        example_environment_pack(),
        template_bog=template,
    )

    compatibility = export.manifest["compatibility"]
    assert compatibility["statically_compatible"] is True
    inspected = compatibility["inputs"]["contractor_template"]
    assert inspected["custom_modules"] == ["acmeControls"]
    assert inspected["custom_component_types"] == ["acmeControls:Reset"]
    assert inspected["uncontracted_custom_component_types"] == []


def test_environment_pack_fails_closed_for_unknown_template_type() -> None:
    template = _zip(
        {
            "file.xml": (
                b'<?xml version="1.0"?><bajaObjectGraph><p t="b:UnrestrictedFolder" '
                b'm="b=baja"><p n="Mystery" t="unknown:Mystery" '
                b'm="unknown=unknownModule"/></p></bajaObjectGraph>'
            )
        }
    )

    with pytest.raises(ValueError, match="missing-module:unknownModule"):
        inspect_environment_pack(
            example_environment_pack(),
            template_bog=template,
        )


def test_typed_custom_palette_block_compiles_with_declared_slots(tmp_path: Path) -> None:
    environment = inspect_environment_pack(example_environment_pack()).descriptor
    graph = ControlGraph(
        name="Custom_Module_Proof",
        blocks=[
            Block(
                id="One",
                kind=BlockKind.NUMERIC_CONST,
                label="One",
                config={"value": 1.0},
            ),
            Block(
                id="Two",
                kind=BlockKind.NUMERIC_CONST,
                label="Two",
                config={"value": 2.0},
            ),
            Block(
                id="CustomAdd",
                kind=BlockKind.ADD,
                label="Shop add block",
                config={"niagara_override": {"type_spec": "acmeControls:Add"}},
            ),
            Block(id="Result", kind=BlockKind.NUMERIC_OUTPUT, label="Result"),
        ],
        links=[
            Link(source="One", target="CustomAdd", target_slot="a"),
            Link(source="Two", target="CustomAdd", target_slot="b"),
            Link(source="CustomAdd", target="Result", target_slot="in"),
        ],
    )
    destination = tmp_path / "custom.bog"

    NiagaraCompiler().compile(graph, destination, environment=environment)

    with zipfile.ZipFile(destination) as archive:
        xml = archive.read("file.xml").decode()
    assert 't="acme:Add"' in xml
    assert 'm="acme=acmeControls"' in xml
    assert '<p n="precision" v="2.0"' in xml
    assert '<p n="targetSlotName" v="inputLeft"' in xml
    assert '<p n="targetSlotName" v="inputRight"' in xml
    assert '<p n="sourceSlotName" v="sum"' in xml


def test_custom_block_without_environment_contract_fails_closed(tmp_path: Path) -> None:
    graph = ControlGraph(
        name="Missing_Custom_Contract",
        blocks=[
            Block(
                id="One",
                kind=BlockKind.NUMERIC_CONST,
                label="One",
                config={"value": 1.0},
            ),
            Block(
                id="Two",
                kind=BlockKind.NUMERIC_CONST,
                label="Two",
                config={"value": 2.0},
            ),
            Block(
                id="CustomAdd",
                kind=BlockKind.ADD,
                label="Shop add block",
                config={"niagara_override": {"type_spec": "acmeControls:Add"}},
            ),
        ],
        links=[
            Link(source="One", target="CustomAdd", target_slot="a"),
            Link(source="Two", target="CustomAdd", target_slot="b"),
        ],
    )

    with pytest.raises(ValueError, match="no typed component contract"):
        NiagaraCompiler().compile(graph, tmp_path / "unsafe.bog")


def test_exact_temporal_block_uses_unique_contractor_component_and_parameters(
    tmp_path: Path,
) -> None:
    environment = inspect_environment_pack(exact_pid_environment_pack()).descriptor
    graph = ControlGraph(
        name="Exact_G36_PID",
        blocks=[
            Block(id="Setpoint", kind=BlockKind.NUMERIC_INPUT, label="Setpoint"),
            Block(id="Measurement", kind=BlockKind.NUMERIC_INPUT, label="Measurement"),
            Block(id="Reset", kind=BlockKind.BOOLEAN_INPUT, label="Reset"),
            Block(
                id="Controller",
                kind=BlockKind.PID_WITH_RESET,
                label="G36 PID with reset",
                config={
                    "controller_type": "PI",
                    "k": 0.05,
                    "ti": 600.0,
                    "td": 0.1,
                    "r": 1.0,
                    "ni": 0.9,
                    "nd": 10.0,
                    "y_min": -1.0,
                    "y_max": 1.0,
                    "xi_start": 0.0,
                    "yd_start": 0.0,
                    "y_reset": 0.0,
                    "reverse_acting": False,
                },
            ),
            Block(id="Output", kind=BlockKind.NUMERIC_OUTPUT, label="Output"),
        ],
        links=[
            Link(source="Setpoint", target="Controller", target_slot="setpoint"),
            Link(source="Measurement", target="Controller", target_slot="measurement"),
            Link(source="Reset", target="Controller", target_slot="trigger"),
            Link(source="Controller", target="Output", target_slot="in"),
        ],
    )
    destination = tmp_path / "exact-pid.bog"

    NiagaraCompiler().compile(graph, destination, environment=environment)

    with zipfile.ZipFile(destination) as archive:
        xml = archive.read("file.xml").decode()
    assert 't="acme:G36PidWithReset"' in xml
    assert 'm="acme=acmeControls"' in xml
    assert '<p n="controllerType" v="PI"' in xml
    assert '<p n="Ti" v="600.0"' in xml
    assert '<p n="Ni" v="0.9"' in xml
    assert '<p n="reverseActing" v="false"' in xml
    assert '<p n="targetSlotName" v="u_s"' in xml
    assert '<p n="targetSlotName" v="u_m"' in xml
    assert '<p n="targetSlotName" v="trigger"' in xml
    assert '<p n="sourceSlotName" v="y"' in xml


def test_exact_temporal_block_without_component_contract_still_fails_closed(
    tmp_path: Path,
) -> None:
    graph = ControlGraph(
        name="Missing_Exact_PID",
        blocks=[
            Block(id="Setpoint", kind=BlockKind.NUMERIC_INPUT, label="Setpoint"),
            Block(id="Measurement", kind=BlockKind.NUMERIC_INPUT, label="Measurement"),
            Block(id="Reset", kind=BlockKind.BOOLEAN_INPUT, label="Reset"),
            Block(
                id="Controller",
                kind=BlockKind.PID_WITH_RESET,
                label="G36 PID with reset",
            ),
        ],
        links=[
            Link(source="Setpoint", target="Controller", target_slot="setpoint"),
            Link(source="Measurement", target="Controller", target_slot="measurement"),
            Link(source="Reset", target="Controller", target_slot="trigger"),
        ],
    )

    # The stock-only lane still fails closed without a contract for the kind;
    # left to itself the native lane (N4) carries it as a bactalkG36 component.
    with pytest.raises(ValueError, match="pid_with_reset"):
        NiagaraCompiler().compile(graph, tmp_path / "unsafe-pid.bog", native=False)
    native = NiagaraCompiler().compile(graph, tmp_path / "native-pid.bog")
    with zipfile.ZipFile(native) as archive:
        assert 't="bactalkG36:PIDWithReset"' in archive.read("file.xml").decode()


def test_environment_pack_is_signed_into_the_approval_bundle(tmp_path: Path) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    record = service.create_run(demo_job(), environment_pack=example_environment_pack())

    assert record.environment_pack_path is not None
    assert record.environment_manifest_path is not None
    manifest = json.loads(Path(record.environment_manifest_path).read_text(encoding="utf-8"))
    assert manifest["environment"]["id"] == "acme-standard"
    assert len(record.environment_artifact_paths) == 5
    deliverable_paths = {Path(path).name for path in record.deliverable_artifact_paths}
    assert "VavOverview.px" in deliverable_paths
    generated_px = next(
        Path(path).read_text(encoding="utf-8")
        for path in record.deliverable_artifact_paths
        if path.endswith("VavOverview.px")
    )
    assert "{{BACTALK:" not in generated_px
    assert (
        "station:|slot:/Config/Drivers/BACnetNetwork/ExampleCampus/VAV_12/ZoneTemp"
        in generated_px
    )

    service.approve(record.id, "Alex Engineer")
    with zipfile.ZipFile(service.review_bundle_path(record.id)) as archive:
        names = set(archive.namelist())
    assert "environment/contractor-environment-pack.zip" in names
    assert "environment/assets/modules/acmeControls-rt.jar" in names
    assert "environment/assets/graphics/ahu-overview.px" in names
    assert "environment/manifest.json" in names
    assert "deliverables/niagara-graphics/VavOverview.px" in names

    Path(record.environment_pack_path).write_bytes(b"tampered")
    with pytest.raises(ArtifactChangedError):
        service.export_path(record.id)


def test_environment_pack_upload_is_wired_through_contractor_import_api(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(tmp_path / "runs"))

    response = client.post(
        "/api/runs/import",
        data={
            "name": "Environment upload proof",
            "site": "Example Campus",
            "equipment_name": "VAV_12",
            "sequence_family": "G36_VAV_REHEAT",
            "sequence_parameters": (
                '{"loop_span_f":3,"minimum_damper_pct":20,"high_zone_temp_f":80}'
            ),
        },
        files={
            "points_file": (
                "points.csv",
                (EXAMPLES / "vav-reheat-points.csv").read_bytes(),
                "text/csv",
            ),
            "bacnet_scan": (
                "scan.json",
                (EXAMPLES / "vav-reheat-scan.json").read_bytes(),
                "application/json",
            ),
            "environment_pack": (
                "acme-environment.zip",
                example_environment_pack(),
                "application/zip",
            ),
        },
    )

    assert response.status_code == 201, response.text
    record = response.json()
    assert record["environment_manifest_path"] is not None
    manifest = client.get(f"/api/runs/{record['id']}/environment-manifest")
    assert manifest.status_code == 200
    assert manifest.json()["environment"]["id"] == "acme-standard"
