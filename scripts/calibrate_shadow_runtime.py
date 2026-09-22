"""Compare Gate G-WB station evidence with the Shadow Runtime's expected traces.

Reads the history CSV exports a human produced by following ``calibration/README.md``
(one directory per calibration, ``<point>.csv`` per observed history), compares each
with the committed ``expected-<point>.csv``, prints a verdict per rule and, unless
``--no-annotate`` is given, writes ``→ VERIFIED (G-WB <date>)`` or
``→ CONTRADICTED (G-WB <date>)`` into the rule's status cell of
``docs/niagara-semantics.md``. A CONTRADICTED rule is a defect in the Shadow Runtime
(or in the documented assumption), never in the station: open a failing test against
the runtime before the next release.

Usage::

    PYTHONPATH=src .venv/bin/python scripts/calibrate_shadow_runtime.py gates/evidence/G-WB \\
        [--kit calibration] [--doc docs/niagara-semantics.md] [--no-annotate] [--json OUT]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bactalk.niagara.calibration import annotate_document, compare_evidence

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("evidence", type=Path, help="directory of station history exports")
    parser.add_argument("--kit", type=Path, default=ROOT / "calibration")
    parser.add_argument("--doc", type=Path, default=ROOT / "docs" / "niagara-semantics.md")
    parser.add_argument("--no-annotate", action="store_true", help="only print the verdicts")
    parser.add_argument("--json", type=Path, help="also write the verdicts as JSON")
    args = parser.parse_args(argv)
    if not args.evidence.is_dir():
        print(f"no evidence directory at {args.evidence}")
        return 2
    verdicts = compare_evidence(args.evidence, args.kit)
    width = max(len(v.assumption) for v in verdicts)
    for verdict in verdicts:
        print(f"{verdict.assumption:<{width}}  {verdict.status:<13} {verdict.detail}")
        for mismatch in verdict.mismatches[:5]:
            print(f"{'':<{width}}    {mismatch}")
    counts = {
        status: sum(1 for v in verdicts if v.status == status)
        for status in ("VERIFIED", "CONTRADICTED", "MISSING", "NOT_TESTABLE")
    }
    print(" ".join(f"{k.lower()}={v}" for k, v in counts.items()))
    if args.json:
        args.json.write_text(
            json.dumps({"verdicts": [v.to_dict() for v in verdicts], "counts": counts}, indent=2)
            + "\n",
            encoding="utf-8",
        )
    if not args.no_annotate:
        changed = annotate_document(args.doc, verdicts)
        print(f"annotated {changed} rules in {args.doc}")
    return 1 if counts["CONTRADICTED"] else 0


if __name__ == "__main__":
    sys.exit(main())
