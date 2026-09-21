from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from bactalk.compiler import NiagaraCompiler
from bactalk.integrations.cxf_importer import CxfImporter
from bactalk.integrations.cxf_vectors import CxfVectorVerifier
from bactalk.stack_lock import locked_revision, stack_lock

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / ".vendor/open-control-library"
ENGINE = ROOT / ".vendor/open-control"
EXPECTED_REVISION = locked_revision("open-control-library")
EXPECTED_ENGINE_REVISION = stack_lock().field("open-control-library", "engine_revision")


def _revision(path: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main() -> int:
    if _revision(LIBRARY) != EXPECTED_REVISION:
        raise RuntimeError("Open Control Library checkout does not match the pinned revision")
    if _revision(ENGINE) != EXPECTED_ENGINE_REVISION:
        raise RuntimeError("Open Control Library engine checkout does not match ENGINE_PIN")
    if (LIBRARY / "ENGINE_PIN").read_text(encoding="utf-8").strip() != EXPECTED_ENGINE_REVISION:
        raise RuntimeError("Open Control Library ENGINE_PIN changed")
    if not (LIBRARY / "LICENSE-MIT").is_file() or not (LIBRARY / "LICENSE-APACHE").is_file():
        raise RuntimeError("dual commercial-use license files are missing")

    registry = json.loads((LIBRARY / "faults/registry.json").read_text(encoding="utf-8"))
    rules = registry.get("rules", [])
    if registry.get("schema") != "cxf-library/registry/v1" or len(rules) != 137:
        raise RuntimeError(f"expected the pinned 137-rule registry, found {len(rules)}")
    families = Counter(rule["family"] for rule in rules)
    if set(families) != {
        "ahu",
        "chw",
        "erv",
        "fcu",
        "fpb",
        "hp",
        "hw",
        "hx",
        "pmp",
        "rtu",
        "sys",
        "tower",
        "vav",
        "vfd",
    }:
        raise RuntimeError(f"unexpected equipment-family coverage: {sorted(families)}")

    for rule in rules:
        fault = LIBRARY / "faults" / rule["family"] / rule["id"]
        required = ("card.md", "diagram.svg", "rule.cxf.jsonld", "vectors.json")
        missing = [name for name in required if not (fault / name).is_file()]
        if missing:
            raise RuntimeError(f"{rule['id']} is missing artifacts: {', '.join(missing)}")

    environment = os.environ.copy()
    environment["RUSTUP_TOOLCHAIN"] = "1.97.1"
    environment["CARGO_TARGET_DIR"] = str(ENGINE / "target")
    completed = subprocess.run(
        [
            "cargo",
            "run",
            "--locked",
            "--quiet",
            "--manifest-path",
            "tools/verify/Cargo.toml",
            "--",
            "--all",
        ],
        cwd=LIBRARY,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=900,
    )
    output = "\n".join((completed.stdout, completed.stderr)).strip()
    if completed.returncode != 0 or "all scenarios passed" not in output:
        raise RuntimeError(f"Open Control Library vector replay failed:\n{output[-8000:]}")

    # Prove both qualification tiers. Every rule must cross CXF -> typed IR ->
    # upstream vectors. The Niagara tier must additionally use only target-lowered
    # primitives and produce a non-empty .bog.
    importer = CxfImporter()
    verifier = CxfVectorVerifier()
    compiler = NiagaraCompiler()
    manifest = json.loads((ROOT / "ops/cxf-lowering-v1.json").read_text(encoding="utf-8"))
    ir_verified_ids = manifest.get("ir_vector_verified_rule_ids", [])
    niagara_verified_ids = manifest.get("niagara_vector_verified_rule_ids", [])
    registry_ids = {rule["id"] for rule in rules}
    if len(ir_verified_ids) != 137 or set(ir_verified_ids) != registry_ids:
        raise RuntimeError("CXF manifest IR tier must contain every unique registry rule")
    if len(niagara_verified_ids) != 113 or len(set(niagara_verified_ids)) != 113:
        raise RuntimeError("CXF manifest Niagara tier must contain 113 unique qualified rules")
    if not set(niagara_verified_ids).issubset(set(ir_verified_ids)):
        raise RuntimeError("CXF manifest Niagara tier must be a subset of the IR tier")
    rows = {rule["id"]: rule for rule in rules}
    ir_verified_families: Counter[str] = Counter()
    verified_families: Counter[str] = Counter()
    with tempfile.TemporaryDirectory(prefix="bactalk-ocl-") as temporary:
        for rule_id in ir_verified_ids:
            rule = rows.get(rule_id)
            if rule is None:
                raise RuntimeError(f"qualified rule is absent from registry: {rule_id}")
            directory = LIBRARY / "faults" / rule["family"] / rule_id
            document = importer.load(directory / "rule.cxf.jsonld")
            coverage = importer.inspect(document)
            graph = importer.import_graph(document)
            vector_report = verifier.verify(
                graph,
                json.loads((directory / "vectors.json").read_text(encoding="utf-8")),
            )
            if not vector_report["passed"]:
                raise RuntimeError(f"translated {rule_id} failed its upstream vectors")
            ir_verified_families[rule["family"]] += 1
            if rule_id in niagara_verified_ids:
                if not coverage["niagara_translatable"]:
                    raise RuntimeError(
                        f"manifest claims Niagara qualification for unsupported {rule_id}"
                    )
                artifact = compiler.compile(graph, Path(temporary) / f"{rule_id}.bog")
                if not artifact.is_file() or artifact.stat().st_size == 0:
                    raise RuntimeError(f"translated {rule_id} did not produce a Niagara artifact")
                verified_families[rule["family"]] += 1
            elif coverage["niagara_translatable"]:
                raise RuntimeError(f"Niagara-qualified rule is missing from manifest: {rule_id}")
    if set(ir_verified_families) != set(families):
        raise RuntimeError("IR vector-qualified rules do not cover all equipment families")
    if set(verified_families) != set(families):
        raise RuntimeError("qualified CXF-to-Niagara rules do not cover all equipment families")

    print(
        json.dumps(
            {
                "passed": True,
                "revision": EXPECTED_REVISION,
                "engine_revision": EXPECTED_ENGINE_REVISION,
                "rules": len(rules),
                "equipment_families": dict(sorted(families.items())),
                "ir_vector_verified_rules": len(ir_verified_ids),
                "ir_vector_verified_families": dict(sorted(ir_verified_families.items())),
                "niagara_vector_verified_rules": len(niagara_verified_ids),
                "niagara_vector_verified_families": dict(sorted(verified_families.items())),
                "checks": [
                    "dual-commercial-license-files",
                    "complete-artifact-sets",
                    "all-cxf-vector-scenarios",
                    "137-cxf-to-bactalk-ir-translations",
                    "137-upstream-vector-suites",
                    "113-niagara-bog-compiles",
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
