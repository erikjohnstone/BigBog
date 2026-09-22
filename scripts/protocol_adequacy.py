"""Run the Test Generation Protocol's adequacy check on a Tier 3 item and retain it.

Writes the item's ``adequacy.json`` (package data beside its requirements: the
adequacy report with the Gate G-ENG status, served by ``GET /api/protocol/sequences``)
and ``docs/test-plans/<id>.md`` (the readable test plan). Nothing here
is Niagara runtime qualification; the mutation leg judges the exported .bog with the
Shadow Runtime.

    PYTHONPATH=src python scripts/protocol_adequacy.py <sequence-id> [--mutants N]
        [--sequences N] [--no-mutation] [--approvals DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bactalk.protocol import catalog as protocol_catalog  # noqa: E402
from bactalk.protocol import generate_test_plan  # noqa: E402
from bactalk.protocol.adequacy import INVARIANT_SEQUENCES, assess_adequacy  # noqa: E402
from bactalk.protocol.approvals import RequirementApprovalRepository  # noqa: E402
from bactalk.protocol.plan import approval_digest, render_test_plan  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("item", choices=sorted(protocol_catalog.sequence_ids()))
    parser.add_argument("--mutants", type=int, default=200)
    parser.add_argument("--sequences", type=int, default=INVARIANT_SEQUENCES)
    parser.add_argument("--no-mutation", action="store_true")
    parser.add_argument(
        "--mutation-leg",
        choices=("scan", "default"),
        default="scan",
        help="execution policy the mutants are judged under (scan: module period = scan)",
    )
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="re-render docs/test-plans/<item>.md from the retained adequacy.json",
    )
    parser.add_argument(
        "--d3-default",
        action="store_true",
        help="also run the D3 differential under the default per-second policy (slow)",
    )
    parser.add_argument(
        "--approvals",
        type=Path,
        default=Path(".bactalk/requirement-approvals"),
        help="retained requirement approvals (Gate G-ENG)",
    )
    args = parser.parse_args()

    entry = protocol_catalog.row(args.item)
    requirements = entry.requirement_set()
    plan = generate_test_plan(requirements)
    approvals = RequirementApprovalRepository(args.approvals)
    approval = approvals.get(requirements.sequence_id, requirements.digest())
    document = ROOT / "docs" / "test-plans" / f"{args.item}.md"
    if args.render_only:
        retained = json.loads(entry.adequacy_path.read_text(encoding="utf-8"))
        if retained.get("requirements_digest") != requirements.digest():
            raise SystemExit("retained adequacy.json is for another requirement digest")
        document.parent.mkdir(parents=True, exist_ok=True)
        document.write_text(
            render_test_plan(requirements, plan, retained, approval), encoding="utf-8"
        )
        print(f"re-rendered {document.relative_to(ROOT)}")
        return 0
    job = protocol_catalog.protocol_job(args.item, plan=plan)
    started = time.time()
    print(
        f"{args.item}: {len(requirements.requirements)} requirements, {len(plan.scenarios)} "
        f"scenarios, {len(plan.gaps)} gaps; running suite, invariants"
        + ("" if args.no_mutation else f", {args.mutants} mutants"),
        flush=True,
    )
    report = assess_adequacy(
        job,
        requirements,
        plan,
        mutants=None if args.no_mutation else args.mutants,
        invariant_sequences=args.sequences,
        mutation_leg=args.mutation_leg,
        differential_legs=("scan", "default") if args.d3_default else ("scan",),
    )
    payload = report.to_dict()
    payload["gate_g_eng"] = approvals.status(requirements)
    payload["approval_digest"] = approval_digest(requirements, plan, report.to_dict())
    payload["seconds"] = round(time.time() - started, 1)

    artifact = entry.adequacy_path
    artifact.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text(render_test_plan(requirements, plan, payload, approval), encoding="utf-8")
    mutation = payload.get("mutation") or {}
    print(
        f"accepted={payload['accepted']} suite={'pass' if payload['suite']['passed'] else 'FAIL'} "
        f"decisions={payload['decisions'].get('percent')}% invariants="
        f"{payload['invariants']['violations']} violations on {payload['invariants']['sequences']} "
        f"sequences d3={ {k: v['passed'] for k, v in payload['differential'].items()} } "
        f"mutation={mutation.get('catch_rate', mutation.get('blocker', 'not run'))} "
        f"gate={payload['gate_g_eng']} questions={len(payload['questions'])}",
        flush=True,
    )
    print(f"wrote {artifact.relative_to(ROOT)} and {document.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
