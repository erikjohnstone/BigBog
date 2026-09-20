#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="$ROOT_DIR/.vendor/bacnet-simulator"
VENV_DIR="$ROOT_DIR/.bacnet-simulator-venv"
REVISION="d06fccb963abd4c773f6b5dd74e12f9ec79a5edd"
LICENSE_SHA256="56c7ffa9ff22bd72c4bf682e962af6742fb0d89101c9a3b358b24a6c33871622"

if [[ ! -d "$SOURCE_DIR/.git" ]]; then
  git clone --filter=blob:none https://github.com/quentinnippert/bacnet-simulator.git "$SOURCE_DIR"
fi
git -C "$SOURCE_DIR" fetch --depth 1 origin "$REVISION"
git -C "$SOURCE_DIR" checkout --detach "$REVISION"

ACTUAL_LICENSE_SHA256="$(shasum -a 256 "$SOURCE_DIR/LICENSE" | awk '{print $1}')"
if [[ "$ACTUAL_LICENSE_SHA256" != "$LICENSE_SHA256" ]]; then
  echo "bacnet-simulator license digest mismatch" >&2
  exit 1
fi

python3.11 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install -e "$SOURCE_DIR[dev]"
