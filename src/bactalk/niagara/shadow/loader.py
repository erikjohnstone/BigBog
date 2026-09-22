"""Load an exported ``.bog`` into a component tree (GOAL-NATIVE-BOG.md N6, item 1).

The file is the runtime's only input: the loader reads ``file.xml`` from the
archive, resolves module symbols in document order (Niagara declares ``m=`` on
first use), builds the component tree with every property and link, resolves
link sources by handle (``h:``) or slot path (``slot:/``), and refuses types the
block registry does not know. Nothing here reads BACTalk's IR.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

from bactalk.niagara.shadow.status import Status, StatusValue, parse_status

_FORBIDDEN_XML = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)
_HANDLE = re.compile(r"^[0-9a-fA-F]+$")

LINK_TYPES = frozenset({"baja:Link", "baja:ConversionLink"})
CONTAINER_TYPES = frozenset(
    {"baja:Folder", "baja:UnrestrictedFolder", "baja:Station", "baja:Component"}
)
INERT_TYPES = frozenset({"baja:WsTextBlock"})

# Customary symbols Niagara files rely on without an m= declaration.
DEFAULT_SYMBOLS: Mapping[str, str] = {
    "b": "baja",
    "c": "control",
    "kitControl": "kitControl",
    "sch": "schedule",
    "schedule": "schedule",
    "history": "history",
    "bactalkG36": "bactalkG36",
}


class ShadowLoadError(ValueError):
    """The file cannot be loaded as a runnable program."""


@dataclass
class Property:
    """One ``<p>`` under a component that is a value, not a child component."""

    name: str
    type: str | None
    value: str | None
    flags: str | None = None
    children: dict[str, Property] = field(default_factory=dict)

    def child_value(self, name: str) -> str | None:
        child = self.children.get(name)
        return child.value if child is not None else None

    def status_value(self, *, numeric: bool) -> StatusValue | None:
        """Read a ``StatusNumeric``/``StatusBoolean`` property (``None`` without a value)."""

        raw = self.child_value("value")
        if raw is None:
            raw = self.value
        status = parse_status(self.child_value("status"))
        if raw is None:
            return None if status == Status.OK else StatusValue(0.0 if numeric else False, status)
        return StatusValue(parse_number(raw) if numeric else parse_boolean(raw), status)


@dataclass
class LinkSpec:
    name: str
    source_ord: str
    source_slot: str
    target_slot: str
    order: int
    """Document order over every link in the file."""


@dataclass
class ComponentNode:
    path: str
    name: str
    type: str
    raw_type: str
    handle: str | None
    order: int
    properties: dict[str, Property] = field(default_factory=dict)
    links: list[LinkSpec] = field(default_factory=list)
    children: list[ComponentNode] = field(default_factory=list)
    parent: ComponentNode | None = field(default=None, repr=False)

    @property
    def folder(self) -> str:
        return self.parent.path if self.parent is not None else "/"

    def prop(self, name: str) -> Property | None:
        return self.properties.get(name)

    def number(self, name: str, default: float) -> float:
        prop = self.properties.get(name)
        if prop is None or prop.value is None:
            return default
        return parse_number(prop.value)

    def seconds(self, name: str, default: float) -> float:
        """A ``RelTime`` property in seconds (the file stores milliseconds)."""

        prop = self.properties.get(name)
        if prop is None or prop.value is None:
            return default
        return parse_number(prop.value) / 1000.0

    def flag(self, name: str, default: bool) -> bool:
        prop = self.properties.get(name)
        if prop is None or prop.value is None:
            return default
        return parse_boolean(prop.value)

    def text(self, name: str, default: str) -> str:
        prop = self.properties.get(name)
        if prop is None or prop.value is None:
            return default
        return prop.value


@dataclass(frozen=True)
class ResolvedLink:
    source: ComponentNode
    source_slot: str
    target: ComponentNode
    target_slot: str
    order: int


@dataclass
class Program:
    root: ComponentNode
    components: list[ComponentNode]
    """Every component in document order, the root included."""

    links: list[ResolvedLink]
    by_handle: dict[str, ComponentNode]
    by_path: dict[str, ComponentNode]
    modules: dict[str, str]
    unknown_types: dict[str, list[str]]
    external_links: list[tuple[ComponentNode, LinkSpec]]

    def find(self, path: str) -> ComponentNode:
        node = self.by_path.get(path)
        if node is None:
            raise KeyError(path)
        return node

    def of_type(self, type_name: str) -> list[ComponentNode]:
        return [node for node in self.components if node.type == type_name]


def parse_number(text: str) -> float:
    value = text.strip()
    lowered = value.lower()
    if lowered in {"+inf", "inf", "infinity", "+infinity"}:
        return float("inf")
    if lowered in {"-inf", "-infinity"}:
        return float("-inf")
    if lowered == "nan":
        return float("nan")
    return float(value)


def parse_boolean(text: str) -> bool:
    value = text.strip().lower()
    if value in {"true", "1"}:
        return True
    if value in {"false", "0"}:
        return False
    raise ShadowLoadError(f"not a boolean: {text!r}")


def read_archive(source: Path | bytes) -> bytes:
    content = source.read_bytes() if isinstance(source, Path) else source
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if "file.xml" not in archive.namelist():
                raise ShadowLoadError("archive has no file.xml entry")
            xml = archive.read("file.xml")
    except zipfile.BadZipFile as exc:
        raise ShadowLoadError("not a zip archive") from exc
    if _FORBIDDEN_XML.search(xml):
        raise ShadowLoadError("DTD or entity declarations are refused")
    return xml


def load_program(
    source: Path | bytes,
    *,
    known_types: Collection[str],
    allow_unknown: bool = False,
    external_links: str = "error",
) -> Program:
    """Parse ``source`` into a :class:`Program`.

    ``known_types`` are the executable types (block registry keys). Container and
    inert types are always accepted. Unknown types raise unless ``allow_unknown``;
    link sources outside the file raise unless ``external_links="ignore"``.
    """

    if external_links not in {"error", "ignore"}:
        raise ValueError("external_links must be 'error' or 'ignore'")
    xml = read_archive(source)
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise ShadowLoadError(f"file.xml is not well-formed: {exc}") from exc
    if root.tag != "bajaObjectGraph":
        raise ShadowLoadError(f"root element is {root.tag!r}, not bajaObjectGraph")
    loader = _Loader(set(known_types))
    program = loader.load(root)
    if program.unknown_types and not allow_unknown:
        listing = "; ".join(
            f"{type_name} at {paths[0]}" + (f" (+{len(paths) - 1})" if len(paths) > 1 else "")
            for type_name, paths in sorted(program.unknown_types.items())
        )
        raise ShadowLoadError(f"unknown Niagara types: {listing}")
    if program.external_links and external_links == "error":
        node, link = program.external_links[0]
        raise ShadowLoadError(
            f"link {node.path}/{link.name} source {link.source_ord!r} is not in the file"
            + (
                f" (+{len(program.external_links) - 1} more)"
                if len(program.external_links) > 1
                else ""
            )
        )
    return program


class _Loader:
    def __init__(self, known_types: set[str]) -> None:
        self.known = known_types
        self.modules: dict[str, str] = {}
        self.components: list[ComponentNode] = []
        self.by_handle: dict[str, ComponentNode] = {}
        self.by_path: dict[str, ComponentNode] = {}
        self.unknown: dict[str, list[str]] = {}
        self.link_order = 0
        self.order = 0

    def load(self, root: ElementTree.Element) -> Program:
        tops = [child for child in root if child.tag == "p"]
        if len(tops) != 1:
            raise ShadowLoadError(
                f"bajaObjectGraph must hold exactly one top element, found {len(tops)}"
            )
        top = tops[0]
        self._declare_modules(top)
        top_type = self._resolve(top.get("t") or "baja:UnrestrictedFolder")
        node = ComponentNode(
            path="/",
            name="",
            type=top_type,
            raw_type=top.get("t") or "",
            handle=top.get("h"),
            order=0,
        )
        self._register(node)
        self._walk(top, node)
        links = self._resolve_links()
        external = [
            (node, link)
            for node in self.components
            for link in node.links
            if (node.path, link.name) in self._unresolved
        ]
        return Program(
            root=node,
            components=self.components,
            links=links,
            by_handle=self.by_handle,
            by_path=self.by_path,
            modules=dict(self.modules),
            unknown_types=self.unknown,
            external_links=external,
        )

    # -- modules and types -----------------------------------------------------

    def _declare_modules(self, element: ElementTree.Element) -> None:
        for token in (element.get("m") or "").split():
            symbol, _, module = token.partition("=")
            if not symbol or not module:
                raise ShadowLoadError(f"malformed module declaration {token!r}")
            existing = self.modules.get(symbol)
            if existing is not None and existing != module:
                raise ShadowLoadError(
                    f"symbol {symbol!r} redeclared as {module!r} after {existing!r}"
                )
            self.modules[symbol] = module

    def _resolve(self, raw_type: str) -> str:
        symbol, _, name = raw_type.partition(":")
        if not name:
            raise ShadowLoadError(f"malformed type spec {raw_type!r}")
        module = self.modules.get(symbol) or DEFAULT_SYMBOLS.get(symbol)
        if module is None:
            raise ShadowLoadError(
                f"type {raw_type!r} uses symbol {symbol!r} that no m= attribute declares"
            )
        return f"{module}:{name}"

    # -- tree ------------------------------------------------------------------

    def _register(self, node: ComponentNode) -> None:
        self.components.append(node)
        self.by_path[node.path] = node
        if node.handle is not None:
            if not _HANDLE.fullmatch(node.handle):
                raise ShadowLoadError(f"handle {node.handle!r} at {node.path} is not hexadecimal")
            key = node.handle.lower()
            if key in self.by_handle:
                raise ShadowLoadError(
                    f"handle {node.handle!r} at {node.path} already used by "
                    f"{self.by_handle[key].path}"
                )
            self.by_handle[key] = node

    def _walk(self, element: ElementTree.Element, parent: ComponentNode) -> None:
        for child in element:
            if child.tag != "p":
                continue
            name = child.get("n")
            if name is None:
                raise ShadowLoadError(f"unnamed slot under {parent.path}")
            self._declare_modules(child)
            raw_type = child.get("t")
            resolved = self._resolve(raw_type) if raw_type is not None else None
            handle = child.get("h")
            if resolved in LINK_TYPES:
                parent.links.append(self._link(child, name, parent))
                continue
            is_component = handle is not None or (
                resolved is not None
                and (
                    resolved in self.known or resolved in CONTAINER_TYPES or resolved in INERT_TYPES
                )
            )
            if is_component and resolved is not None:
                self.order += 1
                path = f"{parent.path.rstrip('/')}/{name}"
                node = ComponentNode(
                    path=path,
                    name=name,
                    type=resolved,
                    raw_type=raw_type or "",
                    handle=handle,
                    order=self.order,
                    parent=parent,
                )
                if (
                    resolved not in self.known
                    and resolved not in CONTAINER_TYPES
                    and resolved not in INERT_TYPES
                ):
                    self.unknown.setdefault(resolved, []).append(path)
                parent.children.append(node)
                self._register(node)
                self._walk(child, node)
                continue
            parent.properties[name] = self._property(child, name, resolved)

    def _property(self, element: ElementTree.Element, name: str, resolved: str | None) -> Property:
        prop = Property(name=name, type=resolved, value=element.get("v"), flags=element.get("f"))
        for child in element:
            if child.tag != "p":
                continue
            child_name = child.get("n")
            if child_name is None:
                continue
            self._declare_modules(child)
            child_type = child.get("t")
            prop.children[child_name] = self._property(
                child, child_name, self._resolve(child_type) if child_type else None
            )
        return prop

    def _link(self, element: ElementTree.Element, name: str, parent: ComponentNode) -> LinkSpec:
        fields: dict[str, str] = {}
        for child in element:
            if child.tag == "p" and child.get("n") is not None:
                fields[str(child.get("n"))] = child.get("v") or ""
        missing = [
            key for key in ("sourceOrd", "sourceSlotName", "targetSlotName") if not fields.get(key)
        ]
        if missing:
            raise ShadowLoadError(f"link {parent.path}/{name} lacks {', '.join(missing)}")
        self.link_order += 1
        return LinkSpec(
            name,
            fields["sourceOrd"],
            fields["sourceSlotName"],
            fields["targetSlotName"],
            self.link_order,
        )

    # -- links -----------------------------------------------------------------

    def _resolve_links(self) -> list[ResolvedLink]:
        self._unresolved: set[tuple[str, str]] = set()
        resolved: list[ResolvedLink] = []
        for node in self.components:
            for link in node.links:
                source = self._resolve_ord(link.source_ord, node)
                if source is None:
                    self._unresolved.add((node.path, link.name))
                    continue
                resolved.append(
                    ResolvedLink(source, link.source_slot, node, link.target_slot, link.order)
                )
        resolved.sort(key=lambda item: item.order)
        return resolved

    def _resolve_ord(self, ord_text: str, target: ComponentNode) -> ComponentNode | None:
        text = ord_text.strip()
        if text.startswith("station:|"):
            text = text[len("station:|") :]
        if text.startswith("h:"):
            return self.by_handle.get(text[2:].strip().lower())
        if text.startswith("slot:"):
            path = text[5:].strip()
            if not path.startswith("/"):
                # Relative to the target's parent, as Niagara resolves relative slot ORDs.
                base = target.folder.rstrip("/")
                path = f"{base}/{path}"
            path = "/" + "/".join(segment for segment in path.split("/") if segment)
            return self.by_path.get(path)
        return None


__all__ = [
    "CONTAINER_TYPES",
    "DEFAULT_SYMBOLS",
    "INERT_TYPES",
    "LINK_TYPES",
    "ComponentNode",
    "LinkSpec",
    "Program",
    "Property",
    "ResolvedLink",
    "ShadowLoadError",
    "load_program",
    "parse_boolean",
    "parse_number",
    "read_archive",
]
