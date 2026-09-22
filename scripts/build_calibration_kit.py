"""Write the Shadow Runtime calibration kit for Gate G-WB.

One folder per ``ASSUMED`` rule of ``docs/niagara-semantics.md`` under ``calibration/``:
``program.bog`` to import into a station, ``steps.json`` describing the operator
actions, one ``expected-<point>.csv`` per observed history with the trace the Shadow
Runtime produced for the same script, and a README with the procedure. The kit is
committed so the gate can run from a checkout; ``--check`` fails when the committed
kit differs from what the current code produces.

Usage::

    PYTHONPATH=src .venv/bin/python scripts/build_calibration_kit.py [--check] [--out DIR]
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
import tempfile
from pathlib import Path

from bactalk.niagara.calibration import CALIBRATIONS, write_kit

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "calibration"


def _differences(fresh: Path, committed: Path) -> list[str]:
    problems: list[str] = []
    fresh_files = sorted(p.relative_to(fresh) for p in fresh.rglob("*") if p.is_file())
    committed_files = sorted(p.relative_to(committed) for p in committed.rglob("*") if p.is_file())
    for missing in set(fresh_files) - set(committed_files):
        problems.append(f"missing from the committed kit: {missing}")
    for extra in set(committed_files) - set(fresh_files):
        problems.append(f"stale file in the committed kit: {extra}")
    for relative in fresh_files:
        if relative in committed_files and not filecmp.cmp(
            fresh / relative, committed / relative, shallow=False
        ):
            problems.append(f"differs: {relative}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="fail if the committed kit is stale")
    parser.add_argument("--out", type=Path, default=DESTINATION)
    args = parser.parse_args(argv)
    if args.check:
        with tempfile.TemporaryDirectory() as scratch:
            fresh = Path(scratch) / "calibration"
            write_kit(fresh)
            # The .bog archives embed no timestamps (zipfile defaults), so a byte
            # comparison is meaningful.
            problems = _differences(fresh, args.out)
        for problem in problems:
            print(problem)
        if problems:
            print(f"calibration kit is stale ({len(problems)} problems); rerun without --check")
            return 1
        print(f"calibration kit up to date: {len(CALIBRATIONS)} calibrations under {args.out}")
        return 0
    if args.out.exists():
        shutil.rmtree(args.out)
    written = write_kit(args.out)
    print(f"wrote {len(written)} files for {len(CALIBRATIONS)} calibrations under {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
