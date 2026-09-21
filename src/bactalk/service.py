from __future__ import annotations

import hashlib
import math
import os
import re
import shutil
import tempfile
import zipfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from bactalk.agent import ControlsPlanner, ProgrammingAgent, SequencePackPlanner
from bactalk.compiler import NiagaraCompiler
from bactalk.deliverables import build_deliverable_package
from bactalk.domain import (
    Approval,
    ControlGraph,
    JobSpec,
    Rejection,
    RunOrigin,
    RunRecord,
    RunStatus,
    TargetArtifactKind,
    TestReport,
    canonical_json,
    graph_changes,
)
from bactalk.intake import validate_template_bog
from bactalk.integrations.alfalfa import AlfalfaClientLike
from bactalk.integrations.alfalfa_bacnet import (
    AlfalfaBacnetGraphRunner,
    prepare_runtime_bacnet_lab,
)
from bactalk.integrations.alfalfa_graph import (
    AlfalfaCancellationCheck,
    AlfalfaGraphMap,
    AlfalfaGraphRunner,
    AlfalfaProgressCallback,
    AlfalfaQualificationCancelled,
    AlfalfaTrajectoryOracle,
)
from bactalk.integrations.bacnet_lab import build_bacnet_lab_export
from bactalk.integrations.boptest_graph import (
    BoptestCancellationCheck,
    BoptestGraphMap,
    BoptestGraphRunner,
    BoptestProgressCallback,
    BoptestQualificationCancelled,
    BoptestQualificationCase,
    BoptestRuntime,
    BoptestScenario,
    BoptestTrajectoryOracle,
)
from bactalk.integrations.brick import build_and_validate_brick
from bactalk.integrations.environment_pack import inspect_environment_pack
from bactalk.integrations.fmi import inspect_fmu_archive
from bactalk.integrations.funnel import FunnelScorer
from bactalk.integrations.nhaystack import build_readonly_nhaystack_export
from bactalk.integrations.niagara_program_codegen import NiagaraProgramPackageBuilder
from bactalk.integrations.niagara_station import assemble_station_bog
from bactalk.integrations.niagara_template import NiagaraTemplateAnalyzer
from bactalk.integrations.plant_controls_library import PlantControlsLibrary
from bactalk.integrations.volttron import build_readonly_volttron_export
from bactalk.niagara.lowering import LoweringPolicy, plan_lowering
from bactalk.niagara.module import declared_types
from bactalk.niagara.validate import validate_bog
from bactalk.repository import RunRepository


class ApprovalRequiredError(RuntimeError):
    pass


class ArtifactChangedError(RuntimeError):
    pass


MAX_SOURCE_DOCUMENTS = 16
MAX_SOURCE_DOCUMENT_BYTES = 50 * 1024 * 1024
MAX_ALFALFA_MODEL_BYTES = 512 * 1024 * 1024


def _safe_source_name(value: str) -> str:
    """Return a stable, path-safe evidence filename without trusting user paths."""

    basename = Path(value).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", basename).strip("._")
    if not cleaned:
        raise ValueError("source document filename is empty after normalization")
    return cleaned[:200]


def artifact_hash(*paths: Path) -> str:
    if not paths:
        raise ValueError("at least one artifact is required")
    resolved = [path.resolve() for path in paths]
    common = Path(os.path.commonpath([str(path.parent) for path in resolved]))
    digest = hashlib.sha256()
    for path in sorted(resolved, key=lambda item: item.relative_to(common).as_posix()):
        name = path.relative_to(common).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


