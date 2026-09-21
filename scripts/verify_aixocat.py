from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from bactalk.compiler import NiagaraCompiler
from bactalk.domain import ControlGraph
from bactalk.integrations.aixocat import AixocatLibrary
from bactalk.stack_lock import locked_revision

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".vendor/aixocat"
EXPECTED_REVISION = locked_revision("aixocat")


def main() -> int:
    revision = subprocess.run(
        ["git", "-C", str(SOURCE), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if revision != EXPECTED_REVISION:
        raise RuntimeError(f"unexpected AixOCAT revision: {revision}")
    if not (SOURCE / "LICENSE").read_text(encoding="utf-8").startswith("MIT License"):
        raise RuntimeError("AixOCAT MIT license is missing")
    forbidden = [
        path.relative_to(SOURCE).as_posix()
        for path in SOURCE.rglob("*")
        if path.is_file()
        and ".git" not in path.parts
        and path.suffix.lower()
        in {".compiled-library", ".library", ".bootinfo", ".tizip"}
    ]
    if forbidden:
        raise RuntimeError(f"AixOCAT sparse checkout admitted vendor binaries: {forbidden}")

    library = AixocatLibrary(SOURCE)
    catalog = library.catalog()
    if catalog["pattern_count"] != 211 or catalog["translatable_count"] != 6:
        raise RuntimeError("AixOCAT allowlist counts changed")
    artifacts: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="bactalk-aixocat-") as directory:
        for pattern_id, parameters in (
            ("oscat.signal_processing.SCALE", {}),
            ("hydronic.components.FC_HeatingCurve", {}),
            ("oscat.automation.INTERLOCK", {"TL_seconds": 2.0}),
            ("oscat.automation.MANUAL", {}),
            ("oscat.control.DEAD_BAND", {}),
            ("oscat.control.DEAD_ZONE", {}),
        ):
            result = library.translate(pattern_id, parameters=parameters)
            graph = ControlGraph.model_validate(result["graph"])
            artifact = NiagaraCompiler().compile(
                graph, Path(directory) / f"{graph.name}.bog"
            )
            artifacts.append(
                {
                    "id": pattern_id,
                    "blocks": len(graph.blocks),
                    "links": len(graph.links),
                    "artifact_bytes": artifact.stat().st_size,
                    "vectors_passed": result["verification"]["passed"],
                }
            )
    print(
        json.dumps(
            {
                "schema": "bactalk.aixocat-contract/v1",
                "passed": True,
                "revision": revision,
                "cataloged_patterns": catalog["pattern_count"],
                "source_only_patterns": (
                    catalog["pattern_count"] - catalog["translatable_count"]
                ),
                "translated_patterns": artifacts,
                "vendor_binaries_admitted": False,
                "licensed_runtime_qualified": False,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
