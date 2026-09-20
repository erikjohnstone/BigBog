from __future__ import annotations

import argparse
import json
from pathlib import Path

from bactalk.integrations.g36_audit import G36CoverageAuditor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit pinned Guideline 36 translation and Niagara target coverage."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".bactalk/g36-coverage-audit.json"),
    )
    parser.add_argument(
        "--controller",
        action="append",
        dest="controllers",
        help="Audit one exact catalog controller id; repeat to select multiple.",
    )
    parser.add_argument(
        "--exclude-validation",
        action="store_true",
        help="Exclude controllers under Validation directories.",
    )
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = G36CoverageAuditor().run(
        args.output,
        controller_ids=args.controllers,
        include_validation=not args.exclude_validation,
        workers=args.workers,
        resume=not args.no_resume,
    )
    print(json.dumps(result["summary"], indent=2, sort_keys=True))
    print(f"evidence={args.output.resolve()}")
    return 0 if result["summary"]["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
