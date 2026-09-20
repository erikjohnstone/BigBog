from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient

from bactalk.agent import SequencePackPlanner
from bactalk.api import create_app
from bactalk.compiler import NiagaraCompiler
from bactalk.demo import demo_job
from bactalk.integrations.niagara_station import assemble_station_bog
from bactalk.repository import RunRepository
from bactalk.service import WorkbenchService


def _bog(xml: str) -> bytes:
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("file.xml", xml.encode())
    return target.getvalue()


def _station(
    *,
    existing_program: bool = False,
    missing_target: bool = False,
    external_reference: bool = False,
) -> bytes:
    target = "" if missing_target else """
      <p n="Drivers" t="b:Folder">
        <p n="BACnetNetwork" t="b:Folder">
          <p n="ExampleCampus" t="b:Folder" h="a">
            {program}
            <p n="ContractorOwned" t="b:Folder" h="b"/>
          </p>
        </p>
    </p>""".format(
        program='<p n="VAV_12" t="b:Folder" h="c"/>' if existing_program else ""
    )
    external = (
        '<p n="ExternalLink" t="b:Ord" v="h:c"/>' if external_reference else ""
    )
    return _bog(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<bajaObjectGraph version="4.0">
  <p t="b:UnrestrictedFolder" m="b=baja">
    <p n="Config" t="b:Folder" h="1">{target}</p>
    <p n="Services" t="b:Folder" h="2">
      <p n="ContractorService" t="b:Folder" h="3"/>
      {external}
    </p>
  </p>
</bajaObjectGraph>"""
    )


def _program(tmp_path: Path):
    job = demo_job()
    graph = SequencePackPlanner().plan(job)
    path = tmp_path / "program.bog"
    NiagaraCompiler().compile(graph, path, deliverables=job.deliverables)
    return job, graph, path.read_bytes()


def _xml(content: bytes) -> ElementTree.Element:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return ElementTree.fromstring(archive.read("file.xml"))


def _find_path(root: ElementTree.Element, path: list[str]) -> ElementTree.Element:
    current = next(child for child in root if child.tag == "p" and child.get("n") is None)
    for name in path:
        current = next(child for child in current if child.tag == "p" and child.get("n") == name)
    return current


def test_station_assembly_inserts_program_rebases_handles_and_preserves_station(
    tmp_path: Path,
) -> None:
    job, graph, program = _program(tmp_path)

    first = assemble_station_bog(_station(), program, job, graph, mode="insert")
    second = assemble_station_bog(_station(), program, job, graph, mode="insert")

    assert first.content == second.content
    root = _xml(first.content)
    _find_path(root, ["Services", "ContractorService"])
    parent = _find_path(root, ["Config", "Drivers", "BACnetNetwork", "ExampleCampus"])
    assert {item.get("n") for item in parent if item.tag == "p"} == {
        "ContractorOwned",
        "VAV_12",
    }
    handles = [item.get("h") for item in root.iter() if item.get("h")]
    assert len(handles) == len(set(handles))
    handle_refs = {
        match.group(1).lower()
        for item in root.iter()
        for value in item.attrib.values()
        for match in re.finditer(r"h:([0-9a-fA-F]+)(?![A-Za-z0-9_$])", value)
    }
    assert handle_refs <= set(handles)
    assert first.manifest["action"] == "inserted"
    assert first.manifest["handle_rebase_count"] > 0
    assert first.manifest["safety"]["live_station_modified"] is False


def test_station_assembly_refuses_insert_collision_and_missing_parent(tmp_path: Path) -> None:
    job, graph, program = _program(tmp_path)

    with pytest.raises(ValueError, match="already contains"):
        assemble_station_bog(_station(existing_program=True), program, job, graph, mode="insert")
    with pytest.raises(ValueError, match="exact target parent path"):
        assemble_station_bog(_station(missing_target=True), program, job, graph, mode="insert")


def test_station_assembly_replace_requires_and_replaces_exact_target(tmp_path: Path) -> None:
    job, graph, program = _program(tmp_path)

    assembly = assemble_station_bog(
        _station(existing_program=True),
        program,
        job,
        graph,
        mode="replace",
    )

    assert assembly.manifest["action"] == "replaced"
    assert assembly.manifest["replaced_component_sha256"] is not None
    root = _xml(assembly.content)
    program_node = _find_path(
        root,
        ["Config", "Drivers", "BACnetNetwork", "ExampleCampus", "VAV_12"],
    )
    assert any(item.get("n") == "ZoneTemp" for item in program_node if item.tag == "p")

    with pytest.raises(ValueError, match="no component"):
        assemble_station_bog(_station(), program, job, graph, mode="replace")
    with pytest.raises(ValueError, match="outside the replacement target"):
        assemble_station_bog(
            _station(existing_program=True, external_reference=True),
            program,
            job,
            graph,
            mode="replace",
        )


def test_service_exports_assembled_station_only_after_approval(tmp_path: Path) -> None:
    job = demo_job()
    assert job.deliverables.shop_profile is not None
    job.deliverables.shop_profile.station_template_mode = "insert"
    runs = tmp_path / "runs"
    service = WorkbenchService(RunRepository(runs))

    record = service.create_run(job, template_bog=_station())

    assert record.assembled_bog_path is not None
    assert record.station_assembly_manifest_path is not None
    manifest = json.loads(Path(record.station_assembly_manifest_path).read_text(encoding="utf-8"))
    assert manifest["target_program_ord"].endswith("/ExampleCampus/VAV_12")
    response = TestClient(create_app(runs)).get(f"/api/runs/{record.id}/station-assembly")
    assert response.status_code == 200
    assert response.json()["assembled_bog_sha256"] == manifest["assembled_bog_sha256"]
    service.approve(record.id, "Alex Engineer")
    assert service.export_path(record.id) == Path(record.assembled_bog_path)


def test_service_requires_station_template_when_assembly_is_selected(tmp_path: Path) -> None:
    job = demo_job()
    assert job.deliverables.shop_profile is not None
    job.deliverables.shop_profile.station_template_mode = "insert"

    with pytest.raises(ValueError, match="requires a contractor station BOG"):
        WorkbenchService(RunRepository(tmp_path / "runs")).create_run(job)
