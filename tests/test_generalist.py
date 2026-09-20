from pathlib import Path

from bactalk.agent import ProgrammingAgent, SequencePackPlanner
from bactalk.compiler import NiagaraCompiler
from bactalk.demo import generalist_demo_job
from bactalk.domain import BlockKind, SequenceSpec


def test_equipment_neutral_ahu_graph_passes_and_compiles(tmp_path: Path) -> None:
    job = generalist_demo_job()

    result = ProgrammingAgent(SequencePackPlanner()).run(job)

    assert result.report.passed
    assert result.report.engine == "BACTalk equipment-neutral truth-table simulator (Tier 1)"
    assert result.graph.metadata["sequence_family"] == "CUSTOM_AHU_SAFETY_COOLING"
    assert {block.kind for block in result.graph.blocks} >= {
        BlockKind.GREATER_THAN_OR_EQUAL,
        BlockKind.BOOLEAN_OUTPUT,
        BlockKind.NUMERIC_SWITCH,
    }
    destination = NiagaraCompiler().compile(result.graph, tmp_path / "ahu.bog")
    assert destination.exists()
    assert destination.stat().st_size > 0


def test_unknown_sequence_requires_graph_or_installed_pack() -> None:
    job = generalist_demo_job().model_copy(
        update={
            "control_graph": None,
            "sequence": SequenceSpec(family="UNKNOWN_EQUIPMENT_SEQUENCE"),
        }
    )

    try:
        ProgrammingAgent(SequencePackPlanner()).run(job)
    except ValueError as exc:
        assert "no installed deterministic pack" in str(exc)
    else:  # pragma: no cover - test assertion guard
        raise AssertionError("custom job without a graph unexpectedly ran")
