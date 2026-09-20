from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from bactalk.demo import demo_job
from bactalk.domain import JobSpec
from bactalk.integrations.niagara_bindings import (
    AM8X_LINK_SOURCE,
    AM8X_REVISION,
    build_niagara_binding_export,
)
from bactalk.sequences.g36_vav import build_g36_vav_reheat

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / ".vendor/am8x-control"

STUBS = {
    "javax/baja/sys/BValue.java": "package javax.baja.sys; public class BValue {}\n",
    "javax/baja/sys/Slot.java": "package javax.baja.sys; public class Slot {}\n",
    "javax/baja/sys/BComponent.java": (
        "package javax.baja.sys; public class BComponent extends BValue { "
        "public Slot getSlot(String n){return new Slot();} "
        "public BLink[] getLinks(){return new BLink[0];} "
        "public void add(String n,BValue v){} }\n"
    ),
    "javax/baja/sys/BLink.java": (
        "package javax.baja.sys; public class BLink extends BValue { "
        "public BLink(javax.baja.naming.BOrd o,String s,String t,boolean e){} "
        "public void setEnabled(boolean v){} public String getTargetSlotName(){return \"\";} "
        "public String getSourceSlotName(){return \"\";} "
        "public BComponent getSourceComponent(){return null;} }\n"
    ),
    "javax/baja/naming/BOrd.java": (
        "package javax.baja.naming; public class BOrd { public static BOrd make(String v){return "
        "new BOrd();} public javax.baja.sys.BValue get(javax.baja.sys.BComponent c,Object x){"
        "return null;} }\n"
    ),
}


def _job() -> JobSpec:
    payload = demo_job().model_dump(mode="json")
    priorities = {"DamperCommand": 8, "ValveCommand": 10}
    for point in payload["points"]:
        if point["bacnet_object"] is None:
            continue
        point["niagara_ord"] = (
            "station:|slot:/Config/Drivers/BacnetNetwork/VAV_12/Points/" + point["name"]
        )
        if point["name"] in priorities:
            point["niagara_write_priority"] = priorities[point["name"]]
    return JobSpec.model_validate(payload)


def main() -> int:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=VENDOR,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if revision != AM8X_REVISION:
        raise RuntimeError(f"am8x-control revision drift: {revision}")
    if "Apache License" not in (VENDOR / "LICENSE").read_text(encoding="utf-8"):
        raise RuntimeError("am8x-control Apache-2.0 license is missing")
    reference = (ROOT / AM8X_LINK_SOURCE).read_text(encoding="utf-8")
    for anchor in (
        "new BLink(sourceOrd, \"out\", targetSlotName, true)",
        "targetPoint.getLinks()",
        "targetPoint.add(null, link)",
    ):
        if anchor not in reference:
            raise RuntimeError(f"am8x Niagara link contract missing {anchor!r}")

    job = _job()
    export = build_niagara_binding_export(job, build_g36_vav_reheat(job))
    manifest = export.manifest
    if manifest["binding_count"] != 3 or manifest["unbound_mapped_points"]:
        raise RuntimeError("exact Niagara point bindings were not fully generated")
    targets = {item["point"]: item["target_slot"] for item in manifest["bindings"]}
    if targets != {"DamperCommand": "in8", "ValveCommand": "in10", "ZoneTemp": "in16"}:
        raise RuntimeError(f"unexpected Niagara binding target slots: {targets}")
    java_artifact = next(item for item in export.artifacts if item.relative_path.endswith(".java"))

    with tempfile.TemporaryDirectory(prefix="bactalk-binding-contract-") as raw_directory:
        directory = Path(raw_directory)
        for relative_path, content in STUBS.items():
            path = directory / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        generated = directory / "com/bactalk/generated" / java_artifact.relative_path
        generated.parent.mkdir(parents=True, exist_ok=True)
        generated.write_text(java_artifact.content, encoding="utf-8")
        classes = directory / "classes"
        classes.mkdir()
        compiled = subprocess.run(
            [
                "javac",
                "-source",
                "8",
                "-target",
                "8",
                "-d",
                str(classes),
                *(str(path) for path in directory.rglob("*.java")),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compiled.returncode != 0:
            raise RuntimeError(f"generated Niagara binding Java is invalid:\n{compiled.stderr}")

    print(
        json.dumps(
            {
                "passed": True,
                "revision": revision,
                "license": "Apache-2.0",
                "exact_point_bindings": manifest["binding_count"],
                "generated_java_compiled_against_contract_stubs": True,
                "target_collision_overwrite_allowed": False,
                "licensed_runtime_qualified": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
