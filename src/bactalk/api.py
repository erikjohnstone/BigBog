from __future__ import annotations

import asyncio
import json
import os
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Match
from starlette.types import Scope

from bactalk.ai import (
    AIProviderError,
    CerebrasProvider,
    ChatRequest,
    ControlsChatAgent,
    ProposedGraphPlanner,
    StructuredChatProvider,
)
from bactalk.capabilities import CapabilityRegistry
from bactalk.demo import demo_job, generalist_demo_job
from bactalk.domain import (
    AcceptanceCase,
    ControlGraph,
    DeliverableRequirements,
    JobSpec,
    PointSpec,
    RunOrigin,
    SequenceSpec,
)
from bactalk.intake import (
    IntakeError,
    parse_bacnet_scan_json,
    parse_points_file,
    parse_sequence_document,
)
from bactalk.integrations.aixocat import AixocatError, AixocatLibrary
from bactalk.integrations.bacnet_lab import VirtualBacnetLab, probe_manifest_with_bac0
from bactalk.integrations.boptest import BoptestClient, BoptestError
from bactalk.integrations.boptest_graph import (
    BoptestGraphMap,
    BoptestRuntime,
    BoptestTrajectoryOracle,
)
from bactalk.integrations.buildingmotif import BuildingMotifAdapter, BuildingMotifError
from bactalk.integrations.constrain import ConStrainError, ConStrainVerifier
from bactalk.integrations.ctrl_flow import CtrlFlowError, CtrlFlowLibrary
from bactalk.integrations.cxf_importer import CxfImporter, CxfImportError
from bactalk.integrations.cxf_vectors import CxfVectorError, CxfVectorVerifier
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
from bactalk.repository import RunRepository
from bactalk.security import AuditLog, Principal, SecurityConfig, required_role
from bactalk.service import (
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


class ApprovalRequest(BaseModel):
    reviewer: str | None = Field(default=None, min_length=2, max_length=120)


class RejectionRequest(BaseModel):
    reviewer: str | None = Field(default=None, min_length=2, max_length=120)
    reason: str | None = Field(default=None, max_length=2_000)


class BoptestQualificationRequest(BaseModel):
    mapping: BoptestGraphMap
    oracles: list[BoptestTrajectoryOracle] = Field(min_length=1, max_length=1_000)
    steps: int = Field(ge=1, le=100_000)
    step_seconds: float = Field(gt=0, le=86_400, allow_inf_nan=False)
    start_time: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    warmup_period: float = Field(default=0.0, ge=0, allow_inf_nan=False)


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


def create_app(
    run_root: Path | None = None,
    *,
    ai_provider: StructuredChatProvider | None = None,
    ai_chat_provider: StructuredChatProvider | None = None,
    ai_coding_provider: StructuredChatProvider | None = None,
    security_config: SecurityConfig | None = None,
    boptest_client_factory: Callable[[], BoptestRuntime] | None = None,
) -> FastAPI:
    root = run_root or Path(os.getenv("BACTALK_RUNS", ".bactalk/runs"))
    repository = RunRepository(root)
    service = WorkbenchService(repository)
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
    make_boptest_client = boptest_client_factory or (
        lambda: BoptestClient(os.getenv("BACTALK_BOPTEST_URL", "http://127.0.0.1:8000"))
    )
    app = FastAPI(
        title="BACTalk",
        version="0.1.0",
        description="Human-gated controls programming workbench",
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
        }

    @app.get("/api/reference-stack")
    def get_reference_stack() -> dict:
        return reference_stack.inventory()

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
        points_file: Annotated[UploadFile, File()],
        selections: Annotated[str, Form(max_length=50_000)] = "{}",
    ) -> dict:
        try:
            parsed_selections = _form_json_object(selections, "ctrl-flow selections")
            points = parse_points_file(
                await points_file.read(),
                points_file.filename or "points.csv",
            )
            return ctrl_flow.reconcile_points(template_id, parsed_selections, points)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except CtrlFlowError as exc:
            status = 404 if "unknown ctrl-flow template" in str(exc) else 422
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        except (IntakeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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

    @app.post(
        "/api/library/plant-controls/controllers/{controller_id}/niagara-program-package"
    )
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

    @app.get("/api/runs")
    def list_runs() -> list[dict]:
        return [record.model_dump(mode="json") for record in repository.list()]

    @app.post("/api/runs", status_code=201)
    def create_run(job: JobSpec) -> dict:
        try:
            return service.create_run(job).model_dump(mode="json")
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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
                oracles=request.oracles,
                steps=request.steps,
                step_seconds=request.step_seconds,
                start_time=request.start_time,
                warmup_period=request.warmup_period,
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
        return service.create_run(demo_job()).model_dump(mode="json")

    @app.post("/api/runs/demo/generalist", status_code=201)
    def create_generalist_demo_run() -> dict:
        return service.create_run(generalist_demo_job()).model_dump(mode="json")

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
                "blocking_gates": (
                    deliverables.get("blocking_gates", []) if deliverables else []
                ),
            },
            "approval": (
                record.approval.model_dump(mode="json") if record.approval else None
            ),
            "downloads": {
                "available": approved,
                "target_url": f"/api/runs/{record.id}/export" if approved else None,
                "review_bundle_url": (
                    f"/api/runs/{record.id}/review-bundle" if approved else None
                ),
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
            source_record = repository.get(run_id)
            source_graph = ControlGraph.model_validate_json(
                Path(source_record.graph_path).read_text(encoding="utf-8")
            )
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
                )
                proposed_parameters = envelope.parameters()
                proposal = None
            else:
                envelope = chat_agent.respond(source_record.job, source_graph, request)
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
                        ProposedGraphPlanner(proposal, chat_agent)
                        if proposal is not None
                        else None
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

    static_next_dir = Path(__file__).parent / "static-next"
    if static_next_dir.is_dir():
        app.mount(
            "/next",
            SPAStaticFiles(directory=static_next_dir, html=True),
            name="next-workbench",
        )
    static_dir = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="workbench")
    return app


app = create_app()
