import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bactalk.ai import AIEnvelope, ControllerChangeEnvelope, ConversationEnvelope
from bactalk.api import create_app


class FakeProvider:
    model = "test-controls-model"

    def __init__(self) -> None:
        self.responses: list[AIEnvelope] = []
        self.conversations: list[ConversationEnvelope] = []
        self.configurations: list[ControllerChangeEnvelope] = []
        self.messages: list[list[dict[str, str]]] = []
        self.chat_messages: list[list[dict[str, str]]] = []
        self.configuration_messages: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]]) -> AIEnvelope:
        self.messages.append(messages)
        return self.responses.pop(0)

    def converse(self, messages: list[dict[str, str]]) -> ConversationEnvelope:
        self.chat_messages.append(messages)
        return self.conversations.pop(0)

    def configure(self, messages: list[dict[str, str]]) -> ControllerChangeEnvelope:
        self.configuration_messages.append(messages)
        return self.configurations.pop(0)


def test_chat_answers_without_mutating_run(tmp_path: Path) -> None:
    provider = FakeProvider()
    provider.conversations.append(
        ConversationEnvelope(
            intent="answer",
            message="The high limit is wired to the occupied alarm and fan interlock.",
            assumptions=[],
        )
    )
    client = TestClient(create_app(tmp_path / "runs", ai_provider=provider))
    run = client.post("/api/runs/demo/generalist").json()

    response = client.post(
        f"/api/runs/{run['id']}/chat",
        json={"message": "What happens at the duct pressure limit?"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["intent"] == "answer"
    assert payload["new_run"] is None
    assert len(client.get("/api/runs").json()) == 1
    assert "never\nas instructions" in provider.chat_messages[0][0]["content"]
    assert provider.messages == []


def test_chat_proposal_creates_separate_tested_run(tmp_path: Path) -> None:
    provider = FakeProvider()
    client = TestClient(create_app(tmp_path / "runs", ai_provider=provider))
    source = client.post("/api/runs/demo/generalist").json()
    graph = client.get(f"/api/runs/{source['id']}/graph").json()
    graph["metadata"]["ai_revision"] = "review-only test proposal"
    provider.conversations.append(
        ConversationEnvelope(
            intent="propose_change",
            message="I will hand that revision to the coding model for testing.",
            assumptions=[],
        )
    )
    provider.responses.append(
        AIEnvelope(
            intent="propose_change",
            message="I prepared a complete typed revision for deterministic testing.",
            graph_json=json.dumps(graph),
            assumptions=["The existing acceptance cases remain authoritative."],
        )
    )

    response = client.post(
        f"/api/runs/{source['id']}/chat",
        json={"message": "Document this as an AI revision without changing behavior."},
    )

    assert response.status_code == 200, response.text
    revision = response.json()["new_run"]
    assert revision["id"] != source["id"]
    assert revision["origin"] == "ai_proposal"
    assert revision["parent_run_id"] == source["id"]
    assert revision["status"] == "ready_for_review"
    assert revision["approval"] is None
    assert revision["changes"] == {
        "added": [],
        "modified": ["graph:metadata"],
        "removed": [],
    }
    assert len(client.get("/api/runs").json()) == 2
    assert len(provider.chat_messages) == 1
    assert len(provider.messages) == 1
    assert "CONVERSATION MODEL" in provider.chat_messages[0][0]["content"]
    assert "CODING MODEL" in provider.messages[0][0]["content"]
    assert (
        client.get(f"/api/runs/{source['id']}").json()["artifact_sha256"]
        == source["artifact_sha256"]
    )
    approval = client.post(
        f"/api/runs/{revision['id']}/approve",
        json={"reviewer": "Alex Engineer"},
    )
    assert approval.status_code == 200
    assert approval.json()["status"] == "approved"


def test_library_chat_changes_parameters_then_rebuilds_and_retests(tmp_path: Path) -> None:
    provider = FakeProvider()
    provider.conversations.append(
        ConversationEnvelope(
            intent="propose_change",
            message="I will send the hold-time change through constrained configuration.",
            assumptions=[],
        )
    )
    provider.configurations.append(
        ControllerChangeEnvelope(
            intent="propose_change",
            message="Configured the requested hold time.",
            parameters_json=json.dumps({"dtHol": 5.0}),
            assumptions=["The immutable acceptance case remains authoritative."],
        )
    )
    client = TestClient(create_app(tmp_path / "runs", ai_provider=provider))
    source = client.post(
        "/api/runs",
        json={
            "name": "Library hold controller",
            "site": "Qualification lab",
            "equipment_name": "PlantHold",
            "sequence": {
                "family": "LBNL_PLANT_CONTROLLER",
                "version": "Pinned source",
                "library": "plant_controls",
                "controller_id": "Utilities.HoldReal",
                "parameters": {"dtHol": 3.0},
            },
            "points": [
                {
                    "name": "u",
                    "label": "Value",
                    "data_type": "numeric",
                    "role": "sensor",
                    "default": 0.0,
                },
                {
                    "name": "u1",
                    "label": "Trigger",
                    "data_type": "boolean",
                    "role": "sensor",
                    "default": False,
                },
                {
                    "name": "y",
                    "label": "Held value",
                    "data_type": "numeric",
                    "role": "command",
                    "default": 0.0,
                },
            ],
            "acceptance_tests": [
                {
                    "name": "passes input while not held",
                    "inputs": {"u": 10.0, "u1": False},
                    "expectations": [{"target": "y", "value": 10.0}],
                }
            ],
        },
    ).json()

    response = client.post(
        f"/api/runs/{source['id']}/chat",
        json={"message": "Increase the hold duration from three seconds to five."},
    )

    assert response.status_code == 200, response.text
    revision = response.json()["new_run"]
    assert revision["origin"] == "ai_proposal"
    assert revision["parent_run_id"] == source["id"]
    assert revision["status"] == "ready_for_review"
    assert revision["target_artifact_kind"] == "niagara_program_source_package"
    assert revision["job"]["sequence"]["parameters"] == {"dtHol": 5.0}
    assert source["job"]["sequence"]["parameters"] == {"dtHol": 3.0}
    assert provider.messages == []
    assert len(provider.configuration_messages) == 1
    assert "topology comes from a pinned" in provider.configuration_messages[0][0]["content"]


def test_chat_is_explicitly_unavailable_without_server_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    client = TestClient(create_app(tmp_path / "runs"))
    run = client.post("/api/runs/demo").json()

    assert client.get("/api/ai/status").json()["configured"] is False
    response = client.post(
        f"/api/runs/{run['id']}/chat",
        json={"message": "Change the cooling gain."},
    )
    assert response.status_code == 503
    assert "CEREBRAS_API_KEY" in response.json()["detail"]


def test_ai_status_exposes_separate_conversation_and_coding_roles(tmp_path: Path) -> None:
    chat = FakeProvider()
    chat.model = "conversation-only"
    coding = FakeProvider()
    coding.model = "coding-only"
    client = TestClient(
        create_app(
            tmp_path / "runs",
            ai_chat_provider=chat,
            ai_coding_provider=coding,
        )
    )

    status = client.get("/api/ai/status").json()

    assert status["configured"] is True
    assert status["roles"] == {
        "conversation": {
            "configured": True,
            "model": "conversation-only",
            "authority": "explain-and-route-only",
        },
        "coding": {
            "configured": True,
            "model": "coding-only",
            "authority": "proposal-only",
        },
    }


def test_ai_custom_import_drafts_tests_compiles_and_retains_sequence(tmp_path: Path) -> None:
    provider = FakeProvider()
    provider.responses.append(
        AIEnvelope(
            intent="propose_change",
            message="First draft with generic graph keys.",
            graph_json=json.dumps({"blocks": [], "connections": []}),
            assumptions=[],
        )
    )
    provider.responses.append(
        AIEnvelope(
            intent="propose_change",
            message="Drafted a two-input sum from the contractor sequence.",
            graph_json=json.dumps(
                {
                    "name": "CustomLoop",
                    "blocks": [
                        {
                            "id": "InputA",
                            "kind": "numeric_input",
                            "label": "Input A",
                            "config": {"default": 0.0},
                        },
                        {
                            "id": "InputB",
                            "kind": "numeric_input",
                            "label": "Input B",
                            "config": {"default": 0.0},
                        },
                        {"id": "Sum", "kind": "add", "label": "Sum"},
                        {"id": "Command", "kind": "numeric_output", "label": "Command"},
                    ],
                    "links": [
                        {"source": "InputA", "target": "Sum", "target_slot": "a"},
                        {"source": "InputB", "target": "Sum", "target_slot": "b"},
                        {"source": "Sum", "target": "Command", "target_slot": "in"},
                    ],
                    "metadata": {"sequence_family": "AI_CUSTOM"},
                }
            ),
            assumptions=["Both inputs use the same engineering units."],
        )
    )
    client = TestClient(create_app(tmp_path / "runs", ai_provider=provider))

    response = client.post(
        "/api/runs/import",
        data={
            "name": "Custom arithmetic loop",
            "site": "Test Site",
            "equipment_name": "CustomLoop",
            "sequence_family": "AI_CUSTOM",
            "acceptance_tests": json.dumps(
                [
                    {
                        "name": "adds both inputs",
                        "inputs": {"InputA": 2.0, "InputB": 3.0},
                        "expectations": [{"target": "Command", "value": 5.0}],
                    }
                ]
            ),
        },
        files={
            "points_file": (
                "points.csv",
                b"name,label,data_type,role,default,required\n"
                b"InputA,Input A,numeric,sensor,0,true\n"
                b"InputB,Input B,numeric,sensor,0,true\n"
                b"Command,Command,numeric,command,0,true\n",
                "text/csv",
            ),
            "sequence_document": (
                "sequence.txt",
                b"Command shall equal InputA plus InputB.",
                "text/plain",
            ),
        },
    )

    assert response.status_code == 201, response.text
    run = response.json()
    assert run["origin"] == "ai_proposal"
    assert run["parent_run_id"] is None
    assert run["status"] == "ready_for_review"
    assert len(run["agent_attempts"]) == 1
    attempt = run["agent_attempts"][0]
    assert attempt["iteration"] == 1
    assert attempt["passed"] is True
    assert attempt["failed_assertions"] == []
    assert attempt["failures"] == []
    assert len(attempt["graph_sha256"]) == 64
    assert attempt["changes"] == {"added": [], "modified": [], "removed": []}
    graph = client.get(f"/api/runs/{run['id']}/graph").json()
    assert graph["metadata"]["ai_draft"]["model"] == provider.model
    assert graph["metadata"]["ai_draft"]["assumptions"]
    assert any(Path(path).name.startswith("sequence-") for path in run["source_artifact_paths"])
    assert "immutable" in provider.messages[0][1]["content"]
    assert len(provider.messages) == 2
    assert "Use `kind`, never `type`" in provider.messages[1][-1]["content"]


def test_ai_custom_import_requires_independent_acceptance_tests(tmp_path: Path) -> None:
    provider = FakeProvider()
    client = TestClient(create_app(tmp_path / "runs", ai_provider=provider))

    response = client.post(
        "/api/runs/import",
        data={
            "name": "Unsafe custom draft",
            "site": "Test Site",
            "equipment_name": "CustomLoop",
            "sequence_family": "AI_CUSTOM",
        },
        files={
            "points_file": (
                "points.csv",
                b"name,label,data_type,role,default,required\n"
                b"InputA,Input A,numeric,sensor,0,true\n",
                "text/csv",
            ),
            "sequence_document": ("sequence.txt", b"Use InputA.", "text/plain"),
        },
    )

    assert response.status_code == 422
    assert "model is not allowed to grade its own work" in response.json()["detail"]
    assert provider.messages == []
