#!/usr/bin/env python3
"""Prove every pinned revision still resolves upstream, without cloning.

A pin is only reproducible while the commit it names is still reachable. A
force-push, a deleted branch, or a repository that disappeared all turn a
"pinned" component into one that cannot be rebuilt from a clean clone -- and
nothing notices until someone tries to bootstrap.

This asks each upstream for the exact object using ``git ls-remote`` and a
blobless partial fetch probe, which downloads no trees. It is cheap enough to
run in CI on every change to the lock.

Exit status is non-zero when any pinned revision cannot be resolved.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bactalk.stack_lock import LockedComponent, StackLock  # noqa: E402


def _resolves(repository: str, revision: str, timeout: int) -> tuple[bool, str]:
    """Return whether ``revision`` exists in ``repository``.

    ``git ls-remote <repo> <rev>`` matches only refs, and a pinned commit is
    usually not a ref tip, so a miss there is inconclusive. The authoritative
    check creates an empty repo and asks the remote for that one object with a
    blobless filter, which transfers no file contents.
    """
    named = subprocess.run(
        ["git", "ls-remote", repository, revision],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if named.returncode == 0 and named.stdout.strip():
        return True, "resolved as a ref tip"

    import tempfile

    with tempfile.TemporaryDirectory() as workdir:
        init = subprocess.run(
            ["git", "init", "--quiet", workdir], capture_output=True, text=True, timeout=60
        )
        if init.returncode != 0:
            return False, "could not create a probe repository"
        fetch = subprocess.run(
            [
                "git",
                "-C",
                workdir,
                "fetch",
                "--depth",
                "1",
                "--filter=blob:none",
                "--quiet",
                repository,
                revision,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if fetch.returncode == 0:
            return True, "resolved by exact-object fetch"
        detail = (fetch.stderr or fetch.stdout or "").strip().splitlines()
        return False, detail[-1][:200] if detail else "fetch failed"


def _check(component: LockedComponent, timeout: int) -> dict:
    repository = component.repository
    revision = component.revision
    if not repository or not revision:
        return {
            "component": component.name,
            "status": "skipped",
            "detail": "pinned by package version, not a git revision",
        }
    started = time.monotonic()
    try:
        ok, detail = _resolves(repository, revision, timeout)
    except subprocess.TimeoutExpired:
        ok, detail = False, f"timed out after {timeout}s"
    return {
        "component": component.name,
        "status": "ok" if ok else "unresolved",
        "repository": repository,
        "revision": revision,
        "detail": detail,
        "seconds": round(time.monotonic() - started, 2),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--output", help="write a JSON report here")
    args = parser.parse_args(argv)

    lock = StackLock()
    components = lock.components()
    print(f"resolving {len(components)} pinned components against their upstreams")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda item: _check(item, args.timeout), components))

    unresolved = [item for item in results if item["status"] == "unresolved"]
    for item in sorted(results, key=lambda entry: entry["component"]):
        icon = {"ok": "OK  ", "skipped": "SKIP", "unresolved": "FAIL"}[item["status"]]
        revision = item.get("revision", "")
        print(f"  [{icon}] {item['component']:<30} {revision[:12]:<14} {item['detail']}")

    payload = {
        "schema": "bactalk.lock-resolution/v1",
        "stack_lock_sha256": lock.sha256(),
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ok": not unresolved,
        "results": results,
    }
    if args.output:
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(payload, indent=2) + "\n")

    print("")
    if unresolved:
        print(f"{len(unresolved)} pinned revision(s) no longer resolve upstream:")
        for item in unresolved:
            print(f"  - {item['component']}: {item['detail']}")
        print("")
        print(
            "A pin that cannot be fetched is not reproducible. Re-pin the "
            "component in ops/stack.lock.json against a revision the upstream "
            "still serves, and re-verify the adopted scope."
        )
        return 1
    resolved = sum(1 for item in results if item["status"] == "ok")
    skipped = sum(1 for item in results if item["status"] == "skipped")
    print(f"all pins reproducible: {resolved} git revisions resolved, {skipped} package pins")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
