"""Harvest the Niagara type and slot catalog from real ``.bog`` files.

GOAL-NATIVE-BOG.md N1. Every component type that appears in a license-compatible
``.bog`` we hold is recorded with its module, its property and slot names with
their value types, which slots are link targets or link sources in practice, the
facet formats seen, and provenance (source file and digest). pybog's own slot
tables are folded in with ``pybog`` provenance. Nothing here is invented: a slot
that is only documented by Tridium lives in ``supplement.json`` marked
``doc-only`` and is written by hand, never by this script.

Sources:

- ``.vendor/n4-hvac-optimization-blocks/bog_files/**/*.bog`` (MIT): the 20
  ProgramObject archives plus the wiresheet examples around them.
- ``.vendor/nhaystack/**/*.bog`` (AFL): four test stations.
- ``.vendor/pybog/examples/*.py`` (MIT): 21 examples, run here to produce their
  ``.bog`` output.

Usage::

    PYTHONPATH=src .venv/bin/python scripts/harvest_niagara_catalog.py [--check]

``--check`` exits non-zero when the committed catalog differs from a fresh
harvest (the integration tier runs it).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / ".vendor"
OUTPUT = ROOT / "src" / "bactalk" / "niagara" / "catalog" / "harvested.json"

SCHEMA = "bactalk.niagara-catalog/v1"

CORPORA = (
    ("n4-hvac-optimization-blocks", VENDOR / "n4-hvac-optimization-blocks", "MIT"),
    ("nhaystack", VENDOR / "nhaystack", "AFL-3.0"),
)
PYBOG = VENDOR / "pybog"

# Link-like children carry sourceOrd/sourceSlotName/targetSlotName rather than
# being slots of their parent.
LINK_TYPES = {"baja:Link", "baja:ConversionLink"}

# Types whose slot set is defined per instance (a Program's declared slots, a
# folder's children). Their slots are not catalogued; the validator skips slot
# existence checks on them.
DYNAMIC_SLOT_TYPES = {
    "baja:Component",
    "baja:Folder",
    "baja:UnrestrictedFolder",
    "baja:Station",
    "baja:ServiceContainer",
    "program:Program",
    "nhaystack:HDict",
    "driver:DriverContainer",
    "app:AppContainer",
}

# pybog spells types with the customary symbols; the catalog keys by module name.
PYBOG_SYMBOLS = {"sch": "schedule", "conv": "converters", "b": "baja", "c": "control"}

# Value types whose slots carry a signal, by the data kind the validator matches
# across links.
DATA_KINDS = {
    "baja:StatusNumeric": "numeric",
    "baja:StatusBoolean": "boolean",
    "baja:StatusEnum": "enum",
    "baja:StatusString": "string",
    "baja:Double": "numeric",
    "baja:Float": "numeric",
    "baja:Integer": "numeric",
    "baja:Long": "numeric",
    "baja:Boolean": "boolean",
    "baja:String": "string",
    "baja:RelTime": "reltime",
    "baja:FrozenEnum": "enum",
}
PYBOG_KINDS = {
    "StatusNumeric": "baja:StatusNumeric",
    "StatusBoolean": "baja:StatusBoolean",
    "StatusEnum": "baja:StatusEnum",
    "Number": "baja:Double",
    "Boolean": "baja:Boolean",
    "RelTime": "baja:RelTime",
    "FrozenEnum": "baja:FrozenEnum",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_xml(path: Path) -> ElementTree.Element | None:
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("file.xml")
    except (zipfile.BadZipFile, KeyError):
        return None
    try:
        return ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return None


def _module_declarations(value: str | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for token in (value or "").split():
        symbol, _, module = token.partition("=")
        if symbol and module:
            result[symbol] = module
    return result


class Harvest:
    def __init__(self) -> None:
        self.sources: dict[str, dict] = {}
        self.types: dict[str, dict] = {}
        self.modules: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.facet_keys: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.link_ords: dict[str, int] = defaultdict(int)
        self.unresolved_symbols: dict[str, int] = defaultdict(int)

    def type_entry(self, type_spec: str) -> dict:
        entry = self.types.get(type_spec)
        if entry is None:
            module, _, name = type_spec.partition(":")
            entry = {
                "type": type_spec,
                "module": module,
                "name": name,
                "component_count": 0,
                "value_count": 0,
                "slots": {},
                "sources": [],
            }
            self.types[type_spec] = entry
        return entry

    def slot_entry(self, type_spec: str, slot: str) -> dict:
        slots = self.type_entry(type_spec)["slots"]
        entry = slots.get(slot)
        if entry is None:
            entry = {
                "value_types": {},
                "flags": {},
                "seen": 0,
                "link_target": 0,
                "link_source": 0,
                "origins": [],
            }
            slots[slot] = entry
        return entry

    def add_source(
        self,
        source_id: str,
        path: Path,
        license_id: str,
        corpus: str,
        *,
        digest_xml: bool = False,
    ) -> None:
        # A generated archive carries zip timestamps; its file.xml is what is
        # stable, so that is what gets digested for generated sources.
        if digest_xml:
            with zipfile.ZipFile(path) as archive:
                digest = hashlib.sha256(archive.read("file.xml")).hexdigest()
        else:
            digest = _sha256(path)
        self.sources[source_id] = {
            "path": source_id,
            "corpus": corpus,
            "license": license_id,
            "sha256": digest,
            "sha256_of": "file.xml" if digest_xml else "archive",
        }

    def harvest_file(self, source_id: str, root: ElementTree.Element) -> None:
        """Record every typed element of one object graph.

        Type keys are ``module:Name`` after resolving the file's ``m=`` symbol
        declarations, so ``c:NumericWritable`` and ``control:NumericWritable``
        land on the same entry. A symbol the file never declares keeps its raw
        spelling and is counted under ``unresolved_symbols``.
        """

        root_component = next((child for child in root if child.tag == "p"), None)
        resolved: dict[int, str] = {}
        by_handle: dict[str, str] = {}
        # Module symbols are declared on the first element that needs them, in
        # document order, and stay in scope for the rest of the file.
        modules: dict[str, str] = {}
        for element in root.iter("p"):
            modules.update(_module_declarations(element.get("m")))
            type_spec = element.get("t")
            if type_spec is None:
                continue
            symbol, _, name = type_spec.partition(":")
            module = modules.get(symbol)
            if module is None:
                self.unresolved_symbols[symbol] += 1
                key = type_spec
            else:
                self.modules[symbol][module] += 1
                key = f"{module}:{name}"
            resolved[id(element)] = key
            handle = element.get("h")
            if handle is not None:
                by_handle[handle.lower()] = key
        touched: set[str] = set()
        for element in root.iter("p"):
            key = resolved.get(id(element))
            if key is None:
                continue
            entry = self.type_entry(key)
            touched.add(key)
            # Components carry a handle; structs (a HistoryConfig, a StatusNumeric)
            # carry none but still own named properties worth cataloguing.
            has_properties = any(
                child.tag == "p" and child.get("n") is not None for child in element
            )
            is_component = (
                element.get("h") is not None or element is root_component or has_properties
            )
            if not is_component:
                entry["value_count"] += 1
                continue
            entry["component_count"] += 1
            for child in element:
                if child.tag != "p":
                    continue
                slot = child.get("n")
                if slot is None:
                    continue
                child_key = resolved.get(id(child))
                if child_key in LINK_TYPES:
                    self._harvest_link(key, child, by_handle)
                    continue
                if key in DYNAMIC_SLOT_TYPES:
                    continue
                slot_entry = self.slot_entry(key, slot)
                slot_entry["seen"] += 1
                if child_key is not None:
                    slot_entry["value_types"][child_key] = (
                        slot_entry["value_types"].get(child_key, 0) + 1
                    )
                flags = child.get("f")
                if flags:
                    slot_entry["flags"][flags] = slot_entry["flags"].get(flags, 0) + 1
                if slot == "facets" and child.get("v"):
                    for part in child.get("v", "").split("|"):
                        facet_key, _, rest = part.partition("=")
                        encoding = rest.split(":", 1)[0] if rest else ""
                        self.facet_keys[facet_key][encoding] += 1
        for key in touched:
            sources = self.types[key]["sources"]
            if source_id not in sources:
                sources.append(source_id)

    def _harvest_link(
        self,
        target_type: str,
        link: ElementTree.Element,
        by_handle: dict[str, str],
    ) -> None:
        values = {child.get("n"): child.get("v") for child in link if child.tag == "p"}
        source_ord = values.get("sourceOrd") or ""
        target_slot = values.get("targetSlotName")
        source_slot = values.get("sourceSlotName")
        scheme = source_ord.split(":", 1)[0] if ":" in source_ord else "(none)"
        self.link_ords[scheme] += 1
        if target_slot and target_type not in DYNAMIC_SLOT_TYPES:
            self.slot_entry(target_type, target_slot)["link_target"] += 1
        if source_slot and scheme == "h":
            source_type = by_handle.get(source_ord[2:].lower())
            if source_type is not None and source_type not in DYNAMIC_SLOT_TYPES:
                self.slot_entry(source_type, source_slot)["link_source"] += 1

    def fold_pybog(self, version: str) -> None:
        from bog_builder import models

        origin = f"pybog {version} models"

        def qualify(type_spec: str) -> str:
            symbol, _, name = type_spec.partition(":")
            return f"{PYBOG_SYMBOLS.get(symbol, symbol)}:{name}"

        for type_spec, slots in models.COMPONENT_SLOT_MAP.items():
            if type_spec == "kitControl:Subract":  # a typo in pybog's table
                continue
            for direction in ("inputs", "outputs"):
                for slot in slots.get(direction, []):
                    entry = self.slot_entry(qualify(type_spec), slot)
                    if origin not in entry["origins"]:
                        entry["origins"].append(origin)
                    entry.setdefault("pybog_direction", direction[:-1])
        for (type_spec, slot), kind in models.SLOT_TYPE_MAPPING.items():
            if type_spec == "kitControl:Subract":
                continue
            entry = self.slot_entry(qualify(type_spec), slot)
            entry.setdefault("pybog_value_type", PYBOG_KINDS[kind])
            if origin not in entry["origins"]:
                entry["origins"].append(origin)
        for type_spec, kind in models.COMPONENT_OUTPUT_TYPE.items():
            entry = self.slot_entry(qualify(type_spec), "out")
            entry.setdefault("pybog_value_type", PYBOG_KINDS[kind])
            entry.setdefault("pybog_direction", "output")
            if origin not in entry["origins"]:
                entry["origins"].append(origin)

    def finish(self) -> dict:
        types = {}
        for type_spec in sorted(self.types):
            entry = self.types[type_spec]
            slots = {}
            for slot in sorted(entry["slots"]):
                item = entry["slots"][slot]
                counts = item["value_types"]
                value_types = sorted(counts, key=lambda k: (-counts[k], k))
                observed = value_types[0] if value_types else None
                value_type = observed or item.get("pybog_value_type")
                origins = []
                if item["seen"] or item["link_target"] or item["link_source"]:
                    origins.append("harvested")
                origins.extend(item["origins"])
                data_kind = DATA_KINDS.get(value_type or "")
                slots[slot] = {
                    "value_type": value_type,
                    "value_types_seen": dict(sorted(item["value_types"].items())),
                    "data_kind": data_kind,
                    "seen": item["seen"],
                    "link_target": item["link_target"],
                    "link_source": item["link_source"],
                    "flags_seen": dict(sorted(item["flags"].items())),
                    "origins": origins,
                }
                if "pybog_direction" in item:
                    slots[slot]["pybog_direction"] = item["pybog_direction"]
            types[type_spec] = {
                "type": type_spec,
                "module": entry["module"],
                "name": entry["name"],
                "component_count": entry["component_count"],
                "value_count": entry["value_count"],
                "origin": "harvested" if entry["sources"] else "pybog",
                "dynamic_slots": type_spec in DYNAMIC_SLOT_TYPES,
                "slots": slots,
                "sources": sorted(entry["sources"]),
            }
        return {
            "schema": SCHEMA,
            "generator": "scripts/harvest_niagara_catalog.py",
            "sources": {key: self.sources[key] for key in sorted(self.sources)},
            "modules": {
                symbol: dict(sorted(modules.items()))
                for symbol, modules in sorted(self.modules.items())
            },
            "facet_keys": {
                key: dict(sorted(encodings.items()))
                for key, encodings in sorted(self.facet_keys.items())
            },
            "link_ord_schemes": dict(sorted(self.link_ords.items())),
            "unresolved_symbols": dict(sorted(self.unresolved_symbols.items())),
            "types": types,
        }


def _pybog_version() -> str:
    from importlib.metadata import version

    return version("pybog")


def _pybog_examples(destination: Path) -> list[Path]:
    examples = sorted((PYBOG / "examples").glob("*.py"))
    for script in examples:
        subprocess.run(
            [sys.executable, str(script), "-o", str(destination)],
            cwd=PYBOG,
            check=True,
            capture_output=True,
        )
    return sorted(destination.glob("*.bog"))


def harvest() -> dict:
    result = Harvest()
    missing = [str(path) for _, path, _ in CORPORA if not path.is_dir()]
    if not PYBOG.is_dir():
        missing.append(str(PYBOG))
    if missing:
        raise SystemExit("vendored corpus missing (run make bootstrap-full): " + ", ".join(missing))
    for corpus, directory, license_id in CORPORA:
        for path in sorted(directory.rglob("*.bog")):
            root = _read_xml(path)
            if root is None:
                continue
            source_id = f"{corpus}/{path.relative_to(directory).as_posix()}"
            result.add_source(source_id, path, license_id, corpus)
            result.harvest_file(source_id, root)
    with tempfile.TemporaryDirectory() as tmp:
        for path in _pybog_examples(Path(tmp)):
            root = _read_xml(path)
            if root is None:
                continue
            source_id = f"pybog-examples/{path.name}"
            result.add_source(source_id, path, "MIT", "pybog", digest_xml=True)
            result.harvest_file(source_id, root)
    result.fold_pybog(_pybog_version())
    return result.finish()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--check", action="store_true", help="fail if the committed catalog is stale"
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    catalog = harvest()
    rendered = json.dumps(catalog, indent=1, sort_keys=False) + "\n"
    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.exists() else ""
        if current != rendered:
            raise SystemExit(f"{args.output} is stale; re-run scripts/harvest_niagara_catalog.py")
        print(f"{args.output} is current: {len(catalog['types'])} types")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(
        f"wrote {args.output}: {len(catalog['types'])} types from "
        f"{len(catalog['sources'])} sources"
    )


if __name__ == "__main__":
    main()
