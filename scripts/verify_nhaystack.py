from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from phable.io.ph_zinc import ph_from_zinc

from bactalk.agent import SequencePackPlanner
from bactalk.demo import demo_job
from bactalk.integrations.nhaystack import (
    NHAYSTACK_REVISION,
    build_readonly_nhaystack_export,
)

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / ".vendor/nhaystack"

STUBS = {
    "javax/baja/sys/BValue.java": "package javax.baja.sys; public class BValue {}\n",
    "javax/baja/sys/BComponent.java": (
        "package javax.baja.sys; import java.util.HashMap; import java.util.Map; "
        "public class BComponent extends BValue { private final Map<String,BValue> props="
        "new HashMap<String,BValue>(); public BValue get(String n){return props.get(n);} "
        "public void add(String n,BValue v){if(props.containsKey(n)) throw new "
        "IllegalStateException(\"slot exists\"); props.put(n,v);} "
        "public void setForTest(String n,BValue v){props.put(n,v);} }\n"
    ),
    "javax/baja/naming/BOrd.java": (
        "package javax.baja.naming; import java.util.HashMap; import java.util.Map; "
        "import javax.baja.sys.BComponent; import javax.baja.sys.BValue; public class BOrd { "
        "private final String value; private static final Map<String,BComponent> values="
        "new HashMap<String,BComponent>(); private BOrd(String v){value=v;} "
        "public static BOrd make(String v){return new BOrd(v);} "
        "public static void register(String v,BComponent c){values.put(v,c);} "
        "public static void clear(){values.clear();} public BValue get(BComponent c,Object x){"
        "return values.get(value);} }\n"
    ),
    "nhaystack/BHDict.java": (
        "package nhaystack; import javax.baja.sys.BValue; public final class BHDict extends "
        "BValue { public static final String HAYSTACK_IDENTIFIER=\"haystack\"; private final "
        "String zinc; private BHDict(String z){zinc=z;} public static BHDict make(String z){"
        "return new BHDict(z);} public boolean equals(Object o){return o instanceof BHDict && "
        "zinc.equals(((BHDict)o).zinc);} public int hashCode(){return zinc.hashCode();} }\n"
    ),
}


def _compile_and_execute_installer(
    java_name: str,
    java_source: str,
    annotations: list[dict[str, str]],
) -> None:
    class_name = java_name.removesuffix(".java")
    registrations = "\n".join(
        f'    BOrd.register({json.dumps(item["ord"])}, new BComponent());'
        for item in annotations
    )
    assertions = "\n".join(
        f'    if (BOrd.make({json.dumps(item["ord"])}).get(context, null) == null) '
        'throw new RuntimeException("unresolved component");'
        for item in annotations
    )
    collision_ord = annotations[-1]["ord"]
    harness = f"""package com.bactalk.generated;
import javax.baja.naming.BOrd;
import javax.baja.sys.BComponent;
import nhaystack.BHDict;
public final class InstallerHarness {{
  public static void main(String[] args) throws Exception {{
    BOrd.clear();
    BComponent context = new BComponent();
{registrations}
    {class_name}.apply(context);
    {class_name}.apply(context);
{assertions}
    BComponent collision = (BComponent) BOrd.make({json.dumps(collision_ord)}).get(context, null);
    collision.setForTest("haystack", BHDict.make("point bogus"));
    boolean refused = false;
    try {{ {class_name}.apply(context); }}
    catch (IllegalStateException expected) {{ refused = true; }}
    if (!refused) throw new RuntimeException("differing tags were overwritten");
    System.out.println("idempotent=true collision_refused=true");
  }}
}}
"""
    with tempfile.TemporaryDirectory(prefix="bactalk-nhaystack-contract-") as raw_directory:
        directory = Path(raw_directory)
        for relative_path, content in STUBS.items():
            path = directory / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        generated = directory / "com/bactalk/generated" / java_name
        generated.parent.mkdir(parents=True, exist_ok=True)
        generated.write_text(java_source, encoding="utf-8")
        harness_path = generated.parent / "InstallerHarness.java"
        harness_path.write_text(harness, encoding="utf-8")
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
            raise RuntimeError(f"generated nHaystack installer Java is invalid:\n{compiled.stderr}")
        executed = subprocess.run(
            ["java", "-cp", str(classes), "com.bactalk.generated.InstallerHarness"],
            capture_output=True,
            text=True,
            check=False,
        )
        if executed.returncode != 0 or "collision_refused=true" not in executed.stdout:
            raise RuntimeError(
                "generated nHaystack installer contract failed:\n"
                + executed.stdout
                + executed.stderr
            )


