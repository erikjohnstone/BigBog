from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bactalk.domain import BlockKind, JobSpec
from bactalk.integrations.readiness import STAGES


class PackStatus(StrEnum):
    PROTOTYPE = "prototype"
    QUALIFYING = "qualifying"
    SUPPORTED = "supported"


class ArtifactCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logic: bool = False
    point_mapping: bool = False
    tags: bool = False
    alarms: bool = False
    schedules: bool = False
    histories: bool = False
    graphics: bool = False
    template_diff: bool = False


class VerificationCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    structural: bool = False
    deterministic: bool = False
    independent_rules: bool = False
    trajectory: bool = False
    fault_injection: bool = False
    recovery: bool = False
    dynamic_building: bool = False
    niagara_runtime: bool = False
    field_qualified: bool = False


class CapabilityPack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9.-]*$")
    name: str
    version: str
    equipment_families: list[str] = Field(min_length=1)
    sequence_families: list[str] = Field(min_length=1)
    stage: str
    status: PackStatus
    supported_blocks: list[BlockKind]
    artifact_coverage: ArtifactCoverage
    verification_coverage: VerificationCoverage
    source_basis: list[str]
    limitations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def known_stage(self) -> CapabilityPack:
        if self.stage not in STAGES:
            raise ValueError(f"unknown capability stage: {self.stage}")
        return self

    @property
    def production_ready(self) -> bool:
        return self.stage == "production-supported" and self.status == PackStatus.SUPPORTED


class EquipmentFamilyCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    stage: str
    semantic_sources: list[str] = Field(default_factory=list)
    installed_pack_ids: list[str] = Field(default_factory=list)
    blocker: str | None = None

    @model_validator(mode="after")
    def known_stage(self) -> EquipmentFamilyCapability:
        if self.stage not in STAGES:
            raise ValueError(f"unknown capability stage: {self.stage}")
        return self


SUPPORTED_BLOCKS = list(BlockKind)


