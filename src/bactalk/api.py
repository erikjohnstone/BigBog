from __future__ import annotations

import asyncio
import json
import os
import socket
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Match
from starlette.types import Scope

from bactalk import block_catalog
from bactalk.ai import (
    AIProviderError,
    CerebrasProvider,
    ChatRequest,
    ControlsChatAgent,
    ProposedGraphPlanner,
    StructuredChatProvider,
    summarize_verification_failures,
)
from bactalk.capabilities import CapabilityRegistry
from bactalk.ctrl_flow_point_repository import (
    CtrlFlowPointIntegrityError,
    CtrlFlowPointReconciliationRecord,
    CtrlFlowPointReconciliationRepository,
)
from bactalk.demo import (
    standard_ahu_demo_job,
    standard_vav_demo_job,
)
from bactalk.domain import (
    AcceptanceCase,
    ControlGraph,
    DeliverableRequirements,
    JobSpec,
    PointSpec,
    RunOrigin,
    RunRecord,
    RunStatus,
    SequenceSpec,
    TargetArtifactKind,
    canonical_json,
)
from bactalk.intake import (
    IntakeError,
    parse_bacnet_scan_json,
    parse_points_file,
    parse_sequence_document,
    validate_template_bog,
)
from bactalk.integrations.aixocat import AixocatError, AixocatLibrary
from bactalk.integrations.alfalfa import AlfalfaClientLike
from bactalk.integrations.bacnet_lab import VirtualBacnetLab, probe_manifest_with_bac0
from bactalk.integrations.boptest import (
    BoptestClient,
    BoptestError,
    discover_boptest_catalog,
    inspect_boptest_test_case,
)
from bactalk.integrations.boptest_graph import (
    BoptestRuntime,
)
from bactalk.integrations.buildingmotif import BuildingMotifAdapter, BuildingMotifError
from bactalk.integrations.constrain import ConStrainError, ConStrainVerifier
from bactalk.integrations.ctrl_flow import CtrlFlowError, CtrlFlowLibrary
from bactalk.integrations.cxf_importer import CxfImporter, CxfImportError
from bactalk.integrations.cxf_vectors import CxfVectorError, CxfVectorVerifier
from bactalk.integrations.fmi import inspect_fmu_archive
from bactalk.integrations.g36_library import G36Library
from bactalk.integrations.haxall import HaxallError, HaxallValidator
from bactalk.integrations.niagara_program_codegen import NiagaraProgramCodegenError
from bactalk.integrations.niagara_program_library import (
    NiagaraProgramLibrary,
    NiagaraProgramLibraryError,
)
from bactalk.integrations.open_control_engine import OpenControlEngine
from bactalk.integrations.open_control_library import OpenControlLibrary
from bactalk.integrations.open_fdd import OpenFddError, OpenFddVerifier
from bactalk.integrations.plant_controls_library import PlantControlsLibrary
from bactalk.integrations.readiness import IntegrationReadiness
from bactalk.integrations.reference_stack import ReferenceStackCatalog
from bactalk.integrations.rumoca import RumocaCompiler, RumocaError
from bactalk.integrations.use_audit import IntegrationUseAudit
from bactalk.library_demo import lbnl_multizone_ahu_demo_job, lbnl_vav_reheat_demo_job
from bactalk.library_tier2 import coverage_report as library_coverage_report
from bactalk.niagara.pointmap import apply_bindings, suggest_bindings
from bactalk.niagara.station_points import parse_station_inventory
from bactalk.optional_dependencies import (
    ALFALFA_CLIENT,
    CEREBRAS,
    OptionalDependencyError,
    optional_dependency_status,
)
from bactalk.point_mapping import (
    PointMappingError,
    canonicalize_deliverable_requirements,
    canonicalize_points,
)
from bactalk.projects import (
    ProjectBuildRepository,
    ProjectBuildService,
    ProjectPreflight,
    ProjectSpec,
)
from bactalk.protocol import RequirementApproval, generate_test_plan
from bactalk.protocol import catalog as protocol_catalog
from bactalk.protocol.adequacy import assess_adequacy
from bactalk.protocol.approvals import RequirementApprovalRepository
from bactalk.protocol.custom import CUSTOM_LABEL, CustomSequenceRepository, custom_job
from bactalk.protocol.plan import render_test_plan
from bactalk.qualification_jobs import (
    TERMINAL_JOB_STATUSES,
    AlfalfaQualificationPayload,
    BoptestQualificationPayload,
    QualificationDispatcher,
    QualificationJobIntegrityError,
    QualificationJobRepository,
    RqQualificationDispatcher,
    ShadowQualificationPayload,
)
from bactalk.repository import RunRepository
from bactalk.security import AuditLog, Principal, SecurityConfig, required_role
from bactalk.sequence_candidate import (
    SequenceCandidateGenerationRequest,
    SequenceCandidatePreflightRequest,
    build_sequence_candidate_job,
    compile_sequence_candidate_preflight,
)
from bactalk.sequence_oracles import (
    SequenceOracleApprovalRecord,
    SequenceOracleApprovalRepository,
    SequenceOracleApprovalRequest,
    SequenceOracleIntegrityError,
    compile_sequence_oracle_approval,
)
from bactalk.sequence_requirements import SequenceRequirementReviewRequest
from bactalk.sequence_review_repository import (
    SequenceRequirementReviewRecord,
    SequenceRequirementReviewRepository,
    SequenceReviewIntegrityError,
)
from bactalk.service import (
    MAX_ALFALFA_MODEL_BYTES,
    ApprovalRequiredError,
    ArtifactChangedError,
    WorkbenchService,
)


class SPAStaticFiles(StaticFiles):
    """Serve the React entry point for extensionless client-side routes."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not Path(path).suffix:
                return await super().get_response("index.html", scope)
            raise
        if response.status_code == 404 and not Path(path).suffix:
            return await super().get_response("index.html", scope)
        return response


class RequirementApprovalRequest(BaseModel):
    """Gate G-ENG: approve one exact requirement set digest (gates/G-ENG.md)."""

    reviewer: str | None = Field(default=None, min_length=2, max_length=120)
    requirements_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    note: str | None = Field(default=None, max_length=4_000)


class CustomSequenceRequest(BaseModel):
    """Tier 5: a contractor's specification section for the AI to draft requirements from."""

    title: str = Field(min_length=3, max_length=200)
    equipment_name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", max_length=120)
    spec_text: str = Field(min_length=20, max_length=200_000)
    spec_filename: str = Field(default="specification.txt", min_length=1, max_length=255)


class CustomAdequacyRequest(BaseModel):
    mutants: int = Field(default=0, ge=0, le=500)
    invariant_sequences: int = Field(default=1_000, ge=1, le=100_000)


class ApprovalRequest(BaseModel):
    reviewer: str | None = Field(default=None, min_length=2, max_length=120)
    artifact_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
        description=(
            "The exact artifact digest the reviewer inspected. When supplied it "
            "must match the candidate's current digest, so an artifact that "
            "changed after review cannot be approved unseen."
        ),
    )


class RejectionRequest(BaseModel):
    reviewer: str | None = Field(default=None, min_length=2, max_length=120)
    reason: str | None = Field(default=None, max_length=2_000)


class BoptestQualificationRequest(BoptestQualificationPayload):
    pass


class AlfalfaQualificationRequest(AlfalfaQualificationPayload):
    pass


class ShadowQualificationRequest(ShadowQualificationPayload):
    pass


class HaxallValidationRequest(BaseModel):
    zinc: str = Field(min_length=1, max_length=5_000_000)
    graph: bool = True


class ConStrainVerificationRequest(BaseModel):
    rule: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=100_000)
    parameters: dict[str, float | bool | str] = Field(default_factory=dict)


class OpenFddVerificationRequest(BaseModel):
    rule_id: str = Field(min_length=1, max_length=120)
    equipment_id: str = Field(min_length=1, max_length=240)
    equipment_kind: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    equipment_type: str = Field(min_length=1, max_length=120)
    poll_seconds: float = Field(gt=0, le=86_400)
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=100_000)
    parameters: dict[str, Any] = Field(default_factory=dict)
    require_operational_gates: bool = True


class BuildingMotifInstantiationRequest(BaseModel):
    library: Literal["g36", "chiller-plant", "ashrae-223p"]
    template: str = Field(min_length=1, max_length=500)
    namespace: str = Field(min_length=5, max_length=2_000)
    bindings: dict[str, str] = Field(default_factory=dict)


class CxfTranslationRequest(BaseModel):
    document: dict[str, Any]
    vectors: dict[str, Any] | None = None


class CxfExecutionSample(BaseModel):
    time: float = Field(ge=0, allow_inf_nan=False)
    inputs: dict[str, float | int | bool]


class CxfExecutionRequest(BaseModel):
    document: dict[str, Any]
    samples: list[CxfExecutionSample] = Field(min_length=1, max_length=100_000)
    collect: list[str] = Field(min_length=1, max_length=10_000)


class G36ExecutionRequest(BaseModel):
    samples: list[CxfExecutionSample] = Field(min_length=1, max_length=100_000)
    collect: list[str] | None = Field(default=None, min_length=1, max_length=10_000)
    parameters: dict[str, Any] = Field(default_factory=dict, max_length=128)


class G36ParameterRequest(BaseModel):
    parameters: dict[str, Any] = Field(default_factory=dict, max_length=128)


class G36FlattenRequest(BaseModel):
    parameters: dict[str, float | int | bool | str] = Field(default_factory=dict, max_length=128)


class AixocatTranslationRequest(BaseModel):
    parameters: dict[str, float] = Field(default_factory=dict, max_length=100)


class CtrlFlowConfigurationRequest(BaseModel):
    selections: dict[str, str | float | int | bool | None] = Field(
        default_factory=dict,
        max_length=500,
    )


class CtrlFlowPointReconciliationRequest(CtrlFlowConfigurationRequest):
    points: list[PointSpec] = Field(min_length=1, max_length=2_000)


