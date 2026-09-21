from __future__ import annotations

from pathlib import Path

import pytest

from bactalk.integrations.funnel import FunnelScorer


def test_real_pyfunnel_scoring_adapter(tmp_path: Path) -> None:
    pytest.importorskip("pyfunnel")

    result = FunnelScorer().compare(
        [0.0, 1.0, 2.0, 3.0],
        [0.0, 1.0, 2.0, 3.0],
        [0.0, 1.0, 2.0, 3.0],
        [0.0, 1.05, 1.95, 3.0],
        tmp_path / "funnel",
        absolute_value_tolerance=0.1,
    )

    assert result.completed is True
    assert result.passed is True
    assert result.max_error == 0.0
    assert result.counterexample(
        [0.0, 1.0, 2.0, 3.0], [0.0, 1.05, 1.95, 3.0]
    ) is None
    assert result.errors_csv.read_text(encoding="utf-8").splitlines() == [
        "x,y",
        "0,0",
        "1,0",
        "2,0",
        "3,0",
    ]


def test_pyfunnel_completion_is_not_mistaken_for_trajectory_pass(tmp_path: Path) -> None:
    pytest.importorskip("pyfunnel")

    result = FunnelScorer().compare(
        [0.0, 1.0, 2.0],
        [0.0, 0.0, 0.0],
        [0.0, 1.0, 2.0],
        [0.0, 10.0, 0.0],
        tmp_path / "failed-funnel",
    )

    assert result.completed is True
    assert result.passed is False
    assert result.max_error is not None
    assert result.max_error > 9.0
    assert result.counterexample(
        [0.0, 1.0, 2.0], [0.0, 10.0, 0.0]
    ) == {
        "schema": "bactalk.trajectory-counterexample/v1",
        "violation_count": 1,
        "first_violation_time": 1.0,
        "last_violation_time": 1.0,
        "peak_error_time": 1.0,
        "peak_error": pytest.approx(10.0),
        "peak_absolute_error": pytest.approx(10.0),
        "context_samples": 1,
        "window": {
            "start_index": 0,
            "end_index": 2,
            "test_times": [0.0, 1.0, 2.0],
            "test_values": [0.0, 10.0, 0.0],
        },
    }
