# STATUS: native Niagara `.bog` pipeline (GOAL-NATIVE-BOG.md)

Updated in the same commit as the work it describes. Every "proves it" line is a
command that passes at that commit.

## Baseline (commit 1cf9e4a, before N0)

| Suite | Command | Result |
|---|---|---|
| Base install | `make test-minimal` | 165 passed, 1 skipped, 26 s (Python 3.11) |
| Web unit + coverage gate | `cd web && npm run test:coverage` | 98 passed; lines 92.5% on trace/stores/diff |
| Browser journeys | `cd web && npx playwright test` | 42 passed (desktop + tablet, axe on every page) |
| Bundle budget | `cd web && npm run size` | eager 207 kB gzip of 350; three/xyflow/uplot lazy |

Integration tier (`make test-integration`) needs `make bootstrap-full`; the vendored
stack is present on the development box and the LBNL translation lane runs
(modelica-json + Open Control Engine, ~5–8 s per controller).

## Milestones

| Milestone | Status | Proves it | Blockers / notes |
|---|---|---|---|
| N0 Clear the ground | **done** | `make test-native-bog` (21 passed), `make test-minimal` (257 passed, 1 skipped), `cd web && npx playwright test` (42 passed, 2 flaky-then-passed) | see N0 results |
| N1 Catalog + validator | **done** | `make test-native-bog` (47 passed); integration: `test_native_bog_validator` drift + corpus tests | catalog is package data (docs/decisions/002) |
| N2 Lowering matrix | **done** | `make test-native-bog` (matrix `--check` + 14 lowering tests; 61 native_bog tests total) | rows provisional until N7 (docs/decisions/003) |
| N3 bactalkG36 kernels | **done (CI part)** | `make kernels-check`; `tests/test_native_bog_kernels.py` in `make test-native-bog` | building and signing the real module is Gate G-SDK (WAITING_ON_HUMAN) |
| N4 Native emitter | **done** | `make test-native-bog` (`tests/test_native_bog_emit.py`); both retained Tier 1 controllers export one validated `.bog` | descriptions and writable parameters wait on N5 (docs/decisions/005) |
| N5 Point linking | not started | | |
| N6 Shadow Runtime | not started | | |
| N7 Prove it | not started | | Gate G-WB written |
| N8–N11 Library tiers | not started | | |

## N0 results

- **Demo is LBNL-sourced.** `bactalk demo`, `POST /api/runs/demo` and
  `POST /api/runs/demo/generalist` build `TerminalUnits.Reheat.Controller`
  (VAV_21) and `AHUs.MultiZone.VAV.Controller` (AHU_1) from translations retained
  as package data (`src/bactalk/library_demo/*.json`, schema
  `bactalk.retained-library-translation/v1`, Modelica Buildings v13.0.0 at
  `55abf579…`, controller and CXF digests recorded). Both pass their cited G36
  acceptance cases on a base install and produce the ProgramObject package (the
  honest current artifact; station assembly still refuses program packages until
  N4). `tests/test_lbnl_demo.py` re-translates in the integration tier and fails
  on drift.
- **Units.** `src/bactalk/niagara/units.py` holds the harvested BUnit encodings;
  `NiagaraCompiler.compile(units=…)` writes `units=u:<name>;<symbol>;<dimension>;
  <scale>;` on every numeric point and its history `valueFacets`. Guard test:
  `tests/test_native_bog_units.py::test_no_point_with_declared_units_ships_with_the_null_unit`.
- **Packs relabelled, not deleted.** The hand-written VAV/AHU packs stay behind
  `standard_vav_demo_job` / `standard_ahu_demo_job` (`demo_job` and
  `generalist_demo_job` remain aliases of them because ~30 station, BACnet,
  nhaystack, VOLTTRON and topology tests are written against those points) and
  no longer claim Guideline 36 in the intake family, capability registry or README.
  They are deleted when N4 exits (docs/decisions/001).
- **CXF importer fix.** `CDL.*` relative class names are now qualified to
  `Buildings.Controls.OBC.CDL.*`; this had blocked every terminal-unit controller
  (`unsupported_classes ['CDL.Logical.Not']`).
