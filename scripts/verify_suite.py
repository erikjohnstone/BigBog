from __future__ import annotations

import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = ROOT / ".bactalk/integration-evidence.json"

CHECKS = [
    ("core", [".venv/bin/pytest", "-q"]),
    ("aixocat", ["make", "aixocat-contract"]),
    ("pybog-equipment-examples", ["make", "pybog-examples-contract"]),
    ("buildingmotif", ["make", "buildingmotif-contract"]),
    ("alfalfa", ["make", "alfalfa-contract"]),
    ("bacnet-lab", ["make", "bacnet-lab-contract"]),
    (
        "independent-bacnet-simulator",
        ["make", "independent-bacnet-simulator-contract"],
    ),
    ("contractor-environment-pack", ["make", "environment-pack-contract"]),
    ("haxall", ["make", "haxall-contract"]),
    ("nhaystack", ["make", "nhaystack-contract"]),
    ("niagara-alarm-runtime", ["make", "niagara-alarm-contract"]),
    ("niagara-point-bindings", ["make", "niagara-binding-contract"]),
    ("niagara-px-graphics", ["make", "niagara-graphics-contract"]),
    ("niagara-program-codegen", ["make", "niagara-program-codegen-contract"]),
    ("niagara-station-assembly", ["make", "niagara-station-contract"]),
    ("whole-building-signals", ["make", "project-signal-contract"]),
    ("integration-use-audit", ["make", "integration-use-contract"]),
    ("constrain", ["make", "constrain-contract"]),
    ("dflexlibs", ["make", "dflexlibs-contract"]),
    ("open-control-library", ["make", "open-control-library-contract"]),
    ("niagara-program-library", ["make", "n4-hvac-library-contract"]),
    ("open-fdd", ["make", "open-fdd-contract"]),
    ("open-control-engine", ["make", "oce-contract"]),
    ("cdl-oce", ["make", "cdl-oce-contract"]),
    ("ctrl-flow", ["make", "ctrl-flow-contract"]),
    ("g36-coverage-audit", ["make", "g36-audit-contract"]),
    ("plant-controls", ["make", "plant-controls-contract"]),
    ("plant-contractor-job", ["make", "plant-job-contract"]),
    ("rumoca-modelica-flattener", ["make", "rumoca-contract"]),
    ("boptest-contract", ["make", "boptest-contract"]),
    ("volttron", ["make", "volttron-contract"]),
    # The two end-to-end workflow proofs. These drive the real API and the
    # real queue and worker rather than any single integration, so they are
    # the closest thing the suite has to a product-level check.
    ("contractor-workflow", ["make", "contractor-workflow"]),
    ("simulation-workflow", ["make", "simulation-workflow"]),
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    results: list[dict] = []
    for check_id, command in CHECKS:
        started = time.monotonic()
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        combined = "\n".join(
            value.strip() for value in (completed.stdout, completed.stderr) if value.strip()
        )
        results.append(
            {
                "id": check_id,
                "command": command,
                "passed": completed.returncode == 0,
                "returncode": completed.returncode,
                "duration_seconds": round(time.monotonic() - started, 3),
                "output_tail": combined[-8_000:],
            }
        )
        print(f"[{check_id}] {'PASS' if completed.returncode == 0 else 'FAIL'}")
    lock_path = ROOT / "ops/stack.lock.json"
    evidence = {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "passed": all(item["passed"] for item in results),
        "policy": (
            "Passing integration contracts proves the pinned development paths execute. It does "
            "not substitute for licensed Niagara, dynamic-building, hardware, or field "
            "qualification."
        ),
        "stack_lock_sha256": _sha256(lock_path),
        "checks": results,
    }
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = EVIDENCE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(EVIDENCE_PATH)
    print(json.dumps({"passed": evidence["passed"], "evidence": str(EVIDENCE_PATH)}))
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
