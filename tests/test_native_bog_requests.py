"""N8 step 5: cross-equipment request signals summed into one program input, in the
project model, the simulator and the assembled station."""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

import pytest

from bactalk.domain import (
    AcceptanceCase,
    Block,
    BlockKind,
    ControlGraph,
    DataType,
    DeliverableRequirements,
    JobSpec,
    Link,
    OutputExpectation,
    PointRole,
    PointSpec,
    SequenceSpec,
    ShopProfile,
)
from bactalk.integrations.niagara_station import (
    NiagaraProgramAggregation,
    assemble_project_station_bog,
)
from bactalk.library_demo import lbnl_multizone_ahu_demo_job, lbnl_vav_reheat_demo_job
from bactalk.library_tier2.requests import REQUEST_RULES, request_signals, with_request_signals
from bactalk.niagara.emit import emit_bog
from bactalk.niagara.module import declared_types
from bactalk.niagara.validate import validate_bog
from bactalk.project_simulator import ProjectGraphInterpreter, run_project_acceptance_suite
from bactalk.projects import (
    EquipmentRelationship,
    ProjectAcceptanceCase,
    ProjectAcceptancePhase,
    ProjectOutputExpectation,
    ProjectSignalAggregation,
    ProjectSignalSource,
    ProjectSpec,
)
from bactalk.simulator import GraphInterpreter

pytestmark = [pytest.mark.native_bog]

ROOT = Path(__file__).resolve().parents[1]
STATION = ROOT / "tests" / "fixtures" / "native-bog" / "station-ahu-25vav.bog"
SITE = "Signal Campus"


def _numeric_job(equipment: str, input_name: str, output_name: str) -> JobSpec:
    graph = ControlGraph(
        name=equipment,
        blocks=[
            Block(
                id=input_name,
                kind=BlockKind.NUMERIC_INPUT,
                label=input_name,
                config={"default": 0.0},
            ),
            Block(id=output_name, kind=BlockKind.NUMERIC_OUTPUT, label=output_name),
        ],
        links=[Link(source=input_name, target=output_name, target_slot="in")],
    )
    return JobSpec(
        name=f"{equipment} controls",
        site=SITE,
        equipment_name=equipment,
        sequence=SequenceSpec(family="CUSTOM", version="test"),
        points=[
            PointSpec(
                name=input_name,
                label=input_name,
                data_type=DataType.NUMERIC,
                role=PointRole.SENSOR,
                default=0.0,
            ),
            PointSpec(
                name=output_name,
                label=output_name,
                data_type=DataType.NUMERIC,
                role=PointRole.COMMAND,
                default=0.0,
            ),
        ],
        control_graph=graph,
        acceptance_tests=[
            AcceptanceCase(
                name="pass through",
                inputs={input_name: 1.0},
                expectations=[OutputExpectation(target=output_name, value=1.0)],
            )
        ],
    )


def _sum_project(reduce: str = "sum") -> ProjectSpec:
    zones = [_numeric_job(f"ZONE_{i}", "Load", "Request") for i in (1, 2, 3)]
    ahu = _numeric_job("AHU_1", "Requests", "FanSpeed")
    return ProjectSpec(
        name="Summed requests",
        site=SITE,
        equipment=[ahu, *zones],
        signal_aggregations=[
            ProjectSignalAggregation(
                target_equipment="AHU_1",
                target_point="Requests",
                sources=[
                    ProjectSignalSource(equipment=z.equipment_name, point="Request") for z in zones
                ],
                reduce=reduce,  # type: ignore[arg-type]
            )
        ],
        acceptance_tests=[
            ProjectAcceptanceCase(
                name="three zones request",
                phases=[
                    ProjectAcceptancePhase(
                        name="requests",
                        inputs={"ZONE_1.Load": 1.0, "ZONE_2.Load": 2.0, "ZONE_3.Load": 3.0},
                        expectations=[
                            ProjectOutputExpectation(
                                equipment="AHU_1",
                                point="FanSpeed",
                                value=6.0 if reduce == "sum" else 3.0,
                            )
                        ],
                    )
                ],
            )
        ],
    )