def _free_loopback_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _form_json_object(value: str, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise IntakeError(f"{label} are invalid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise IntakeError(f"{label} must be a JSON object")
    return payload


def _form_acceptance_tests(value: str) -> list[AcceptanceCase]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise IntakeError(f"acceptance tests are invalid JSON: {exc.msg}") from exc
    if not isinstance(payload, list):
        raise IntakeError("acceptance tests must be a JSON array")
    try:
        return [AcceptanceCase.model_validate(item) for item in payload]
    except ValueError as exc:
        raise IntakeError(f"acceptance tests are invalid: {exc}") from exc


def _shadow_summary(record: RunRecord) -> dict[str, Any]:
    """Release-summary view of the Shadow Runtime evidence (tier bog-simulated)."""

    path = Path(record.shadow_verification_path) if record.shadow_verification_path else None
    if path is None or not path.is_file():
        return {
            "available": False,
            "passed": None,
            "tier": "bog-simulated",
            "failing_cases": [],
        }
    evidence = json.loads(path.read_text(encoding="utf-8"))
    differential = evidence.get("differential") or {}
    failing = list(differential.get("failing_cases", []))
    report = evidence.get("report") or {}
    for scenario in report.get("scenarios", []):
        if scenario.get("passed") is False and scenario.get("name") not in failing:
            failing.append(scenario.get("name"))
    return {
        "available": True,
        "passed": evidence.get("status") == "pass",
        "tier": "bog-simulated",
        "engine": evidence.get("engine"),
        "failing_cases": failing,
    }


def create_app(
    run_root: Path | None = None,
    *,
    ai_provider: StructuredChatProvider | None = None,
    ai_chat_provider: StructuredChatProvider | None = None,
    ai_coding_provider: StructuredChatProvider | None = None,
    security_config: SecurityConfig | None = None,
    boptest_client_factory: Callable[[], BoptestRuntime] | None = None,
    alfalfa_client_factory: Callable[[], AlfalfaClientLike] | None = None,
    qualification_dispatcher: QualificationDispatcher | None = None,
) -> FastAPI:
    root = run_root or Path(os.getenv("BACTALK_RUNS", ".bactalk/runs"))
    repository = RunRepository(root)
    requirement_approvals = RequirementApprovalRepository(root.parent / "requirement-approvals")
    custom_sequences = CustomSequenceRepository(root.parent / "custom-sequences")
    service = WorkbenchService(repository, requirement_approvals=requirement_approvals)
    qualification_jobs = QualificationJobRepository(root.parent / "qualification-jobs")
    dispatch_qualification = qualification_dispatcher or RqQualificationDispatcher(
        queue_url=os.getenv(
            "BACTALK_QUEUE_URL",
            "redis://:bactalk-queue-local-secret@127.0.0.1:6380/0",
        ),
        jobs_root=qualification_jobs.root,
        runs_root=root,
        queue_name=os.getenv("BACTALK_QUALIFICATION_QUEUE", "bactalk-qualification"),
    )
    if ai_provider is not None and (ai_chat_provider is not None or ai_coding_provider is not None):
        raise ValueError("ai_provider cannot be combined with role-specific AI providers")
    if ai_provider is not None:
        # Backward-compatible test/custom injection. Production configuration
        # always creates distinct role-scoped clients below.
        chat_provider = ai_provider
        coding_provider = ai_provider
    else:
        chat_provider = ai_chat_provider or CerebrasProvider.from_environment(
            model_variable="CEREBRAS_CHAT_MODEL",
            default_model="gpt-oss-120b",
            legacy_model_variable="CEREBRAS_MODEL",
        )
        coding_provider = ai_coding_provider or CerebrasProvider.from_environment(
            model_variable="CEREBRAS_CODING_MODEL",
            default_model="qwen-3.8-27b",
        )
    reference_stack = ReferenceStackCatalog()
    readiness = IntegrationReadiness()
    integration_audit = IntegrationUseAudit()
    capabilities = CapabilityRegistry()
    project_preflight = ProjectPreflight(capabilities)
    project_repository = ProjectBuildRepository(root.parent / "projects")
    sequence_review_repository = SequenceRequirementReviewRepository(
        root.parent / "sequence-requirement-reviews"
    )
    ctrl_flow_point_repository = CtrlFlowPointReconciliationRepository(
        root.parent / "ctrl-flow-point-reconciliations"
    )
    sequence_oracle_repository = SequenceOracleApprovalRepository(
        root.parent / "sequence-oracle-approvals"
    )
    project_builder = ProjectBuildService(project_repository, service, capabilities)
    buildingmotif = BuildingMotifAdapter()
    aixocat_library = AixocatLibrary()
    haxall = HaxallValidator()
    constrain = ConStrainVerifier()
    ctrl_flow = CtrlFlowLibrary()
    open_fdd = OpenFddVerifier()
    cxf_importer = CxfImporter()
    cxf_vectors = CxfVectorVerifier()
    open_control_library = OpenControlLibrary()
    open_control_engine = OpenControlEngine()
    g36_library = G36Library(engine=open_control_engine)
    plant_controls_library = PlantControlsLibrary(engine=open_control_engine)
    rumoca = RumocaCompiler(library=g36_library)
    niagara_program_library = NiagaraProgramLibrary()
    security = security_config or SecurityConfig.from_environment()
    security_audit = AuditLog(root.parent / "audit" / "events.jsonl")

    def configured_boptest_client() -> BoptestClient:
        return BoptestClient(
            os.getenv("BACTALK_BOPTEST_URL", "http://127.0.0.1:8000"),
            scenario_timeout=float(os.getenv("BACTALK_BOPTEST_SCENARIO_TIMEOUT_SECONDS", "900")),
        )

    make_boptest_client = boptest_client_factory or configured_boptest_client
    alfalfa_base_url = os.getenv("BACTALK_ALFALFA_URL", "http://127.0.0.1:8088")

    def _default_alfalfa_client() -> AlfalfaClientLike:
        # Imported on demand: a minimal install without the Alfalfa extra must
        # still start the API and serve every other capability.
        client_class = ALFALFA_CLIENT.attribute("AlfalfaClient")
        return client_class(alfalfa_base_url)

    make_alfalfa_client = alfalfa_client_factory or _default_alfalfa_client
    app = FastAPI(
        title="BACTalk",
        version="0.1.0",
        description="Human-gated controls programming workbench",
    )

    @app.exception_handler(OptionalDependencyError)
    async def optional_dependency_unavailable(
        request: Request, exc: OptionalDependencyError
    ) -> JSONResponse:
        """Report a missing optional extra as an unavailable capability.

        A minimal install is a supported configuration, so a capability whose
        package was never installed answers with an explicit remediation
        instead of a 500 that looks like a product defect.
        """
        return JSONResponse(
            status_code=503,
            content={
                "detail": str(exc),
                "capability": exc.capability,
                "distribution": exc.dependency.distribution,
                "extra": exc.dependency.extra,
                "remediation": exc.remediation,
            },
        )

    def review_identity(
        http_request: Request,
        submitted_reviewer: str | None,
    ) -> tuple[str, str | None, str | None, str]:
        principal: Principal | None = getattr(http_request.state, "principal", None)
        if security.enabled:
            if principal is None:  # The middleware guarantees this; retain a fail-closed guard.
                raise HTTPException(status_code=401, detail="authenticated identity required")
            return (
                principal.display_name,
                principal.subject,
                principal.tenant_id,
                "bearer-token",
            )
        if submitted_reviewer is None:
            raise HTTPException(
                status_code=422,
                detail="reviewer is required while local-development authentication is active",
            )
        return submitted_reviewer, None, None, "self-asserted-local"

    def retained_review_visible(
        http_request: Request,
        record: SequenceRequirementReviewRecord,
    ) -> bool:
        if not security.enabled:
            return True
        principal: Principal | None = getattr(http_request.state, "principal", None)
        return (
            principal is not None
            and record.result.get("review", {}).get("tenant_id") == principal.tenant_id
        )

    def retained_point_reconciliation_visible(
        http_request: Request,
        record: CtrlFlowPointReconciliationRecord,
    ) -> bool:
        if not security.enabled:
            return True
        principal: Principal | None = getattr(http_request.state, "principal", None)
        return principal is not None and record.tenant_id == principal.tenant_id

    def retained_oracle_visible(
        http_request: Request,
        record: SequenceOracleApprovalRecord,
    ) -> bool:
        if not security.enabled:
            return True
        principal: Principal | None = getattr(http_request.state, "principal", None)
        return (
            principal is not None
            and record.result.get("approval", {}).get("tenant_id") == principal.tenant_id
        )

    def load_sequence_candidate_evidence(
        approval_id: str,
        http_request: Request,
    ) -> tuple[
        SequenceOracleApprovalRecord,
        SequenceRequirementReviewRecord,
        CtrlFlowPointReconciliationRecord,
        dict[str, Any],
    ]:
        oracle_record = sequence_oracle_repository.get(approval_id)
        if not retained_oracle_visible(http_request, oracle_record):
            raise HTTPException(status_code=404, detail="sequence oracle approval not found")
        review_record = sequence_review_repository.get(oracle_record.review_id)
        if not retained_review_visible(http_request, review_record):
            raise HTTPException(status_code=404, detail="sequence requirement review not found")
        point_evidence = review_record.result.get("contractor_point_reconciliation", {})
        point_record = ctrl_flow_point_repository.get(str(point_evidence.get("id", "")))
        if not retained_point_reconciliation_visible(http_request, point_record):
            raise HTTPException(status_code=404, detail="ctrl-flow point reconciliation not found")
        brief = ctrl_flow.programming_brief(
            review_record.template_id,
            review_record.selections,
        )
        return oracle_record, review_record, point_record, brief

    def qualification_job_visible(http_request: Request, tenant_id: str | None) -> bool:
        if not security.enabled:
            return True
        principal: Principal | None = getattr(http_request.state, "principal", None)
        return principal is not None and tenant_id == principal.tenant_id

    @app.middleware("http")
    async def enforce_identity_and_audit(request: Request, call_next):
        request_id = uuid4().hex
        request.state.request_id = request_id
        request.state.principal = None
        role = required_role(request.method, request.url.path)
        principal: Principal | None = None
        response = None
        if security.enabled and role is not None:
            if security.require_https and request.url.scheme != "https":
                response = JSONResponse(
                    {"detail": "HTTPS is required when authentication is enabled"},
                    status_code=400,
                )
            else:
                principal = security.authenticate(request.headers.get("authorization"))
                request.state.principal = principal
                if principal is None:
                    response = JSONResponse(
                        {"detail": "valid bearer token required"},
                        status_code=401,
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                elif not principal.permits(role):
                    response = JSONResponse(
                        {"detail": f"{role.value} role required"},
                        status_code=403,
                    )
        if response is None:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["Cache-Control"] = "no-store" if role is not None else "no-cache"
        if role is not None:
            security_audit.append(
                action=f"api.{role.value}",
                outcome="allowed" if response.status_code < 400 else "denied-or-failed",
                principal=principal,
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                request_id=request_id,
            )
        return response

    @app.middleware("http")
    async def add_required_allow_header(request, call_next):
        response = await call_next(request)
        if response.status_code == 405 and "allow" not in response.headers:
            allowed: set[str] = set()
            for route in app.router.routes:
                match, _ = route.matches(request.scope)
                if match == Match.PARTIAL:
                    allowed.update(route.methods or set())
            if allowed:
                response.headers["Allow"] = ", ".join(sorted(allowed))
        return response

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "offline-safe"}

    @app.get("/api/security/status")
    def security_status() -> dict:
        return security.status()

    @app.get("/api/security/audit/status")
    def security_audit_status() -> dict:
        return {
            "schema": "bactalk.audit-status/v1",
            **security_audit.verify(),
            "external_immutable_retention": False,
        }

    @app.get("/api/ai/status")
    def ai_status() -> dict:
        return {
            "configured": chat_provider is not None and coding_provider is not None,
            "provider": (
                "cerebras" if chat_provider is not None or coding_provider is not None else None
            ),
            "model": chat_provider.model if chat_provider is not None else None,
            "roles": {
                "conversation": {
                    "configured": chat_provider is not None,
                    "model": chat_provider.model if chat_provider is not None else None,
                    "authority": "explain-and-route-only",
                },
                "coding": {
                    "configured": coding_provider is not None,
                    "model": coding_provider.model if coding_provider is not None else None,
                    "authority": "proposal-only",
                },
            },
            "authority": "proposal-only",
            # When a key is configured but the SDK extra is absent the roles
            # stay unconfigured on purpose; name the remediation so the UI can
            # show why instead of silently hiding the capability.
            "unavailable_reason": (
                None
                if chat_provider is not None and coding_provider is not None
                else (
                    CEREBRAS.remediation
                    if os.getenv("CEREBRAS_API_KEY") and not CEREBRAS.available()
                    else "CEREBRAS_API_KEY is not configured"
                    if not os.getenv("CEREBRAS_API_KEY")
                    else None
                )
            ),
        }

    @app.get("/api/system/optional-capabilities")
    def optional_capabilities() -> dict:
        """Report which optional extras are installed and how to add the rest.

        A minimal install is supported, so the UI reads this to disable
        capability entry points instead of offering buttons that 503.
        """
        statuses = optional_dependency_status()
        return {
            "schema": "bactalk.optional-capabilities/v1",
            "dependencies": statuses,
            "all_installed": all(item["installed"] for item in statuses),
            "bootstrap_command": "make bootstrap-full",
        }

    @app.get("/api/reference-stack")
    def get_reference_stack() -> dict:
        return reference_stack.inventory()

    @app.get("/api/block-catalog")
    def get_block_catalog() -> dict:
        """Typed slots for every block kind, so the wiresheet draws declared ports."""
        return block_catalog.catalog()

    @app.get("/api/system/readiness")
    def get_system_readiness() -> dict:
        return readiness.report()

    @app.get("/api/system/integration-audit")
    def get_integration_audit() -> dict:
        return integration_audit.report()

    @app.get("/api/capability-packs")
    def get_capability_packs() -> dict:
        return capabilities.inventory()

    @app.get("/api/capability-packs/{pack_id}/release-gates")
    def get_capability_pack_release_gates(pack_id: str) -> dict:
        try:
            return capabilities.release_assessment(pack_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="capability pack not found") from exc

    @app.post("/api/translate/cxf/inspect")
    def inspect_cxf(request: CxfTranslationRequest) -> dict:
        try:
            return cxf_importer.inspect(request.document)
        except CxfImportError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/translate/cxf")
    def translate_cxf(request: CxfTranslationRequest) -> dict:
        try:
            graph = cxf_importer.import_graph(request.document)
            vector_report = (
                cxf_vectors.verify(graph, request.vectors) if request.vectors is not None else None
            )
            return {
                "graph": graph.model_dump(mode="json"),
                "coverage": graph.metadata["coverage"],
                "vector_report": vector_report,
            }
        except (CxfImportError, CxfVectorError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/execute/cxf")
    def execute_cxf(request: CxfExecutionRequest) -> dict:
        """Run standards-native CXF directly in the isolated Open Control Engine."""

        try:
            return open_control_engine.simulate_document(
                request.document,
                samples=[sample.model_dump(mode="json") for sample in request.samples],
                collect=request.collect,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/library/g36/controllers")
    def g36_controller_catalog() -> dict:
        try:
            return g36_library.catalog()
        except (FileNotFoundError, RuntimeError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/library/coverage")
    def library_coverage() -> dict:
        """D1–D4 per library configuration (GOAL-NATIVE-BOG.md N8 step 6), as committed by
        scripts/coverage_report.py; every failing or blocked configuration carries its reason."""

        report = library_coverage_report()
        if report is None:
            raise HTTPException(
                status_code=404, detail="no coverage report; run scripts/coverage_report.py"
            )
        return report

    # --- Test Generation Protocol (GOAL-NATIVE-BOG.md N9): Tier 3+ requirement sets --------

    def _protocol_requirements(sequence_id: str):
        """(requirements, label, item id, configuration dict, adequacy, custom record)."""

        try:
            entry = protocol_catalog.row(sequence_id)
        except KeyError:
            entry = None
        if entry is not None:
            return (
                entry.requirement_set(),
                entry.item.label,
                entry.item.id,
                {
                    "id": entry.configuration.id,
                    "label": entry.configuration.label,
                    "options": entry.configuration.options,
                },
                entry.adequacy_artifact(),
                None,
            )
        try:
            record = custom_sequences.get(sequence_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="protocol sequence not found") from exc
        return (
            record.requirement_set(),
            CUSTOM_LABEL,
            "custom",
            {"id": "job", "label": record.equipment_name, "options": {}},
            record.adequacy,
            record,
        )

    def _protocol_item(sequence_id: str) -> dict:
        requirements, label, item_id, configuration, adequacy, record = _protocol_requirements(
            sequence_id
        )
        plan = generate_test_plan(requirements)
        approvals = requirement_approvals.for_sequence(sequence_id)
        exact = requirement_approvals.get(sequence_id, requirements.digest())
        custom = None
        if record is not None:
            custom = {
                "spec_filename": record.spec_filename,
                "spec_sha256": record.spec_sha256,
                "assumptions": record.assumptions,
                "questions": record.questions,
                "drafted_by": record.drafted_by,
                "has_program": record.graph is not None,
                "created_at": record.created_at.isoformat(),
            }
        return {
            "schema": "bactalk.protocol-sequence/v1",
            "sequence_id": sequence_id,
            "title": requirements.title,
            "tier": requirements.tier,
            "label": label,
            "item": item_id,
            "configuration": configuration,
            "custom": custom,
            "version": requirements.version,
            "requirements_digest": requirements.digest(),
            "gate_g_eng": requirement_approvals.status(requirements),
            "approval": exact.model_dump(mode="json", by_alias=True) if exact else None,
            "earlier_approvals": [
                item.model_dump(mode="json", by_alias=True)
                for item in approvals
                if item.requirements_digest != requirements.digest()
            ],
            "requirements": requirements.model_dump(mode="json", by_alias=True),
            "plan": {
                "digest": plan.digest(),
                "generator": plan.generator,
                "scenarios": len(plan.scenarios),
                "per_requirement": {key: len(value) for key, value in plan.traceability().items()},
                "kinds": sorted({scenario.kind for scenario in plan.scenarios}),
                "gaps": plan.gaps,
            },
            "adequacy": adequacy,
            "adequacy_current": bool(adequacy)
            and adequacy.get("requirements_digest") == requirements.digest(),
            "test_plan_markdown": render_test_plan(requirements, plan, adequacy, exact),
        }

    @app.get("/api/protocol/sequences")
    def list_protocol_sequences() -> dict:
        """Every Tier 3+ sequence with its Gate G-ENG status and adequacy summary."""

        items = []
        custom_ids = [record.id for record in custom_sequences.list()]
        for sequence_id in [*protocol_catalog.sequence_ids(), *custom_ids]:
            full = _protocol_item(sequence_id)
            adequacy = full["adequacy"] or {}
            items.append(
                {
                    key: full[key]
                    for key in (
                        "sequence_id",
                        "title",
                        "tier",
                        "label",
                        "item",
                        "configuration",
                        "version",
                        "requirements_digest",
                        "gate_g_eng",
                        "adequacy_current",
                    )
                }
                | {
                    "requirements": len(full["requirements"]["requirements"]),
                    "invariants": len(full["requirements"]["invariants"]),
                    "scenarios": full["plan"]["scenarios"],
                    "gaps": len(full["plan"]["gaps"]),
                    "accepted": adequacy.get("accepted"),
                    "questions": len(adequacy.get("questions", [])),
                }
            )
        return {"schema": "bactalk.protocol-sequence-list/v1", "items": items}

    @app.get("/api/protocol/sequences/{sequence_id}")
    def get_protocol_sequence(sequence_id: str) -> dict:
        return _protocol_item(sequence_id)

    @app.get("/api/protocol/sequences/{sequence_id}/test-plan")
    def get_protocol_test_plan(sequence_id: str) -> PlainTextResponse:
        """The readable test plan (requirement → scenarios → expected → result), which is
        also the commissioning functional test plan."""

        return PlainTextResponse(
            _protocol_item(sequence_id)["test_plan_markdown"], media_type="text/markdown"
        )

    @app.post("/api/protocol/sequences/{sequence_id}/approve", status_code=201)
    def approve_protocol_requirements(
        sequence_id: str, request: RequirementApprovalRequest, http_request: Request
    ) -> dict:
        """Gate G-ENG: a named engineer approves the exact requirement set digest."""

        requirements = _protocol_requirements(sequence_id)[0]
        if request.requirements_digest != requirements.digest():
            raise HTTPException(
                status_code=409,
                detail=(
                    "the digest approved is not the current requirement set: "
                    f"submitted {request.requirements_digest[:12]}, current "
                    f"{requirements.digest()[:12]}; reload and review the current set"
                ),
            )
        reviewer, actor_id, tenant_id, authentication = review_identity(
            http_request, request.reviewer
        )
        approval = RequirementApproval(
            sequence_id=sequence_id,
            requirements_digest=request.requirements_digest,
            reviewer=reviewer,
            actor_id=actor_id,
            tenant_id=tenant_id,
            authentication=authentication,
            note=request.note,
        )
        try:
            requirement_approvals.save(approval)
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return approval.model_dump(mode="json", by_alias=True)

    # --- Tier 5: custom, job-specific sequences (N11) -------------------------------------

    def _custom_record(sequence_id: str):
        try:
            return custom_sequences.get(sequence_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="custom sequence not found") from exc

    @app.post("/api/protocol/custom", status_code=201)
    def create_custom_sequence(request: CustomSequenceRequest) -> dict:
        """The AI (conversation role) drafts the requirement set from the uploaded
        specification section; the contractor approves it like any protocol sequence."""

        if chat_provider is None:
            raise HTTPException(status_code=503, detail="AI provider unavailable")
        try:
            record = custom_sequences.create(
                title=request.title,
                equipment_name=request.equipment_name,
                spec_text=request.spec_text,
                spec_filename=request.spec_filename,
                provider=chat_provider,
            )
        except AIProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return _protocol_item(record.id)

    @app.get("/api/protocol/custom")
    def list_custom_sequences() -> dict:
        return {
            "schema": "bactalk.custom-sequence-list/v1",
            "items": [
                {
                    "sequence_id": record.id,
                    "title": record.title,
                    "equipment_name": record.equipment_name,
                    "requirements_digest": record.requirements_digest,
                    "gate_g_eng": requirement_approvals.status(record.requirement_set()),
                    "has_program": record.graph is not None,
                    "adequacy_accepted": (record.adequacy or {}).get("accepted"),
                    "label": record.label,
                }
                for record in custom_sequences.list()
            ],
        }

    @app.post("/api/protocol/custom/{sequence_id}/program", status_code=201)
    def draft_custom_program(sequence_id: str) -> dict:
        """The AI (coding role, a separate session and model from the drafter) implements
        the approved requirements; refused while the requirements are unapproved."""

        record = _custom_record(sequence_id)
        if not requirement_approvals.is_approved(record.id, record.requirements_digest):
            raise HTTPException(
                status_code=409,
                detail="requirements are unapproved (Gate G-ENG): the program is drafted "
                "from approved requirements only",
            )
        if coding_provider is None:
            raise HTTPException(status_code=503, detail="AI provider unavailable")
        try:
            custom_sequences.set_program(record.id, provider=coding_provider)
        except AIProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return _protocol_item(record.id)

    @app.post("/api/protocol/custom/{sequence_id}/adequacy")
    def run_custom_adequacy(sequence_id: str, request: CustomAdequacyRequest) -> dict:
        """The protocol's adequacy check on the drafted program: suite, decision coverage,
        invariants, the Shadow scan leg and (when asked) a mutant sample; retained on the
        record and reported as measured."""

        record = _custom_record(sequence_id)
        if record.graph is None:
            raise HTTPException(status_code=409, detail="the custom sequence has no program yet")
        requirements = record.requirement_set()
        plan = generate_test_plan(requirements)
        try:
            job = custom_job(record, plan=plan)
            report = assess_adequacy(
                job,
                requirements,
                plan,
                mutants=request.mutants or None,
                invariant_sequences=request.invariant_sequences,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        payload = report.to_dict()
        payload["gate_g_eng"] = requirement_approvals.status(requirements)
        custom_sequences.set_adequacy(record.id, payload)
        return payload

    @app.post("/api/protocol/custom/{sequence_id}/runs", status_code=201)
    def create_custom_run(sequence_id: str) -> dict:
        """A programming run for the custom sequence, labelled custom, job-specific; it goes
        through every normal gate and cannot be approved before its requirements are."""

        record = _custom_record(sequence_id)
        if record.graph is None:
            raise HTTPException(status_code=409, detail="the custom sequence has no program yet")
        try:
            return service.create_run(custom_job(record)).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/library/ctrl-flow/templates")
    def ctrl_flow_template_catalog() -> dict:
        try:
            return ctrl_flow.catalog()
        except (FileNotFoundError, CtrlFlowError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/library/ctrl-flow/templates/{template_id:path}/schema")
    def ctrl_flow_template_schema(template_id: str) -> dict:
        try:
            return ctrl_flow.schema(template_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except CtrlFlowError as exc:
            status = 404 if "unknown ctrl-flow template" in str(exc) else 422
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.post("/api/library/ctrl-flow/templates/{template_id:path}/configure")
    def configure_ctrl_flow_template(
        template_id: str,
        request: CtrlFlowConfigurationRequest,
    ) -> dict:
        try:
            return ctrl_flow.configure(template_id, request.selections)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except CtrlFlowError as exc:
            status = 404 if "unknown ctrl-flow template" in str(exc) else 422
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/library/ctrl-flow/templates/{template_id:path}/programming-brief")
    def build_ctrl_flow_programming_brief(
        template_id: str,
        request: CtrlFlowConfigurationRequest,
    ) -> dict:
        try:
            return ctrl_flow.programming_brief(template_id, request.selections)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except CtrlFlowError as exc:
            status = 404 if "unknown ctrl-flow template" in str(exc) else 422
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/library/ctrl-flow/templates/{template_id:path}/reconcile-points")
    def reconcile_ctrl_flow_points(
        template_id: str,
        request: CtrlFlowPointReconciliationRequest,
    ) -> dict:
        try:
            return ctrl_flow.reconcile_points(
                template_id,
                request.selections,
                request.points,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except CtrlFlowError as exc:
            status = 404 if "unknown ctrl-flow template" in str(exc) else 422
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/library/ctrl-flow/templates/{template_id:path}/inspect-points")
    async def inspect_ctrl_flow_points_file(
        template_id: str,
        http_request: Request,
        points_file: Annotated[UploadFile, File()],
        selections: Annotated[str, Form(max_length=50_000)] = "{}",
    ) -> dict:
        try:
            parsed_selections = _form_json_object(selections, "ctrl-flow selections")
            source_content = await points_file.read()
            points = parse_points_file(
                source_content,
                points_file.filename or "points.csv",
            )
            result = ctrl_flow.reconcile_points(template_id, parsed_selections, points)
            principal: Principal | None = getattr(http_request.state, "principal", None)
            record = ctrl_flow_point_repository.save(
                template_id=template_id,
                selections=parsed_selections,
                source_content=source_content,
                source_filename=points_file.filename or "points.csv",
                source_media_type=points_file.content_type or "application/octet-stream",
                actor_id=principal.subject if principal is not None else None,
                tenant_id=principal.tenant_id if principal is not None else None,
                result=result,
            )
            return {
                **result,
                "point_reconciliation_id": record.id,
                "retention": {
                    "schema": record.schema_name,
                    "artifact_digest": record.artifact_digest,
                    "result_digest": record.result_digest,
                    "source_sha256": record.source_sha256,
                    "created_at": record.created_at.isoformat(),
                    "source_bytes_retained": True,
                    "storage": "append-only-local-hash-verified",
                    "external_immutable_retention": False,
                },
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except CtrlFlowError as exc:
            status = 404 if "unknown ctrl-flow template" in str(exc) else 422
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        except (IntakeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/ctrl-flow-point-reconciliations")
    def list_ctrl_flow_point_reconciliations(http_request: Request) -> dict:
        try:
            records = [
                record
                for record in ctrl_flow_point_repository.list()
                if retained_point_reconciliation_visible(http_request, record)
            ]
            return {
                "schema": "bactalk.ctrl-flow-point-reconciliation-list/v1",
                "count": len(records),
                "reconciliations": [
                    {
                        "id": record.id,
                        "template_id": record.template_id,
                        "created_at": record.created_at.isoformat(),
                        "source_filename": record.source_filename,
                        "source_sha256": record.source_sha256,
                        "configuration_digest": record.configuration_digest,
                        "result_digest": record.result_digest,
                        "artifact_digest": record.artifact_digest,
                        "ready_for_sequence_reconciliation": record.result.get(
                            "ready_for_sequence_reconciliation", False
                        ),
                    }
                    for record in records
                ],
            }
        except CtrlFlowPointIntegrityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/ctrl-flow-point-reconciliations/{reconciliation_id}")
    def get_ctrl_flow_point_reconciliation(
        reconciliation_id: str,
        http_request: Request,
    ) -> dict:
        try:
            record = ctrl_flow_point_repository.get(reconciliation_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="ctrl-flow point reconciliation not found"
            ) from exc
        except (CtrlFlowPointIntegrityError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not retained_point_reconciliation_visible(http_request, record):
            raise HTTPException(status_code=404, detail="ctrl-flow point reconciliation not found")
        return record.model_dump(mode="json", by_alias=True)

    @app.post("/api/library/ctrl-flow/templates/{template_id:path}/inspect-sequence")
    async def inspect_ctrl_flow_sequence_file(
        template_id: str,
        sequence_document: Annotated[UploadFile, File()],
        selections: Annotated[str, Form(max_length=50_000)] = "{}",
    ) -> dict:
        try:
            parsed_selections = _form_json_object(selections, "ctrl-flow selections")
            document = parse_sequence_document(
                await sequence_document.read(),
                sequence_document.filename or "sequence.txt",
                sequence_document.content_type,
            )
            return ctrl_flow.reconcile_sequence(template_id, parsed_selections, document)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except CtrlFlowError as exc:
            status = 404 if "unknown ctrl-flow template" in str(exc) else 422
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        except (IntakeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/library/ctrl-flow/templates/{template_id:path}/review-requirements/approve")
    async def approve_ctrl_flow_sequence_requirements(
        template_id: str,
        http_request: Request,
        sequence_document: Annotated[UploadFile, File()],
        review: Annotated[str, Form(min_length=2, max_length=5_000_000)],
        point_reconciliation_id: Annotated[str, Form(pattern=r"^[0-9a-f]{32}$")],
        selections: Annotated[str, Form(max_length=50_000)] = "{}",
    ) -> dict:
        try:
            parsed_selections = _form_json_object(selections, "ctrl-flow selections")
            point_record = ctrl_flow_point_repository.get(point_reconciliation_id)
            if not retained_point_reconciliation_visible(http_request, point_record):
                raise HTTPException(
                    status_code=404, detail="ctrl-flow point reconciliation not found"
                )
            if point_record.template_id != template_id:
                raise ValueError("point reconciliation belongs to a different ctrl-flow template")
            if point_record.selections != parsed_selections:
                raise ValueError("point reconciliation selections changed; inspect points again")
            if not point_record.result.get("ready_for_sequence_reconciliation", False):
                raise ValueError(
                    "point reconciliation is blocked; resolve the contractor point list first"
                )
            parsed_review = SequenceRequirementReviewRequest.model_validate(
                _form_json_object(review, "sequence requirement review")
            )
            reviewer, actor_id, tenant_id, authentication = review_identity(
                http_request,
                parsed_review.reviewer,
            )
            source_content = await sequence_document.read()
            document = parse_sequence_document(
                source_content,
                sequence_document.filename or "sequence.txt",
                sequence_document.content_type,
            )
            result = ctrl_flow.review_sequence_requirements(
                template_id,
                parsed_selections,
                document,
                parsed_review,
                reviewer=reviewer,
                actor_id=actor_id,
                tenant_id=tenant_id,
                authentication=authentication,
                point_reconciliation={
                    "id": point_record.id,
                    "artifact_digest": point_record.artifact_digest,
                    "result_digest": point_record.result_digest,
                    "source_sha256": point_record.source_sha256,
                    "source_filename": point_record.source_filename,
                    "template_id": point_record.template_id,
                    "configuration_digest": point_record.configuration_digest,
                    "ready_for_sequence_reconciliation": point_record.result[
                        "ready_for_sequence_reconciliation"
                    ],
                    "canonical_points": point_record.result["canonical_points"],
                    "matches": point_record.result["matches"],
                    "unit_conversions": point_record.result["unit_conversions"],
                    "unmatched_provided": point_record.result["unmatched_provided"],
                },
            )
            record = sequence_review_repository.save(
                template_id=template_id,
                selections=parsed_selections,
                source_content=source_content,
                source_filename=document.filename,
                source_media_type=document.media_type,
                result=result,
            )
            return {
                **result,
                "review_id": record.id,
                "retention": {
                    "schema": record.schema_name,
                    "artifact_digest": record.artifact_digest,
                    "created_at": record.created_at.isoformat(),
                    "source_bytes_retained": True,
                    "storage": "append-only-local-hash-verified",
                    "external_immutable_retention": False,
                },
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except CtrlFlowError as exc:
            status = 404 if "unknown ctrl-flow template" in str(exc) else 422
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        except CtrlFlowPointIntegrityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="ctrl-flow point reconciliation not found"
            ) from exc
        except (IntakeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/sequence-requirement-reviews")
    def list_sequence_requirement_reviews(http_request: Request) -> dict:
        try:
            records = [
                record
                for record in sequence_review_repository.list()
                if retained_review_visible(http_request, record)
            ]
            return {
                "schema": "bactalk.sequence-requirement-review-list/v1",
                "count": len(records),
                "reviews": [
                    {
                        "id": record.id,
                        "template_id": record.template_id,
                        "created_at": record.created_at.isoformat(),
                        "source_filename": record.source_filename,
                        "source_sha256": record.source_sha256,
                        "candidate_digest": record.candidate_digest,
                        "review_digest": record.review_digest,
                        "artifact_digest": record.artifact_digest,
                        "reviewer": record.result["review"]["reviewer"],
                        "blocker_count": len(record.result.get("blockers", [])),
                        "oracle_draft_count": record.result.get("oracle_draft_count", 0),
                        "ready_for_independent_oracle_authoring": record.result.get(
                            "ready_for_independent_oracle_authoring", False
                        ),
                    }
                    for record in records
                ],
            }
        except SequenceReviewIntegrityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/sequence-requirement-reviews/{review_id}")
    def get_sequence_requirement_review(review_id: str, http_request: Request) -> dict:
        try:
            record = sequence_review_repository.get(review_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="sequence requirement review not found"
            ) from exc
        except (SequenceReviewIntegrityError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not retained_review_visible(http_request, record):
            raise HTTPException(status_code=404, detail="sequence requirement review not found")
        return record.model_dump(mode="json", by_alias=True)

    @app.post("/api/sequence-requirement-reviews/{review_id}/oracles/approve")
    def approve_sequence_oracles(
        review_id: str,
        request: SequenceOracleApprovalRequest,
        http_request: Request,
    ) -> dict:
        try:
            review_record = sequence_review_repository.get(review_id)
            if not retained_review_visible(http_request, review_record):
                raise HTTPException(status_code=404, detail="sequence requirement review not found")
            author, actor_id, tenant_id, authentication = review_identity(
                http_request, request.author
            )
            result = compile_sequence_oracle_approval(
                review_id,
                review_record.model_dump(mode="json"),
                request,
                author=author,
                actor_id=actor_id,
                tenant_id=tenant_id,
                authentication=authentication,
            )
            record = sequence_oracle_repository.save(result)
            return {
                **result,
                "oracle_approval_id": record.id,
                "retention": {
                    "schema": record.schema_name,
                    "artifact_digest": record.artifact_digest,
                    "created_at": record.created_at.isoformat(),
                    "storage": "append-only-local-hash-verified",
                    "external_immutable_retention": False,
                },
            }
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="sequence requirement review not found"
            ) from exc
        except HTTPException:
            raise
        except (SequenceReviewIntegrityError, SequenceOracleIntegrityError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/sequence-oracle-approvals")
    def list_sequence_oracle_approvals(http_request: Request) -> dict:
        try:
            records = [
                record
                for record in sequence_oracle_repository.list()
                if retained_oracle_visible(http_request, record)
            ]
            return {
                "schema": "bactalk.sequence-oracle-approval-list/v1",
                "count": len(records),
                "approvals": [
                    {
                        "id": record.id,
                        "review_id": record.review_id,
                        "review_artifact_digest": record.review_artifact_digest,
                        "created_at": record.created_at.isoformat(),
                        "oracle_digest": record.oracle_digest,
                        "artifact_digest": record.artifact_digest,
                        "author": record.result["approval"]["author"],
                        "case_count": record.result["case_count"],
                        "ready_for_graph_generation": record.result["ready_for_graph_generation"],
                    }
                    for record in records
                ],
            }
        except SequenceOracleIntegrityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/sequence-oracle-approvals/{approval_id}")
    def get_sequence_oracle_approval(approval_id: str, http_request: Request) -> dict:
        try:
            record = sequence_oracle_repository.get(approval_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="sequence oracle approval not found"
            ) from exc
        except (SequenceOracleIntegrityError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not retained_oracle_visible(http_request, record):
            raise HTTPException(status_code=404, detail="sequence oracle approval not found")
        return record.model_dump(mode="json", by_alias=True)

    @app.post("/api/sequence-oracle-approvals/{approval_id}/candidate-preflight")
    def preflight_sequence_candidate(
        approval_id: str,
        request: SequenceCandidatePreflightRequest,
        http_request: Request,
    ) -> dict:
        try:
            oracle_record, review_record, point_record, brief = load_sequence_candidate_evidence(
                approval_id, http_request
            )
            return compile_sequence_candidate_preflight(
                oracle_record=oracle_record.model_dump(mode="json", by_alias=True),
                review_record=review_record.model_dump(mode="json", by_alias=True),
                point_record=point_record.model_dump(mode="json", by_alias=True),
                programming_brief=brief,
                request=request,
                g36_library=g36_library,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="candidate preflight evidence chain is incomplete"
            ) from exc
        except HTTPException:
            raise
        except (
            CtrlFlowPointIntegrityError,
            SequenceReviewIntegrityError,
            SequenceOracleIntegrityError,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (CtrlFlowError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post(
        "/api/sequence-oracle-approvals/{approval_id}/candidate",
        status_code=201,
    )
    def generate_sequence_candidate(
        approval_id: str,
        request: SequenceCandidateGenerationRequest,
        http_request: Request,
    ) -> Response:
        try:
            oracle_record, review_record, point_record, brief = load_sequence_candidate_evidence(
                approval_id, http_request
            )
            preflight, job = build_sequence_candidate_job(
                oracle_record=oracle_record.model_dump(mode="json", by_alias=True),
                review_record=review_record.model_dump(mode="json", by_alias=True),
                point_record=point_record.model_dump(mode="json", by_alias=True),
                programming_brief=brief,
                request=request,
                g36_library=g36_library,
            )
            if job is None:
                return JSONResponse(
                    status_code=409,
                    content={
                        "schema": "bactalk.sequence-candidate-blocked/v1",
                        "message": (
                            "The approved document chain does not produce a complete candidate."
                        ),
                        "preflight": preflight,
                    },
                )

            evidence = {
                "schema": "bactalk.sequence-candidate-source-chain/v1",
                "oracle_approval": {
                    "id": oracle_record.id,
                    "artifact_digest": oracle_record.artifact_digest,
                    "oracle_digest": oracle_record.oracle_digest,
                },
                "requirement_review": {
                    "id": review_record.id,
                    "artifact_digest": review_record.artifact_digest,
                    "result_digest": review_record.result_digest,
                    "source_sha256": review_record.source_sha256,
                },
                "point_reconciliation": {
                    "id": point_record.id,
                    "artifact_digest": point_record.artifact_digest,
                    "result_digest": point_record.result_digest,
                    "source_sha256": point_record.source_sha256,
                },
                "configuration_digest": brief["configuration_digest"],
                "generation_request": request.model_dump(mode="json"),
                "preflight": preflight,
            }
            source_documents = {
                f"points-{point_record.source_filename}": (
                    ctrl_flow_point_repository.source(point_record.id)
                ),
                f"sequence-{review_record.source_filename}": (
                    sequence_review_repository.source(review_record.id)
                ),
                "approved-sequence-evidence.json": canonical_json(evidence).encode("utf-8"),
            }
            run = service.create_run(job, source_documents=source_documents)
            return JSONResponse(
                status_code=201,
                content={
                    "schema": "bactalk.sequence-candidate-generation/v1",
                    "preflight": preflight,
                    "run": run.model_dump(mode="json"),
                    "safety": {
                        "live_writes_enabled": False,
                        "human_approval_required": True,
                        "candidate_retained": True,
                        "candidate_authorizes_deployment": False,
                    },
                },
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="candidate generation evidence chain is incomplete"
            ) from exc
        except HTTPException:
            raise
        except (
            CtrlFlowPointIntegrityError,
            SequenceReviewIntegrityError,
            SequenceOracleIntegrityError,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (CtrlFlowError, ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/library/g36/controllers/{controller_id}/translate")
    def translate_g36_controller(
        controller_id: str,
        request: G36ParameterRequest | None = None,
        execution_profile: Literal["modelica_exact", "host_tick_v1"] = "modelica_exact",
    ) -> dict:
        try:
            return g36_library.translate(
                controller_id,
                execution_profile=execution_profile,
                parameters=request.parameters if request is not None else None,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="G36 controller not found") from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/library/g36/controllers/{controller_id}/parameters")
    def inspect_g36_controller_parameters(controller_id: str) -> dict:
        try:
            return g36_library.parameter_schema(controller_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="G36 controller not found") from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/library/g36/controllers/{controller_id}/job-template")
    def build_g36_controller_job_template(
        controller_id: str,
        request: G36ParameterRequest | None = None,
        execution_profile: Literal["modelica_exact", "host_tick_v1"] = "modelica_exact",
    ) -> dict:
        try:
            return g36_library.job_template(
                controller_id,
                parameters=request.parameters if request is not None else None,
                execution_profile=execution_profile,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="G36 controller not found") from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (
            NiagaraProgramCodegenError,
            ValueError,
            RuntimeError,
            json.JSONDecodeError,
        ) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/library/g36/controllers/{controller_id}/flatten")
    def flatten_g36_controller(controller_id: str, request: G36FlattenRequest) -> dict:
        """Elaborate an allowlisted G36 class into source-bound flattened Modelica IR."""

        try:
            return rumoca.flatten_g36(controller_id, parameters=request.parameters)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="G36 controller not found") from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (RumocaError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/library/g36/controllers/{controller_id}/niagara-program-package")
    def build_g36_niagara_program_package(
        controller_id: str,
        request: G36ParameterRequest | None = None,
        execution_profile: Literal["modelica_exact", "host_tick_v1"] = "modelica_exact",
    ) -> Response:
        try:
            content, filename = g36_library.niagara_program_package(
                controller_id,
                parameters=request.parameters if request is not None else None,
                execution_profile=execution_profile,
            )
            return Response(
                content=content,
                media_type="application/zip",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="G36 controller not found") from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (
            NiagaraProgramCodegenError,
            ValueError,
            RuntimeError,
            json.JSONDecodeError,
        ) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/library/aixocat/patterns")
    def aixocat_pattern_catalog() -> dict:
        try:
            return aixocat_library.catalog()
        except (FileNotFoundError, AixocatError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/library/aixocat/patterns/{pattern_id}")
    def inspect_aixocat_pattern(pattern_id: str) -> dict:
        try:
            return aixocat_library.inspect(pattern_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="AixOCAT pattern not found") from exc
        except (FileNotFoundError, AixocatError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/library/aixocat/patterns/{pattern_id}/translate")
    def translate_aixocat_pattern(pattern_id: str, request: AixocatTranslationRequest) -> dict:
        try:
            return aixocat_library.translate(
                pattern_id,
                parameters=request.parameters,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="AixOCAT pattern not found") from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except AixocatError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/library/g36/controllers/{controller_id}/execute")
    def execute_g36_controller(controller_id: str, request: G36ExecutionRequest) -> dict:
        try:
            return g36_library.execute(
                controller_id,
                samples=[sample.model_dump(mode="json") for sample in request.samples],
                collect=request.collect,
                parameters=request.parameters,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="G36 controller not found") from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/library/plant-controls/controllers")
    def plant_controls_catalog() -> dict:
        try:
            return plant_controls_library.catalog()
        except (FileNotFoundError, RuntimeError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/library/plant-controls/controllers/{controller_id}/parameters")
    def inspect_plant_controller_parameters(controller_id: str) -> dict:
        try:
            return plant_controls_library.parameter_schema(controller_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="plant controller not found") from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/library/plant-controls/controllers/{controller_id}/job-template")
    def build_plant_controller_job_template(
        controller_id: str,
        request: G36ParameterRequest | None = None,
        execution_profile: Literal["modelica_exact", "host_tick_v1"] = "modelica_exact",
    ) -> dict:
        try:
            return plant_controls_library.job_template(
                controller_id,
                parameters=request.parameters if request is not None else None,
                execution_profile=execution_profile,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="plant controller not found") from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/library/plant-controls/controllers/{controller_id}/translate")
    def translate_plant_controller(
        controller_id: str,
        request: G36ParameterRequest | None = None,
        execution_profile: Literal["modelica_exact", "host_tick_v1"] = "modelica_exact",
    ) -> dict:
        try:
            return plant_controls_library.translate(
                controller_id,
                execution_profile=execution_profile,
                parameters=request.parameters if request is not None else None,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="plant controller not found") from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/library/plant-controls/controllers/{controller_id}/execute")
    def execute_plant_controller(controller_id: str, request: G36ExecutionRequest) -> dict:
        try:
            return plant_controls_library.execute(
                controller_id,
                samples=[sample.model_dump(mode="json") for sample in request.samples],
                collect=request.collect,
                parameters=request.parameters,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="plant controller not found") from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/library/plant-controls/controllers/{controller_id}/niagara-program-package")
    def build_plant_niagara_program_package(
        controller_id: str,
        request: G36ParameterRequest | None = None,
        execution_profile: Literal["modelica_exact", "host_tick_v1"] = "modelica_exact",
    ) -> Response:
        try:
            content, filename = plant_controls_library.niagara_program_package(
                controller_id,
                parameters=request.parameters if request is not None else None,
                execution_profile=execution_profile,
            )
            return Response(
                content=content,
                media_type="application/zip",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="plant controller not found") from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (
            NiagaraProgramCodegenError,
            ValueError,
            RuntimeError,
            json.JSONDecodeError,
        ) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/library/open-control/faults")
    def open_control_fault_catalog() -> dict:
        try:
            return open_control_library.catalog()
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/library/open-control/faults/{rule_id}/translate")
    def translate_open_control_fault(rule_id: str) -> dict:
        try:
            graph, vector_report = open_control_library.translate(rule_id)
            return {
                "graph": graph.model_dump(mode="json"),
                "coverage": graph.metadata["coverage"],
                "vector_report": vector_report,
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="fault rule not found") from exc
        except (CxfImportError, CxfVectorError, FileNotFoundError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/library/niagara-programs")
    def niagara_program_catalog() -> dict:
        try:
            return niagara_program_library.catalog()
        except (FileNotFoundError, NiagaraProgramLibraryError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/library/niagara-programs/{template_id}")
    def inspect_niagara_program(template_id: str) -> dict:
        try:
            return niagara_program_library.inspect(template_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Niagara template not found") from exc
        except (FileNotFoundError, NiagaraProgramLibraryError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/projects/preflight")
    def preflight_project(project: ProjectSpec) -> dict:
        return project_preflight.assess(project)

    @app.get("/api/projects")
    def list_projects() -> list[dict]:
        return [record.model_dump(mode="json") for record in project_repository.list()]

    @app.post("/api/projects/build", status_code=201)
    def build_project(project: ProjectSpec) -> dict:
        try:
            return project_builder.build(project).model_dump(mode="json")
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/projects/build-import", status_code=201)
    async def build_project_import(
        project_json: Annotated[str, Form(min_length=2, max_length=10_000_000)],
        station_template: Annotated[UploadFile, File()],
    ) -> dict:
        try:
            project = ProjectSpec.model_validate_json(project_json)
            template = await station_template.read()
            return project_builder.build(
                project,
                station_template=template,
            ).model_dump(mode="json")
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str) -> dict:
        try:
            return project_repository.get(project_id).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="project build not found") from exc

    @app.get("/api/projects/{project_id}/report")
    def get_project_report(project_id: str) -> JSONResponse:
        try:
            record = project_repository.get(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="project build not found") from exc
        if record.project_report_path is None:
            raise HTTPException(status_code=404, detail="project build has no project test report")
        return JSONResponse(
            json.loads(Path(record.project_report_path).read_text(encoding="utf-8"))
        )

    @app.post("/api/projects/{project_id}/approve")
    def approve_project(
        project_id: str,
        request: ApprovalRequest,
        http_request: Request,
    ) -> dict:
        try:
            reviewer, actor_id, tenant_id, authentication = review_identity(
                http_request, request.reviewer
            )
            return project_builder.approve(
                project_id,
                reviewer,
                actor_id=actor_id,
                tenant_id=tenant_id,
                authentication=authentication,
            ).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="project build not found") from exc
        except ApprovalRequiredError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ArtifactChangedError as exc:
            raise HTTPException(status_code=412, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/export")
    def export_project(project_id: str) -> FileResponse:
        try:
            path = project_builder.export_path(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="project build not found") from exc
        except ApprovalRequiredError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ArtifactChangedError as exc:
            raise HTTPException(status_code=412, detail=str(exc)) from exc
        return FileResponse(path, filename=path.name, media_type="application/zip")

    @app.get("/api/semantics/buildingmotif/{library}/catalog")
    def buildingmotif_catalog(
        library: Literal["g36", "chiller-plant", "ashrae-223p"],
    ) -> dict:
        try:
            return buildingmotif.catalog(library)
        except BuildingMotifError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/semantics/buildingmotif/instantiate")
    def instantiate_buildingmotif(request: BuildingMotifInstantiationRequest) -> dict:
        try:
            return buildingmotif.instantiate(
                library=request.library,
                template=request.template,
                namespace=request.namespace,
                bindings=request.bindings,
            )
        except BuildingMotifError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/verify/haxall")
    def verify_haxall(request: HaxallValidationRequest) -> dict:
        try:
            result = haxall.validate_zinc(request.zinc, graph=request.graph)
            return {
                "engine": "Haxall/Xeto 4.0.4 via Phable",
                "conforms": result.conforms,
                "errors": result.errors,
                "raw_zinc": result.raw_zinc,
            }
        except HaxallError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/verify/constrain")
    def verify_constrain(request: ConStrainVerificationRequest) -> dict:
        try:
            return constrain.verify(
                rule=request.rule,
                rows=request.rows,
                parameters=request.parameters,
            )
        except ConStrainError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/verify/open-fdd")
    def verify_open_fdd(request: OpenFddVerificationRequest) -> dict:
        try:
            return open_fdd.verify(
                rule_id=request.rule_id,
                equipment_id=request.equipment_id,
                equipment_kind=request.equipment_kind,
                equipment_type=request.equipment_type,
                poll_seconds=request.poll_seconds,
                rows=request.rows,
                parameters=request.parameters,
                require_operational_gates=request.require_operational_gates,
            )
        except OpenFddError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/integrations/boptest/catalog")
    def get_boptest_catalog() -> dict:
        client = make_boptest_client()
        try:
            return discover_boptest_catalog(client)
        except (BoptestError, httpx.HTTPError) as exc:
            raise HTTPException(
                status_code=503,
                detail=f"BOPTEST catalog is unavailable: {exc}",
            ) from exc
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    @app.get("/api/integrations/boptest/catalog/{test_case}")
    def get_boptest_test_case_contract(test_case: str) -> dict:
        client = make_boptest_client()
        try:
            return inspect_boptest_test_case(client, test_case)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (BoptestError, httpx.HTTPError) as exc:
            raise HTTPException(
                status_code=503,
                detail=f"BOPTEST test-case inspection failed: {exc}",
            ) from exc
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    @app.get("/api/runs")
    def list_runs() -> list[dict]:
        return [record.model_dump(mode="json") for record in repository.list()]

    @app.post("/api/runs", status_code=201)
    def create_run(job: JobSpec) -> dict:
        try:
            return service.create_run(job).model_dump(mode="json")
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/runs/{run_id}/qualification-jobs/alfalfa", status_code=202)
    async def enqueue_alfalfa_qualification(
        run_id: str,
        http_request: Request,
        model_file: Annotated[UploadFile, File()],
        qualification: Annotated[str, Form(min_length=2, max_length=5_000_000)],
    ) -> dict:
        try:
            request = AlfalfaQualificationRequest.model_validate_json(qualification)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Alfalfa qualification request is invalid: {exc}",
            ) from exc
        model_bytes = await model_file.read(MAX_ALFALFA_MODEL_BYTES + 1)
        if len(model_bytes) > MAX_ALFALFA_MODEL_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Alfalfa FMU exceeds the {MAX_ALFALFA_MODEL_BYTES}-byte limit",
            )
        try:
            candidate = repository.get(run_id)
            if candidate.status != RunStatus.READY_FOR_REVIEW:
                raise HTTPException(
                    status_code=409,
                    detail="qualification requires a passing candidate awaiting review",
                )
            if candidate.alfalfa_verification_path is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Alfalfa qualification is append-once; create a new candidate to retest",
                )
            inspect_fmu_archive(
                model_bytes,
                filename=model_file.filename or "model.fmu",
            )
            principal: Principal | None = getattr(http_request.state, "principal", None)
            record = qualification_jobs.create(
                run_id=run_id,
                candidate_artifact_sha256=candidate.artifact_sha256,
                payload=request,
                model_bytes=model_bytes,
                model_filename=model_file.filename or "model.fmu",
                actor_id=principal.subject if principal is not None else None,
                tenant_id=principal.tenant_id if principal is not None else None,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except HTTPException:
            raise
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            dispatch_qualification.enqueue(record)
        except Exception as exc:
            failed = qualification_jobs.mark_failed(
                record.id, f"Qualification queue dispatch failed: {type(exc).__name__}: {exc}"
            )
            raise HTTPException(
                status_code=503,
                detail={
                    "message": "qualification queue is unavailable",
                    "job": failed.model_dump(mode="json"),
                },
            ) from exc
        return record.model_dump(mode="json")

    @app.post("/api/runs/{run_id}/qualification-jobs/boptest", status_code=202)
    def enqueue_boptest_qualification(
        run_id: str,
        request: BoptestQualificationRequest,
        http_request: Request,
    ) -> dict:
        try:
            candidate = repository.get(run_id)
            if candidate.status != RunStatus.READY_FOR_REVIEW:
                raise HTTPException(
                    status_code=409,
                    detail="qualification requires a passing candidate awaiting review",
                )
            if candidate.boptest_verification_path is not None:
                raise HTTPException(
                    status_code=409,
                    detail="BOPTEST qualification is append-once; create a new candidate to retest",
                )
            principal: Principal | None = getattr(http_request.state, "principal", None)
            record = qualification_jobs.create_boptest(
                run_id=run_id,
                candidate_artifact_sha256=candidate.artifact_sha256,
                payload=request,
                actor_id=principal.subject if principal is not None else None,
                tenant_id=principal.tenant_id if principal is not None else None,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except HTTPException:
            raise
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            dispatch_qualification.enqueue(record)
        except Exception as exc:
            failed = qualification_jobs.mark_failed(
                record.id, f"Qualification queue dispatch failed: {type(exc).__name__}: {exc}"
            )
            raise HTTPException(
                status_code=503,
                detail={
                    "message": "qualification queue is unavailable",
                    "job": failed.model_dump(mode="json"),
                },
            ) from exc
        return record.model_dump(mode="json")

    @app.post("/api/runs/{run_id}/qualification-jobs/shadow", status_code=202)
    def enqueue_shadow_qualification(
        run_id: str,
        request: ShadowQualificationRequest,
        http_request: Request,
    ) -> dict:
        """Queue the candidate's .bog for the Niagara Shadow Runtime (N7, D5)."""

        try:
            candidate = repository.get(run_id)
            if candidate.status != RunStatus.READY_FOR_REVIEW:
                raise HTTPException(
                    status_code=409,
                    detail="qualification requires a passing candidate awaiting review",
                )
            if candidate.shadow_verification_path is not None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Shadow Runtime qualification is append-once; "
                        "create a new candidate to retest"
                    ),
                )
            if candidate.target_artifact_kind != TargetArtifactKind.NIAGARA_BOG:
                raise HTTPException(
                    status_code=409,
                    detail="Shadow Runtime qualification needs a native .bog target",
                )
            total_steps = sum(
                sum(phase.repeat for phase in case.timeline) if case.timeline else case.repeat
                for case in candidate.job.acceptance_tests
            )
            principal: Principal | None = getattr(http_request.state, "principal", None)
            record = qualification_jobs.create_shadow(
                run_id=run_id,
                candidate_artifact_sha256=candidate.artifact_sha256,
                payload=request,
                total_steps=total_steps + 1,
                actor_id=principal.subject if principal is not None else None,
                tenant_id=principal.tenant_id if principal is not None else None,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except HTTPException:
            raise
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            dispatch_qualification.enqueue(record)
        except Exception as exc:
            failed = qualification_jobs.mark_failed(
                record.id, f"Qualification queue dispatch failed: {type(exc).__name__}: {exc}"
            )
            raise HTTPException(
                status_code=503,
                detail={
                    "message": "qualification queue is unavailable",
                    "job": failed.model_dump(mode="json"),
                },
            ) from exc
        return record.model_dump(mode="json")

    @app.get("/api/runs/{run_id}/qualification-jobs/latest")
    def latest_qualification_job(run_id: str, http_request: Request) -> dict:
        try:
            record = qualification_jobs.latest_for_run(run_id)
            record = qualification_jobs.expire_stale(record.id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="qualification job not found") from exc
        except QualificationJobIntegrityError as exc:
            raise HTTPException(status_code=412, detail=str(exc)) from exc
        if not qualification_job_visible(http_request, record.tenant_id):
            raise HTTPException(status_code=404, detail="qualification job not found")
        return record.model_dump(mode="json")

    @app.get("/api/qualification-jobs/{job_id}")
    def get_qualification_job(job_id: str, http_request: Request) -> dict:
        try:
            record = qualification_jobs.get(job_id)
            record = qualification_jobs.expire_stale(record.id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="qualification job not found") from exc
        except QualificationJobIntegrityError as exc:
            raise HTTPException(status_code=412, detail=str(exc)) from exc
        if not qualification_job_visible(http_request, record.tenant_id):
            raise HTTPException(status_code=404, detail="qualification job not found")
        return record.model_dump(mode="json")

    @app.get("/api/qualification-jobs/{job_id}/events")
    async def stream_qualification_job_events(
        job_id: str,
        http_request: Request,
        limit: int | None = None,
    ) -> StreamingResponse:
        """Server-sent job progress: one event per second until the job ends.

        The stream re-reads the retained record each tick, so it reports the
        same status, progress, and heartbeat the polling endpoint does. A
        ``limit`` caps the number of events, which tests and short-lived
        clients use; the browser client falls back to polling when the
        stream is unavailable.
        """

        def snapshot() -> tuple[str, bool]:
            try:
                record = qualification_jobs.get(job_id)
                record = qualification_jobs.expire_stale(record.id)
            except (KeyError, ValueError):
                return (
                    "event: gone\ndata: "
                    + json.dumps({"detail": "qualification job not found"})
                    + "\n\n",
                    True,
                )
            except QualificationJobIntegrityError as exc:
                return (
                    "event: error\ndata: " + json.dumps({"detail": str(exc)}) + "\n\n",
                    True,
                )
            if not qualification_job_visible(http_request, record.tenant_id):
                return (
                    "event: gone\ndata: "
                    + json.dumps({"detail": "qualification job not found"})
                    + "\n\n",
                    True,
                )
            payload = {
                "id": record.id,
                "status": record.status.value,
                "progress": record.progress.model_dump(mode="json"),
                "heartbeat_at": (record.heartbeat_at.isoformat() if record.heartbeat_at else None),
                "updated_at": record.updated_at.isoformat(),
                "error": record.error,
                "qualification_passed": record.qualification_passed,
                "result_artifact_sha256": record.result_artifact_sha256,
                "cancellation_requested": record.cancellation_requested,
            }
            return (
                "event: progress\ndata: " + json.dumps(payload) + "\n\n",
                record.status in TERMINAL_JOB_STATUSES,
            )

        async def events():
            emitted = 0
            while True:
                chunk, done = snapshot()
                yield chunk
                emitted += 1
                if done or (limit is not None and emitted >= limit):
                    return
                if await http_request.is_disconnected():
                    return
                await asyncio.sleep(1.0)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/qualification-jobs/{job_id}/cancel")
    def cancel_qualification_job(job_id: str, http_request: Request) -> dict:
        try:
            current = qualification_jobs.get(job_id)
            if not qualification_job_visible(http_request, current.tenant_id):
                raise HTTPException(status_code=404, detail="qualification job not found")
            updated = qualification_jobs.request_cancel(job_id)
            dispatch_qualification.cancel(updated)
            return updated.model_dump(mode="json")
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="qualification job not found") from exc
        except QualificationJobIntegrityError as exc:
            raise HTTPException(status_code=412, detail=str(exc)) from exc

    @app.post("/api/runs/{run_id}/verify/boptest")
    def qualify_run_with_boptest(
        run_id: str,
        request: BoptestQualificationRequest,
    ) -> dict:
        client = make_boptest_client()
        try:
            record = service.qualify_with_boptest(
                run_id,
                client=client,
                mapping=request.mapping,
                oracles=request.oracles or None,
                steps=request.steps,
                step_seconds=request.step_seconds,
                start_time=request.start_time,
                warmup_period=request.warmup_period,
                scenario=request.scenario,
                cases=request.cases or None,
            )
            evidence = json.loads(service.boptest_verification_path(run_id).read_text())
            return {"run": record.model_dump(mode="json"), "evidence": evidence}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except ApprovalRequiredError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ArtifactChangedError as exc:
            raise HTTPException(status_code=412, detail=str(exc)) from exc
        except BoptestError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    @app.get("/api/runs/{run_id}/verify/boptest")
    def get_boptest_qualification(run_id: str) -> dict:
        try:
            return json.loads(service.boptest_verification_path(run_id).read_text())
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="run or BOPTEST qualification evidence not found",
            ) from exc
        except ArtifactChangedError as exc:
            raise HTTPException(status_code=412, detail=str(exc)) from exc

    @app.post("/api/runs/{run_id}/verify/shadow")
    def qualify_run_with_shadow(run_id: str, request: ShadowQualificationRequest) -> dict:
        """Run the Shadow Runtime qualification synchronously (small suites)."""

        try:
            record = service.qualify_with_shadow(
                run_id,
                policy=request.policy,
                kernel_backend=request.kernel_backend,
                band_set=request.band_set,
            )
            evidence = json.loads(service.shadow_verification_path(run_id).read_text())
            return {"run": record.model_dump(mode="json"), "evidence": evidence}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except ApprovalRequiredError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ArtifactChangedError as exc:
            raise HTTPException(status_code=412, detail=str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/verify/shadow")
    def get_shadow_qualification(run_id: str) -> dict:
        try:
            return json.loads(service.shadow_verification_path(run_id).read_text())
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="run or Shadow Runtime qualification evidence not found",
            ) from exc
        except ArtifactChangedError as exc:
            raise HTTPException(status_code=412, detail=str(exc)) from exc

    @app.post("/api/runs/{run_id}/verify/alfalfa")
    async def qualify_run_with_alfalfa(
        run_id: str,
        model_file: Annotated[UploadFile, File()],
        qualification: Annotated[str, Form(min_length=2, max_length=5_000_000)],
    ) -> dict:
        try:
            request = AlfalfaQualificationRequest.model_validate_json(qualification)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Alfalfa qualification request is invalid: {exc}",
            ) from exc
        model_bytes = await model_file.read(MAX_ALFALFA_MODEL_BYTES + 1)
        client = make_alfalfa_client()
        try:
            server_version: object = None
            if alfalfa_client_factory is None:
                response = httpx.get(
                    f"{alfalfa_base_url.rstrip('/')}/api/v2/version",
                    timeout=15.0,
                )
                response.raise_for_status()
                body = response.json()
                server_version = body.get("payload", body) if isinstance(body, dict) else body
            if request.transport == "bacnet_ip_loopback":
                record = await service.qualify_with_alfalfa_bacnet(
                    run_id,
                    client=client,
                    mapping=request.mapping,
                    oracles=request.oracles,
                    model_bytes=model_bytes,
                    model_filename=model_file.filename or "model.fmu",
                    steps=request.steps,
                    step_seconds=request.step_seconds,
                    start=request.start,
                    server_version=server_version,
                    client_version=metadata.version("alfalfa-client"),
                )
            else:
                record = service.qualify_with_alfalfa(
                    run_id,
                    client=client,
                    mapping=request.mapping,
                    oracles=request.oracles,
                    model_bytes=model_bytes,
                    model_filename=model_file.filename or "model.fmu",
                    steps=request.steps,
                    step_seconds=request.step_seconds,
                    start=request.start,
                    server_version=server_version,
                    client_version=metadata.version("alfalfa-client"),
                )
            evidence = json.loads(service.alfalfa_verification_path(run_id).read_text())
            return {"run": record.model_dump(mode="json"), "evidence": evidence}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except ApprovalRequiredError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ArtifactChangedError as exc:
            raise HTTPException(status_code=412, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    @app.post("/api/integrations/alfalfa/inspect-fmu")
    async def inspect_alfalfa_fmu(
        model_file: Annotated[UploadFile, File()],
    ) -> dict:
        model_bytes = await model_file.read(MAX_ALFALFA_MODEL_BYTES + 1)
        if len(model_bytes) > MAX_ALFALFA_MODEL_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Alfalfa FMU exceeds the {MAX_ALFALFA_MODEL_BYTES}-byte limit",
            )
        try:
            return inspect_fmu_archive(
                model_bytes,
                filename=model_file.filename or "model.fmu",
            ).model_dump(mode="json", by_alias=True)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/verify/alfalfa")
    def get_alfalfa_qualification(run_id: str) -> dict:
        try:
            return json.loads(service.alfalfa_verification_path(run_id).read_text())
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="run or Alfalfa qualification evidence not found",
            ) from exc
        except ArtifactChangedError as exc:
            raise HTTPException(status_code=412, detail=str(exc)) from exc

    @app.post("/api/intake/station-bindings")
    async def suggest_station_bindings(
        station_bog: Annotated[UploadFile, File()],
        points_file: Annotated[UploadFile, File()],
        sequence_family: Annotated[
            str,
            Form(pattern=r"^(AUTO|[A-Za-z][A-Za-z0-9_.-]*)$", max_length=120),
        ] = "AUTO",
    ) -> dict:
        """Parse a contractor station as data and suggest proxy points for each job point.

        Suggestions only: a human confirms them in the intake UI and the confirmed
        bindings travel with the import as ``point_bindings``.
        """

        station = await station_bog.read()
        try:
            validate_template_bog(station)
            inventory = parse_station_inventory(station)
            points_content = await points_file.read()
            points = parse_points_file(points_content, points_file.filename or "points.csv")
            if sequence_family != "AUTO":
                points = list(canonicalize_points(points, sequence_family).points)
        except (IntakeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        suggestions = suggest_bindings(points, inventory.points)
        return {
            "schema": "bactalk.station-binding-suggestions/v1",
            "inventory": inventory.to_dict(),
            "points": [point.model_dump(mode="json") for point in points],
            "suggestions": {
                name: [item.to_dict() for item in items] for name, items in suggestions.items()
            },
            "policy": {
                "human_confirmation_required": True,
                "write_priority": "explicit, 2-16; priority 1 and implicit priorities are refused",
            },
        }

    @app.post("/api/intake/inspect")
    async def inspect_contractor_intake(
        points_file: Annotated[UploadFile, File()],
        sequence_document: Annotated[UploadFile | None, File()] = None,
        sequence_family: Annotated[
            str,
            Form(pattern=r"^(AUTO|[A-Za-z][A-Za-z0-9_.-]*)$", max_length=120),
        ] = "AUTO",
    ) -> dict:
        try:
            points = parse_points_file(
                await points_file.read(),
                points_file.filename or "points.csv",
            )
            sequence = (
                parse_sequence_document(
                    await sequence_document.read(),
                    sequence_document.filename or "sequence.txt",
                    sequence_document.content_type,
                )
                if sequence_document
                else None
            )
            selected_family = sequence_family if sequence_family != "AUTO" else None
            if selected_family is None and sequence and sequence.suggested_sequence_families:
                highest = float(sequence.suggested_sequence_families[0]["confidence"])
                tied = [
                    item
                    for item in sequence.suggested_sequence_families
                    if float(item["confidence"]) == highest
                ]
                if len(tied) == 1:
                    selected_family = str(tied[0]["family"])
            mapping = (
                canonicalize_points(points, selected_family)
                if selected_family is not None
                else None
            )
            inspected_points = list(mapping.points) if mapping else points
            return {
                "schema": "bactalk-intake-inspection/v1",
                "point_count": len(inspected_points),
                "points": [point.model_dump(mode="json") for point in inspected_points],
                "mapped_bacnet_points": sum(
                    point.bacnet_object is not None for point in inspected_points
                ),
                "selected_sequence_family": selected_family,
                "canonical_point_mappings": list(mapping.mappings) if mapping else [],
                "missing_required_points": list(mapping.missing_required) if mapping else [],
                "sequence": sequence.model_dump(mode="json") if sequence else None,
                "build_started": False,
                "writes_enabled": False,
            }
        except (IntakeError, PointMappingError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/runs/import", status_code=201)
    async def import_run(
        name: Annotated[str, Form(min_length=1, max_length=200)],
        site: Annotated[str, Form(min_length=1, max_length=200)],
        equipment_name: Annotated[str, Form(min_length=1, max_length=120)],
        points_csv: Annotated[UploadFile | None, File()] = None,
        points_file: Annotated[UploadFile | None, File()] = None,
        sequence_family: Annotated[
            str,
            Form(pattern=r"^(AUTO|[A-Za-z][A-Za-z0-9_.-]*)$", max_length=120),
        ] = "G36_VAV_REHEAT",
        sequence_version: Annotated[str, Form(max_length=200)] = (
            "Contractor sequence of operations"
        ),
        sequence_parameters: Annotated[str, Form(max_length=10_000)] = "{}",
        sequence_library: Annotated[
            str,
            Form(pattern=r"^(|plant_controls|g36)$", max_length=40),
        ] = "",
        controller_id: Annotated[
            str | None,
            Form(pattern=r"^[A-Za-z][A-Za-z0-9_.]*$", max_length=240),
        ] = None,
        execution_profile: Annotated[
            Literal["modelica_exact", "host_tick_v1"],
            Form(),
        ] = "modelica_exact",
        expert_program_objects: Annotated[bool, Form()] = False,
        point_bindings: Annotated[str, Form(max_length=200_000)] = "{}",
        deliverable_requirements: Annotated[str, Form(max_length=100_000)] = "{}",
        acceptance_tests: Annotated[str, Form(max_length=200_000)] = "[]",
        notes: Annotated[str | None, Form(max_length=5_000)] = None,
        sequence_document: Annotated[UploadFile | None, File()] = None,
        bacnet_scan: Annotated[UploadFile | None, File()] = None,
        template_bog: Annotated[UploadFile | None, File()] = None,
        environment_pack: Annotated[UploadFile | None, File()] = None,
    ) -> dict:
        try:
            parameters = _form_json_object(sequence_parameters, "sequence parameters")
            deliverables_payload = _form_json_object(
                deliverable_requirements, "deliverable requirements"
            )
            deliverables = DeliverableRequirements.model_validate(deliverables_payload)
            acceptance_cases = _form_acceptance_tests(acceptance_tests)
            uploaded_points = points_file or points_csv
            if uploaded_points is None:
                raise IntakeError("a points .csv or .xlsx file is required")
            points_content = await uploaded_points.read()
            points = parse_points_file(
                points_content,
                uploaded_points.filename or "points.csv",
            )
            sequence_content = await sequence_document.read() if sequence_document else None
            sequence_source = (
                parse_sequence_document(
                    sequence_content,
                    sequence_document.filename or "sequence.txt",
                    sequence_document.content_type,
                )
                if sequence_document
                else None
            )
            if sequence_family == "AUTO":
                suggestions = sequence_source.suggested_sequence_families if sequence_source else []
                if not suggestions:
                    raise IntakeError(
                        "automatic sequence selection found no supported family; choose a family "
                        "or use the AI programmer to propose a typed custom graph"
                    )
                highest = float(suggestions[0]["confidence"])
                tied = [item for item in suggestions if float(item["confidence"]) == highest]
                if len(tied) != 1:
                    raise IntakeError(
                        "automatic sequence selection is ambiguous: "
                        + ", ".join(str(item["family"]) for item in tied)
                    )
                sequence_family = str(tied[0]["family"])
            ai_custom = sequence_family == "AI_CUSTOM"
            if ai_custom and coding_provider is None:
                raise IntakeError(
                    "AI custom programming is unavailable; configure CEREBRAS_API_KEY and "
                    "restart BACTalk"
                )
            if ai_custom and sequence_source is None:
                raise IntakeError("AI custom programming requires a sequence document")
            if ai_custom and not acceptance_cases:
                raise IntakeError(
                    "AI custom programming requires engineer-authored acceptance tests; the "
                    "model is not allowed to grade its own work"
                )
            mapping = canonicalize_points(points, sequence_family)
            points = list(mapping.points)
            confirmed_bindings = _form_json_object(point_bindings, "point bindings")
            if confirmed_bindings:
                try:
                    points = apply_bindings(points, confirmed_bindings)
                except ValueError as exc:
                    raise IntakeError(str(exc)) from exc
            deliverables = canonicalize_deliverable_requirements(deliverables, points)
            scan_content = await bacnet_scan.read() if bacnet_scan else None
            scan = parse_bacnet_scan_json(scan_content) if scan_content is not None else None
            template = await template_bog.read() if template_bog else None
            environment = await environment_pack.read() if environment_pack else None
            job = JobSpec(
                name=name,
                site=site,
                equipment_name=equipment_name,
                sequence=SequenceSpec(
                    family=sequence_family,
                    version=sequence_version,
                    parameters=parameters,
                    library=sequence_library or None,
                    controller_id=controller_id,
                    execution_profile=execution_profile,
                    expert_program_objects=expert_program_objects,
                    source_filename=(sequence_source.filename if sequence_source else None),
                    source_media_type=(sequence_source.media_type if sequence_source else None),
                    source_sha256=(sequence_source.sha256 if sequence_source else None),
                    source_text=(sequence_source.text if sequence_source else None),
                ),
                points=points,
                acceptance_tests=acceptance_cases,
                deliverables=deliverables,
                bacnet_scan=scan,
                notes=notes,
            )
            source_documents = {
                f"points-{uploaded_points.filename or 'points.csv'}": points_content,
            }
            if sequence_document is not None and sequence_content is not None:
                source_documents[f"sequence-{sequence_document.filename or 'sequence.txt'}"] = (
                    sequence_content
                )
            if bacnet_scan is not None and scan_content is not None:
                source_documents[f"bacnet-{bacnet_scan.filename or 'scan.json'}"] = scan_content
            if ai_custom:
                chat_agent = ControlsChatAgent(chat_provider, coding_provider)
                envelope = chat_agent.draft(job)
                proposal = envelope.graph()
                if proposal is None:  # guarded by ControlsChatAgent.draft
                    raise AIProviderError("AI custom programming returned no graph")
                proposal = proposal.model_copy(
                    update={
                        "metadata": {
                            **proposal.metadata,
                            "ai_draft": {
                                "model": coding_provider.model,
                                "message": envelope.message,
                                "assumptions": envelope.assumptions,
                            },
                        }
                    }
                )
                return service.create_run(
                    job,
                    template_bog=template,
                    environment_pack=environment,
                    source_documents=source_documents,
                    origin=RunOrigin.AI_PROPOSAL,
                    planner=ProposedGraphPlanner(proposal, chat_agent),
                ).model_dump(mode="json")
            return service.create_run(
                job,
                template_bog=template,
                environment_pack=environment,
                source_documents=source_documents,
            ).model_dump(mode="json")
        except AIProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except (IntakeError, PointMappingError, ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/runs/demo", status_code=201)
    def create_demo_run() -> dict:
        return service.create_run(lbnl_vav_reheat_demo_job()).model_dump(mode="json")

    @app.post("/api/runs/demo/generalist", status_code=201)
    def create_generalist_demo_run() -> dict:
        return service.create_run(lbnl_multizone_ahu_demo_job()).model_dump(mode="json")

    @app.post("/api/runs/demo/standard-vav", status_code=201)
    def create_standard_vav_demo_run() -> dict:
        """The bounded standard VAV pack with BACnet mappings (not Guideline 36)."""
        return service.create_run(standard_vav_demo_job()).model_dump(mode="json")

    @app.post("/api/runs/demo/standard-ahu", status_code=201)
    def create_standard_ahu_demo_run() -> dict:
        """The AHU safety/cooling pack fixture used by the whole-building demo."""
        return service.create_run(standard_ahu_demo_job()).model_dump(mode="json")

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        try:
            return repository.get(run_id).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc

    @app.get("/api/runs/{run_id}/graph")
    def get_graph(run_id: str) -> JSONResponse:
        try:
            path = Path(repository.get(run_id).graph_path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        return JSONResponse(json.loads(path.read_text(encoding="utf-8")))

    @app.get("/api/runs/{run_id}/report")
    def get_report(run_id: str) -> JSONResponse:
        try:
            path = Path(repository.get(run_id).report_path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        return JSONResponse(json.loads(path.read_text(encoding="utf-8")))

    @app.get("/api/runs/{run_id}/template-analysis")
    def get_template_analysis(run_id: str) -> JSONResponse:
        try:
            record = repository.get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        if not record.template_analysis_path:
            raise HTTPException(status_code=404, detail="run has no Niagara template")
        path = Path(record.template_analysis_path)
        return JSONResponse(json.loads(path.read_text(encoding="utf-8")))

    @app.get("/api/runs/{run_id}/station-assembly")
    def get_station_assembly(run_id: str) -> JSONResponse:
        try:
            record = repository.get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        if not record.station_assembly_manifest_path:
            raise HTTPException(status_code=404, detail="run has no assembled Niagara station")
        path = Path(record.station_assembly_manifest_path)
        return JSONResponse(json.loads(path.read_text(encoding="utf-8")))

    @app.get("/api/runs/{run_id}/volttron-manifest")
    def get_volttron_manifest(run_id: str) -> JSONResponse:
        try:
            record = repository.get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        if not record.volttron_manifest_path:
            raise HTTPException(status_code=404, detail="run has no BACnet scan")
        path = Path(record.volttron_manifest_path)
        return JSONResponse(json.loads(path.read_text(encoding="utf-8")))

    @app.get("/api/runs/{run_id}/nhaystack-manifest")
    def get_nhaystack_manifest(run_id: str) -> JSONResponse:
        try:
            record = repository.get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        if not record.nhaystack_manifest_path:
            raise HTTPException(status_code=404, detail="run has no nHaystack package")
        path = Path(record.nhaystack_manifest_path)
        return JSONResponse(json.loads(path.read_text(encoding="utf-8")))

    @app.get("/api/runs/{run_id}/bacnet-lab-manifest")
    def get_bacnet_lab_manifest(run_id: str) -> JSONResponse:
        try:
            record = repository.get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        if not record.bacnet_lab_manifest_path:
            raise HTTPException(status_code=404, detail="run has no BACnet lab")
        path = Path(record.bacnet_lab_manifest_path)
        return JSONResponse(json.loads(path.read_text(encoding="utf-8")))

    @app.post("/api/runs/{run_id}/bacnet-lab/probe")
    async def probe_bacnet_lab(run_id: str) -> dict:
        """Boot the signed loopback lab and read every mapped point through BAC0."""

        try:
            record = repository.get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        if not record.bacnet_lab_manifest_path:
            raise HTTPException(status_code=404, detail="run has no BACnet lab")
        manifest_path = Path(record.bacnet_lab_manifest_path)
        lab = VirtualBacnetLab.load(manifest_path)
        try:
            await lab.start()
            await asyncio.sleep(0.05)
            result = await probe_manifest_with_bac0(
                manifest_path,
                client_port=_free_loopback_udp_port(),
            )
        except OptionalDependencyError:
            # A capability whose extra was never installed is a 503 with
            # remediation, not a 409 that reads like a product defect.
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail=f"BACnet loopback probe could not run: {exc}",
            ) from exc
        finally:
            lab.close()
        return {
            **result,
            "run_id": run_id,
            "lab_mode": "isolated-loopback",
            "live_network_routes_allowed": False,
        }

    @app.get("/api/runs/{run_id}/environment-manifest")
    def get_environment_manifest(run_id: str) -> JSONResponse:
        try:
            record = repository.get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        if not record.environment_manifest_path:
            raise HTTPException(status_code=404, detail="run has no contractor environment pack")
        path = Path(record.environment_manifest_path)
        return JSONResponse(json.loads(path.read_text(encoding="utf-8")))

    @app.get("/api/runs/{run_id}/deliverables")
    def get_deliverables(run_id: str) -> JSONResponse:
        try:
            record = repository.get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        if not record.deliverable_manifest_path:
            raise HTTPException(status_code=404, detail="run has no deliverable manifest")
        return JSONResponse(
            json.loads(Path(record.deliverable_manifest_path).read_text(encoding="utf-8"))
        )

    @app.get("/api/runs/{run_id}/release-summary")
    def get_release_summary(run_id: str) -> dict:
        """Return the server-verified release contract for one immutable candidate."""

        try:
            record = service.verify_integrity(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except ArtifactChangedError as exc:
            raise HTTPException(status_code=412, detail=str(exc)) from exc
        report = json.loads(Path(record.report_path).read_text(encoding="utf-8"))
        deliverables = (
            json.loads(Path(record.deliverable_manifest_path).read_text(encoding="utf-8"))
            if record.deliverable_manifest_path
            else None
        )
        scenarios = report.get("scenarios", [])
        assertion_count = sum(len(item.get("assertions", [])) for item in scenarios)
        passed_assertions = sum(
            assertion.get("passed") is True
            for item in scenarios
            for assertion in item.get("assertions", [])
        )
        target_path_value = (
            record.assembled_bog_path or record.target_artifact_path or record.bog_path
        )
        approved = record.status.value == "approved" and record.approval is not None
        return {
            "schema": "bactalk.release-summary/v1",
            "run_id": record.id,
            "status": record.status.value,
            "integrity": {
                "verified": True,
                "artifact_sha256": record.artifact_sha256,
            },
            "behavior": {
                "passed": report.get("passed") is True,
                "scenario_count": len(scenarios),
                "assertion_count": assertion_count,
                "passed_assertion_count": passed_assertions,
            },
            "target": {
                "artifact_kind": record.target_artifact_kind.value,
                "filename": Path(target_path_value).name if target_path_value else None,
                "manual_import_required": True,
                "licensed_runtime_qualified": False,
            },
            "deliverables": {
                "available": deliverables is not None,
                "deployment_ready": bool(
                    deliverables and deliverables.get("deployment_ready") is True
                ),
                "artifacts": deliverables.get("artifacts", []) if deliverables else [],
                "coverage": deliverables.get("coverage", {}) if deliverables else {},
                "blocking_gates": (deliverables.get("blocking_gates", []) if deliverables else []),
            },
            "shadow": _shadow_summary(record),
            "approval": (record.approval.model_dump(mode="json") if record.approval else None),
            "downloads": {
                "available": approved,
                "target_url": f"/api/runs/{record.id}/export" if approved else None,
                "review_bundle_url": (f"/api/runs/{record.id}/review-bundle" if approved else None),
            },
            "safety": {
                "live_writes_enabled": False,
                "approval_authorizes_live_deployment": False,
            },
        }

    @app.get("/api/runs/{run_id}/niagara-alarm-plan")
    def get_niagara_alarm_plan(run_id: str) -> JSONResponse:
        try:
            record = repository.get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        path = next(
            (
                Path(value)
                for value in record.deliverable_artifact_paths
                if Path(value).name == "niagara-alarm-plan.json"
            ),
            None,
        )
        if path is None:
            raise HTTPException(status_code=404, detail="run has no Niagara alarm plan")
        return JSONResponse(json.loads(path.read_text(encoding="utf-8")))

    @app.get("/api/runs/{run_id}/graphics-model")
    def get_graphics_model(run_id: str) -> JSONResponse:
        try:
            record = repository.get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        path = next(
            (
                Path(value)
                for value in record.deliverable_artifact_paths
                if Path(value).name == "graphics-model.json"
            ),
            None,
        )
        if path is None:
            raise HTTPException(status_code=404, detail="run has no graphics model")
        return JSONResponse(json.loads(path.read_text(encoding="utf-8")))

    @app.get("/api/runs/{run_id}/niagara-previews")
    def get_niagara_previews(run_id: str) -> dict:
        """The native lane's per-folder wiresheet SVG previews (N4)."""

        try:
            folders = service.niagara_previews(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        if not folders:
            raise HTTPException(status_code=404, detail="run has no Niagara folder previews")
        return {
            "schema": "bactalk.niagara-previews/v1",
            "folders": [{"name": name, "svg": svg} for name, svg in folders],
        }

    @app.get("/api/runs/{run_id}/niagara-graphics-plan")
    def get_niagara_graphics_plan(run_id: str) -> JSONResponse:
        try:
            record = repository.get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        path = next(
            (
                Path(value)
                for value in record.deliverable_artifact_paths
                if Path(value).name == "niagara-graphics-plan.json"
            ),
            None,
        )
        if path is None:
            raise HTTPException(status_code=404, detail="run has no Niagara graphics plan")
        return JSONResponse(json.loads(path.read_text(encoding="utf-8")))

    @app.post("/api/runs/{run_id}/chat")
    def chat_with_program(run_id: str, request: ChatRequest) -> dict:
        if chat_provider is None or coding_provider is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "AI programmer is not configured; set CEREBRAS_API_KEY in the server "
                    "environment and restart BACTalk"
                ),
            )
        try:
            source_record = service.verify_integrity(run_id)
            source_graph = ControlGraph.model_validate_json(
                Path(source_record.graph_path).read_text(encoding="utf-8")
            )
            counterexample_artifacts: dict[str, dict[str, Any]] = {}
            for raw_path in source_record.verification_artifact_paths:
                artifact_path = Path(raw_path)
                if artifact_path.name != "counterexample.json":
                    continue
                lane = (
                    "boptest"
                    if "boptest-verification" in artifact_path.parts
                    else "alfalfa"
                    if "alfalfa-verification" in artifact_path.parts
                    else "verification"
                )
                case_directory = artifact_path.parent.parent.name
                case_id = (
                    case_directory.split("-", 2)[2]
                    if case_directory.startswith("case-") and len(case_directory.split("-", 2)) == 3
                    else "single-run"
                )
                context_id = f"{lane}/{case_id}/{artifact_path.parent.name}"
                counterexample_artifacts[context_id] = json.loads(
                    artifact_path.read_text(encoding="utf-8")
                )
            verification_failures = summarize_verification_failures(counterexample_artifacts)
            chat_agent = ControlsChatAgent(chat_provider, coding_provider)
            if source_record.job.sequence.library in {"plant_controls", "g36"}:
                controller_id = source_record.job.sequence.controller_id
                if controller_id is None:
                    raise ValueError("library run has no controller_id")
                selected_library = (
                    plant_controls_library
                    if source_record.job.sequence.library == "plant_controls"
                    else g36_library
                )
                envelope = chat_agent.respond_library(
                    source_record.job,
                    source_graph,
                    request,
                    parameter_schema=selected_library.parameter_schema(controller_id),
                    verification_failures=verification_failures,
                )
                proposed_parameters = envelope.parameters()
                proposal = None
            else:
                envelope = chat_agent.respond(
                    source_record.job,
                    source_graph,
                    request,
                    verification_failures=verification_failures,
                )
                proposed_parameters = None
                proposal = envelope.graph()
            new_record = None
            if proposal is not None or proposed_parameters is not None:
                # The source artifact remains immutable. A model proposal always
                # becomes a separate run with its own tests, hash, and approval.
                if proposed_parameters is not None:
                    missing_parameters = sorted(
                        set(source_record.job.sequence.parameters) - set(proposed_parameters)
                    )
                    if missing_parameters:
                        raise AIProviderError(
                            "Configuration model omitted existing parameters: "
                            + ", ".join(missing_parameters)
                        )
                    sequence_payload = source_record.job.sequence.model_dump(mode="json")
                    sequence_payload["parameters"] = proposed_parameters
                    derived_sequence = SequenceSpec.model_validate(sequence_payload)
                else:
                    derived_sequence = source_record.job.sequence
                derived_job = source_record.job.model_copy(
                    update={"control_graph": None, "sequence": derived_sequence}
                )
                inherited_sources = {
                    Path(path).name: Path(path).read_bytes()
                    for path in source_record.source_artifact_paths
                }
                inherited_template = (
                    Path(source_record.template_bog_path).read_bytes()
                    if source_record.template_bog_path
                    else None
                )
                inherited_environment = (
                    Path(source_record.environment_pack_path).read_bytes()
                    if source_record.environment_pack_path
                    else None
                )
                new_record = service.create_run(
                    derived_job,
                    template_bog=inherited_template,
                    environment_pack=inherited_environment,
                    source_documents=inherited_sources,
                    baseline_graph=source_graph,
                    origin=RunOrigin.AI_PROPOSAL,
                    parent_run_id=source_record.id,
                    planner=(
                        ProposedGraphPlanner(proposal, chat_agent) if proposal is not None else None
                    ),
                )
            return {
                "message": envelope.message,
                "intent": envelope.intent,
                "assumptions": envelope.assumptions,
                "source_run_id": source_record.id,
                "new_run": (new_record.model_dump(mode="json") if new_record is not None else None),
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except AIProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except ArtifactChangedError as exc:
            raise HTTPException(status_code=412, detail=str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/runs/{run_id}/approve")
    def approve_run(run_id: str, request: ApprovalRequest, http_request: Request) -> dict:
        try:
            reviewer, actor_id, tenant_id, authentication = review_identity(
                http_request, request.reviewer
            )
            return service.approve(
                run_id,
                reviewer,
                actor_id=actor_id,
                tenant_id=tenant_id,
                authentication=authentication,
                expected_artifact_sha256=request.artifact_sha256,
            ).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except ApprovalRequiredError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ArtifactChangedError as exc:
            raise HTTPException(status_code=412, detail=str(exc)) from exc

    @app.post("/api/runs/{run_id}/reject")
    def reject_run(run_id: str, request: RejectionRequest, http_request: Request) -> dict:
        try:
            reviewer, actor_id, tenant_id, authentication = review_identity(
                http_request, request.reviewer
            )
            return service.reject(
                run_id,
                reviewer,
                request.reason,
                actor_id=actor_id,
                tenant_id=tenant_id,
                authentication=authentication,
            ).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except ApprovalRequiredError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ArtifactChangedError as exc:
            raise HTTPException(status_code=412, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/export")
    def export_run(run_id: str) -> FileResponse:
        try:
            path = service.export_path(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except ApprovalRequiredError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ArtifactChangedError as exc:
            raise HTTPException(status_code=412, detail=str(exc)) from exc
        return FileResponse(path, filename=path.name, media_type="application/zip")

    @app.get("/api/runs/{run_id}/review-bundle")
    def export_review_bundle(run_id: str) -> FileResponse:
        try:
            path = service.review_bundle_path(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except ApprovalRequiredError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ArtifactChangedError as exc:
            raise HTTPException(status_code=412, detail=str(exc)) from exc
        return FileResponse(path, filename=path.name, media_type="application/zip")

    # The React workbench owns the root. The retired static workbench stays
    # reachable at /legacy for one transition period; /next keeps old links
    # working and serves the same bundle.
    static_dir = Path(__file__).parent / "static"
    app.mount("/legacy", StaticFiles(directory=static_dir, html=True), name="legacy-workbench")
    static_next_dir = Path(__file__).parent / "static-next"
    if static_next_dir.is_dir():
        app.mount(
            "/next",
            SPAStaticFiles(directory=static_next_dir, html=True),
            name="next-workbench",
        )
        app.mount("/", SPAStaticFiles(directory=static_next_dir, html=True), name="workbench")
    else:
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="workbench")
    return app


app = create_app()
