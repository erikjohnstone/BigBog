"""Units reach the exported .bog (GOAL-NATIVE-BOG.md, N0).

pybog writes ``units=u:null`` on every writable point. The compiler now rewrites
the facets of every numeric point whose job point declares a unit, using the
Niagara unit encodings harvested from real stations. This test fails if a point
with declared units ever ships without a unit facet again.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

from bactalk.compiler import NiagaraCompiler
from bactalk.demo import standard_vav_demo_job
from bactalk.domain import (
    AcceptanceCase,
    Block,
    BlockKind,
    ControlGraph,
    DataType,
    JobSpec,
    Link,
    OutputExpectation,
    PointRole,
    PointSpec,
    SequenceSpec,
)
from bactalk.niagara.units import NIAGARA_UNITS, resolve_unit, units_facet
from bactalk.repository import RunRepository
from bactalk.service import WorkbenchService

pytestmark = [pytest.mark.minimal, pytest.mark.native_bog]


def _points_facets(archive: Path, folder_name: str) -> dict[str, str]:
    with zipfile.ZipFile(archive) as source:
        root = ElementTree.fromstring(source.read("file.xml"))
    folder = next(
        element
        for element in root.iter("p")
        if element.get("n") == folder_name and element.get("t") == "b:Folder"
    )
    facets: dict[str, str] = {}
    for point in folder:
        if point.get("t") not in {"control:NumericWritable", "control:BooleanWritable"}:
            continue
        facet = next((child for child in point if child.get("n") == "facets"), None)
        facets[point.get("n") or ""] = facet.get("v") or "" if facet is not None else ""
    return facets


def _job() -> JobSpec:
    graph = ControlGraph(
        name="UNITS_1",
        blocks=[
            Block(
                id="SupplyTemp",
                kind=BlockKind.NUMERIC_INPUT,
                label="Supply temp",
                config={"default": 55.0},
            ),
            Block(
                id="Airflow", kind=BlockKind.NUMERIC_INPUT, label="Airflow", config={"default": 0.0}
            ),
            Block(
                id="Mystery", kind=BlockKind.NUMERIC_INPUT, label="No unit", config={"default": 0.0}
            ),
            Block(id="DamperCmd", kind=BlockKind.NUMERIC_OUTPUT, label="Damper"),
            Block(id="FanCmd", kind=BlockKind.BOOLEAN_OUTPUT, label="Fan"),
            Block(id="Gain", kind=BlockKind.NUMERIC_CONST, label="Gain", config={"value": 1.0}),
            Block(id="Scaled", kind=BlockKind.MULTIPLY, label="Scaled"),
            Block(id="On", kind=BlockKind.BOOLEAN_CONST, label="On", config={"value": True}),
        ],
        links=[
            Link(source="SupplyTemp", target="Scaled", target_slot="a"),
            Link(source="Gain", target="Scaled", target_slot="b"),
            Link(source="Scaled", target="DamperCmd", target_slot="in"),
            Link(source="On", target="FanCmd", target_slot="in"),
        ],
    )
    return JobSpec(
        name="Units contract",
        site="Example Campus",
        equipment_name="UNITS_1",
        sequence=SequenceSpec(family="CUSTOM", version="test"),
        points=[
            PointSpec(
                name="SupplyTemp",
                label="Supply temp",
                data_type=DataType.NUMERIC,
                role=PointRole.SENSOR,
                units="°F",
                default=55.0,
            ),
            PointSpec(
                name="Airflow",
                label="Airflow",
                data_type=DataType.NUMERIC,
                role=PointRole.SENSOR,
                units="cfm",
                default=0.0,
            ),
            PointSpec(
                name="Mystery",
                label="No unit",
                data_type=DataType.NUMERIC,
                role=PointRole.SENSOR,
                default=0.0,
            ),
            PointSpec(
                name="DamperCmd",
                label="Damper",
                data_type=DataType.NUMERIC,
                role=PointRole.COMMAND,
                units="%",
                default=0.0,
            ),
            PointSpec(
                name="FanCmd",
                label="Fan",
                data_type=DataType.BOOLEAN,
                role=PointRole.COMMAND,
                default=False,
            ),
        ],
        control_graph=graph,
        acceptance_tests=[
            AcceptanceCase(
                name="passes through",
                inputs={"SupplyTemp": 60.0},
                expectations=[
                    OutputExpectation(target="DamperCmd", value=60.0),
                    OutputExpectation(target="FanCmd", value=True),
                ],
            )
        ],
    )


def test_harvested_encodings_follow_the_bunit_grammar() -> None:
    for unit in NIAGARA_UNITS.values():
        assert re.fullmatch(r"[a-z ]+", unit.name), unit
        assert unit.encoding.count(";") == 4, unit
        assert unit.facet().startswith("units=u:")
    assert (
        NIAGARA_UNITS["fahrenheit"].facet()
        == "units=u:fahrenheit;°F;(K);*0.5555555555555556+255.37222222222223;"
    )
    assert NIAGARA_UNITS["percent"].facet() == "units=u:percent;%;;;"


@pytest.mark.parametrize(
    ("declared", "expected"),
    [
        ("°F", "fahrenheit"),
        ("degF", "fahrenheit"),
        ("deg F", "fahrenheit"),
        ("%", "percent"),
        ("inH2O", "inches of water"),
        ("in/wc", "inches of water"),
        ("cfm", "cubic feet per minute"),
        ("psi", "pounds per square inch"),
        ("°C", "celsius"),
        ("gpm", "gallons per minute"),
    ],
)
def test_contractor_unit_spellings_resolve(declared: str, expected: str) -> None:
    unit = resolve_unit(declared)
    assert unit is not None and unit.name == expected


def test_unknown_or_blank_units_fall_back_to_the_null_unit() -> None:
    assert resolve_unit("furlongs") is None
    assert resolve_unit("") is None
    assert units_facet(None) == "units=u:null;;;;"


def test_compiler_writes_declared_units_into_point_facets(tmp_path: Path) -> None:
    job = _job()
    archive = NiagaraCompiler().compile(
        job.control_graph,
        tmp_path / "units.bog",
        units={point.name: point.units for point in job.points},
    )
    facets = _points_facets(archive, "UNITS_1")
    assert facets["SupplyTemp"].startswith(
        "units=u:fahrenheit;°F;(K);*0.5555555555555556+255.37222222222223;|precision=i:"
    )
    assert facets["Airflow"].startswith("units=u:cubic feet per minute;cfm;(m3)(s-1);")
    assert facets["DamperCmd"].startswith("units=u:percent;%;;;|precision=i:")
    # The pybog defaults after the unit are preserved.
    assert facets["DamperCmd"].endswith("|min=d:-inf|max=d:+inf")
    # A point with no declared unit keeps the null unit, honestly.
    assert facets["Mystery"].startswith("units=u:null;;;;|")
    # Boolean points never carry a numeric unit.
    assert "units=" not in facets["FanCmd"]


def test_no_point_with_declared_units_ships_with_the_null_unit(tmp_path: Path) -> None:
    """The guard the goal asks for: every declared unit reaches the file."""
    service = WorkbenchService(RunRepository(tmp_path / "runs"))
    for job in (_job(), standard_vav_demo_job()):
        record = service.create_run(job)
        assert record.bog_path is not None, job.equipment_name
        folder = job.control_graph.name if job.control_graph else job.equipment_name
        facets = _points_facets(Path(record.bog_path), folder)
        declared = {point.name: point.units for point in job.points if point.units}
        offenders = {
            name: facets.get(name, "")
            for name in declared
            if name in facets and "units=u:null" in facets[name]
        }
        assert offenders == {}, f"points with declared units emitted u:null: {offenders}"
