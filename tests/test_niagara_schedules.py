import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

from bactalk.compiler import NiagaraCompiler
from bactalk.demo import demo_job
from bactalk.domain import DeliverableRequirements, ScheduleRequirement, WeeklySchedulePeriod
from bactalk.sequences.g36_vav import build_g36_vav_reheat


def _xml(path: Path) -> bytes:
    with zipfile.ZipFile(path) as archive:
        return archive.read("file.xml")


def test_boolean_weekly_schedule_is_compiled_and_linked_into_bog(tmp_path: Path) -> None:
    job = demo_job()
    graph = build_g36_vav_reheat(job)

    destination = NiagaraCompiler().compile(
        graph,
        tmp_path / "scheduled-vav.bog",
        deliverables=job.deliverables,
    )
    xml = _xml(destination)

    assert b"sch:BooleanSchedule" in xml
    assert b'n="OccupancySchedule"' in xml
    assert b'v="07:00:00.000"' in xml
    assert b'v="18:00:00.000"' in xml
    root = ElementTree.fromstring(xml)
    components = {element.attrib.get("n"): element for element in root.iter("p")}
    schedule_handle = components["OccupancySchedule"].attrib["h"]
    link = next(child for child in components["Occupied"] if child.attrib.get("t") == "b:Link")
    slots = {child.attrib["n"]: child.attrib.get("v") for child in link}
    assert slots["sourceOrd"] == f"h:{schedule_handle}"
    assert slots["sourceSlotName"] == "out"
    assert slots["targetSlotName"] == "in16"


def test_numeric_schedule_and_multiple_daily_periods_compile(tmp_path: Path) -> None:
    job = demo_job()
    graph = build_g36_vav_reheat(job)
    requirements = DeliverableRequirements(
        schedules=[
            ScheduleRequirement(
                id="CoolingSetpointSchedule",
                output_point="CoolingSetpoint",
                timezone="America/New_York",
                default_value=78.0,
                weekly_periods=[
                    WeeklySchedulePeriod(day="monday", start="06:00", end="08:00", value=72.0),
                    WeeklySchedulePeriod(day="monday", start="09:00", end="18:00", value=74.0),
                ],
            )
        ]
    )

    destination = NiagaraCompiler().compile(
        graph,
        tmp_path / "numeric-schedule.bog",
        deliverables=requirements,
    )
    xml = _xml(destination)

    assert b"sch:NumericSchedule" in xml
    assert b'n="time1"' in xml
    assert b'v="72.0"' in xml
    assert b'v="74.0"' in xml


def test_unqualified_holiday_calendar_lowering_fails_closed(tmp_path: Path) -> None:
    job = demo_job()
    graph = build_g36_vav_reheat(job)
    schedule = job.deliverables.schedules[0].model_copy(update={"holiday_calendar": "US_Holidays"})
    requirements = DeliverableRequirements(schedules=[schedule])

    with pytest.raises(ValueError, match="special-event lowering is not qualified"):
        NiagaraCompiler().compile(
            graph,
            tmp_path / "holiday-schedule.bog",
            deliverables=requirements,
        )
