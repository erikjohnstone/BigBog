#!/usr/bin/env bash
# Install the pinned Rumoca Modelica flattener.
#
# This is a thin wrapper around the single bootstrap driver so that every
# pinned revision, license digest, and tracked patch is read from
# ops/stack.lock.json instead of being copied into this script. Run
# `make bootstrap-full` to install the whole stack at once.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT_DIR/scripts/bootstrap.py" --only rumoca "$@"