def test_aggregation_is_summed_or_maxed_in_the_project_simulator() -> None:
    for reduce, expected in (("sum", 6.0), ("max", 3.0)):
        project = _sum_project(reduce)
        graphs = {job.equipment_name: job.control_graph for job in project.equipment}
        report = run_project_acceptance_suite(project, graphs)
        assert report.passed, [a for s in report.scenarios for a in s.assertions if not a.passed]
        assert report.coverage["signal_aggregation_count"] == 1
        sim = ProjectGraphInterpreter(project, graphs)
        values = sim.evaluate(
            {"ZONE_1.Load": 1.0, "ZONE_2.Load": 2.0, "ZONE_3.Load": 3.0}, step_seconds=1.0
        )
        assert values["AHU_1.FanSpeed"] == expected


def test_aggregation_validation_refuses_type_mismatch_and_double_drivers() -> None:
    project = _sum_project()
    with pytest.raises(ValueError, match="boolean target"):
        project.model_copy(
            update={
                "signal_aggregations": [
                    project.signal_aggregations[0].model_copy(update={"reduce": "any"})
                ]
            },
            deep=True,
        ).model_validate(
            project.model_copy(
                update={
                    "signal_aggregations": [
                        project.signal_aggregations[0].model_copy(update={"reduce": "any"})
                    ]
                }
            ).model_dump(mode="json")
        )
    doubled = project.model_dump(mode="json")
    doubled["signal_aggregations"].append(doubled["signal_aggregations"][0])
    with pytest.raises(ValueError, match="multiple drivers"):
        ProjectSpec.model_validate(doubled)
    without_tests = project.model_dump(mode="json")
    without_tests["acceptance_tests"] = []
    with pytest.raises(ValueError, match="require project acceptance tests"):
        ProjectSpec.model_validate(without_tests)


def _g36_project() -> ProjectSpec:
    ahu = lbnl_multizone_ahu_demo_job()
    site = ahu.site
    profile = ShopProfile(name="fixture", version="1")
    jobs = []
    for job, name in (
        (ahu, "AHU_1"),
        (lbnl_vav_reheat_demo_job(), "VAV_1"),
        (lbnl_vav_reheat_demo_job(), "VAV_2"),
    ):
        assert job.control_graph is not None
        jobs.append(
            job.model_copy(
                update={
                    "equipment_name": name,
                    "site": site,
                    "control_graph": job.control_graph.model_copy(update={"name": name}),
                    "deliverables": DeliverableRequirements(shop_profile=profile),
                }
            )
        )
    # Every AHU output must be observed by the project suite; the booleans take the
    # values the AHU produces on its own in occupied mode (characterised below).
    interpreter = GraphInterpreter(jobs[0].control_graph)
    values: dict[str, float | bool] = {}
    interpreter.evaluate({}, step_seconds=0.0)
    for _ in range(45):
        values = interpreter.evaluate({}, step_seconds=60.0)
    expectations = []
    for point in jobs[0].points:
        if point.role is not PointRole.COMMAND:
            continue
        if point.data_type is DataType.BOOLEAN:
            expectations.append(
                ProjectOutputExpectation(
                    equipment="AHU_1", point=point.name, value=bool(values[point.name])
                )
            )
        else:
            expectations.append(
                ProjectOutputExpectation(
                    equipment="AHU_1", point=point.name, operator="gte", value=-1e300
                )
            )
    return ProjectSpec(
        name="One AHU, two reheat boxes",
        site=site,
        equipment=jobs,
        relationships=[
            EquipmentRelationship(source="AHU_1", relation="feeds", target=n)
            for n in ("VAV_1", "VAV_2")
        ],
        acceptance_tests=[
            ProjectAcceptanceCase(
                name="starved zones raise pressure requests",
                phases=[
                    ProjectAcceptancePhase(
                        name="both zones in cooling, starved",
                        inputs={
                            f"{n}.{k}": v
                            for n in ("VAV_1", "VAV_2")
                            for k, v in (("TZon", 299.15), ("VDis_flow", 0.2))
                        },
                        expectations=expectations,
                    )
                ],
            )
        ],
    )


