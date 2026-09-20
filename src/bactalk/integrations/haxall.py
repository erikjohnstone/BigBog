from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from phable import Grid
from phable.io.ph_zinc import ph_from_zinc


class HaxallError(RuntimeError):
    pass


@dataclass(frozen=True)
class XetoValidationResult:
    conforms: bool
    errors: list[dict[str, str]]
    raw_zinc: str


class HaxallValidator:
    """Validate Haystack Zinc records against Haxall/Xeto schemas."""

    def __init__(self, executable: Path | None = None, *, timeout: float = 60.0):
        self.executable = executable or Path(
            os.getenv("BACTALK_XETO", "ops/haxall/node_modules/.bin/xeto")
        )
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return self.executable.is_file()

    def validate_zinc(self, zinc: str, *, graph: bool = True) -> XetoValidationResult:
        if not self.available:
            raise HaxallError("Haxall runtime is unavailable; run 'make install-haxall'")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".zinc", encoding="utf-8") as source:
            source.write(zinc)
            source.flush()
            command = [
                str(self.executable),
                "fits",
                source.name,
                "-outFile",
                "stdout.zinc",
            ]
            if graph:
                command.append("-graph")
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        if completed.returncode != 0:
            raise HaxallError((completed.stderr or completed.stdout).strip())
        decoded = ph_from_zinc(completed.stdout)
        if not isinstance(decoded, Grid):
            raise HaxallError("Haxall returned an unexpected response")
        errors = [
            {"id": str(row.get("id", "")), "message": str(row.get("msg", ""))}
            for row in decoded.rows
        ]
        return XetoValidationResult(
            conforms=not errors,
            errors=errors,
            raw_zinc=completed.stdout,
        )
