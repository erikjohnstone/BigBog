from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bactalk.demo import demo_job
from bactalk.domain import ControlGraph
from bactalk.sequences import build_g36_vav_reheat
from bactalk.simulator import GraphInterpreter, run_acceptance_suite

INTERPRETER = GraphInterpreter(build_g36_vav_reheat(demo_job()))


def _reference(
    zone_temp: float,
    heating_setpoint: float,
    cooling_setpoint: float,
    occupied: bool,
) -> dict[str, float | bool]:
    cooling = min(100.0, max(0.0, (zone_temp - cooling_setpoint) * 100.0 / 3.0))
    heating = min(100.0, max(0.0, (heating_setpoint - zone_temp) * 100.0 / 3.0))
    return {
        "CoolingDemand": cooling if occupied else 0.0,
        "HeatingDemand": heating if occupied else 0.0,
        "DamperCommand": max(20.0, cooling) if occupied else 0.0,
        "ValveCommand": heating if occupied else 0.0,
        "HighZoneTempAlarm": occupied and zone_temp > 80.0,
    }


@settings(max_examples=400, deadline=None)
@given(
    zone_temp=st.floats(min_value=-40, max_value=140, allow_nan=False, allow_infinity=False),
    heating_setpoint=st.floats(min_value=40, max_value=90, allow_nan=False, allow_infinity=False),
    deadband=st.floats(min_value=0, max_value=15, allow_nan=False, allow_infinity=False),
    occupied=st.booleans(),
)
def test_graph_matches_independent_reference_over_operating_envelope(
    zone_temp: float,
    heating_setpoint: float,
    deadband: float,
    occupied: bool,
) -> None:
    cooling_setpoint = heating_setpoint + deadband
    actual = INTERPRETER.evaluate(
        {
            "ZoneTemp": zone_temp,
            "HeatingSetpoint": heating_setpoint,
            "CoolingSetpoint": cooling_setpoint,
            "Occupied": occupied,
        }
    )
    expected = _reference(zone_temp, heating_setpoint, cooling_setpoint, occupied)

    for output, expected_value in expected.items():
        if isinstance(expected_value, bool):
            assert actual[output] is expected_value
        else:
            assert float(actual[output]) == pytest.approx(expected_value)
            assert 0.0 <= float(actual[output]) <= 100.0
    assert not (float(actual["CoolingDemand"]) > 0 and float(actual["HeatingDemand"]) > 0)


def _mutate_link(graph: ControlGraph, target: str, slot: str, source: str) -> ControlGraph:
    value = graph.model_dump(mode="python")
    matching = [
        link for link in value["links"] if link["target"] == target and link["target_slot"] == slot
    ]
    assert len(matching) == 1
    matching[0]["source"] = source
    return ControlGraph.model_validate(value)


@pytest.mark.parametrize(
    ("target", "slot", "source"),
    [
        ("HeatingError", "a", "ZoneTemp"),
        ("CoolingClamped", "b", "CoolingNonNegative"),
        ("DamperEnable", "selector", "ZoneTempHigh"),
        ("OccupiedHighTemp", "a", "Occupied"),
        ("OccupiedCooling", "selector", "ZoneTempHigh"),
    ],
)
def test_acceptance_suite_kills_meaningful_controls_mutations(
    target: str,
    slot: str,
    source: str,
) -> None:
    graph = build_g36_vav_reheat(demo_job())
    mutant = _mutate_link(graph, target, slot, source)

    assert run_acceptance_suite(mutant).passed is False
