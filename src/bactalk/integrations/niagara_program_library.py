from __future__ import annotations

import hashlib
import os
import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


class NiagaraProgramLibraryError(ValueError):
    pass


_SLOT_TYPES = {
    "b:StatusBoolean": "boolean",
    "b:StatusNumeric": "numeric",
    "b:StatusString": "string",
    "b:StatusEnum": "enum",
    "b:Boolean": "boolean",
    "b:Integer": "integer",
    "b:Double": "numeric",
    "b:String": "string",
    "b:RelTime": "duration",
    "b:AbsTime": "datetime",
    "b:Ord": "ord",
    "b:TypeSpec": "type",
    "b:Enum": "enum",
}
_SOURCE_CAPABILITIES = {
    "external_network": (
        "java.net.",
        "HttpURLConnection",
        "openConnection(",
        "new URL(",
    ),
    "filesystem": (
        "java.io.File",
        "FileInputStream",
        "FileOutputStream",
        "RandomAccessFile",
        "Files.",
        "Paths.",
    ),
    "process_execution": ("ProcessBuilder", "Runtime.getRuntime(", "System.exit("),
    "station_ord_resolution": ("BOrd.make(", ".resolve(", "getOrdInSession("),
    "wall_clock": ("System.currentTimeMillis(", "BAbsTime.now("),
    "scheduled_execution": ("Clock.schedule(",),
    "station_link_introspection": ("getComponent().getLinks(", "getComponent().getSlot("),
}
_BARE_GETTER = re.compile(r"(?<![.A-Za-z0-9_$])get([A-Z][A-Za-z0-9_$]*)\s*\(")
_BARE_SETTER = re.compile(r"(?<![.A-Za-z0-9_$])set([A-Z][A-Za-z0-9_$]*)\s*\(")
_METHOD_DEFINITION = re.compile(
    r"(?m)^\s*(?:(?:public|private|protected|static|final|synchronized)\s+)*"
    r"[A-Za-z_$][A-Za-z0-9_$<>\[\].?, ]*\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\("
)
_FRAMEWORK_ACCESSORS = {
    "Component",
    "Class",
    "Message",
    "Cause",
    "StackTrace",
}


def _child_value(parent: ElementTree.Element, name: str) -> str | None:
    child = next((item for item in parent.findall("p") if item.get("n") == name), None)
    return child.get("v") if child is not None else None