def test_g36_request_rules_generate_summed_zone_requests_for_the_ahu() -> None:
    project = _g36_project()
    bindings, aggregations = request_signals(project)
    assert bindings == []
    assert sorted((a.target_point, a.reduce, len(a.sources)) for a in aggregations) == [
        ("uZonPreResReq", "sum", 2),
        ("uZonTemResReq", "sum", 2),
    ]
    assert {rule.section for rule in REQUEST_RULES} >= {
        "G36 §5.6.8.1",
        "G36 §5.6.8.2",
        "G36 §5.16.14",
    }
    wired = with_request_signals(project)
    assert wired.signal_aggregations == aggregations
    graphs = {job.equipment_name: job.control_graph for job in wired.equipment}
    report = run_project_acceptance_suite(wired, graphs)
    assert report.passed, [a for s in report.scenarios for a in s.assertions if not a.passed][:5]

    def final(spec: ProjectSpec, inputs: dict[str, float | bool]) -> dict[str, float | bool]:
        sim = ProjectGraphInterpreter(spec, graphs)
        sim.evaluate(inputs, step_seconds=0.0)
        values: dict[str, float | bool] = {}
        for _ in range(45):
            values = sim.evaluate(inputs, step_seconds=60.0)
        return values

    starved = wired.acceptance_tests[0].phases[0].inputs
    with_requests = final(wired, starved)
    assert with_requests["VAV_1.yZonPreResReq"] == 3.0
    # The summed pressure requests reach the AHU: its static-pressure trim-and-respond
    # raises the fan above the no-request speed (the unwired project sees nothing).
    unwired = final(project, starved)
    assert with_requests["AHU_1.ySupFan"] > unwired["AHU_1.ySupFan"]


def _xml(content: bytes) -> ElementTree.Element:
    with zipfile.ZipFile(BytesIO(content)) as archive:
        return ElementTree.fromstring(archive.read("file.xml"))


def test_assembled_station_carries_the_request_sum_as_kitcontrol_add_chains() -> None:
    project = with_request_signals(_g36_project())
    programs = [
        (emit_bog(job.control_graph, points=job.points).content, job, job.control_graph)
        for job in project.equipment
    ]
    aggregations = [
        NiagaraProgramAggregation(
            target_equipment=item.target_equipment,
            target_point=item.target_point,
            sources=tuple((s.equipment, s.point) for s in item.sources),
            reduce=item.reduce,
            data_type="numeric",
        )
        for item in project.signal_aggregations
    ]
    assembly = assemble_project_station_bog(
        STATION.read_bytes(), programs, mode="insert", program_aggregations=aggregations
    )
    manifest = assembly.manifest
    assert manifest["cross_program_aggregation_count"] == 2
    rows = {row["target_point"]: row for row in manifest["cross_program_aggregations"]}
    assert rows["uZonPreResReq"]["block_type"] == "kitControl:Add"
    assert rows["uZonPreResReq"]["source_count"] == 2 and len(rows["uZonPreResReq"]["stages"]) == 1
    report = validate_bog(assembly.content, declared_types=declared_types(), label="requests")
    assert report.ok, [str(issue) for issue in report.errors][:5]
    root = _xml(assembly.content)
    ahu = next(e for e in root.iter("p") if e.get("n") == "AHU_1" and e.get("t") == "b:Folder")
    requests = next(e for e in ahu if e.get("n") == "Requests")
    adds = [e for e in requests if e.get("t") == "kitControl:Add"]
    assert len(adds) == 2
    links = [child for add in adds for child in add if child.get("t") == "b:Link"]
    assert len(links) == 4  # two sources per sum
    target = next(e for e in ahu.iter("p") if e.get("n") == "uZonPreResReq")
    driver = next(
        e for e in target if e.get("t") == "b:Link" and e.get("n") == "BactalkProjectRequest"
    )
    assert any(p.get("n") == "targetSlotName" and p.get("v") == "in16" for p in driver)


def test_many_sources_chain_reducers_four_inputs_at_a_time() -> None:
    zones = [_numeric_job(f"ZONE_{i}", "Load", "Request") for i in range(1, 10)]
    ahu = _numeric_job("AHU_1", "Requests", "FanSpeed")
    profile = ShopProfile(name="fixture", version="1")
    jobs = [
        j.model_copy(update={"deliverables": DeliverableRequirements(shop_profile=profile)})
        for j in (ahu, *zones)
    ]
    programs = [
        (emit_bog(j.control_graph, points=j.points).content, j, j.control_graph) for j in jobs
    ]
    aggregation = NiagaraProgramAggregation(
        "AHU_1", "Requests", tuple((z.equipment_name, "Request") for z in zones), "sum", "numeric"
    )
    assembly = assemble_project_station_bog(
        STATION.read_bytes(), programs, mode="insert", program_aggregations=[aggregation]
    )
    row = assembly.manifest["cross_program_aggregations"][0]
    # 9 sources: 4 in the first stage, then 3 more per stage with the carry → 3 stages.
    assert len(row["stages"]) == 3
    report = validate_bog(assembly.content, declared_types=declared_types(), label="chain")
    assert report.ok, [str(issue) for issue in report.errors][:5]
