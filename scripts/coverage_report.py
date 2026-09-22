"""Render docs/coverage.md from the library (GOAL-NATIVE-BOG.md N8 step 6).

Every configuration BACTalk carries (Tier 1 demos and every Tier 2 configuration)
is pushed through the unchanged N4–N7 pipeline and graded:

- D1 native by default: the graph lowers to the native lane and emits one ``.bog``;
- D2 statically valid: the validator reports no errors;
- D3 three engines agree: Shadow Runtime, IR interpreter and the retained reference
  inside the documented bands, every scenario;
- D4 mutations caught: a seeded mutant sample judged validator → loader → suite →
  differential, target ≥ 95 %.

The JSON report is written to ``src/bactalk/library_tier2/coverage.json`` (package data,
served at ``GET /api/library/coverage``) and rendered to ``docs/coverage.md``; ``--check``
fails when either committed copy is stale. A configuration with no retained data, or one
that fails a proof, is listed with its exact blocker, never dropped.

Usage::

    PYTHONPATH=src .venv/bin/python scripts/coverage_report.py [--check] [--only ID,ID]
        [--mutants N]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from bactalk.domain import JobSpec
from bactalk.library_demo import (
    lbnl_multizone_ahu_demo_job,
    lbnl_vav_reheat_demo_job,
)
from bactalk.library_demo import reference_trace as tier1_reference
from bactalk.library_tier2 import (
    CONFIGURATIONS,
    reference_trace,
    retained_ids,
    tier2_job,
)
from bactalk.niagara.differential import three_way_differential
from bactalk.niagara.emit import emit_bog
from bactalk.niagara.lowering import LoweringPolicy, plan_lowering
from bactalk.niagara.module import declared_types
from bactalk.niagara.mutate import generate_mutants, run_mutation_suite
from bactalk.niagara.shadow.policy import DEFAULT_POLICY, PLAUSIBLE_POLICIES, SCAN_POLICY
from bactalk.niagara.validate import validate_bog
from bactalk.protocol import catalog as protocol_catalog
from bactalk.simulator import run_acceptance_suite

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "src" / "bactalk" / "library_tier2" / "coverage.json"
DOCUMENT = ROOT / "docs" / "coverage.md"
BLOCKERS = ROOT / "src" / "bactalk" / "library_tier2" / "blockers.json"
MUTATION_TARGET = 0.95
MUTATION_SEED = 7
COARSE = next(policy for policy in PLAUSIBLE_POLICIES if policy.name == "coarse-module-tick")
GRADING_VERSION = 3

TIER_ONE = (
    ("tier1-vav-reheat", "TerminalUnits.Reheat.Controller", lbnl_vav_reheat_demo_job),
    ("tier1-ahu-multizone-vav", "AHUs.MultiZone.VAV.Controller", lbnl_multizone_ahu_demo_job),
)


def grade_static(job: JobSpec) -> dict[str, Any]:
    """D1 (native lowering) and D2 (static validation); the emitted .bog rides along under
    ``_content`` for the dynamic grades and is dropped from the row."""

    assert job.control_graph is not None
    graph = job.control_graph
    row: dict[str, Any] = {"scenarios": len(job.acceptance_tests)}
    plan = plan_lowering(graph, LoweringPolicy())
    row["d1"] = {
        "passed": plan.lane in {"native_stock", "native_with_module"},
        "lane": plan.lane,
        "blockers": list(plan.blockers),
    }
    if not row["d1"]["passed"]:
        row["d2"] = row["d3"] = row["d4"] = {"passed": False, "blocker": "no native lowering"}
        return row
    result = emit_bog(graph, points=job.points)
    content = result.content
    validation = validate_bog(content, declared_types=declared_types(), label=job.equipment_name)
    row["d2"] = {
        "passed": validation.ok,
        "errors": [str(issue) for issue in validation.errors[:5]],
        "warnings": len(validation.warnings),
        "components": validation.component_count,
        "links": validation.link_count,
    }
    if not validation.ok:
        row["d3"] = row["d4"] = {"passed": False, "blocker": "static validation failed"}
        return row
    row["_content"] = content
    return row


def grade(job: JobSpec, reference: dict[str, Any] | None, *, mutants: int) -> dict[str, Any]:
    """D1–D4 for one job; every failure carries its reason."""

    assert job.control_graph is not None
    graph = job.control_graph
    row = grade_static(job)
    content = row.pop("_content", None)
    if content is None:
        return row
    interpreter = run_acceptance_suite(graph, job)
    started = time.time()
    differential = three_way_differential(
        job, bog=content, reference=reference, interpreter_report=interpreter
    )
    failing = [case.name for case in differential.cases if not case.passed]
    # The reference is stepped at the scan interval while module kernels tick every
    # second; a second leg with the module period equal to the scan (tight bands)
    # separates a runtime defect from that discretisation difference.
    coarse = three_way_differential(
        job,
        bog=content,
        reference=reference,
        interpreter_report=interpreter,
        policy=COARSE,
        band_set="coarse",
    )
    row["d3"] = {
        "passed": differential.passed and interpreter.passed,
        "coarse_passed": coarse.passed and interpreter.passed,
        "interpreter_passed": interpreter.passed,
        "reference_available": differential.reference_available,
        "legs": sorted({leg for case in differential.cases for leg in case.legs_available}),
        "failing_cases": failing[:10],
        "first_divergence": next(
            (case.first_divergence for case in differential.cases if not case.passed), None
        ),
        "seconds": round(time.time() - started, 1),
    }
    started = time.time()
    generated = len(generate_mutants(content, seed=MUTATION_SEED))
    # D4 is judged on the D3 leg the unmutated file passed: a mutant is "caught by the
    # differential" only when it leaves bands the baseline stays inside. A row that
    # fails both legs has no baseline to compare against and D4 is a blocker.
    if row["d3"]["passed"]:
        policy, band_set = DEFAULT_POLICY, "default"
    elif row["d3"]["coarse_passed"]:
        policy, band_set = COARSE, "coarse"
    else:
        row["d4"] = {
            "passed": False,
            "blocker": "D3: the unmutated .bog leaves the bands on "
            + ", ".join(failing[:3])
            + "; a catch rate would count that, not defects",
            "mutants_generated": generated,
        }
        return row
    report = None
    attempts = [(policy, band_set)]
    if band_set == "default":
        # A per-second Shadow Runtime can miss a reference-derived end-of-scenario
        # expectation by a hair while the trajectories agree inside the bands (the PID
        # integration difference of decision 008); the mutation judge's suite oracle
        # then catches the unmutated file. The scan leg reproduces the interpreter's
        # discretisation and is the leg the baseline passes (decision 010 item 8).
        attempts.append((SCAN_POLICY, "scan"))
    failures: list[str] = []
    for policy, band_set in attempts:
        try:
            report = run_mutation_suite(
                content,
                job.acceptance_tests,
                seed=MUTATION_SEED,
                limit=mutants,
                job=job,
                reference=reference,
                policy=policy,
                band_set=band_set,
            )
            break
        except ValueError as exc:
            failures.append(f"{policy.name}: {exc}")
    if report is None:
        row["d4"] = {
            "passed": False,
            "blocker": "baseline: " + " | ".join(failures),
            "mutants_generated": generated,
            "policy": policy.name,
            "band_set": band_set,
        }
        return row
    summary = report.to_dict()
    row["d4"] = {
        "passed": summary["catch_rate"] >= MUTATION_TARGET,
        "policy": policy.name,
        "band_set": band_set,
        "mutants_generated": generated,
        "sample": summary["total"],
        "caught": summary["caught"],
        "catch_rate": summary["catch_rate"],
        "by_catcher": summary["by_catcher"],
        "survivors": summary["survivors"][:25],
        "seconds": round(time.time() - started, 1),
    }
    return row


def _protocol_row(entry: protocol_catalog.Row) -> dict[str, Any]:
    """A Tier 3+ row under the Test Generation Protocol: D1 and D2 graded here, D3 and
    D4 read from the retained adequacy artifact (scripts/protocol_adequacy.py), with
    Gate G-ENG beside them. Nothing is graded from a reference model; there is none."""

    requirements = entry.requirement_set()
    job = protocol_catalog.protocol_job(requirements.sequence_id)
    row: dict[str, Any] = {
        "id": requirements.sequence_id,
        "controller": requirements.title,
        "family": job.sequence.family,
        "variant": f"{entry.configuration.label} · {len(requirements.requirements)} requirements",
        "tier": str(requirements.tier),
        "label": entry.item.label,
        "parameters": dict(entry.configuration.options),
        "source_of_truth": "requirement set (Gate G-ENG)",
        "expectations": "generated by the test author (docs/decisions/011)",
        "requirements_digest": requirements.digest(),
    }
    row.update(grade_static(job))
    row.pop("_content", None)
    artifact = entry.adequacy_artifact()
    if artifact is None or artifact.get("requirements_digest") != requirements.digest():
        reason = (
            "no retained adequacy artifact (scripts/protocol_adequacy.py)"
            if artifact is None
            else "retained adequacy artifact is for an earlier requirement digest"
        )
        row["d3"] = row["d4"] = {"passed": False, "blocker": reason}
        row["gate_g_eng"] = "unknown"
        return row
    legs = artifact.get("differential", {})
    scan = legs.get("scan") or {}
    default = legs.get("default")
    row["d3"] = {
        "passed": bool(default and default.get("passed")),
        "coarse_passed": bool(scan.get("passed")),
        "legs": sorted(legs),
        "failing_cases": (default or scan).get("failing_cases", [])[:10],
        "first_divergence": (default or scan).get("first_divergence"),
        "note": (
            "default (per-second) leg not run; scan leg only"
            if default is None
            else "both legs retained"
        ),
    }
    if default is None:
        row["d3"]["blocker"] = (
            "per-second leg not run (multi-day rotation scenarios); scan leg "
            + ("passes" if scan.get("passed") else "fails")
        )
    mutation = artifact.get("mutation") or {}
    if "catch_rate" in mutation:
        row["d4"] = {
            "passed": mutation["catch_rate"] >= MUTATION_TARGET,
            "policy": mutation.get("policy"),
            "band_set": mutation.get("band_set"),
            "mutants_generated": mutation.get("mutants_generated"),
            "sample": mutation.get("sample"),
            "caught": mutation.get("caught"),
            "catch_rate": mutation["catch_rate"],
            "by_catcher": mutation.get("by_catcher"),
            "survivors": mutation.get("survivors", [])[:25],
        }
    else:
        row["d4"] = {"passed": False, "blocker": mutation.get("blocker", "mutation not run")}
    row["gate_g_eng"] = artifact.get("gate_g_eng", "unknown")
    row["adequacy"] = {
        "accepted": artifact.get("accepted"),
        "scenarios": artifact.get("suite", {}).get("count"),
        "decisions_percent": artifact.get("decisions", {}).get("percent"),
        "invariant_sequences": artifact.get("invariants", {}).get("sequences"),
        "questions": len(artifact.get("questions", [])),
    }
    return row


PROGRESS = ROOT / ".bactalk" / "coverage-progress.json"


def _load_progress(resume: bool) -> dict[str, dict[str, Any]]:
    if resume and PROGRESS.is_file():
        return json.loads(PROGRESS.read_text(encoding="utf-8"))
    return {}


def _save_progress(progress: dict[str, dict[str, Any]]) -> None:
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(json.dumps(progress, indent=1, sort_keys=True), encoding="utf-8")


def build(only: set[str] | None, *, mutants: int, resume: bool = False) -> dict[str, Any]:
    blockers = json.loads(BLOCKERS.read_text(encoding="utf-8")) if BLOCKERS.is_file() else {}
    retained = set(retained_ids())
    items: list[dict[str, Any]] = []
    # Grading is slow (D3 and D4 per configuration); a graded row is kept under
    # .bactalk/ so an interrupted run resumes instead of starting over.
    progress = _load_progress(resume)
    for config_id, controller_id, build_job in TIER_ONE:
        if only and config_id not in only:
            continue
        job = build_job()
        row = {
            "id": config_id,
            "controller": controller_id,
            "family": controller_id.split(".")[0],
            "variant": "LBNL validation configuration",
            "tier": "1",
            "source_of_truth": "Open Control Engine (retained reference)",
            "expectations": "hand-written from the G36 text (N0), reference-checked (D3)",
        }
        cached = progress.get(config_id)
        if cached and cached.get("_mutants") == mutants and cached.get("_v") == GRADING_VERSION:
            row.update(cached)
        else:
            row.update(grade(job, tier1_reference(controller_id), mutants=mutants))
            progress[config_id] = {**row, "_mutants": mutants, "_v": GRADING_VERSION}
            _save_progress(progress)
        row.pop("_mutants", None)
        row.pop("_v", None)
        items.append(row)
        _progress(config_id, row)
    for config in CONFIGURATIONS:
        if only and config.id not in only:
            continue
        row = {
            "id": config.id,
            "controller": config.controller_id,
            "family": config.family,
            "variant": config.variant,
            "tier": config.tier,
            "parameters": config.parameters,
            "source_of_truth": "Open Control Engine (retained reference)",
            "expectations": "reference-derived (docs/decisions/010)",
        }
        if config.id in blockers:
            row["blocker"] = blockers[config.id]
            row["d1"] = row["d2"] = row["d3"] = row["d4"] = {
                "passed": False,
                "blocker": f"{blockers[config.id]['stage']}: {blockers[config.id]['reason']}",
            }
        elif config.id not in retained or reference_trace(config.id) is None:
            row["blocker"] = {"stage": "retention", "reason": "not retained yet"}
            row["d1"] = row["d2"] = row["d3"] = row["d4"] = {
                "passed": False,
                "blocker": "no retained translation or reference (scripts/retain_tier2.py)",
            }
        elif (
            (cached := progress.get(config.id))
            and cached.get("_mutants") == mutants
            and cached.get("_v") == GRADING_VERSION
            and not str(cached.get("d4", {}).get("blocker", "")).startswith("baseline:")
        ):
            row.update(cached)
        else:
            job = tier2_job(config.id)
            row.update(grade(job, reference_trace(config.id), mutants=mutants))
            progress[config.id] = {**row, "_mutants": mutants, "_v": GRADING_VERSION}
            _save_progress(progress)
        row.pop("_mutants", None)
        row.pop("_v", None)
        items.append(row)
        _progress(config.id, row)
    for entry in protocol_catalog.rows():
        items.append(_protocol_row(entry))
        _progress(items[-1]["id"], items[-1])
    return {
        "schema": "bactalk.native-bog-coverage/v1",
        "mutation_sample": mutants,
        "mutation_seed": MUTATION_SEED,
        "mutation_target": MUTATION_TARGET,
        "items": items,
        "summary": {
            "configurations": len(items),
            "all_four": sum(
                1 for i in items if all(i[d]["passed"] for d in ("d1", "d2", "d3", "d4"))
            ),
            "d1": sum(1 for i in items if i["d1"]["passed"]),
            "d2": sum(1 for i in items if i["d2"]["passed"]),
            "d3": sum(1 for i in items if i["d3"]["passed"]),
            "d4": sum(1 for i in items if i["d4"]["passed"]),
            "blocked": sum(1 for i in items if "blocker" in i),
        },
    }


def _progress(config_id: str, row: dict[str, Any]) -> None:
    d4 = row["d4"].get("catch_rate", row["d4"].get("blocker"))
    print(
        f"{config_id}: d1={row['d1']['passed']} d2={row['d2']['passed']} "
        f"d3={row['d3']['passed']} d4={d4}",
        flush=True,
    )


def _one_line(text: str, limit: int = 160) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _mark(entry: dict[str, Any]) -> str:
    leg = f" ({entry['band_set']} leg)" if entry.get("band_set") in {"coarse", "scan"} else ""
    if entry.get("passed"):
        return f"pass{leg}"
    blocker = entry.get("blocker")
    if blocker:
        return f"blocked: {_one_line(blocker)}"
    if "catch_rate" in entry:
        return f"{entry['catch_rate'] * 100:.1f} % (target 95 %){leg}"
    if entry.get("failing_cases"):
        detail = "fail: " + ", ".join(entry["failing_cases"][:3])
        if entry.get("coarse_passed"):
            detail += " (1 s module tick; passes at scan tick)"
        return detail
    if entry.get("errors"):
        return "fail: " + entry["errors"][0]
    if entry.get("blockers"):
        return "fail: " + entry["blockers"][0]
    return "fail"


def render(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Library coverage (D1–D4 per configuration)",
        "",
        "Generated by `scripts/coverage_report.py` from `bactalk.library_demo` (Tier 1),",
        "`bactalk.library_tier2` (Tier 2) and the protocol catalogue (Tiers 3–5,",
        "`bactalk.protocol.catalog`: requirement sets under Gate G-ENG, graded from their",
        "retained adequacy artifacts, decisions 011–013); do not edit by hand. Every row is",
        "one controller with one complete parameter set or one configuration. D1 native by",
        "default, D2 statically valid, D3 the",
        "Shadow Runtime, the IR interpreter and the retained Open Control Engine reference",
        "agree inside the documented bands on every scenario (a D3 fail that passes with the",
        "module period equal to the scan says so: the reference is stepped at the scan",
        "interval while module kernels tick every second), D4 a seeded sample of",
        f"{report['mutation_sample']} mutants is caught at ≥ 95 %, judged on the D3 leg the",
        "unmutated file passed (a row graded on the coarse leg says `coarse` beside its",
        "rate). A configuration that fails or cannot be built is listed with its exact",
        "blocker.",
        "",
        f"Summary: {summary['configurations']} configurations, "
        f"{summary['all_four']} pass all four; "
        f"D1 {summary['d1']}, D2 {summary['d2']}, D3 {summary['d3']}, D4 {summary['d4']}, "
        f"blocked {summary['blocked']}.",
        "",
        "| Id | Controller | Variant | Tier | Scenarios | D1 | D2 | D3 | D4 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for item in report["items"]:
        lines.append(
            f"| `{item['id']}` | {item['controller']} | {item['variant']}"
            + (f" · Gate G-ENG {item['gate_g_eng']}" if "gate_g_eng" in item else "")
            + f" | {item['tier']} "
            f"| {item.get('scenarios', '—')} | {_mark(item['d1'])} | {_mark(item['d2'])} "
            f"| {_mark(item['d3'])} | {_mark(item['d4'])} |"
        )
    lines += ["", "## Survivors and divergences", ""]
    for item in report["items"]:
        d3, d4 = item["d3"], item["d4"]
        if d3.get("passed") and d4.get("passed"):
            continue
        lines.append(f"### `{item['id']}`")
        lines.append("")
        if "blocker" in item:
            lines.append(
                f"- Blocked at {item['blocker']['stage']}: "
                f"{_one_line(item['blocker']['reason'], 600)}"
            )
        if not d3.get("passed") and d3.get("first_divergence"):
            lines.append(
                f"- First divergence: `{json.dumps(d3['first_divergence'], sort_keys=True)[:300]}`"
            )
        for survivor in d4.get("survivors", [])[:12]:
            lines.append(f"- Survivor: {survivor['operator']} `{survivor['path']}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--only", help="comma-separated configuration ids")
    parser.add_argument("--mutants", type=int, default=40)
    parser.add_argument(
        "--resume", action="store_true", help="reuse rows graded by an interrupted run"
    )
    args = parser.parse_args(argv)
    only = set(args.only.split(",")) if args.only else None
    report = build(only, mutants=args.mutants, resume=args.resume)
    rendered_json = json.dumps(report, indent=1, sort_keys=True) + "\n"
    rendered_md = render(report)
    if args.check:
        stale = []
        if not ARTIFACT.is_file() or ARTIFACT.read_text(encoding="utf-8") != rendered_json:
            stale.append(str(ARTIFACT.relative_to(ROOT)))
        if not DOCUMENT.is_file() or DOCUMENT.read_text(encoding="utf-8") != rendered_md:
            stale.append(str(DOCUMENT.relative_to(ROOT)))
        for path in stale:
            print(f"stale: {path}")
        return 1 if stale else 0
    if only:
        print("partial run (--only): reports not written")
        print(rendered_md)
        return 0
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(rendered_json, encoding="utf-8")
    DOCUMENT.write_text(rendered_md, encoding="utf-8")
    print(f"wrote {ARTIFACT.relative_to(ROOT)} and {DOCUMENT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
