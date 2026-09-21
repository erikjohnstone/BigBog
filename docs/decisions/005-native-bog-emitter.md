# 005: The native `.bog` is emitted directly as XML, foldered by CDL composite

Status: accepted (N4).

## Context

pybog 0.1.6 builds flat folders of a fixed set of stock types; it has no API for
custom types (`bactalkG36:*`), nested folders, or handle-addressed links between
folders, and today's compiler already reaches into its private `_links`. The
LBNL controllers need all three.

## Decision

- **Direct XML behind a typed emitter.** `bactalk.niagara.emit` writes the
  `bajaObjectGraph` itself: root `UnrestrictedFolder` with every module symbol
  declared once, one `Folder` per graph, sub-folders, components with
  sequential hexadecimal handles, `wsAnnotation` positions and `b:Link`
  children on the target. Archives are deterministic (fixed zip timestamp), so
  identical input gives byte-identical output. pybog stays for the pack lane
  until pack retirement.
- **Folders by origin.** The CXF importer now records each block's composite
  instance path (`metadata.block_origins`, e.g. `actAirSet.max2`). The emitter
  makes `Inputs`, `Parameters` (root-level constants, emitted as writable points
  so a contractor can adjust them in Workbench), one folder per first-level
  composite (`ActAirSet`, `SetPoiVAV`, …), root-level logic under the graph's
  own name, and `Outputs`. A folder over 60 blocks is split into numbered
  chunks in topological order. A graph without origins (a pack, an old retained
  translation) gets `Logic` chunks.
- **Cross-folder links are ordinary links.** Niagara links address their source
  by station handle, so a link between folders needs nothing special; the
  validator checks that every handle resolves.
- **Composite rows are expanded in the emitter**, exactly as the matrix says:
  falling edge (Not → OneShot), set/reset (OneShot, Or, And, Not with a feedback
  link), sampler (MultiVibrator → NumericLatch), sample trigger (MultiVibrator →
  OneShot), assert (a wiresheet note; `ok` readers are rewired to the
  condition's source). Hysteresis becomes `kitControl:Tstat` with
  `sp = (u_low + u_high)/2` and `diff = u_high − u_low`.
- **Module rows become `bactalkG36` components** with parameter properties
  filled from `bactalk.niagara.module` bindings (seconds → `RelTime`
  milliseconds).
- **Layout is layered longest-path** per folder with barycentre ordering
  (`bactalk.niagara.layout`); cells are 14 wide by 8 high, so nothing overlaps.
- **Previews** are SVGs rendered from the emit report, one per folder,
  deterministic and snapshot-testable.
- **Lane selection.** `NiagaraCompiler.compile` takes the native lane whenever
  a graph carries a block the stock table cannot lower, and the service chooses
  the artifact from `plan_lowering`: `native_*` → `.bog`, `blocked` → refused
  with the blockers, `program_objects` → the expert ProgramObject package. The
  expert lane is opted into per job (`SequenceSpec.expert_program_objects`);
  the plant library (Tier 2, N8) sets it until its kinds have native rows.

## Consequences

- Both retained Tier 1 controllers export one `.bog` that passes the N1
  validator with the `bactalkG36` types declared; the demo run now produces a
  `.bog` and station assembly is no longer refused for LBNL jobs.
- Descriptions for `Inputs`/`Outputs` points come from the retained interface
  and are written as a per-folder note; Niagara has no description slot on a
  writable point.
- The ProgramObject package remains reachable only through the expert flag,
  and the run records which lane it took.
