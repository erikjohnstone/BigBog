"""Tier 4 library: BACTalk standard sequences (engineer-approved requirements), never
labelled G36, built under the Test Generation Protocol (GOAL-NATIVE-BOG.md N10).
Configurable, not forked: one graph builder per equipment type takes the declared
options of each configuration."""

from __future__ import annotations

from bactalk.library_tier4.doas.graph import build_graph as _build_doas
from bactalk.library_tier4.exhaust_fan.graph import build_graph as _build_exhaust_fan
from bactalk.library_tier4.heat_pump.graph import build_graph as _build_heat_pump
from bactalk.library_tier4.pump_duty_standby.graph import build_graph as _build_pump_pair
from bactalk.library_tier4.rtu.graph import build_graph as _build_rtu
from bactalk.protocol.catalog import ItemConfiguration, ProtocolItem, register

TIER4_LABEL = "BACTalk standard sequence (engineer-approved requirements)"

ITEMS: tuple[ProtocolItem, ...] = (
    register(
        ProtocolItem(
            id="exhaust-fan",
            tier=4,
            label=TIER4_LABEL,
            package="bactalk.library_tier4.exhaust_fan",
            family="BACTALK_STANDARD_SEQUENCE",
            equipment_name="EF_1",
            builder=_build_exhaust_fan,
            configurations=(
                ItemConfiguration(id="default", label="basic", options={"isolation_damper": False}),
                ItemConfiguration(
                    id="damper", label="isolation damper", options={"isolation_damper": True}
                ),
            ),
        )
    ),
    register(
        ProtocolItem(
            id="pump-duty-standby",
            tier=4,
            label=TIER4_LABEL,
            package="bactalk.library_tier4.pump_duty_standby",
            family="BACTALK_STANDARD_SEQUENCE",
            equipment_name="PMP_1",
            builder=_build_pump_pair,
        )
    ),
    register(
        ProtocolItem(
            id="rtu",
            tier=4,
            label=TIER4_LABEL,
            package="bactalk.library_tier4.rtu",
            family="BACTALK_STANDARD_SEQUENCE",
            equipment_name="RTU_1",
            builder=_build_rtu,
            configurations=(
                ItemConfiguration(
                    id="default", label="no economizer", options={"economizer": False}
                ),
                ItemConfiguration(
                    id="economizer", label="economizer", options={"economizer": True}
                ),
            ),
        )
    ),
    register(
        ProtocolItem(
            id="heat-pump",
            tier=4,
            label=TIER4_LABEL,
            package="bactalk.library_tier4.heat_pump",
            family="BACTALK_STANDARD_SEQUENCE",
            equipment_name="HP_1",
            builder=_build_heat_pump,
            configurations=(
                ItemConfiguration(
                    id="default", label="compressor only", options={"aux_heat": False}
                ),
                ItemConfiguration(id="aux", label="auxiliary heat", options={"aux_heat": True}),
            ),
        )
    ),
    register(
        ProtocolItem(
            id="doas",
            tier=4,
            label=TIER4_LABEL,
            package="bactalk.library_tier4.doas",
            family="BACTALK_STANDARD_SEQUENCE",
            equipment_name="DOAS_1",
            builder=_build_doas,
            configurations=(
                ItemConfiguration(
                    id="default", label="no recovery", options={"energy_recovery": False}
                ),
                ItemConfiguration(
                    id="erv", label="energy recovery", options={"energy_recovery": True}
                ),
            ),
        )
    ),
)
ITEMS_BY_ID = {item.id: item for item in ITEMS}

__all__ = ["ITEMS", "ITEMS_BY_ID", "TIER4_LABEL"]
