from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bactalk.domain import BLOCK_SLOTS, BlockKind, DataType, canonical_json

MAX_ENVIRONMENT_PACK_BYTES = 100 * 1024 * 1024
MAX_ENVIRONMENT_ENTRIES = 2_000
MAX_ENVIRONMENT_ENTRY_BYTES = 50 * 1024 * 1024
MAX_ENVIRONMENT_UNCOMPRESSED_BYTES = 250 * 1024 * 1024

_CORE_NIAGARA_MODULES = {
    "alarm",
    "baja",
    "bacnet",
    "control",
    "driver",
    "email",
    "history",
    "kitControl",
    "schedule",
    "web",
    "workbench",
}


def _safe_archive_path(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe environment-pack path: {value!r}")
    normalized = path.as_posix()
    if len(normalized) > 500:
        raise ValueError("environment-pack paths may not exceed 500 characters")
    return normalized


class ModuleArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$", max_length=120)
    version: str = Field(min_length=1, max_length=120)
    vendor: str = Field(min_length=1, max_length=200)
    preferred_symbol: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
        max_length=40,
    )
    runtime_profiles: list[Literal["rt", "wb", "se"]] = Field(min_length=1, max_length=3)
    artifact: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    license_spdx: str | None = Field(default=None, max_length=120)
    redistribution: Literal["bundled_permitted", "shop_supplied_only", "reference_only"]
    required: bool = True

    @model_validator(mode="after")
    def artifact_policy_is_consistent(self) -> ModuleArtifact:
        self.runtime_profiles = list(dict.fromkeys(self.runtime_profiles))
        if self.redistribution == "reference_only":
            if self.artifact is not None or self.sha256 is not None:
                raise ValueError("reference-only modules cannot include an artifact or hash")
        elif self.artifact is None or self.sha256 is None:
            raise ValueError("bundled and shop-supplied modules require artifact and sha256")
        if self.artifact is not None:
            self.artifact = _safe_archive_path(self.artifact)
            if not self.artifact.lower().endswith(".jar"):
                raise ValueError("Niagara module artifacts must be .jar files")
        return self


class CustomSlotContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    niagara_slot: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_$]*$", max_length=120)
    data_type: DataType


class CustomComponentContract(BaseModel):
    """Typed lowering contract for one shop-supplied Niagara component."""

    model_config = ConfigDict(extra="forbid")

    type_spec: str = Field(
        pattern=r"^[A-Za-z][A-Za-z0-9_.-]*:[A-Za-z][A-Za-z0-9_$.-]*$",
        max_length=240,
    )
    behavior_kind: BlockKind
    inputs: dict[str, CustomSlotContract]
    outputs: dict[str, CustomSlotContract]
    properties: dict[str, float | bool | str] = Field(default_factory=dict, max_length=500)
    config_properties: dict[str, str] = Field(default_factory=dict, max_length=500)
    contract_version: str = Field(default="1.0", min_length=1, max_length=120)

    @model_validator(mode="after")
    def slots_are_unique(self) -> CustomComponentContract:
        for label, slots in (("input", self.inputs), ("output", self.outputs)):
            physical = [item.niagara_slot for item in slots.values()]
            if len(physical) != len(set(physical)):
                raise ValueError(f"custom component {label} Niagara slots must be unique")
        for config_name, property_name in self.config_properties.items():
            if config_name == "niagara_override" or not re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*", config_name
            ):
                raise ValueError(
                    f"custom component config key is invalid: {config_name!r}"
                )
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", property_name):
                raise ValueError(
                    f"custom component Niagara property is invalid: {property_name!r}"
                )
        if len(self.config_properties.values()) != len(set(self.config_properties.values())):
            raise ValueError("custom component config properties must be unique")
        collisions = sorted(set(self.properties) & set(self.config_properties.values()))
        if collisions:
            raise ValueError(
                "custom component static and config properties collide: "
                + ", ".join(collisions)
            )
        return self


class PaletteContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$", max_length=120)
    module: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$", max_length=120)
    resource: str = Field(min_length=1, max_length=500)
    component_types: list[str] = Field(default_factory=list, max_length=10_000)
    components: list[CustomComponentContract] = Field(default_factory=list, max_length=10_000)

    @model_validator(mode="after")
    def type_specs_are_qualified(self) -> PaletteContract:
        self.resource = _safe_archive_path(self.resource)
        self.component_types = list(
            dict.fromkeys([*self.component_types, *(item.type_spec for item in self.components)])
        )
        if len(self.component_types) != len(set(self.component_types)):
            raise ValueError("palette component types must be unique")
        for type_spec in self.component_types:
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*:[A-Za-z][A-Za-z0-9_$.-]*", type_spec):
                raise ValueError(f"invalid Niagara component type spec: {type_spec!r}")
        return self


class GraphicsTemplateArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$", max_length=120)
    artifact: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: Literal[
        "application/vnd.tridium.px",
        "application/vnd.tridium.bog",
        "application/json",
        "image/svg+xml",
        "image/png",
    ]

    @model_validator(mode="after")
    def artifact_path_is_safe(self) -> GraphicsTemplateArtifact:
        self.artifact = _safe_archive_path(self.artifact)
        return self


class EnvironmentPackManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$", max_length=120)
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=120)
    niagara_version: str = Field(min_length=1, max_length=120)
    modules: list[ModuleArtifact] = Field(default_factory=list, max_length=1_000)
    palettes: list[PaletteContract] = Field(default_factory=list, max_length=1_000)
    graphics_templates: list[GraphicsTemplateArtifact] = Field(
        default_factory=list,
        max_length=1_000,
    )

    @model_validator(mode="after")
    def identifiers_and_references_are_valid(self) -> EnvironmentPackManifest:
        for label, values in {
            "module names": [item.name for item in self.modules],
            "palette ids": [item.id for item in self.palettes],
            "graphics template ids": [item.id for item in self.graphics_templates],
        }.items():
            if len(values) != len(set(values)):
                raise ValueError(f"environment {label} must be unique")
        module_names = {item.name for item in self.modules}
        modules = {item.name: item for item in self.modules}
        component_types: list[str] = []
        for palette in self.palettes:
            if palette.module not in module_names:
                raise ValueError(
                    f"palette {palette.id} references undeclared module {palette.module}"
                )
            module = modules[palette.module]
            accepted_prefixes = {module.name, module.preferred_symbol}
            for component in palette.components:
                prefix = component.type_spec.split(":", 1)[0]
                if prefix not in accepted_prefixes:
                    raise ValueError(
                        f"custom type {component.type_spec} does not belong to module "
                        f"{palette.module}"
                    )
                expected = BLOCK_SLOTS[component.behavior_kind]
                if component.inputs.keys() != expected.inputs.keys():
                    raise ValueError(
                        f"custom type {component.type_spec} inputs do not match behavior "
                        f"{component.behavior_kind.value}"
                    )
                if component.outputs.keys() != expected.outputs.keys():
                    raise ValueError(
                        f"custom type {component.type_spec} outputs do not match behavior "
                        f"{component.behavior_kind.value}"
                    )
                for logical, slot in component.inputs.items():
                    if slot.data_type != expected.inputs[logical]:
                        raise ValueError(
                            f"custom type {component.type_spec} input {logical} has wrong type"
                        )
                for logical, slot in component.outputs.items():
                    if slot.data_type != expected.outputs[logical]:
                        raise ValueError(
                            f"custom type {component.type_spec} output {logical} has wrong type"
                        )
                component_types.append(component.type_spec)
        if len(component_types) != len(set(component_types)):
            raise ValueError("custom component contracts must have unique type specs")
        return self


@dataclass(frozen=True)
class EnvironmentArtifact:
    relative_path: str
    content: bytes


@dataclass(frozen=True)
class EnvironmentPackExport:
    manifest: dict[str, Any]
    artifacts: list[EnvironmentArtifact]
    descriptor: EnvironmentPackManifest


def _validate_zip_member(info: zipfile.ZipInfo) -> str:
    name = _safe_archive_path(info.filename)
    if info.is_dir():
        return name
    if info.flag_bits & 0x1:
        raise ValueError(f"encrypted environment-pack entries are not accepted: {name}")
    if info.file_size > MAX_ENVIRONMENT_ENTRY_BYTES:
        raise ValueError(f"environment-pack entry exceeds 50 MiB: {name}")
    file_type = (info.external_attr >> 16) & 0o170000
    if file_type == 0o120000:
        raise ValueError(f"environment-pack symbolic links are not accepted: {name}")
    return name


