from __future__ import annotations

import compileall
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".vendor/dflexlibs"


def main() -> int:
    license_text = (SOURCE / "License.txt").read_text(encoding="utf-8")
    if "Redistribution and use in source and binary forms" not in license_text:
        raise RuntimeError("DFLEXLIBS commercial-use license grant was not found")
    if not compileall.compile_dir(SOURCE / "dflexlibs", quiet=1):
        raise RuntimeError("DFLEXLIBS source did not compile")

    sys.path.insert(0, str(SOURCE))
    from dflexlibs.hvac.functions.fu_os_shed_single_step_adj_zone import (  # noqa: PLC0415
        shed_single_step_adj_zone,
    )
    from dflexlibs.hvac.functions.fu_os_zone_qualification_check import (  # noqa: PLC0415
        zone_qualification_check,
    )

    with redirect_stdout(io.StringIO()):
        shed = shed_single_step_adj_zone(
            "cool",
            20.0,
            24.0,
            1.0,
            18.0,
            30.0,
            [20.0],
            [24.0],
        )
        qualified = zone_qualification_check(
            "cool",
            24.0,
            20.0,
            27.0,
            [],
            "Zone_1",
            20.0,
            24.0,
            0.8,
            15.0,
            0.0,
            14.0,
            1.0,
            1.0,
            "celsius",
        )
        hands_off = zone_qualification_check(
            "cool",
            24.0,
            20.0,
            27.0,
            ["Zone_1"],
            "Zone_1",
            20.0,
            24.0,
            0.8,
            15.0,
            0.0,
            14.0,
            1.0,
            1.0,
            "celsius",
        )

    if shed != (20.0, 25.0, 1):
        raise RuntimeError(f"unexpected DFLEXLIBS cooling shed result: {shed!r}")
    if qualified is not True or hands_off is not False:
        raise RuntimeError("DFLEXLIBS zone qualification safety gates failed")

    print(
        json.dumps(
            {
                "passed": True,
                "revision": "9462cf2c732d9be50207cd846a6c6ce044695a80",
                "checks": [
                    "source-compilation",
                    "commercial-license-grant",
                    "zone-setpoint-shed",
                    "qualified-zone",
                    "hands-off-zone-rejection",
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
