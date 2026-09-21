from pathlib import Path

from fastapi.testclient import TestClient

from bactalk.api import create_app
from bactalk.block_catalog import FAMILIES, catalog, family_of
from bactalk.domain import BLOCK_SLOTS, BlockKind


def test_every_block_kind_has_a_family_and_declared_slots() -> None:
    entries = {item["kind"]: item for item in catalog()["kinds"]}
    assert set(entries) == {kind.value for kind in BlockKind}
    for kind in BlockKind:
        entry = entries[kind.value]
        assert entry["family"] in FAMILIES
        assert entry["family"] == family_of(kind)
        assert [slot["name"] for slot in entry["inputs"]] == list(BLOCK_SLOTS[kind].inputs)
        assert [slot["name"] for slot in entry["outputs"]] == list(BLOCK_SLOTS[kind].outputs)
        for slot in entry["inputs"] + entry["outputs"]:
            assert slot["type"] in {"numeric", "boolean"}


def test_stateful_and_feedback_flags_are_consistent() -> None:
    entries = {item["kind"]: item for item in catalog()["kinds"]}
    assert entries["numeric_unit_delay"]["feedback"] is True
    assert entries["boolean_pre_host_tick"]["feedback"] is True
    assert entries["add"]["stateful"] is False
    assert entries["timer"]["stateful"] is True
    for entry in entries.values():
        if entry["feedback"]:
            assert entry["stateful"]


def test_block_catalog_endpoint(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))
    response = client.get("/api/block-catalog")
    assert response.status_code == 200
    body = response.json()
    assert body["schema"] == "bactalk.block-catalog/v1"
    assert len(body["kinds"]) == len(BlockKind)
