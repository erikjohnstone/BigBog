"""Tier 3 library: G36 sequences with no LBNL reference, built under the Test
Generation Protocol (GOAL-NATIVE-BOG.md N9). Items register with
``bactalk.protocol.catalog``; the helpers here keep the N9 names."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bactalk.domain import JobSpec
from bactalk.library_tier3.hw_plant_boiler.graph import build_graph as _build_hw_plant
from bactalk.protocol.catalog import ProtocolItem, Row, points_for, protocol_job, register
from bactalk.protocol.requirements import RequirementSet
from bactalk.protocol.test_author import TestPlan

TIER3_LABEL = "G36 sequence without an LBNL reference (Tier 3, Gate G-ENG)"

ITEMS: tuple[ProtocolItem, ...] = (
    register(
        ProtocolItem(
            id="hw-plant-boiler",
            tier=3,
            label=TIER3_LABEL,
            package="bactalk.library_tier3.hw_plant_boiler",
            family="BACTALK_HW_PLANT",
            equipment_name="HWP_1",
            builder=lambda requirements, points, options: _build_hw_plant(requirements, points),
        )
    ),
)
ITEMS_BY_ID = {item.id: item for item in ITEMS}


def _row(item_id: str) -> Row:
    return Row(ITEMS_BY_ID[item_id], ITEMS_BY_ID[item_id].configurations[0])


def requirement_set(item_id: str) -> RequirementSet:
    return _row(item_id).requirement_set()


def requirements_path(item_id: str) -> Path:
    return _row(item_id).requirements_path


def adequacy_path(item_id: str) -> Path:
    return _row(item_id).adequacy_path


def adequacy_artifact(item_id: str) -> dict[str, Any] | None:
    """The retained adequacy report (scripts/protocol_adequacy.py), if committed."""

    return _row(item_id).adequacy_artifact()


def tier3_job(item_id: str, *, plan: TestPlan | None = None) -> JobSpec:
    return protocol_job(requirement_set(item_id).sequence_id, plan=plan)


__all__ = [
    "ITEMS",
    "ITEMS_BY_ID",
    "TIER3_LABEL",
    "adequacy_artifact",
    "adequacy_path",
    "points_for",
    "requirement_set",
    "requirements_path",
    "tier3_job",
]
