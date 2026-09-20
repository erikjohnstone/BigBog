from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


class ConStrainError(RuntimeError):
    pass


class ConStrainVerifier:
    """Process-isolated adapter for PNNL ConStrain's incompatible dependency lane."""

    def __init__(
        self,
        *,
        python: Path | None = None,
        worker: Path | None = None,
        timeout: float = 60.0,
    ):
        self.python = python or Path(
            os.getenv("BACTALK_CONSTRAIN_PYTHON", ".constrain-venv/bin/python")
        )
        self.worker = worker or Path("scripts/constrain_worker.py")
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return self.python.is_file() and self.worker.is_file()

    def verify(
        self,
        *,
        rule: str,
        rows: list[dict[str, Any]],
        parameters: dict[str, float | bool | str] | None = None,
    ) -> dict[str, Any]:
        if not self.available:
            raise ConStrainError("ConStrain runtime is unavailable; run 'make constrain-install'")
        request = {"rule": rule, "rows": rows, "parameters": parameters or {}}
        completed = subprocess.run(
            [str(self.python), str(self.worker)],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise ConStrainError(detail or "ConStrain verification failed")
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ConStrainError("ConStrain returned invalid JSON") from exc
