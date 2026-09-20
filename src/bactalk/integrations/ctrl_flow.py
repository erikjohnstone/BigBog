from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any

from bactalk.domain import PointSpec
from bactalk.intake import SequenceDocument
from bactalk.integrations.ctrl_flow_planning import CtrlFlowProgrammingPlanner
from bactalk.integrations.ctrl_flow_reconciliation import CtrlFlowPointReconciler
from bactalk.integrations.ctrl_flow_sequence import CtrlFlowSequenceReconciler
from bactalk.sequence_requirements import (
    SequenceRequirementReviewRequest,
    compile_sequence_requirement_review,
)


class CtrlFlowError(RuntimeError):
    """Raised when the pinned ctrl-flow configuration boundary rejects input."""


class CtrlFlowLibrary:
    """Product adapter for LBNL ctrl-flow's real Linkage Schema interpreter."""

    def __init__(self, root: Path | None = None, *, timeout_seconds: float = 45.0):
        self.root = (root or Path(__file__).resolve().parents[3]).resolve()
        self.source = self.root / ".vendor/ctrl-flow-dev"
        self.bridge = self.root / "ops/ctrl-flow/bridge.cjs"
        self.timeout_seconds = timeout_seconds

    @property
    def snapshot(self) -> Path:
        return self.source / "client/src/data/templates.json"

    def _require_runtime(self) -> None:
        required = (
            self.source / "LICENSE.txt",
            self.snapshot,
            self.source / "client/node_modules/ts-node",
            self.bridge,
        )
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise FileNotFoundError(
                "ctrl-flow runtime is incomplete; run scripts/install_ctrl_flow.sh; "
                f"missing: {', '.join(missing)}"
            )

    def _invoke(self, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        self._require_runtime()
        try:
            completed = subprocess.run(
                ["node", str(self.bridge), action],
                cwd=self.root,
                input=json.dumps(payload or {}, separators=(",", ":")),
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CtrlFlowError(
                f"ctrl-flow {action} exceeded the {self.timeout_seconds:g}s isolated boundary"
            ) from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "unknown failure"
            raise CtrlFlowError(f"ctrl-flow {action} failed: {detail[-2_000:]}")
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise CtrlFlowError("ctrl-flow returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise CtrlFlowError("ctrl-flow returned a non-object response")
        return result

    def catalog(self) -> dict[str, Any]:
        result = self._invoke("catalog")
        templates = result.get("templates", [])
        return {
            "schema": "bactalk.ctrl-flow-catalog/v1",
            "source": "LBNL ctrl-flow Linkage Schema",
            "scope": (
                "Modelica Buildings system templates, conditional engineering choices, and "
                "evaluated configuration evidence"
            ),
            "license": "BSD-3-Clause-style LBNL license with notices",
            "revision": "9063e347b13b1a55f9b324ab35da01b5006492de",
            "snapshot_sha256": hashlib.sha256(self.snapshot.read_bytes()).hexdigest(),
            "template_count": len(templates),
            "option_count": result.get("option_count", 0),
            "schedule_option_count": result.get("schedule_option_count", 0),
            "templates": [
                {
                    **template,
                    "family": " / ".join(
                        segment.split(".")[-1] for segment in template.get("system_types", [])
                    ),
                    "product_status": "upstream-interpreter-wired",
                    "relative_path": "client/src/data/templates.json",
                }
                for template in templates
            ],
            "system_types": result.get("system_types", []),
            "project": result.get("project", {}),
            "authority": (
                "offline design configuration only; no live writes and no claim of Niagara "
                "runtime equivalence"
            ),
        }

    def schema(self, template_id: str) -> dict[str, Any]:
        result = self._invoke("schema", {"template_id": template_id})
        return self._decorate_configuration(result, requested_selection_count=0)

    def configure(self, template_id: str, selections: dict[str, Any]) -> dict[str, Any]:
        if len(selections) > 500:
            raise ValueError("at most 500 ctrl-flow selections are accepted")
        for key, value in selections.items():
            if len(key) > 1_000:
                raise ValueError("ctrl-flow selection paths are limited to 1,000 characters")
            if isinstance(value, str) and len(value) > 2_000:
                raise ValueError("ctrl-flow selection values are limited to 2,000 characters")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("ctrl-flow numeric selections must be finite")
        result = self._invoke(
            "configure",
            {"template_id": template_id, "selections": selections},
        )
        return self._decorate_configuration(
            result,
            requested_selection_count=len(selections),
        )

    def programming_brief(
        self,
        template_id: str,
        selections: dict[str, Any],
    ) -> dict[str, Any]:
        """Bind an evaluated HVAC design to points, scenarios, packs, and release gates."""

        configuration = self.configure(template_id, selections)
        return CtrlFlowProgrammingPlanner().build(configuration)

    def reconcile_points(
        self,
        template_id: str,
        selections: dict[str, Any],
        points: list[PointSpec],
    ) -> dict[str, Any]:
        """Compare contractor points against the exact selected-system brief."""

        brief = self.programming_brief(template_id, selections)
        return CtrlFlowPointReconciler().reconcile(brief, points)

    def reconcile_sequence(
        self,
        template_id: str,
        selections: dict[str, Any],
        document: SequenceDocument,
    ) -> dict[str, Any]:
        """Triage contractor sequence language against every selected-system scenario."""

        brief = self.programming_brief(template_id, selections)
        return CtrlFlowSequenceReconciler().reconcile(brief, document)

    def review_sequence_requirements(
        self,
        template_id: str,
        selections: dict[str, Any],
        document: SequenceDocument,
        request: SequenceRequirementReviewRequest,
        *,
        reviewer: str,
        actor_id: str | None,
        tenant_id: str | None,
        authentication: str,
        point_reconciliation: dict[str, Any],
    ) -> dict[str, Any]:
        """Re-derive and review every sequence candidate against immutable source evidence."""

        brief = self.programming_brief(template_id, selections)
        reconciliation = CtrlFlowSequenceReconciler().reconcile(brief, document)
        return compile_sequence_requirement_review(
            brief,
            reconciliation,
            request,
            reviewer=reviewer,
            actor_id=actor_id,
            tenant_id=tenant_id,
            authentication=authentication,
            point_reconciliation=point_reconciliation,
        )

    def _decorate_configuration(
        self,
        result: dict[str, Any],
        *,
        requested_selection_count: int,
    ) -> dict[str, Any]:
        template = result.get("template", {})
        selections = result.get("selections", {})
        rejected = result.get("rejected_selections", [])
        fields = result.get("fields", [])
        digest_payload = {
            "template_id": template.get("modelicaPath"),
            "selections": selections,
            "revision": "9063e347b13b1a55f9b324ab35da01b5006492de",
        }
        digest = hashlib.sha256(
            json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return {
            "schema": "bactalk.ctrl-flow-configuration/v1",
            "configuration_digest": digest,
            "template": template,
            "requested_selection_count": requested_selection_count,
            "accepted_selection_count": len(selections),
            "rejected_selection_count": len(rejected),
            "selections": selections,
            "rejected_selections": rejected,
            "visible_field_count": len(fields),
            "fields": fields,
            "display_tree": result.get("display_tree", []),
            "evaluated_value_count": len(result.get("evaluated_values", {})),
            "evaluated_values": result.get("evaluated_values", {}),
            "source_evidence": {
                "repository": "https://github.com/lbl-srg/ctrl-flow-dev",
                "revision": "9063e347b13b1a55f9b324ab35da01b5006492de",
                "snapshot_sha256": hashlib.sha256(self.snapshot.read_bytes()).hexdigest(),
                "interpreter": "client/src/interpreter/interpreter.ts",
                "display_mapper": "client/src/interpreter/display-option.ts",
            },
            "downstream_boundary": {
                "engineering_brief_ready": not rejected,
                "niagara_code_generated": False,
                "reason": (
                    "ctrl-flow configures the HVAC design. BACTalk must explicitly map the "
                    "approved selections to its verified G36, plant, and Niagara target lanes."
                ),
            },
            "safety": {
                "offline_only": True,
                "live_writes_enabled": False,
                "human_approval_required": True,
            },
        }
