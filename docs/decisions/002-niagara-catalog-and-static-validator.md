# 002: The Niagara catalog is package data, and every `.bog` is validated before it ships

Status: accepted (N1). Supersedes nothing.

## Context

GOAL-NATIVE-BOG.md N1 asks for a catalog of Niagara component types and slots
built from real `.bog` files, and a static validator that runs on every `.bog`
BACTalk produces. The goal names `data/niagara-catalog/` as the catalog's home.

The validator has to run inside `WorkbenchService.create_run` on a base install
(`make install`, no vendored corpus), so the catalog must travel with the wheel.

## Decision

- **Location.** The catalog lives at `src/bactalk/niagara/catalog/` as package
  data, not at `data/niagara-catalog/`: `harvested.json` is generated,
  `supplement.json` is hand-written. `make niagara-catalog` regenerates the
  harvest and the known-bad fixtures; the integration tier fails when the
  committed harvest drifts from a fresh one.
- **Provenance is per type and per slot.** A harvested type lists every source
  file it was seen in; every source carries its licence and digest (the archive
  for vendored files, the inner `file.xml` for archives pybog generates at
  harvest time, because zip timestamps are not stable). A slot's `origins` say
  whether it was harvested, taken from pybog's tables, or is `doc-only`.
- **Doc-only entries are the exception, cited, and never generated.** Real
  archives omit properties left at their defaults and serialise writable priority
  inputs as bare `<p n="in16" f="tsL"/>` with no value type. The supplement fills
  exactly those gaps (writable `in1..in16`, comparison and math inputs, Program's
  `execute` action, HistoryConfig `capacity`) and each entry names the Tridium
  guide it comes from. The harvester never writes to the supplement.
- **Types are keyed by module, not symbol.** A file may spell the control module
  `c:` or `control:`; the catalog stores `control:NumericWritable` and the
  validator resolves each file's `m=` declarations in document order (a symbol
  declared on one element stays in scope for the rest of the file, which is how
  Niagara writes them).
- **Errors fail the run; warnings do not.** Structure, module, type, handle, link
  and facet rules are errors and `create_run` raises before the run is recorded.
  A link out of an input slot, an external `slot:` source ord, or a property the
  catalog does not know are warnings, written to `niagara-validation.json` beside
  the archive.
- **Assembled stations are validated without the type rule.** The contractor's
  template brings station and driver types the catalog does not hold, so
  `assembled-station.bog` is checked for structure, handles, links and facets
  with `require_known_types=False`.
- **Dynamic-slot types are checked against the instance.** A `program:Program`
  or a folder declares its slots per instance; a link into one must name a slot
  the element actually declares (or a frozen slot from the supplement).

## Consequences

- 54 archives pass today: the two compiled pack demos, all 30 vendored MIT and
  AFL archives, the 21 pybog examples and the contractor demo station.
- Every rule has a known-bad fixture under `tests/fixtures/native-bog/bad/`,
  generated from the compiled VAV demo with one defect each.
- A `bactalkG36` module (N3) declares its types to the validator through
  `validate_bog(declared_types=...)`; nothing else changes.
- The catalog is evidence of what real files contain, not a claim about what
  Niagara accepts. Gate G-WB still decides that.