- **Tier 1 translation state at v13.0.0** (`host_tick_v1`, retained parameters):

  | Controller | Typed IR | Blocks | Niagara target |
  |---|---|---|---|
  | `TerminalUnits.Reheat.Controller` | complete | 485 | `contractor_component_required` |
  | `TerminalUnits.CoolingOnly.Controller` | complete | 337 | `contractor_component_required` |
  | `AHUs.MultiZone.VAV.Controller` | complete | 566 | `contractor_component_required` |

  None has a stock-Niagara lowering: the blockers are `CDL.Discrete.Sampler`,
  `TriggeredSampler`, `UnitDelay`, `Logical.Latch`, `Pre`, `Timer`, `TrueFalseHold`,
  `Reals.PIDWithReset`, `Utilities.Assert`, and every `TrueDelay(delayOnInit=false)`.
  That is the N2 matrix and the N3 kernel list. `modelica_exact` is additionally
  blocked by `CDL.Logical.Pre` on the terminal units; the AHU translates under it.
- **Reheat needs `heaCoi=WaterBased`**: with the electric coil the LBNL model leaves
  `ala.fanHotPlaOn.u1` undriven and Open Control Engine rejects the CXF
  (`single-assignment`). Recorded as a parameter requirement, not a bug here.
- Test tiers: `native_bog` marker, `make test-native-bog`, CI step "Native .bog
  contract" after the minimal tier.

## N1 results

- **Catalog.** `src/bactalk/niagara/catalog/harvested.json`: 179 `module:Name`
  types from 51 archives (26 MIT n4-hvac-optimization-blocks, 4 AFL nhaystack
  stations, 21 MIT pybog examples generated at harvest time), with slots, value
  types, link-target and link-source counts, facet keys, symbol table and
  per-source digests. `supplement.json` holds 30 doc-only entries, each citing
  its Tridium guide. Regenerate with `make niagara-catalog`; the integration
  tier fails on drift.
- **Validator.** `bactalk.niagara.validate.validate_bog` checks 16 rules
  (archive, XML root, module declaration and consistency, type known, handle
  form and uniqueness, link fields, source resolution, source and target slot
  existence, double-driven inputs, kind match, facet grammar, unit names) and
  warns on links out of input slots, external ords and uncatalogued properties.
  It runs in `create_run` on every compiled `.bog` (report written to
  `niagara-validation.json`, errors abort the run) and on every assembled
  station (types from the contractor template exempt).
- **Corpus result.** 54 of 54 archives pass: both compiled pack demos, all 30
  vendored archives, all 21 pybog examples, the contractor demo station. Two
  real gaps were found and closed on the way: `program:Program`'s frozen
  `execute` action and handle-less structs (HistoryConfig) not being harvested.
- **Fixtures.** `tests/fixtures/native-bog/bad/<rule>.bog`, one per rule,
  generated by `scripts/make_native_bog_fixtures.py` from the compiled VAV demo.
- **Deferred to N3.** `validate_bog(declared_types=...)` is the hook for the
  `bactalkG36` module's types; the catalog holds none yet.

## N2 results

- **Matrix.** `src/bactalk/niagara/lowering.py` classifies all 58 kinds:
  28 `STOCK_EXACT`, 9 `STOCK_WITHIN_BANDS` (each with its deviation and
  bounding scenarios), 15 `MODULE`, 6 `UNSUPPORTED` (the `plant_*` composites,
  N8). `boolean_delay` is configuration-dependent (`delay_on_init` false →
  `bactalkG36:TrueDelay`). `docs/niagara-lowering-matrix.md` is rendered from
  code and checked by `make test-native-bog` and CI.
- **Tier 1 exit met.** Retained VAV reheat: 444 stock-exact, 16 within-bands,
  25 module, 0 unsupported. Retained multizone AHU: 509 / 30 / 27 / 0. Module
  components needed: `PIDWithReset`, `Pre`, `Timer`, `TrueDelay`,
  `TrueFalseHold`, `UnitDelay`, plus `FirstOrderHold` and `MovingAverage` for
  the AHU. That is the N3 build list.
- **Policy.** `LoweringPolicy(expert_program_objects=False)` by default;
  `plan_lowering` yields the lane and blockers; every run writes
  `niagara-lowering.json`. The artifact choice still follows the compiler's
  stock table until N4 replaces it (recorded, not yet enforced).
- **Not claimed.** No row is runtime-qualified; `pi_loop`→`LoopPoint` and the
  `Tstat`, `OneShot` and MultiVibrator composites are the rows most likely to
  move to `MODULE` once N7 measures them.

