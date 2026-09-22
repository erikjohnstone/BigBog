"""JVM sidecar: run the Java kernels through ``KernelHarness``'s session protocol.

When a JDK is present the Shadow Runtime steps every ``bactalkG36`` component
through the real Java kernels (docs/decisions/007). The classes are compiled
once per kernel-source digest into a cache directory and one harness process
serves a whole run; each ``step`` is one line out and one line back.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from bactalk.niagara.kernels import (
    HARNESS_CLASS,
    KERNEL_SOURCES,
    compile_kernels,
    javac_available,
)


class SidecarError(RuntimeError):
    pass


def kernel_source_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(KERNEL_SOURCES.glob("*.java")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def kernel_classes_dir(cache_root: Path | None = None) -> Path:
    """Compile the kernels into a digest-keyed cache directory and return it."""

    if not javac_available():
        raise SidecarError("javac/java not found; the JVM sidecar needs a JDK")
    root = cache_root or Path(
        os.environ.get("BACTALK_KERNEL_CACHE")
        or Path(tempfile.gettempdir()) / "bactalk-shadow-kernels"
    )
    target = root / kernel_source_digest()
    marker = target / ".complete"
    if marker.exists():
        return target
    scratch = root / f".build-{os.getpid()}"
    if scratch.exists():
        shutil.rmtree(scratch)
    compile_kernels(scratch)
    (scratch / ".complete").write_text("ok\n")
    if marker.exists():
        shutil.rmtree(scratch)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(scratch, target)
    return target


def _render_param(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _render_cell(value: float | bool) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return repr(float(value))


class KernelSidecar:
    """One harness process holding any number of kernels."""

    def __init__(self, classes: Path | None = None) -> None:
        self.classes = classes or kernel_classes_dir()
        self.process = subprocess.Popen(
            ["java", "-cp", str(self.classes), HARNESS_CLASS],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._next = 0

    def _send(self, line: str) -> str:
        assert self.process.stdin is not None and self.process.stdout is not None
        try:
            self.process.stdin.write(line + "\n")
            self.process.stdin.flush()
            reply = self.process.stdout.readline()
        except (BrokenPipeError, ValueError) as exc:
            raise SidecarError(self._failure("sidecar pipe closed")) from exc
        if reply == "":
            raise SidecarError(self._failure("sidecar exited"))
        return reply.rstrip("\n")

    def _failure(self, prefix: str) -> str:
        stderr = ""
        if self.process.stderr is not None:
            try:
                stderr = self.process.stderr.read()
            except ValueError:
                stderr = ""
        return f"{prefix}: {stderr.strip()}"

    def open(self, kernel: str, params: Mapping[str, object]) -> str:
        self._next += 1
        ident = f"k{self._next}"
        rendered = " ".join(f"{key}={_render_param(value)}" for key, value in params.items())
        reply = self._send(f"open {ident} {kernel} {rendered}".rstrip())
        if reply != f"ok {ident}":
            raise SidecarError(f"unexpected reply to open: {reply!r}")
        return ident

    def step(
        self, ident: str, time_seconds: float, inputs: Sequence[float | bool]
    ) -> tuple[float | bool, ...]:
        cells = " ".join(_render_cell(value) for value in inputs)
        reply = self._send(f"step {ident} {repr(float(time_seconds))} {cells}".rstrip())
        return parse_reply(reply)

    def close_kernel(self, ident: str) -> None:
        self._send(f"close {ident}")

    def close(self) -> None:
        if self.process.poll() is None:
            try:
                assert self.process.stdin is not None
                self.process.stdin.write("end\n")
                self.process.stdin.flush()
            except (BrokenPipeError, ValueError):
                pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None:
                stream.close()

    def __enter__(self) -> KernelSidecar:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def parse_reply(reply: str) -> tuple[float | bool, ...]:
    values: list[float | bool] = []
    for cell in reply.split(","):
        token = cell.strip()
        if token == "true":
            values.append(True)
        elif token == "false":
            values.append(False)
        else:
            values.append(float(token))
    return tuple(values)


def sidecar_available() -> bool:
    return javac_available()


__all__ = [
    "KernelSidecar",
    "SidecarError",
    "kernel_classes_dir",
    "kernel_source_digest",
    "parse_reply",
    "sidecar_available",
]
