"""Cross-equipment request signals from the Guideline 36 request definitions (N8 step 5).

G36 wires equipment together with *requests*: each zone sends supply-temperature and
static-pressure reset requests to its air handler, which sums them; each air handler
sends chilled- and hot-water plant requests to its plants. The port names below are
LBNL's. ``request_signals`` turns a project's ``feeds`` and ``serves`` relationships
into the typed bindings and aggregations the project model already validates, the
simulator executes and the station assembler builds as kitControl chains.
"""

from __future__ import annotations

from dataclasses import dataclass

from bactalk.domain import DataType, JobSpec, PointRole
from bactalk.projects import (
    ProjectSignalAggregation,
    ProjectSignalBinding,
    ProjectSignalSource,
    ProjectSpec,
)


@dataclass(frozen=True)
class RequestRule:
    relation: str
    """The relationship that carries the request, read source → target."""

    from_role: str
    """Which end of the relationship sends: ``source`` or ``target``."""

    source_point: str
    target_point: str
    reduce: str
    section: str


# Zone → air handler (the AHU "feeds" the zone; the requests flow back up).
_ZONE_TO_AHU = (
    RequestRule("feeds", "target", "yZonTemResReq", "uZonTemResReq", "sum", "G36 §5.6.8.1"),
    RequestRule("feeds", "target", "yZonPreResReq", "uZonPreResReq", "sum", "G36 §5.6.8.2"),
)
# Air handler (or zone) → plant (the plant "serves" the equipment).
_TO_PLANT = (
    RequestRule("serves", "target", "yChiWatResReq", "uChiWatResReq", "sum", "G36 §5.16.14"),
    RequestRule("serves", "target", "yChiPlaReq", "uChiPlaReq", "sum", "G36 §5.16.14"),
    RequestRule("serves", "target", "yHotWatResReq", "uHotWatResReq", "sum", "G36 §5.16.14"),
    RequestRule("serves", "target", "yHotWatPlaReq", "uHotWatPlaReq", "sum", "G36 §5.16.14"),
    RequestRule("serves", "target", "yHeaValResReq", "uHotWatResReq", "sum", "G36 §5.6.8.3"),
)
REQUEST_RULES: tuple[RequestRule, ...] = _ZONE_TO_AHU + _TO_PLANT


def _point(job: JobSpec, name: str):
    return next((p for p in job.points if p.name == name), None)


def request_signals(
    project: ProjectSpec,
) -> tuple[list[ProjectSignalBinding], list[ProjectSignalAggregation]]:
    """Bindings (one sender) and aggregations (several senders) for every request the
    project's relationships and point names support. Nothing is invented: a rule
    applies only when the sender exposes the output and the receiver the input with
    matching types, and a receiver input that is already bound is left alone."""

    jobs = {job.equipment_name: job for job in project.equipment}
    bound = {(b.target_equipment, b.target_point) for b in project.signal_bindings} | {
        (a.target_equipment, a.target_point) for a in project.signal_aggregations
    }
    senders: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
    for rule in REQUEST_RULES:
        for relation in project.relationships:
            if relation.relation != rule.relation:
                continue
            sender, receiver = (
                (relation.target, relation.source)
                if rule.from_role == "target"
                else (relation.source, relation.target)
            )
            sender_job, receiver_job = jobs.get(sender), jobs.get(receiver)
            if sender_job is None or receiver_job is None:
                continue
            out = _point(sender_job, rule.source_point)
            inp = _point(receiver_job, rule.target_point)
            if out is None or inp is None:
                continue
            if out.role not in {PointRole.COMMAND, PointRole.ALARM}:
                continue
            if inp.role not in {PointRole.SENSOR, PointRole.SETPOINT, PointRole.STATUS}:
                continue
            if out.data_type != inp.data_type or (receiver, rule.target_point) in bound:
                continue
            reduce = "any" if inp.data_type == DataType.BOOLEAN else rule.reduce
            senders.setdefault((receiver, rule.target_point, reduce), []).append(
                (sender, rule.source_point)
            )
    bindings: list[ProjectSignalBinding] = []
    aggregations: list[ProjectSignalAggregation] = []
    for (receiver, target_point, reduce), sources in sorted(senders.items()):
        unique = sorted(set(sources))
        if len(unique) == 1:
            bindings.append(
                ProjectSignalBinding(
                    source_equipment=unique[0][0],
                    source_point=unique[0][1],
                    target_equipment=receiver,
                    target_point=target_point,
                )
            )
        else:
            aggregations.append(
                ProjectSignalAggregation(
                    target_equipment=receiver,
                    target_point=target_point,
                    sources=[ProjectSignalSource(equipment=e, point=p) for e, p in unique],
                    reduce=reduce,  # type: ignore[arg-type]
                )
            )
    return bindings, aggregations


def with_request_signals(project: ProjectSpec) -> ProjectSpec:
    """The project with every generated request signal added."""

    bindings, aggregations = request_signals(project)
    return project.model_copy(
        update={
            "signal_bindings": [*project.signal_bindings, *bindings],
            "signal_aggregations": [*project.signal_aggregations, *aggregations],
        }
    )


__all__ = ["REQUEST_RULES", "RequestRule", "request_signals", "with_request_signals"]
