from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class SequenceReviewIntegrityError(ValueError):
    """Raised when retained review evidence no longer matches its manifest."""


class SequenceRequirementReviewRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_name: Literal["bactalk.sequence-requirement-review-record/v1"] = Field(
        default="bactalk.sequence-requirement-review-record/v1", alias="schema"
    )
    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    template_id: str = Field(min_length=1, max_length=500)
    selections: dict[str, Any]
    created_at: datetime
    source_filename: str = Field(min_length=1, max_length=255)
    source_media_type: str = Field(min_length=1, max_length=200)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    result: dict[str, Any]


def _canonical_json(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", by_alias=True)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _artifact_payload(
    *,
    record_id: str,
    template_id: str,
    selections: dict[str, Any],
    created_at: datetime,
    source_filename: str,
    source_media_type: str,
    source_sha256: str,
    candidate_digest: str,
    review_digest: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": record_id,
        "template_id": template_id,
        "selections": selections,
        "created_at": created_at.isoformat(),
        "source_filename": source_filename,
        "source_media_type": source_media_type,
        "source_sha256": source_sha256,
        "candidate_digest": candidate_digest,
        "review_digest": review_digest,
        "result": result,
    }


class SequenceRequirementReviewRepository:
    """Append-only, hash-verified evidence store for sequence requirement reviews."""

    SOURCE_NAME = "source.bin"
    MANIFEST_NAME = "manifest.json"

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._discard_stale_staging_directories()

    def _directory(self, review_id: str, *, staging: bool = False) -> Path:
        if re.fullmatch(r"[0-9a-f]{32}", review_id) is None:
            raise ValueError("invalid sequence requirement review id")
        name = f".{review_id}.staging" if staging else review_id
        return self.root / name

    @staticmethod
    def _write_bytes(path: Path, value: bytes) -> None:
        with path.open("xb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())

    @classmethod
    def _write_text(cls, path: Path, value: str) -> None:
        cls._write_bytes(path, value.encode("utf-8"))

    def save(
        self,
        *,
        template_id: str,
        selections: dict[str, Any],
        source_content: bytes,
        source_filename: str,
        source_media_type: str,
        result: dict[str, Any],
    ) -> SequenceRequirementReviewRecord:
        if Path(source_filename).name != source_filename:
            raise ValueError("sequence source filename must not contain a path")
        if result.get("schema") != "bactalk.sequence-requirement-review/v1":
            raise ValueError("unsupported sequence requirement review result")
        source_sha256 = _sha256(source_content)
        if source_sha256 != result.get("source_sha256"):
            raise SequenceReviewIntegrityError(
                "sequence review source hash does not match uploaded source bytes"
            )
        candidate_digest = str(result.get("candidate_digest", ""))
        review_digest = str(result.get("review_digest", ""))
        if re.fullmatch(r"[0-9a-f]{64}", candidate_digest) is None:
            raise ValueError("sequence review candidate digest is invalid")
        if re.fullmatch(r"[0-9a-f]{64}", review_digest) is None:
            raise ValueError("sequence review digest is invalid")

        review_id = uuid4().hex
        created_at = datetime.now(UTC)
        payload = _artifact_payload(
            record_id=review_id,
            template_id=template_id,
            selections=selections,
            created_at=created_at,
            source_filename=source_filename,
            source_media_type=source_media_type,
            source_sha256=source_sha256,
            candidate_digest=candidate_digest,
            review_digest=review_digest,
            result=result,
        )
        record = SequenceRequirementReviewRecord(
            id=review_id,
            template_id=template_id,
            selections=selections,
            created_at=created_at,
            source_filename=source_filename,
            source_media_type=source_media_type,
            source_sha256=source_sha256,
            candidate_digest=candidate_digest,
            review_digest=review_digest,
            artifact_digest=_sha256(_canonical_json(payload).encode("utf-8")),
            result=result,
        )

        staging = self._directory(review_id, staging=True)
        final = self._directory(review_id)
        staging.mkdir(parents=False, exist_ok=False)
        try:
            self._write_bytes(staging / self.SOURCE_NAME, source_content)
            self._write_text(staging / self.MANIFEST_NAME, _canonical_json(record))
            if final.exists():
                raise FileExistsError(final)
            os.replace(staging, final)
            directory_fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise
        return record

    def get(self, review_id: str) -> SequenceRequirementReviewRecord:
        directory = self._directory(review_id)
        manifest = directory / self.MANIFEST_NAME
        source = directory / self.SOURCE_NAME
        if not manifest.exists():
            raise KeyError(review_id)
        try:
            record = SequenceRequirementReviewRecord.model_validate_json(
                manifest.read_text(encoding="utf-8")
            )
        except (ValueError, json.JSONDecodeError) as exc:
            raise SequenceReviewIntegrityError(
                f"sequence requirement review {review_id} manifest is invalid"
            ) from exc
        if record.id != review_id:
            raise SequenceReviewIntegrityError(
                f"sequence requirement review {review_id} manifest identity changed"
            )
        if not source.is_file():
            raise SequenceReviewIntegrityError(
                f"sequence requirement review {review_id} source is missing"
            )
        if _sha256(source.read_bytes()) != record.source_sha256:
            raise SequenceReviewIntegrityError(
                f"sequence requirement review {review_id} source hash changed"
            )
        if record.result.get("source_sha256") != record.source_sha256:
            raise SequenceReviewIntegrityError(
                f"sequence requirement review {review_id} result source hash changed"
            )
        if record.result.get("candidate_digest") != record.candidate_digest:
            raise SequenceReviewIntegrityError(
                f"sequence requirement review {review_id} candidate digest changed"
            )
        if record.result.get("review_digest") != record.review_digest:
            raise SequenceReviewIntegrityError(
                f"sequence requirement review {review_id} review digest changed"
            )
        payload = _artifact_payload(
            record_id=record.id,
            template_id=record.template_id,
            selections=record.selections,
            created_at=record.created_at,
            source_filename=record.source_filename,
            source_media_type=record.source_media_type,
            source_sha256=record.source_sha256,
            candidate_digest=record.candidate_digest,
            review_digest=record.review_digest,
            result=record.result,
        )
        digest = _sha256(_canonical_json(payload).encode("utf-8"))
        if digest != record.artifact_digest:
            raise SequenceReviewIntegrityError(
                f"sequence requirement review {review_id} artifact digest changed"
            )
        return record

    def source(self, review_id: str) -> bytes:
        self.get(review_id)
        return (self._directory(review_id) / self.SOURCE_NAME).read_bytes()

    def list(self) -> list[SequenceRequirementReviewRecord]:
        records = [self.get(path.parent.name) for path in self.root.glob("*/manifest.json")]
        return sorted(records, key=lambda item: item.created_at, reverse=True)

    def _discard_stale_staging_directories(self) -> None:
        for candidate in self.root.iterdir():
            if candidate.is_dir() and re.fullmatch(
                r"\.[0-9a-f]{32}\.staging", candidate.name
            ):
                shutil.rmtree(candidate)
