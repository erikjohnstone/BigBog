"""``ops/stack.lock.json`` is the only place a pinned revision may live.

These tests pin two contracts. First, the loader is strict: a missing
component or a missing required field raises instead of defaulting, because a
silently-absent pin would let an unpinned checkout look verified. Second, no
first-party source file may carry its own copy of an upstream revision -- that
duplication is how a checkout and the code that trusts it drift apart.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from bactalk.stack_lock import StackLock, StackLockError, locked_revision, stack_lock

pytestmark = pytest.mark.minimal

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "ops" / "stack.lock.json"

# A 40-character lowercase hex string is a git revision.
SHA_PATTERN = re.compile(r"\b[0-9a-f]{40}\b")

# Directories whose contents are first-party and must stay free of copied pins.
FIRST_PARTY = ("src", "scripts", "tests")


def test_lock_file_is_well_formed() -> None:
    document = json.loads(LOCK_PATH.read_text())
    assert isinstance(document["components"], dict)
    assert document["components"], "the lock must pin at least one component"
    assert isinstance(document.get("verified_at"), str)


def test_loader_exposes_every_component() -> None:
    lock = StackLock()
    document = json.loads(LOCK_PATH.read_text())
    assert set(lock.names) == set(document["components"])
    assert lock.verified_at == document["verified_at"]
    assert len(lock.sha256()) == 64


def test_unknown_component_names_the_known_ones() -> None:
    lock = StackLock()
    with pytest.raises(StackLockError) as excinfo:
        lock.get("not-a-real-component")
    message = str(excinfo.value)
    assert "not-a-real-component" in message
    assert "known components" in message


def test_missing_required_field_fails_closed() -> None:
    """A component without the field a caller needs raises, never defaults."""
    lock = StackLock()
    # openpyxl is pinned as a package, so it carries no git revision.
    with pytest.raises(StackLockError) as excinfo:
        lock.get("openpyxl").require_revision()
    assert "openpyxl" in str(excinfo.value)
    assert "revision" in str(excinfo.value)


def test_every_component_declares_a_license() -> None:
    """License screening is part of the pin, so it may never be absent."""
    missing = [
        component.name for component in StackLock().components() if not component.license
    ]
    assert missing == [], f"components with no declared license: {missing}"


def test_every_component_is_pinned_exactly() -> None:
    """Every component is pinned by revision, by package version, or both.

    Components BACTalk clones carry a full git revision. Components installed
    from a package index instead carry an exact ``name==version`` pin and may
    list a repository only for provenance. Either way there is no floating
    reference.
    """
    unpinned: list[str] = []
    for component in StackLock().components():
        revision = component.revision
        package = component.package
        if revision:
            if not SHA_PATTERN.fullmatch(revision):
                unpinned.append(f"{component.name} (revision is not a full sha)")
            continue
        if package:
            if "==" not in package:
                unpinned.append(f"{component.name} (package is not pinned with ==)")
            continue
        unpinned.append(f"{component.name} (neither revision nor package)")
    assert unpinned == [], f"components without an exact pin: {unpinned}"


def test_convenience_accessors_agree_with_the_document() -> None:
    document = json.loads(LOCK_PATH.read_text())
    for name, entry in document["components"].items():
        if "revision" in entry:
            assert locked_revision(name) == entry["revision"]
    assert stack_lock().verified_at == document["verified_at"]


def _first_party_sources() -> list[Path]:
    files: list[Path] = []
    for directory in FIRST_PARTY:
        for pattern in ("*.py", "*.sh"):
            files.extend((ROOT / directory).rglob(pattern))
    return [path for path in files if "__pycache__" not in path.parts]


def test_no_first_party_source_duplicates_a_pinned_revision() -> None:
    """Revisions live in the lock file alone.

    A copied SHA in an installer or an adapter is exactly what lets a checkout
    and the code that trusts it disagree, so this fails the build rather than
    waiting for the drift to cause a confusing runtime error.
    """
    locked = {
        component.revision
        for component in StackLock().components()
        if component.revision
    }
    # Revisions referenced by other pinned components (parser dependencies,
    # engine revisions) count as locked values too.
    document = json.loads(LOCK_PATH.read_text())
    for entry in document["components"].values():
        for key, value in entry.items():
            if key.endswith("revision") and isinstance(value, str):
                locked.add(value)

    offenders: list[str] = []
    for path in _first_party_sources():
        if path.name == "test_stack_lock.py":
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            for match in SHA_PATTERN.findall(line):
                if match in locked:
                    offenders.append(f"{path.relative_to(ROOT)}:{lineno}")
    assert offenders == [], (
        "pinned revisions are duplicated outside ops/stack.lock.json at: "
        f"{offenders}. Read them with bactalk.stack_lock.locked_revision() instead."
    )
