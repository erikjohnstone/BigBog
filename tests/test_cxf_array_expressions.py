"""Array evaluation and MultiSum gains in the CXF scalariser (docs/decisions/015, 016)."""

from __future__ import annotations

import pytest

from bactalk.integrations.cxf_arrays import CxfArrayScalarizationError, _parse_array_expression
from bactalk.library_tier2 import retained_translation

pytestmark = [pytest.mark.minimal]


def test_modelica_matrix_literal() -> None:
    assert _parse_array_expression("[0, 1; 24*3600, 1]", {}, context="sch") == [
        [0, 1],
        [86400, 1],
    ]


def test_nested_comprehension_and_two_dimensional_index_transpose() -> None:
    # EquipmentEnable's traStaEqu = {{staEqu[i, j] for i in 1:nSta} for j in 1:nEqu}
    staging = [[1, 0, 0], [0, 0.5, 0.5]]
    transposed = _parse_array_expression(
        "{{staEqu[i, j] for i in 1:nSta} for j in 1:nEqu}",
        {"staEqu": staging, "nSta": 2, "nEqu": 3},
        context="traStaEqu",
    )
    assert transposed == [[1, 0], [0, 0.5], [0, 0.5]]


def test_comprehension_repeats_an_array_body_as_rows() -> None:
    # SortRuntime's idxEquAltMat k = {idxEquAlt for i in 1:nEquAlt}
    assert _parse_array_expression(
        "{idxEquAlt for i in 1:nEquAlt}", {"idxEquAlt": [1, 2, 3], "nEquAlt": 3}, context="k"
    ) == [[1, 2, 3], [1, 2, 3], [1, 2, 3]]


def test_indexing_outside_a_matrix_is_refused() -> None:
    with pytest.raises(CxfArrayScalarizationError):
        _parse_array_expression(
            "{staEqu[i, 3] for i in 1:2}", {"staEqu": [[1, 0], [0, 1]]}, context="bad"
        )


def _gains(configuration: str, label: str) -> list[float]:
    blocks = retained_translation(configuration)["typed_ir"]["blocks"]
    return sorted(
        block["config"]["value"]
        for block in blocks
        if block["kind"] == "numeric_const"
        and str(block.get("label", "")).startswith(f"{label} gain ")
    )


def test_multisum_gains_are_applied_not_dropped() -> None:
    """Decision 016: the fold used to ignore MultiSum's k, so these two LBNL sums were
    translated (and referenced) without their gains."""

    # Economizers.Subsequences.Tuning: mulSum(k={-step, step, 1}), step = 0.02; the
    # third gain is 1 and needs no block
    assert _gains("chw-economizer", "mulSum") == [-0.02, 0.02]
    # Towers ... IntegratedOperation: totMinCycLoa(k=fill(1.1, nChi)), two chillers
    assert _gains("chw-towers", "totMinCycLoa") == [1.1, 1.1]
