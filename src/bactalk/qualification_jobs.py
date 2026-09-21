from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import shutil
import tempfile
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from importlib import metadata
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import uuid4

import httpx
from alfalfa_client import AlfalfaClient
from pydantic import BaseModel, ConfigDict, Field, model_validator

from bactalk.domain import canonical_json
from bactalk.integrations.alfalfa import AlfalfaClientLike
from bactalk.integrations.alfalfa_graph import (
    AlfalfaGraphMap,
    AlfalfaQualificationCancelled,
    AlfalfaTrajectoryOracle,
)
from bactalk.integrations.boptest import BoptestClient
from bactalk.integrations.boptest_graph import (
    BoptestGraphMap,
    BoptestQualificationCancelled,
    BoptestRuntime,
    BoptestTrajectoryOracle,
)
from bactalk.repository import RunRepository
from bactalk.service import MAX_ALFALFA_MODEL_BYTES, WorkbenchService


class QualificationJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELED = "canceled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


TERMINAL_JOB_STATUSES = {
    QualificationJobStatus.CANCELED,
    QualificationJobStatus.SUCCEEDED,
    QualificationJobStatus.FAILED,
}

QUALIFICATION_HEARTBEAT_SECONDS = 10
QUALIFICATION_LEASE_SECONDS = 300


class QualificationJobIntegrityError(RuntimeError):
    pass


class AlfalfaQualificationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mapping: AlfalfaGraphMap
    oracles: list[AlfalfaTrajectoryOracle] = Field(min_length=1, max_length=1_000)
    steps: int = Field(ge=1, le=100_000)
    step_seconds: float = Field(gt=0, le=86_400, allow_inf_nan=False)
    start: datetime
    transport: Literal["direct", "bacnet_ip_loopback"] = "direct"


class BoptestQualificationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mapping: BoptestGraphMap
    oracles: list[BoptestTrajectoryOracle] = Field(min_length=1, max_length=1_000)
    steps: int = Field(ge=1, le=100_000)
    step_seconds: float = Field(gt=0, le=86_400, allow_inf_nan=False)
    start_time: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    warmup_period: float = Field(default=0.0, ge=0, allow_inf_nan=False)


class QualificationJobProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase: str = Field(min_length=1, max_length=120)
    completed_steps: int = Field(ge=0)
    total_steps: int = Field(ge=0)
    percent: float = Field(ge=0, le=100, allow_inf_nan=False)


class QualificationJobRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[
        "bactalk.qualification-job/v1",
        "bactalk.qualification-job/v2",
        "bactalk.qualification-job/v3",
    ] = "bactalk.qualification-job/v3"
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    broker_job_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    run_id: str = Field(pattern=r"^[A-Za-z0-9]+$")
    candidate_artifact_sha256: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{64}$"
    )
    kind: Literal["alfalfa", "boptest"] = "alfalfa"
    transport: Literal["direct", "bacnet_ip_loopback", "boptest_rest"]
    status: QualificationJobStatus
    model_filename: str | None = Field(default=None, min_length=1, max_length=240)
    model_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    request_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    input_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    heartbeat_at: datetime | None = None
    lease_expires_at: datetime | None = None
    worker_id: str | None = Field(default=None, max_length=240)
    actor_id: str | None = Field(default=None, max_length=240)
    tenant_id: str | None = Field(default=None, max_length=240)
    progress: QualificationJobProgress
    cancellation_requested: bool = False
    error: str | None = Field(default=None, max_length=4_000)
    result_artifact_sha256: str | None = Field(
        default=None, pattern=r"^[a-f0-9]{64}$"
    )
    qualification_passed: bool | None = None

    @model_validator(mode="after")
    def valid_kind_contract(self) -> QualificationJobRecord:
        if (
            self.schema_version == "bactalk.qualification-job/v3"
            and self.candidate_artifact_sha256 is None
        ):
            raise ValueError("v3 qualification jobs require the submitted candidate digest")
        if self.kind == "alfalfa":
            if self.transport not in {"direct", "bacnet_ip_loopback"}:
                raise ValueError("Alfalfa qualification has an invalid transport")
            if self.model_filename is None or self.model_sha256 is None:
                raise ValueError("Alfalfa qualification requires an immutable FMU")
        else:
            if self.transport != "boptest_rest":
                raise ValueError("BOPTEST qualification has an invalid transport")
            if self.model_filename is not None or self.model_sha256 is not None:
                raise ValueError("BOPTEST qualification cannot contain an uploaded FMU")
        return self


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _qualification_input_sha256(
    *,
    schema_version: str,
    kind: str,
    run_id: str,
    candidate_artifact_sha256: str | None,
    request_sha256: str,
    model_sha256: str | None,
) -> str:
    if schema_version == "bactalk.qualification-job/v1":
        return _sha256_bytes(
            f"{run_id}:{request_sha256}:{model_sha256 or ''}".encode()
        )
    if schema_version == "bactalk.qualification-job/v2":
        return _sha256_bytes(
            f"{kind}:{run_id}:{request_sha256}:{model_sha256 or '-'}".encode()
        )
    if candidate_artifact_sha256 is None:
        raise QualificationJobIntegrityError(
            "v3 qualification job is missing its submitted candidate digest"
        )
    return _sha256_bytes(
        (
            f"{kind}:{run_id}:{candidate_artifact_sha256}:"
            f"{request_sha256}:{model_sha256 or '-'}"
        ).encode()
    )


