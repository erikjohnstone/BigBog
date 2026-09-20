import io
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from bactalk.api import create_app
from bactalk.demo import demo_job, generalist_demo_job
from bactalk.domain import (
    AcceptanceCase,
    Block,
    BlockKind,
    ControlGraph,
    DataType,
    JobSpec,
    Link,
    OutputExpectation,
    PointRole,
    PointSpec,
    RunStatus,
    SequenceSpec,
)
from bactalk.projects import (
    EquipmentRelationship,
    ProjectAcceptanceCase,
    ProjectAcceptancePhase,
    ProjectBuildRepository,
    ProjectBuildService,
    ProjectOutputExpectation,
    ProjectPreflight,
    ProjectSignalBinding,
    ProjectSpec,
)
from bactalk.repository import RunRepository
from bactalk.service import ApprovalRequiredError, ArtifactChangedError, WorkbenchService


def _project() -> ProjectSpec:
    vav = demo_job().model_copy(update={"equipment_name": "VAV_1"})
    ahu = generalist_demo_job().model_copy(update={"equipment_name": "AHU_1", "site": vav.site})
    return ProjectSpec(
        name="Office building",
        site=vav.site,
        equipment=[vav, ahu],
        relationships=[EquipmentRelationship(source="AHU_1", relation="feeds", target="VAV_1")],
    )


def _station_template() -> bytes:
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<bajaObjectGraph version="4.0">
  <p t="b:UnrestrictedFolder" m="b=baja">
    <p n="Config" t="b:Folder" h="1">
      <p n="Drivers" t="b:Folder">
        <p n="BACnetNetwork" t="b:Folder">
          <p n="ExampleCampus" t="b:Folder" h="2"/>
        </p>
      </p>
    </p>
    <p n="Services" t="b:Folder" h="3"/>
  </p>