class CapabilityRegistry:
    """Truthful registry of what BACTalk can compile and how far it is qualified."""

    def __init__(self) -> None:
        self.packs = [
            CapabilityPack(
                id="g36-vav-reheat-mvp",
                name="Guideline 36 VAV with reheat — bounded subset",
                version="0.1.0",
                equipment_families=["terminal.vav.reheat"],
                sequence_families=["G36_VAV_REHEAT"],
                stage="target-compiled",
                status=PackStatus.PROTOTYPE,
                supported_blocks=SUPPORTED_BLOCKS,
                artifact_coverage=ArtifactCoverage(
                    logic=True,
                    point_mapping=True,
                    tags=True,
                    schedules=True,
                    histories=True,
                    template_diff=True,
                ),
                verification_coverage=VerificationCoverage(
                    structural=True,
                    deterministic=True,
                ),
                source_basis=[
                    "LBNL Buildings/OBC G36 source",
                    "BuildingMOTIF G36 topology templates",
                    "Haxall ashrae.g36 Xeto specs",
                ],
                limitations=[
                    "This is a small G36-inspired subset, not a complete Guideline 36 sequence.",
                    "Weekly schedule objects are target-compiled when declared; Niagara alarm "
                    "extensions and PX graphics are not.",
                    "No licensed Niagara runtime or field qualification has passed.",
                ],
            ),
            CapabilityPack(
                id="ahu-safety-cooling-v1",
                name="AHU supply-fan safety and bounded cooling",
                version="0.1.0",
                equipment_families=["ahu.single-zone", "ahu.multi-zone-vav"],
                sequence_families=["CUSTOM_AHU_SAFETY_COOLING"],
                stage="target-compiled",
                status=PackStatus.PROTOTYPE,
                supported_blocks=SUPPORTED_BLOCKS,
                artifact_coverage=ArtifactCoverage(
                    logic=True,
                    point_mapping=True,
                    tags=True,
                    schedules=True,
                    histories=True,
                    template_diff=True,
                ),
                verification_coverage=VerificationCoverage(
                    structural=True,
                    deterministic=True,
                ),
                source_basis=[
                    "BACTalk bounded AHU safety pack",
                    "BuildingMOTIF AHU topology templates",
                    "Contractor acceptance cases",
                ],
                limitations=[
                    "This is not a complete Guideline 36 AHU sequence.",
                    "Economizer, freeze protection, fan proof, resets, modes, alarms, and "
                    "plant requests remain to be added.",
                    "No licensed Niagara runtime or field qualification has passed.",
                ],
            ),
            CapabilityPack(
                id="exhaust-fan-proof-v1",
                name="Exhaust fan command and proof alarm",
                version="0.1.0",
                equipment_families=["exhaust"],
                sequence_families=["EXHAUST_FAN_PROOF"],
                stage="target-compiled",
                status=PackStatus.PROTOTYPE,
                supported_blocks=SUPPORTED_BLOCKS,
                artifact_coverage=ArtifactCoverage(
                    logic=True,
                    point_mapping=True,
                    tags=True,
                    schedules=True,
                    histories=True,
                    template_diff=True,
                ),
                verification_coverage=VerificationCoverage(
                    structural=True,
                    deterministic=True,
                    fault_injection=True,
                    recovery=True,
                ),
                source_basis=[
                    "BuildingMOTIF G36 exhaust-fan topology",
                    "Niagara boolean delay proof pattern",
                ],
                limitations=[
                    "Only enable, command, status proof, and delayed alarm are included.",
                    "Fire/smoke, pressure control, safeties, overrides, and runtime tracking "
                    "require project-specific extension.",
                    "No licensed Niagara runtime or field qualification has passed.",
                ],
            ),
            CapabilityPack(
                id="ahu-duct-static-pi-v1",
                name="AHU duct-static pressure PI control",
                version="0.1.0",
                equipment_families=["ahu.single-zone", "ahu.multi-zone-vav"],
                sequence_families=["AHU_DUCT_STATIC_PI"],
                stage="target-compiled",
                status=PackStatus.PROTOTYPE,
                supported_blocks=SUPPORTED_BLOCKS,
                artifact_coverage=ArtifactCoverage(
                    logic=True,
                    point_mapping=True,
                    tags=True,
                    schedules=True,
                    histories=True,
                    template_diff=True,
                ),
                verification_coverage=VerificationCoverage(
                    structural=True,
                    deterministic=True,
                ),
                source_basis=[
                    "pybog Niagara LoopPoint AHU example",
                    "Typed BACTalk PI block and stateful acceptance timelines",
                ],
                limitations=[
                    "Only enable, pressure input/setpoint, and bounded speed output are included.",
                    "Niagara LoopPoint runtime parity and licensed-version behavior remain to be "
                    "qualified.",
                    "No sensor-failure fallback, fan proof, reset, or field tuning workflow is "
                    "included yet.",
                ],
            ),
            CapabilityPack(
                id="two-pump-selector-v1",
                name="Two-pump duty/standby availability selector",
                version="0.1.0",
                equipment_families=["hydronic.pump"],
                sequence_families=["TWO_PUMP_AVAILABILITY_SELECTOR"],
                stage="target-compiled",
                status=PackStatus.PROTOTYPE,
                supported_blocks=SUPPORTED_BLOCKS,
                artifact_coverage=ArtifactCoverage(
                    logic=True,
                    point_mapping=True,
                    tags=True,
                    schedules=True,
                    histories=True,
                    template_diff=True,
                ),
                verification_coverage=VerificationCoverage(
                    structural=True,
                    deterministic=True,
                    fault_injection=True,
                ),
                source_basis=[
                    "pybog two-pump rotator pattern",
                    "BACTalk fail-closed acyclic availability selector",
                ],
                limitations=[
                    "Availability must be supplied by separately verified proof/safety logic.",
                    "Runtime/cycle rotation, failure latching, manual reset, and staging are not "
                    "included.",
                    "No licensed Niagara runtime or field qualification has passed.",
                ],
            ),
            CapabilityPack(
                id="typed-control-graph-v1",
                name="Equipment-neutral typed control graph",
                version="0.1.0",
                equipment_families=["custom"],
                sequence_families=["CUSTOM"],
                stage="target-compiled",
                status=PackStatus.PROTOTYPE,
                supported_blocks=SUPPORTED_BLOCKS,
                artifact_coverage=ArtifactCoverage(
                    logic=True,
                    point_mapping=True,
                    tags=True,
                    schedules=True,
                    histories=True,
                    template_diff=True,
                ),
                verification_coverage=VerificationCoverage(
                    structural=True,
                    deterministic=True,
                ),
                source_basis=["Contractor-supplied typed graph and acceptance oracle"],
                limitations=[
                    "Delays, latches, linear reset, a bounded PI loop, and weekly schedules are "
                    "available; staging, filters, and general state machines remain incomplete.",
                    "The contractor must provide complete acceptance cases for every output.",
                    "No licensed Niagara runtime or field qualification has passed.",
                ],
            ),
            CapabilityPack(
                id="lbnl-plant-controls-v1",
                name="LBNL plant-controls source package",
                version="0.1.0",
                equipment_families=[
                    "plant.chilled-water",
                    "plant.hot-water",
                    "plant.heat-pump",
                    "plant.cooling-tower",
                    "hydronic.pump",
                ],
                sequence_families=["LBNL_PLANT_CONTROLLER"],
                stage="product-wired",
                status=PackStatus.QUALIFYING,
                supported_blocks=SUPPORTED_BLOCKS,
                artifact_coverage=ArtifactCoverage(
                    logic=True,
                    point_mapping=True,
                    tags=True,
                    alarms=True,
                    schedules=True,
                    histories=True,
                    graphics=True,
                    template_diff=False,
                ),
                verification_coverage=VerificationCoverage(
                    structural=True,
                    deterministic=True,
                    independent_rules=True,
                    trajectory=True,
                ),
                source_basis=[
                    "Pinned LBNL Modelica Buildings Templates.Plants.Controls source",
                    "38/38 retained translation, execution, and target-package audit",
                    "BACTalk typed-IR interpreter and deterministic acceptance oracle",
                ],
                limitations=[
                    "Stateful controllers emit exact Niagara ProgramObject source and a wiring "
                    "plan, not a licensed-runtime-compiled BOG.",
                    "Contractor jobs must map the controller's complete public interface and "
                    "provide independent acceptance tests for every output.",
                    "Licensed Workbench compilation, runtime parity, hardware-in-loop, and field "
                    "qualification remain mandatory before deployment.",
                ],
            ),
            CapabilityPack(
                id="lbnl-g36-controller-source-v1",
                name="LBNL G36 controller source lane",
                version="0.1.0",
                equipment_families=[
                    "terminal.vav.cooling-only",
                    "terminal.vav.reheat",
                    "terminal.fan-powered",
                    "terminal.dual-duct",
                    "ahu.single-zone",
                    "ahu.multi-zone-vav",
                    "zone.fan-coil",
                ],
                sequence_families=["LBNL_G36_CONTROLLER"],
                stage="product-wired",
                status=PackStatus.QUALIFYING,
                supported_blocks=SUPPORTED_BLOCKS,
                artifact_coverage=ArtifactCoverage(
                    logic=True,
                    point_mapping=True,
                    tags=True,
                    alarms=True,
                    schedules=True,
                    histories=True,
                    graphics=True,
                    template_diff=False,
                ),
                verification_coverage=VerificationCoverage(
                    structural=True,
                    deterministic=True,
                    independent_rules=True,
                    trajectory=True,
                ),
                source_basis=[
                    "Pinned LBNL Modelica Buildings G36 source",
                    "modelica-json CXF and Open Control Engine validation",
                    "Exact stock or generated ProgramObject target assessment",
                ],
                limitations=[
                    "This lane packages configured source controllers and subsequences; it does "
                    "not claim that every catalog entry is a complete equipment application.",
                    "Controllers without complete typed IR and an exact Niagara target fail "
                    "closed during job planning.",
                    "Licensed Workbench compilation, runtime parity, hardware-in-loop, and field "
                    "qualification remain mandatory before deployment.",
                ],
            ),
        ]
        discovered = [
            ("terminal.vav.cooling-only", "Cooling-only VAV", ["BuildingMOTIF G36", "Haxall"]),
            ("terminal.vav.reheat", "VAV with reheat", ["LBNL OBC", "BuildingMOTIF", "Haxall"]),
            ("terminal.fan-powered", "Fan-powered terminal", ["BuildingMOTIF G36", "Haxall"]),
            ("terminal.dual-duct", "Dual-duct terminal", ["BuildingMOTIF G36", "Haxall"]),
            ("ahu.single-zone", "Single-zone AHU / RTU", ["LBNL OBC", "BuildingMOTIF G36"]),
            ("ahu.multi-zone-vav", "Multiple-zone VAV AHU", ["LBNL OBC", "BuildingMOTIF G36"]),
            ("ahu.doas", "Dedicated outdoor-air system", ["Brick", "ASHRAE 223P"]),
            (
                "plant.chilled-water",
                "Chilled-water plant",
                ["BuildingMOTIF chiller plant", "ASHRAE 223P"],
            ),
            ("plant.hot-water", "Hot-water / boiler plant", ["ASHRAE 223P", "LBNL OBC"]),
            ("plant.heat-pump", "Heat-pump plant", ["LBNL OBC", "ASHRAE 223P"]),
            ("plant.cooling-tower", "Cooling tower / heat rejection", ["Brick", "ASHRAE 223P"]),
            ("hydronic.pump", "Hydronic pump and lead/lag", ["BuildingMOTIF", "pybog kitControl"]),
            ("zone.fan-coil", "Fan-coil unit", ["BuildingMOTIF G36 AFDD", "Brick"]),
            ("zone.unit-heater", "Unit heater", ["ASHRAE 223P", "Brick"]),
            ("exhaust", "Exhaust and relief systems", ["BuildingMOTIF G36", "Haxall"]),
            ("lighting", "Lighting controls", ["Brick", "Haxall"]),
            ("metering", "Meters and energy points", ["Brick", "BuildingMOTIF"]),
        ]
        installed_by_family = {
            "terminal.vav.cooling-only": ["lbnl-g36-controller-source-v1"],
            "terminal.vav.reheat": [
                "g36-vav-reheat-mvp",
                "lbnl-g36-controller-source-v1",
            ],
            "terminal.fan-powered": ["lbnl-g36-controller-source-v1"],
            "terminal.dual-duct": ["lbnl-g36-controller-source-v1"],
            "ahu.single-zone": [
                "ahu-safety-cooling-v1",
                "ahu-duct-static-pi-v1",
                "lbnl-g36-controller-source-v1",
            ],
            "ahu.multi-zone-vav": [
                "ahu-safety-cooling-v1",
                "ahu-duct-static-pi-v1",
                "lbnl-g36-controller-source-v1",
            ],
            "zone.fan-coil": ["lbnl-g36-controller-source-v1"],
            "exhaust": ["exhaust-fan-proof-v1"],
            "hydronic.pump": ["two-pump-selector-v1", "lbnl-plant-controls-v1"],
            "plant.chilled-water": ["lbnl-plant-controls-v1"],
            "plant.hot-water": ["lbnl-plant-controls-v1"],
            "plant.heat-pump": ["lbnl-plant-controls-v1"],
            "plant.cooling-tower": ["lbnl-plant-controls-v1"],
        }
        target_compiled_families = {
            "terminal.vav.reheat",
            "ahu.single-zone",
            "ahu.multi-zone-vav",
            "exhaust",
            "hydronic.pump",
        }
        self.families = [
            EquipmentFamilyCapability(
                id=family_id,
                name=name,
                stage=(
                    "target-compiled"
                    if family_id in target_compiled_families
                    else "product-wired"
                    if family_id in installed_by_family
                    else "discovered"
                ),
                semantic_sources=sources,
                installed_pack_ids=installed_by_family.get(family_id, []),
                blocker=(
                    "Installed paths remain unqualified prototypes/source packages; licensed "
                    "runtime and field evidence are missing."
                    if family_id in installed_by_family
                    else "No complete Niagara compiler + verification pack is installed yet."
                ),
            )
            for family_id, name, sources in discovered
        ]

    def match_job(self, job: JobSpec) -> CapabilityPack | None:
        if job.control_graph is not None:
            return self.get("typed-control-graph-v1")
        for pack in self.packs:
            if job.sequence.family in pack.sequence_families:
                return pack
        return None

    def get(self, pack_id: str) -> CapabilityPack:
        for pack in self.packs:
            if pack.id == pack_id:
                return pack
        raise KeyError(pack_id)

    def release_assessment(self, pack_id: str) -> dict[str, Any]:
        """Evaluate the non-negotiable gates for a production-supported pack."""

        pack = self.get(pack_id)
        artifact_gates = {
            "artifact.logic": pack.artifact_coverage.logic,
            "artifact.point_mapping": pack.artifact_coverage.point_mapping,
            "artifact.tags": pack.artifact_coverage.tags,
            "artifact.alarms": pack.artifact_coverage.alarms,
            "artifact.schedules": pack.artifact_coverage.schedules,
            "artifact.histories": pack.artifact_coverage.histories,
            "artifact.graphics": pack.artifact_coverage.graphics,
            "artifact.template_diff": pack.artifact_coverage.template_diff,
        }
        verification_gates = {
            "verification.structural": pack.verification_coverage.structural,
            "verification.deterministic": pack.verification_coverage.deterministic,
            "verification.independent_rules": (pack.verification_coverage.independent_rules),
            "verification.trajectory": pack.verification_coverage.trajectory,
            "verification.fault_injection": pack.verification_coverage.fault_injection,
            "verification.recovery": pack.verification_coverage.recovery,
            "verification.dynamic_building": (pack.verification_coverage.dynamic_building),
            "verification.niagara_runtime": pack.verification_coverage.niagara_runtime,
            "verification.field_qualified": pack.verification_coverage.field_qualified,
        }
        gates = [
            {
                "id": gate_id,
                "passed": passed,
                "category": gate_id.split(".", 1)[0],
                "requirement": gate_id.split(".", 1)[1].replace("_", " "),
            }
            for gate_id, passed in {**artifact_gates, **verification_gates}.items()
        ]
        blockers = [gate["id"] for gate in gates if not gate["passed"]]
        return {
            "pack_id": pack.id,
            "eligible_for_production_support": (
                not blockers
                and pack.stage == "production-supported"
                and pack.status == PackStatus.SUPPORTED
            ),
            "passed_gates": len(gates) - len(blockers),
            "total_gates": len(gates),
            "blocking_gate_ids": blockers,
            "gates": gates,
            "policy": (
                "Every artifact and verification gate must pass, and the pack must be promoted "
                "through field qualification before production support."
            ),
        }

    def inventory(self) -> dict[str, Any]:
        return {
            "production_ready": all(pack.production_ready for pack in self.packs),
            "policy": (
                "A reference model or semantic template is not a deployable equipment pack. "
                "Production support requires compiled artifacts, independent verification, "
                "Niagara runtime qualification, and field evidence."
            ),
            "summary": {
                "installed_packs": len(self.packs),
                "production_supported_packs": sum(pack.production_ready for pack in self.packs),
                "catalogued_equipment_families": len(self.families),
                "target_compiled_families": sum(
                    family.stage == "target-compiled" for family in self.families
                ),
            },
            "packs": [
                {
                    **pack.model_dump(mode="json"),
                    "production_ready": pack.production_ready,
                    "release_assessment": self.release_assessment(pack.id),
                }
                for pack in self.packs
            ],
            "families": [family.model_dump(mode="json") for family in self.families],
        }
