"""``python -m bactalk.niagara.shadow``: run or check the Shadow Runtime.

run <program.bog> --job job.json [--policy NAME] [--kernels auto|python|jvm] [--robust]
check   compare the Python kernel ports with the Java kernels (needs a JDK)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bactalk.domain import JobSpec
from bactalk.niagara.shadow.driver import ShadowRunOptions, run_shadow_suite, run_under_policies
from bactalk.niagara.shadow.policy import DEFAULT_POLICY, PLAUSIBLE_POLICIES


def _policy(name: str):
    for policy in (DEFAULT_POLICY, *PLAUSIBLE_POLICIES):
        if policy.name == name:
            return policy
    raise SystemExit(f"unknown policy {name!r}; choose from {[p.name for p in PLAUSIBLE_POLICIES]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Niagara Shadow Runtime")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run a job's acceptance suite against an exported .bog")
    run.add_argument("bog", type=Path)
    run.add_argument(
        "--job", type=Path, required=True, help="JobSpec JSON (acceptance_tests are used)"
    )
    run.add_argument("--policy", default=DEFAULT_POLICY.name)
    run.add_argument("--kernels", default="auto", choices=["auto", "python", "jvm"])
    run.add_argument("--robust", action="store_true", help="run under every plausible policy")
    run.add_argument("--output", type=Path, help="write the report JSON here")
    commands.add_parser("check", help="Python kernel ports against the Java kernels")
    args = parser.parse_args(argv)
    if args.command == "check":
        from bactalk.niagara.shadow.equivalence import check_kernel_equivalence

        outcome = check_kernel_equivalence()
        print(outcome.summary())
        return 0 if outcome.ok else 1
    job = JobSpec.model_validate(json.loads(args.job.read_text("utf-8")))
    options = ShadowRunOptions(
        policy=_policy(args.policy),
        kernel_backend=args.kernels,
        sequence_family=job.sequence.family if job.sequence else None,
    )
    if args.robust:
        robustness = run_under_policies(args.bog, job.acceptance_tests, options=options)
        payload = robustness.to_dict()
        print(json.dumps(payload, indent=2))
        if args.output:
            args.output.write_text(json.dumps(payload, indent=2))
        return 0 if robustness.robust else 1
    report = run_shadow_suite(args.bog, job.acceptance_tests, options=options)
    for scenario in report.scenarios:
        print(f"{'PASS' if scenario.passed else 'FAIL'}  {scenario.name}")
        for assertion in scenario.assertions:
            if not assertion.passed:
                print(
                    f"      {assertion.name}: observed {assertion.observed}, "
                    f"expected {assertion.expected}"
                )
    print(report.engine, "|", report.coverage["shadow"])
    if args.output:
        args.output.write_text(report.model_dump_json(indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
