from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

TranslationMode = Literal["cdl", "modelica"]


class CdlTranslator:
    """Run LBNL modelica-json as a separate, version-pinned build tool."""

    def __init__(
        self,
        modelica_json_checkout: Path,
        *,
        node_binary: str = "node",
        modelica_path: Path | None = None,
    ):
        self.checkout = modelica_json_checkout.resolve()
        self.node_binary = node_binary
        self.modelica_path = modelica_path.resolve() if modelica_path else None

    def build_command(
        self,
        source: Path,
        output_directory: Path,
        *,
        mode: TranslationMode = "cdl",
    ) -> list[str]:
        if mode not in {"cdl", "modelica"}:
            raise ValueError(f"unsupported Modelica translation mode: {mode!r}")
        app = self.checkout / "app.js"
        if not app.is_file():
            raise FileNotFoundError(f"modelica-json app.js not found under {self.checkout}")
        source_path = source.absolute()
        try:
            source_argument = str(source_path.relative_to(self.checkout))
        except ValueError:
            source_argument = str(source_path)
        return [
            self.node_binary,
            str(app),
            "-f",
            source_argument,
            "-o",
            "cxf",
            "-m",
            mode,
            "-d",
            str(output_directory.resolve()),
            "-p",
            "-l",
            "error",
        ]

    def translate(
        self,
        source: Path,
        output_directory: Path,
        *,
        mode: TranslationMode = "cdl",
        timeout: float = 120.0,
    ) -> list[Path]:
        output_directory.mkdir(parents=True, exist_ok=True)
        before = set(output_directory.rglob("*"))
        environment = os.environ.copy()
        with tempfile.TemporaryDirectory(prefix="bactalk-modelica-") as alias_directory:
            source_for_command = source
            if self.modelica_path:
                source_resolved = source.resolve()
                try:
                    relative_source = source_resolved.relative_to(self.modelica_path)
                except ValueError:
                    environment["MODELICAPATH"] = str(self.modelica_path)
                else:
                    # modelica-json strips leading dots from absolute path segments.
                    # A temporary visible alias makes hidden checkouts such as `.vendor`
                    # usable without copying or modifying the upstream source tree.
                    alias_root = Path(alias_directory)
                    top_level = relative_source.parts[0]
                    (alias_root / top_level).symlink_to(
                        self.modelica_path / top_level,
                        target_is_directory=True,
                    )
                    source_for_command = alias_root / relative_source
                    environment["MODELICAPATH"] = str(alias_root)
            command = self.build_command(
                source_for_command,
                output_directory,
                mode=mode,
            )
            try:
                subprocess.run(
                    command,
                    cwd=self.checkout,
                    check=True,
                    capture_output=True,
                    text=True,
                    env=environment,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("modelica-json translation exceeded its time limit") from exc
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or exc.stdout or str(exc)).strip()
                raise RuntimeError(f"modelica-json translation failed: {detail}") from exc
        generated = [
            path for path in output_directory.rglob("*") if path.is_file() and path not in before
        ]
        if not generated:
            raise RuntimeError("modelica-json completed without producing a CXF artifact")
        return sorted(generated)