class WorkbenchService:
    def __init__(
        self,
        repository: RunRepository,
        *,
        planner: ControlsPlanner | None = None,
        max_attempts: int = 3,
    ):
        self.repository = repository
        self.compiler = NiagaraCompiler()
        self.template_analyzer = NiagaraTemplateAnalyzer()
        self.plant_controls = PlantControlsLibrary()
        default_planner = SequencePackPlanner(plant_controls=self.plant_controls)
        self.agent = ProgrammingAgent(
            planner or default_planner,
            max_attempts=max_attempts,
        )

    def create_run(
        self,
        job: JobSpec,
        *,
        template_bog: bytes | None = None,
        environment_pack: bytes | None = None,
        source_documents: Mapping[str, bytes] | None = None,
        baseline_graph: ControlGraph | None = None,
        origin: RunOrigin = RunOrigin.CONTRACTOR,
        parent_run_id: str | None = None,
        planner: ControlsPlanner | None = None,
    ) -> RunRecord:
        if template_bog is not None:
            validate_template_bog(template_bog)
        profile = job.deliverables.shop_profile
        assembly_mode = profile.station_template_mode if profile is not None else "compare_only"
        if assembly_mode != "compare_only" and template_bog is None:
            raise ValueError(
                f"station_template_mode={assembly_mode!r} requires a contractor station BOG"
            )
        source_documents = source_documents or {}
        if len(source_documents) > MAX_SOURCE_DOCUMENTS:
            raise ValueError(f"a run accepts at most {MAX_SOURCE_DOCUMENTS} source documents")
        if sum(len(content) for content in source_documents.values()) > MAX_SOURCE_DOCUMENT_BYTES:
            raise ValueError("source documents exceed the 50 MiB aggregate limit")
        agent = (
            ProgrammingAgent(planner, max_attempts=self.agent.max_attempts)
            if planner is not None
            else self.agent
        )
        agent_result = agent.run(job)
        graph = agent_result.graph
        report = agent_result.report
        # GOAL-NATIVE-BOG.md N2/N4: the lowering matrix chooses the lane. Native
        # graphs become one .bog; the ProgramObject package survives only behind
        # the job's expert flag; anything else is refused with its blockers.
        lowering_plan = plan_lowering(
            graph,
            LoweringPolicy(expert_program_objects=job.sequence.expert_program_objects),
        )
        if lowering_plan.lane == "blocked":
            raise ValueError(
                "no native Niagara lowering for this graph: "
                + "; ".join(lowering_plan.blockers)
                + " (set sequence.expert_program_objects to use the ProgramObject lane)"
            )
        requires_program_package = lowering_plan.lane == "program_objects"
        target_artifact_kind = (
            TargetArtifactKind.NIAGARA_PROGRAM_SOURCE_PACKAGE
            if requires_program_package
            else TargetArtifactKind.NIAGARA_BOG
        )
        if requires_program_package and assembly_mode != "compare_only":
            raise ValueError(
                "Niagara ProgramObject source packages require licensed Workbench compilation "
                "before contractor-station assembly; use station_template_mode='compare_only'"
            )

        provisional = RunRecord(
            origin=origin,
            parent_run_id=parent_run_id,
            job=job,
            status=RunStatus.READY_FOR_REVIEW if report.passed else RunStatus.FAILED,
            graph_path="",
            target_artifact_kind=target_artifact_kind,
            target_artifact_path=None,
            bog_path=None,
            program_package_path=None,
            report_path="",
            manifest_path="",
            job_path=None,
            template_bog_path=None,
            template_analysis_path=None,
            assembled_bog_path=None,
            station_assembly_manifest_path=None,
            semantic_model_path=None,
            semantic_validation_path=None,
            deliverable_manifest_path=None,
            deliverable_artifact_paths=[],
            volttron_manifest_path=None,
            volttron_artifact_paths=[],
            nhaystack_manifest_path=None,
            nhaystack_artifact_paths=[],
            bacnet_lab_manifest_path=None,
            bacnet_lab_artifact_paths=[],
            environment_pack_path=None,
            environment_manifest_path=None,
            environment_artifact_paths=[],
            source_artifact_paths=[],
            artifact_sha256="",
            changes=(
                graph_changes(baseline_graph, graph)
                if baseline_graph is not None
                else {
                    "added": [block.id for block in graph.blocks],
                    "modified": [],
                    "removed": [],
                }
            ),
            agent_attempts=[item.model_dump(mode="json") for item in agent_result.attempts],
        )
        try:
            return self._materialize_run(
                provisional,
                graph=graph,
                report=report,
                template_bog=template_bog,
                environment_pack=environment_pack,
                source_documents=source_documents,
                baseline_graph=baseline_graph,
            )
        except BaseException:
            self.repository.discard_staged(provisional.id)
            raise

    def _materialize_run(
        self,
        provisional: RunRecord,
        *,
        graph: ControlGraph,
        report: TestReport,
        template_bog: bytes | None,
        environment_pack: bytes | None,
        source_documents: Mapping[str, bytes],
        baseline_graph: ControlGraph | None,
    ) -> RunRecord:
        job = provisional.job
        run_dir = self.repository.begin_staged(provisional.id)
        final_dir = self.repository.run_directory(provisional.id)
        graph_path = run_dir / "control-graph.json"
        bog_path: Path | None = None
        program_package_path: Path | None = None
        if provisional.target_artifact_kind == TargetArtifactKind.NIAGARA_BOG:
            bog_path = run_dir / f"{graph.name}.bog"
        else:
            program_package_path = run_dir / f"{graph.name}-niagara-program-source.zip"
        report_path = run_dir / "test-report.json"
        manifest_path = run_dir / "manifest.json"
        job_path = run_dir / "job-spec.json"
        semantic_model_path = run_dir / "semantic-model.ttl"
        semantic_validation_path = run_dir / "semantic-validation.json"

        job_path.write_text(canonical_json(job), encoding="utf-8")
        graph_path.write_text(canonical_json(graph), encoding="utf-8")
        report_path.write_text(canonical_json(report), encoding="utf-8")
        # GOAL-NATIVE-BOG.md N2: record which lane the lowering matrix assigns
        # this graph. The artifact choice itself moves to the matrix in N4.
        lowering_plan = plan_lowering(
            graph,
            LoweringPolicy(expert_program_objects=job.sequence.expert_program_objects),
        )
        (run_dir / "niagara-lowering.json").write_text(
            canonical_json(lowering_plan.to_dict()), encoding="utf-8"
        )
        environment_definition = (
            inspect_environment_pack(environment_pack, template_bog=template_bog)
            if environment_pack is not None
            else None
        )
        if bog_path is not None:
            self.compiler.compile(
                graph,
                bog_path,
                deliverables=job.deliverables,
                environment=(
                    environment_definition.descriptor
                    if environment_definition is not None
                    else None
                ),
                units={point.name: point.units for point in job.points},
                points=job.points,
                report_directory=run_dir,
            )
            # GOAL-NATIVE-BOG.md N1: nothing ships that fails static validation.
            validation = validate_bog(
                bog_path, declared_types=declared_types(), label=bog_path.name
            )
            (run_dir / "niagara-validation.json").write_text(
                canonical_json(validation.to_dict()), encoding="utf-8"
            )
            validation.raise_for_errors()
        else:
            if program_package_path is None or job.sequence.controller_id is None:
                raise AssertionError("program source package target is incomplete")
            program_package_path.write_bytes(
                NiagaraProgramPackageBuilder().build(
                    graph,
                    controller_id=job.sequence.controller_id,
                )
            )
        semantic = build_and_validate_brick(job)
        if not semantic.conforms:
            raise ValueError(f"Brick semantic validation failed: {semantic.validation_report}")
        semantic_model_path.write_text(semantic.turtle, encoding="utf-8")
        semantic_validation_path.write_text(
            canonical_json(
                {
                    "conforms": semantic.conforms,
                    "triples": semantic.triples,
                    "report": semantic.validation_report,
                }
            ),
            encoding="utf-8",
        )
        deliverables_dir = run_dir / "deliverables"
        deliverables_dir.mkdir()
        deliverable_package = build_deliverable_package(
            job,
            graph,
            report,
            environment=environment_definition,
            target_artifact_kind=provisional.target_artifact_kind.value,
        )
        deliverable_artifact_paths: list[Path] = []
        for artifact in deliverable_package.artifacts:
            path = deliverables_dir / artifact.relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(artifact.content)
            deliverable_artifact_paths.append(path)
        deliverable_manifest_path = deliverables_dir / "manifest.json"
        deliverable_manifest_path.write_text(
            canonical_json(deliverable_package.manifest),
            encoding="utf-8",
        )
        signed_paths = [
            job_path,
            graph_path,
            bog_path or program_package_path,
            report_path,
            semantic_model_path,
            semantic_validation_path,
            deliverable_manifest_path,
            *deliverable_artifact_paths,
        ]
        source_artifact_paths: list[Path] = []
        if source_documents:
            source_dir = run_dir / "sources"
            source_dir.mkdir()
            used_names: set[str] = set()
            for original_name, content in sorted(source_documents.items()):
                safe_name = _safe_source_name(original_name)
                if safe_name in used_names:
                    raise ValueError(f"duplicate normalized source document filename: {safe_name}")
                used_names.add(safe_name)
                path = source_dir / safe_name
                path.write_bytes(content)
                source_artifact_paths.append(path)
            signed_paths.extend(source_artifact_paths)
        volttron_manifest_path: Path | None = None
        volttron_artifact_paths: list[Path] = []
        volttron_export = build_readonly_volttron_export(job)
        if volttron_export is not None:
            volttron_dir = run_dir / "volttron"
            volttron_dir.mkdir()
            for artifact in volttron_export.artifacts:
                path = volttron_dir / artifact.relative_path
                path.write_text(artifact.content, encoding="utf-8")
                volttron_artifact_paths.append(path)
            volttron_manifest_path = volttron_dir / "manifest.json"
            volttron_manifest_path.write_text(
                canonical_json(volttron_export.manifest),
                encoding="utf-8",
            )
            volttron_artifact_paths.append(volttron_manifest_path)
            signed_paths.extend(volttron_artifact_paths)
        nhaystack_dir = run_dir / "nhaystack"
        nhaystack_dir.mkdir()
        nhaystack_export = build_readonly_nhaystack_export(job, graph)
        nhaystack_artifact_paths: list[Path] = []
        for artifact in nhaystack_export.artifacts:
            path = nhaystack_dir / artifact.relative_path
            path.write_text(artifact.content, encoding="utf-8")
            nhaystack_artifact_paths.append(path)
        nhaystack_manifest_path = nhaystack_dir / "manifest.json"
        nhaystack_manifest_path.write_text(
            canonical_json(nhaystack_export.manifest),
            encoding="utf-8",
        )
        nhaystack_artifact_paths.append(nhaystack_manifest_path)
        signed_paths.extend(nhaystack_artifact_paths)
        bacnet_lab_manifest_path: Path | None = None
        bacnet_lab_artifact_paths: list[Path] = []
        bacnet_lab_export = build_bacnet_lab_export(job)
        if bacnet_lab_export is not None:
            bacnet_lab_dir = run_dir / "bacnet-lab"
            bacnet_lab_dir.mkdir()
            for artifact in bacnet_lab_export.artifacts:
                path = bacnet_lab_dir / artifact.relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(artifact.content, encoding="utf-8")
                bacnet_lab_artifact_paths.append(path)
            bacnet_lab_manifest_path = bacnet_lab_dir / "manifest.json"
            bacnet_lab_manifest_path.write_text(
                canonical_json(bacnet_lab_export.manifest),
                encoding="utf-8",
            )
            bacnet_lab_artifact_paths.append(bacnet_lab_manifest_path)
            signed_paths.extend(bacnet_lab_artifact_paths)
        environment_pack_path: Path | None = None
        environment_manifest_path: Path | None = None
        environment_artifact_paths: list[Path] = []
        if environment_pack is not None:
            environment_export = inspect_environment_pack(
                environment_pack,
                generated_bog=bog_path.read_bytes() if bog_path is not None else None,
                template_bog=template_bog,
            )
            environment_dir = run_dir / "environment"
            environment_dir.mkdir()
            environment_pack_path = environment_dir / "contractor-environment-pack.zip"
            environment_pack_path.write_bytes(environment_pack)
            environment_artifact_paths.append(environment_pack_path)
            for artifact in environment_export.artifacts:
                path = environment_dir / artifact.relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(artifact.content)
                environment_artifact_paths.append(path)
            environment_manifest_path = environment_dir / "manifest.json"
            environment_manifest_path.write_text(
                canonical_json(environment_export.manifest),
                encoding="utf-8",
            )
            environment_artifact_paths.append(environment_manifest_path)
            signed_paths.extend(environment_artifact_paths)
        template_bog_path: Path | None = None
        template_analysis_path: Path | None = None
        assembled_bog_path: Path | None = None
        station_assembly_manifest_path: Path | None = None
        changes = provisional.changes
        if template_bog is not None:
            template_bog_path = run_dir / "contractor-template.bog"
            template_bog_path.write_bytes(template_bog)
            analysis: dict[str, object] = {
                "baseline": self.template_analyzer.summarize(template_bog_path),
            }
            profile = job.deliverables.shop_profile
            assembly_mode = profile.station_template_mode if profile is not None else "compare_only"
            if bog_path is None:
                analysis.update(
                    {
                        "program_comparison": None,
                        "comparison": None,
                        "reason": (
                            "The generated target is a Niagara ProgramObject source package. "
                            "Compile it in the licensed target Workbench before BOG comparison "
                            "or station assembly."
                        ),
                    }
                )
            else:
                program_comparison = self.template_analyzer.compare(template_bog_path, bog_path)
                analysis.update(
                    {
                        "program_comparison": program_comparison,
                        "comparison": program_comparison,
                    }
                )
            if assembly_mode != "compare_only" and bog_path is not None:
                assembly = assemble_station_bog(
                    template_bog,
                    bog_path.read_bytes(),
                    job,
                    graph,
                    mode=assembly_mode,
                )
                assembled_bog_path = run_dir / "assembled-station.bog"
                assembled_bog_path.write_bytes(assembly.content)
                # The contractor's template brings station types the catalog
                # does not hold; structure, handles and links are still checked.
                validate_bog(
                    assembled_bog_path,
                    require_known_types=False,
                    label=assembled_bog_path.name,
                ).raise_for_errors()
                station_assembly_manifest_path = run_dir / "station-assembly.json"
                station_assembly_manifest_path.write_text(
                    canonical_json(assembly.manifest),
                    encoding="utf-8",
                )
                assembled_comparison = self.template_analyzer.compare(
                    template_bog_path,
                    assembled_bog_path,
                )
                analysis["assembled"] = self.template_analyzer.summarize(assembled_bog_path)
                analysis["assembled_comparison"] = assembled_comparison
                analysis["comparison"] = assembled_comparison
            template_analysis_path = run_dir / "template-analysis.json"
            template_analysis_path.write_text(canonical_json(analysis), encoding="utf-8")
            comparison = analysis["comparison"]
            if baseline_graph is None and comparison is not None:
                changes = {
                    "added": [item["path"] for item in comparison["added"]],
                    "modified": [item["key"]["path"] for item in comparison["modified"]],
                    "removed": [item["path"] for item in comparison["removed"]],
                }
            signed_paths.extend([template_bog_path, template_analysis_path])
            if assembled_bog_path is not None and station_assembly_manifest_path is not None:
                signed_paths.extend([assembled_bog_path, station_assembly_manifest_path])
        digest = artifact_hash(*signed_paths)

        def final_path(path: Path) -> str:
            return str(final_dir / path.relative_to(run_dir))

        target_artifact_path = bog_path or program_package_path
        if target_artifact_path is None:
            raise AssertionError("run target artifact was not materialized")

        record = provisional.model_copy(
            update={
                "graph_path": final_path(graph_path),
                "target_artifact_path": final_path(target_artifact_path),
                "bog_path": final_path(bog_path) if bog_path is not None else None,
                "program_package_path": (
                    final_path(program_package_path)
                    if program_package_path is not None
                    else None
                ),
                "report_path": final_path(report_path),
                "manifest_path": final_path(manifest_path),
                "job_path": final_path(job_path),
                "template_bog_path": (
                    final_path(template_bog_path) if template_bog_path else None
                ),
                "template_analysis_path": (
                    final_path(template_analysis_path) if template_analysis_path else None
                ),
                "assembled_bog_path": (
                    final_path(assembled_bog_path) if assembled_bog_path else None
                ),
                "station_assembly_manifest_path": (
                    final_path(station_assembly_manifest_path)
                    if station_assembly_manifest_path
                    else None
                ),
                "semantic_model_path": final_path(semantic_model_path),
                "semantic_validation_path": final_path(semantic_validation_path),
                "deliverable_manifest_path": final_path(deliverable_manifest_path),
                "deliverable_artifact_paths": [
                    final_path(path) for path in deliverable_artifact_paths
                ],
                "volttron_manifest_path": (
                    final_path(volttron_manifest_path) if volttron_manifest_path else None
                ),
                "volttron_artifact_paths": [
                    final_path(path) for path in volttron_artifact_paths
                ],
                "nhaystack_manifest_path": final_path(nhaystack_manifest_path),
                "nhaystack_artifact_paths": [
                    final_path(path) for path in nhaystack_artifact_paths
                ],
                "bacnet_lab_manifest_path": (
                    final_path(bacnet_lab_manifest_path) if bacnet_lab_manifest_path else None
                ),
                "bacnet_lab_artifact_paths": [
                    final_path(path) for path in bacnet_lab_artifact_paths
                ],
                "environment_pack_path": (
                    final_path(environment_pack_path) if environment_pack_path else None
                ),
                "environment_manifest_path": (
                    final_path(environment_manifest_path) if environment_manifest_path else None
                ),
                "environment_artifact_paths": [
                    final_path(path) for path in environment_artifact_paths
                ],
                "source_artifact_paths": [final_path(path) for path in source_artifact_paths],
                "artifact_sha256": digest,
                "changes": changes,
            }
        )
        self.repository.commit_staged(run_dir, record)
        return record

    @staticmethod
    def _validate_boptest_oracles(oracles: list[BoptestTrajectoryOracle]) -> None:
        if not oracles:
            raise ValueError("BOPTEST qualification requires at least one trajectory oracle")
        oracle_ids = [oracle.id for oracle in oracles]
        if len(oracle_ids) != len(set(oracle_ids)):
            raise ValueError("BOPTEST trajectory oracle ids must be unique")

    @classmethod
    def _score_boptest_oracles(
        cls,
        runtime_evidence: dict[str, object],
        oracles: list[BoptestTrajectoryOracle],
        output_root: Path,
        *,
        scorer: FunnelScorer | None = None,
    ) -> tuple[list[dict[str, object]], dict[str, object], bool]:
        cls._validate_boptest_oracles(oracles)
        raw_trajectory = runtime_evidence.get("trajectory")
        if not isinstance(raw_trajectory, list) or not raw_trajectory:
            raise ValueError("BOPTEST runtime evidence has no valid trajectory clock")
        first = raw_trajectory[0]
        if not isinstance(first, dict) or not isinstance(
            first.get("start_time"), (int, float)
        ):
            raise ValueError("BOPTEST runtime trajectory has an invalid start clock")
        oracle_time_origin = float(first["start_time"])
        test_times: list[float] = []
        for sample in raw_trajectory:
            if not isinstance(sample, dict) or not isinstance(
                sample.get("end_time"), (int, float)
            ):
                raise ValueError("BOPTEST runtime trajectory has an invalid sample clock")
            test_times.append(float(sample["end_time"]) - oracle_time_origin)

        scorer = scorer or FunnelScorer()
        oracle_results: list[dict[str, object]] = []
        for index, oracle in enumerate(oracles, start=1):
            test_values: list[float] = []
            section = (
                "controller_outputs"
                if oracle.signal_kind == "graph_output"
                else "measurements"
            )
            for sample in raw_trajectory:
                if not isinstance(sample, dict) or not isinstance(sample.get(section), dict):
                    raise ValueError(f"BOPTEST trajectory section {section!r} is invalid")
                signals = sample[section]
                if oracle.signal not in signals:
                    raise ValueError(
                        f"BOPTEST trajectory does not contain {oracle.signal_kind} "
                        f"signal {oracle.signal!r}"
                    )
                raw = signals[oracle.signal]
                if isinstance(raw, bool):
                    value = float(raw)
                elif isinstance(raw, (int, float)):
                    value = float(raw)
                else:
                    raise ValueError(
                        f"BOPTEST oracle signal {oracle.signal!r} is not numeric"
                    )
                if not math.isfinite(value):
                    raise ValueError(
                        f"BOPTEST oracle signal {oracle.signal!r} is not finite"
                    )
                test_values.append(value)
            output_directory = output_root / f"oracle-{index:03d}-{oracle.id}"
            result = scorer.compare(
                oracle.reference_times,
                oracle.reference_values,
                test_times,
                test_values,
                output_directory,
                absolute_time_tolerance=oracle.absolute_time_tolerance,
                absolute_value_tolerance=oracle.absolute_value_tolerance,
            )
            counterexample = result.counterexample(test_times, test_values)
            if counterexample is not None:
                (output_directory / "counterexample.json").write_text(
                    canonical_json(
                        {
                            "schema": "bactalk.oracle-counterexample/v1",
                            "oracle": oracle.model_dump(mode="json"),
                            "counterexample": counterexample,
                        }
                    ),
                    encoding="utf-8",
                )
            oracle_results.append(
                {
                    "oracle": oracle.model_dump(mode="json"),
                    "test_times": test_times,
                    "test_values": test_values,
                    "pyfunnel_status_code": result.status_code,
                    "completed": result.completed,
                    "passed": result.passed,
                    "max_error": result.max_error,
                    "counterexample": counterexample,
                    "report_directory": output_directory.name,
                }
            )
        clock: dict[str, object] = {
            "basis": "elapsed_seconds_from_run_start",
            "runtime_time_origin": oracle_time_origin,
        }
        return (
            oracle_results,
            clock,
            all(bool(item["passed"]) for item in oracle_results),
        )

    def qualify_with_boptest(
        self,
        run_id: str,
        *,
        client: BoptestRuntime,
        mapping: BoptestGraphMap,
        oracles: list[BoptestTrajectoryOracle] | None = None,
        steps: int | None = None,
        step_seconds: float | None = None,
        start_time: float = 0.0,
        warmup_period: float = 0.0,
        scenario: BoptestScenario | None = None,
        cases: list[BoptestQualificationCase] | None = None,
        scorer: FunnelScorer | None = None,
        progress_callback: BoptestProgressCallback | None = None,
        cancellation_requested: BoptestCancellationCheck | None = None,
        expected_artifact_sha256: str | None = None,
    ) -> RunRecord:
        """Attach signed, pass/fail BOPTEST evidence to an undecided run.

        Qualification is append-once.  The exact graph already signed on the
        run is executed against BOPTEST, independent trajectory oracles are
        scored with pyfunnel, and every generated report becomes part of the
        artifact digest that a later human approval signs.
        """

        record = self.repository.get(run_id)
        if (
            expected_artifact_sha256 is not None
            and record.artifact_sha256 != expected_artifact_sha256
        ):
            raise ArtifactChangedError(
                "candidate changed after BOPTEST qualification was submitted"
            )
        if record.status != RunStatus.READY_FOR_REVIEW:
            raise ApprovalRequiredError(
                "BOPTEST qualification requires a passing candidate awaiting review"
            )
        self._verify_integrity(record)
        if record.boptest_verification_path:
            raise ValueError("BOPTEST qualification is append-once; create a new run to retest")
        suite_mode = bool(cases)
        if suite_mode:
            if (
                oracles is not None
                or steps is not None
                or step_seconds is not None
                or start_time != 0.0
                or warmup_period != 0.0
                or scenario is not None
            ):
                raise ValueError(
                    "BOPTEST suite cases cannot be combined with single-run fields"
                )
            assert cases is not None
            if len(cases) > 50:
                raise ValueError(
                    "BOPTEST qualification suites cannot exceed 50 cases"
                )
            if sum(case.steps for case in cases) > 1_000_000:
                raise ValueError(
                    "BOPTEST qualification suites cannot exceed 1000000 steps"
                )
            case_ids = [case.id for case in cases]
            if len(case_ids) != len(set(case_ids)):
                raise ValueError("BOPTEST qualification case ids must be unique")
        else:
            if cases is not None:
                raise ValueError("BOPTEST qualification cases cannot be empty")
            if oracles is None or steps is None or step_seconds is None:
                raise ValueError(
                    "BOPTEST qualification requires oracles, steps, and step_seconds"
                )
            self._validate_boptest_oracles(oracles)

        graph = ControlGraph.model_validate_json(
            Path(record.graph_path).read_text(encoding="utf-8")
        )
        run_dir = self.repository.run_directory(record.id)
        destination = run_dir / "boptest-verification"
        if destination.exists():
            raise ValueError("BOPTEST verification directory already exists")
        staging = Path(tempfile.mkdtemp(prefix=".boptest-verification.", dir=run_dir))
        scorer = scorer or FunnelScorer()
        try:
            runner = BoptestGraphRunner(client, graph, mapping)
            if suite_mode:
                assert cases is not None
                total_steps = sum(case.steps for case in cases)
                completed_before = 0
                case_results: list[dict[str, object]] = []
                for index, case in enumerate(cases, start=1):
                    if cancellation_requested is not None and cancellation_requested():
                        raise BoptestQualificationCancelled(
                            f"BOPTEST qualification was canceled before case {case.id}"
                        )

                    def case_progress(
                        phase: str,
                        completed: int,
                        _total: int,
                        *,
                        offset: int = completed_before,
                        case_index: int = index,
                    ) -> None:
                        if progress_callback is not None:
                            progress_callback(
                                f"case_{case_index:02d}:{phase}",
                                offset + completed,
                                total_steps,
                            )

                    runtime_evidence = runner.run(
                        steps=case.steps,
                        step_seconds=case.step_seconds,
                        start_time=case.start_time,
                        warmup_period=case.warmup_period,
                        scenario=case.scenario,
                        progress_callback=case_progress,
                        cancellation_requested=cancellation_requested,
                    )
                    if cancellation_requested is not None and cancellation_requested():
                        raise BoptestQualificationCancelled(
                            f"BOPTEST qualification was canceled before scoring case {case.id}"
                        )
                    if progress_callback is not None:
                        progress_callback(
                            f"case_{index:02d}:scoring_oracles",
                            completed_before + case.steps,
                            total_steps,
                        )
                    case_directory = staging / f"case-{index:03d}-{case.id}"
                    oracle_results, oracle_clock, case_passed = (
                        self._score_boptest_oracles(
                            runtime_evidence,
                            case.oracles,
                            case_directory,
                            scorer=scorer,
                        )
                    )
                    case_results.append(
                        {
                            "id": case.id,
                            "status": "pass" if case_passed else "fail",
                            "request": case.model_dump(
                                mode="json", exclude={"oracles"}
                            ),
                            "runtime": runtime_evidence,
                            "oracle_clock": oracle_clock,
                            "oracles": oracle_results,
                            "report_directory": case_directory.name,
                        }
                    )
                    completed_before += case.steps
                passed = all(item["status"] == "pass" for item in case_results)
                evidence = {
                    "schema": "bactalk.boptest-qualification-suite/v1",
                    "status": "pass" if passed else "fail",
                    "run_id": record.id,
                    "artifact_sha256_before_qualification": record.artifact_sha256,
                    "mapping": mapping.model_dump(mode="json"),
                    "case_count": len(case_results),
                    "total_steps": total_steps,
                    "cases": case_results,
                    "approval_allowed": passed,
                    "live_building_writes": False,
                }
            else:
                assert oracles is not None
                assert steps is not None
                assert step_seconds is not None
                runtime_evidence = runner.run(
                    steps=steps,
                    step_seconds=step_seconds,
                    start_time=start_time,
                    warmup_period=warmup_period,
                    scenario=scenario,
                    progress_callback=progress_callback,
                    cancellation_requested=cancellation_requested,
                )
                if cancellation_requested is not None and cancellation_requested():
                    raise BoptestQualificationCancelled(
                        "BOPTEST qualification was canceled before trajectory scoring"
                    )
                if progress_callback is not None:
                    progress_callback("scoring_oracles", steps, steps)
                oracle_results, oracle_clock, passed = self._score_boptest_oracles(
                    runtime_evidence,
                    oracles,
                    staging,
                    scorer=scorer,
                )
                evidence = {
                    "schema": "bactalk.boptest-qualification/v1",
                    "status": "pass" if passed else "fail",
                    "run_id": record.id,
                    "artifact_sha256_before_qualification": record.artifact_sha256,
                    "runtime": runtime_evidence,
                    "oracle_clock": oracle_clock,
                    "oracles": oracle_results,
                    "approval_allowed": passed,
                    "live_building_writes": False,
                }
            evidence_path = staging / "evidence.json"
            evidence_path.write_text(canonical_json(evidence), encoding="utf-8")
            staged_paths = sorted(path for path in staging.rglob("*") if path.is_file())
            os.replace(staging, destination)
        except BaseException:
            if staging.exists():
                shutil.rmtree(staging)
            raise

        final_paths = [destination / path.relative_to(staging) for path in staged_paths]
        final_evidence_path = destination / "evidence.json"
        digest = artifact_hash(*self._record_artifact_paths(record), *final_paths)
        updated = record.model_copy(
            update={
                "status": RunStatus.READY_FOR_REVIEW if passed else RunStatus.FAILED,
                "boptest_verification_path": str(final_evidence_path),
                "verification_artifact_paths": [
                    *record.verification_artifact_paths,
                    *(str(path) for path in final_paths),
                ],
                "artifact_sha256": digest,
            }
        )
        try:
            self.repository.save(updated)
        except BaseException:
            shutil.rmtree(destination)
            raise
        return updated

    @staticmethod
    def _validate_alfalfa_oracles(oracles: list[AlfalfaTrajectoryOracle]) -> None:
        if not oracles:
            raise ValueError("Alfalfa qualification requires at least one trajectory oracle")
        oracle_ids = [oracle.id for oracle in oracles]
        if len(oracle_ids) != len(set(oracle_ids)):
            raise ValueError("Alfalfa trajectory oracle ids must be unique")

    @classmethod
    def _score_alfalfa_oracles(
        cls,
        runtime_evidence: dict[str, object],
        oracles: list[AlfalfaTrajectoryOracle],
        output_root: Path,
        *,
        scorer: FunnelScorer | None = None,
    ) -> tuple[list[dict[str, object]], bool]:
        cls._validate_alfalfa_oracles(oracles)
        raw_trajectory = runtime_evidence.get("trajectory")
        raw_start = runtime_evidence.get("start")
        if not isinstance(raw_trajectory, list) or not isinstance(raw_start, str):
            raise ValueError("Alfalfa runtime evidence has no valid trajectory clock")
        start = datetime.fromisoformat(raw_start)
        test_times: list[float] = []
        for sample in raw_trajectory:
            if not isinstance(sample, dict) or not isinstance(sample.get("end_time"), str):
                raise ValueError("Alfalfa runtime trajectory has an invalid sample clock")
            test_times.append(
                (datetime.fromisoformat(str(sample["end_time"])) - start).total_seconds()
            )
        sections = {
            "graph_input": "graph_inputs",
            "graph_output": "controller_outputs",
            "fmu_input": "fmu_inputs",
            "fmu_output": "observed_outputs",
        }
        scorer = scorer or FunnelScorer()
        results: list[dict[str, object]] = []
        for index, oracle in enumerate(oracles, start=1):
            section = sections[oracle.signal_kind]
            test_values: list[float] = []
            for sample in raw_trajectory:
                if not isinstance(sample, dict) or not isinstance(sample.get(section), dict):
                    raise ValueError(f"Alfalfa trajectory section {section!r} is invalid")
                signals = sample[section]
                if oracle.signal not in signals:
                    raise ValueError(
                        f"Alfalfa trajectory does not contain {oracle.signal_kind} "
                        f"signal {oracle.signal!r}"
                    )
                raw = signals[oracle.signal]
                if isinstance(raw, bool):
                    value = float(raw)
                elif isinstance(raw, (int, float)):
                    value = float(raw)
                else:
                    raise ValueError(
                        f"Alfalfa oracle signal {oracle.signal!r} is not numeric"
                    )
                if not math.isfinite(value):
                    raise ValueError(
                        f"Alfalfa oracle signal {oracle.signal!r} is not finite"
                    )
                test_values.append(value)
            output_directory = output_root / f"oracle-{index:03d}-{oracle.id}"
            comparison = scorer.compare(
                oracle.reference_times,
                oracle.reference_values,
                test_times,
                test_values,
                output_directory,
                absolute_time_tolerance=oracle.absolute_time_tolerance,
                absolute_value_tolerance=oracle.absolute_value_tolerance,
            )
            counterexample = comparison.counterexample(test_times, test_values)
            if counterexample is not None:
                (output_directory / "counterexample.json").write_text(
                    canonical_json(
                        {
                            "schema": "bactalk.oracle-counterexample/v1",
                            "oracle": oracle.model_dump(mode="json"),
                            "counterexample": counterexample,
                        }
                    ),
                    encoding="utf-8",
                )
            results.append(
                {
                    "oracle": oracle.model_dump(mode="json"),
                    "test_times": test_times,
                    "test_values": test_values,
                    "pyfunnel_status_code": comparison.status_code,
                    "completed": comparison.completed,
                    "passed": comparison.passed,
                    "max_error": comparison.max_error,
                    "counterexample": counterexample,
                    "report_directory": output_directory.name,
                }
            )
        return results, all(bool(item["passed"]) for item in results)

    def qualify_with_alfalfa(
        self,
        run_id: str,
        *,
        client: AlfalfaClientLike,
        mapping: AlfalfaGraphMap,
        oracles: list[AlfalfaTrajectoryOracle],
        model_bytes: bytes,
        model_filename: str,
        steps: int,
        step_seconds: float,
        start: datetime,
        server_version: object = None,
        client_version: str | None = None,
        scorer: FunnelScorer | None = None,
        progress_callback: AlfalfaProgressCallback | None = None,
        cancellation_requested: AlfalfaCancellationCheck | None = None,
        expected_artifact_sha256: str | None = None,
    ) -> RunRecord:
        """Attach one signed, graph-coupled Alfalfa FMU run to a candidate.

        The uploaded FMU is admitted into a private staging directory, hashed
        with the exact runtime evidence, and included in the human approval
        boundary. No caller-controlled host path is accepted.
        """

        record = self.repository.get(run_id)
        if (
            expected_artifact_sha256 is not None
            and record.artifact_sha256 != expected_artifact_sha256
        ):
            raise ArtifactChangedError(
                "candidate changed after Alfalfa qualification was submitted"
            )
        if record.status != RunStatus.READY_FOR_REVIEW:
            raise ApprovalRequiredError(
                "Alfalfa qualification requires a passing candidate awaiting review"
            )
        self._verify_integrity(record)
        if record.alfalfa_verification_path:
            raise ValueError(
                "Alfalfa qualification is append-once; create a new run to retest"
            )
        self._validate_alfalfa_oracles(oracles)
        if not model_bytes:
            raise ValueError("Alfalfa FMU is empty")
        if len(model_bytes) > MAX_ALFALFA_MODEL_BYTES:
            raise ValueError(
                f"Alfalfa FMU exceeds the {MAX_ALFALFA_MODEL_BYTES}-byte admission limit"
            )
        safe_name = _safe_source_name(model_filename)
        if Path(safe_name).suffix.lower() != ".fmu":
            raise ValueError("Alfalfa model must use the .fmu extension")

        graph = ControlGraph.model_validate_json(
            Path(record.graph_path).read_text(encoding="utf-8")
        )
        run_dir = self.repository.run_directory(record.id)
        destination = run_dir / "alfalfa-verification"
        if destination.exists():
            raise ValueError("Alfalfa verification directory already exists")
        staging = Path(tempfile.mkdtemp(prefix=".alfalfa-verification.", dir=run_dir))
        try:
            model_path = staging / safe_name
            model_path.write_bytes(model_bytes)
            inspect_fmu_archive(model_path)
            evidence = AlfalfaGraphRunner(client, graph, mapping).run(
                model_path,
                steps=steps,
                step_seconds=step_seconds,
                start=start,
                server_version=server_version,
                client_version=client_version,
                progress_callback=progress_callback,
                cancellation_requested=cancellation_requested,
            )
            if cancellation_requested is not None and cancellation_requested():
                raise AlfalfaQualificationCancelled(
                    "Alfalfa qualification was canceled before trajectory scoring"
                )
            if progress_callback is not None:
                progress_callback("scoring_oracles", steps, steps)
            oracle_results, passed = self._score_alfalfa_oracles(
                evidence,
                oracles,
                staging,
                scorer=scorer,
            )
            evidence.update(
                {
                    "status": "pass" if passed else "fail",
                    "bactalk_run_id": record.id,
                    "artifact_sha256_before_qualification": record.artifact_sha256,
                    "model_original_filename": model_filename,
                    "oracles": oracle_results,
                    "approval_allowed": passed,
                }
            )
            evidence_path = staging / "evidence.json"
            evidence_path.write_text(canonical_json(evidence), encoding="utf-8")
            staged_paths = sorted(path for path in staging.rglob("*") if path.is_file())
            os.replace(staging, destination)
        except BaseException:
            if staging.exists():
                shutil.rmtree(staging)
            raise

        final_paths = [destination / path.relative_to(staging) for path in staged_paths]
        final_evidence_path = destination / "evidence.json"
        digest = artifact_hash(*self._record_artifact_paths(record), *final_paths)
        updated = record.model_copy(
            update={
                "status": RunStatus.READY_FOR_REVIEW if passed else RunStatus.FAILED,
                "alfalfa_verification_path": str(final_evidence_path),
                "verification_artifact_paths": [
                    *record.verification_artifact_paths,
                    *(str(path) for path in final_paths),
                ],
                "artifact_sha256": digest,
            }
        )
        try:
            self.repository.save(updated)
        except BaseException:
            shutil.rmtree(destination)
            raise
        return updated

    async def qualify_with_alfalfa_bacnet(
        self,
        run_id: str,
        *,
        client: AlfalfaClientLike,
        mapping: AlfalfaGraphMap,
        oracles: list[AlfalfaTrajectoryOracle],
        model_bytes: bytes,
        model_filename: str,
        steps: int,
        step_seconds: float,
        start: datetime,
        server_version: object = None,
        client_version: str | None = None,
        scorer: FunnelScorer | None = None,
        progress_callback: AlfalfaProgressCallback | None = None,
        cancellation_requested: AlfalfaCancellationCheck | None = None,
        expected_artifact_sha256: str | None = None,
    ) -> RunRecord:
        """Qualify a graph/FMU loop through the run's signed virtual BACnet devices."""

        record = self.repository.get(run_id)
        if (
            expected_artifact_sha256 is not None
            and record.artifact_sha256 != expected_artifact_sha256
        ):
            raise ArtifactChangedError(
                "candidate changed after Alfalfa qualification was submitted"
            )
        if record.status != RunStatus.READY_FOR_REVIEW:
            raise ApprovalRequiredError(
                "Alfalfa BACnet qualification requires a passing candidate awaiting review"
            )
        self._verify_integrity(record)
        if record.alfalfa_verification_path:
            raise ValueError(
                "Alfalfa qualification is append-once; create a new run to retest"
            )
        if record.bacnet_lab_manifest_path is None:
            raise ValueError(
                "BACnet-coupled Alfalfa qualification requires a mapped BACnet scan"
            )
        self._validate_alfalfa_oracles(oracles)
        if not model_bytes:
            raise ValueError("Alfalfa FMU is empty")
        if len(model_bytes) > MAX_ALFALFA_MODEL_BYTES:
            raise ValueError(
                f"Alfalfa FMU exceeds the {MAX_ALFALFA_MODEL_BYTES}-byte admission limit"
            )
        safe_name = _safe_source_name(model_filename)
        if Path(safe_name).suffix.lower() != ".fmu":
            raise ValueError("Alfalfa model must use the .fmu extension")

        graph = ControlGraph.model_validate_json(
            Path(record.graph_path).read_text(encoding="utf-8")
        )
        run_dir = self.repository.run_directory(record.id)
        destination = run_dir / "alfalfa-verification"
        if destination.exists():
            raise ValueError("Alfalfa verification directory already exists")
        staging = Path(tempfile.mkdtemp(prefix=".alfalfa-verification.", dir=run_dir))
        try:
            model_path = staging / safe_name
            model_path.write_bytes(model_bytes)
            inspect_fmu_archive(model_path)
            lab = prepare_runtime_bacnet_lab(
                Path(record.bacnet_lab_manifest_path),
                staging / "bacnet-runtime",
            )
            evidence = await AlfalfaBacnetGraphRunner(client, graph, mapping, lab).run(
                model_path,
                steps=steps,
                step_seconds=step_seconds,
                start=start,
                server_version=server_version,
                client_version=client_version,
                progress_callback=progress_callback,
                cancellation_requested=cancellation_requested,
            )
            if cancellation_requested is not None and cancellation_requested():
                raise AlfalfaQualificationCancelled(
                    "Alfalfa qualification was canceled before trajectory scoring"
                )
            if progress_callback is not None:
                progress_callback("scoring_oracles", steps, steps)
            oracle_results, passed = self._score_alfalfa_oracles(
                evidence,
                oracles,
                staging,
                scorer=scorer,
            )
            evidence.update(
                {
                    "status": "pass" if passed else "fail",
                    "bactalk_run_id": record.id,
                    "artifact_sha256_before_qualification": record.artifact_sha256,
                    "model_original_filename": model_filename,
                    "oracles": oracle_results,
                    "approval_allowed": passed,
                }
            )
            evidence_path = staging / "evidence.json"
            evidence_path.write_text(canonical_json(evidence), encoding="utf-8")
            staged_paths = sorted(path for path in staging.rglob("*") if path.is_file())
            os.replace(staging, destination)
        except BaseException:
            if staging.exists():
                shutil.rmtree(staging)
            raise

        final_paths = [destination / path.relative_to(staging) for path in staged_paths]
        final_evidence_path = destination / "evidence.json"
        digest = artifact_hash(*self._record_artifact_paths(record), *final_paths)
        updated = record.model_copy(
            update={
                "status": RunStatus.READY_FOR_REVIEW if passed else RunStatus.FAILED,
                "alfalfa_verification_path": str(final_evidence_path),
                "verification_artifact_paths": [
                    *record.verification_artifact_paths,
                    *(str(path) for path in final_paths),
                ],
                "artifact_sha256": digest,
            }
        )
        try:
            self.repository.save(updated)
        except BaseException:
            shutil.rmtree(destination)
            raise
        return updated

    def approve(
        self,
        run_id: str,
        reviewer: str,
        *,
        actor_id: str | None = None,
        tenant_id: str | None = None,
        authentication: str = "self-asserted-local",
        expected_artifact_sha256: str | None = None,
    ) -> RunRecord:
        """Approve one exact artifact on behalf of a named reviewer.

        ``expected_artifact_sha256`` is the digest the reviewer actually
        inspected. When supplied it must equal the candidate's current digest,
        so an artifact that changed between review and approval -- for example
        because a qualification tier appended evidence and re-signed the run --
        is refused instead of being approved unseen.
        """
        record = self.repository.get(run_id)
        if record.status != RunStatus.READY_FOR_REVIEW:
            raise ApprovalRequiredError("only a passing run can be approved")
        self._verify_integrity(record)
        if expected_artifact_sha256 is not None:
            if expected_artifact_sha256 != record.artifact_sha256:
                raise ArtifactChangedError(
                    "the artifact changed since it was reviewed: approval names "
                    f"{expected_artifact_sha256}, the candidate is now "
                    f"{record.artifact_sha256}. Re-review the current artifact "
                    "before approving it."
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
            }
        )
        self.repository.save(approved)
        return approved

    def reject(
        self,
        run_id: str,
        reviewer: str,
        reason: str | None = None,
        *,
        actor_id: str | None = None,
        tenant_id: str | None = None,
        authentication: str = "self-asserted-local",
    ) -> RunRecord:
        record = self.repository.get(run_id)
        if record.status != RunStatus.READY_FOR_REVIEW:
            raise ApprovalRequiredError("only a passing candidate awaiting review can be rejected")
        self._verify_integrity(record)
        rejected = record.model_copy(
            update={
                "status": RunStatus.REJECTED,
                "rejection": Rejection(
                    reviewer=reviewer,
                    actor_id=actor_id,
                    tenant_id=tenant_id,
                    authentication=authentication,
                    reason=reason,
                    artifact_sha256=record.artifact_sha256,
                ),
            }
        )
        self.repository.save(rejected)
        return rejected

    def export_path(self, run_id: str) -> Path:
        record = self.repository.get(run_id)
        if record.status != RunStatus.APPROVED or record.approval is None:
            raise ApprovalRequiredError("human approval is required before export")
        self._verify_integrity(record)
        target = record.assembled_bog_path or record.target_artifact_path or record.bog_path
        if target is None:
            raise ArtifactChangedError("run has no signed target artifact")
        return Path(target)

    def review_bundle_path(self, run_id: str) -> Path:
        record = self.repository.get(run_id)
        if record.status != RunStatus.APPROVED or record.approval is None:
            raise ApprovalRequiredError("human approval is required before bundle export")
        self._verify_integrity(record)
        run_dir = self.repository.run_directory(record.id)
        destination = run_dir / f"{record.id}-review-bundle.zip"
        entries = {
            path.relative_to(run_dir).as_posix(): path.read_bytes()
            for path in self._record_artifact_paths(record)
        }
        entries["run-manifest.json"] = canonical_json(record).encode("utf-8")
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(entries):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, entries[name])
        return destination

    def boptest_verification_path(self, run_id: str) -> Path:
        record = self.repository.get(run_id)
        self._verify_integrity(record)
        if record.boptest_verification_path is None:
            raise KeyError("run has no BOPTEST qualification evidence")
        path = Path(record.boptest_verification_path)
        if not path.is_file():
            raise ArtifactChangedError("BOPTEST qualification evidence is missing")
        return path

    def alfalfa_verification_path(self, run_id: str) -> Path:
        record = self.repository.get(run_id)
        self._verify_integrity(record)
        if record.alfalfa_verification_path is None:
            raise KeyError("run has no Alfalfa qualification evidence")
        path = Path(record.alfalfa_verification_path)
        if not path.is_file():
            raise ArtifactChangedError("Alfalfa qualification evidence is missing")
        return path

    def verify_integrity(self, run_id: str) -> RunRecord:
        """Return a run only after all signed artifacts still match its digest."""

        record = self.repository.get(run_id)
        self._verify_integrity(record)
        return record

    @staticmethod
    def _record_artifact_paths(record: RunRecord) -> list[Path]:
        paths = [
            Path(record.graph_path),
            Path(record.report_path),
        ]
        target = record.target_artifact_path or record.bog_path
        if target:
            paths.append(Path(target))
        if record.job_path:
            paths.append(Path(record.job_path))
        if record.template_bog_path:
            paths.append(Path(record.template_bog_path))
        if record.template_analysis_path:
            paths.append(Path(record.template_analysis_path))
        if record.assembled_bog_path:
            paths.append(Path(record.assembled_bog_path))
        if record.station_assembly_manifest_path:
            paths.append(Path(record.station_assembly_manifest_path))
        if record.semantic_model_path:
            paths.append(Path(record.semantic_model_path))
        if record.semantic_validation_path:
            paths.append(Path(record.semantic_validation_path))
        if record.deliverable_manifest_path:
            paths.append(Path(record.deliverable_manifest_path))
        paths.extend(Path(path) for path in record.deliverable_artifact_paths)
        paths.extend(Path(path) for path in record.volttron_artifact_paths)
        paths.extend(Path(path) for path in record.nhaystack_artifact_paths)
        paths.extend(Path(path) for path in record.bacnet_lab_artifact_paths)
        paths.extend(Path(path) for path in record.environment_artifact_paths)
        paths.extend(Path(path) for path in record.source_artifact_paths)
        paths.extend(Path(path) for path in record.verification_artifact_paths)
        return paths

    @classmethod
    def _verify_integrity(cls, record: RunRecord) -> None:
        paths = cls._record_artifact_paths(record)
        current = artifact_hash(*paths)
        if current != record.artifact_sha256:
            raise ArtifactChangedError("artifact changed after validation; create a new run")
        if record.approval is not None and record.approval.artifact_sha256 != current:
            raise ArtifactChangedError("approval is not bound to the current artifact")
        if record.rejection is not None and record.rejection.artifact_sha256 != current:
            raise ArtifactChangedError("rejection is not bound to the current artifact")