class NiagaraProgramLibrary:
    """Inspect pinned Niagara ProgramObject `.bog` templates without executing them."""

    def __init__(self, root: Path | None = None):
        self.root = (
            root
            or Path(
                os.getenv(
                    "BACTALK_NIAGARA_PROGRAM_LIBRARY",
                    ".vendor/n4-hvac-optimization-blocks",
                )
            )
        ).resolve()

    def catalog(self) -> dict[str, Any]:
        files = self._templates()
        templates = [self._inspect(path, include_source=False) for path in files.values()]
        programs = [program for template in templates for program in template["programs"]]
        return {
            "schema": "bactalk-niagara-program-library/v1",
            "count": len(templates),
            "program_object_count": len(programs),
            "declared_slot_count": sum(len(program["slots"]) for program in programs),
            "control_template_candidate_count": sum(
                program["eligible_for_control_template_lane"] for program in programs
            ),
            "source_capability_blocked_count": sum(
                bool(program["disallowed_source_capabilities"]) for program in programs
            ),
            "templates": templates,
            "license": "MIT",
            "policy": (
                "Pinned ProgramObjects are immutable Niagara-native references. Reuse or generated "
                "source requires licensed Workbench compilation, isolated runtime tests, and human "
                "approval before deployment."
            ),
        }

    def inspect(self, template_id: str) -> dict[str, Any]:
        path = self._templates().get(template_id)
        if path is None:
            raise KeyError(template_id)
        return self._inspect(path, include_source=True)

    def _templates(self) -> dict[str, Path]:
        directory = self.root / "bog_files"
        if not directory.is_dir():
            raise FileNotFoundError("Niagara ProgramObject library is not installed")
        return {path.stem: path for path in sorted(directory.glob("*.bog"))}

    @staticmethod
    def _inspect(path: Path, *, include_source: bool) -> dict[str, Any]:
        try:
            with zipfile.ZipFile(path) as archive:
                if archive.testzip() is not None:
                    raise NiagaraProgramLibraryError(f"corrupt archive member in {path.name}")
                xml = archive.read("file.xml")
        except (KeyError, zipfile.BadZipFile) as exc:
            raise NiagaraProgramLibraryError(f"invalid Niagara archive: {path.name}") from exc
        try:
            root = ElementTree.fromstring(xml)
        except ElementTree.ParseError as exc:
            raise NiagaraProgramLibraryError(f"invalid Niagara XML: {path.name}") from exc

        type_counts = Counter(
            element.get("t") for element in root.iter("p") if element.get("t") is not None
        )
        parent_by_id = {id(child): parent for parent in root.iter() for child in parent}

        def component_path(element: ElementTree.Element) -> str:
            names: list[str] = []
            current: ElementTree.Element | None = element
            while current is not None and current is not root:
                name = current.get("n")
                if name:
                    names.append(name)
                current = parent_by_id.get(id(current))
            return "/".join(reversed(names))

        programs: list[dict[str, Any]] = []
        for program in (item for item in root.iter("p") if item.get("t") == "p:Program"):
            code = next(
                (item for item in program.findall("p") if item.get("t") == "p:ProgramCode"),
                None,
            )
            if code is None:
                raise NiagaraProgramLibraryError(
                    f"ProgramObject {program.get('n')} in {path.name} has no ProgramCode"
                )
            source = _child_value(code, "source")
            class_file = _child_value(code, "classFile")
            class_name = _child_value(code, "className")
            dependencies = _child_value(code, "dependencies")
            checksum = _child_value(code, "checksum")
            if not all((source, class_file, class_name, dependencies, checksum)):
                raise NiagaraProgramLibraryError(
                    f"ProgramObject {program.get('n')} in {path.name} is incomplete"
                )
            slots = []
            for child in program.findall("p"):
                type_spec = child.get("t")
                if type_spec not in _SLOT_TYPES:
                    continue
                flags = child.get("f", "")
                slots.append(
                    {
                        "name": child.get("n"),
                        "type_spec": type_spec,
                        "data_type": _SLOT_TYPES[type_spec],
                        "direction": "output" if "r" in flags else "input_or_parameter",
                        "flags": flags,
                        "default": child.get("v"),
                    }
                )
            slot_names = {item["name"] for item in slots}
            slot_names_folded = {
                str(name).casefold(): str(name) for name in slot_names if name is not None
            }
            source_capabilities = sorted(
                name
                for name, patterns in _SOURCE_CAPABILITIES.items()
                if any(pattern in source for pattern in patterns)
            )
            defined_methods = set(_METHOD_DEFINITION.findall(source))
            accessor_names = {
                name
                for prefix, regex in (("get", _BARE_GETTER), ("set", _BARE_SETTER))
                for name in regex.findall(source)
                if name not in _FRAMEWORK_ACCESSORS
                and f"{prefix}{name}" not in defined_methods
            }
            # Niagara accessor capitalization does not preserve leading all-caps
            # acronyms consistently (SP0 may appear as getSP0). Slot comparison
            # is therefore case-insensitive while emitted names remain exact.
            missing_accessors = sorted(
                name for name in accessor_names if name.casefold() not in slot_names_folded
            )
            disallowed_capabilities = sorted(
                set(source_capabilities)
                & {
                    "external_network",
                    "filesystem",
                    "process_execution",
                    "station_ord_resolution",
                }
            )
            record: dict[str, Any] = {
                "name": program.get("n"),
                "handle": program.get("h"),
                "component_path": component_path(program),
                "class_name": class_name,
                "dependencies": dependencies.split(";"),
                "checksum": checksum,
                "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                "source_characters": len(source),
                "compiled_class_present": bool(class_file),
                "slots": slots,
                "input_or_parameter_count": sum(
                    item["direction"] == "input_or_parameter" for item in slots
                ),
                "output_count": sum(item["direction"] == "output" for item in slots),
                "source_capabilities": source_capabilities,
                "disallowed_source_capabilities": disallowed_capabilities,
                "source_slot_contract_complete": not missing_accessors,
                "missing_source_slot_accessors": missing_accessors,
                "eligible_for_control_template_lane": (
                    not disallowed_capabilities and not missing_accessors
                ),
            }
            if include_source:
                record["source"] = source
            programs.append(record)

        return {
            "id": path.stem,
            "filename": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
            "program_object_count": len(programs),
            "programs": programs,
            "component_type_counts": dict(sorted(type_counts.items())),
            "runtime_qualified": False,
        }
