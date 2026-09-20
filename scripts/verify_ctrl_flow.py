from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from bactalk.integrations.ctrl_flow import CtrlFlowLibrary

ROOT = Path(__file__).resolve().parents[1]
REVISION = "9063e347b13b1a55f9b324ab35da01b5006492de"
LICENSE_SHA256 = "1d1367874c6d5f974749edc9fdbd8988a5ab3d73c6900bc03737f8547d95c29f"
AHU_TEMPLATE = "Buildings.Templates.AirHandlersFans.VAVMultiZone"
DRAW_THROUGH_SELECTION = (
    "Buildings.Templates.AirHandlersFans.VAVMultiZone.fanSupDra-fanSupDra"
)
NO_FAN = "Buildings.Templates.Components.Fans.None"


def main() -> int:
    source = ROOT / ".vendor/ctrl-flow-dev"
    actual_revision = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    actual_license_sha256 = hashlib.sha256((source / "LICENSE.txt").read_bytes()).hexdigest()
    if actual_revision != REVISION:
        raise RuntimeError(f"ctrl-flow revision mismatch: {actual_revision}")
    if actual_license_sha256 != LICENSE_SHA256:
        raise RuntimeError("ctrl-flow license digest mismatch")

    library = CtrlFlowLibrary(ROOT)
    catalog = library.catalog()
    baseline = library.schema(AHU_TEMPLATE)
    configured = library.configure(AHU_TEMPLATE, {DRAW_THROUGH_SELECTION: NO_FAN})
    if catalog["option_count"] != 2_593 or catalog["template_count"] != 3:
        raise RuntimeError("ctrl-flow catalog shape changed")
    if not any(field["instance_path"] == "fanSupBlo" for field in configured["fields"]):
        raise RuntimeError("ctrl-flow conditional fan branch did not activate")

    evidence = {
        "schema": "bactalk.ctrl-flow-contract/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "passed": True,
        "repository": "https://github.com/lbl-srg/ctrl-flow-dev",
        "revision": actual_revision,
        "license_sha256": actual_license_sha256,
        "template_count": catalog["template_count"],
        "option_count": catalog["option_count"],
        "baseline_visible_field_count": baseline["visible_field_count"],
        "configured_visible_field_count": configured["visible_field_count"],
        "evaluated_value_count": configured["evaluated_value_count"],
        "conditional_branch_proved": "fanSupBlo",
        "configuration_digest": configured["configuration_digest"],
        "niagara_code_generated": configured["downstream_boundary"][
            "niagara_code_generated"
        ],
        "live_writes_enabled": configured["safety"]["live_writes_enabled"],
    }
    target = ROOT / ".bactalk/ctrl-flow-evidence.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
