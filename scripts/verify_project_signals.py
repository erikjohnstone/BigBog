from __future__ import annotations

import io
import json
import tempfile
import zipfile
from pathlib import Path

from bactalk.domain import (
    AcceptanceCase,
    Block,
    BlockKind,
    ControlGraph,
    DataType,
    JobSpec,
    Link,
    OutputExpectation,
    PointRole,
    PointSpec,
    RunStatus,
    SequenceSpec,
)
from bactalk.projects import (
    ProjectAcceptanceCase,
    ProjectAcceptancePhase,
    ProjectBuildRepository,
    ProjectBuildService,
    ProjectOutputExpectation,
    ProjectSignalBinding,
    ProjectSpec,
)
from bactalk.repository import RunRepository
from bactalk.service import WorkbenchService


def _job(equipment: str, input_name: str, output_name: str, role: PointRole) -> JobSpec:
    graph = ControlGraph(
        name=equipment,
        blocks=[
            Block(
                id=input_name,
                kind=BlockKind.BOOLEAN_INPUT,
                label=input_name,
                config={"default": False},
            ),
            Block(id=output_name, kind=BlockKind.BOOLEAN_OUTPUT, label=output_name),
        ],
        links=[Link(source=input_name, target=output_name, target_slot="in")],
    )
    return JobSpec(
        name=f"{equipment} controls",
        site="Contract Campus",
        equipment_name=equipment,
        sequence=SequenceSpec(family="CUSTOM", version="contract"),
        points=[
            PointSpec(
                name=input_name,
                label=input_name,
                data_type=DataType.BOOLEAN,
                role=role,
                default=False,
            ),
            PointSpec(
                name=output_name,
                label=output_name,
                data_type=DataType.BOOLEAN,
                role=PointRole.COMMAND,
                default=False,
            ),
        ],
        control_graph=graph,
        acceptance_tests=[
            AcceptanceCase(
                name="equipment pass-through",
                inputs={input_name: True},
                expectations=[OutputExpectation(target=output_name, value=True)],
            )
        ],
    )


def _station() -> bytes:
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<bajaObjectGraph version="4.0">
  <p t="b:UnrestrictedFolder" m="b=baja">
    <p n="Services" t="b:Folder" h="1"/>
  </p>
</bajaObjectGraph>"""
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("file.xml", xml)
    return target.getvalue()


def main() -> int:
    ahu = _job("AHU_1", "Occupied", "HeatingPlantRequest", PointRole.SENSOR)
    plant = _job(
        "BoilerPlant_1",
        "HeatingPlantRequest",
        "BoilerEnable",
        PointRole.STATUS,
    )
    project = ProjectSpec(
        name="Cross-equipment proof",
        site="Contract Campus",
        equipment=[ahu, plant],
        signal_bindings=[
            ProjectSignalBinding(
                source_equipment="AHU_1",
                source_point="HeatingPlantRequest",
                target_equipment="BoilerPlant_1",
                target_point="HeatingPlantRequest",
            )
        ],
        acceptance_tests=[
            ProjectAcceptanceCase(
                name="request propagation",
                phases=[
                    ProjectAcceptancePhase(
                        name="off",
                        inputs={"AHU_1.Occupied": False},
                        expectations=[
                            ProjectOutputExpectation(
                                equipment="BoilerPlant_1",
                                point="BoilerEnable",
                                value=False,
                            )
                        ],
                    ),
                    ProjectAcceptancePhase(
                        name="on",
                        inputs={"AHU_1.Occupied": True},
                        expectations=[
                            ProjectOutputExpectation(
                                equipment="BoilerPlant_1",
                                point="BoilerEnable",
                                value=True,
                            )
                        ],
                    ),
                ],
            )
        ],
        station_assembly_mode="insert",
    )
    with tempfile.TemporaryDirectory(prefix="bactalk-project-signals-") as raw:
        root = Path(raw)
        service = ProjectBuildService(
            ProjectBuildRepository(root / "projects"),
            WorkbenchService(RunRepository(root / "runs")),
        )
        record = service.build(project, station_template=_station())
        report = json.loads(Path(record.project_report_path).read_text(encoding="utf-8"))
        manifest = json.loads(
            Path(record.station_assembly_manifest_path).read_text(encoding="utf-8")
        )
        if record.status != RunStatus.READY_FOR_REVIEW or not report["passed"]:
            raise RuntimeError("cross-equipment acceptance did not pass")
        if manifest["cross_program_link_count"] != 1:
            raise RuntimeError("cross-equipment Niagara link was not emitted")
        observed = [
            assertion["observed"]
            for assertion in report["scenarios"][0]["assertions"]
        ]
        if observed != ["False", "True"]:
            raise RuntimeError("request did not propagate through both project states")

    print(
        json.dumps(
            {
                "passed": True,
                "equipment_programs": 2,
                "typed_signal_bindings": 1,
                "project_acceptance_phases": 2,
                "observed_downstream_states": observed,
                "offline_niagara_links": manifest["cross_program_link_count"],
                "licensed_runtime_qualified": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