def _jar_inventory(content: bytes) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = [_safe_archive_path(item.filename) for item in archive.infolist()]
    except (zipfile.BadZipFile, ValueError) as exc:
        raise ValueError("Niagara module artifact is not a valid, safe JAR") from exc
    descriptors = [
        name
        for name in names
        if name in {"module.xml", "META-INF/niagara-module.xml", "META-INF/MANIFEST.MF"}
    ]
    return {
        "class_count": sum(name.endswith(".class") for name in names),
        "descriptor_entries": descriptors,
        "entry_count": len(names),
        "executed_during_ingest": False,
    }


def _bog_inventory(content: bytes) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            xml_content = archive.read("file.xml")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise ValueError("Niagara compatibility input must be a .bog containing file.xml") from exc
    try:
        root = ElementTree.fromstring(xml_content)
    except ElementTree.ParseError as exc:
        raise ValueError("Niagara compatibility input contains invalid file.xml") from exc
    symbol_to_module: dict[str, str] = {}
    raw_types: set[str] = set()
    for element in root.iter():
        for declaration in element.attrib.get("m", "").split():
            if "=" not in declaration:
                continue
            symbol, module_name = declaration.split("=", 1)
            if symbol and module_name:
                symbol_to_module[symbol] = module_name
        type_spec = element.attrib.get("t")
        if type_spec and ":" in type_spec:
            raw_types.add(type_spec)
    canonical_types = sorted(
        f"{symbol_to_module.get(symbol, symbol)}:{type_name}"
        for symbol, type_name in (value.split(":", 1) for value in raw_types)
    )
    modules = sorted({value.split(":", 1)[0] for value in canonical_types})
    return {
        "type_specs": canonical_types,
        "modules": modules,
        "module_symbols": dict(sorted(symbol_to_module.items())),
    }


def _compatibility_report(
    descriptor: EnvironmentPackManifest,
    *,
    generated_bog: bytes | None,
    template_bog: bytes | None,
) -> dict[str, Any]:
    modules = {item.name: item for item in descriptor.modules}
    symbol_to_name = {
        item.preferred_symbol: item.name
        for item in descriptor.modules
        if item.preferred_symbol is not None
    }
    contracted_types: set[str] = set()
    for palette in descriptor.palettes:
        for type_spec in palette.component_types:
            prefix, type_name = type_spec.split(":", 1)
            contracted_types.add(f"{symbol_to_name.get(prefix, prefix)}:{type_name}")

    inputs: dict[str, dict[str, Any]] = {}
    for label, content in (("generated", generated_bog), ("contractor_template", template_bog)):
        if content is None:
            continue
        inventory = _bog_inventory(content)
        custom_modules = sorted(set(inventory["modules"]) - _CORE_NIAGARA_MODULES)
        missing_modules = sorted(set(custom_modules) - set(modules))
        custom_types = sorted(
            value
            for value in inventory["type_specs"]
            if value.split(":", 1)[0] in custom_modules
        )
        uncontracted_types = sorted(set(custom_types) - contracted_types)
        inputs[label] = {
            **inventory,
            "custom_modules": custom_modules,
            "missing_modules": missing_modules,
            "custom_component_types": custom_types,
            "uncontracted_custom_component_types": uncontracted_types,
            "statically_compatible": not missing_modules and not uncontracted_types,
        }
    incompatible = {
        label: item
        for label, item in inputs.items()
        if not item["statically_compatible"]
    }
    return {
        "target_niagara_version": descriptor.niagara_version,
        "inputs": inputs,
        "statically_compatible": not incompatible,
        "runtime_qualified": False,
        "module_installation_automatic": False,
        "reason": (
            "Module and component-type closure is checked statically; the exact Niagara "
            "version, transitive module dependencies, palettes, and graphics must still pass "
            "the licensed runtime matrix."
        ),
    }


