from __future__ import annotations

import io
import json
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from bactalk.agent import SequencePackPlanner
from bactalk.compiler import NiagaraCompiler
from bactalk.demo import demo_job, generalist_demo_job
from bactalk.integrations.niagara_station import (
    assemble_project_station_bog,
    assemble_station_bog,
)
from bactalk.integrations.niagara_template import NiagaraTemplateAnalyzer


def _bog(xml: str) -> bytes:
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("file.xml", xml.encode())
    return target.getvalue()


def _station(*, collision: bool = False, external_ref: bool = False) -> bytes:
    program = '<p n="VAV_12" t="b:Folder" h="c"/>' if collision else ""
    ref = '<p n="ExternalRef" t="b:Ord" v="h:c"/>' if external_ref else ""
    return _bog(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<bajaObjectGraph version="4.0">
  <p t="b:UnrestrictedFolder" m="b=baja">
    <p n="Config" t="b:Folder" h="1">
      <p n="Drivers" t="b:Folder">
        <p n="BACnetNetwork" t="b:Folder">
          <p n="ExampleCampus" t="b:Folder" h="a">
            {program}<p n="Preserved" t="b:Folder" h="b"/>
          </p>
        </p>
      </p>
    </p>
    <p n="Services" t="b:Folder" h="2">{ref}</p>
  </p>
</bajaObjectGraph>"""
    )


def main() -> int:
    job = demo_job()
    graph = SequencePackPlanner().plan(job)
    with tempfile.TemporaryDirectory(prefix="bactalk-station-contract-") as raw_directory:
        directory = Path(raw_directory)
        program_path = directory / "program.bog"
        NiagaraCompiler().compile(graph, program_path, deliverables=job.deliverables)
        template = _station()
        assembly = assemble_station_bog(
            template,
            program_path.read_bytes(),
            job,
            graph,
            mode="insert",
        )
        assembled_path = directory / "assembled.bog"
        assembled_path.write_bytes(assembly.content)
        summary = NiagaraTemplateAnalyzer().summarize(assembled_path)
        with zipfile.ZipFile(assembled_path) as archive:
            root = ElementTree.fromstring(archive.read("file.xml"))
        names = {item.get("n") for item in root.iter() if item.get("n")}
        if not {"VAV_12", "Preserved", "Services"} <= names:
            raise RuntimeError("station assembly did not preserve and insert expected components")

        collision_refused = False
        try:
            assemble_station_bog(
                _station(collision=True),
                program_path.read_bytes(),
                job,
                graph,
                mode="insert",
            )
        except ValueError as exc:
            collision_refused = "already contains" in str(exc)
        if not collision_refused:
            raise RuntimeError("station insert collision was not refused")

        external_ref_refused = False
        try:
            assemble_station_bog(
                _station(collision=True, external_ref=True),
                program_path.read_bytes(),
                job,
                graph,
                mode="replace",
            )
        except ValueError as exc:
            external_ref_refused = "outside the replacement target" in str(exc)
        if not external_ref_refused:
            raise RuntimeError("replacement with external handle references was not refused")

        ahu_job = generalist_demo_job().model_copy(update={"equipment_name": "AHU_1"})
        ahu_graph = SequencePackPlanner().plan(ahu_job)
        ahu_path = directory / "ahu.bog"
        NiagaraCompiler().compile(ahu_graph, ahu_path, deliverables=ahu_job.deliverables)
        project_assembly = assemble_project_station_bog(
            template,
            [
                (program_path.read_bytes(), job, graph),
                (ahu_path.read_bytes(), ahu_job, ahu_graph),
            ],
            mode="insert",
        )
        if project_assembly.manifest["program_count"] != 2:
            raise RuntimeError("multi-equipment station assembly omitted a program")

    print(
        json.dumps(
            {
                "passed": True,
                "action": assembly.manifest["action"],
                "target_program_ord": assembly.manifest["target_program_ord"],
                "handles_rebased": assembly.manifest["handle_rebase_count"],
                "analyzed_nodes": summary["diagnosis"]["node_count"],
                "unrelated_components_preserved": True,
                "insert_collision_refused": True,
                "replace_external_reference_refused": True,
                "atomic_project_programs": project_assembly.manifest["program_count"],
                "live_station_modified": False,
                "licensed_runtime_qualified": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
