from __future__ import annotations

import pytest
from pydantic import ValidationError

from bactalk.demo import demo_job
from bactalk.domain import (
    BacnetDeviceSpec,
    BacnetObjectSpec,
    BacnetScan,
    Block,
    BlockKind,
    ControlGraph,
    DataType,
    JobSpec,
    Link,
    PointRole,
    PointSpec,
)
from bactalk.sequences import build_g36_vav_reheat
from bactalk.simulator import GraphInterpreter, run_acceptance_suite


def test_vav_sequence_is_typed_and_passes_acceptance_suite() -> None:
    graph = build_g36_vav_reheat(demo_job())

    assert len(graph.blocks) == 28
    assert len(graph.links) == 36
    assert run_acceptance_suite(graph).passed is True


def test_vav_sequence_has_expected_boundary_behavior() -> None:
    graph = build_g36_vav_reheat(demo_job())
    outputs = GraphInterpreter(graph).evaluate(
        {
            "ZoneTemp": 75.5,
            "CoolingSetpoint": 74.0,
            "HeatingSetpoint": 70.0,
            "Occupied": True,
        }
    )

    assert outputs["CoolingDemand"] == pytest.approx(50.0)
    assert outputs["HeatingDemand"] == 0.0
    assert outputs["DamperCommand"] == pytest.approx(50.0)
    assert outputs["ValveCommand"] == 0.0


def test_graph_rejects_type_mismatch() -> None:
    with pytest.raises(ValidationError, match="type mismatch"):
        ControlGraph(
            name="BadGraph",
            blocks=[
                Block(
                    id="Bool", kind=BlockKind.BOOLEAN_CONST, label="Boolean", config={"value": True}
                ),
                Block(id="Number", kind=BlockKind.NUMERIC_OUTPUT, label="Number"),
            ],
            links=[Link(source="Bool", target="Number", target_slot="in")],
        )


def test_graph_rejects_multiple_drivers() -> None:
    with pytest.raises(ValidationError, match="multiple drivers"):
        ControlGraph(
            name="BadGraph",
            blocks=[
                Block(id="One", kind=BlockKind.NUMERIC_CONST, label="One", config={"value": 1}),
                Block(id="Two", kind=BlockKind.NUMERIC_CONST, label="Two", config={"value": 2}),
                Block(id="Output", kind=BlockKind.NUMERIC_OUTPUT, label="Output"),
            ],
            links=[
                Link(source="One", target="Output", target_slot="in"),
                Link(source="Two", target="Output", target_slot="in"),
            ],
        )


def test_job_rejects_command_mapped_to_read_only_bacnet_object() -> None:
    with pytest.raises(ValidationError, match="read-only"):
        JobSpec(
            name="Unsafe map",
            site="Test",
            equipment_name="VAV_1",
            points=[
                PointSpec(
                    name="DamperCommand",
                    label="Damper",
                    data_type=DataType.NUMERIC,
                    role=PointRole.COMMAND,
                    bacnet_object="analog-input,1",
                )
            ],
            bacnet_scan=BacnetScan(
                source="fixture",
                devices=[
                    BacnetDeviceSpec(
                        device_instance=1,
                        address="192.0.2.1",
                        name="Controller",
                        objects=[
                            BacnetObjectSpec(
                                object_id="analog-input,1",
                                name="Sensor",
                                data_type=DataType.NUMERIC,
                                writable=False,
                            )
                        ],
                    )
                ],
            ),
        )