def inspect_environment_pack(
    content: bytes,
    *,
    generated_bog: bytes | None = None,
    template_bog: bytes | None = None,
) -> EnvironmentPackExport:
    """Validate and inventory a contractor pack without loading any Java or Niagara code."""

    if not content:
        raise ValueError("environment pack is empty")
    if len(content) > MAX_ENVIRONMENT_PACK_BYTES:
        raise ValueError("environment pack exceeds 100 MiB")
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise ValueError("environment pack must be a ZIP archive") from exc

    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ENVIRONMENT_ENTRIES:
            raise ValueError("environment pack contains too many entries")
        names: dict[str, zipfile.ZipInfo] = {}
        total_size = 0
        for info in infos:
            name = _validate_zip_member(info)
            if info.is_dir():
                continue
            if name in names:
                raise ValueError(f"duplicate environment-pack entry: {name}")
            names[name] = info
            total_size += info.file_size
        if total_size > MAX_ENVIRONMENT_UNCOMPRESSED_BYTES:
            raise ValueError("environment pack exceeds 250 MiB uncompressed")
        descriptor_info = names.get("environment.json")
        if descriptor_info is None:
            raise ValueError("environment pack must contain environment.json at its root")
        try:
            raw_descriptor = archive.read(descriptor_info)
            descriptor = EnvironmentPackManifest.model_validate_json(raw_descriptor)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            raise ValueError(f"invalid environment.json: {exc}") from exc

        declared_paths = {
            item.artifact
            for item in descriptor.modules
            if item.artifact is not None
        } | {item.artifact for item in descriptor.graphics_templates}
        undeclared_files = sorted(set(names) - declared_paths - {"environment.json"})
        if undeclared_files:
            raise ValueError(
                "environment pack contains undeclared files: " + ", ".join(undeclared_files[:10])
            )

        artifacts: list[EnvironmentArtifact] = []
        artifact_inventory: list[dict[str, Any]] = []
        module_inventory: dict[str, dict[str, Any]] = {}
        declarations: list[tuple[str, str, str]] = []
        declarations.extend(
            (item.artifact, item.sha256, f"module:{item.name}")
            for item in descriptor.modules
            if item.artifact is not None and item.sha256 is not None
        )
        declarations.extend(
            (item.artifact, item.sha256, f"graphics:{item.id}")
            for item in descriptor.graphics_templates
        )
        seen: set[str] = set()
        for path, expected_hash, owner in declarations:
            if path in seen:
                raise ValueError(f"environment artifact is declared more than once: {path}")
            seen.add(path)
            info = names.get(path)
            if info is None:
                raise ValueError(f"declared environment artifact is missing: {path}")
            payload = archive.read(info)
            actual_hash = hashlib.sha256(payload).hexdigest()
            if actual_hash != expected_hash:
                raise ValueError(f"environment artifact hash mismatch: {path}")
            inventory = {
                "path": f"assets/{path}",
                "source_path": path,
                "owner": owner,
                "sha256": actual_hash,
                "size_bytes": len(payload),
            }
            artifact_inventory.append(inventory)
            artifacts.append(EnvironmentArtifact(relative_path=f"assets/{path}", content=payload))
            if owner.startswith("module:"):
                module_inventory[owner.removeprefix("module:")] = _jar_inventory(payload)

    normalized = descriptor.model_dump(mode="json")
    for module in normalized["modules"]:
        module["static_inventory"] = module_inventory.get(module["name"])
        if module["artifact"] is not None:
            module["artifact"] = f"assets/{module['artifact']}"
    for template in normalized["graphics_templates"]:
        template["artifact"] = f"assets/{template['artifact']}"
    compatibility = _compatibility_report(
        descriptor,
        generated_bog=generated_bog,
        template_bog=template_bog,
    )
    if not compatibility["statically_compatible"]:
        gaps = []
        for label, item in compatibility["inputs"].items():
            gaps.extend(f"{label}:missing-module:{value}" for value in item["missing_modules"])
            gaps.extend(
                f"{label}:uncontracted-type:{value}"
                for value in item["uncontracted_custom_component_types"]
            )
        raise ValueError("Niagara environment compatibility failed: " + ", ".join(gaps))

    manifest = {
        "format": "bactalk.niagara-environment.v1",
        "environment": normalized,
        "artifacts": artifact_inventory,
        "custom_component_types": sorted(
            {
                type_spec
                for palette in descriptor.palettes
                for type_spec in palette.component_types
            }
        ),
        "safety": {
            "java_or_niagara_code_executed_during_ingest": False,
            "archive_paths_validated": True,
            "declared_artifact_hashes_verified": True,
            "undeclared_files_rejected": True,
            "licensed_niagara_runtime_qualification_required": True,
            "redistribution_policy_preserved": True,
        },
        "compatibility": compatibility,
    }
    artifacts.append(
        EnvironmentArtifact(
            relative_path="normalized-environment.json",
            content=canonical_json(manifest).encode("utf-8"),
        )
    )
    return EnvironmentPackExport(
        manifest=manifest,
        artifacts=artifacts,
        descriptor=descriptor,
    )
