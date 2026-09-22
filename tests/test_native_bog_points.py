"""N5 contract: station points as data, binding suggestions, and linked assembly.

The exit: a fixture station with one AHU and 25 VAVs and messy real-world names
exports as a linked ``.bog`` that passes the validator with no generated Java.
"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient

from bactalk.api import create_app
from bactalk.domain import DeliverableRequirements, PointRole, ShopProfile
from bactalk.integrations.niagara_station import (
    PointBinding,
    assemble_project_station_bog,
    assemble_station_bog,
    point_bindings,
)
from bactalk.library_demo import lbnl_multizone_ahu_demo_job, lbnl_vav_reheat_demo_job
from bactalk.niagara.emit import emit_bog
from bactalk.niagara.module import declared_types
from bactalk.niagara.pointmap import apply_bindings, suggest_bindings, tokens
from bactalk.niagara.station_points import parse_station_inventory
from bactalk.niagara.validate import validate_bog
from bactalk.repository import RunRepository
from bactalk.service import WorkbenchService

pytestmark = [pytest.mark.minimal, pytest.mark.native_bog]

ROOT = Path(__file__).resolve().parents[1]
STATION = ROOT / "tests" / "fixtures" / "native-bog" / "station-ahu-25vav.bog"

# What a technician would confirm for one VAV box, given the fixture's names.
VAV_EXPECTED = {
    "TZon": "ZN_T",
    "TDis": "DAT",
    "VDis_flow": "AFL_CFM",
    "TCooSet": "CLG_STPT",
    "THeaSet": "HTG_SP",
    "u1Occ": "OCC",
    "u1Win": "WIN_STS",
    "ppmCO2": "CO2",
    "yDam": "DMPR_POS",
    "yVal": "RHT_VLV",
}


def _xml(content: bytes) -> ElementTree.Element:
    with zipfile.ZipFile(BytesIO(content)) as archive:
        return ElementTree.fromstring(archive.read("file.xml"))


def test_station_fixture_parses_as_data() -> None:
    inventory = parse_station_inventory(STATION.read_bytes())
    assert inventory.networks == ("station:|slot:/Drivers/BacnetNetwork",)
    assert len(inventory.devices) == 26
    assert len(inventory.points) == 20 + 25 * 10
    assert inventory.warnings == ()
    ahu = inventory.devices[0]
    assert ahu.name == "AHU_1" and ahu.device_instance == 1001
    point = next(p for p in ahu.points if p.name == "AHU1_SA_T")
    assert point.bacnet_object == "analog-input,1"
    assert point.data_type == "numeric" and point.units == "fahrenheit"
    assert point.writable is False
    assert point.ord == "station:|slot:/Drivers/BacnetNetwork/AHU_1/points/AHU1_SA_T"
    command = next(p for p in ahu.points if p.name == "AHU1_SF_SPD_CMD")
    assert command.writable and command.bacnet_object == "analog-output,1"


def test_station_fixture_passes_the_validator_with_bacnet_types_declared() -> None:
    report = validate_bog(STATION.read_bytes(), label="station")
    assert report.ok, [str(issue) for issue in report.errors]
    assert not report.warnings, [str(issue) for issue in report.warnings][:5]


def test_tokens_expand_field_abbreviations() -> None:
    assert tokens("VAV-1-01 ZN-T") == ("vav", "zone", "temp")
    assert tokens("AHU1_OAD_CMD") == ("ahu1", "outside", "air", "damper", "command")
    assert tokens("yDam") == ("damper",)
    assert tokens("TCooSet") == ("temp", "cooling", "setpoint")


def test_suggestions_rank_the_right_proxy_first_for_a_messy_vav() -> None:
    inventory = parse_station_inventory(STATION.read_bytes())
    vav = [p for p in inventory.points if p.device == "VAV_1_01"]
    job = lbnl_vav_reheat_demo_job()
    suggestions = suggest_bindings(job.points, vav)
    misses = {
        name: [item.ord.rsplit("/", 1)[-1] for item in suggestions[name]]
        for name, suffix in VAV_EXPECTED.items()
        if not suggestions[name] or not suggestions[name][0].ord.endswith(suffix)
    }
    assert not misses, misses
    for name, items in suggestions.items():
        for item in items:
            assert item.reasons and item.score >= 0.35
            role = next(p for p in job.points if p.name == name).role
            if role is PointRole.COMMAND:
                assert item.write_priority == 16
    # Nothing is ever suggested without a shared name token.
    assert suggestions["u1Fan"] == []


def test_apply_bindings_refuses_priority_one_and_implicit_priorities() -> None:
    job = lbnl_vav_reheat_demo_job()
    ords = {
        "TZon": {
            "niagara_ord": "station:|slot:/Drivers/BacnetNetwork/VAV_1_01/points/VAV_1_01_ZN_T",
        },
        "yDam": {
            "niagara_ord": "station:|slot:/Drivers/BacnetNetwork/VAV_1_01/points/VAV_1_01_DMPR_POS",
            "write_priority": 8,
        },
    }
    points = apply_bindings(job.points, ords)
    by_name = {p.name: p for p in points}
    assert by_name["TZon"].niagara_ord and by_name["TZon"].niagara_write_priority is None
    assert by_name["yDam"].niagara_write_priority == 8
    with pytest.raises(ValueError, match="explicit write priority"):
        apply_bindings(job.points, {"yDam": {"niagara_ord": ords["yDam"]["niagara_ord"]}})
    with pytest.raises(ValueError, match="never 1"):
        apply_bindings(job.points, {"yDam": {**ords["yDam"], "write_priority": 1}})
    with pytest.raises(ValueError, match="station:\\|slot:/"):
        apply_bindings(job.points, {"TZon": {"niagara_ord": "h:12"}})


def _vav_job(box: str, priority: int = 16):
    """The retained VAV job bound to one fixture box by the expected names."""

    job = lbnl_vav_reheat_demo_job()
    prefix = f"station:|slot:/Drivers/BacnetNetwork/{box}/points/{box}_"
    confirmed = {}
    for name, suffix in VAV_EXPECTED.items():
        point = next(p for p in job.points if p.name == name)
        entry: dict[str, object] = {"niagara_ord": prefix + suffix}
        if point.role is PointRole.COMMAND:
            entry["write_priority"] = priority
        confirmed[name] = entry
    points = apply_bindings(job.points, confirmed)
    return job.model_copy(update={"points": points, "equipment_name": box})


def test_assembly_links_confirmed_points_and_checks_collisions() -> None:
    job = _vav_job("VAV_1_01")
    program = emit_bog(job.control_graph, points=job.points).content
    profile = ShopProfile(name="fixture", version="1", station_template_mode="insert")
    job = job.model_copy(update={"deliverables": DeliverableRequirements(shop_profile=profile)})
    bindings = point_bindings(job, job.control_graph)
    assert len(bindings) == len(VAV_EXPECTED)
    assembly = assemble_station_bog(
        STATION.read_bytes(), program, job, job.control_graph, mode="insert", bindings=bindings
    )
    assert assembly.manifest["point_link_count"] == len(VAV_EXPECTED)
    report = validate_bog(assembly.content, declared_types=declared_types(), label="assembled")
    assert report.ok, [str(issue) for issue in report.errors]
    root = _xml(assembly.content)
    damper = next(e for e in root.iter("p") if e.get("n") == "VAV_1_01_DMPR_POS")
    link = next(c for c in damper if c.get("t") == "b:Link")
    fields = {c.get("n"): c.get("v") for c in link}
    assert fields["targetSlotName"] == "in16" and fields["sourceSlotName"] == "out"
    # A second binding onto the same driven slot is refused.
    with pytest.raises(ValueError, match="already driven"):
        assemble_station_bog(
            STATION.read_bytes(),
            program,
            job,
            job.control_graph,
            mode="insert",
            bindings=(
                *bindings,
                PointBinding("yVal", bindings[-1].proxy_ord, "program_to_proxy", 16),
            ),
        )
    with pytest.raises(ValueError, match="between 2 and 16"):
        assemble_station_bog(
            STATION.read_bytes(),
            program,
            job,
            job.control_graph,
            mode="insert",
            bindings=(PointBinding("yDam", bindings[0].proxy_ord, "program_to_proxy", 1),),
        )
    with pytest.raises(ValueError, match="does not resolve"):
        assemble_station_bog(
            STATION.read_bytes(),
            program,
            job,
            job.control_graph,
            mode="insert",
            bindings=(PointBinding("TZon", "station:|slot:/Nope/Point", "proxy_to_program"),),
        )


def test_one_ahu_and_25_vavs_export_as_one_linked_station() -> None:
    """The N5 exit condition."""

    inventory = parse_station_inventory(STATION.read_bytes())
    template = STATION.read_bytes()
    profile = ShopProfile(name="fixture", version="1", station_template_mode="insert")
    programs = []
    bindings_by_equipment = {}
    for device in inventory.devices:
        if device.name == "AHU_1":
            job = lbnl_multizone_ahu_demo_job().model_copy(update={"equipment_name": "AHU_1"})
            graph = job.control_graph.model_copy(update={"name": "AHU_1"})
        else:
            job = _vav_job(device.name)
            graph = job.control_graph.model_copy(update={"name": device.name})
        job = job.model_copy(update={"deliverables": DeliverableRequirements(shop_profile=profile)})
        programs.append((emit_bog(graph, points=job.points).content, job, graph))
        bindings_by_equipment[job.equipment_name] = point_bindings(job, graph)
    assembly = assemble_project_station_bog(
        template, programs, mode="insert", bindings_by_equipment=bindings_by_equipment
    )
    assert assembly.manifest["program_count"] == 26
    total_links = sum(step["point_link_count"] for step in assembly.manifest["steps"])
    assert total_links == 25 * len(VAV_EXPECTED)
    report = validate_bog(assembly.content, declared_types=declared_types(), label="project")
    assert report.ok, [str(issue) for issue in report.errors][:5]
    assert not report.warnings, [str(issue) for issue in report.warnings][:5]
    root = _xml(assembly.content)
    programs_in_station = [
        e.get("n")
        for e in root.iter("p")
        if e.get("n", "").startswith("VAV_") and e.get("t") == "b:Folder"
    ]
    assert len(programs_in_station) == 25
    assert not any(name.endswith(".java") for name in (e.get("n") or "" for e in root.iter("p")))


def test_service_exports_a_linked_station_without_java(tmp_path: Path) -> None:
    job = _vav_job("VAV_2_11")
    job = job.model_copy(
        update={
            "deliverables": DeliverableRequirements(
                shop_profile=ShopProfile(
                    name="fixture", version="1", station_template_mode="insert"
                )
            )
        }
    )
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    record = service.create_run(job, template_bog=STATION.read_bytes())
    assert record.status.value == "ready_for_review"
    assert record.assembled_bog_path is not None
    manifest = json.loads(Path(record.station_assembly_manifest_path).read_text("utf-8"))
    assert manifest["point_link_count"] == len(VAV_EXPECTED)
    # The generated point binder (Java) left the default path; the JSON binding
    # plan stays. (The alarm installer is a separate deliverable, out of N5's scope.)
    assert not [p for p in record.deliverable_artifact_paths if "PointBinder" in p]
    assert any(p.endswith("niagara-point-bindings.json") for p in record.deliverable_artifact_paths)


def test_station_binding_suggestions_route(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))
    job = lbnl_vav_reheat_demo_job()
    csv = "name,label,data_type,role,default,required\n" + "\n".join(
        f"{p.name},{p.label},{p.data_type.value},{p.role.value},{p.default},true"
        for p in job.points
    )
    response = client.post(
        "/api/intake/station-bindings",
        data={"sequence_family": "AUTO"},
        files={
            "station_bog": ("station.bog", STATION.read_bytes(), "application/octet-stream"),
            "points_file": ("points.csv", csv.encode(), "text/csv"),
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["inventory"]["device_count"] == 26
    assert payload["policy"]["human_confirmation_required"] is True
    assert payload["suggestions"]["yDam"][0]["write_priority"] == 16
    assert payload["suggestions"]["uOpeMod"] == []
