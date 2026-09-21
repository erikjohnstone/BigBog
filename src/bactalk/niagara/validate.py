"""Static validator for Niagara ``.bog`` archives (GOAL-NATIVE-BOG.md N1).

It reads a ``.bog`` (a zip holding ``file.xml``) without any Niagara runtime and
checks what can be checked from the file alone:

``archive.structure``   the zip holds exactly ``file.xml`` and no DTD or entity
``xml.well_formed``     the XML parses
``xml.root``            the root is ``bajaObjectGraph``
``module.declared``     every type symbol is declared by an ``m=`` attribute
                        before it is used (document order) or is a customary one
``module.consistent``   a symbol is never redeclared to a different module
``type.known``          every type is in the catalog or was declared to the
                        validator (a ``bactalkG36`` module, for example)
``handle.well_formed``  handles are hexadecimal
``handle.unique``       no two components share a handle
``link.fields``         a link names its source ord and both slots
``link.source_resolves`` a ``h:`` source ord points at a component in the file
``link.source_slot``    the source slot exists on the source component
``link.target_slot``    the target slot exists on the target component
``link.double_driven``  no input slot is the target of two links
``link.kind_match``     numeric, boolean, enum and string kinds agree across a
                        plain link (conversion links are exempt)
``facets.parse``        every ``facets`` value follows ``key=enc:value|...``
``facets.unit_known``   ``units=u:<name>;...`` names a Niagara unit we know

Findings are :class:`Issue` records with a severity; ``ok`` means no errors.
Warnings (an external ``slot:`` source ord, a link out of a slot never seen as
a source, a property the catalog does not know) never fail a run on their own.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

from bactalk.niagara.catalog import DATA_KINDS, NiagaraCatalog, TypeSpec, load_catalog
from bactalk.niagara.units import NIAGARA_UNITS

ERROR = "error"
WARNING = "warning"

_HANDLE = re.compile(r"^[0-9a-fA-F]+$")
_FORBIDDEN_XML = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)
_FACET = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=([A-Za-z])(?::(.*))?$", re.DOTALL)
_UNIT = re.compile(r"^([^;]*);([^;]*);([^;]*);([^;]*);$")
_LINK_TYPES = {"baja:Link", "baja:ConversionLink"}
_UNIT_NAMES = set(NIAGARA_UNITS) | {"null"}


@dataclass(frozen=True)
class Issue:
    rule: str
    severity: str
    path: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.rule} at {self.path}: {self.message}"


@dataclass
class ValidationReport:
    label: str
    issues: list[Issue] = field(default_factory=list)
    component_count: int = 0
    link_count: int = 0
    types_seen: dict[str, int] = field(default_factory=dict)

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    def rules(self, severity: str | None = None) -> set[str]:
        return {
            issue.rule for issue in self.issues if severity is None or issue.severity == severity
        }

    def raise_for_errors(self) -> None:
        if self.ok:
            return
        lines = [str(issue) for issue in self.errors[:12]]
        more = len(self.errors) - len(lines)
        if more > 0:
            lines.append(f"... and {more} more")
        raise BogValidationError(
            f"{self.label} failed static Niagara validation:\n" + "\n".join(lines),
            report=self,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "ok": self.ok,
            "component_count": self.component_count,
            "link_count": self.link_count,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [issue.__dict__ for issue in self.issues],
        }


class BogValidationError(ValueError):
    def __init__(self, message: str, *, report: ValidationReport) -> None:
        super().__init__(message)
        self.report = report


@dataclass
class _Component:
    element: ElementTree.Element
    path: str
    type_spec: str | None  # resolved module:Name, or None when unresolved
    raw_type: str
    handle: str | None
    modules: Mapping[str, str]


def validate_bog(
    source: Path | bytes,
    *,
    catalog: NiagaraCatalog | None = None,
    declared_types: Iterable[TypeSpec] = (),
    require_known_types: bool = True,
    label: str | None = None,
) -> ValidationReport:
    """Validate one ``.bog`` archive and return every finding."""

    if isinstance(source, Path):
        content = source.read_bytes()
        label = label or source.name
    else:
        content = source
        label = label or "<bytes>"
    catalog = (catalog or load_catalog()).with_types(declared_types)
    report = ValidationReport(label=label)
    root = _read_archive(content, report)
    if root is None:
        return report
    _Validator(catalog, report, require_known_types).run(root)
    return report


def _read_archive(content: bytes, report: ValidationReport) -> ElementTree.Element | None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = archive.namelist()
            if "file.xml" not in names:
                report.issues.append(
                    Issue("archive.structure", ERROR, "/", "archive has no file.xml entry")
                )
                return None
            extra = [name for name in names if name != "file.xml"]
            if extra:
                report.issues.append(
                    Issue(
                        "archive.structure",
                        WARNING,
                        "/",
                        f"archive carries entries besides file.xml: {extra[:5]}",
                    )
                )
            xml = archive.read("file.xml")
    except zipfile.BadZipFile:
        report.issues.append(Issue("archive.structure", ERROR, "/", "not a zip archive"))
        return None
    if _FORBIDDEN_XML.search(xml):
        report.issues.append(
            Issue("archive.structure", ERROR, "/file.xml", "DTD or entity declarations are refused")
        )
        return None
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        report.issues.append(Issue("xml.well_formed", ERROR, "/file.xml", str(exc)))
        return None
    if root.tag != "bajaObjectGraph":
        report.issues.append(
            Issue(
                "xml.root", ERROR, "/file.xml", f"root element is {root.tag!r}, not bajaObjectGraph"
            )
        )
        return None
    if root.get("version") is None:
        report.issues.append(
            Issue("xml.root", ERROR, "/file.xml", "bajaObjectGraph has no version attribute")
        )
    return root


class _Validator:
    def __init__(
        self, catalog: NiagaraCatalog, report: ValidationReport, require_known_types: bool
    ) -> None:
        self.catalog = catalog
        self.report = report
        self.require_known_types = require_known_types
        self.components: list[_Component] = []
        self.by_handle: dict[str, _Component] = {}
        self.modules: dict[str, str] = {}

    def issue(self, rule: str, severity: str, path: str, message: str) -> None:
        self.report.issues.append(Issue(rule, severity, path, message))

    # -- pass 1: modules, types, handles -------------------------------------

    def run(self, root: ElementTree.Element) -> None:
        self._walk(root, "", {}, is_root=True)
        self._check_links()

    def _resolve(self, raw_type: str, path: str) -> str | None:
        symbol, _, name = raw_type.partition(":")
        if not name:
            self.issue("type.known", ERROR, path, f"malformed type spec {raw_type!r}")
            return None
        module = self.modules.get(symbol)
        if module is None:
            module = self.catalog.symbols.get(symbol)
            if module is None:
                self.issue(
                    "module.declared",
                    ERROR,
                    path,
                    f"type {raw_type!r} uses symbol {symbol!r} that no m= attribute declares",
                )
                return None
            self.issue(
                "module.declared",
                WARNING,
                path,
                f"type {raw_type!r} relies on the customary symbol {symbol}={module} "
                "without an m= declaration",
            )
        return f"{module}:{name}"

    def _declare_modules(self, element: ElementTree.Element, path: str) -> None:
        for token in (element.get("m") or "").split():
            symbol, _, module = token.partition("=")
            if not symbol or not module:
                self.issue(
                    "module.declared", ERROR, path, f"malformed module declaration {token!r}"
                )
                continue
            existing = self.modules.get(symbol)
            if existing is not None and existing != module:
                self.issue(
                    "module.consistent",
                    ERROR,
                    path,
                    f"symbol {symbol!r} redeclared as {module!r} after {existing!r}",
                )
                continue
            self.modules[symbol] = module

    def _walk(
        self,
        element: ElementTree.Element,
        path: str,
        inherited: Mapping[str, str],
        *,
        is_root: bool,
    ) -> None:
        for child in element:
            if child.tag != "p":
                continue
            name = child.get("n")
            child_path = f"{path}/{name}" if name is not None else f"{path}/<unnamed>"
            self._declare_modules(child, child_path)
            raw_type = child.get("t")
            handle = child.get("h")
            resolved: str | None = None
            if raw_type is not None:
                resolved = self._resolve(raw_type, child_path)
                if resolved is not None:
                    self.report.types_seen[resolved] = self.report.types_seen.get(resolved, 0) + 1
                    if resolved not in self.catalog:
                        self.issue(
                            "type.known",
                            ERROR if self.require_known_types else WARNING,
                            child_path,
                            f"type {resolved!r} is not in the Niagara catalog",
                        )
            if handle is not None:
                if not _HANDLE.fullmatch(handle):
                    self.issue(
                        "handle.well_formed",
                        ERROR,
                        child_path,
                        f"handle {handle!r} is not hexadecimal",
                    )
                else:
                    key = handle.lower()
                    if key in self.by_handle:
                        self.issue(
                            "handle.unique",
                            ERROR,
                            child_path,
                            f"handle {handle!r} already used by {self.by_handle[key].path}",
                        )
            is_component = handle is not None or (is_root and raw_type is not None)
            if is_component and raw_type is not None:
                component = _Component(
                    element=child,
                    path=child_path,
                    type_spec=resolved,
                    raw_type=raw_type,
                    handle=handle,
                    modules=dict(self.modules),
                )
                self.components.append(component)
                self.report.component_count += 1
                if handle is not None and _HANDLE.fullmatch(handle):
                    self.by_handle.setdefault(handle.lower(), component)
                self._check_properties(component)
            self._walk(child, child_path, self.modules, is_root=False)

    # -- properties and facets -----------------------------------------------

    def _check_properties(self, component: _Component) -> None:
        spec = self.catalog.get(component.type_spec) if component.type_spec else None
        for child in component.element:
            if child.tag != "p":
                continue
            name = child.get("n")
            if name is None:
                continue
            child_type = child.get("t")
            resolved_child = self._peek(child_type)
            if resolved_child in _LINK_TYPES:
                continue
            if name == "facets" and child.get("v") is not None:
                self._check_facets(child.get("v") or "", f"{component.path}/facets")
            if (
                spec is not None
                and not spec.dynamic_slots
                and name not in spec.slots
                and child.get("h") is None
                and name != "wsAnnotation"
            ):
                self.issue(
                    "slot.unknown_property",
                    WARNING,
                    f"{component.path}/{name}",
                    f"{spec.type} has no catalogued slot {name!r}",
                )

    def _peek(self, raw_type: str | None) -> str | None:
        if raw_type is None:
            return None
        symbol, _, name = raw_type.partition(":")
        module = self.modules.get(symbol) or self.catalog.symbols.get(symbol)
        return f"{module}:{name}" if module and name else None

    def _check_facets(self, value: str, path: str) -> None:
        if value == "":
            return
        for part in value.split("|"):
            match = _FACET.match(part)
            if match is None:
                self.issue("facets.parse", ERROR, path, f"facet {part!r} is not key=enc:value")
                continue
            key, encoding, payload = match.group(1), match.group(2), match.group(3) or ""
            if key == "units":
                if encoding != "u":
                    self.issue(
                        "facets.parse",
                        ERROR,
                        path,
                        f"units facet must use the u: encoding, not {encoding!r}",
                    )
                    continue
                unit = _UNIT.match(payload)
                if unit is None:
                    self.issue(
                        "facets.parse",
                        ERROR,
                        path,
                        f"unit {payload!r} is not name;symbol;dimension;scale;",
                    )
                    continue
                if unit.group(1) not in _UNIT_NAMES:
                    self.issue(
                        "facets.unit_known",
                        ERROR,
                        path,
                        f"unit {unit.group(1)!r} is not a Niagara unit we know",
                    )

    # -- links ---------------------------------------------------------------

    def _check_links(self) -> None:
        driven: dict[tuple[int, str], str] = {}
        for target in self.components:
            for child in target.element:
                if child.tag != "p":
                    continue
                link_type = self._peek(child.get("t"))
                if link_type not in _LINK_TYPES:
                    continue
                self.report.link_count += 1
                path = f"{target.path}/{child.get('n') or '<link>'}"
                fields = {
                    item.get("n"): item.get("v")
                    for item in child
                    if item.tag == "p" and item.get("n") is not None
                }
                source_ord = fields.get("sourceOrd")
                source_slot = fields.get("sourceSlotName")
                target_slot = fields.get("targetSlotName")
                missing = [
                    name
                    for name, value in (
                        ("sourceOrd", source_ord),
                        ("sourceSlotName", source_slot),
                        ("targetSlotName", target_slot),
                    )
                    if not value
                ]
                if missing:
                    self.issue("link.fields", ERROR, path, f"link is missing {', '.join(missing)}")
                    continue
                assert source_ord and source_slot and target_slot
                key = (id(target.element), target_slot)
                if key in driven:
                    self.issue(
                        "link.double_driven",
                        ERROR,
                        path,
                        f"{target.path}.{target_slot} is already driven by {driven[key]}",
                    )
                else:
                    driven[key] = path
                source = self._resolve_source(source_ord, path)
                if source is None:
                    continue
                source_kind = self._slot_check(
                    source, source_slot, path, "link.source_slot", "source"
                )
                target_kind = self._slot_check(
                    target, target_slot, path, "link.target_slot", "target"
                )
                if (
                    link_type == "baja:Link"
                    and source_kind is not None
                    and target_kind is not None
                    and source_kind != target_kind
                ):
                    self.issue(
                        "link.kind_match",
                        ERROR,
                        path,
                        f"{source.path}.{source_slot} is {source_kind} but "
                        f"{target.path}.{target_slot} is {target_kind}",
                    )

    def _resolve_source(self, source_ord: str, path: str) -> _Component | None:
        scheme, _, rest = source_ord.partition(":")
        if scheme != "h":
            self.issue(
                "link.source_external",
                WARNING,
                path,
                f"source ord {source_ord!r} is not a handle and cannot be checked here",
            )
            return None
        source = self.by_handle.get(rest.lower())
        if source is None:
            self.issue(
                "link.source_resolves",
                ERROR,
                path,
                f"source ord {source_ord!r} does not name a component in this file",
            )
        return source

    def _slot_check(
        self,
        component: _Component,
        slot: str,
        path: str,
        rule: str,
        role: str,
    ) -> str | None:
        """Confirm ``slot`` exists on ``component``; return its data kind if known."""

        declared = next(
            (child for child in component.element if child.tag == "p" and child.get("n") == slot),
            None,
        )
        spec = self.catalog.get(component.type_spec) if component.type_spec else None
        if spec is None:
            # Unknown type: a slot declared on the instance is all we can accept.
            if declared is None and self.require_known_types:
                self.issue(
                    rule,
                    ERROR,
                    path,
                    f"{role} slot {slot!r} is not declared on {component.path} "
                    f"({component.raw_type} is not catalogued)",
                )
            return self._declared_kind(declared)
        slot_spec = spec.slots.get(slot)
        if slot_spec is None and declared is None and not spec.dynamic_slots:
            self.issue(
                rule,
                ERROR,
                path,
                f"{spec.type} has no slot {slot!r} ({role} of this link)",
            )
            return None
        if slot_spec is None and declared is None and spec.dynamic_slots:
            self.issue(
                rule,
                ERROR,
                path,
                f"{component.path} ({spec.type}) declares no slot {slot!r} ({role} of this link)",
            )
            return None
        if slot_spec is not None:
            if slot_spec.slot_kind != "property":
                return None
            if (
                role == "source"
                and slot_spec.direction == "input"
                and slot_spec.link_source_seen == 0
            ):
                self.issue(
                    "link.source_not_output",
                    WARNING,
                    path,
                    f"{spec.type}.{slot} is an input slot used as a link source",
                )
            if role == "target" and slot_spec.direction == "output":
                self.issue(
                    "link.target_is_output",
                    WARNING,
                    path,
                    f"{spec.type}.{slot} is an output slot used as a link target",
                )
            return slot_spec.data_kind or self._declared_kind(declared)
        return self._declared_kind(declared)

    def _declared_kind(self, declared: ElementTree.Element | None) -> str | None:
        if declared is None:
            return None
        resolved = self._peek(declared.get("t"))
        return DATA_KINDS.get(resolved) if resolved else None
