"""Compile and drive the ``bactalkG36`` Java kernels without a Niagara runtime.

The kernels live under ``niagara-module/bactalkG36`` in the repository (they are
not package data: a base install never needs them). This module gives the tests a
``javac`` front end and a driver for ``KernelHarness`` so every kernel can be
compared with the IR interpreter and the Open Control Engine goldens.

``python -m bactalk.niagara.kernels --check`` compiles the kernels and the
component wrappers (against the ``javax.baja`` stubs) and reports what it built.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_ROOT = REPO_ROOT / "niagara-module" / "bactalkG36"
KERNEL_SOURCES = MODULE_ROOT / "bactalkG36-rt" / "src" / "com" / "bactalk" / "g36" / "kernel"
COMPONENT_SOURCES = MODULE_ROOT / "bactalkG36-rt" / "src" / "com" / "bactalk" / "g36"
STUB_SOURCES = REPO_ROOT / "niagara-module" / "stubs" / "src"
HARNESS_CLASS = "com.bactalk.g36.kernel.KernelHarness"

_JAVA_ENV_KEYS = ("JAVA_TOOL_OPTIONS",)


def javac_available() -> bool:
    return shutil.which("javac") is not None and shutil.which("java") is not None


def _javac(sources: Iterable[Path], destination: Path, *, sourcepath: Path | None = None) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    command = ["javac", "-Xlint:all", "-Werror", "-d", str(destination)]
    if sourcepath is not None:
        command += ["-sourcepath", str(sourcepath)]
    command += [str(path) for path in sources]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError("javac failed:\n" + result.stdout + result.stderr)


def compile_kernels(destination: Path) -> Path:
    """Compile the plain-Java kernels and the harness; returns the classes directory."""

    _javac(sorted(KERNEL_SOURCES.glob("*.java")), destination)
    return destination


def compile_components(destination: Path) -> Path:
    """Compile the kernels, the stubs and the component wrappers together."""

    sources = [
        *sorted(STUB_SOURCES.rglob("*.java")),
        *sorted(KERNEL_SOURCES.glob("*.java")),
        *sorted(COMPONENT_SOURCES.glob("*.java")),
    ]
    _javac(sources, destination)
    return destination


def run_kernel(
    classes: Path,
    kernel: str,
    params: Mapping[str, object],
    rows: Sequence[Sequence[float | bool]],
) -> list[str]:
    """Drive one kernel through ``KernelHarness``; one output line per row."""

    lines = [f"kernel {kernel}"]
    for key, value in params.items():
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = str(value)
        lines.append(f"param {key}={rendered}")
    for row in rows:
        cells = " ".join(
            ("1" if cell else "0") if isinstance(cell, bool) else repr(float(cell)) for cell in row
        )
        lines.append(f"row {cells}")
    lines.append("end")
    result = subprocess.run(
        ["java", "-cp", str(classes), HARNESS_CLASS],
        input="\n".join(lines) + "\n",
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{kernel} harness failed:\n{result.stderr}")
    return result.stdout.splitlines()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile the bactalkG36 kernels and wrappers.")
    parser.add_argument("--check", action="store_true", required=True)
    parser.parse_args(argv)
    if not javac_available():
        print("javac/java not found; install a JDK (21 recommended)")
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        kernels = compile_kernels(Path(tmp) / "kernels")
        kernel_classes = sorted(path.name for path in kernels.rglob("*.class"))
        components = compile_components(Path(tmp) / "components")
        component_classes = sorted(
            path.stem for path in (components / "com" / "bactalk" / "g36").glob("B*.class")
        )
    print(f"kernels: {len(kernel_classes)} classes")
    print("components (against stubs): " + ", ".join(component_classes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
