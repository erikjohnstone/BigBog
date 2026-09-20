from __future__ import annotations

import pytest

from bactalk.demo import demo_job
from bactalk.integrations.brick import build_and_validate_brick


def test_job_exports_valid_brick_graph() -> None:
    result = build_and_validate_brick(demo_job())

    assert result.conforms is True
    assert result.triples >= 40
    assert "brick:VAV" in result.turtle
    assert "brick:Zone_Air_Temperature_Sensor" in result.turtle
    assert "bacnetObjectIdentifier" in result.turtle


def test_unknown_brick_class_is_rejected() -> None:
    job = demo_job()
    job.points[0].brick_class = "brick:Definitely_Not_A_Real_Brick_Class"

    with pytest.raises(ValueError, match="unknown Brick class"):
        build_and_validate_brick(job)
