from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from bactalk.agent import SequencePackPlanner
from bactalk.demo import demo_job
from bactalk.integrations.niagara_alarms import AM8X_REVISION, build_niagara_alarm_export

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / ".vendor/am8x-control"
SOURCE = VENDOR / (
    "am8xControl-rt/src/com/sitecVendor/am8xControl/modbus/Am8xAlarmAutomation.java"
)


STUBS = {
    "javax/baja/sys/BValue.java": "package javax.baja.sys; public class BValue {}\n",
    "javax/baja/sys/Flags.java": (
        "package javax.baja.sys; public final class Flags { public static final int SUMMARY=1; }\n"
    ),
    "javax/baja/sys/BRelTime.java": (
        "package javax.baja.sys; public class BRelTime extends BValue { "
        "public static BRelTime make(long v){return new BRelTime();} }\n"
    ),
    "javax/baja/sys/BComponent.java": (
        "package javax.baja.sys; public class BComponent extends BValue { "
        "public BValue get(String n){return null;} "
        "public void add(String n,BValue v,int f){} }\n"
    ),
    "javax/baja/alarm/BAlarmClass.java": (
        "package javax.baja.alarm; public class BAlarmClass extends javax.baja.sys.BComponent {}\n"
    ),
    "javax/baja/alarm/BAlarmService.java": (
        "package javax.baja.alarm; public class BAlarmService extends javax.baja.sys.BComponent { "
        "public BAlarmClass lookupAlarmClass(String n){return null;} }\n"
    ),
    "javax/baja/alarm/ext/BLimitEnable.java": (
        "package javax.baja.alarm.ext; public class BLimitEnable { "
        "public void setHighLimitEnable(boolean v){} public void setLowLimitEnable(boolean v){} }\n"
    ),
    "javax/baja/alarm/ext/BAlarmSourceExt.java": (
        "package javax.baja.alarm.ext; public class BAlarmSourceExt extends "
        "javax.baja.sys.BComponent { "
        "public void setOffnormalAlgorithm(Object v){} public void setAlarmClass(String v){} "
        "public void setSourceName(javax.baja.util.BFormat v){} "
        "public void setTimeDelay(javax.baja.sys.BRelTime v){} "
        "public void setToOffnormalText(javax.baja.util.BFormat v){} "
        "public void setToNormalText(javax.baja.util.BFormat v){} }\n"
    ),
    "javax/baja/alarm/ext/offnormal/BBooleanChangeOfStateAlgorithm.java": (
        "package javax.baja.alarm.ext.offnormal; public class BBooleanChangeOfStateAlgorithm { "
        "public void setAlarmValue(boolean v){} }\n"
    ),
    "javax/baja/alarm/ext/offnormal/BOutOfRangeAlgorithm.java": (
        "package javax.baja.alarm.ext.offnormal; public class BOutOfRangeAlgorithm { "
        "public void setLimitEnable(javax.baja.alarm.ext.BLimitEnable v){} "
        "public void setHighLimit(double v){} public void setLowLimit(double v){} "
        "public void setDeadband(double v){} }\n"
    ),
    "javax/baja/control/BControlPoint.java": (
        "package javax.baja.control; public class BControlPoint extends "
        "javax.baja.sys.BComponent {}\n"
    ),
    "javax/baja/naming/BOrd.java": (
        "package javax.baja.naming; public class BOrd { public static BOrd make(String v){return "
        "new BOrd();} public javax.baja.sys.BValue get(javax.baja.sys.BComponent c,Object x){"
        "return null;} }\n"
    ),
    "javax/baja/util/BFormat.java": (
        "package javax.baja.util; public class BFormat { public static BFormat make(String v){"
        "return new BFormat();} }\n"
    ),
}


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
    source_reference = SOURCE.read_text(encoding="utf-8")
    for anchor in (
        "new BAlarmClass()",
        "new BAlarmSourceExt()",
        "new BEnumChangeOfStateAlgorithm()",
        "new BOutOfRangeAlgorithm()",
        "ext.setAlarmClass(alarmClass)",
        "ext.setToOffnormalText",
        "ext.setToNormalText",
    ):
        if anchor not in source_reference:
            raise RuntimeError(f"am8x Niagara alarm contract missing {anchor!r}")

    job = demo_job()
    graph = SequencePackPlanner().plan(job)
    export = build_niagara_alarm_export(job, graph)
    java_artifact = next(item for item in export.artifacts if item.relative_path.endswith(".java"))
    plan_artifact = next(
        item for item in export.artifacts if item.relative_path == "niagara-alarm-plan.json"
    )
    plan = json.loads(plan_artifact.content)
    expected_ord = (
        "station:|slot:/Config/Drivers/BACnetNetwork/ExampleCampus/"
        "VAV_12/HighZoneTempAlarm"
    )
    if plan["extensions"][0]["point_ord"] != expected_ord:
        raise RuntimeError("generated alarm plan does not target the compiled point")
    if plan["licensed_runtime_qualified"]:
        raise RuntimeError("offline source generation cannot claim Niagara runtime qualification")
    if any(token in java_artifact.content for token in ("Am8x", "ESCLUSIONI", "GUASTI")):
        raise RuntimeError("vendor-specific fire-panel behavior leaked into generic alarm source")

    with tempfile.TemporaryDirectory(prefix="bactalk-alarm-contract-") as raw_directory:
        directory = Path(raw_directory)
        for relative_path, content in STUBS.items():
            path = directory / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        generated = directory / "com/bactalk/generated" / java_artifact.relative_path
        generated.parent.mkdir(parents=True, exist_ok=True)
        generated.write_text(java_artifact.content, encoding="utf-8")
        java_files = [str(path) for path in directory.rglob("*.java")]
        classes = directory / "classes"
        classes.mkdir()
        compiled = subprocess.run(
            ["javac", "-source", "8", "-target", "8", "-d", str(classes), *java_files],
            capture_output=True,
            text=True,
            check=False,
        )
        if compiled.returncode != 0:
            raise RuntimeError(f"generated Niagara alarm Java is invalid:\n{compiled.stderr}")

    print(
        json.dumps(
            {
                "passed": True,
                "revision": revision,
                "license": "Apache-2.0",
                "alarm_extensions": len(plan["extensions"]),
                "generated_java_compiled_against_contract_stubs": True,
                "licensed_runtime_qualified": False,
                "vendor_specific_logic_included": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
