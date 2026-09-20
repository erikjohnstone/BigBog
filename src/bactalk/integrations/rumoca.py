from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from bactalk.integrations.g36_library import G36Library


class RumocaError(RuntimeError):
    """Raised when the isolated Modelica compiler rejects an allowlisted model."""


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_QUALIFIED_NAME = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$"
)
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head(path: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return "unavailable"
    return completed.stdout.strip()


def _modelica_literal(value: float | int | bool | str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Modelica parameter values must be finite")
        return repr(value)
    if isinstance(value, str) and _QUALIFIED_NAME.fullmatch(value):
        return value
    raise ValueError(
        "Modelica parameters must be finite numbers, booleans, or qualified enum names"
    )


class RumocaCompiler:
    """Bounded adapter for Apache-2.0 Rumoca's flattened Modelica IR."""

    MAX_PARAMETERS = 128
    MAX_FLAT_IR_BYTES = 64 * 1024 * 1024
    WRAPPER_MODEL = "BACTalkRumocaProbe"

    def __init__(
        self,
        *,
        binary: Path = Path(".vendor/bin/rumoca"),
        rumoca_checkout: Path = Path(".vendor/rumoca"),
        buildings_root: Path = Path(".vendor/modelica-buildings-rumoca"),
        standard_library_root: Path = Path(".vendor/modelica-standard-library"),
        library: G36Library | None = None,
    ):
        self.binary = binary.resolve()
        self.rumoca_checkout = rumoca_checkout.resolve()
        self.buildings_root = buildings_root.resolve()
        self.standard_library_root = standard_library_root.resolve()
        self.library = library or G36Library()

    def _controller(self, controller_id: str) -> dict[str, Any]:
        controllers = {
            item["id"]: item for item in self.library.catalog()["controllers"]
        }
        try:
            return controllers[controller_id]
        except KeyError as exc:
            raise KeyError(controller_id) from exc

    def _check_runtime(self) -> None:
        if not self.binary.is_file() or not os.access(self.binary, os.X_OK):
            raise FileNotFoundError(f"Rumoca binary not found: {self.binary}")
        if not (self.buildings_root / "Buildings/package.mo").is_file():
            raise FileNotFoundError(
                f"Rumoca Buildings source root not found: {self.buildings_root}"
            )
        if not (self.standard_library_root / "Modelica/package.mo").is_file():
            raise FileNotFoundError(
                "Modelica Standard Library source root not found: "
                f"{self.standard_library_root}"
            )

    @classmethod
    def _wrapper(
        cls,
        controller_id: str,
        parameters: dict[str, float | int | bool | str],
    ) -> str:
        if len(parameters) > cls.MAX_PARAMETERS:
            raise ValueError(f"at most {cls.MAX_PARAMETERS} Modelica parameters are allowed")
        assignments: list[str] = []
        for name, value in sorted(parameters.items()):
            if not _IDENTIFIER.fullmatch(name):
                raise ValueError(f"invalid Modelica parameter name: {name!r}")
            assignments.append(f"{name}={_modelica_literal(value)}")
        target = f"Buildings.Controls.OBC.ASHRAE.G36.{controller_id}"
        modification = f"({','.join(assignments)})" if assignments else ""
        # The explicit MSL-typed parameter is intentional. Rumoca 0.10 lazily
        # loads source roots referenced by the compile unit; Buildings reaches
        # MSL transitively, which otherwise leaves that root unloaded.
        return (
            f"model {cls.WRAPPER_MODEL}\n"
            f"  extends {target}{modification};\n"
            "  parameter Modelica.Units.SI.Time bactalkMslProbe = 0;\n"
            f"end {cls.WRAPPER_MODEL};\n"
        )

    def flatten_g36(
        self,
        controller_id: str,
        *,
        parameters: dict[str, float | int | bool | str] | None = None,
        timeout: float = 180.0,
    ) -> dict[str, Any]:
        """Flatten one allowlisted G36 class without executing arbitrary Modelica code."""

        controller = self._controller(controller_id)
        self._check_runtime()
        wrapper = self._wrapper(controller_id, parameters or {})
        with tempfile.TemporaryDirectory(prefix="bactalk-rumoca-") as directory:
            root = Path(directory)
            source = root / "probe.mo"
            output = root / "flat.json"
            source.write_text(wrapper, encoding="utf-8")
            command = [
                str(self.binary),
                "compile",
                str(source),
                "--model",
                self.WRAPPER_MODEL,
                "--source-root",
                str(self.buildings_root),
                "--source-root",
                str(self.standard_library_root),
                "--emit",
                "flat-json",
                "--output",
                str(output),
            ]
            environment = os.environ.copy()
            environment["NO_COLOR"] = "1"
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
                raise RumocaError("Rumoca flattening exceeded its time limit") from exc
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or exc.stdout or str(exc)).strip()
                detail = _ANSI_ESCAPE.sub("", detail)
                detail = detail.replace("│", " ")
                detail = re.sub(r"\s+", " ", detail).strip()
                raise RumocaError(f"Rumoca rejected G36 model: {detail[-8_000:]}") from exc
            if not output.is_file():
                raise RumocaError("Rumoca did not emit flattened JSON")
            if output.stat().st_size > self.MAX_FLAT_IR_BYTES:
                raise RumocaError(
                    f"Rumoca flat IR exceeds the {self.MAX_FLAT_IR_BYTES}-byte limit"
                )
            try:
                flat_ir = json.loads(output.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise RumocaError("Rumoca emitted invalid flattened JSON") from exc

        variables = flat_ir.get("variables")
        equations = flat_ir.get("equations")
        if not isinstance(variables, dict) or not isinstance(equations, list):
            raise RumocaError("Rumoca flat IR is missing variables or equations")
        warnings = [line for line in completed.stderr.splitlines() if "warning[" in line]
        encoded = json.dumps(flat_ir, sort_keys=True, separators=(",", ":")).encode()
        return {
            "schema": "bactalk.rumoca-flatten/v1",
            "controller": controller,
            "parameter_overrides": dict(sorted((parameters or {}).items())),
            "variable_count": len(variables),
            "equation_count": len(equations),
            "initial_equation_count": len(flat_ir.get("initial_equations", [])),
            "when_chain_count": len(flat_ir.get("when_chains", [])),
            "top_level_input_count": len(flat_ir.get("top_level_input_components", [])),
            "top_level_connector_count": len(flat_ir.get("top_level_connectors", [])),
            "warning_count": len(warnings),
            "flat_ir_sha256": hashlib.sha256(encoded).hexdigest(),
            "provenance": {
                "rumoca_revision": _git_head(self.rumoca_checkout),
                "rumoca_binary_sha256": _sha256(self.binary),
                "modelica_buildings_revision": _git_head(self.buildings_root),
                "modelica_standard_library_revision": _git_head(
                    self.standard_library_root
                ),
                "source_sha256": controller["source_sha256"],
                "wrapper_sha256": hashlib.sha256(wrapper.encode()).hexdigest(),
            },
            "flat_ir": flat_ir,
        }
