"""Single source of truth for pinned upstream revisions.

``ops/stack.lock.json`` records every selected open-source component with its
repository, exact revision, license, and the scope BACTalk adopted. Installers,
adapters, the readiness ledger and ``make doctor`` all read the lock through
this module so a revision exists in exactly one place: duplicating a SHA in a
shell script or an adapter is how a checkout and the code that trusts it drift
apart.

The loader is deliberately strict. A component that is missing, or a field that
a caller requires and the lock does not carry, raises rather than defaulting,
because a silently-missing pin would let an unpinned checkout look verified.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


class StackLockError(RuntimeError):
    """Raised when the lock file is missing, malformed, or lacks a pin."""


def stack_lock_path() -> Path:
    """Path to the lock file, overridable with ``BACTALK_STACK_LOCK``."""
    override = os.getenv("BACTALK_STACK_LOCK")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "ops" / "stack.lock.json"


@dataclass(frozen=True)
class LockedComponent:
    """One pinned upstream component."""

    name: str
    data: dict[str, Any]

    @property
    def repository(self) -> str | None:
        return self.data.get("repository")

    @property
    def revision(self) -> str | None:
        return self.data.get("revision")

    @property
    def release(self) -> str | None:
        return self.data.get("release")

    @property
    def package(self) -> str | None:
        return self.data.get("package")

    @property
    def license(self) -> str | None:
        return self.data.get("license")

    @property
    def scope(self) -> str | None:
        return self.data.get("scope")

    @property
    def branch(self) -> str | None:
        return self.data.get("branch")

    def require(self, field: str) -> str:
        """Return a required field or raise naming the component and field."""
        value = self.data.get(field)
        if not isinstance(value, str) or not value:
            raise StackLockError(
                f"ops/stack.lock.json component '{self.name}' is missing "
                f"required field '{field}'"
            )
        return value

    def require_revision(self) -> str:
        return self.require("revision")

    def require_repository(self) -> str:
        return self.require("repository")

    @property
    def short_revision(self) -> str | None:
        revision = self.revision
        return revision[:12] if revision else None

    def version_label(self) -> str:
        """Human-readable version: the release when pinned, else a short SHA."""
        return self.release or self.package or self.short_revision or "unpinned"


@lru_cache(maxsize=4)
def _load(path_text: str) -> dict[str, Any]:
    path = Path(path_text)
    if not path.is_file():
        raise StackLockError(f"stack lock file is not present at {path}")
    try:
        document = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise StackLockError(f"stack lock file at {path} is not valid JSON: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("components"), dict):
        raise StackLockError(f"stack lock file at {path} has no 'components' object")
    return document


class StackLock:
    """Read-only view over the pinned component set."""

    def __init__(self, path: Path | None = None):
        self.path = path or stack_lock_path()
        self._document = _load(str(self.path))

    @property
    def verified_at(self) -> str | None:
        value = self._document.get("verified_at")
        return value if isinstance(value, str) else None

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._document["components"].keys())

    def get(self, name: str) -> LockedComponent:
        """Return one component or raise naming the missing pin."""
        components = self._document["components"]
        if name not in components:
            raise StackLockError(
                f"ops/stack.lock.json has no component named '{name}'; "
                f"known components: {', '.join(sorted(components))}"
            )
        entry = components[name]
        if not isinstance(entry, dict):
            raise StackLockError(f"stack lock component '{name}' is not an object")
        return LockedComponent(name=name, data=entry)

    def revision(self, name: str) -> str:
        """Exact pinned revision for a component."""
        return self.get(name).require_revision()

    def repository(self, name: str) -> str:
        return self.get(name).require_repository()

    def field(self, name: str, field: str) -> str:
        return self.get(name).require(field)

    def components(self) -> list[LockedComponent]:
        return [self.get(name) for name in self.names]

    def sha256(self) -> str:
        """Digest of the lock file itself, for evidence bundles."""
        import hashlib

        return hashlib.sha256(self.path.read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def stack_lock() -> StackLock:
    """Shared lock instance."""
    return StackLock()


def locked_revision(name: str) -> str:
    """Convenience accessor used by adapters that pin one upstream revision."""
    return stack_lock().revision(name)
