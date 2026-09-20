from __future__ import annotations

import pytest

from bactalk.agent import SequencePackPlanner
from bactalk.demo import generalist_demo_job
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
)
from bactalk.simulator import run_acceptance_suite
from bactalk.validation import validate_job_graph_contract


def _graph_job(**updates: object) -> JobSpec:
    job = generalist_demo_job()
    return job.model_copy(update=updates)


def _planned_graph() -> ControlGraph:
    return SequencePackPlanner().plan(generalist_demo_job())


def _graph_with(*, blocks: list[Block], links: list[Link]) -> ControlGraph:
    graph = _planned_graph()
    return ControlGraph.model_validate(
        {**graph.model_dump(mode="python"), "blocks": blocks, "links": links}
    )


def test_generalist_job_and_graph_have_a_complete_boundary_contract() -> None:
    job = generalist_demo_job()
    graph = _planned_graph()

    validate_job_graph_contract(job, graph)


def test_graph_cannot_invent_an_unauthorized_output_point() -> None:
    job = generalist_demo_job()
    graph = _planned_graph()
    rogue = Block(id="RogueCommand", kind=BlockKind.BOOLEAN_OUTPUT, label="Rogue")
    mutated = _graph_with(
        blocks=[*graph.blocks, rogue],
        links=[*graph.links, Link(source="FanEnable", target="RogueCommand", target_slot="in")],
    )

    with pytest.raises(ValueError, match="not an authorized job point"):
        validate_job_graph_contract(job, mutated)


def test_graph_cannot_silently_drop_a_required_command() -> None:
    job = generalist_demo_job()
    graph = _planned_graph()
    mutated = _graph_with(
        blocks=[block for block in graph.blocks if block.id != "CoolingValveCommand"],
        links=[link for link in graph.links if link.target != "CoolingValveCommand"],
    )

    with pytest.raises(ValueError, match="CoolingValveCommand"):
        validate_job_graph_contract(job, mutated)


def test_boundary_type_and_role_must_match_the_job_point() -> None:
    job = generalist_demo_job()
    graph = _planned_graph()
    wrong_type_points = [
        point.model_copy(update={"data_type": DataType.BOOLEAN, "default": False})
        if point.name == "DuctStatic"
        else point
        for point in job.points
    ]
    wrong_role_points = [
        point.model_copy(update={"role": PointRole.SENSOR})
        if point.name == "SupplyFanCommand"
        else point
        for point in job.points
    ]

    with pytest.raises(ValueError, match="type does not match"):
        validate_job_graph_contract(_graph_job(points=wrong_type_points), graph)
    with pytest.raises(ValueError, match="sensor point.*must be a graph input"):
        validate_job_graph_contract(_graph_job(points=wrong_role_points), graph)


def test_graph_input_default_is_bound_to_the_job_default() -> None:
    job = generalist_demo_job()
    graph = _planned_graph()
    blocks = [
        block.model_copy(update={"config": {"default": 99.0}})
        if block.id == "DuctStatic"
        else block
        for block in graph.blocks
    ]
    mutated = _graph_with(blocks=blocks, links=graph.links)

    with pytest.raises(ValueError, match="does not match job point default"):
        validate_job_graph_contract(job, mutated)


@pytest.mark.parametrize(
    ("case", "message"),
    [
        (
            AcceptanceCase(
                name="unknown input",
                inputs={"Typo": 1.0},
                expectations=[OutputExpectation(target="SupplyFanCommand", value=False)],
            ),
            "is not a graph input",
        ),
        (
            AcceptanceCase(
                name="internal target",
                inputs={},
                expectations=[OutputExpectation(target="PressureHigh", value=False)],
            ),
            "is not a graph output",
        ),
        (
            AcceptanceCase(
                name="wrong output type",
                inputs={},
                expectations=[OutputExpectation(target="CoolingValveCommand", value=True)],
            ),
            "must be numeric",
        ),
    ],
)
def test_acceptance_oracle_can_only_drive_inputs_and_observe_typed_outputs(
    case: AcceptanceCase, message: str
) -> None:
    graph = _planned_graph()

    with pytest.raises(ValueError, match=message):
        run_acceptance_suite(graph, _graph_job(acceptance_tests=[case]))


def test_custom_acceptance_oracle_must_cover_every_graph_output() -> None:
    job = generalist_demo_job()
    graph = _planned_graph()
    cases = []
    for case in job.acceptance_tests:
        expectations = [item for item in case.expectations if item.target != "DuctPressureAlarm"]
        cases.append(case.model_copy(update={"expectations": expectations}))

    with pytest.raises(ValueError, match="DuctPressureAlarm"):
        run_acceptance_suite(graph, _graph_job(acceptance_tests=cases))
