from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from bactalk.demo import demo_job
from bactalk.domain import (
    AcceptanceCase,
    DataType,
    JobSpec,
    OutputExpectation,
    PointRole,
    PointSpec,
    RunStatus,
    SequenceSpec,
    TargetArtifactKind,
)
from bactalk.repository import RunRepository
from bactalk.service import (
    ApprovalRequiredError,
    ArtifactChangedError,
    WorkbenchService,
)


def test_run_creates_valid_bog_and_requires_approval(tmp_path: Path) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))

    record = service.create_run(demo_job())

    assert record.status == RunStatus.READY_FOR_REVIEW
    assert Path(record.graph_path).is_file()
    assert Path(record.report_path).is_file()
    assert record.deliverable_manifest_path is not None
    assert Path(record.deliverable_manifest_path).is_file()
    assert len(record.deliverable_artifact_paths) == 15
    assert record.volttron_manifest_path is not None
    assert Path(record.volttron_manifest_path).is_file()
    assert len(record.volttron_artifact_paths) == 3
    assert record.nhaystack_manifest_path is not None
    assert Path(record.nhaystack_manifest_path).is_file()
    assert len(record.nhaystack_artifact_paths) == 5
    assert record.bacnet_lab_manifest_path is not None
    assert Path(record.bacnet_lab_manifest_path).is_file()
    assert len(record.bacnet_lab_artifact_paths) == 10
    assert zipfile.is_zipfile(record.bog_path)
    with zipfile.ZipFile(record.bog_path) as archive:
        assert archive.namelist() == ["file.xml"]
        assert b"kitControl:NumericSwitch" in archive.read("file.xml")
        assert b"sch:BooleanSchedule" in archive.read("file.xml")
        assert b"h:NumericIntervalHistoryExt" in archive.read("file.xml")

    with pytest.raises(ApprovalRequiredError):
        service.export_path(record.id)
    with pytest.raises(ApprovalRequiredError):
        service.review_bundle_path(record.id)

    approved = service.approve(record.id, "Alex Engineer")
    assert approved.status == RunStatus.APPROVED
    assert approved.approval is not None
    assert approved.approval.artifact_sha256 == record.artifact_sha256
    assert service.export_path(record.id) == Path(record.bog_path)
    bundle = service.review_bundle_path(record.id)
    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()
        assert "deliverables/manifest.json" in names
        assert "deliverables/point-map.csv" in names
        assert "deliverables/niagara-alarm-plan.json" in names
        assert "deliverables/BactalkAlarmInstaller_VAV_12.java" in names
        assert "deliverables/BactalkPointBinder_VAV_12.java" in names
        assert "deliverables/niagara-point-bindings.json" in names
        assert "nhaystack/expected-readback.zinc" in names
        assert "nhaystack/verification.json" in names
        assert "bacnet-lab/devices/120012.json" in names
        assert "bacnet-lab/acceptance-scenarios.json" in names
        assert "control-graph.json" in names
        assert "test-report.json" in names
        assert "run-manifest.json" in names


def test_plant_library_job_runs_tests_and_exports_signed_program_source_package(
    tmp_path: Path,
) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    job = JobSpec(
        name="Plant hold controller",
        site="Qualification lab",
        equipment_name="PlantHold",
        sequence=SequenceSpec(
            family="LBNL_PLANT_CONTROLLER",
            version="Pinned LBNL Modelica Buildings source",
            library="plant_controls",
            controller_id="Utilities.HoldReal",
            parameters={"dtHol": 3.0},
        ),
        points=[
            PointSpec(
                name="u",
                label="Value",
                data_type=DataType.NUMERIC,
                role=PointRole.SENSOR,
                default=0.0,
            ),
            PointSpec(
                name="u1",
                label="Trigger",
                data_type=DataType.BOOLEAN,
                role=PointRole.SENSOR,
                default=False,
            ),
            PointSpec(
                name="y",
                label="Held value",
                data_type=DataType.NUMERIC,
                role=PointRole.COMMAND,
                default=0.0,
            ),
        ],
        acceptance_tests=[
            AcceptanceCase(
                name="passes input while not held",
                inputs={"u": 10.0, "u1": False},
                expectations=[OutputExpectation(target="y", value=10.0)],
            )
        ],
    )

    record = service.create_run(job)

    # Since N4 a library controller whose kinds have native rows exports one .bog;
    # the ProgramObject package survives only for blocked graphs behind the
    # expert flag (tests/test_native_bog_emit.py).
    assert record.status == RunStatus.READY_FOR_REVIEW
    assert record.target_artifact_kind == TargetArtifactKind.NIAGARA_BOG
    assert record.program_package_path is None
    assert record.bog_path == record.target_artifact_path
    assert record.bog_path is not None
    deliverables = json.loads(Path(record.deliverable_manifest_path).read_text())
    assert deliverables["coverage"]["logic"]["artifact_kind"] == "niagara_bog"
    with zipfile.ZipFile(record.bog_path) as archive:
        assert archive.namelist() == ["file.xml"]
    lowering = json.loads((Path(record.bog_path).parent / "niagara-lowering.json").read_text())
    assert lowering["lane"].startswith("native")

    service.approve(record.id, "Alex Engineer")
    assert service.export_path(record.id) == Path(record.bog_path)


