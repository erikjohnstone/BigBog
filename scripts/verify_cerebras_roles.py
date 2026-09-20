from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from fastapi.testclient import TestClient

from bactalk.ai import CerebrasProvider
from bactalk.api import create_app


def main() -> None:
    load_dotenv(".env")
    key = os.getenv("CEREBRAS_API_KEY")
    if not key:
        raise SystemExit("CEREBRAS_API_KEY is not configured")
    chat = CerebrasProvider(
        key,
        model=os.getenv("CEREBRAS_CHAT_MODEL", "gpt-oss-120b"),
    )
    coding = CerebrasProvider(
        key,
        model=os.getenv("CEREBRAS_CODING_MODEL", "qwen-3.8-27b"),
    )
    chat.assert_available()
    coding.assert_available()

    with tempfile.TemporaryDirectory(prefix="bactalk-cerebras-smoke-") as temporary:
        client = TestClient(
            create_app(
                Path(temporary) / "runs",
                ai_chat_provider=chat,
                ai_coding_provider=coding,
            )
        )
        response = client.post(
            "/api/runs/import",
            data={
                "name": "Cerebras role smoke",
                "site": "Isolated Test Lab",
                "equipment_name": "BinaryProof",
                "sequence_family": "AI_CUSTOM",
                "acceptance_tests": json.dumps(
                    [
                        {
                            "name": "disabled",
                            "inputs": {"Enable": False},
                            "expectations": [{"target": "Command", "value": False}],
                        },
                        {
                            "name": "enabled",
                            "inputs": {"Enable": True},
                            "expectations": [{"target": "Command", "value": True}],
                        },
                    ]
                ),
            },
            files={
                "points_file": (
                    "points.csv",
                    b"name,label,data_type,role,default,required\n"
                    b"Enable,Enable,boolean,sensor,false,true\n"
                    b"Command,Command,boolean,command,false,true\n",
                    "text/csv",
                ),
                "sequence_document": (
                    "sequence.txt",
                    b"Command shall equal Enable with no delay or inversion.",
                    "text/plain",
                ),
            },
        )
        if response.status_code != 201:
            raise RuntimeError(f"coding-role smoke failed: {response.text[:1000]}")
        run = response.json()
        question = client.post(
            f"/api/runs/{run['id']}/chat",
            json={"message": "Explain what the generated command does. Do not change it."},
        )
        if question.status_code != 200:
            raise RuntimeError(f"conversation-role smoke failed: {question.text[:1000]}")
        chat_result = question.json()
        if chat_result["intent"] != "answer" or chat_result["new_run"] is not None:
            raise RuntimeError("conversation model mutated or rerouted an explanation request")
        graph = client.get(f"/api/runs/{run['id']}/graph").json()
        print(
            json.dumps(
                {
                    "schema": "bactalk.cerebras-role-smoke/v1",
                    "passed": True,
                    "conversation_model": chat.model,
                    "coding_model": coding.model,
                    "coding_run_status": run["status"],
                    "coding_attempts": run["agent_attempts"],
                    "graph_blocks": len(graph["blocks"]),
                    "graph_links": len(graph["links"]),
                    "conversation_intent": chat_result["intent"],
                    "live_building_authority": False,
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
