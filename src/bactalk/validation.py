from __future__ import annotations

from bactalk.domain import (
    AcceptanceCase,
    Block,
    BlockKind,
    ComparisonOperator,
    ControlGraph,
    DataType,
    JobSpec,
    OutputExpectation,
    PointRole,
)

INPUT_KINDS = {BlockKind.NUMERIC_INPUT, BlockKind.BOOLEAN_INPUT}
OUTPUT_KINDS = {BlockKind.NUMERIC_OUTPUT, BlockKind.BOOLEAN_OUTPUT}
NUMERIC_KINDS = {BlockKind.NUMERIC_INPUT, BlockKind.NUMERIC_OUTPUT}
BOOLEAN_KINDS = {BlockKind.BOOLEAN_INPUT, BlockKind.BOOLEAN_OUTPUT}


def _direction(block: Block) -> str | None:
    if block.kind in INPUT_KINDS:
        return "input"
    if block.kind in OUTPUT_KINDS:
        return "output"
    return None


def _data_type(block: Block) -> DataType:
    if block.kind in NUMERIC_KINDS:
        return DataType.NUMERIC
    if block.kind in BOOLEAN_KINDS:
        return DataType.BOOLEAN
    raise ValueError(f"block {block.id} is not a boundary I/O block")


def _assert_value_type(name: str, value: float | bool, data_type: DataType) -> None:
    if data_type == DataType.BOOLEAN:
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be boolean")
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")


def _validate_default(block: Block, default: float | bool) -> None:
    actual = block.config.get("default")
    if actual is None:
        raise ValueError(f"input block {block.id} must declare the job point default")
    if isinstance(default, bool):
        matches = actual is default
    else:
        matches = not isinstance(actual, bool) and float(actual) == float(default)
    if not matches:
        raise ValueError(
            f"input block {block.id} default {actual!r} does not match job point default "
            f"{default!r}"
        )


def _validate_case(
    case: AcceptanceCase,
    input_blocks: dict[str, Block],
    output_blocks: dict[str, Block],
) -> set[str]:
    input_sets = [(case.name, case.inputs)]
    input_sets.extend((f"{case.name} / {phase.name}", phase.inputs) for phase in case.timeline)
    for case_label, inputs in input_sets:
        for name, value in inputs.items():
            block = input_blocks.get(name)
            if block is None:
                raise ValueError(
                    f"acceptance case {case_label!r} input {name!r} is not a graph input"
                )
            _assert_value_type(
                f"acceptance case {case_label!r} input {name!r}",
                value,
                _data_type(block),
            )

    expectation_sets: list[tuple[str, list[OutputExpectation]]] = [(case.name, case.expectations)]
    expectation_sets.extend(
        (f"{case.name} / {phase.name}", phase.expectations) for phase in case.timeline
    )
    covered: set[str] = set()
    for case_label, expectations in expectation_sets:
        for expectation in expectations:
            block = output_blocks.get(expectation.target)
            if block is None:
                raise ValueError(
                    f"acceptance case {case_label!r} target {expectation.target!r} "
                    "is not a graph output"
                )
            data_type = _data_type(block)
            _assert_value_type(
                f"acceptance case {case_label!r} expectation {expectation.target!r}",
                expectation.value,
                data_type,
            )
            if data_type == DataType.BOOLEAN and expectation.operator not in {
                ComparisonOperator.EQUAL,
                ComparisonOperator.NOT_EQUAL,
            }:
                raise ValueError(
                    f"boolean expectation {expectation.target!r} only supports eq or ne"
                )
            covered.add(expectation.target)
    return covered


def validate_job_graph_contract(job: JobSpec, graph: ControlGraph) -> None:
    """Bind a typed graph to the contractor-authorized point and test contracts.

    Structural graph validation proves that wires are type-safe. This separate
    gate proves that every boundary block is an authorized job point and that a
    custom test oracle observes the program's actual outputs.
    """

    points = {point.name: point for point in job.points}
    boundary_blocks = {block.id: block for block in graph.blocks if _direction(block) is not None}
    input_blocks = {
        block_id: block for block_id, block in boundary_blocks.items() if block.kind in INPUT_KINDS
    }
    output_blocks = {
        block_id: block for block_id, block in boundary_blocks.items() if block.kind in OUTPUT_KINDS
    }

    for block_id, block in boundary_blocks.items():
        point = points.get(block_id)
        if point is None:
            raise ValueError(f"graph boundary block {block_id!r} is not an authorized job point")
        direction = _direction(block)
        if _data_type(block) != point.data_type:
            raise ValueError(f"graph boundary block {block_id!r} type does not match its job point")
        if point.role in {PointRole.SENSOR, PointRole.SETPOINT} and direction != "input":
            raise ValueError(f"{point.role.value} point {block_id!r} must be a graph input")
        if point.role in {PointRole.COMMAND, PointRole.ALARM} and direction != "output":
            raise ValueError(f"{point.role.value} point {block_id!r} must be a graph output")
        if direction == "input":
            _validate_default(block, point.default)

    missing = sorted(
        point.name for point in job.points if point.required and point.name not in boundary_blocks
    )
    if missing:
        raise ValueError(f"required job points are absent from the graph: {', '.join(missing)}")

    if not job.acceptance_tests:
        return
    case_names = [case.name for case in job.acceptance_tests]
    if len(case_names) != len(set(case_names)):
        raise ValueError("acceptance case names must be unique")
    covered_outputs: set[str] = set()
    for case in job.acceptance_tests:
        covered_outputs.update(_validate_case(case, input_blocks, output_blocks))
    untested_outputs = sorted(set(output_blocks) - covered_outputs)
    if untested_outputs:
        raise ValueError(
            "custom acceptance tests do not observe graph outputs: " + ", ".join(untested_outputs)
        )
