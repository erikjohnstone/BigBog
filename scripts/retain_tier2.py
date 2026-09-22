"""Retain the Tier 2 translations and Open Control Engine references (N8).

For every configuration in ``bactalk.library_tier2.CONFIGURATIONS``: translate the
controller with its parameter set (modelica-json + the importer), retain the same
envelope ``scripts/retain_library_translations.py`` writes for Tier 1, build the
mechanical scenarios, run them through the Open Control Engine and retain the output
trajectories as the D3 reference. Needs the vendored toolchain (``make
bootstrap-full``). A configuration that cannot be translated or executed is recorded
under ``blockers`` in ``src/bactalk/library_tier2/blockers.json`` so
``docs/coverage.md`` can name the exact reason.

Usage::

    PYTHONPATH=src .venv/bin/python scripts/retain_tier2.py [--only ID,ID] [--check]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from bactalk.integrations.g36_library import G36Library, G36RequiredParametersError
from bactalk.library_tier2 import (
    CONFIGURATIONS,
    CONFIGURATIONS_BY_ID,
    SCHEMA_REFERENCE,
    SCHEMA_TRANSLATION,
    probe_cases,
    retained_translation,
    scenarios_for,
)
from bactalk.stack_lock import stack_lock_path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "bactalk" / "library_tier2"
TRANSLATIONS = PACKAGE / "translations"
REFERENCES = PACKAGE / "references"
BLOCKERS = PACKAGE / "blockers.json"
NOTE = (
    "Retained so a base install can build the Tier 2 job without the vendored "
    "translation toolchain (GOAL-NATIVE-BOG.md N8). Regenerate with scripts/retain_tier2.py."
)


def _lock_component(name: str) -> dict[str, Any]:
    lock = json.loads(stack_lock_path().read_text(encoding="utf-8"))
    components = lock.get("components", lock)
    entry = components[name]
    return {
        "repository": entry["repository"],
        "revision": entry["revision"],
        "tag": entry.get("release") or entry.get("tag"),
    }


def translation_envelope(library: G36Library, config_id: str) -> dict[str, Any]:
    config = CONFIGURATIONS_BY_ID[config_id]
    fresh = library.translate(
        config.controller_id,
        execution_profile=config.execution_profile,  # type: ignore[arg-type]
        parameters=dict(config.parameters),
    )
    if fresh["typed_ir"] is None:
        lowering = fresh["lowering"]
        reasons = []
        if lowering.get("unsupported_classes"):
            reasons.append("importer lacks " + ", ".join(lowering["unsupported_classes"]))
        if lowering.get("missing_components"):
            reasons.append("missing components " + ", ".join(lowering["missing_components"][:5]))
        if lowering.get("exactness_blockers"):
            reasons.append("; ".join(lowering["exactness_blockers"][:2]))
        if not reasons:
            reasons.append(json.dumps(lowering)[:300])
        raise RuntimeError("not translatable to the typed IR: " + " | ".join(reasons))
    template = library.job_template(
        config.controller_id,
        parameters=dict(config.parameters),
        execution_profile=config.execution_profile,  # type: ignore[arg-type]
    )
    lock = _lock_component("modelica-buildings")
    assessment = template["target_assessment"]
    return {
        "schema": SCHEMA_TRANSLATION,
        "configuration_id": config_id,
        "controller_id": config.controller_id,
        "execution_profile": config.execution_profile,
        "interface": fresh["interface"],
        "library": "g36",
        "niagara_target": {
            "complete": bool(assessment["complete"]),
            "generated_program_count": assessment.get("generated_program_count"),
        },
        "note": NOTE,
        "parameters": dict(config.parameters),
        "points": template["points"],
        "source": {
            "relative_path": fresh["controller"]["relative_path"],
            "repository": lock["repository"],
            "revision": lock["revision"],
            "source_sha256": fresh["controller"]["source_sha256"],
            "tag": lock["tag"],
        },
        "translator": {
            "cxf_source_sha256": fresh["lowering"]["source_sha256"],
            "lowering_schema": fresh["lowering"]["schema"],
            "name": str(fresh["translator"]),
            "runtime": str(fresh["runtime"]),
        },
        "typed_ir": fresh["typed_ir"],
    }


def _case_samples(case: Any, integer_inputs: set[str]) -> list[dict[str, Any]]:
    def cast(inputs: dict[str, Any]) -> dict[str, Any]:
        return {
            name: (int(value) if name in integer_inputs and not isinstance(value, bool) else value)
            for name, value in inputs.items()
        }

    return [
        {"time": scan * case.step_seconds, "inputs": cast(case.inputs)}
        for scan in range(case.repeat + 1)
    ]


def reference_envelope(library: G36Library, config_id: str) -> dict[str, Any]:
    config = CONFIGURATIONS_BY_ID[config_id]
    translation = retained_translation(config_id)
    integer_inputs = {
        port["label"]
        for port in translation["interface"]["inputs"]
        if "Integer" in str(port.get("type"))
    }
    cases = []
    runtime = profile = None
    absent: list[str] = []
    for case in probe_cases(config_id):
        # A conditional input (``if have_...``) is part of the translated interface but
        # absent from the engine's instance for this parameter set; the engine names
        # it, the scenario drops it and the reference records the omission.
        while True:
            inputs = {k: v for k, v in case.inputs.items() if k not in absent}
            probe = case.model_copy(update={"inputs": inputs})
            try:
                result = library.execute(
                    config.controller_id,
                    samples=_case_samples(probe, integer_inputs),
                    parameters=dict(config.parameters),
                )
                break
            except RuntimeError as exc:
                match = re.search(r"unknown scenario input: \S*[#.](\w+)$", str(exc).strip())
                if match is None or match.group(1) in absent or len(absent) > 32:
                    raise
                absent.append(match.group(1))
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
    if absent:
        # The scenario list itself depends on the inputs, so rebuild it without the
        # absent ones and keep only the cases that still exist.
        kept = {s.name for s in scenarios_for(config_id, absent_inputs=absent)}
        cases = [case for case in cases if case["name"] in kept]
    return {
        "schema": SCHEMA_REFERENCE,
        "configuration_id": config_id,
        "absent_inputs": sorted(absent),
        "controller_id": config.controller_id,
        "runtime": runtime,
        "execution_profile": profile,
        "source": translation["source"],
        "translator": translation["translator"],
        "parameters": dict(config.parameters),
        "note": (
            "Open Control Engine output trajectories for the mechanical Tier 2 scenarios; "
            "the third leg of the three-way differential (D3) and the source of the "
            "reference-derived expectations. Regenerate with scripts/retain_tier2.py."
        ),
        "cases": cases,
    }


def _render(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=1, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--only", help="comma-separated configuration ids")
    parser.add_argument("--check", action="store_true", help="compare with the retained copies")
    parser.add_argument(
        "--references-only", action="store_true", help="keep the retained translations"
    )
    parser.add_argument(
        "--resume", action="store_true", help="skip configurations already fully retained"
    )
    args = parser.parse_args(argv)
    selected = (
        [CONFIGURATIONS_BY_ID[item] for item in args.only.split(",")]
        if args.only
        else list(CONFIGURATIONS)
    )
    library = G36Library()
    blockers: dict[str, Any] = (
        json.loads(BLOCKERS.read_text(encoding="utf-8")) if BLOCKERS.is_file() else {}
    )
    drift = 0
    for config in selected:
        started = time.time()
        if (
            args.resume
            and (TRANSLATIONS / config.translation_file).is_file()
            and (REFERENCES / config.translation_file).is_file()
        ):
            print(f"kept  {config.id}", flush=True)
            continue
        try:
            if not args.references_only or not (TRANSLATIONS / config.translation_file).is_file():
                translation = translation_envelope(library, config.id)
                rendered = _render(translation)
                path = TRANSLATIONS / config.translation_file
                if args.check:
                    if (path.read_text(encoding="utf-8") if path.is_file() else "") != rendered:
                        drift += 1
                        print(f"DRIFT translation {config.id}")
                else:
                    TRANSLATIONS.mkdir(parents=True, exist_ok=True)
                    path.write_text(rendered, encoding="utf-8")
                    retained_translation.cache_clear()
            reference = reference_envelope(library, config.id)
            rendered = _render(reference)
            path = REFERENCES / config.translation_file
            if args.check:
                if (path.read_text(encoding="utf-8") if path.is_file() else "") != rendered:
                    drift += 1
                    print(f"DRIFT reference {config.id}")
                else:
                    print(f"ok    {config.id}")
            else:
                REFERENCES.mkdir(parents=True, exist_ok=True)
                path.write_text(rendered, encoding="utf-8")
                blockers.pop(config.id, None)
                print(
                    f"wrote {config.id}: {len(reference['cases'])} cases "
                    f"in {time.time() - started:.0f}s",
                    flush=True,
                )
        except G36RequiredParametersError as exc:
            blockers[config.id] = {"stage": "parameters", "reason": str(exc)}
            print(f"BLOCKED {config.id}: {exc}", flush=True)
        except Exception as exc:  # noqa: BLE001 - every blocker is recorded, not hidden
            blockers[config.id] = {
                "stage": "translation"
                if not (TRANSLATIONS / config.translation_file).is_file()
                else "reference",
                "reason": f"{type(exc).__name__}: {str(exc)[:600]}",
            }
            print(f"BLOCKED {config.id}: {type(exc).__name__}: {str(exc)[:300]}", flush=True)
            traceback.print_exc(limit=2)
    if not args.check:
        BLOCKERS.write_text(json.dumps(blockers, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