</bajaObjectGraph>"""
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("file.xml", xml)
    return target.getvalue()


def _signal_job(
    equipment: str,
    input_name: str,
    output_name: str,
    *,
    input_role: PointRole = PointRole.SENSOR,
) -> JobSpec:
    graph = ControlGraph(
        name=equipment,
        blocks=[
            Block(
                id=input_name,
                kind=BlockKind.BOOLEAN_INPUT,
                label=input_name,
                config={"default": False},
            ),
            Block(id=output_name, kind=BlockKind.BOOLEAN_OUTPUT, label=output_name),
        ],
        links=[Link(source=input_name, target=output_name, target_slot="in")],
    )
    return JobSpec(
        name=f"{equipment} controls",
        site="Signal Campus",
        equipment_name=equipment,
        sequence=SequenceSpec(family="CUSTOM", version="test"),
        points=[
            PointSpec(
                name=input_name,
                label=input_name,
                data_type=DataType.BOOLEAN,
                role=input_role,
                default=False,
            ),
            PointSpec(
                name=output_name,
                label=output_name,
                data_type=DataType.BOOLEAN,
                role=PointRole.COMMAND,
                default=False,
            ),
        ],
        control_graph=graph,
        acceptance_tests=[
            AcceptanceCase(
                name="Pass through",
                inputs={input_name: True},
                expectations=[OutputExpectation(target=output_name, value=True)],
            )
        ],
    )


def _signal_project(*, assembly: bool = False) -> ProjectSpec:
    ahu = _signal_job("AHU_1", "Occupied", "HeatingPlantRequest")
    plant = _signal_job(
        "BoilerPlant_1",
        "HeatingPlantRequest",
        "BoilerEnable",
        input_role=PointRole.STATUS,
    )
    return ProjectSpec(
        name="Integrated heating request",
        site="Signal Campus",
        equipment=[ahu, plant],
        signal_bindings=[
            ProjectSignalBinding(
                source_equipment="AHU_1",
                source_point="HeatingPlantRequest",
                target_equipment="BoilerPlant_1",
                target_point="HeatingPlantRequest",
            )
        ],
        acceptance_tests=[
            ProjectAcceptanceCase(
                name="AHU request propagates to plant",
                phases=[
                    ProjectAcceptancePhase(
                        name="unoccupied",
                        inputs={"AHU_1.Occupied": False},
                        expectations=[
                            ProjectOutputExpectation(
                                equipment="BoilerPlant_1",
                                point="BoilerEnable",
                                value=False,
                            )
                        ],
                    ),
                    ProjectAcceptancePhase(
                        name="occupied",
                        inputs={"AHU_1.Occupied": True},
                        expectations=[
                            ProjectOutputExpectation(
                                equipment="BoilerPlant_1",
                                point="BoilerEnable",
                                value=True,
                            )
                        ],
                    ),
                ],
            )
        ],
        station_assembly_mode="insert" if assembly else "none",
    )


def test_multi_equipment_project_preflight_matches_installed_packs() -> None:
    project = _project()

    report = ProjectPreflight().assess(project)

    assert report["accepted_for_build"] is True
    assert report["production_ready"] is False
    assert report["equipment_count"] == 2
    assert {item["pack_id"] for item in report["equipment"]} == {
        "ahu-safety-cooling-v1",
        "g36-vav-reheat-mvp",
    }


def test_project_rejects_unknown_relationship_target() -> None:
    job = demo_job()
    with pytest.raises(ValidationError, match="unknown equipment"):
        ProjectSpec(
            name="Bad topology",
            site=job.site,
            equipment=[job],
            relationships=[
                EquipmentRelationship(
                    source=job.equipment_name,
                    relation="feeds",
                    target="MISSING",
                )
            ],
        )


def test_project_build_requires_approval_and_exports_every_equipment(
    tmp_path: Path,
) -> None:
    workbench = WorkbenchService(RunRepository(tmp_path / "runs"))
    service = ProjectBuildService(
        ProjectBuildRepository(tmp_path / "projects"),
        workbench,
    )

    record = service.build(_project())

    assert record.status == RunStatus.READY_FOR_REVIEW
    assert len(record.equipment_runs) == 2
    with pytest.raises(ApprovalRequiredError):
        service.export_path(record.id)

    approved = service.approve(record.id, "Controls Engineer")
    bundle = service.export_path(record.id)

    assert approved.status == RunStatus.APPROVED
    assert approved.approval is not None
    with zipfile.ZipFile(bundle) as archive:
        names = set(archive.namelist())
    assert "project-spec.json" in names
    assert "project-test-report.json" in names
    assert "project-manifest.json" in names
    assert any(name.startswith("equipment/AHU_1/") for name in names)
    assert any(name.startswith("equipment/VAV_1/") for name in names)
    assert "equipment/VAV_1/nhaystack/expected-readback.zinc" in names
    assert "equipment/VAV_1/bacnet-lab/acceptance-scenarios.json" in names
    assert "equipment/VAV_1/deliverables/niagara-graphics-plan.json" in names
    assert sum(name.endswith(".bog") for name in names) == 2


def test_project_approval_rejects_tampered_child_artifact(tmp_path: Path) -> None:
    run_repository = RunRepository(tmp_path / "runs")
    service = ProjectBuildService(
        ProjectBuildRepository(tmp_path / "projects"),
        WorkbenchService(run_repository),
    )
    record = service.build(_project())
    child = run_repository.get(record.equipment_runs[0].run_id)
    Path(child.graph_path).write_text("{}\n", encoding="utf-8")

    with pytest.raises(ArtifactChangedError):
        service.approve(record.id, "Controls Engineer")


def test_project_atomically_assembles_every_equipment_into_one_station(
    tmp_path: Path,
) -> None:
    workbench = WorkbenchService(RunRepository(tmp_path / "runs"))
    service = ProjectBuildService(
        ProjectBuildRepository(tmp_path / "projects"),
        workbench,
    )
    project = _project().model_copy(update={"station_assembly_mode": "insert"})

    record = service.build(project, station_template=_station_template())

    assert record.assembled_station_path is not None
    assert record.station_assembly_manifest_path is not None
    manifest = json.loads(
        Path(record.station_assembly_manifest_path).read_text(encoding="utf-8")
    )
    assert manifest["program_count"] == 2
    assert manifest["safety"]["atomic_artifact_generation"] is True
    with zipfile.ZipFile(record.assembled_station_path) as archive:
        root = ElementTree.fromstring(archive.read("file.xml"))
    names = {item.get("n") for item in root.iter() if item.get("n")}
    assert {"AHU_1", "VAV_1", "Services"} <= names

    service.approve(record.id, "Controls Engineer")
    with zipfile.ZipFile(service.export_path(record.id)) as archive:
        exported = set(archive.namelist())
    assert "assembled-station.bog" in exported
    assert "station-assembly.json" in exported


def test_project_build_import_api_accepts_station_template(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))
    project = _project().model_copy(update={"station_assembly_mode": "insert"})

    response = client.post(
        "/api/projects/build-import",
        data={"project_json": project.model_dump_json()},
        files={
            "station_template": (
                "station.bog",
                _station_template(),
                "application/zip",
            )
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["assembled_station_path"].endswith("assembled-station.bog")


def test_project_station_assembly_requires_matching_template_contract(tmp_path: Path) -> None:
    service = ProjectBuildService(
        ProjectBuildRepository(tmp_path / "projects"),
        WorkbenchService(RunRepository(tmp_path / "runs")),
    )

    with pytest.raises(ValueError, match="requires a contractor station BOG"):
        service.build(_project().model_copy(update={"station_assembly_mode": "insert"}))
    with pytest.raises(ValueError, match="requires project station_assembly_mode"):
        service.build(_project(), station_template=_station_template())


def test_cross_equipment_signal_is_tested_and_compiled_into_station(tmp_path: Path) -> None:
    service = ProjectBuildService(
        ProjectBuildRepository(tmp_path / "projects"),
        WorkbenchService(RunRepository(tmp_path / "runs")),
    )

    record = service.build(_signal_project(assembly=True), station_template=_station_template())

    assert record.status == RunStatus.READY_FOR_REVIEW
    report = json.loads(Path(record.project_report_path).read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert report["coverage"]["signal_binding_count"] == 1
    assert report["scenarios"][0]["assertions"][-1]["observed"] == "True"

    manifest = json.loads(
        Path(record.station_assembly_manifest_path).read_text(encoding="utf-8")
    )
    assert manifest["cross_program_link_count"] == 1
    link = manifest["cross_program_links"][0]
    assert link["source_ord"].endswith("/AHU_1/HeatingPlantRequest")
    assert link["target_ord"].endswith("/BoilerPlant_1/HeatingPlantRequest")
    assert link["target_slot"] == "in16"

    with zipfile.ZipFile(record.assembled_station_path) as archive:
        root = ElementTree.fromstring(archive.read("file.xml"))
    plant_program = next(item for item in root.iter() if item.get("n") == "BoilerPlant_1")
    target = next(
        item for item in plant_program if item.get("n") == "HeatingPlantRequest"
    )
    compiled_links = [item for item in target if item.get("t") == "b:Link"]
    assert len(compiled_links) == 1
    properties = {item.get("n"): item.get("v") for item in compiled_links[0]}
    assert properties["sourceOrd"] == link["source_handle"]
    assert properties["targetSlotName"] == "in16"


def test_cross_equipment_binding_requires_independent_acceptance_oracle() -> None:
    project = _signal_project()
    with pytest.raises(ValidationError, match="require project acceptance tests"):
        ProjectSpec.model_validate(
            {**project.model_dump(mode="json"), "acceptance_tests": []}
        )
