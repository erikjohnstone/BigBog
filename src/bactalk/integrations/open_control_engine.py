from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class OpenControlEngine:
    """Isolated CLI adapter for deterministic validation and execution of CXF."""

    MAX_CXF_BYTES = 8 * 1024 * 1024
    MAX_SCENARIO_BYTES = 16 * 1024 * 1024

    def __init__(
        self,
        manifest: Path = Path("ops/open-control-engine-runner/Cargo.toml"),
        *,
        engine_checkout: Path = Path(".vendor/open-control-engine"),
        cargo_binary: str = "cargo",
    ):
        self.manifest = manifest.resolve()
        self.engine_checkout = engine_checkout.resolve()
        self.cargo_binary = cargo_binary

    def _base_command(self) -> list[str]:
        if not self.manifest.is_file():
            raise FileNotFoundError(f"Open Control Engine runner not found: {self.manifest}")
        if not (self.engine_checkout / "crates" / "oce-api").is_dir():
            raise FileNotFoundError(
                f"Open Control Engine checkout not found: {self.engine_checkout}"
            )
        return [
            self.cargo_binary,
            "run",
            "--quiet",
            "--manifest-path",
            str(self.manifest),
            "--",
        ]

    def build_command(
        self,
        cxf_path: Path,
        *,
        operation: str = "inspect",
        scenario_path: Path | None = None,
    ) -> list[str]:
        if operation not in {"inspect", "simulate"}:
            raise ValueError(f"unsupported Open Control Engine operation: {operation}")
        command = [*self._base_command(), operation, str(cxf_path.resolve())]
        if operation == "simulate":
            if scenario_path is None:
                raise ValueError("simulate requires a scenario path")
            command.append(str(scenario_path.resolve()))
        elif scenario_path is not None:
            raise ValueError("inspect does not accept a scenario path")
        return command

    def _run(self, command: list[str], *, timeout: float) -> dict[str, Any]:
        environment = os.environ.copy()
        environment["CARGO_TARGET_DIR"] = str(self.engine_checkout / "target")
        environment.setdefault("RUSTUP_TOOLCHAIN", "1.97.1")
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Open Control Engine request exceeded its time limit") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            raise RuntimeError(f"Open Control Engine rejected request: {detail}") from exc
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Open Control Engine returned invalid JSON") from exc

    def inspect(self, cxf_path: Path, *, timeout: float = 120.0) -> dict[str, Any]:
        size = cxf_path.stat().st_size
        if size > self.MAX_CXF_BYTES:
            raise ValueError(f"CXF exceeds the {self.MAX_CXF_BYTES}-byte admission limit")
        return self._run(self.build_command(cxf_path), timeout=timeout)

    def inspect_document(
        self,
        document: dict[str, Any],
        *,
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        """Validate an in-memory CXF document through the isolated engine."""

        encoded = json.dumps(
            document,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded) > self.MAX_CXF_BYTES:
            raise ValueError(f"CXF exceeds the {self.MAX_CXF_BYTES}-byte admission limit")
        with tempfile.NamedTemporaryFile(suffix=".jsonld") as handle:
            handle.write(encoded)
            handle.flush()
            return self.inspect(Path(handle.name), timeout=timeout)

    def simulate(
        self,
        cxf_path: Path,
        *,
        samples: list[dict[str, Any]],
        collect: list[str],
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        """Execute a bounded explicit-time trace in the vendored OCE runtime."""

        cxf_size = cxf_path.stat().st_size
        if cxf_size > self.MAX_CXF_BYTES:
            raise ValueError(f"CXF exceeds the {self.MAX_CXF_BYTES}-byte admission limit")
        scenario = json.dumps(
            {"samples": samples, "collect": collect},
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(scenario) > self.MAX_SCENARIO_BYTES:
            raise ValueError(
                f"scenario exceeds the {self.MAX_SCENARIO_BYTES}-byte admission limit"
            )
        with tempfile.NamedTemporaryFile(suffix=".json") as handle:
            handle.write(scenario)
            handle.flush()
            return self._run(
                self.build_command(
                    cxf_path,
                    operation="simulate",
                    scenario_path=Path(handle.name),
                ),
                timeout=timeout,
            )

    def simulate_document(
        self,
        document: dict[str, Any],
        *,
        samples: list[dict[str, Any]],
        collect: list[str],
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        """Execute an in-memory CXF document without admitting an arbitrary host path."""

        encoded = json.dumps(
            document,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded) > self.MAX_CXF_BYTES:
            raise ValueError(f"CXF exceeds the {self.MAX_CXF_BYTES}-byte admission limit")
        with tempfile.NamedTemporaryFile(suffix=".jsonld") as handle:
            handle.write(encoded)
            handle.flush()
            return self.simulate(
                Path(handle.name),
                samples=samples,
                collect=collect,
                timeout=timeout,
            )
