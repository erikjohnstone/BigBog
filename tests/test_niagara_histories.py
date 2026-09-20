import math
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

from bactalk.compiler import NiagaraCompiler
from bactalk.demo import demo_job
from bactalk.domain import DeliverableRequirements, HistoryRequirement
from bactalk.sequences.g36_vav import build_g36_vav_reheat


def _root(path: Path) -> ElementTree.Element:
    with zipfile.ZipFile(path) as archive:
        return ElementTree.fromstring(archive.read("file.xml"))


def _named(root: ElementTree.Element, name: str) -> ElementTree.Element:
    return next(element for element in root.iter("p") if element.attrib.get("n") == name)


def test_numeric_fixed_interval_history_is_embedded_with_retention_capacity(
    tmp_path: Path,
) -> None:
    job = demo_job()
    graph = build_g36_vav_reheat(job)

    destination = NiagaraCompiler().compile(
        graph,
        tmp_path / "history-vav.bog",
        deliverables=job.deliverables,
    )
    root = _root(destination)
    point = _named(root, "ZoneTemp")
    extension = next(
        child for child in point if child.attrib.get("t") == "h:NumericIntervalHistoryExt"
    )
    config = _named(extension, "historyConfig")
    properties = {child.attrib.get("n"): child.attrib for child in config}

    assert extension.attrib["n"] == "NumericInterval"
    assert properties["source"]["v"] == (
        "station:|slot:/Config/Drivers/BACnetNetwork/ExampleCampus/"
        "VAV_12/ZoneTemp/NumericInterval"
    )
    assert properties["sourceHandle"]["v"] == f"h:{extension.attrib['h']}"
    assert properties["interval"]["v"] == "false:300000"
    assert properties["capacity"]["v"] == f"1:{math.ceil(365 * 86_400 / 300)}"
    assert properties["recordType"]["v"] == "history:NumericTrendRecord"


def test_boolean_fixed_interval_history_uses_boolean_extension(tmp_path: Path) -> None:
    job = demo_job()
    graph = build_g36_vav_reheat(job)
    requirements = DeliverableRequirements(
        histories=[
            HistoryRequirement(
                point="Occupied",
                mode="fixed_interval",
                interval_seconds=900,
                retention_days=30,
            )
        ]
    )

    destination = NiagaraCompiler().compile(
        graph,
        tmp_path / "boolean-history.bog",
        deliverables=requirements,
    )
    root = _root(destination)
    point = _named(root, "Occupied")
    extension = next(
        child for child in point if child.attrib.get("t") == "h:BooleanIntervalHistoryExt"
    )
    config = _named(extension, "historyConfig")
    properties = {child.attrib.get("n"): child.attrib for child in config}

    assert extension.attrib["n"] == "BooleanInterval"
    assert properties["recordType"]["v"] == "history:BooleanTrendRecord"
    assert properties["valueFacets"]["v"] == "trueText=s:true|falseText=s:false"


def test_cov_history_remains_uncompiled_until_serialization_is_qualified(tmp_path: Path) -> None:
    job = demo_job()
    graph = build_g36_vav_reheat(job)
    requirements = DeliverableRequirements(
        histories=[
            HistoryRequirement(
                point="ZoneTemp",
                mode="cov",
                cov_tolerance=0.5,
                retention_days=30,
            )
        ]
    )

    destination = NiagaraCompiler().compile(
        graph,
        tmp_path / "cov-history.bog",
        deliverables=requirements,
    )

    with zipfile.ZipFile(destination) as archive:
        xml = archive.read("file.xml")
    assert b"CovHistoryExt" not in xml


def test_history_capacity_above_qualified_integer_limit_fails_closed(tmp_path: Path) -> None:
    job = demo_job()
    graph = build_g36_vav_reheat(job)
    requirements = DeliverableRequirements(
        histories=[
            HistoryRequirement(
                point="ZoneTemp",
                mode="fixed_interval",
                interval_seconds=1,
                retention_days=36_500,
            )
        ]
    )

    with pytest.raises(ValueError, match="above Niagara's qualified integer capacity limit"):
        NiagaraCompiler().compile(
            graph,
            tmp_path / "oversized-history.bog",
            deliverables=requirements,
        )
