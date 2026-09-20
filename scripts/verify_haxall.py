from __future__ import annotations

import json
import subprocess
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    executable = root / "ops/haxall/node_modules/.bin/xeto"
    fixture = root / "ops/haxall/fixtures/g36-reheat-vav.trio"
    completed = subprocess.run(
        [str(executable), "fits", str(fixture), "-graph", "-outFile", "stdout.zinc"],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if lines != ['ver:"3.0"', "id,msg"]:
        raise SystemExit(f"Haxall rejected the known-good G36 graph:\n{completed.stdout}")

    bad = fixture.read_text(encoding="utf-8").replace(
        "spec: @ph.points::ZoneCo2Sensor", "spec: @ph.points::ZoneAirTempSensor", 1
    )
    bad_path = root / ".bactalk/haxall-known-bad.trio"
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_text(bad, encoding="utf-8")
    rejected = subprocess.run(
        [str(executable), "fits", str(bad_path), "-graph", "-outFile", "stdout.zinc"],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if len([line for line in rejected.stdout.splitlines() if line.strip()]) <= 2:
        raise SystemExit("Haxall unexpectedly accepted the known-bad G36 graph")
    print(
        json.dumps(
            {
                "engine": "Haxall/Xeto",
                "version": "4.0.4",
                "schema": "ashrae.g36::G36ReheatVav",
                "known_good_errors": 0,
                "known_bad_rejected": True,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
