"""N11 exit: a fixture job combining Tier 1 equipment (the LBNL AHU and VAV box) with two
custom, job-specific sequences exports one .bog through declared typed signals only; the
station lowers natively and validates, the project suite passes, and every custom
scenario traces to a requirement whose approval state the gate reports."""

from __future__ import annotations

from pathlib import Path

import pytest

from bactalk.domain import DataType, DeliverableRequirements, PointRole, ShopProfile
from bactalk.integrations.niagara_station import NiagaraProgramLink, assemble_project_station_bog
from bactalk.library_demo import lbnl_multizone_ahu_demo_job, lbnl_vav_reheat_demo_job
from bactalk.library_tier5_fixture import ITEMS, TIER5_FIXTURE_LABEL
from bactalk.niagara.emit import emit_bog
from bactalk.niagara.lowering import LoweringPolicy, plan_lowering
from bactalk.niagara.module import declared_types
from bactalk.niagara.validate import validate_bog
from bactalk.project_simulator import run_project_acceptance_suite
from bactalk.projects import (
    ProjectAcceptanceCase,
    ProjectAcceptancePhase,
    ProjectOutputExpectation,
    ProjectSignalBinding,
    ProjectSpec,
)
from bactalk.protocol import catalog, generate_test_plan
from bactalk.protocol.adequacy import run_suite
from bactalk.simulator import GraphInterpreter

pytestmark = [pytest.mark.native_bog]

ROOT = Path(__file__).resolve().parents[1]
STATION = ROOT / "tests" / "fixtures" / "native-bog" / "station-ahu-25vav.bog"
ROWS = [entry for entry in catalog.rows() if entry.item.tier == 5]
IDS = [entry.item.id for entry in ROWS]


def _characterised(
    job, inputs: dict[str, float | bool], steps: int
) -> list[ProjectOutputExpectation]:
    """Every output of a bound-into program must be observed: the booleans take the
    values the program produces on its own under the phase inputs, the numerics are
    observed with an open range (the requests fixture does the same)."""

    interpreter = GraphInterpreter(job.control_graph)
    interpreter.evaluate(inputs, step_seconds=0.0)
    values: dict[str, float | bool] = {}
    for _ in range(steps):
        values = interpreter.evaluate(inputs, step_seconds=60.0)
    expectations = []
    for point in job.points:
        if point.role not in {PointRole.COMMAND, PointRole.ALARM}:
            continue
        if point.data_type is DataType.BOOLEAN:
            expectations.append(
                ProjectOutputExpectation(
                    equipment=job.equipment_name, point=point.name, value=bool(values[point.name])
                )
            )
        else:
            expectations.append(
                ProjectOutputExpectation(
                    equipment=job.equipment_name, point=point.name, operator="gte", value=-1e300
                )
            )
    return expectations


def _fixture_project() -> ProjectSpec:
    profile = ShopProfile(name="fixture", version="1")

    def placed(job):
        return job.model_copy(
            update={
                "site": "fixture",
                "control_graph": job.control_graph.model_copy(update={"name": job.equipment_name}),
                "deliverables": DeliverableRequirements(shop_profile=profile),
            }
        )

    ahu = placed(lbnl_multizone_ahu_demo_job())
    vav = placed(lbnl_vav_reheat_demo_job())
    hood = placed(catalog.protocol_job("custom-kitchen-hood-interlock"))
    changeover = placed(catalog.protocol_job("custom-seasonal-changeover"))
    occupied_ahu = {f"AHU_1.{k}": v for k, v in ahu.acceptance_tests[0].inputs.items()}
    hood_inputs = {"uHooSw": True, "uMakFanSta": True, "uAhuFan": True}
    vav_inputs = {
        point.name: point.default
        for point in vav.points
        if point.role not in {PointRole.COMMAND, PointRole.ALARM}
    }
    vav_inputs["u1HotPla"] = True
    observed = [
        *_characterised(hood, hood_inputs, 40),
        *[e for e in _characterised(vav, vav_inputs, 40) if e.point != "yHotWatPlaReq"],
    ]
    return ProjectSpec(
        name="Tier 1 equipment with two custom sequences",
        site="fixture",
        equipment=[ahu, vav, hood, changeover],
        signal_bindings=[
            ProjectSignalBinding(
                source_equipment="AHU_1",
                source_point="y1SupFan",
                target_equipment="HOOD_1",
                target_point="uAhuFan",
            ),
            ProjectSignalBinding(
                source_equipment="CHG_1",
                source_point="yHeaSea",
                target_equipment="VAV_21",
                target_point="u1HotPla",
            ),
        ],
        acceptance_tests=[
            ProjectAcceptanceCase(
                name="hood follows the AHU fan; heating season reaches the VAV",
                phases=[
                    ProjectAcceptancePhase(
                        name="occupied, cold, hood on",
                        inputs={
                            **occupied_ahu,
                            "HOOD_1.uHooSw": True,
                            "HOOD_1.uMakFanSta": True,
                            "CHG_1.TOut": 278.15,
                            "CHG_1.uHeaOvr": False,
                            "CHG_1.uCooOvr": False,
                        },
                        repeat=40,
                        step_seconds=60.0,
                        expectations=[
                            ProjectOutputExpectation(
                                equipment="AHU_1", point="y1SupFan", value=True
                            ),
                            ProjectOutputExpectation(
                                equipment="CHG_1", point="yHeaSea", value=True
                            ),
                            ProjectOutputExpectation(
                                equipment="VAV_21", point="yHotWatPlaReq", operator="gte", value=0.0
                            ),
                            *observed,
                        ],
                    ),
                    ProjectAcceptancePhase(
                        name="hood off",
                        inputs={"HOOD_1.uHooSw": False},
                        repeat=2,
                        step_seconds=60.0,
                        expectations=[
                            ProjectOutputExpectation(
                                equipment="HOOD_1", point="yMakFan", value=False
                            ),
                            ProjectOutputExpectation(
                                equipment="HOOD_1", point="yMakDam", value=False
                            ),
                        ],
                    ),
                ],
            )
        ],
    )