## N3 results

- **Module skeleton.** `niagara-module/bactalkG36/` in the nhaystack Gradle
  layout: `settings.gradle.kts`, `build.gradle.kts` (default signing profile
  refused), `gradle.properties`, `niagara-module.xml`, `bactalkG36-rt`
  (kernels, 13 components, `module-include.xml`, lexicon) and `bactalkG36-wb`
  (palette as a `bajaObjectGraph`). `README.md` says what CI proves and what it
  cannot.
- **Kernels.** 13 plain-Java kernels ported from the ProgramObject generator's
  kernel members, parameterised at construction: `PidWithReset`, `TrueDelay`,
  `Timer`, `TimerWithReset`, `TimerAccumulating`, `TrueFalseHold`, `Pre`,
  `UnitDelay`, `FirstOrderHold`, `MovingAverage`, `TrimAndRespond` (hold variant
  by `holdEnabled`), `BooleanInitialization`, `NumericChange`. `KernelHarness`
  drives any of them from a line protocol.
- **Pinned twice.** OCE golden rows (PID, Trim-and-Respond, Timer, UnitDelay,
  FirstOrderHold) and a differential against the IR interpreter for 16
  kind/configuration cases × 3 seeds on irregular steps, 1e-9 tolerance.
- **Wrappers compile against stubs.** `niagara-module/stubs` is the minimal
  `javax.baja` surface; `BKernelComponent` owns the ticket, the time base and
  the null-status policy. `python -m bactalk.niagara.kernels --check` and CI
  (`actions/setup-java`, Temurin 21) compile both.
- **Registry.** `bactalk.niagara.module` declares each component's slots and
  parameter bindings; `validate_bog(declared_types=declared_types())` accepts
  `bactalkG36:*` (the palette validates; without the declaration it fails on
  `type.known`). Tests fail on drift between the registry, the Java slots and
  `module-include.xml`.
- **Not claimed.** Nothing here has been loaded by a Niagara station. Gate
  G-SDK lists the exact build, signing, palette and execution evidence.

## N4 results

- **Emitter.** `bactalk.niagara.emit` writes the `bajaObjectGraph` directly
  (pybog kept for the pack lane): root folder, `Inputs`, one folder per
  first-level CDL composite (`ActAirSet`, `DamVal`, `SysReq`, …; chunked to at
  most 60 components), `Outputs`; stock blocks, matrix composites (falling
  edge, set/reset with feedback, sampler, sample trigger, assert note, Tstat
  hysteresis) and `bactalkG36` components with their parameter properties;
  units on every numeric point; sequential handles; deterministic layered
  layout (`bactalk.niagara.layout`); byte-identical output for identical input.
- **Origins.** The CXF importer now records `metadata.block_origins`
  (composite instance path per block); both retained translations were
  regenerated with `scripts/retain_library_translations.py`.
- **Result.** VAV reheat: 496 components, 650 links, 13 logic folders; multizone
  AHU: 606 components, 792 links, 15 logic folders. Both pass the N1 validator
  with the module types declared, with zero warnings, and fail on `type.known`
  without the declaration (the module is real, not assumed).
- **Previews.** `bactalk.niagara.preview` renders one deterministic SVG per
  folder; the service writes `niagara-emit.json` and `previews/*.svg` beside
  the archive.
- **Lane wiring.** `NiagaraCompiler.compile` takes the native lane for any
  graph the stock table cannot carry; the service chooses the artifact from
  the matrix (`native_*` → `.bog`, `blocked` → refused with blockers,
  `program_objects` → package only with `sequence.expert_program_objects`).
  The LBNL demo, the plant `HoldReal` job and the G36 `SupplySignals` job now
  produce a `.bog`; station assembly is no longer refused for them. The
  air-to-water plant contract keeps the expert flag until N8.
- **Not done here.** Interface descriptions on points and writable
  `Parameters` (the CDL parameters are folded into composite-level constants
  by the importer) are N5 work; multi-equipment output (AHU + N VAVs in one
  `.bog`) is deferred to N5 with point linking.

## Gates

| Gate | Status | File |
|---|---|---|
| G-SDK | WAITING_ON_HUMAN (ready to run after N3) | `gates/G-SDK.md` |
| G-WB | WAITING_ON_HUMAN | `gates/G-WB.md` |
| G-ENG | not yet needed (Tier 3+) | |
