from bactalk.domain import AcceptanceCase, Block, BlockKind, ControlGraph, Link, OutputExpectation
from bactalk.simulator import run_generic_acceptance_suite


def _boolean_and_graph() -> ControlGraph:
    return ControlGraph(
        name="BooleanCoverage",
        blocks=[
            Block(
                id="Enable",
                kind=BlockKind.BOOLEAN_INPUT,
                label="Enable",
                config={"default": False},
            ),
            Block(
                id="Proof",
                kind=BlockKind.BOOLEAN_INPUT,
                label="Proof",
                config={"default": False},
            ),
            Block(id="Both", kind=BlockKind.AND, label="Both true"),
            Block(id="Command", kind=BlockKind.BOOLEAN_OUTPUT, label="Command"),
        ],
        links=[
            Link(source="Enable", target="Both", target_slot="a"),
            Link(source="Proof", target="Both", target_slot="b"),
            Link(source="Both", target="Command", target_slot="in"),
        ],
    )


def _case(name: str, enable: bool, proof: bool, expected: bool) -> AcceptanceCase:
    return AcceptanceCase(
        name=name,
        inputs={"Enable": enable, "Proof": proof},
        expectations=[OutputExpectation(target="Command", value=expected)],
    )


def test_decision_coverage_exposes_passing_but_untested_outcome() -> None:
    report = run_generic_acceptance_suite(
        _boolean_and_graph(),
        [_case("disabled", False, False, False)],
    )

    assert report.passed is True
    assert report.coverage["percent"] == 50.0
    assert report.coverage["fully_covered"] is False
    assert report.coverage["gaps"] == ["Both"]


def test_decision_coverage_recognizes_both_boolean_outcomes() -> None:
    report = run_generic_acceptance_suite(
        _boolean_and_graph(),
        [
            _case("disabled", False, False, False),
            _case("enabled and proven", True, True, True),
        ],
    )

    assert report.passed is True
    assert report.coverage["percent"] == 100.0
    assert report.coverage["fully_covered"] is True
    assert report.coverage["gaps"] == []
