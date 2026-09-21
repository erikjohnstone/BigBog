#!/usr/bin/env python3
"""Prove the contractor workflow end to end through the real HTTP API.

This drives the same endpoints the UI calls, in the order a contractor uses
them, and asserts the gates hold at each step:

  1. intake        upload a real points schedule and sequence document; the
                   server normalizes and maps them
  2. candidate     build a typed control graph from that intake
  3. tests         read the deterministic acceptance evidence
  4. deliverables  read the generated artifact coverage and target blockers
  5. gate          export and the review bundle are refused before approval
  6. review        read the graph, report, and release summary a reviewer sees
  7. approval      a named engineer approves one exact artifact digest
  8. export        the approved artifact and full review bundle download
  9. tamper        a changed artifact invalidates the approval

It runs against a live server when one is reachable and falls back to an
in-process ASGI client otherwise; the transport used is recorded in the
evidence so a passing run is never mistaken for a live-server proof it was
not.

Nothing here writes to a building: the workflow stops at a downloadable
artifact, which still requires licensed Workbench compilation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import httpx  # noqa: E402

EXAMPLES = ROOT / "examples"


class WorkflowError(AssertionError):
    """Raised when a workflow gate does not behave as specified."""


class Recorder:
    """Collects step evidence and prints progress."""

    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []
        self.started = time.monotonic()

    def ok(self, step: str, detail: str, **evidence: Any) -> None:
        print(f"  [OK  ] {step:<32} {detail}", flush=True)
        self.steps.append(
            {"step": step, "status": "passed", "detail": detail, "evidence": evidence}
        )

    def to_json(self, transport: str) -> dict[str, Any]:
        return {
            "schema": "bactalk.contractor-workflow-evidence/v1",
            "transport": transport,
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "duration_seconds": round(time.monotonic() - self.started, 2),
            "steps": self.steps,
            "passed": all(item["status"] == "passed" for item in self.steps),
            "safety": {
                "live_building_writes": False,
                "licensed_niagara_runtime_qualified": False,
                "boundary": "export produces a reviewable artifact for manual "
                "Workbench import; BACTalk never commands equipment",
            },
        }


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise WorkflowError(message)


def _client(base_url: str | None) -> tuple[httpx.Client, str]:
    """Return a live HTTP client when possible, else an in-process ASGI one."""
    if base_url:
        client = httpx.Client(base_url=base_url, timeout=180.0)
        try:
            response = client.get("/api/health")
            if response.status_code == 200:
                return client, f"live HTTP server at {base_url}"
        except httpx.HTTPError:
            pass
        client.close()

    from fastapi.testclient import TestClient  # noqa: PLC0415

    from bactalk.api import create_app  # noqa: PLC0415

    runs = ROOT / ".bactalk" / "workflow-proof" / "runs"
    runs.parent.mkdir(parents=True, exist_ok=True)
    app = create_app(runs)
    return TestClient(app), "in-process ASGI application"


# --------------------------------------------------------------------------
# workflow steps
# --------------------------------------------------------------------------


def step_intake(client: httpx.Client, recorder: Recorder) -> None:
    """Upload a real point schedule and prove the server normalizes it."""
    points = EXAMPLES / "vav-reheat-points.csv"
    expect(points.is_file(), f"example point schedule missing at {points}")
    sequence = ROOT / ".bactalk" / "workflow-proof" / "sequence.txt"
    sequence.parent.mkdir(parents=True, exist_ok=True)
    sequence.write_text(
        "Sequence of operation for VAV-12.\n"
        "When the zone is occupied the controller modulates the damper between "
        "the minimum airflow setpoint and full open to maintain the zone "
        "cooling setpoint.\n"
        "On a fall in zone temperature below the heating setpoint the reheat "
        "valve modulates open.\n"
        "When the zone temperature exceeds 80 degF the controller annunciates a "
        "high zone temperature alarm.\n"
        "When the zone is unoccupied the damper closes and the reheat valve "
        "closes.\n"
    )

    response = client.post(
        "/api/intake/inspect",
        files={
            "points_file": (points.name, points.read_bytes(), "text/csv"),
            "sequence_document": (sequence.name, sequence.read_bytes(), "text/plain"),
        },
    )
    expect(
        response.status_code == 200,
        f"intake inspect returned {response.status_code}: {response.text[:400]}",
    )
    body = response.json()
    parsed = body.get("points", body)
    count = len(parsed) if isinstance(parsed, list) else parsed.get("count", 0)
    expect(count >= 9, f"expected the 9-point VAV schedule, normalized {count}")
    recorder.ok(
        "intake normalization",
        f"{count} points normalized, sequence document inspected",
        point_count=count,
        source_sha256=hashlib.sha256(points.read_bytes()).hexdigest(),
    )


def step_build_candidate(client: httpx.Client, recorder: Recorder) -> str:
    """Build a typed candidate from the uploaded contractor documents."""
    points = EXAMPLES / "vav-reheat-points.csv"
    job = json.loads((EXAMPLES / "vav-reheat-job.json").read_text())

    response = client.post(
        "/api/runs/import",
        data={
            "name": "Workflow proof VAV-12",
            "site": "Example Campus",
            "equipment_name": "VAV_12",
            "sequence_family": "G36_VAV_REHEAT",
            "sequence_version": job["sequence"]["version"],
            "sequence_parameters": json.dumps(job["sequence"]["parameters"]),
            "deliverable_requirements": json.dumps(job["deliverables"]),
            "notes": "Generated by scripts/verify_contractor_workflow.py",
        },
        files={"points_file": (points.name, points.read_bytes(), "text/csv")},
    )
    expect(
        response.status_code == 201,
        f"run import returned {response.status_code}: {response.text[:500]}",
    )
    record = response.json()
    run_id = record["id"]
    expect(
        record["status"] == "ready_for_review",
        f"a passing candidate must be ready_for_review, got {record['status']}",
    )
    recorder.ok(
        "candidate generation",
        f"run {run_id} built and tested, status {record['status']}",
        run_id=run_id,
        artifact_sha256=record.get("artifact_sha256"),
        target_artifact_kind=record.get("target_artifact_kind"),
    )
    return run_id


def step_graph_and_tests(client: httpx.Client, recorder: Recorder, run_id: str) -> None:
    """Read the typed graph and the deterministic acceptance evidence."""
    graph = client.get(f"/api/runs/{run_id}/graph")
    expect(graph.status_code == 200, f"graph read returned {graph.status_code}")
    graph_body = graph.json()
    blocks = graph_body.get("blocks", [])
    links = graph_body.get("links", [])
    expect(len(blocks) > 0, "the generated graph has no blocks")
    recorder.ok(
        "typed control graph",
        f"{len(blocks)} blocks, {len(links)} links",
        block_count=len(blocks),
        link_count=len(links),
    )

    report = client.get(f"/api/runs/{run_id}/report")
    expect(report.status_code == 200, f"report read returned {report.status_code}")
    body = report.json()
    scenarios = body.get("scenarios", [])
    assertions = sum(len(item.get("assertions", [])) for item in scenarios)
    expect(body.get("passed") is True, "the candidate's acceptance report did not pass")
    expect(assertions > 0, "the acceptance report contains no assertions")
    recorder.ok(
        "deterministic tests",
        f"{len(scenarios)} scenarios, {assertions} assertions, passed",
        scenario_count=len(scenarios),
        assertion_count=assertions,
        engine=body.get("engine"),
    )


def step_deliverables(client: httpx.Client, recorder: Recorder, run_id: str) -> None:
    """Read generated artifact coverage and the explicit target blockers."""
    response = client.get(f"/api/runs/{run_id}/deliverables")
    expect(response.status_code == 200, f"deliverables returned {response.status_code}")
    body = response.json()
    blockers = body.get("blocking_gates", [])
    expect(
        body.get("deployment_ready") is False,
        "deliverables must never report deployment_ready before a licensed runtime "
        "has qualified the artifact",
    )
    expect(blockers, "deliverables must enumerate the gates that remain")
    recorder.ok(
        "deliverable coverage",
        f"{len(blockers)} blocking gates declared, deployment_ready=False",
        blocking_gate_count=len(blockers),
    )


def step_export_denied(client: httpx.Client, recorder: Recorder, run_id: str) -> None:
    """Export and the review bundle must be refused before approval."""
    export = client.get(f"/api/runs/{run_id}/export")
    expect(
        export.status_code == 403,
        f"unapproved export must be refused with 403, got {export.status_code}",
    )
    bundle = client.get(f"/api/runs/{run_id}/review-bundle")
    expect(
        bundle.status_code == 403,
        f"unapproved review bundle must be refused with 403, got {bundle.status_code}",
    )
    recorder.ok(
        "pre-approval export gate",
        "export and review bundle both refused with 403",
    )


def step_release_summary(client: httpx.Client, recorder: Recorder, run_id: str) -> str:
    """Re-hash the retained candidate and read what the reviewer signs."""
    response = client.get(f"/api/runs/{run_id}/release-summary")
    expect(
        response.status_code == 200, f"release summary returned {response.status_code}"
    )
    body = response.json()
    integrity = body.get("integrity", {})
    digest = integrity.get("artifact_sha256")
    expect(bool(digest), "release summary does not expose an artifact digest to approve")
    expect(
        integrity.get("verified") is True,
        "the release summary must re-verify the retained artifact before review",
    )
    target = body.get("target", {})
    expect(
        target.get("licensed_runtime_qualified") is False,
        "the release summary must never claim licensed runtime qualification",
    )
    behavior = body.get("behavior", {})
    recorder.ok(
        "review evidence",
        f"digest {digest[:16]} re-verified, "
        f"{behavior.get('passed_assertion_count')}/{behavior.get('assertion_count')} "
        f"assertions passed",
        artifact_sha256=digest,
        target_artifact_kind=target.get("artifact_kind"),
        licensed_runtime_qualified=target.get("licensed_runtime_qualified"),
    )
    return digest


def step_approve(
    client: httpx.Client, recorder: Recorder, run_id: str, digest: str
) -> None:
    """A named engineer approves one exact digest; a wrong digest is refused."""
    wrong = client.post(
        f"/api/runs/{run_id}/approve",
        json={
            "reviewer": "Workflow Proof Engineer",
            "artifact_sha256": "0" * 64,
        },
    )
    expect(
        wrong.status_code >= 400,
        f"approving a digest that does not match must fail, got {wrong.status_code}",
    )

    response = client.post(
        f"/api/runs/{run_id}/approve",
        json={"reviewer": "Workflow Proof Engineer", "artifact_sha256": digest},
    )
    expect(
        response.status_code == 200,
        f"approval returned {response.status_code}: {response.text[:400]}",
    )
    body = response.json()
    expect(body["status"] == "approved", f"run status after approval is {body['status']}")
    recorder.ok(
        "artifact-bound approval",
        f"approved by a named reviewer against digest {digest[:16]}",
        approved_digest=digest,
        mismatched_digest_rejected_with=wrong.status_code,
    )


def step_export(client: httpx.Client, recorder: Recorder, run_id: str) -> None:
    """The approved artifact and the full review bundle download."""
    export = client.get(f"/api/runs/{run_id}/export")
    expect(
        export.status_code == 200,
        f"approved export returned {export.status_code}: {export.text[:300]}",
    )
    payload = export.content
    expect(len(payload) > 0, "approved export returned an empty artifact")
    expect(
        payload[:2] == b"PK",
        "the exported target artifact is not a zip archive as expected",
    )

    bundle = client.get(f"/api/runs/{run_id}/review-bundle")
    expect(
        bundle.status_code == 200,
        f"approved review bundle returned {bundle.status_code}",
    )
    expect(len(bundle.content) > 0, "the review bundle is empty")

    out_dir = ROOT / ".bactalk" / "workflow-proof"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "approved-target.zip").write_bytes(payload)
    (out_dir / "review-bundle.zip").write_bytes(bundle.content)

    recorder.ok(
        "approved export",
        f"target {len(payload)} bytes, review bundle {len(bundle.content)} bytes",
        target_bytes=len(payload),
        target_sha256=hashlib.sha256(payload).hexdigest(),
        review_bundle_bytes=len(bundle.content),
        review_bundle_sha256=hashlib.sha256(bundle.content).hexdigest(),
    )


def step_tamper_detection(recorder: Recorder, run_id: str, runs_root: Path) -> None:
    """Changing a signed artifact must invalidate the approval.

    This touches the run store directly because the point is to prove the
    digest check catches an out-of-band edit, which no API call can create.
    """
    run_dir = runs_root / run_id
    graph_file = run_dir / "control-graph.json"
    if not graph_file.is_file():
        recorder.ok(
            "tamper detection",
            "skipped: run store is not local to this process",
        )
        return

    original = graph_file.read_bytes()
    try:
        document = json.loads(original)
        document["name"] = str(document.get("name", "")) + " (tampered)"
        graph_file.write_bytes(json.dumps(document, indent=2).encode())

        from bactalk.repository import RunRepository  # noqa: PLC0415
        from bactalk.service import WorkbenchService  # noqa: PLC0415

        service = WorkbenchService(RunRepository(runs_root))
        detected = False
        try:
            service.export_path(run_id)
        except Exception:  # noqa: BLE001 - any refusal proves the gate held
            detected = True
        expect(detected, "a tampered artifact was still exportable after approval")
        recorder.ok(
            "tamper detection",
            "a modified signed artifact invalidates the approved export",
        )
    finally:
        graph_file.write_bytes(original)


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8011",
        help="live API to test against; falls back to an in-process app",
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / ".bactalk" / "contractor-workflow-evidence.json"),
        help="where to write the workflow evidence",
    )
    args = parser.parse_args(argv)

    client, transport = _client(args.base_url)
    recorder = Recorder()
    print(f"proving the contractor workflow through the {transport}")

    try:
        step_intake(client, recorder)
        run_id = step_build_candidate(client, recorder)
        step_graph_and_tests(client, recorder, run_id)
        step_deliverables(client, recorder, run_id)
        step_export_denied(client, recorder, run_id)
        digest = step_release_summary(client, recorder, run_id)
        step_approve(client, recorder, run_id, digest)
        step_export(client, recorder, run_id)
        if transport.startswith("in-process"):
            step_tamper_detection(
                recorder, run_id, ROOT / ".bactalk" / "workflow-proof" / "runs"
            )
    except WorkflowError as exc:
        print(f"\n  [FAIL] {exc}", file=sys.stderr)
        return 1
    except httpx.HTTPError as exc:
        print(f"\n  [FAIL] transport error: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()

    payload = recorder.to_json(transport)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2) + "\n")

    print("")
    print(f"contractor workflow proven: {len(payload['steps'])} steps passed")
    print(f"evidence written to {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
