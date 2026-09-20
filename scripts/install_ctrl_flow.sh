#!/usr/bin/env bash
set -euo pipefail

BACTALK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="$BACTALK_ROOT/.vendor/ctrl-flow-dev"
DEPENDENCY_ROOT="$BACTALK_ROOT/.vendor/ctrl-flow-dependencies"
MODELICA_JSON_DIR="$DEPENDENCY_ROOT/modelica-json"
REVISION="9063e347b13b1a55f9b324ab35da01b5006492de"
MODELICA_JSON_REVISION="b715c09d3092192779e8eccd80c813f08ea1a8e6"
LICENSE_SHA256="1d1367874c6d5f974749edc9fdbd8988a5ab3d73c6900bc03737f8547d95c29f"
MODELICA_JSON_LICENSE_SHA256="bb349c1e17f72d51f0ed42fa1101812078fbac47be4fcfc09f5313f7f2befa70"

if [[ ! -d "$SOURCE_DIR/.git" ]]; then
  git clone --filter=blob:none --no-checkout \
    https://github.com/lbl-srg/ctrl-flow-dev "$SOURCE_DIR"
fi

git -C "$SOURCE_DIR" fetch --depth 1 origin "$REVISION"
git -C "$SOURCE_DIR" sparse-checkout set --no-cone \
  /LICENSE.txt /LEGAL.txt /ReadMe.md /client/ /server/ /specification/ /docs/
git -C "$SOURCE_DIR" checkout --detach "$REVISION"

[[ "$(git -C "$SOURCE_DIR" rev-parse HEAD)" == "$REVISION" ]] || {
  echo "ctrl-flow checkout is not at pinned revision $REVISION" >&2
  exit 1
}

ACTUAL_LICENSE_SHA256="$(shasum -a 256 "$SOURCE_DIR/LICENSE.txt" | awk '{print $1}')"
[[ "$ACTUAL_LICENSE_SHA256" == "$LICENSE_SHA256" ]] || {
  echo "ctrl-flow license digest mismatch" >&2
  exit 1
}

npm --prefix "$SOURCE_DIR/client" ci --ignore-scripts
npm --prefix "$SOURCE_DIR/server" ci --ignore-scripts

mkdir -p "$DEPENDENCY_ROOT"
if [[ ! -d "$MODELICA_JSON_DIR/.git" ]]; then
  git clone --filter=blob:none https://github.com/lbl-srg/modelica-json.git \
    "$MODELICA_JSON_DIR"
fi
git -C "$MODELICA_JSON_DIR" fetch --depth 1 origin "$MODELICA_JSON_REVISION"
git -C "$MODELICA_JSON_DIR" checkout --detach "$MODELICA_JSON_REVISION"

ACTUAL_MODELICA_JSON_LICENSE_SHA256="$(
  shasum -a 256 "$MODELICA_JSON_DIR/LICENSE.md" | awk '{print $1}'
)"
[[ "$ACTUAL_MODELICA_JSON_LICENSE_SHA256" == "$MODELICA_JSON_LICENSE_SHA256" ]] || {
  echo "ctrl-flow modelica-json license digest mismatch" >&2
  exit 1
}

npm --prefix "$MODELICA_JSON_DIR" install --ignore-scripts --no-audit --no-fund
if [[ ! -f "$MODELICA_JSON_DIR/java/moParser.jar" ]]; then
  make -C "$MODELICA_JSON_DIR" install-maven
  make -C "$MODELICA_JSON_DIR" compile
fi
