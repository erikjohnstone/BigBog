#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from buildingmotif import BuildingMOTIF
from buildingmotif.dataclasses import Library
from rdflib import URIRef

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / ".vendor/buildingmotif/libraries"
LIBRARIES = {
    "g36": VENDOR / "ashrae/guideline36",
    "chiller-plant": VENDOR / "chiller-plant",
    "ashrae-223p": VENDOR / "ashrae/223p/nrel-templates",
}


def _load_library(library_id: str) -> Library:
    directory = LIBRARIES.get(library_id)
    if directory is None:
        raise ValueError(f"unknown BuildingMOTIF library: {library_id}")
    Library.load(ontology_graph=str(VENDOR / "brick/Brick-subset.ttl"))
    return Library.load(directory=str(directory))


def execute(payload: dict[str, Any]) -> dict[str, Any]:
    BuildingMOTIF("sqlite://")
    library_id = str(payload.get("library", "g36"))
    library = _load_library(library_id)
    templates = library.get_templates()
    operation = payload.get("operation", "catalog")
    if operation == "catalog":
        names = sorted(str(template.name) for template in templates)
        return {"library": library_id, "template_count": len(names), "templates": names}
    if operation != "instantiate":
        raise ValueError(f"unknown BuildingMOTIF operation: {operation}")

    template_name = str(payload["template"])
    template = library.get_template_by_name(template_name).inline_dependencies()
    namespace = str(payload.get("namespace", "urn:bactalk#"))
    overrides = payload.get("bindings", {})
    if not isinstance(overrides, dict):
        raise ValueError("bindings must be an object")
    parameters = sorted(str(parameter) for parameter in template.parameters)
    bindings = {
        parameter: URIRef(
            str(overrides.get(parameter, namespace + parameter.replace("-", "_")))
        )
        for parameter in parameters
    }
    graph = template.evaluate(bindings)
    return {
        "library": library_id,
        "template": template_name,
        "parameters": parameters,
        "triple_count": len(graph),
        "turtle": graph.serialize(format="turtle"),
    }


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("request must be an object")
        print(json.dumps({"ok": True, "result": execute(payload)}, sort_keys=True))
        return 0
    except Exception as exc:  # noqa: BLE001 - isolated worker error boundary
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
