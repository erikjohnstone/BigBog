"""Retain Open Control Engine reference traces for the Tier 1 acceptance suites.

The three-way differential (GOAL-NATIVE-BOG.md N7, D3) compares the exported
``.bog`` in the Shadow Runtime, the IR interpreter and the item's source of
truth. For Tier 1 that truth is the LBNL controller executed by the Open Control
Engine. This script runs every acceptance case of both retained demo jobs
through OCE and stores the output trajectories under
``src/bactalk/library_demo/references/`` so a base install can run D3;
``tests/test_native_bog_differential.py`` re-runs OCE on the integration tier
and fails if the retained copy drifts.

Usage::

    PYTHONPATH=src .venv/bin/python scripts/retain_reference_traces.py [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from bactalk.domain import AcceptanceCase, JobSpec
from bactalk.integrations.g36_library import G36Library
from bactalk.library_demo import (
    RETAINED,
    lbnl_multizone_ahu_demo_job,
    lbnl_vav_reheat_demo_job,
    retained_translation,
)

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "src" / "bactalk" / "library_demo" / "references"
SCHEMA = "bactalk.retained-reference-trace/v1"
JOBS = {
    "TerminalUnits.Reheat.Controller": lbnl_vav_reheat_demo_job,
    "AHUs.MultiZone.VAV.Controller": lbnl_multizone_ahu_demo_job,
}


def case_samples(case: AcceptanceCase, integer_inputs: set[str]) -> list[dict[str, Any]]:
    """The explicit-time sample list OCE takes: one row per scan boundary, t=0 first."""

    def cast(inputs: dict[str, float | bool]) -> dict[str, Any]:
        return {
            name: (int(value) if name in integer_inputs and not isinstance(value, bool) else value)
            for name, value in inputs.items()
        }

    rows: list[dict[str, Any]] = []
    if case.timeline:
        current: dict[str, float | bool] = {}
        time_seconds = 0.0
        for index, phase in enumerate(case.timeline):
            current.update(phase.inputs)
            if index == 0:
                rows.append({"time": 0.0, "inputs": cast(current)})
            for _ in range(phase.repeat):
                time_seconds += phase.step_seconds
                rows.append({"time": time_seconds, "inputs": cast(current)})
        return rows
    for scan in range(case.repeat + 1):
        rows.append({"time": scan * case.step_seconds, "inputs": cast(case.inputs)})
    return rows


def reference_for(job: JobSpec, library: G36Library) -> dict[str, Any]:
    controller_id = job.sequence.controller_id
    assert controller_id is not None
    retained = retained_translation(controller_id)
    integer_inputs = {
        port["label"]
        for port in retained["interface"]["inputs"]
        if "Integer" in str(port.get("type"))
    }
    cases = []
    runtime = None
    profile = None
    for case in job.acceptance_tests:
        result = library.execute(
            controller_id,
            samples=case_samples(case, integer_inputs),
            parameters=dict(retained["parameters"]),
        )
        runtime = result["runtime"]
        profile = result["execution_profile"]
        labels = {port["id"]: port["label"] for port in result["interface"]["outputs"]}
        rows = result["trace"]["trace"]
        outputs: dict[str, list[Any]] = {label: [] for label in labels.values()}
        for row in rows:
            for port_id, cell in row["outputs"].items():
                outputs[labels[port_id]].append(cell["value"])
        cases.append(
            {
                "name": case.name,
                "times": [float(row["time"]) for row in rows],
                "outputs": outputs,
            }
        )
    return {
        "schema": SCHEMA,
        "controller_id": controller_id,
        "runtime": runtime,
        "execution_profile": profile,
        "source": retained["source"],
        "translator": retained["translator"],
        "parameters": retained["parameters"],
        "note": (
            "Open Control Engine output trajectories for the retained acceptance cases; the "
            "third leg of the three-way differential (D3). Regenerate with "
            "scripts/retain_reference_traces.py after changing the cases or the pin."
        ),
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="compare with the retained copy")
    args = parser.parse_args(argv)
    library = G36Library()
    drift = 0
    for controller_id, filename in RETAINED.items():
        job = JOBS[controller_id]()
        fresh = reference_for(job, library)
        path = DESTINATION / filename
        rendered = json.dumps(fresh, indent=2, sort_keys=True) + "\n"
        if args.check:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current != rendered:
                drift += 1
                print(f"DRIFT {path.relative_to(ROOT)}")
            else:
                print(f"ok    {path.relative_to(ROOT)}")
            continue
        path.write_text(rendered, encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)} ({len(fresh['cases'])} cases)")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
