"""Tier 5 fixture: two custom, job-specific sequences written the way the AI drafts
them from a contractor's specification section (GOAL-NATIVE-BOG.md N11), retained so
the protocol can grade them and the composition fixture can export them with Tier 1
equipment in one .bog. Real custom sequences live with their job
(`bactalk.protocol.custom`), not here."""

from __future__ import annotations

from bactalk.library_tier5_fixture.kitchen_hood.graph import build_graph as _build_hood
from bactalk.library_tier5_fixture.seasonal_changeover.graph import build_graph as _build_changeover
from bactalk.protocol.catalog import ProtocolItem, register

TIER5_LABEL = "custom, job-specific"
TIER5_FIXTURE_LABEL = "custom, job-specific (fixture)"

ITEMS: tuple[ProtocolItem, ...] = (
    register(
        ProtocolItem(
            id="custom-kitchen-hood-interlock",
            tier=5,
            label=TIER5_FIXTURE_LABEL,
            package="bactalk.library_tier5_fixture.kitchen_hood",
            family="CUSTOM_JOB_SPECIFIC",
            equipment_name="HOOD_1",
            builder=_build_hood,
        )
    ),
    register(
        ProtocolItem(
            id="custom-seasonal-changeover",
            tier=5,
            label=TIER5_FIXTURE_LABEL,
            package="bactalk.library_tier5_fixture.seasonal_changeover",
            family="CUSTOM_JOB_SPECIFIC",
            equipment_name="CHG_1",
            builder=_build_changeover,
        )
    ),
)
ITEMS_BY_ID = {item.id: item for item in ITEMS}

__all__ = ["ITEMS", "ITEMS_BY_ID", "TIER5_FIXTURE_LABEL", "TIER5_LABEL"]
