from __future__ import annotations

import sys
from pathlib import Path

OLD = "            point.value = y_output\n"
NEW = "            point.value = value\n"


def patch(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    occurrences = source.count(OLD)
    if occurrences != 1:
        raise RuntimeError(
            f"refusing to patch {path}: expected one vulnerable assignment, found {occurrences}"
        )
    path.write_text(source.replace(OLD, NEW), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_output_value.py STEP_RUN_PATH")
    patch(Path(sys.argv[1]))
