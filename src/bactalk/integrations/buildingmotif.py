from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


class BuildingMotifError(RuntimeError):
    pass


class BuildingMotifAdapter:
    """Isolated adapter for BuildingMOTIF's semantic equipment templates."""

    def __init__(
        self,
        *,
        root: Path = Path("."),
        timeout_seconds: float = 60.0,
    ):
        self.root = root.resolve()
        self.python = self.root / ".buildingmotif-venv/bin/python"
        self.worker = self.root / "scripts/buildingmotif_worker.py"
        self.timeout_seconds = timeout_seconds

    def catalog(self, library: str = "g36") -> dict[str, Any]:
        return self._execute({"operation": "catalog", "library": library})

    def instantiate(
        self,
        *,
        library: str,
        template: str,
        namespace: str,
        bindings: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if not namespace.startswith(("urn:", "https://", "http://")):
            raise BuildingMotifError("namespace must be an absolute urn/http/https URI")
        return self._execute(
            {
                "operation": "instantiate",
                "library": library,
                "template": template,
                "namespace": namespace,
                "bindings": bindings or {},
            }
        )

    def _execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.python.is_file() or not self.worker.is_file():
            raise BuildingMotifError(
                "BuildingMOTIF runtime is unavailable; run make buildingmotif-install"
            )
        try:
            completed = subprocess.run(
                [str(self.python), str(self.worker)],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                cwd=self.root,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise BuildingMotifError("BuildingMOTIF worker timed out") from exc
        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            detail = completed.stderr.strip() or completed.stdout.strip() or "no output"
            raise BuildingMotifError(f"BuildingMOTIF returned invalid output: {detail}") from exc
        if completed.returncode != 0 or not response.get("ok"):
            raise BuildingMotifError(response.get("error", "BuildingMOTIF worker failed"))
        return response["result"]