def test_fixture_items_are_labelled_custom_job_specific() -> None:
    assert {item.id for item in ITEMS} == {
        "custom-kitchen-hood-interlock",
        "custom-seasonal-changeover",
    }
    for item in ITEMS:
        assert item.label == TIER5_FIXTURE_LABEL and item.family == "CUSTOM_JOB_SPECIFIC"
        job = catalog.protocol_job(item.id)
        assert job.sequence.parameters["protocol"]["tier"] == 5
        assert "custom, job-specific" in job.sequence.parameters["protocol"]["label"]


@pytest.mark.parametrize("entry", ROWS, ids=IDS)
def test_custom_sequence_passes_its_generated_suite_and_traces_every_scenario(entry) -> None:
    requirements = entry.requirement_set()
    plan = generate_test_plan(requirements)
    job = catalog.protocol_job(requirements.sequence_id, plan=plan)
    report, suite = run_suite(job, plan, requirements)
    assert suite["passed"] and report.coverage["fully_covered"], report.coverage["gaps"]
    ids = {r.id for r in requirements.requirements}
    for scenario in plan.scenarios:
        assert scenario.requirement_id in ids
        citation = requirements.requirement(scenario.requirement_id).citation
        assert citation.paragraph, "every custom requirement cites its specification paragraph"
    assert set(plan.traceability()) == ids
    cited = {req for reqs in job.control_graph.metadata["traceability"].values() for req in reqs}
    assert ids <= cited
    assert set(job.control_graph.metadata["citations"]) == ids


@pytest.mark.parametrize("entry", ROWS, ids=IDS)
def test_retained_custom_adequacy_is_current(entry) -> None:
    requirements = entry.requirement_set()
    artifact = entry.adequacy_artifact()
    assert artifact is not None, f"run scripts/protocol_adequacy.py {requirements.sequence_id}"
    assert artifact["requirements_digest"] == requirements.digest()
    assert artifact["suite"]["passed"] is True and artifact["decisions"]["fully_covered"] is True
    assert artifact["invariants"]["violations"] == 0 and "catch_rate" in (
        artifact["mutation"] or {}
    )


def test_project_composes_tier1_and_custom_programs_into_one_validated_bog() -> None:
    project = _fixture_project()
    graphs = {job.equipment_name: job.control_graph for job in project.equipment}
    report = run_project_acceptance_suite(project, graphs)
    assert report.passed, [
        (s.name, [a.name for a in s.assertions if not a.passed])
        for s in report.scenarios
        if not s.passed
    ]
    programs = []
    for job in project.equipment:
        lowering = plan_lowering(job.control_graph, LoweringPolicy())
        assert lowering.lane in {"native_stock", "native_with_module"} and not lowering.blockers, (
            job.name
        )
        programs.append(
            (emit_bog(job.control_graph, points=job.points).content, job, job.control_graph)
        )
    links = [
        NiagaraProgramLink(
            source_equipment=b.source_equipment,
            source_point=b.source_point,
            target_equipment=b.target_equipment,
            target_point=b.target_point,
            data_type="boolean",
        )
        for b in project.signal_bindings
    ]
    assembly = assemble_project_station_bog(
        STATION.read_bytes(), programs, mode="insert", program_links=links
    )
    validation = validate_bog(assembly.content, declared_types=declared_types(), label="tier5")
    assert validation.ok, [str(issue) for issue in validation.errors[:5]]
    manifest = assembly.manifest
    assert manifest["cross_program_link_count"] == 2
    labels = {
        job.equipment_name: job.sequence.parameters.get("protocol", {}).get("label")
        for job in project.equipment
    }
    assert labels["HOOD_1"] == TIER5_FIXTURE_LABEL and labels["CHG_1"] == TIER5_FIXTURE_LABEL
    assert labels["AHU_1"] is None and labels["VAV_21"] is None
