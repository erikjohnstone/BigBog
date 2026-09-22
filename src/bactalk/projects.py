from __future__ import annotations

import hashlib
import json
import zipfile
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bactalk.capabilities import CapabilityRegistry
from bactalk.compiler import NiagaraCompiler
from bactalk.domain import (
    Approval,
    ComparisonOperator,
    ControlGraph,
    DataType,
    JobSpec,
    PointRole,
    RunStatus,
    TestReport,
    canonical_json,
    safe_component_name,
)
from bactalk.intake import validate_template_bog
from bactalk.integrations.niagara_station import (
    NiagaraProgramAggregation,
    NiagaraProgramLink,
    assemble_project_station_bog,
)
from bactalk.project_simulator import run_project_acceptance_suite
from bactalk.service import ApprovalRequiredError, ArtifactChangedError, WorkbenchService


class EquipmentRelationship(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    relation: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    target: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")


class ProjectSignalBinding(BaseModel):
    """One typed, directed signal between two independently compiled programs."""

    model_config = ConfigDict(extra="forbid")

    source_equipment: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    source_point: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    target_equipment: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    target_point: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")


class ProjectSignalSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equipment: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    point: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")


class ProjectSignalAggregation(BaseModel):
    """Several programs' outputs reduced into one program input (G36 request counts:
    the zones' reset requests are summed at the AHU, the AHUs' plant requests at the
    plant). ``sum`` and ``max`` for numeric and integer points, ``any`` for booleans.
    In the assembled station this becomes a chain of kitControl Add (or Or) blocks
    under a ``Requests`` folder of the target program (GOAL-NATIVE-BOG.md N8 step 5)."""

    model_config = ConfigDict(extra="forbid")

    target_equipment: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    target_point: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    sources: list[ProjectSignalSource] = Field(min_length=1, max_length=10_000)
    reduce: Literal["sum", "max", "any"] = "sum"


class ProjectOutputExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equipment: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    point: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    operator: ComparisonOperator = ComparisonOperator.EQUAL
    value: float | bool
    upper: float | None = None
    tolerance: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def validate_range(self) -> ProjectOutputExpectation:
        if self.operator == ComparisonOperator.BETWEEN:
            if isinstance(self.value, bool) or self.upper is None:
                raise ValueError("between expectations require numeric value and upper")
            if float(self.value) > self.upper:
                raise ValueError("between expectation value cannot exceed upper")
        elif self.upper is not None:
            raise ValueError("upper is only valid for a between expectation")
        return self


class ProjectAcceptancePhase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    inputs: dict[str, float | bool] = Field(default_factory=dict)
    repeat: int = Field(default=1, ge=1, le=1_000_000)
    step_seconds: float = Field(default=1.0, gt=0.0, le=86_400.0)
    expectations: list[ProjectOutputExpectation] = Field(min_length=1)

    @model_validator(mode="after")
    def qualified_inputs(self) -> ProjectAcceptancePhase:
        for key in self.inputs:
            if not _qualified_point(key):
                raise ValueError("project acceptance inputs must use EquipmentName.PointName keys")
        return self


class ProjectAcceptanceCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    phases: list[ProjectAcceptancePhase] = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def unique_phases(self) -> ProjectAcceptanceCase:
        names = [phase.name for phase in self.phases]
        if len(names) != len(set(names)):
            raise ValueError("project acceptance phase names must be unique")
        return self


def _qualified_point(value: str) -> tuple[str, str] | None:
    parts = value.split(".")
    if len(parts) != 2:
        return None
    equipment, point = parts
    valid = all(
        name and (name[0].isalpha() or name[0] == "_") and name.replace("_", "").isalnum()
        for name in parts
    )
    return (equipment, point) if valid else None


class ProjectSpec(BaseModel):
    """Whole-building intake contract composed from equipment programming jobs."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    site: str = Field(min_length=1, max_length=200)
    equipment: list[JobSpec] = Field(min_length=1, max_length=10_000)
    relationships: list[EquipmentRelationship] = Field(default_factory=list)
    signal_bindings: list[ProjectSignalBinding] = Field(default_factory=list, max_length=100_000)
    signal_aggregations: list[ProjectSignalAggregation] = Field(
        default_factory=list, max_length=100_000
    )
    acceptance_tests: list[ProjectAcceptanceCase] = Field(default_factory=list, max_length=10_000)
    station_assembly_mode: Literal["none", "insert", "replace"] = "none"

    @model_validator(mode="after")
    def validate_topology(self) -> ProjectSpec:
        names = [item.equipment_name for item in self.equipment]
        if len(names) != len(set(names)):
            raise ValueError("equipment names must be unique within a project")
        wrong_site = [item.equipment_name for item in self.equipment if item.site != self.site]
        if wrong_site:
            raise ValueError(
                "equipment jobs must use the project site: " + ", ".join(sorted(wrong_site))
            )
        conflicting_modes = [
            item.equipment_name
            for item in self.equipment
            if item.deliverables.shop_profile is not None
            and item.deliverables.shop_profile.station_template_mode != "compare_only"
        ]
        if conflicting_modes:
            raise ValueError(
                "project equipment must leave station_template_mode at compare_only; use the "
                "project station_assembly_mode: " + ", ".join(sorted(conflicting_modes))
            )
        known = set(names)
        seen: set[tuple[str, str, str]] = set()
        for relation in self.relationships:
            if relation.source not in known or relation.target not in known:
                raise ValueError(
                    f"relationship references unknown equipment: "
                    f"{relation.source} -> {relation.target}"
                )
            key = (relation.source, relation.relation, relation.target)
            if key in seen:
                raise ValueError("project relationships must be unique")
            seen.add(key)
        self._validate_signal_contracts()
        return self

    def _validate_signal_contracts(self) -> None:
        jobs = {item.equipment_name: item for item in self.equipment}
        incoming_targets: set[tuple[str, str]] = set()
        adjacency: dict[str, set[str]] = defaultdict(set)
        indegree = {name: 0 for name in jobs}
        for binding in self.signal_bindings:
            if binding.source_equipment == binding.target_equipment:
                raise ValueError("project signal bindings must connect different equipment")
            source_job = jobs.get(binding.source_equipment)
            target_job = jobs.get(binding.target_equipment)
            if source_job is None or target_job is None:
                raise ValueError("project signal binding references unknown equipment")
            source = next(
                (point for point in source_job.points if point.name == binding.source_point), None
            )
            target = next(
                (point for point in target_job.points if point.name == binding.target_point), None
            )
            if source is None or target is None:
                raise ValueError("project signal binding references an unknown point")
            if source.role not in {PointRole.COMMAND, PointRole.ALARM}:
                raise ValueError(
                    f"signal source {binding.source_equipment}.{binding.source_point} "
                    "must be a command or alarm output"
                )
            if target.role not in {PointRole.SENSOR, PointRole.SETPOINT, PointRole.STATUS}:
                raise ValueError(
                    f"signal target {binding.target_equipment}.{binding.target_point} "
                    "must be an input"
                )
            if source.data_type != target.data_type:
                raise ValueError("project signal binding source and target types must match")
            if target.bacnet_object is not None or target.niagara_ord is not None:
                raise ValueError(
                    f"bound target {binding.target_equipment}.{binding.target_point} cannot also "
                    "be driven by BACnet or an external Niagara ORD"
                )
            if any(
                schedule.output_point == target.name
                for schedule in target_job.deliverables.schedules
            ):
                raise ValueError(
                    f"bound target {binding.target_equipment}.{binding.target_point} cannot also "
                    "be schedule-driven"
                )
            target_key = (binding.target_equipment, binding.target_point)
            if target_key in incoming_targets:
                raise ValueError("project signal target has multiple drivers")
            incoming_targets.add(target_key)
            if binding.target_equipment not in adjacency[binding.source_equipment]:
                adjacency[binding.source_equipment].add(binding.target_equipment)
                indegree[binding.target_equipment] += 1
        for aggregation in self.signal_aggregations:
            target_job = jobs.get(aggregation.target_equipment)
            if target_job is None:
                raise ValueError("project signal aggregation references unknown equipment")
            target = next(
                (p for p in target_job.points if p.name == aggregation.target_point), None
            )
            if target is None:
                raise ValueError("project signal aggregation references an unknown point")
            if target.role not in {PointRole.SENSOR, PointRole.SETPOINT, PointRole.STATUS}:
                raise ValueError(
                    f"aggregation target {aggregation.target_equipment}."
                    f"{aggregation.target_point} must be an input"
                )
            if aggregation.reduce == "any":
                if target.data_type != DataType.BOOLEAN:
                    raise ValueError("an 'any' aggregation needs a boolean target")
            elif target.data_type is not DataType.NUMERIC:
                raise ValueError(f"a '{aggregation.reduce}' aggregation needs a numeric target")
            if target.bacnet_object is not None or target.niagara_ord is not None:
                raise ValueError(
                    f"aggregated target {aggregation.target_equipment}."
                    f"{aggregation.target_point} cannot also be driven by BACnet or an ORD"
                )
            target_key = (aggregation.target_equipment, aggregation.target_point)
            if target_key in incoming_targets:
                raise ValueError("project signal target has multiple drivers")
            incoming_targets.add(target_key)
            seen_sources: set[tuple[str, str]] = set()
            for source in aggregation.sources:
                if source.equipment == aggregation.target_equipment:
                    raise ValueError("project signal aggregations must connect different equipment")
                source_job = jobs.get(source.equipment)
                if source_job is None:
                    raise ValueError("project signal aggregation references unknown equipment")
                point = next((p for p in source_job.points if p.name == source.point), None)
                if point is None:
                    raise ValueError("project signal aggregation references an unknown point")
                if point.role not in {PointRole.COMMAND, PointRole.ALARM}:
                    raise ValueError(
                        f"aggregation source {source.equipment}.{source.point} "
                        "must be a command or alarm output"
                    )
                if point.data_type != target.data_type:
                    raise ValueError("aggregation source and target types must match")
                if (source.equipment, source.point) in seen_sources:
                    raise ValueError("aggregation sources must be unique")
                seen_sources.add((source.equipment, source.point))
                if aggregation.target_equipment not in adjacency[source.equipment]:
                    adjacency[source.equipment].add(aggregation.target_equipment)
                    indegree[aggregation.target_equipment] += 1

        queue = deque(name for name, degree in indegree.items() if degree == 0)
        visited = 0
        while queue:
            current = queue.popleft()
            visited += 1
            for target in adjacency[current]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    queue.append(target)
        if visited != len(jobs):
            raise ValueError("project signal bindings contain an equipment cycle")
        if (self.signal_bindings or self.signal_aggregations) and not self.acceptance_tests:
            raise ValueError("cross-equipment signal bindings require project acceptance tests")

        outputs_by_job = {
            job.equipment_name: {
                point.name: point
                for point in job.points
                if point.role in {PointRole.COMMAND, PointRole.ALARM}
            }
            for job in self.equipment
        }
        covered: set[tuple[str, str]] = set()
        for case in self.acceptance_tests:
            current_inputs: set[str] = set()
            for phase in case.phases:
                for qualified, value in phase.inputs.items():
                    parsed = _qualified_point(qualified)
                    if parsed is None:
                        raise ValueError("invalid qualified project input")
                    equipment_name, point_name = parsed
                    job = jobs.get(equipment_name)
                    point = (
                        next((item for item in job.points if item.name == point_name), None)
                        if job is not None
                        else None
                    )
                    if point is None or point.role in {PointRole.COMMAND, PointRole.ALARM}:
                        raise ValueError(f"project input {qualified} is not an equipment input")
                    if (equipment_name, point_name) in incoming_targets:
                        raise ValueError(f"project input {qualified} is driven by a signal binding")
                    expected_type = point.data_type
                    if (expected_type == DataType.BOOLEAN) != isinstance(value, bool):
                        raise ValueError(f"project input {qualified} has the wrong data type")
                    current_inputs.add(qualified)
                for expectation in phase.expectations:
                    point = outputs_by_job.get(expectation.equipment, {}).get(expectation.point)
                    if point is None:
                        raise ValueError(
                            f"project expectation {expectation.equipment}.{expectation.point} "
                            "is not an equipment output"
                        )
                    if (point.data_type == DataType.BOOLEAN) != isinstance(expectation.value, bool):
                        raise ValueError("project expectation has the wrong data type")
                    if point.data_type == DataType.BOOLEAN and expectation.operator not in {
                        ComparisonOperator.EQUAL,
                        ComparisonOperator.NOT_EQUAL,
                    }:
                        raise ValueError("boolean project expectations only support eq or ne")
                    covered.add((expectation.equipment, expectation.point))
        if self.signal_bindings or self.signal_aggregations:
            downstream = {
                (target_equipment, point_name)
                for target_equipment in {
                    *(binding.target_equipment for binding in self.signal_bindings),
                    *(item.target_equipment for item in self.signal_aggregations),
                }
                for point_name in outputs_by_job[target_equipment]
            }
            unobserved = sorted(downstream - covered)
            if unobserved:
                names = ", ".join(f"{equipment}.{point}" for equipment, point in unobserved)
                raise ValueError(
                    "project acceptance tests do not observe downstream outputs: " + names
                )


class ProjectPreflight:
    """Fail-closed capability assessment before a whole-building build is accepted."""

    def __init__(self, registry: CapabilityRegistry | None = None):
        self.registry = registry or CapabilityRegistry()
        self.compiler = NiagaraCompiler()

    def assess(self, project: ProjectSpec) -> dict[str, Any]:
        equipment: list[dict[str, Any]] = []
        accepted = True
        for job in project.equipment:
            pack = self.registry.match_job(job)
            blockers: list[str] = []
            if pack is None:
                blockers.append(
                    f"No installed pack or supplied typed graph for {job.sequence.family!r}."
                )
            if project.station_assembly_mode != "none" and job.sequence.library is not None:
                blockers.append(
                    "Plant-library ProgramObject source packages require licensed Workbench "
                    "compilation before whole-station BOG assembly."
                )
            if job.control_graph is not None:
                unsupported = sorted(
                    {
                        block.kind.value
                        for block in job.control_graph.blocks
                        if block.kind not in self.compiler.SLOT_NAMES
                    }
                )
                if unsupported:
                    blockers.append(
                        "Niagara compiler does not lower blocks: " + ", ".join(unsupported)
                    )
            if blockers:
                accepted = False
            equipment.append(
                {
                    "equipment_name": job.equipment_name,
                    "sequence_family": job.sequence.family,
                    "pack_id": pack.id if pack else None,
                    "pack_stage": pack.stage if pack else None,
                    "preflight_passed": not blockers,
                    "blockers": blockers,
                }
            )
        return {
            "accepted_for_build": accepted,
            "production_ready": False,
            "project": project.name,
            "site": project.site,
            "equipment_count": len(project.equipment),
            "relationship_count": len(project.relationships),
            "signal_binding_count": len(project.signal_bindings),
            "signal_aggregation_count": len(project.signal_aggregations),
            "project_acceptance_case_count": len(project.acceptance_tests),
            "equipment": equipment,
            "next_gate": (
                "Typed cross-equipment acceptance and offline Niagara links run during the "
                "build; dynamic building physics and licensed-runtime testing remain."
            ),
        }


class EquipmentBuild(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equipment_name: str
    run_id: str
    status: RunStatus
    artifact_sha256: str


class ProjectBuildRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    project: ProjectSpec
    status: RunStatus
    equipment_runs: list[EquipmentBuild]
    project_path: str
    project_report_path: str | None = None
    manifest_path: str
    station_template_path: str | None = None
    assembled_station_path: str | None = None
    station_assembly_manifest_path: str | None = None
    artifact_sha256: str
    approval: Approval | None = None


class ProjectBuildRepository:
    """Small file-backed repository for whole-building build manifests."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def directory(self, project_id: str) -> Path:
        if not project_id.isalnum():
            raise ValueError("invalid project id")
        return self.root / project_id

    def save(self, record: ProjectBuildRecord) -> None:
        manifest = Path(record.manifest_path)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(canonical_json(record), encoding="utf-8")

    def get(self, project_id: str) -> ProjectBuildRecord:
        manifest = self.directory(project_id) / "manifest.json"
        if not manifest.exists():
            raise KeyError(project_id)
        return ProjectBuildRecord.model_validate_json(manifest.read_text(encoding="utf-8"))

    def list(self) -> list[ProjectBuildRecord]:
        records: list[ProjectBuildRecord] = []
        for manifest in self.root.glob("*/manifest.json"):
            try:
                records.append(
                    ProjectBuildRecord.model_validate_json(manifest.read_text(encoding="utf-8"))
                )
            except (ValueError, json.JSONDecodeError):
                continue
        return sorted(records, key=lambda item: item.created_at, reverse=True)


class ProjectBuildService:
    """Build, sign, approve, and export a set of independently tested programs."""

    def __init__(
        self,
        repository: ProjectBuildRepository,
        workbench: WorkbenchService,
        registry: CapabilityRegistry | None = None,
    ):
        self.repository = repository
        self.workbench = workbench
        self.preflight = ProjectPreflight(registry)

    def build(
        self,
        project: ProjectSpec,
        *,
        station_template: bytes | None = None,
    ) -> ProjectBuildRecord:
        preflight = self.preflight.assess(project)
        if not preflight["accepted_for_build"]:
            blockers = [blocker for item in preflight["equipment"] for blocker in item["blockers"]]
            raise ValueError("project preflight failed: " + "; ".join(blockers))
        if project.station_assembly_mode == "none" and station_template is not None:
            raise ValueError("station template requires project station_assembly_mode")
        if project.station_assembly_mode != "none" and station_template is None:
            raise ValueError("project station assembly requires a contractor station BOG")
        if station_template is not None:
            validate_template_bog(station_template)

        provisional_id = uuid4().hex[:12]
        project_dir = self.repository.directory(provisional_id)
        project_dir.mkdir(parents=True, exist_ok=False)
        project_path = project_dir / "project-spec.json"
        manifest_path = project_dir / "manifest.json"
        project_path.write_text(canonical_json(project), encoding="utf-8")

        equipment_runs: list[EquipmentBuild] = []
        graphs: dict[str, ControlGraph] = {}
        status = RunStatus.READY_FOR_REVIEW
        for job in project.equipment:
            run = self.workbench.create_run(job)
            if run.status != RunStatus.READY_FOR_REVIEW:
                status = RunStatus.FAILED
            equipment_runs.append(
                EquipmentBuild(
                    equipment_name=job.equipment_name,
                    run_id=run.id,
                    status=run.status,
                    artifact_sha256=run.artifact_sha256,
                )
            )
            graphs[job.equipment_name] = ControlGraph.model_validate_json(
                Path(run.graph_path).read_text(encoding="utf-8")
            )

        project_report: TestReport = run_project_acceptance_suite(project, graphs)
        project_report_path = project_dir / "project-test-report.json"
        project_report_path.write_text(canonical_json(project_report), encoding="utf-8")
        if not project_report.passed:
            status = RunStatus.FAILED

        station_template_path: Path | None = None
        assembled_station_path: Path | None = None
        station_assembly_manifest_path: Path | None = None
        if station_template is not None:
            station_template_path = project_dir / "contractor-station-template.bog"
            station_template_path.write_bytes(station_template)
            jobs = {job.equipment_name: job for job in project.equipment}
            programs: list[tuple[bytes, JobSpec, ControlGraph]] = []
            for equipment in equipment_runs:
                run = self.workbench.repository.get(equipment.run_id)
                graph = graphs[equipment.equipment_name]
                if run.bog_path is None:
                    raise ValueError(
                        "project station assembly requires compiled Niagara BOG artifacts; "
                        f"{equipment.equipment_name} produced a ProgramObject source package"
                    )
                programs.append(
                    (
                        Path(run.bog_path).read_bytes(),
                        jobs[equipment.equipment_name],
                        graph,
                    )
                )
            assembly = assemble_project_station_bog(
                station_template,
                programs,
                mode=project.station_assembly_mode,
                program_links=[
                    NiagaraProgramLink(
                        source_equipment=binding.source_equipment,
                        source_point=binding.source_point,
                        target_equipment=binding.target_equipment,
                        target_point=binding.target_point,
                        data_type=next(
                            point.data_type.value
                            for job in project.equipment
                            if job.equipment_name == binding.source_equipment
                            for point in job.points
                            if point.name == binding.source_point
                        ),
                    )
                    for binding in project.signal_bindings
                ],
                program_aggregations=[
                    NiagaraProgramAggregation(
                        target_equipment=item.target_equipment,
                        target_point=item.target_point,
                        sources=tuple((s.equipment, s.point) for s in item.sources),
                        reduce=item.reduce,
                        data_type=next(
                            point.data_type.value
                            for job in project.equipment
                            if job.equipment_name == item.target_equipment
                            for point in job.points
                            if point.name == item.target_point
                        ),
                    )
                    for item in project.signal_aggregations
                ],
            )
            assembled_station_path = project_dir / "assembled-station.bog"
            assembled_station_path.write_bytes(assembly.content)
            station_assembly_manifest_path = project_dir / "station-assembly.json"
            station_assembly_manifest_path.write_text(
                canonical_json(assembly.manifest),
                encoding="utf-8",
            )

        project_artifacts = [
            path
            for path in (
                station_template_path,
                assembled_station_path,
                station_assembly_manifest_path,
                project_report_path,
            )
            if path is not None
        ]
        digest = self._project_digest(project_path, equipment_runs, project_artifacts)
        record = ProjectBuildRecord(
            id=provisional_id,
            project=project,
            status=status,
            equipment_runs=equipment_runs,
            project_path=str(project_path),
            project_report_path=str(project_report_path),
            manifest_path=str(manifest_path),
            station_template_path=(
                str(station_template_path) if station_template_path is not None else None
            ),
            assembled_station_path=(
                str(assembled_station_path) if assembled_station_path is not None else None
            ),
            station_assembly_manifest_path=(
                str(station_assembly_manifest_path)
                if station_assembly_manifest_path is not None
                else None
            ),
            artifact_sha256=digest,
        )
        self.repository.save(record)
        return record

    def approve(
        self,
        project_id: str,
        reviewer: str,
        *,
        actor_id: str | None = None,
        tenant_id: str | None = None,
        authentication: str = "self-asserted-local",
    ) -> ProjectBuildRecord:
        record = self.repository.get(project_id)
        if record.status != RunStatus.READY_FOR_REVIEW:
            raise ApprovalRequiredError("only a passing project build can be approved")
        self._verify_integrity(record)
        for equipment in record.equipment_runs:
            self.workbench.approve(
                equipment.run_id,
                reviewer,
                actor_id=actor_id,
                tenant_id=tenant_id,
                authentication=authentication,
            )
        approved = record.model_copy(
            update={
                "status": RunStatus.APPROVED,
                "approval": Approval(
                    reviewer=reviewer,
                    actor_id=actor_id,
                    tenant_id=tenant_id,
                    authentication=authentication,
                    artifact_sha256=record.artifact_sha256,
                ),
                "equipment_runs": [
                    item.model_copy(update={"status": RunStatus.APPROVED})
                    for item in record.equipment_runs
                ],
            }
        )
        self.repository.save(approved)
        return approved

    def export_path(self, project_id: str) -> Path:
        record = self.repository.get(project_id)
        if record.status != RunStatus.APPROVED or record.approval is None:
            raise ApprovalRequiredError("human approval is required before project export")
        self._verify_integrity(record)
        destination = self.repository.directory(project_id) / (
            safe_component_name(record.project.name) + ".zip"
        )
        entries: dict[str, bytes] = {
            "project-spec.json": Path(record.project_path).read_bytes(),
            "project-manifest.json": canonical_json(record).encode(),
        }
        if record.project_report_path is not None:
            entries["project-test-report.json"] = Path(record.project_report_path).read_bytes()
        for name, value in (
            ("contractor-station-template.bog", record.station_template_path),
            ("assembled-station.bog", record.assembled_station_path),
            ("station-assembly.json", record.station_assembly_manifest_path),
        ):
            if value is not None:
                entries[name] = Path(value).read_bytes()
        for equipment in sorted(record.equipment_runs, key=lambda item: item.equipment_name):
            run = self.workbench.repository.get(equipment.run_id)
            prefix = f"equipment/{safe_component_name(equipment.equipment_name)}"
            run_dir = Path(run.manifest_path).parent
            for path in self._run_artifact_paths(run):
                relative = path.relative_to(run_dir).as_posix()
                entries[f"{prefix}/{relative}"] = path.read_bytes()
            entries[f"{prefix}/run-manifest.json"] = canonical_json(run).encode()
        self._write_deterministic_zip(destination, entries)
        return destination

    def _verify_integrity(self, record: ProjectBuildRecord) -> None:
        equipment: list[EquipmentBuild] = []
        for expected in record.equipment_runs:
            actual = self.workbench.verify_integrity(expected.run_id)
            if actual.artifact_sha256 != expected.artifact_sha256:
                raise ArtifactChangedError(
                    f"equipment artifact changed after build: {expected.equipment_name}"
                )
            equipment.append(expected)
        project_artifacts = [
            Path(value)
            for value in (
                record.station_template_path,
                record.assembled_station_path,
                record.station_assembly_manifest_path,
                record.project_report_path,
            )
            if value is not None
        ]
        current = self._project_digest(Path(record.project_path), equipment, project_artifacts)
        if current != record.artifact_sha256:
            raise ArtifactChangedError("project artifact changed after validation")
        if record.approval and record.approval.artifact_sha256 != current:
            raise ArtifactChangedError("project approval does not match current artifacts")

    @staticmethod
    def _project_digest(
        project_path: Path,
        equipment_runs: list[EquipmentBuild],
        project_artifacts: list[Path] | None = None,
    ) -> str:
        digest = hashlib.sha256()
        digest.update(b"project-spec.json\0")
        digest.update(project_path.read_bytes())
        for item in sorted(equipment_runs, key=lambda value: value.equipment_name):
            digest.update(item.equipment_name.encode())
            digest.update(b"\0")
            digest.update(item.artifact_sha256.encode())
        for path in sorted(project_artifacts or [], key=lambda item: item.name):
            digest.update(path.name.encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
        return digest.hexdigest()

    @staticmethod
    def _run_artifact_paths(run: Any) -> list[Path]:
        paths = [
            Path(run.job_path),
            Path(run.graph_path),
            Path(run.report_path),
            Path(run.semantic_model_path),
            Path(run.semantic_validation_path),
        ]
        target = run.target_artifact_path or run.bog_path
        if target:
            paths.append(Path(target))
        optional = [
            run.template_bog_path,
            run.template_analysis_path,
            run.assembled_bog_path,
            run.station_assembly_manifest_path,
        ]
        paths.extend(Path(path) for path in optional if path)
        paths.extend(Path(path) for path in run.volttron_artifact_paths)
        paths.extend(Path(path) for path in run.nhaystack_artifact_paths)
        paths.extend(Path(path) for path in run.bacnet_lab_artifact_paths)
        paths.extend(Path(path) for path in run.environment_artifact_paths)
        paths.extend(Path(path) for path in run.source_artifact_paths)
        paths.extend(Path(path) for path in run.deliverable_artifact_paths)
        if run.deliverable_manifest_path:
            paths.append(Path(run.deliverable_manifest_path))
        return paths

    @staticmethod
    def _write_deterministic_zip(destination: Path, entries: dict[str, bytes]) -> None:
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(entries):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, entries[name])
