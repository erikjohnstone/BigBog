from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / ".vendor/pybog/examples"
REPRESENTATIVE_EXAMPLES = [
    "hvac_ahu_fan_control.py",
    "hvac_simple_chiller_plant_one.py",
    "hvac_two_pump_rotator.py",
    "hvac_g36_ahu_supply_temp_reset.py",
    "schedule_bool_example.py",
]


def main() -> int:
    results: list[dict] = []
    for filename in REPRESENTATIVE_EXAMPLES:
        with tempfile.TemporaryDirectory(prefix="bactalk-pybog-") as directory:
            completed = subprocess.run(
                [sys.executable, str(EXAMPLES / filename), "-o", directory],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
                timeout=60,
            )
            artifacts = sorted(Path(directory).glob("*.bog"))
            if completed.returncode != 0 or len(artifacts) != 1:
                detail = (completed.stdout + completed.stderr)[-4_000:]
                raise RuntimeError(f"{filename} failed to compile: {detail}")
            artifact = artifacts[0]
            if not zipfile.is_zipfile(artifact):
                raise RuntimeError(f"{filename} did not emit a zip-based .bog")
            with zipfile.ZipFile(artifact) as archive:
                if archive.namelist() != ["file.xml"]:
                    raise RuntimeError(f"{filename} emitted an unexpected archive")
            results.append(
                {
                    "example": filename,
                    "artifact": artifact.name,
                    "bytes": artifact.stat().st_size,
                }
            )
    print(
        json.dumps(
            {
                "engine": "pybog equipment example contract",
                "version": "0.1.6",
                "catalog_examples": len(list(EXAMPLES.glob("*.py"))),
                "compiled_examples": results,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
