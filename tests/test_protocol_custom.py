"""N11: custom, job-specific sequences. The AI drafts the requirement set from a
specification section and, once the contractor approved that exact digest, the program;
both are validated by BACTalk's own models; the protocol's adequacy runs on the result;
the run is labelled and gated. A fake provider stands in for the models."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bactalk.ai import AIEnvelope, AIProviderError, CustomRequirementsEnvelope
from bactalk.api import create_app
from bactalk.library_tier5_fixture.kitchen_hood import author as hood_author
from bactalk.library_tier5_fixture.kitchen_hood.graph import build_graph as build_hood
from bactalk.protocol.catalog import points_for
from bactalk.protocol.custom import (
    CUSTOM_LABEL,
    CustomSequenceRepository,
    custom_job,
    draft_program,
    draft_requirements,
)
from bactalk.protocol.requirements import RequirementSet

SPEC = """3.4 KITCHEN HOOD EXHAUST INTERLOCK
A. The hood exhaust fan shall start when the kitchen hood switch is on and stop when it is off.
B. The makeup air fan shall run whenever the hood exhaust fan is running and the building air
   handling unit supply fan is in operation; the makeup air damper shall open with the makeup fan.
C. If the makeup air fan is commanded on and its proof is not made within 45 seconds, a makeup air
   failure alarm shall be generated; the alarm shall clear when proof is made or the command is
   removed."""


class FakeProvider:
    """Returns the fixture requirement set and graph, with the sequence id the caller pinned."""

    model = "fake-model"

    def __init__(self, *, graph_traceability: bool = True):
        self.graph_traceability = graph_traceability
        self.calls: list[str] = []

    def draft_requirements(self, messages):  # noqa: ANN001
        self.calls.append("requirements")
        assert messages[0]["role"] == "system" and "REQUIREMENTS DRAFTER" in messages[0]["content"]
        user = json.loads(messages[1]["content"])
        document = json.loads(json.dumps(hood_author.build()))
        document["sequence_id"] = user["sequence_id"]
        return CustomRequirementsEnvelope(
            requirements_json=json.dumps(document),
            assumptions=["proof input is a current switch"],
            questions=["Should the hood fan also stop on a fire alarm input?"],
        )

    def complete(self, messages):  # noqa: ANN001
        self.calls.append("program")
        assert "LOGIC AUTHOR" in messages[0]["content"]
        payload = json.loads(messages[1]["content"])
        requirements = RequirementSet.model_validate(payload["requirements"])
        graph = build_hood(requirements, points_for(requirements), {})
        if not self.graph_traceability:
            graph = graph.model_copy(update={"metadata": {}})
        return AIEnvelope(
            intent="propose_change",
            message="drafted",
            graph_json=graph.model_dump_json(),
            assumptions=["timer semantics per docs/niagara-semantics.md"],
        )

    def converse(self, messages):  # noqa: ANN001
        raise NotImplementedError

    def configure(self, messages):  # noqa: ANN001
        raise NotImplementedError


def test_drafts_are_validated_and_pinned() -> None:
    provider = FakeProvider()
    requirements, assumptions, questions = draft_requirements(
        SPEC, title="Hood", sequence_id="custom-0123456789ab", provider=provider
    )
    assert requirements.sequence_id == "custom-0123456789ab" and requirements.tier == 5
    assert questions and assumptions
    graph, program_assumptions = draft_program(requirements, provider=provider)
    assert graph.metadata["requirements_digest"] == requirements.digest()
    assert program_assumptions
    with pytest.raises(AIProviderError, match="traceability"):
        draft_program(requirements, provider=FakeProvider(graph_traceability=False))


def test_repository_round_trip_and_job_label(tmp_path: Path) -> None:
    repo = CustomSequenceRepository(tmp_path / "custom")
    provider = FakeProvider()
    record = repo.create(
        title="Hood interlock",
        equipment_name="HOOD_1",
        spec_text=SPEC,
        spec_filename="23-09-93.txt",
        provider=provider,
    )
    assert record.id.startswith("custom-") and record.graph is None
    record = repo.set_program(record.id, provider=provider)
    assert repo.get(record.id).graph is not None
    job = custom_job(record)
    protocol = job.sequence.parameters["protocol"]
    assert protocol["label"] == CUSTOM_LABEL and protocol["tier"] == 5
    assert protocol["sequence_id"] == record.id
    assert job.sequence.family == "CUSTOM_JOB_SPECIFIC" and job.acceptance_tests


def test_api_flow_draft_approve_program_adequacy_run(tmp_path: Path) -> None:
    provider = FakeProvider()
    client = TestClient(create_app(tmp_path / "runs", ai_provider=provider))
    created = client.post(
        "/api/protocol/custom",
        json={"title": "Hood interlock", "equipment_name": "HOOD_1", "spec_text": SPEC},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    sequence_id = body["sequence_id"]
    assert (
        body["label"] == CUSTOM_LABEL and body["tier"] == 5 and body["gate_g_eng"] == "unapproved"
    )
    assert body["custom"]["questions"] and body["custom"]["has_program"] is False
    assert sequence_id in {
        i["sequence_id"] for i in client.get("/api/protocol/sequences").json()["items"]
    }
    # the program is drafted from approved requirements only
    refused = client.post(f"/api/protocol/custom/{sequence_id}/program")
    assert refused.status_code == 409 and "Gate G-ENG" in refused.json()["detail"]
    approved = client.post(
        f"/api/protocol/sequences/{sequence_id}/approve",
        json={"reviewer": "Contractor", "requirements_digest": body["requirements_digest"]},
    )
    assert approved.status_code == 201
    drafted = client.post(f"/api/protocol/custom/{sequence_id}/program")
    assert drafted.status_code == 201 and drafted.json()["custom"]["has_program"] is True
    assert provider.calls == ["requirements", "program"]
    adequacy = client.post(
        f"/api/protocol/custom/{sequence_id}/adequacy",
        json={"mutants": 0, "invariant_sequences": 50},
    )
    assert adequacy.status_code == 200, adequacy.text
    report = adequacy.json()
    assert report["suite"]["passed"] is True and report["decisions"]["fully_covered"] is True
    assert report["differential"]["scan"]["passed"] is True and report["mutation"] is None
    assert client.get(f"/api/protocol/sequences/{sequence_id}").json()["adequacy"]["suite"][
        "passed"
    ]
    run = client.post(f"/api/protocol/custom/{sequence_id}/runs")
    assert run.status_code == 201, run.text
    record = run.json()
    assert record["job"]["sequence"]["parameters"]["protocol"]["label"] == CUSTOM_LABEL
    accepted = client.post(
        f"/api/runs/{record['id']}/approve",
        json={"reviewer": "Reviewer", "artifact_sha256": record["artifact_sha256"]},
    )
    assert accepted.status_code == 200, accepted.text


def test_api_without_a_provider_says_so(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))
    response = client.post(
        "/api/protocol/custom",
        json={"title": "Hood interlock", "equipment_name": "HOOD_1", "spec_text": SPEC},
    )
    assert response.status_code in {502, 503}, response.text
    assert response.json()["detail"]
