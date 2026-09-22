"""A small ``.bog`` builder for unit tests and the calibration kit (N7).

It writes the same XML shape the native emitter does, so a hand-built file
exercises exactly the loader path a real export takes.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree

MODULES = (
    "b=baja c=control kitControl=kitControl bactalkG36=bactalkG36 sch=schedule history=history"
)


@dataclass(frozen=True)
class Prop:
    name: str
    type: str | None = None
    value: str | None = None
    flags: str | None = None
    children: tuple[Prop, ...] = ()


def status_numeric(name: str, value: float, status: str | None = None) -> Prop:
    children = [Prop("value", None, _num(value))]
    if status:
        children.append(Prop("status", None, status))
    return Prop(name, "b:StatusNumeric", None, None, tuple(children))


def status_boolean(name: str, value: bool, status: str | None = None) -> Prop:
    children = [Prop("value", None, "true" if value else "false")]
    if status:
        children.append(Prop("status", None, status))
    return Prop(name, "b:StatusBoolean", None, None, tuple(children))


def rel_time(name: str, seconds: float) -> Prop:
    return Prop(name, "b:RelTime", str(round(seconds * 1000)))


def double(name: str, value: float) -> Prop:
    return Prop(name, "b:Double", _num(value))


def boolean(name: str, value: bool) -> Prop:
    return Prop(name, "b:Boolean", "true" if value else "false")


def string(name: str, value: str) -> Prop:
    return Prop(name, "b:String", value)


def raw(name: str, value: str, type_spec: str | None = None) -> Prop:
    return Prop(name, type_spec, value)


def _num(value: float) -> str:
    number = float(value)
    return f"{number:.1f}" if number.is_integer() and abs(number) < 1e15 else repr(number)


@dataclass
class _Node:
    name: str
    type: str
    props: list[Prop]
    handle: int
    folder: str
    children: list[_Node] = field(default_factory=list)


class BogBuilder:
    """``add(folder, name, type, props)`` then ``link(...)`` then ``build()``."""

    def __init__(self, name: str = "Program") -> None:
        self.name = name
        self.folders: dict[str, list[_Node]] = {}
        self.nodes: dict[str, _Node] = {}
        self.links: list[tuple[str, str, str, str]] = []
        self._handle = 1

    def _next(self) -> int:
        self._handle += 1
        return self._handle

    def add(
        self,
        folder: str,
        name: str,
        type_spec: str,
        props: list[Prop] | None = None,
        *,
        parent: str | None = None,
    ) -> str:
        """Add a component and return its key ``folder/name``.

        ``parent`` nests it under another component instead of the folder.
        """

        key = f"{folder}/{name}"
        if key in self.nodes:
            raise ValueError(f"duplicate component {key}")
        node = _Node(name, type_spec, list(props or []), self._next(), folder)
        self.nodes[key] = node
        if parent is not None:
            self.nodes[parent].children.append(node)
        else:
            self.folders.setdefault(folder, []).append(node)
        return key

    def link(self, source: str, source_slot: str, target: str, target_slot: str) -> None:
        for key in (source, target):
            if key not in self.nodes:
                raise KeyError(key)
        self.links.append((source, source_slot, target, target_slot))

    def build(self) -> bytes:
        root = ElementTree.Element(
            "bajaObjectGraph",
            {"version": "4.0", "reversibleEncodingKeySource": "none", "FIPSEnabled": "false"},
        )
        top = ElementTree.SubElement(root, "p", {"m": MODULES, "t": "b:UnrestrictedFolder"})
        program = ElementTree.SubElement(top, "p", {"n": self.name, "h": "1", "t": "b:Folder"})
        by_target: dict[str, list[tuple[str, str, str, str]]] = {}
        for link in self.links:
            by_target.setdefault(link[2], []).append(link)
        handle = self._handle
        for folder, nodes in self.folders.items():
            handle += 1
            element = ElementTree.SubElement(
                program, "p", {"n": folder, "h": format(handle, "x"), "t": "b:Folder"}
            )
            for node in nodes:
                self._render(element, node, by_target)
        ElementTree.indent(root, space=" ")
        xml = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ElementTree.tostring(
            root, encoding="utf-8"
        )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("file.xml", xml)
        return buffer.getvalue()

    def _render(self, parent: ElementTree.Element, node: _Node, by_target: dict) -> None:
        element = ElementTree.SubElement(
            parent, "p", {"n": node.name, "h": format(node.handle, "x"), "t": node.type}
        )
        for prop in node.props:
            _render_prop(element, prop)
        for child in node.children:
            self._render(element, child, by_target)
        key = f"{node.folder}/{node.name}"
        for index, (source, source_slot, _, target_slot) in enumerate(by_target.get(key, [])):
            link = ElementTree.SubElement(
                element, "p", {"n": "Link" if index == 0 else f"Link{index}", "t": "b:Link"}
            )
            ElementTree.SubElement(
                link, "p", {"n": "sourceOrd", "v": f"h:{format(self.nodes[source].handle, 'x')}"}
            )
            ElementTree.SubElement(link, "p", {"n": "relationId", "v": "n:dataLink"})
            ElementTree.SubElement(link, "p", {"n": "sourceSlotName", "v": source_slot})
            ElementTree.SubElement(link, "p", {"n": "targetSlotName", "v": target_slot})


def _render_prop(parent: ElementTree.Element, prop: Prop) -> None:
    attributes = {"n": prop.name}
    if prop.flags:
        attributes["f"] = prop.flags
    if prop.type:
        attributes["t"] = prop.type
    if prop.value is not None:
        attributes["v"] = prop.value
    element = ElementTree.SubElement(parent, "p", attributes)
    for child in prop.children:
        _render_prop(element, child)


__all__ = [
    "BogBuilder",
    "Prop",
    "boolean",
    "double",
    "raw",
    "rel_time",
    "status_boolean",
    "status_numeric",
    "string",
]
