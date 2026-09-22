"""Write the committed proof reports for the native .bog pipeline (GOAL-NATIVE-BOG.md).

Each D-item has a report under ``artifacts/native-bog/``; CI regenerates them and
``tests/test_native_bog_proofs.py`` fails when the committed summary differs from a
fresh run, so a report can never quietly go stale.

    PYTHONPATH=src .venv/bin/python scripts/native_bog_proofs.py [--check] [--only d1,d2,d3,d4]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from bactalk.library_demo import (
    lbnl_multizone_ahu_demo_job,
    lbnl_vav_reheat_demo_job,
    reference_trace,
)
from bactalk.niagara.differential import three_way_differential
from bactalk.niagara.emit import emit_bog
from bactalk.niagara.module import declared_types
from bactalk.niagara.mutate import generate_mutants, run_mutation_suite
from bactalk.niagara.shadow.policy import PLAUSIBLE_POLICIES
from bactalk.niagara.validate import validate_bog

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts" / "native-bog"
TIER_ONE = (lbnl_vav_reheat_demo_job, lbnl_multizone_ahu_demo_job)
COARSE = next(policy for policy in PLAUSIBLE_POLICIES if policy.name == "coarse-module-tick")


def d1_native_by_default() -> dict[str, Any]:
    items = []
    for build in TIER_ONE:
        job = build()
        first = emit_bog(job.control_graph, points=job.points)
        second = emit_bog(job.control_graph, points=job.points)
        items.append(
            {
                "controller": job.sequence.controller_id,
                "equipment": job.equipment_name,
                "lane": first.plan.lane,
                "program_objects": False,
                "deterministic": first.content == second.content,
                "sha256": hashlib.sha256(first.content).hexdigest(),
                "component_count": first.report.component_count,
                "link_count": first.report.link_count,
                "module_types": list(first.report.module_types),
                "stock_only_plus_module": all(
                    t.split(":")[0] in {"b", "c", "baja", "control", "kitControl", "bactalkG36"}
                    for folder in first.report.folders
                    for _, t, *_ in folder.components
                ),
            }
        )
    return {
        "schema": "bactalk.native-bog-proof/d1/v1",
        "passed": all(
            i["deterministic"] and i["lane"].startswith("native") and i["stock_only_plus_module"]
            for i in items
        ),
        "items": items,
    }


def d2_statically_valid() -> dict[str, Any]:
    items = []
    for build in TIER_ONE:
        job = build()
        content = emit_bog(job.control_graph, points=job.points).content
        report = validate_bog(content, declared_types=declared_types(), label=job.equipment_name)
        items.append(
            {
                "equipment": job.equipment_name,
                "ok": report.ok,
                "errors": len(report.errors),
                "warnings": len(report.warnings),
                "component_count": report.component_count,
            }
        )
    bad = sorted(
        path.stem for path in (ROOT / "tests" / "fixtures" / "native-bog" / "bad").glob("*.bog")
    )
    return {
        "schema": "bactalk.native-bog-proof/d2/v1",
        "passed": all(i["ok"] and i["warnings"] == 0 for i in items),
        "items": items,
        "known_bad_fixtures": bad,
    }


def d3_three_way() -> dict[str, Any]:
    items = []
    for build in TIER_ONE:
        job = build()
        reference = reference_trace(job.sequence.controller_id)
        default = three_way_differential(job, reference=reference)
        coarse = three_way_differential(job, reference=reference, policy=COARSE, band_set="coarse")
        items.append(
            {
                "equipment": job.equipment_name,
                "controller": job.sequence.controller_id,
                "reference": default.reference_engine,
                "default_policy": _summarise(default.to_dict()),
                "coarse_module_tick": _summarise(coarse.to_dict()),
            }
        )
    return {
        "schema": "bactalk.native-bog-proof/d3/v1",
        "passed": all(
            i["default_policy"]["passed"] and i["coarse_module_tick"]["passed"] for i in items
        ),
        "bands": "src/bactalk/niagara/bands.json (docs/decisions/008)",
        "items": items,
    }


def _summarise(report: dict[str, Any]) -> dict[str, Any]:
    cases = []
    for case in report["cases"]:
        worst = max(
            (
                (leg["max_error"] or 0.0, signal["signal"], name)
                for signal in case["signals"]
                for name, leg in signal["legs"].items()
            ),
            default=(0.0, None, None),
        )
        cases.append(
            {
                "name": case["name"],
                "passed": case["passed"],
                "signals": len(case["signals"]),
                "legs": sorted(case["legs_available"]),
                "worst_excess": round(worst[0], 9),
                "worst_signal": worst[1],
                "first_divergence": case["first_divergence"],
            }
        )
    return {"passed": report["passed"], "engines": report["engines"], "cases": cases}


MUTATION_SAMPLE = 200
MUTATION_SEED = 7
MUTATION_TARGET = 0.95


def d4_mutations_caught() -> dict[str, Any]:
    """D4: a seeded sample of every operator's mutants, judged validator → loader →
    suite → three-way differential. The full mutant count is reported so the sample
    size is explicit; survivors are listed for review (they are the suite's gaps)."""

    items = []
    for build in TIER_ONE:
        job = build()
        content = emit_bog(job.control_graph, points=job.points).content
        generated = len(generate_mutants(content, seed=MUTATION_SEED))
        report = run_mutation_suite(
            content,
            job.acceptance_tests,
            seed=MUTATION_SEED,
            limit=MUTATION_SAMPLE,
            job=job,
            reference=reference_trace(job.sequence.controller_id),
        )
        summary = report.to_dict()
        items.append(
            {
                "equipment": job.equipment_name,
                "controller": job.sequence.controller_id,
                "mutants_generated": generated,
                "sample": summary["total"],
                "seed": MUTATION_SEED,
                "caught": summary["caught"],
                "catch_rate": summary["catch_rate"],
                "target": MUTATION_TARGET,
                "target_met": summary["catch_rate"] >= MUTATION_TARGET,
                "by_operator": summary["by_operator"],
                "by_catcher": summary["by_catcher"],
                "survivors": summary["survivors"],
            }
        )
    return {
        "schema": "bactalk.native-bog-proof/d4/v1",
        "passed": all(item["target_met"] for item in items),
        "oracles": ["validator", "loader", "suite", "differential"],
        "items": items,
    }


PROOFS = {
    "d1": d1_native_by_default,
    "d2": d2_statically_valid,
    "d3": d3_three_way,
    "d4": d4_mutations_caught,
}


def render(proof: str) -> str:
    return json.dumps(PROOFS[proof](), indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="compare with the committed reports")
    parser.add_argument("--only", default=",".join(PROOFS), help="comma-separated proof ids")
    args = parser.parse_args(argv)
    drift = 0
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    for proof in [item.strip() for item in args.only.split(",") if item.strip()]:
        rendered = render(proof)
        path = ARTIFACTS / f"{proof}-tier1.json"
        if args.check:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            status = "ok   " if current == rendered else "DRIFT"
            drift += status == "DRIFT"
            print(f"{status} {path.relative_to(ROOT)}")
            continue
        path.write_text(rendered, encoding="utf-8")
        passed = json.loads(rendered)["passed"]
        print(f"wrote {path.relative_to(ROOT)} passed={passed}")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
