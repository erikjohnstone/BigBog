"""Generate the known-bad ``.bog`` fixtures for the static validator (N1).

Each fixture under ``tests/fixtures/native-bog/bad/`` is the compiled standard
VAV demo with exactly one defect introduced, named after the rule it must trip.
``tests/test_native_bog_validator.py`` asserts that every fixture fails on its
rule and that the untouched compilation passes.

Usage::

    PYTHONPATH=src .venv/bin/python scripts/make_native_bog_fixtures.py
"""

from __future__ import annotations

import io
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from xml.etree import ElementTree

from bactalk.agent import SequencePackPlanner
from bactalk.compiler import NiagaraCompiler
from bactalk.demo import standard_vav_demo_job

ROOT = Path(__file__).resolve().parents[1]
BAD = ROOT / "tests" / "fixtures" / "native-bog" / "bad"

Mutation = Callable[[ElementTree.Element], None]


def _compile_base() -> bytes:
    job = standard_vav_demo_job()
    graph = SequencePackPlanner().plan(job)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{graph.name}.bog"
        NiagaraCompiler().compile(
            graph,
            path,
            deliverables=job.deliverables,
            units={point.name: point.units for point in job.points},
        )
        return path.read_bytes()


def _xml(content: bytes) -> ElementTree.Element:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return ElementTree.fromstring(archive.read("file.xml"))


def _archive(root: ElementTree.Element) -> bytes:
    rendered = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ElementTree.tostring(
        root, encoding="utf-8"
    )
    return _archive_bytes(rendered)


def _archive_bytes(xml: bytes, name: str = "file.xml") -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, xml)
    return output.getvalue()


def _components(root: ElementTree.Element) -> list[ElementTree.Element]:
    return [element for element in root.iter("p") if element.get("h") is not None]


def _first(root: ElementTree.Element, type_name: str) -> ElementTree.Element:
    for element in root.iter("p"):
        if (element.get("t") or "").endswith(f":{type_name}"):
            return element
    raise LookupError(type_name)


def _links(root: ElementTree.Element) -> list[tuple[ElementTree.Element, ElementTree.Element]]:
    found = []
    for parent in root.iter("p"):
        for child in parent:
            if child.tag == "p" and (child.get("t") or "").endswith(":Link"):
                found.append((parent, child))
    return found


def _link_field(link: ElementTree.Element, name: str) -> ElementTree.Element:
    for child in link:
        if child.get("n") == name:
            return child
    raise LookupError(name)


def _first_facets(root: ElementTree.Element) -> ElementTree.Element:
    for element in root.iter("p"):
        if element.get("n") == "facets" and element.get("v", "").startswith("units="):
            return element
    raise LookupError("facets")


# --- one mutation per rule --------------------------------------------------


def module_declared(root: ElementTree.Element) -> None:
    _first(root, "NumericWritable").set("t", "zz:NumericWritable")


def module_consistent(root: ElementTree.Element) -> None:
    # Redeclare the control symbol to another module on a later component.
    writables = [
        element
        for element in root.iter("p")
        if (element.get("t") or "").endswith(":NumericWritable")
    ]
    writables[-1].set("m", "control=kitControl")


def type_known(root: ElementTree.Element) -> None:
    _first(root, "NumericWritable").set("t", "control:NumericWritableDeluxe")


def handle_well_formed(root: ElementTree.Element) -> None:
    _components(root)[0].set("h", "zz")


def handle_unique(root: ElementTree.Element) -> None:
    components = _components(root)
    components[1].set("h", components[0].get("h", "1"))


def link_fields(root: ElementTree.Element) -> None:
    _, link = _links(root)[0]
    link.remove(_link_field(link, "targetSlotName"))


def link_source_resolves(root: ElementTree.Element) -> None:
    _, link = _links(root)[0]
    _link_field(link, "sourceOrd").set("v", "h:fffff")


def link_source_slot(root: ElementTree.Element) -> None:
    _, link = _links(root)[0]
    _link_field(link, "sourceSlotName").set("v", "outNope")


def link_target_slot(root: ElementTree.Element) -> None:
    _, link = _links(root)[0]
    _link_field(link, "targetSlotName").set("v", "inNope")


def link_double_driven(root: ElementTree.Element) -> None:
    parent, link = _links(root)[0]
    duplicate = ElementTree.fromstring(ElementTree.tostring(link))
    duplicate.set("n", (link.get("n") or "Link") + "Dup")
    parent.append(duplicate)


def link_kind_match(root: ElementTree.Element) -> None:
    # Drive a numeric writable's priority input from a boolean writable's out.
    boolean_source = _first(root, "BooleanWritable")
    for parent, link in _links(root):
        if (parent.get("t") or "").endswith(":NumericWritable") and _link_field(
            link, "targetSlotName"
        ).get("v") == "in16":
            _link_field(link, "sourceOrd").set("v", f"h:{boolean_source.get('h')}")
            _link_field(link, "sourceSlotName").set("v", "out")
            return
    raise LookupError("a link into a NumericWritable in16")


def facets_parse(root: ElementTree.Element) -> None:
    _first_facets(root).set("v", "units=u:fahrenheit;°F;(K);|precision")


def facets_unit_known(root: ElementTree.Element) -> None:
    _first_facets(root).set("v", "units=u:parsecs;pc;(m);*3.0857e16;|precision=i:1")


MUTATIONS: dict[str, Mutation] = {
    "module.declared": module_declared,
    "module.consistent": module_consistent,
    "type.known": type_known,
    "handle.well_formed": handle_well_formed,
    "handle.unique": handle_unique,
    "link.fields": link_fields,
    "link.source_resolves": link_source_resolves,
    "link.source_slot": link_source_slot,
    "link.target_slot": link_target_slot,
    "link.double_driven": link_double_driven,
    "link.kind_match": link_kind_match,
    "facets.parse": facets_parse,
    "facets.unit_known": facets_unit_known,
}


def main() -> None:
    base = _compile_base()
    BAD.mkdir(parents=True, exist_ok=True)
    for stale in BAD.glob("*.bog"):
        stale.unlink()
    for rule, mutate in MUTATIONS.items():
        root = _xml(base)
        mutate(root)
        (BAD / f"{rule}.bog").write_bytes(_archive(root))
    # Rules that break the archive before any XML rule runs.
    (BAD / "archive.structure.bog").write_bytes(_archive_bytes(b"<x/>", name="other.xml"))
    (BAD / "xml.well_formed.bog").write_bytes(
        _archive_bytes(b"<bajaObjectGraph><p></bajaObjectGraph>")
    )
    (BAD / "xml.root.bog").write_bytes(_archive_bytes(b'<notBaja version="4.0"/>'))
    print(f"wrote {len(list(BAD.glob('*.bog')))} fixtures to {BAD}")


if __name__ == "__main__":
    main()
