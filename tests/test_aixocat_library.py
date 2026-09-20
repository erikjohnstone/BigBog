from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from bactalk.api import create_app
from bactalk.compiler import NiagaraCompiler
from bactalk.domain import ControlGraph
from bactalk.integrations.aixocat import AixocatLibrary


def test_aixocat_catalog_parses_only_sparse_allowlisted_sources() -> None:
    catalog = AixocatLibrary().catalog()

    assert catalog["license"] == "MIT"
    assert catalog["pattern_count"] == 211
    assert catalog["translatable_count"] == 6
    assert catalog["group_counts"]["oscat.control"] == 38
    assert catalog["group_counts"]["hydronic.components"] == 33
    assert catalog["group_counts"]["heat_pump.systemcheck"] == 10
    assert all("_Libraries" not in row["relative_path"] for row in catalog["patterns"])


def test_aixocat_inspection_exposes_typed_interface_and_source(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))

    response = client.get("/api/library/aixocat/patterns/oscat.automation.INTERLOCK")

    assert response.status_code == 200, response.text
    result = response.json()
    assert [(row["name"], row["type"]) for row in result["inputs"]] == [
        ("I1", "BOOL"),
        ("I2", "BOOL"),
        ("TL", "TIME"),
    ]
    assert [(row["name"], row["type"]) for row in result["outputs"]] == [
        ("Q1", "BOOL"),
        ("Q2", "BOOL"),
    ]
    assert "Q1 := I1 AND NOT t2.Q" in result["implementation"]
    assert result["pattern"]["source_sha256"]


def test_aixocat_scale_and_heating_curve_are_verified_and_niagara_compilable(
    tmp_path: Path,
) -> None:
    library = AixocatLibrary()
    compiler = NiagaraCompiler()

    for pattern_id in (
        "oscat.signal_processing.SCALE",
        "hydronic.components.FC_HeatingCurve",
    ):
        result = library.translate(pattern_id)
        graph = ControlGraph.model_validate(result["graph"])
        artifact = compiler.compile(graph, tmp_path / f"{graph.name}.bog")
        assert artifact.is_file()
        assert result["verification"]["passed"] is True
        assert result["niagara_compilable"] is True
        assert result["runtime_qualified"] is False


def test_aixocat_interlock_specializes_time_and_proves_mutual_exclusion(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(tmp_path / "runs"))

    response = client.post(
        "/api/library/aixocat/patterns/oscat.automation.INTERLOCK/translate",
        json={"parameters": {"TL_seconds": 2.0}},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["specialization"]["TL_seconds"] == 2.0
    assert result["verification"]["passed"] is True
    assert all(
        not (row["Q1"] and row["Q2"])
        for row in result["verification"]["timeline"]
    )
    assert result["verification"]["timeline"][-1]["Q2"] is True


def test_aixocat_unmapped_pattern_fails_closed(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "runs"))

    response = client.post(
        "/api/library/aixocat/patterns/oscat.control.CTRL_PID/translate",
        json={"parameters": {}},
    )

    assert response.status_code == 422
    assert "no exact BACTalk lowering" in response.json()["detail"]


def test_aixocat_common_control_primitives_are_behavior_verified() -> None:
    library = AixocatLibrary()

    for pattern_id in (
        "oscat.automation.MANUAL",
        "oscat.control.DEAD_BAND",
        "oscat.control.DEAD_ZONE",
    ):
        result = library.translate(pattern_id)
        assert result["verification"]["passed"] is True
        assert all(row["passed"] for row in result["verification"]["vectors"])
