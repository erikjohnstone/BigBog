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

from bactalk.integrations.cxf_arrays import _REDUCTIONS
from bactalk.integrations.g36_library import G36Library, G36RequiredParametersError
from bactalk.integrations.plant_controls_library import PlantControlsCdlLibrary
from bactalk.library_tier2 import (
    CONFIGURATIONS,
    CONFIGURATIONS_BY_ID,
    SCHEMA_REFERENCE,
    SCHEMA_TRANSLATION,
    absent_inputs,
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


LOCK_COMPONENT = {
    "release": "modelica-buildings",
    "plants": "modelica-buildings-plants",
    "templates": "modelica-buildings",
}
MODELICA_ROOT = {
    "release": ROOT / ".vendor" / "modelica-buildings",
    "plants": ROOT / ".vendor" / "modelica-buildings-plants",
    "templates": ROOT / ".vendor" / "modelica-buildings",
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
    lock = _lock_component(LOCK_COMPONENT[config.source])
    assessment = template["target_assessment"]
    return {
        "schema": SCHEMA_TRANSLATION,
        "configuration_id": config_id,
        "controller_id": config.controller_id,
        "execution_profile": config.execution_profile,
        "interface": fresh["interface"],
        "library": "plant_controls" if config.source == "templates" else "g36",
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

    if case.timeline:
        # A step scenario: t = 0 takes the first phase's inputs, then each phase's
        # inputs for its scans, on the same grid the single-phase cases use.
        samples = [{"time": 0.0, "inputs": cast(case.timeline[0].inputs)}]
        clock = 0.0
        for phase in case.timeline:
            for _ in range(phase.repeat):
                clock += phase.step_seconds
                samples.append({"time": clock, "inputs": cast(phase.inputs)})
        return samples
    return [
        {"time": scan * case.step_seconds, "inputs": cast(case.inputs)}
        for scan in range(case.repeat + 1)
    ]


def _without(case: Any, absent: list[str]) -> Any:
    """The case with the absent inputs dropped (from every phase of a step scenario)."""

    if case.timeline:
        return case.model_copy(
            update={
                "timeline": [
                    phase.model_copy(
                        update={
                            "inputs": {k: v for k, v in phase.inputs.items() if k not in absent}
                        }
                    )
                    for phase in case.timeline
                ]
            }
        )
    return case.model_copy(
        update={"inputs": {k: v for k, v in case.inputs.items() if k not in absent}}
    )


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
    # The probe cases already leave out the inputs the retained reference recorded as
    # absent, so the engine is told about them up front; new ones are learned below.
    absent: list[str] = list(absent_inputs(config_id))
    for case in probe_cases(config_id):
        # A conditional input (``if have_...``) is part of the translated interface but
        # absent from the engine's instance for this parameter set; the engine names
        # it, the scenario drops it and the reference records the omission.
        while True:
            probe = _without(case, absent)
            try:
                result = library.execute(
                    config.controller_id,
                    samples=_case_samples(probe, integer_inputs),
                    parameters=dict(config.parameters),
                    absent_inputs=list(absent),
                )
                break
            except RuntimeError as exc:
                match = re.search(r"unknown scenario input: \S*[#.](\w+)$", str(exc).strip())
                if match is None or match.group(1) in absent or len(absent) > 32:
                    raise
                absent.append(match.group(1))
        runtime = result["runtime"]
        profile = result["execution_profile"]
        if runtime != "Open Control Engine":
            # A reviewed composite (a Modelica-equation utility the engine cannot
            # ingest) falls back to BACTalk's own interpreter; that is not an
            # independent reference, so the row is a blocker, not a retained row.
            missing = result["engine_report"].get("oce_missing_classes", [])
            raise RuntimeError(
                "the Open Control Engine cannot load "
                + ", ".join(missing)
                + " inside this controller, so only BACTalk's own interpreter runs it, "
                "which is not an independent reference"
            )
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


TEMPLATES_PACKAGE = ("Buildings", "Templates", "Plants", "Controls")
ARRAY_REDUCTIONS = frozenset(_REDUCTIONS)


def _equation_statements(text: str) -> list[str]:
    """The statements of a class's equation sections other than ``connect``."""

    body = re.sub(r"annotation\s*\((?:[^()]|\((?:[^()]|\([^()]*\))*\))*\)", "", text)
    statements: list[str] = []
    for section in re.findall(r"(?ms)^\s*equation\b(.*?)(?=^\s*end\s+\w+\s*;|\Z)", body):
        for statement in section.split(";"):
            # structural ``if have_inp then connect(u, y); else ...; end if``
            statement = re.sub(
                r"(?s)^(?:(?:end\s+if|else|(?:else)?if\b.*?\bthen)\s*)+", "", statement.strip()
            ).strip()
            if statement and not statement.startswith(("connect(", "annotation")):
                statements.append(statement)
    return statements


def non_cdl_classes(config: Any) -> list[str]:
    """Classes in a template controller that are not CDL block diagrams.

    Read from the source: a class whose equation section holds anything but
    ``connect`` (``y = if initial() then ...``, a ``when`` clause), one with an
    ``algorithm`` section, or one built on ``Modelica.StateGraph``. The engine
    executes CDL block diagrams only, so any of these, at any depth, is the blocker.
    """

    if config.source != "templates":
        return []
    root = MODELICA_ROOT[config.source].joinpath(*TEMPLATES_PACKAGE)
    found: set[str] = set()
    seen: set[str] = set()
    queue = [config.controller_id]
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        path = root.joinpath(*name.split(".")).with_suffix(".mo")
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if "Modelica.StateGraph" in text:
            found.add(f"{name} (Modelica.StateGraph)")
        elif re.search(r"(?m)^\s*algorithm\b", text):
            found.add(f"{name} (an algorithm section)")
        elif _equation_statements(text) and (
            name == config.controller_id
            or f"Utilities.{name.rsplit('.', 1)[-1]}" not in ARRAY_REDUCTIONS
        ):
            # (inside a composite MultiMaxInteger's ``y = max(u)`` is rewritten to
            # CDL folds, so it runs; on its own it is an equation, not a diagram)
            found.add(f"{name} (Modelica equations)")
        package = name.rsplit(".", 1)[0] if "." in name else ""
        for reference in re.findall(
            r"(?m)^\s*(?:final\s+)?([A-Z][A-Za-z0-9_.]*)\s+\w+\s*[\[(\n]", text
        ):
            if reference.startswith(("Buildings.", "Modelica.")):
                reference = reference.removeprefix("Buildings.Templates.Plants.Controls.")
                if reference.startswith(("Buildings.", "Modelica.")):
                    continue
            # Modelica name lookup: the enclosing package first, then its parents
            candidates = [f"{package}.{reference}" if package else reference, reference]
            parts = package.split(".") if package else []
            candidates += [".".join([*parts[:depth], reference]) for depth in range(len(parts))]
            for candidate in candidates:
                if root.joinpath(*candidate.split(".")).with_suffix(".mo").is_file():
                    queue.append(candidate)
                    break
    return sorted(found)


_DIAGNOSTIC = re.compile(r"(?m)^(error)\|([^|]+)\|([^|]*)\|(.*)$")


def _exact_reason(exc: BaseException) -> str:
    """The blocker in one line: an engine rejection is summarised by what it names (the
    block classes it has no definition for, the constructs outside its subset), not
    truncated mid-diagnostic."""

    # a scratch directory name would make the recorded reason differ on every run
    text = re.sub(r"/\S*?/bactalk-g36-[^/\s]+/cxf/", "", str(exc))
    diagnostics = _DIAGNOSTIC.findall(text)
    if not diagnostics:
        return f"{type(exc).__name__}: {' '.join(text.split())[:600]}"
    head = text.split("\n", 1)[0]
    head = head.split(": CXF validation failed", 1)[0] if "CXF validation" in head else head
    findings: list[str] = []
    missing = sorted(
        {
            match
            for _, code, _, message in diagnostics
            if code == "class-not-found"
            for match in re.findall(r"`([^`]+)`", message)
        }
    )
    if missing:
        findings.append("no block class for " + ", ".join(missing))
    constructs = sorted(
        {
            message.split(";", 1)[0].strip()
            for _, code, _, message in diagnostics
            if code == "non-subset-construct"
        }
    )
    findings.extend(constructs[:4])
    others = sorted(
        {
            f"{code}: {message.strip()} ({subject.rsplit('.', 2)[-2]}.{subject.rsplit('.', 1)[-1]})"
            for _, code, subject, message in diagnostics
            if code not in {"class-not-found", "non-subset-construct", "unresolved-reference"}
            and "." in subject
        }
    )
    if not findings:
        findings.extend(others[:3])
    return (
        f"{type(exc).__name__}: {head.strip()}; "
        + "; ".join(findings)
        + f" ({len(diagnostics)} engine errors)"
    )


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
    libraries: dict[str, G36Library] = {}

    def library_for(config: Any) -> G36Library:
        if config.source not in libraries:
            # Tier 2b: Templates.Plants.Controls through the plain CDL lane
            factory = PlantControlsCdlLibrary if config.source == "templates" else G36Library
            libraries[config.source] = factory(modelica_root=MODELICA_ROOT[config.source])
        return libraries[config.source]

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
                translation = translation_envelope(library_for(config), config.id)
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
            reference = reference_envelope(library_for(config), config.id)
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
            reason = _exact_reason(exc)
            outside = non_cdl_classes(config)
            if outside:
                reason = (
                    "not a CDL block diagram, so the Open Control Engine cannot execute it: "
                    "contains " + ", ".join(outside) + ". First failure: " + reason
                )
            blockers[config.id] = {
                "stage": "translation"
                if not (TRANSLATIONS / config.translation_file).is_file()
                else "reference",
                "reason": reason,
            }
            print(f"BLOCKED {config.id}: {type(exc).__name__}: {str(exc)[:300]}", flush=True)
            traceback.print_exc(limit=2)
    if not args.check:
        BLOCKERS.write_text(json.dumps(blockers, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