def test_g36_library_controller_enters_the_same_human_gated_job_lane(
    tmp_path: Path,
) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    job = JobSpec(
        name="G36 supply signal controller",
        site="Qualification lab",
        equipment_name="AHU_SupplySignals",
        sequence=SequenceSpec(
            family="LBNL_G36_CONTROLLER",
            version="Pinned LBNL Modelica Buildings G36 source",
            library="g36",
            controller_id="AHUs.MultiZone.VAV.SetPoints.SupplySignals",
        ),
        points=[
            PointSpec(
                name="TAirSup",
                label="Supply air temperature",
                data_type=DataType.NUMERIC,
                role=PointRole.SENSOR,
                default=292.15,
            ),
            PointSpec(
                name="TAirSupSet",
                label="Supply air temperature setpoint",
                data_type=DataType.NUMERIC,
                role=PointRole.SETPOINT,
                default=290.15,
            ),
            PointSpec(
                name="u1SupFan",
                label="Supply fan proven",
                data_type=DataType.BOOLEAN,
                role=PointRole.STATUS,
                default=True,
            ),
            *[
                PointSpec(
                    name=name,
                    label=name,
                    data_type=DataType.NUMERIC,
                    role=PointRole.COMMAND,
                    default=0.0,
                )
                for name in ("uTSup", "yCooCoi", "yHeaCoi")
            ],
        ],
        acceptance_tests=[
            AcceptanceCase(
                name="bounded first scan",
                inputs={
                    "TAirSup": 292.15,
                    "TAirSupSet": 290.15,
                    "u1SupFan": True,
                },
                expectations=[
                    OutputExpectation(target="uTSup", value=0.0, tolerance=1e-12),
                    OutputExpectation(target="yCooCoi", value=0.0, tolerance=1e-12),
                    OutputExpectation(target="yHeaCoi", value=0.0, tolerance=1e-12),
                ],
            )
        ],
    )

    record = service.create_run(job)

    assert record.status == RunStatus.READY_FOR_REVIEW
    assert record.target_artifact_kind == TargetArtifactKind.NIAGARA_BOG
    assert record.bog_path is not None and record.program_package_path is None
    emit = json.loads((Path(record.bog_path).parent / "niagara-emit.json").read_text())
    assert emit["graph"] and emit["component_count"] > 0
    assert "bactalkG36:PIDWithReset" in emit["module_types"]


def test_artifact_tampering_invalidates_approval(tmp_path: Path) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    record = service.create_run(demo_job())
    service.approve(record.id, "Alex Engineer")

    with Path(record.report_path).open("a", encoding="utf-8") as stream:
        stream.write("\n")

    with pytest.raises(ArtifactChangedError):
        service.export_path(record.id)


def test_volttron_artifact_tampering_invalidates_approval(tmp_path: Path) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    record = service.create_run(demo_job())
    service.approve(record.id, "Alex Engineer")

    registry_path = next(
        Path(path) for path in record.volttron_artifact_paths if path.endswith(".csv")
    )
    with registry_path.open("a", encoding="utf-8") as stream:
        stream.write("tampered\n")

    with pytest.raises(ArtifactChangedError):
        service.export_path(record.id)


def test_deliverable_tampering_invalidates_approval(tmp_path: Path) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    record = service.create_run(demo_job())
    service.approve(record.id, "Alex Engineer")

    graphics = next(
        Path(path)
        for path in record.deliverable_artifact_paths
        if path.endswith("graphics-model.json")
    )
    with graphics.open("a", encoding="utf-8") as stream:
        stream.write("tampered\n")

    with pytest.raises(ArtifactChangedError):
        service.review_bundle_path(record.id)


def test_retained_source_document_is_signed_and_tampering_invalidates_approval(
    tmp_path: Path,
) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    record = service.create_run(
        demo_job(),
        source_documents={"points-contractor.csv": b"name,data_type\nZoneTemp,numeric\n"},
    )

    assert len(record.source_artifact_paths) == 1
    source_path = Path(record.source_artifact_paths[0])
    assert source_path.read_bytes().startswith(b"name,data_type")
    service.approve(record.id, "Alex Engineer")
    source_path.write_bytes(b"tampered")

    with pytest.raises(ArtifactChangedError):
        service.export_path(record.id)


def test_failed_materialization_leaves_no_partial_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = RunRepository(tmp_path / "runs")
    service = WorkbenchService(repository)

    def fail_compile(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected compiler failure")

    monkeypatch.setattr(service.compiler, "compile", fail_compile)
    with pytest.raises(RuntimeError, match="injected compiler failure"):
        service.create_run(demo_job())

    assert repository.list() == []
    assert list(repository.root.iterdir()) == []


def test_successful_materialization_is_atomically_promoted(tmp_path: Path) -> None:
    repository = RunRepository(tmp_path / "runs")
    service = WorkbenchService(repository)

    record = service.create_run(demo_job())

    assert Path(record.manifest_path).parent == repository.run_directory(record.id)
    recorded_strings = [
        value
        for value in record.model_dump(mode="json").values()
        if isinstance(value, str)
    ]
    assert all(".staging" not in path for path in recorded_strings)
    assert not any(path.name.endswith(".staging") for path in repository.root.iterdir())
    service.verify_integrity(record.id)


def test_rejected_candidate_is_retained_and_cannot_be_approved_or_exported(
    tmp_path: Path,
) -> None:
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    record = service.create_run(demo_job())

    rejected = service.reject(record.id, "Alex Engineer", "Point mapping needs correction")

    assert rejected.status == RunStatus.REJECTED
    assert rejected.rejection is not None
    assert rejected.rejection.reason == "Point mapping needs correction"
    assert rejected.rejection.artifact_sha256 == record.artifact_sha256
    with pytest.raises(ApprovalRequiredError):
        service.approve(record.id, "Alex Engineer")
    with pytest.raises(ApprovalRequiredError):
        service.export_path(record.id)
