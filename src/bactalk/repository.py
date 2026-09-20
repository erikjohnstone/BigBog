from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from bactalk.domain import RunRecord, canonical_json


class RunRepository:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._discard_stale_staging_directories()

    def run_directory(self, run_id: str) -> Path:
        if not run_id.isalnum():
            raise ValueError("invalid run id")
        return self.root / run_id

    def staging_directory(self, run_id: str) -> Path:
        if not run_id.isalnum():
            raise ValueError("invalid run id")
        return self.root / f".{run_id}.staging"

    def begin_staged(self, run_id: str) -> Path:
        staging = self.staging_directory(run_id)
        final = self.run_directory(run_id)
        if final.exists():
            raise FileExistsError(final)
        staging.mkdir(parents=False, exist_ok=False)
        return staging

    def commit_staged(self, staging: Path, record: RunRecord) -> None:
        expected = self.staging_directory(record.id)
        resolved = staging.resolve()
        if resolved != expected:
            raise ValueError("staging directory does not match run id")
        final = self.run_directory(record.id)
        if final.exists():
            raise FileExistsError(final)
        manifest = staging / "manifest.json"
        if Path(record.manifest_path).resolve() != (final / "manifest.json").resolve():
            raise ValueError("record manifest path does not point at final run directory")
        manifest.write_text(canonical_json(record), encoding="utf-8")
        os.replace(staging, final)

    def discard_staged(self, run_id: str) -> None:
        staging = self.staging_directory(run_id)
        if staging.exists():
            shutil.rmtree(staging)

    def _discard_stale_staging_directories(self) -> None:
        for candidate in self.root.iterdir():
            if candidate.is_dir() and re.fullmatch(r"\.[A-Za-z0-9]+\.staging", candidate.name):
                shutil.rmtree(candidate)

    def save(self, record: RunRecord) -> None:
        manifest = Path(record.manifest_path)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{manifest.name}.",
            suffix=".tmp",
            dir=manifest.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(canonical_json(record))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, manifest)
        finally:
            temporary.unlink(missing_ok=True)

    def get(self, run_id: str) -> RunRecord:
        manifest = self.run_directory(run_id) / "manifest.json"
        if not manifest.exists():
            raise KeyError(run_id)
        return RunRecord.model_validate_json(manifest.read_text(encoding="utf-8"))

    def list(self) -> list[RunRecord]:
        records: list[RunRecord] = []
        for manifest in self.root.glob("*/manifest.json"):
            try:
                records.append(RunRecord.model_validate_json(manifest.read_text(encoding="utf-8")))
            except (ValueError, json.JSONDecodeError):
                continue
        return sorted(records, key=lambda item: item.created_at, reverse=True)

    def clean(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
