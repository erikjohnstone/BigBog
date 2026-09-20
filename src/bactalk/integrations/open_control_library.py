from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from bactalk.domain import ControlGraph
from bactalk.integrations.cxf_importer import CxfImporter
from bactalk.integrations.cxf_vectors import CxfVectorVerifier


class OpenControlLibrary:
    """Read and translate the pinned Open Control Library without mutating it."""

    def __init__(self, root: Path | None = None, manifest: Path | None = None):
        self.root = (
            root or Path(os.getenv("BACTALK_OPEN_CONTROL_LIBRARY", ".vendor/open-control-library"))
        ).resolve()
        self.manifest = (
            manifest or Path(os.getenv("BACTALK_CXF_MANIFEST", "ops/cxf-lowering-v1.json"))
        ).resolve()
        self.importer = CxfImporter()
        self.verifier = CxfVectorVerifier()

    def catalog(self) -> dict[str, Any]:
        registry_path = self.root / "faults" / "registry.json"
        if not registry_path.is_file():
            raise FileNotFoundError("Open Control Library fault registry is not installed")
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        manifest = (
            json.loads(self.manifest.read_text(encoding="utf-8"))
            if self.manifest.is_file()
            else {
                "ir_vector_verified_rule_ids": [],
                "niagara_vector_verified_rule_ids": [],
            }
        )
        ir_verified = set(manifest.get("ir_vector_verified_rule_ids", []))
        niagara_verified = set(manifest.get("niagara_vector_verified_rule_ids", []))
        rules = [
            {
                **rule,
                "ir_translation_status": (
                    "vector-verified" if rule.get("id") in ir_verified else "source-only"
                ),
                "niagara_translation_status": (
                    "compiled-vector-verified"
                    if rule.get("id") in niagara_verified
                    else (
                        "ir-only-vector-verified"
                        if rule.get("id") in ir_verified
                        else "source-only"
                    )
                ),
            }
            for rule in registry.get("rules", [])
        ]
        return {
            "schema": registry.get("schema"),
            "count": len(rules),
            "ir_vector_verified_count": len(ir_verified),
            "niagara_vector_verified_count": len(niagara_verified),
            "translation_manifest": manifest.get("schema"),
            "rules": rules,
            "scope": "fault-detection and commissioning logic; not complete equipment sequences",
        }

    def translate(self, rule_id: str) -> tuple[ControlGraph, dict[str, Any]]:
        rows = {row["id"]: row for row in self.catalog()["rules"]}
        rule = rows.get(rule_id)
        if rule is None:
            raise KeyError(rule_id)
        directory = self.root / "faults" / rule["family"] / rule["id"]
        document = self.importer.load(directory / "rule.cxf.jsonld")
        graph = self.importer.import_graph(document)
        vectors = json.loads((directory / "vectors.json").read_text(encoding="utf-8"))
        report = self.verifier.verify(graph, vectors)
        if not report["passed"]:
            raise ValueError(f"{rule_id} does not pass its upstream vectors after BACTalk lowering")
        return graph, report