def _atomic_text(path: Path, value: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class QualificationJobRepository:
    """Durable local metadata and immutable inputs for external queue workers."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.root / ".repository.lock"

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self.lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def job_directory(self, job_id: str) -> Path:
        if len(job_id) != 32 or any(character not in "0123456789abcdef" for character in job_id):
            raise ValueError("invalid qualification job id")
        return self.root / job_id

    def record_path(self, job_id: str) -> Path:
        return self.job_directory(job_id) / "record.json"

    def request_path(self, job_id: str) -> Path:
        return self.job_directory(job_id) / "request.json"

    def model_path(self, job_id: str) -> Path:
        return self.job_directory(job_id) / "model.fmu"

    def _read_unlocked(self, job_id: str, *, verify: bool = True) -> QualificationJobRecord:
        path = self.record_path(job_id)
        if not path.is_file():
            raise KeyError(job_id)
        record = QualificationJobRecord.model_validate_json(path.read_text(encoding="utf-8"))
        if verify:
            if _sha256_file(self.request_path(job_id)) != record.request_sha256:
                raise QualificationJobIntegrityError(
                    f"qualification job {job_id} request digest changed"
                )
            if record.model_sha256 is not None:
                if _sha256_file(self.model_path(job_id)) != record.model_sha256:
                    raise QualificationJobIntegrityError(
                        f"qualification job {job_id} FMU digest changed"
                    )
            expected = _qualification_input_sha256(
                schema_version=record.schema_version,
                kind=record.kind,
                run_id=record.run_id,
                candidate_artifact_sha256=record.candidate_artifact_sha256,
                request_sha256=record.request_sha256,
                model_sha256=record.model_sha256,
            )
            if expected != record.input_sha256:
                raise QualificationJobIntegrityError(
                    f"qualification job {job_id} input digest is invalid"
                )
        return record

    def _save_unlocked(self, record: QualificationJobRecord) -> QualificationJobRecord:
        updated = record.model_copy(update={"updated_at": datetime.now(UTC)})
        _atomic_text(self.record_path(record.id), canonical_json(updated))
        return updated

    def create(
        self,
        *,
        run_id: str,
        candidate_artifact_sha256: str,
        payload: AlfalfaQualificationPayload,
        model_bytes: bytes,
        model_filename: str,
        actor_id: str | None = None,
        tenant_id: str | None = None,
    ) -> QualificationJobRecord:
        if not run_id.isalnum():
            raise ValueError("invalid run id")
        if not model_bytes:
            raise ValueError("Alfalfa FMU is empty")
        if len(model_bytes) > MAX_ALFALFA_MODEL_BYTES:
            raise ValueError(f"Alfalfa FMU exceeds the {MAX_ALFALFA_MODEL_BYTES}-byte limit")
        safe_filename = Path(model_filename).name
        if safe_filename != model_filename or not safe_filename.lower().endswith(".fmu"):
            raise ValueError("Alfalfa model filename must be a basename ending in .fmu")
        request_bytes = canonical_json(payload).encode("utf-8")
        request_sha256 = _sha256_bytes(request_bytes)
        model_sha256 = _sha256_bytes(model_bytes)
        now = datetime.now(UTC)
        with self._locked():
            for path in self.root.glob("*/record.json"):
                try:
                    existing = QualificationJobRecord.model_validate_json(
                        path.read_text(encoding="utf-8")
                    )
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                if (
                    existing.run_id == run_id
                    and existing.status not in TERMINAL_JOB_STATUSES
                ):
                    raise ValueError(
                        f"run {run_id} already has active qualification job {existing.id}"
                    )
            job_id = uuid4().hex
            staging = self.root / f".{job_id}.staging"
            final = self.job_directory(job_id)
            staging.mkdir()
            try:
                (staging / "model.fmu").write_bytes(model_bytes)
                (staging / "request.json").write_bytes(request_bytes)
                record = QualificationJobRecord(
                    id=job_id,
                    broker_job_id=job_id,
                    run_id=run_id,
                    candidate_artifact_sha256=candidate_artifact_sha256,
                    kind="alfalfa",
                    transport=payload.transport,
                    status=QualificationJobStatus.QUEUED,
                    model_filename=safe_filename,
                    model_sha256=model_sha256,
                    request_sha256=request_sha256,
                    input_sha256=_qualification_input_sha256(
                        schema_version="bactalk.qualification-job/v3",
                        kind="alfalfa",
                        run_id=run_id,
                        candidate_artifact_sha256=candidate_artifact_sha256,
                        request_sha256=request_sha256,
                        model_sha256=model_sha256,
                    ),
                    created_at=now,
                    updated_at=now,
                    actor_id=actor_id,
                    tenant_id=tenant_id,
                    progress=QualificationJobProgress(
                        phase="queued", completed_steps=0, total_steps=payload.steps, percent=0
                    ),
                )
                (staging / "record.json").write_text(
                    canonical_json(record), encoding="utf-8"
                )
                os.replace(staging, final)
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
        return record

    def create_boptest(
        self,
        *,
        run_id: str,
        candidate_artifact_sha256: str,
        payload: BoptestQualificationPayload,
        actor_id: str | None = None,
        tenant_id: str | None = None,
    ) -> QualificationJobRecord:
        if not run_id.isalnum():
            raise ValueError("invalid run id")
        request_bytes = canonical_json(payload).encode("utf-8")
        request_sha256 = _sha256_bytes(request_bytes)
        now = datetime.now(UTC)
        with self._locked():
            for path in self.root.glob("*/record.json"):
                try:
                    existing = QualificationJobRecord.model_validate_json(
                        path.read_text(encoding="utf-8")
                    )
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                if (
                    existing.run_id == run_id
                    and existing.status not in TERMINAL_JOB_STATUSES
                ):
                    raise ValueError(
                        f"run {run_id} already has active qualification job {existing.id}"
                    )
            job_id = uuid4().hex
            staging = self.root / f".{job_id}.staging"
            final = self.job_directory(job_id)
            staging.mkdir()
            try:
                (staging / "request.json").write_bytes(request_bytes)
                record = QualificationJobRecord(
                    id=job_id,
                    broker_job_id=job_id,
                    run_id=run_id,
                    candidate_artifact_sha256=candidate_artifact_sha256,
                    kind="boptest",
                    transport="boptest_rest",
                    status=QualificationJobStatus.QUEUED,
                    request_sha256=request_sha256,
                    input_sha256=_qualification_input_sha256(
                        schema_version="bactalk.qualification-job/v3",
                        kind="boptest",
                        run_id=run_id,
                        candidate_artifact_sha256=candidate_artifact_sha256,
                        request_sha256=request_sha256,
                        model_sha256=None,
                    ),
                    created_at=now,
                    updated_at=now,
                    actor_id=actor_id,
                    tenant_id=tenant_id,
                    progress=QualificationJobProgress(
                        phase="queued",
                        completed_steps=0,
                        total_steps=payload.steps,
                        percent=0,
                    ),
                )
                (staging / "record.json").write_text(
                    canonical_json(record), encoding="utf-8"
                )
                os.replace(staging, final)
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
        return record

    def get(self, job_id: str) -> QualificationJobRecord:
        with self._locked():
            return self._read_unlocked(job_id)

    def payload(
        self, job_id: str
    ) -> AlfalfaQualificationPayload | BoptestQualificationPayload:
        record = self.get(job_id)
        payload_type = (
            AlfalfaQualificationPayload
            if record.kind == "alfalfa"
            else BoptestQualificationPayload
        )
        return payload_type.model_validate_json(
            self.request_path(record.id).read_text(encoding="utf-8")
        )

    def list_for_run(self, run_id: str) -> list[QualificationJobRecord]:
        records: list[QualificationJobRecord] = []
        with self._locked():
            for path in self.root.glob("*/record.json"):
                try:
                    candidate = self._read_unlocked(path.parent.name, verify=False)
                except (KeyError, OSError, ValueError):
                    continue
                if candidate.run_id != run_id:
                    continue
                record = self._read_unlocked(path.parent.name)
                if record.run_id == run_id:
                    records.append(record)
        return sorted(records, key=lambda item: item.created_at, reverse=True)

    def latest_for_run(self, run_id: str) -> QualificationJobRecord:
        records = self.list_for_run(run_id)
        if not records:
            raise KeyError(run_id)
        return records[0]

    def mark_running(self, job_id: str, worker_id: str) -> QualificationJobRecord:
        with self._locked():
            record = self._read_unlocked(job_id)
            if record.status == QualificationJobStatus.CANCELED:
                return record
            if record.status != QualificationJobStatus.QUEUED:
                raise ValueError(f"qualification job {job_id} is {record.status}")
            now = datetime.now(UTC)
            return self._save_unlocked(
                record.model_copy(
                    update={
                        "status": QualificationJobStatus.RUNNING,
                        "started_at": now,
                        "heartbeat_at": now,
                        "lease_expires_at": now
                        + timedelta(seconds=QUALIFICATION_LEASE_SECONDS),
                        "worker_id": worker_id,
                        "progress": QualificationJobProgress(
                            phase="starting", completed_steps=0,
                            total_steps=record.progress.total_steps, percent=0,
                        ),
                    }
                )
            )

    def heartbeat(self, job_id: str) -> QualificationJobRecord:
        with self._locked():
            record = self._read_unlocked(job_id)
            if record.status not in {
                QualificationJobStatus.RUNNING,
                QualificationJobStatus.CANCEL_REQUESTED,
            }:
                return record
            now = datetime.now(UTC)
            return self._save_unlocked(
                record.model_copy(
                    update={
                        "heartbeat_at": now,
                        "lease_expires_at": now
                        + timedelta(seconds=QUALIFICATION_LEASE_SECONDS),
                    }
                )
            )

    def expire_stale(
        self, job_id: str, *, now: datetime | None = None
    ) -> QualificationJobRecord:
        with self._locked():
            record = self._read_unlocked(job_id)
            if record.status not in {
                QualificationJobStatus.RUNNING,
                QualificationJobStatus.CANCEL_REQUESTED,
            }:
                return record
            observed_at = now or datetime.now(UTC)
            lease_expires_at = record.lease_expires_at
            if lease_expires_at is None or observed_at <= lease_expires_at:
                return record
            return self._save_unlocked(
                record.model_copy(
                    update={
                        "status": QualificationJobStatus.FAILED,
                        "completed_at": observed_at,
                        "lease_expires_at": None,
                        "error": (
                            "Qualification worker lease expired; the worker stopped "
                            "heartbeating before it recorded a terminal result"
                        ),
                        "progress": record.progress.model_copy(
                            update={"phase": "worker_lost"}
                        ),
                    }
                )
            )

    def update_progress(
        self, job_id: str, phase: str, completed_steps: int, total_steps: int
    ) -> QualificationJobRecord:
        percent = 0.0 if total_steps == 0 else min(100.0, completed_steps * 100 / total_steps)
        with self._locked():
            record = self._read_unlocked(job_id)
            if record.status not in {
                QualificationJobStatus.RUNNING,
                QualificationJobStatus.CANCEL_REQUESTED,
            }:
                return record
            return self._save_unlocked(
                record.model_copy(
                    update={
                        "progress": QualificationJobProgress(
                            phase=phase,
                            completed_steps=completed_steps,
                            total_steps=total_steps,
                            percent=percent,
                        )
                    }
                )
            )

    def cancellation_requested(self, job_id: str) -> bool:
        return self.get(job_id).cancellation_requested

    def request_cancel(self, job_id: str) -> QualificationJobRecord:
        with self._locked():
            record = self._read_unlocked(job_id)
            if record.status in TERMINAL_JOB_STATUSES:
                return record
            now = datetime.now(UTC)
            if record.status == QualificationJobStatus.QUEUED:
                return self._save_unlocked(
                    record.model_copy(
                        update={
                            "status": QualificationJobStatus.CANCELED,
                            "cancellation_requested": True,
                            "completed_at": now,
                            "lease_expires_at": None,
                            "progress": record.progress.model_copy(
                                update={"phase": "canceled"}
                            ),
                        }
                    )
                )
            return self._save_unlocked(
                record.model_copy(
                    update={
                        "status": QualificationJobStatus.CANCEL_REQUESTED,
                        "cancellation_requested": True,
                        "progress": record.progress.model_copy(
                            update={"phase": "cancel_requested"}
                        ),
                    }
                )
            )

    def mark_canceled(self, job_id: str, detail: str | None = None) -> QualificationJobRecord:
        with self._locked():
            record = self._read_unlocked(job_id)
            if record.status in {
                QualificationJobStatus.SUCCEEDED,
                QualificationJobStatus.FAILED,
            }:
                return record
            return self._save_unlocked(
                record.model_copy(
                    update={
                        "status": QualificationJobStatus.CANCELED,
                        "cancellation_requested": True,
                        "completed_at": datetime.now(UTC),
                        "lease_expires_at": None,
                        "error": detail,
                        "progress": record.progress.model_copy(
                            update={"phase": "canceled"}
                        ),
                    }
                )
            )

    def mark_succeeded(
        self, job_id: str, *, artifact_sha256: str, qualification_passed: bool
    ) -> QualificationJobRecord:
        with self._locked():
            record = self._read_unlocked(job_id)
            if record.status in TERMINAL_JOB_STATUSES:
                return record
            return self._save_unlocked(
                record.model_copy(
                    update={
                        "status": QualificationJobStatus.SUCCEEDED,
                        "completed_at": datetime.now(UTC),
                        "lease_expires_at": None,
                        "result_artifact_sha256": artifact_sha256,
                        "qualification_passed": qualification_passed,
                        "progress": QualificationJobProgress(
                            phase="completed",
                            completed_steps=record.progress.total_steps,
                            total_steps=record.progress.total_steps,
                            percent=100,
                        ),
                    }
                )
            )

    def mark_failed(self, job_id: str, error: str) -> QualificationJobRecord:
        with self._locked():
            record = self._read_unlocked(job_id)
            if record.status in TERMINAL_JOB_STATUSES:
                return record
            return self._save_unlocked(
                record.model_copy(
                    update={
                        "status": QualificationJobStatus.FAILED,
                        "completed_at": datetime.now(UTC),
                        "lease_expires_at": None,
                        "error": error[:4_000],
                        "progress": record.progress.model_copy(update={"phase": "failed"}),
                    }
                )
            )


class QualificationDispatcher(Protocol):
    def enqueue(self, record: QualificationJobRecord) -> None: ...

    def cancel(self, record: QualificationJobRecord) -> None: ...


class RqQualificationDispatcher:
    """Redis/Valkey-backed dispatch using JSON-only RQ payloads."""

    def __init__(
        self,
        *,
        queue_url: str,
        jobs_root: Path,
        runs_root: Path,
        queue_name: str = "bactalk-qualification",
    ) -> None:
        from redis import Redis
        from rq import Queue
        from rq.serializers import JSONSerializer

        self.connection = Redis.from_url(queue_url)
        self.queue = Queue(
            queue_name,
            connection=self.connection,
            serializer=JSONSerializer,
            default_timeout=86_400,
        )
        self.jobs_root = jobs_root.resolve()
        self.runs_root = runs_root.resolve()

    def enqueue(self, record: QualificationJobRecord) -> None:
        from rq.job import Callback

        self.connection.ping()
        function = {
            "alfalfa": "bactalk.qualification_jobs.execute_alfalfa_qualification_job",
            "boptest": "bactalk.qualification_jobs.execute_boptest_qualification_job",
        }[record.kind]
        self.queue.enqueue_call(
            function,
            args=(record.id, str(self.jobs_root), str(self.runs_root)),
            job_id=record.broker_job_id,
            description=(
                f"{record.kind.upper()} qualification for BACTalk run {record.run_id}"
            ),
            timeout=86_400,
            result_ttl=604_800,
            failure_ttl=2_592_000,
            unique=True,
            meta={"jobs_root": str(self.jobs_root), "qualification_job_id": record.id},
            on_failure=Callback(
                "bactalk.qualification_jobs.rq_qualification_failure_callback"
            ),
            on_stopped=Callback(
                "bactalk.qualification_jobs.rq_qualification_stopped_callback"
            ),
        )

    def cancel(self, record: QualificationJobRecord) -> None:
        from rq.job import Job
        from rq.serializers import JSONSerializer

        try:
            broker_job = Job.fetch(
                record.broker_job_id,
                connection=self.connection,
                serializer=JSONSerializer,
            )
        except Exception:  # Broker cancellation is best-effort; durable intent is local.
            return
        if broker_job.get_status(refresh=True) in {"queued", "deferred", "scheduled"}:
            broker_job.cancel()


@contextmanager
def _maintain_worker_lease(
    jobs: QualificationJobRepository, job_id: str
) -> Iterator[None]:
    heartbeat_stop = threading.Event()

    def maintain() -> None:
        while not heartbeat_stop.wait(QUALIFICATION_HEARTBEAT_SECONDS):
            try:
                jobs.heartbeat(job_id)
            except Exception:
                # The foreground path remains authoritative and will retain any failure.
                # A missed heartbeat becomes observable through lease expiry.
                continue

    heartbeat_thread = threading.Thread(
        target=maintain,
        name=f"qualification-heartbeat-{job_id[:8]}",
        daemon=True,
    )
    heartbeat_thread.start()
    try:
        yield
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=QUALIFICATION_HEARTBEAT_SECONDS)


class AlfalfaQualificationJobExecutor:
    def __init__(
        self,
        jobs: QualificationJobRepository,
        service: WorkbenchService,
        *,
        client_factory: Callable[[], AlfalfaClientLike],
        server_version_loader: Callable[[], object] | None = None,
        client_version: str | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.jobs = jobs
        self.service = service
        self.client_factory = client_factory
        self.server_version_loader = server_version_loader
        self.client_version = client_version
        self.worker_id = worker_id or f"pid-{os.getpid()}"

    def execute(self, job_id: str) -> QualificationJobRecord:
        record = self.jobs.mark_running(job_id, self.worker_id)
        if record.status == QualificationJobStatus.CANCELED:
            return record
        client: AlfalfaClientLike | None = None
        try:
            with _maintain_worker_lease(self.jobs, job_id):
                payload = self.jobs.payload(job_id)
                if not isinstance(payload, AlfalfaQualificationPayload):
                    raise ValueError(f"qualification job {job_id} is not an Alfalfa job")
                if record.model_filename is None:
                    raise QualificationJobIntegrityError(
                        f"qualification job {job_id} has no FMU filename"
                    )
                client = self.client_factory()
                server_version = (
                    self.server_version_loader()
                    if self.server_version_loader is not None
                    else None
                )

                def progress(phase: str, completed: int, total: int) -> None:
                    self.jobs.update_progress(job_id, phase, completed, total)

                def canceled() -> bool:
                    return self.jobs.cancellation_requested(job_id)

                if payload.transport == "bacnet_ip_loopback":
                    result = asyncio.run(
                        self.service.qualify_with_alfalfa_bacnet(
                            record.run_id,
                            client=client,
                            mapping=payload.mapping,
                            oracles=payload.oracles,
                            model_bytes=self.jobs.model_path(job_id).read_bytes(),
                            model_filename=record.model_filename,
                            steps=payload.steps,
                            step_seconds=payload.step_seconds,
                            start=payload.start,
                            server_version=server_version,
                            client_version=self.client_version,
                            progress_callback=progress,
                            cancellation_requested=canceled,
                            expected_artifact_sha256=record.candidate_artifact_sha256,
                        )
                    )
                else:
                    result = self.service.qualify_with_alfalfa(
                        record.run_id,
                        client=client,
                        mapping=payload.mapping,
                        oracles=payload.oracles,
                        model_bytes=self.jobs.model_path(job_id).read_bytes(),
                        model_filename=record.model_filename,
                        steps=payload.steps,
                        step_seconds=payload.step_seconds,
                        start=payload.start,
                        server_version=server_version,
                        client_version=self.client_version,
                        progress_callback=progress,
                        cancellation_requested=canceled,
                        expected_artifact_sha256=record.candidate_artifact_sha256,
                    )
                evidence = json.loads(
                    self.service.alfalfa_verification_path(record.run_id).read_text(
                        encoding="utf-8"
                    )
                )
                return self.jobs.mark_succeeded(
                    job_id,
                    artifact_sha256=result.artifact_sha256,
                    qualification_passed=evidence.get("status") == "pass",
                )
        except AlfalfaQualificationCancelled as exc:
            return self.jobs.mark_canceled(job_id, str(exc))
        except Exception as exc:
            self.jobs.mark_failed(job_id, f"{type(exc).__name__}: {exc}")
            raise
        finally:
            close = getattr(client, "close", None) if client is not None else None
            if callable(close):
                close()


class BoptestQualificationJobExecutor:
    def __init__(
        self,
        jobs: QualificationJobRepository,
        service: WorkbenchService,
        *,
        client_factory: Callable[[], BoptestRuntime],
        worker_id: str | None = None,
    ) -> None:
        self.jobs = jobs
        self.service = service
        self.client_factory = client_factory
        self.worker_id = worker_id or f"pid-{os.getpid()}"

    def execute(self, job_id: str) -> QualificationJobRecord:
        record = self.jobs.mark_running(job_id, self.worker_id)
        if record.status == QualificationJobStatus.CANCELED:
            return record
        client: BoptestRuntime | None = None
        try:
            with _maintain_worker_lease(self.jobs, job_id):
                payload = self.jobs.payload(job_id)
                if not isinstance(payload, BoptestQualificationPayload):
                    raise ValueError(f"qualification job {job_id} is not a BOPTEST job")
                client = self.client_factory()

                def progress(phase: str, completed: int, total: int) -> None:
                    self.jobs.update_progress(job_id, phase, completed, total)

                def canceled() -> bool:
                    return self.jobs.cancellation_requested(job_id)

                result = self.service.qualify_with_boptest(
                    record.run_id,
                    client=client,
                    mapping=payload.mapping,
                    oracles=payload.oracles,
                    steps=payload.steps,
                    step_seconds=payload.step_seconds,
                    start_time=payload.start_time,
                    warmup_period=payload.warmup_period,
                    progress_callback=progress,
                    cancellation_requested=canceled,
                    expected_artifact_sha256=record.candidate_artifact_sha256,
                )
                evidence = json.loads(
                    self.service.boptest_verification_path(record.run_id).read_text(
                        encoding="utf-8"
                    )
                )
                return self.jobs.mark_succeeded(
                    job_id,
                    artifact_sha256=result.artifact_sha256,
                    qualification_passed=evidence.get("status") == "pass",
                )
        except BoptestQualificationCancelled as exc:
            return self.jobs.mark_canceled(job_id, str(exc))
        except Exception as exc:
            self.jobs.mark_failed(job_id, f"{type(exc).__name__}: {exc}")
            raise
        finally:
            close = getattr(client, "close", None) if client is not None else None
            if callable(close):
                close()


def _alfalfa_server_version(base_url: str) -> object:
    response = httpx.get(f"{base_url.rstrip('/')}/api/v2/version", timeout=15.0)
    response.raise_for_status()
    body = response.json()
    return body.get("payload", body) if isinstance(body, dict) else body


def execute_alfalfa_qualification_job(
    job_id: str, jobs_root: str, runs_root: str
) -> dict[str, Any]:
    base_url = os.getenv("BACTALK_ALFALFA_URL", "http://127.0.0.1:8088")
    executor = AlfalfaQualificationJobExecutor(
        QualificationJobRepository(Path(jobs_root)),
        WorkbenchService(RunRepository(Path(runs_root))),
        client_factory=lambda: AlfalfaClient(base_url),
        server_version_loader=lambda: _alfalfa_server_version(base_url),
        client_version=metadata.version("alfalfa-client"),
    )
    return executor.execute(job_id).model_dump(mode="json")


def execute_boptest_qualification_job(
    job_id: str, jobs_root: str, runs_root: str
) -> dict[str, Any]:
    base_url = os.getenv("BACTALK_BOPTEST_URL", "http://127.0.0.1:8000")
    executor = BoptestQualificationJobExecutor(
        QualificationJobRepository(Path(jobs_root)),
        WorkbenchService(RunRepository(Path(runs_root))),
        client_factory=lambda: BoptestClient(base_url),
    )
    return executor.execute(job_id).model_dump(mode="json")


def _rq_job_record(job: Any) -> tuple[QualificationJobRepository, str] | None:
    jobs_root = job.meta.get("jobs_root") if isinstance(job.meta, dict) else None
    job_id = job.meta.get("qualification_job_id") if isinstance(job.meta, dict) else None
    if not isinstance(jobs_root, str) or not isinstance(job_id, str):
        return None
    return QualificationJobRepository(Path(jobs_root)), job_id


def rq_qualification_failure_callback(
    job: Any,
    connection: Any,
    exception_type: type[BaseException],
    value: BaseException,
    traceback: Any,
) -> None:
    del connection, traceback
    target = _rq_job_record(job)
    if target is not None:
        repository, job_id = target
        repository.mark_failed(job_id, f"{exception_type.__name__}: {value}")


def rq_qualification_stopped_callback(job: Any, connection: Any, *args: Any) -> None:
    del connection, args
    target = _rq_job_record(job)
    if target is not None:
        repository, job_id = target
        repository.mark_canceled(job_id, "RQ worker stopped the qualification job")
