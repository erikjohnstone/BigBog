"""Retained requirement approvals (Gate G-ENG), one file per approved digest."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from bactalk.protocol.requirements import (
    ApprovalStatus,
    RequirementApproval,
    RequirementSet,
    approval_status,
)

_SAFE = re.compile(r"^[a-z0-9][a-z0-9-]{1,80}$")


class RequirementApprovalRepository:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _directory(self, sequence_id: str) -> Path:
        if not _SAFE.fullmatch(sequence_id):
            raise ValueError("invalid sequence id")
        return self.root / sequence_id

    def save(self, approval: RequirementApproval) -> Path:
        directory = self._directory(approval.sequence_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{approval.requirements_digest}.json"
        if path.exists():
            raise FileExistsError(
                f"{approval.sequence_id} at {approval.requirements_digest[:12]} is already approved"
            )
        staging = path.with_suffix(".json.tmp")
        staging.write_text(
            approval.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(staging, path)
        return path

    def get(self, sequence_id: str, requirements_digest: str) -> RequirementApproval | None:
        if not re.fullmatch(r"[0-9a-f]{64}", requirements_digest):
            raise ValueError("invalid requirements digest")
        path = self._directory(sequence_id) / f"{requirements_digest}.json"
        if not path.is_file():
            return None
        approval = RequirementApproval.model_validate(json.loads(path.read_text(encoding="utf-8")))
        if (
            approval.sequence_id != sequence_id
            or approval.requirements_digest != requirements_digest
        ):
            raise ValueError("approval record does not match its path")
        return approval

    def for_sequence(self, sequence_id: str) -> list[RequirementApproval]:
        directory = self._directory(sequence_id)
        if not directory.is_dir():
            return []
        approvals = [
            RequirementApproval.model_validate(json.loads(path.read_text(encoding="utf-8")))
            for path in sorted(directory.glob("*.json"))
        ]
        return sorted(approvals, key=lambda item: item.approved_at)

    def status(self, requirements: RequirementSet) -> ApprovalStatus:
        exact = self.get(requirements.sequence_id, requirements.digest())
        if exact is not None:
            return approval_status(requirements, exact)
        earlier = self.for_sequence(requirements.sequence_id)
        return approval_status(requirements, earlier[-1]) if earlier else "unapproved"

    def is_approved(self, sequence_id: str, requirements_digest: str) -> bool:
        return self.get(sequence_id, requirements_digest) is not None


__all__ = ["RequirementApprovalRepository"]
