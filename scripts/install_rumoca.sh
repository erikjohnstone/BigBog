#!/usr/bin/env bash
set -euo pipefail

BACTALK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACTALK_VENDOR="$BACTALK_ROOT/.vendor"
RUMOCA_REV="7ddbadf77eb5699580c32cef680c3e1ea3a36fdc"
MSL_REV="8ae3d35c24e519cb2996cab20f3b13daf2b0c50a"
BUILDINGS_REV="55abf579598ca81cae0a82f337350375958e6722"
RUMOCA_DIR="$BACTALK_VENDOR/rumoca"
RUMOCA_BIN="$BACTALK_VENDOR/bin/rumoca"
MSL_DIR="$BACTALK_VENDOR/modelica-standard-library"
BUILDINGS_DIR="$BACTALK_VENDOR/modelica-buildings-rumoca"
COMPAT_PATCH="$BACTALK_ROOT/ops/rumoca/modelica-buildings-compat.patch"

mkdir -p "$BACTALK_VENDOR"

if [[ ! -d "$RUMOCA_DIR/.git" ]]; then
  git clone --filter=blob:none https://github.com/CogniPilot/rumoca "$RUMOCA_DIR"
  git -C "$RUMOCA_DIR" checkout --detach "$RUMOCA_REV"
fi
[[ "$(git -C "$RUMOCA_DIR" rev-parse HEAD)" == "$RUMOCA_REV" ]] || {
  echo "Rumoca checkout is not at pinned revision $RUMOCA_REV" >&2
  exit 1
}

if [[ ! -d "$MSL_DIR/.git" ]]; then
  git clone --filter=blob:none https://github.com/modelica/ModelicaStandardLibrary "$MSL_DIR"
  git -C "$MSL_DIR" checkout --detach "$MSL_REV"
fi
[[ "$(git -C "$MSL_DIR" rev-parse HEAD)" == "$MSL_REV" ]] || {
  echo "Modelica Standard Library is not at pinned revision $MSL_REV" >&2
  exit 1
}

if [[ ! -e "$BUILDINGS_DIR/.git" ]]; then
  git clone --filter=blob:none --no-checkout \
    https://github.com/lbl-srg/modelica-buildings "$BUILDINGS_DIR"
  git -C "$BUILDINGS_DIR" sparse-checkout set \
    Buildings/Controls/OBC Buildings/Utilities
  git -C "$BUILDINGS_DIR" checkout --detach "$BUILDINGS_REV"
fi
[[ "$(git -C "$BUILDINGS_DIR" rev-parse HEAD)" == "$BUILDINGS_REV" ]] || {
  echo "Rumoca Buildings checkout is not at pinned revision $BUILDINGS_REV" >&2
  exit 1
}

if git -C "$BUILDINGS_DIR" apply --reverse --check "$COMPAT_PATCH"; then
  : # compatibility patch is already present
elif git -C "$BUILDINGS_DIR" apply --check "$COMPAT_PATCH"; then
  git -C "$BUILDINGS_DIR" apply "$COMPAT_PATCH"
else
  echo "Rumoca Buildings compatibility patch does not apply cleanly" >&2
  exit 1
fi

cargo build --release -p rumoca --bin rumoca --manifest-path "$RUMOCA_DIR/Cargo.toml"
install -d "$(dirname "$RUMOCA_BIN")"
install -m 0755 "$RUMOCA_DIR/target/release/rumoca" "$RUMOCA_BIN"
"$RUMOCA_BIN" --version
if [[ "${BACTALK_KEEP_RUMOCA_BUILD_CACHE:-0}" != "1" ]]; then
  cargo clean --release --manifest-path "$RUMOCA_DIR/Cargo.toml"
fi
