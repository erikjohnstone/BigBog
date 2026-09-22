"""Catalogue of sequences built under the Test Generation Protocol (Tiers 3–5).

An item is one equipment type with one graph builder; a configuration is one set of
declared options for it (configurable, not forked). Each configuration retains its
own requirement set (the options resolved into plain language and numbers) and its
own adequacy artifact, and is one row of the coverage report and one entry of
``/api/protocol/sequences``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from bactalk.domain import ControlGraph, DataType, JobSpec, PointRole, PointSpec, SequenceSpec
from bactalk.protocol.requirements import RequirementSet
from bactalk.protocol.test_author import TestPlan, generate_test_plan

Builder = Callable[[RequirementSet, list[PointSpec], Mapping[str, Any]], ControlGraph]


@dataclass(frozen=True)
class ItemConfiguration:
    id: str
    label: str
    options: dict[str, Any] = field(default_factory=dict)

    @property
    def requirements_file(self) -> str:
        return "requirements.json" if self.id == "default" else f"requirements-{self.id}.json"

    @property
    def adequacy_file(self) -> str:
        return "adequacy.json" if self.id == "default" else f"adequacy-{self.id}.json"


DEFAULT_CONFIGURATION = ItemConfiguration(id="default", label="default")


@dataclass(frozen=True)
class ProtocolItem:
    id: str
    tier: int
    label: str
    package: str
    family: str
    equipment_name: str
    builder: Builder
    configurations: tuple[ItemConfiguration, ...] = (DEFAULT_CONFIGURATION,)

    def configuration(self, config_id: str) -> ItemConfiguration:
        for configuration in self.configurations:
            if configuration.id == config_id:
                return configuration
        raise KeyError(config_id)


@dataclass(frozen=True)
class Row:
    """One (item, configuration) pair: the unit of retention, grading and approval."""

    item: ProtocolItem
    configuration: ItemConfiguration

    @property
    def requirements_path(self) -> Path:
        return Path(
            str(resources.files(self.item.package).joinpath(self.configuration.requirements_file))
        )

    @property
    def adequacy_path(self) -> Path:
        return Path(
            str(resources.files(self.item.package).joinpath(self.configuration.adequacy_file))
        )

    def requirement_set(self) -> RequirementSet:
        return RequirementSet.model_validate(
            json.loads(self.requirements_path.read_text(encoding="utf-8"))
        )

    def adequacy_artifact(self) -> dict[str, Any] | None:
        path = self.adequacy_path
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


_ITEMS: dict[str, ProtocolItem] = {}


def register(item: ProtocolItem) -> ProtocolItem:
    if item.id in _ITEMS and _ITEMS[item.id] is not item:
        raise ValueError(f"protocol item {item.id} registered twice")
    _ITEMS[item.id] = item
    return item


def _load_libraries() -> None:
    # Library packages register their items on import; importing them here keeps
    # the catalogue complete for whoever asks first.
    import bactalk.library_tier3  # noqa: F401
    import bactalk.library_tier4  # noqa: F401
    import bactalk.library_tier5_fixture  # noqa: F401


def items() -> list[ProtocolItem]:
    _load_libraries()
    return sorted(_ITEMS.values(), key=lambda item: (item.tier, item.id))


def rows() -> list[Row]:
    return [Row(item, configuration) for item in items() for configuration in item.configurations]


def row(sequence_id: str) -> Row:
    """The row whose retained requirement set carries ``sequence_id``."""

    for candidate in rows():
        if candidate.requirement_set().sequence_id == sequence_id:
            return candidate
    raise KeyError(sequence_id)


def sequence_ids() -> list[str]:
    return [candidate.requirement_set().sequence_id for candidate in rows()]


def points_for(requirements: RequirementSet) -> list[PointSpec]:
    points: list[PointSpec] = []
    for point in requirements.points:
        if point.direction == "input":
            role = PointRole.STATUS if point.data_type == "boolean" else PointRole.SENSOR
        else:
            role = PointRole.ALARM if point.name.endswith("Ala") else PointRole.COMMAND
        points.append(
            PointSpec(
                name=point.name,
                label=point.label,
                data_type=DataType(point.data_type),
                role=role,
                units=point.unit,
                default=point.nominal,
                required=True,
                brick_class=point.brick_class,
            )
        )
    return points


def sequence_for(candidate: Row, requirements: RequirementSet) -> SequenceSpec:
    return SequenceSpec(
        family=candidate.item.family,
        version=f"{requirements.title} · requirements {requirements.version}",
        execution_profile="host_tick_v1",
        parameters={
            "protocol": {
                "sequence_id": requirements.sequence_id,
                "requirements_digest": requirements.digest(),
                "tier": requirements.tier,
                "label": candidate.item.label,
                "item": candidate.item.id,
                "configuration": candidate.configuration.id,
                "options": dict(candidate.configuration.options),
            }
        },
    )


def protocol_job(sequence_id: str, *, plan: TestPlan | None = None) -> JobSpec:
    """The job for one row: points and graph from the logic author (with the
    configuration's options), acceptance tests from the test author's plan."""

    candidate = row(sequence_id)
    requirements = candidate.requirement_set()
    points = points_for(requirements)
    graph = candidate.item.builder(requirements, points, candidate.configuration.options)
    if plan is None:
        plan = generate_test_plan(requirements)
    return JobSpec(
        name=requirements.title,
        site="BACTalk protocol library",
        equipment_name=candidate.item.equipment_name,
        equipment_brick_class=requirements.equipment_brick_class,
        sequence=sequence_for(candidate, requirements),
        points=points,
        control_graph=graph,
        acceptance_tests=plan.cases(),
    )


__all__ = [
    "DEFAULT_CONFIGURATION",
    "Builder",
    "ItemConfiguration",
    "ProtocolItem",
    "Row",
    "items",
    "points_for",
    "protocol_job",
    "register",
    "row",
    "rows",
    "sequence_for",
    "sequence_ids",
]