def _read_readme(vendor: Path) -> str:
    """Read the upstream readme whatever case it is published in.

    nHaystack ships `readme.md`; a hardcoded `README.md` resolves only on a
    case-insensitive filesystem, so the contract failed on Linux.
    """
    for name in ("readme.md", "README.md", "ReadMe.md"):
        candidate = vendor / name
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    raise RuntimeError(
        f"nHaystack readme is missing from {vendor}; the deployment contract "
        "cannot be verified"
    )


def main() -> int:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=VENDOR,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if revision != NHAYSTACK_REVISION:
        raise RuntimeError(f"nHaystack revision drift: {revision}")
    # The upstream HTML contains a legacy single-byte copyright glyph.
    license_text = (VENDOR / "license.html").read_text(encoding="latin-1")
    if "Academic Free License" not in license_text or "v. 3.0" not in license_text:
        raise RuntimeError("nHaystack AFL-3.0 license is missing")

    tag_manager = (
        VENDOR / "nhaystack-rt/src/nhaystack/server/TagManager.java"
    ).read_text(encoding="utf-8")
    readme = _read_readme(VENDOR)
    bhdict = (VENDOR / "nhaystack-rt/src/nhaystack/BHDict.java").read_text(encoding="utf-8")
    for anchor in (
        "createComponentTags(BComponent comp)",
        'hdb.add("n4SlotPath", slotPath)',
        'hdb.add("point")',
        'hdb.add("cur")',
        'hdb.add("his")',
    ):
        if anchor not in tag_manager:
            raise RuntimeError(f"nHaystack source contract missing {anchor!r}")
    if "Actions->Rebuild Cache" not in readme:
        raise RuntimeError("nHaystack cache-rebuild deployment contract is missing")
    for anchor in (
        "public static BHDict make(String s)",
        'must be stored in a property called \'haystack\'',
        "public static HDict findTagAnnotation(BComponent comp)",
    ):
        if anchor not in bhdict:
            raise RuntimeError(f"nHaystack BHDict contract missing {anchor!r}")

    job = demo_job()
    graph = SequencePackPlanner().plan(job)
    export = build_readonly_nhaystack_export(job, graph)
    zinc = next(
        item.content for item in export.artifacts if item.relative_path == "expected-readback.zinc"
    )
    grid = ph_from_zinc(zinc)
    points = [row for row in grid.rows if "point" in row]
    historized = [row for row in points if "his" in row]
    if len(points) != len(job.points) or len(historized) != 1:
        raise RuntimeError("generated nHaystack projection does not match the compiled job")
    if any("write" in row or "writeVal" in row for row in grid.rows):
        raise RuntimeError("read-only nHaystack projection exposed a write capability")
    java_artifact = next(item for item in export.artifacts if item.relative_path.endswith(".java"))
    _compile_and_execute_installer(
        java_artifact.relative_path,
        java_artifact.content,
        export.manifest["tag_annotations"],
    )

    print(
        json.dumps(
            {
                "passed": True,
                "revision": revision,
                "license": "AFL-3.0",
                "records": len(grid.rows),
                "points": len(points),
                "historized_points": len(historized),
                "writes_enabled": False,
                "tag_annotations": export.manifest["tag_annotation_count"],
                "generated_java_compiled_against_contract_stubs": True,
                "tag_installer_idempotent": True,
                "existing_tag_collision_refused": True,
                "licensed_runtime_qualified": False,
                "proof": [
                    "pinned-source-contract",
                    "generated-zinc-round-trip",
                    "compiled-history-readback-expectation",
                    "read-only-operation-boundary",
                    "compiled-generated-tag-installer",
                    "idempotence-and-collision-contract",
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
