"""N6 contract: the Shadow Runtime loader reads an exported ``.bog`` and nothing else."""

from __future__ import annotations

import io
import zipfile

import pytest

from bactalk.library_demo import lbnl_multizone_ahu_demo_job, lbnl_vav_reheat_demo_job
from bactalk.niagara.emit import emit_bog
from bactalk.niagara.shadow import REGISTRY, ShadowLoadError, known_types, load_program
from bactalk.niagara.shadow.builder import BogBuilder, rel_time, status_numeric
from bactalk.niagara.shadow.status import Status, parse_status

pytestmark = [pytest.mark.minimal, pytest.mark.native_bog]

TIER_ONE = [lbnl_vav_reheat_demo_job, lbnl_multizone_ahu_demo_job]


@pytest.mark.parametrize("build", TIER_ONE)
def test_tier_one_exports_load_with_every_link_resolved(build) -> None:
    job = build()
    result = emit_bog(job.control_graph, points=job.points)
    program = load_program(result.content, known_types=known_types())
    assert not program.unknown_types
    assert not program.external_links
    assert len(program.links) == result.report.link_count
    executable = [node for node in program.components if node.type in REGISTRY]
    assert len(executable) == result.report.component_count
    # Handles and paths both resolve to the same node.
    first = program.links[0]
    assert program.by_handle[first.source.handle.lower()] is first.source
    assert program.find(first.target.path) is first.target


def test_unknown_types_are_rejected_with_their_paths() -> None:
    builder = BogBuilder("P")
    builder.add("Logic", "mystery", "kitControl:Ramp", [])
    with pytest.raises(ShadowLoadError, match=r"kitControl:Ramp at /P/Logic/mystery"):
        load_program(builder.build(), known_types=known_types())
    program = load_program(builder.build(), known_types=known_types(), allow_unknown=True)
    assert program.unknown_types == {"kitControl:Ramp": ["/P/Logic/mystery"]}


def test_module_symbols_resolve_in_document_order_and_customary_defaults_apply() -> None:
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<bajaObjectGraph version="4.0">
 <p t="b:UnrestrictedFolder" m="b=baja">
  <p n="P" h="1" t="b:Folder">
   <p n="a" h="2" t="kc:Add" m="kc=kitControl"/>
   <p n="b" h="3" t="kc:Not"/>
   <p n="c" h="4" t="c:NumericWritable"/>
  </p>
 </p>
</bajaObjectGraph>"""
    program = load_program(_zip(xml), known_types=known_types())
    assert [node.type for node in program.components[1:]] == [
        "baja:Folder",
        "kitControl:Add",
        "kitControl:Not",
        "control:NumericWritable",
    ]
    redeclared = xml.replace(
        b'<p n="b" h="3" t="kc:Not"/>', b'<p n="b" h="3" t="kc:Not" m="kc=kitPx"/>'
    )
    with pytest.raises(ShadowLoadError, match="redeclared"):
        load_program(_zip(redeclared), known_types=known_types())


def test_links_resolve_by_handle_and_by_slot_path_and_external_sources_are_refused() -> None:
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<bajaObjectGraph version="4.0">
 <p t="b:UnrestrictedFolder" m="b=baja c=control kitControl=kitControl">
  <p n="P" h="1" t="b:Folder">
   <p n="src" h="2" t="c:NumericWritable"/>
   <p n="byHandle" h="3" t="kitControl:Add">
    <p n="Link" t="b:Link"><p n="sourceOrd" v="h:2"/><p n="sourceSlotName" v="out"/>
     <p n="targetSlotName" v="inA"/></p>
   </p>
   <p n="byPath" h="4" t="kitControl:Add">
    <p n="Link" t="b:Link"><p n="sourceOrd" v="slot:/P/src"/><p n="sourceSlotName" v="out"/>
     <p n="targetSlotName" v="inB"/></p>
   </p>
   <p n="external" h="5" t="kitControl:Add">
    <p n="Link" t="b:Link">
     <p n="sourceOrd" v="station:|slot:/Drivers/BacnetNetwork/VAV/points/ZN_T"/>
     <p n="sourceSlotName" v="out"/><p n="targetSlotName" v="inA"/></p>
   </p>
  </p>
 </p>
</bajaObjectGraph>"""
    with pytest.raises(ShadowLoadError, match="is not in the file"):
        load_program(_zip(xml), known_types=known_types())
    program = load_program(_zip(xml), known_types=known_types(), external_links="ignore")
    resolved = {(link.target.name, link.target_slot): link.source.name for link in program.links}
    assert resolved == {("byHandle", "inA"): "src", ("byPath", "inB"): "src"}
    assert [node.name for node, _ in program.external_links] == ["external"]


def test_properties_keep_types_values_flags_and_status_children() -> None:
    builder = BogBuilder("P")
    builder.add("Logic", "delay", "kitControl:BooleanDelay", [rel_time("onDelay", 30.0)])
    builder.add("Logic", "k", "kitControl:NumericConst", [status_numeric("out", 2.5, "{fault}")])
    program = load_program(builder.build(), known_types=known_types())
    delay = program.find("/P/Logic/delay")
    assert delay.prop("onDelay").type == "baja:RelTime"
    assert delay.seconds("onDelay", 0.0) == 30.0
    const = program.find("/P/Logic/k").prop("out").status_value(numeric=True)
    assert const is not None and const.value == 2.5 and const.status == Status.FAULT
    assert parse_status("{null,stale}") == Status.NULL | Status.STALE
    assert parse_status("{ok}") == Status.OK


def test_malformed_archives_are_refused() -> None:
    with pytest.raises(ShadowLoadError, match="not a zip"):
        load_program(b"nope", known_types=known_types())
    with pytest.raises(ShadowLoadError, match="no file.xml"):
        load_program(_zip(b"<x/>", name="other.xml"), known_types=known_types())
    with pytest.raises(ShadowLoadError, match="DTD"):
        load_program(
            _zip(b'<!DOCTYPE x [<!ENTITY e "x">]><bajaObjectGraph/>'), known_types=known_types()
        )
    with pytest.raises(ShadowLoadError, match="not bajaObjectGraph"):
        load_program(_zip(b"<other/>"), known_types=known_types())


def _zip(xml: bytes, name: str = "file.xml") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, xml)
    return buffer.getvalue()
