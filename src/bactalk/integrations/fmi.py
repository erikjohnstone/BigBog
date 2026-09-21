from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field

MAX_FMU_ARCHIVE_MEMBERS = 100_000
MAX_FMU_UNCOMPRESSED_BYTES = 4 * 1024 * 1024 * 1024
MAX_FMU_COMPRESSION_RATIO = 500
MAX_MODEL_DESCRIPTION_BYTES = 32 * 1024 * 1024


class FmiVariable(BaseModel):
    """One declared FMI variable, preserving source strings for human review."""

    model_config = ConfigDict(extra="forbid")

    name: str
    value_reference: str | None = None
    causality: str
    variability: str | None = None
    initial: str | None = None
    data_type: str
    unit: str | None = None
    minimum: str | None = None
    maximum: str | None = None
    start: str | None = None
    description: str | None = None


class FmiModelDescription(BaseModel):
    """Read-only metadata admitted from an FMU before runtime submission."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_name: str = Field(
        default="bactalk.fmi-model-description/v1",
        alias="schema",
    )
    filename: str
    sha256: str
    bytes: int = Field(ge=0)
    fmi_version: str
    model_name: str
    guid: str | None = None
    instantiation_token: str | None = None
    generation_tool: str | None = None
    model_identifiers: list[str]
    platforms: list[str]
    inputs: list[FmiVariable]
    outputs: list[FmiVariable]
    parameter_count: int = Field(ge=0)
    local_variable_count: int = Field(ge=0)
    variable_count: int = Field(ge=0)
    live_building_writes: bool = False


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def _archive_source(source: Path | bytes) -> tuple[BinaryIO, bytes, str]:
    if isinstance(source, Path):
        content = source.read_bytes()
        return io.BytesIO(content), content, source.name
    content = bytes(source)
    return io.BytesIO(content), content, "model.fmu"


def _validate_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > MAX_FMU_ARCHIVE_MEMBERS:
        raise ValueError("Alfalfa FMU contains too many archive members")
    total_size = 0
    members: dict[str, zipfile.ZipInfo] = {}
    for info in infos:
        normalized = info.filename.replace("\\", "/")
        member = PurePosixPath(normalized)
        if member.is_absolute() or ".." in member.parts:
            raise ValueError("Alfalfa FMU contains an unsafe archive path")
        if not normalized or normalized in members:
            raise ValueError("Alfalfa FMU contains duplicate archive members")
        if info.flag_bits & 0x1:
            raise ValueError("Alfalfa FMU contains encrypted archive members")
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise ValueError("Alfalfa FMU contains symbolic links")
        total_size += info.file_size
        if total_size > MAX_FMU_UNCOMPRESSED_BYTES:
            raise ValueError("Alfalfa FMU expands beyond the 4 GiB admission limit")
        if (
            info.compress_size
            and info.file_size / info.compress_size > MAX_FMU_COMPRESSION_RATIO
        ):
            raise ValueError("Alfalfa FMU contains a suspiciously compressed member")
        members[normalized] = info
    if "modelDescription.xml" not in members:
        raise ValueError("Alfalfa FMU is missing modelDescription.xml")
    if members["modelDescription.xml"].file_size > MAX_MODEL_DESCRIPTION_BYTES:
        raise ValueError("Alfalfa FMU modelDescription.xml exceeds the 32 MiB limit")
    return members


def _variable(element: ElementTree.Element) -> FmiVariable:
    """Read both FMI 1/2 ScalarVariable and FMI 3 typed-variable layouts."""

    element_type = _local_name(element.tag)
    attributes = element.attrib
    if element_type == "ScalarVariable":
        typed = next(iter(element), None)
        if typed is None:
            raise ValueError(
                f"FMI variable {attributes.get('name', '<unnamed>')} has no type"
            )
        type_attributes = typed.attrib
        data_type = _local_name(typed.tag)
    else:
        type_attributes = attributes
        data_type = element_type
    name = attributes.get("name", "").strip()
    causality = attributes.get("causality", "local").strip().lower()
    if not name:
        raise ValueError("Alfalfa FMU contains an unnamed FMI variable")
    return FmiVariable(
        name=name,
        value_reference=attributes.get("valueReference"),
        causality=causality,
        variability=attributes.get("variability"),
        initial=attributes.get("initial"),
        data_type=data_type,
        unit=type_attributes.get("unit") or attributes.get("unit"),
        minimum=type_attributes.get("min") or attributes.get("min"),
        maximum=type_attributes.get("max") or attributes.get("max"),
        start=type_attributes.get("start") or attributes.get("start"),
        description=attributes.get("description"),
    )


def inspect_fmu_archive(
    source: Path | bytes,
    *,
    filename: str | None = None,
) -> FmiModelDescription:
    """Validate an FMU container and return deterministic read-only metadata."""

    stream, content, inferred_filename = _archive_source(source)
    try:
        with zipfile.ZipFile(stream) as archive:
            members = _validate_members(archive)
            with archive.open(members["modelDescription.xml"]) as description_stream:
                description = description_stream.read(MAX_MODEL_DESCRIPTION_BYTES + 1)
            upper = description.upper()
            if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
                raise ValueError(
                    "Alfalfa FMU modelDescription.xml contains forbidden declarations"
                )
            try:
                root = ElementTree.fromstring(description)
            except ElementTree.ParseError as exc:
                raise ValueError(
                    "Alfalfa FMU has an invalid modelDescription.xml"
                ) from exc
            if _local_name(root.tag) != "fmiModelDescription":
                raise ValueError("Alfalfa FMU has an invalid modelDescription.xml")

            model_variables = next(
                (
                    child
                    for child in root
                    if _local_name(child.tag) == "ModelVariables"
                ),
                None,
            )
            if model_variables is None:
                raise ValueError("Alfalfa FMU modelDescription.xml has no ModelVariables")
            variables = [_variable(element) for element in model_variables]
            names = [variable.name for variable in variables]
            if len(names) != len(set(names)):
                raise ValueError("Alfalfa FMU contains duplicate FMI variable names")

            model_identifiers = sorted(
                {
                    identifier
                    for element in root
                    if _local_name(element.tag) in {"CoSimulation", "ModelExchange"}
                    and (identifier := element.attrib.get("modelIdentifier"))
                }
            )
            platforms = sorted(
                {
                    PurePosixPath(name).parts[1]
                    for name in members
                    if len(PurePosixPath(name).parts) >= 3
                    and PurePosixPath(name).parts[0] == "binaries"
                }
            )
    except zipfile.BadZipFile as exc:
        raise ValueError("Alfalfa model is not a valid FMU/ZIP archive") from exc

    def selected(*causalities: str) -> list[FmiVariable]:
        allowed = set(causalities)
        return [variable for variable in variables if variable.causality in allowed]

    return FmiModelDescription(
        filename=filename or inferred_filename,
        sha256=hashlib.sha256(content).hexdigest(),
        bytes=len(content),
        fmi_version=root.attrib.get("fmiVersion", "unknown"),
        model_name=root.attrib.get("modelName", "unknown"),
        guid=root.attrib.get("guid"),
        instantiation_token=root.attrib.get("instantiationToken"),
        generation_tool=root.attrib.get("generationTool"),
        model_identifiers=model_identifiers,
        platforms=platforms,
        inputs=selected("input"),
        outputs=selected("output"),
        parameter_count=len(
            selected("parameter", "calculatedparameter", "structuralparameter")
        ),
        local_variable_count=len(selected("local", "independent")),
        variable_count=len(variables),
    )
