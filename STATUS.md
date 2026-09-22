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
| N5 Point linking | **done** | `tests/test_native_bog_points.py` in `make test-native-bog`: one AHU + 25 VAVs linked in one station, validator clean | station structure is doc-only until Gate G-WB (docs/decisions/006) |
| N6 Shadow Runtime | **done** | `make test-native-bog` (232 passed: `tests/test_native_bog_shadow_*.py` add the loader, block-semantics, kernel-equivalence and driver tests incl. both Tier 1 suites and the AHU + 25 VAVs fan-out); `make test-minimal` (408 passed, 1 skipped); `make shadow-check` | stock semantics are ASSUMED until Gate G-WB's calibration kit (N7); event-ordering hazard in the VAV time-suppression logic recorded for N7 (docs/niagara-semantics.md) |
| N7 Prove it | **done (D4 target not met; recorded)** | `make test-native-bog` (calibration kit `--check` + 312 native_bog tests: differential, property, mutation, calibration, shadow qualification); `make test-minimal` (469 passed, 1 skipped); committed proofs `artifacts/native-bog/d1..d4-tier1.json`; web: `make web-lint`, `make web-build`, `make web-test`, Playwright `e2e/shadow.spec.ts` | D4 catch rate: neither Tier 1 suite meets ≥ 95 % (VAV reheat 63.5 %, multizone AHU 65.5 % on 200-mutant samples; the AHU's earlier 100 % was a failing-baseline artifact found in N8; survivors listed, N8's first work list, docs/decisions/009); stock semantics stay ASSUMED until a human runs `calibration/` (Gate G-WB) |
| N8 Library Tier 2 | **partial** | `make test-native-bog` (337 passed: `tests/test_native_bog_tier2.py`, `tests/test_native_bog_requests.py`); `make test-minimal` (494 passed, 1 skipped); `docs/coverage.md` + `src/bactalk/library_tier2/coverage.json` from `make coverage-report` | 22 Tier 2 configurations defined; 16 retained with OCE references, 6 blocked with the exact reason in `docs/coverage.md` (single-zone AHU: OCE rejects the flattened CXF; fan coil, zone setpoints, zone-group operation mode: importer lacks `CDL.Reals.Limiter` / `CDL.Conversions.RealToInteger`; cooling-only Title 24: engine input mapping); D3 fails for the two constant-volume fan-powered boxes (Shadow Runtime valve PID transient, recorded below); D4 ≥ 95 % on 6 of 18 graded rows; chiller-plant pin (step 1) not started |
| N9–N11 Library tiers 3–5 | not started | | Test Generation Protocol |

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

## N5 results

- **Station as data.** `bactalk.niagara.station_points` parses a contractor
  station's BACnet network, devices and proxy points (ORD, handle, object,
  data type, units, writability) without executing anything. The `bacnet:*`
  driver types are doc-only catalog entries; the fixture station validates
  with zero warnings.
- **Suggestions, human confirmation.** `bactalk.niagara.pointmap` ranks proxy
  points per job point from expanded name tokens (abbreviation dictionary),
  BACnet object type, units and device grouping; nothing without a shared name
  token is suggested. `POST /api/intake/station-bindings` returns the
  inventory and suggestions; the Normalize step shows them and records only
  confirmed rows (`point_bindings` on `/api/runs/import`). For the fixture VAV
  box, the first suggestion is the right proxy for all ten mappable points.
- **Links in the station.** Station assembly (single and project) adds proper
  `b:Link` elements for confirmed bindings: proxy `out` → program `in16`, or
  program `out` → proxy `in<priority>`; already-driven slots, unresolved ORDs,
  priority 1 and implicit priorities are refused.
- **Exit met.** `tests/fixtures/native-bog/station-ahu-25vav.bog` (one AHU,
  25 VAVs, 270 technician-named points) plus the retained AHU and 25 retained
  VAV programs assemble into one station with 250 point links; the validator
  reports zero errors and zero warnings; no generated Java is involved.
- **Java binder retired from the default path.** `BactalkPointBinder_*.java`
  is emitted only for expert-lane jobs; the JSON binding plan stays.
- **Not claimed.** The station structure comes from documentation and a
  generated fixture, not a real export; Gate G-WB will surface differences.
  Writable `Parameters` and interface descriptions on points remain open.

## N6 results

- **The file is the only input.** `bactalk.niagara.shadow` loads an exported
  `.bog` (module symbols in document order, handles and `slot:` ORDs, every
  property and link) and refuses unknown types. Both Tier 1 exports load with
  every link resolved: VAV reheat 496 components / 650 links, multizone AHU
  606 / 792.
- **Semantics with sources.** `docs/niagara-semantics.md` lists 59 rules
  (`S-*`) as DOCUMENTED, ASSUMED or OWN with their source; a test fails if the
  document and the block tests cite different sets. Status bits, writable
  priority arrays with level 1/8 overrides, expiry and BooleanWritable minimum
  times, event-driven links with loop detection, timed kitControl blocks,
  LoopPoint, schedules and interval histories run on one simulated clock.
- **Uncertainty is a policy.** Every ASSUMED ordering or timing rule is an
  `ExecutionPolicy` knob; `run_under_policies` runs a suite under nine plausible
  policies. VAV reheat: verdicts and final outputs identical under all nine.
  AHU: verdicts identical; one final output (`ySupFan`) varies between 0.2766
  and 0.2791 because module PIDs integrate at the policy's tick rate. That is a
  band for N7, not a defect.
- **Module kernels, two implementations.** Python ports of the 13 Java kernels
  agree with the Java kernels on 4560 random rows through the `KernelHarness`
  session protocol (`make shadow-check`, also in CI); the runtime uses the JVM
  sidecar when a JDK is present and the ports otherwise (docs/decisions/007).
  N6 corrected three kernels in both implementations: `MovingAverage`'s
  64-entry ring truncated windows longer than 64 execution periods;
  `UnitDelay`, `FirstOrderHold` and the sampler in `TrimAndRespond` sampled the
  first value seen at a sample instant instead of the last. `Pre` and
  `NumericChange` wrappers now step only on the execution period.
- **Exit met.** Both Tier 1 exports pass their full acceptance suites in the
  Shadow Runtime with either backend (VAV 12 s, AHU 11 s with Python kernels;
  62 s and 43 s through the JVM), grading the same cases the IR suite grades,
  with the same sample shape (`step`, `phase`, inputs, `fault.*`, `effective.*`,
  every slot, sparse `.status`). An AHU plus 25 VAVs through the full suite
  takes 107 s with Python kernels and 293 s through the JVM on four cores via
  `run_project_suite`; `enqueue_project_suite` puts the same jobs on the RQ
  queue.
- **Finding for N7 (D3 will have to resolve it).** In the VAV's time
  suppression, a `MultiVibrator`-clocked latch and a `UnitDelay` update in
  separate events at one instant; between them `|swi − uniDel|` trips a
  `OneShot` and a set/reset latch stays set. The synchronous IR never sees it.
  The `one_shot`, `boolean_set_reset` and sampler lowerings need a glitch-free
  form (or a host-tick driver in the module) before their matrix rows leave
  "provisional".
- **Not claimed.** Every stock-block rule marked ASSUMED is exactly that until
  a human runs the calibration kit in Workbench (Gate G-WB). LoopPoint's
  execute period, disabled behaviour and integral form are the least certain.

## N7 results

- **D3 three-way differential passes for both Tier 1 controllers.** For every
  acceptance scenario the exported `.bog` in the Shadow Runtime, the IR
  interpreter and the retained Open Control Engine trajectory agree inside the
  bands of `src/bactalk/niagara/bands.json` (docs/decisions/008: two scans in
  time, 2 % of the suite-wide range in value; a coarse set for the
  coarse-module-tick policy). References are retained under
  `src/bactalk/library_demo/references/` by `scripts/retain_reference_traces.py`
  and an integration test fails if a fresh OCE run drifts. Along the way the
  runtime found and N7 fixed: `And` self-latching from null-initialised
  outputs at start (S-STATUS-6), stale latch values from depth-first start,
  a `TrueDelay` restarted by a false→true glitch inside one propagation, a
  `UnitDelay` in a loop sampling the pre-update value (S-MODULE-6), the PID
  integrating twice within one instant, and a divide-by-zero in the AHU
  demo's design outdoor-air parameters. The glitch hazard recorded by N6 is
  closed: `one_shot`, `falling_edge`, `boolean_set_reset`, `sampler`,
  `sample_trigger` and `hysteresis` now lower to tick-semantic `bactalkG36`
  components (matrix: STOCK_EXACT 28, MODULE 21, UNSUPPORTED 6,
  STOCK_WITHIN_BANDS 3).
- **Property-based testing.** `tests/test_native_bog_property.py` generates
  random valid IR graphs over the supported block set with hypothesis, emits,
  validates and runs them in the Shadow Runtime, and compares every observed
  slot with the IR interpreter.
- **D4 mutation testing, reported as measured.** `bactalk.niagara.mutate`
  applies eight operators (VAV reheat: 1596 mutants; AHU: 1854) and
  judges each by validator → loader → acceptance suite → three-way
  differential. On the committed 200-mutant seeded samples
  (`artifacts/native-bog/d4-tier1.json`): VAV reheat 127 of 200 caught (63.5 %),
  multizone AHU 131 of 200 (65.5 %; the 200 of 200 first recorded here was an
  artifact of a failing baseline, corrected in N8), target not met for either.
  Every VAV survivor sits in logic the six scenarios never exercise (time suppression, CO2 demand control, the
  heating-maximum branch, the flow-sensor alarm, override modes) or is
  equivalent under the suite (an input point's fallback the scenarios
  override; facets on a boolean point). That list is N8's first work list
  (docs/decisions/009); nothing was weakened to raise the number.
- **D5 in the web app.** A `shadow` qualification job kind
  (`POST /api/runs/{id}/qualification-jobs/shadow`, the same queue, SSE
  progress and cancel routes as BOPTEST and Alfalfa) runs the exact signed
  `.bog` in the Shadow Runtime and the differential, writes
  `shadow-verification/evidence.json` into the artifact digest and sets the run
  to `ready_for_review` or `failed`, so a failing scenario blocks approval and
  export (append-once). The Test stage gains a "Shadow Runtime (bog-simulated)"
  clock source drawn against the reference with bands, first-divergence detail
  per scenario, the Build stage shows the exported folders' SVG previews
  (`GET /api/runs/{id}/niagara-previews`), the Review stage has a Shadow
  Runtime surface and blockers, and the release summary carries
  `shadow.passed`. Playwright `web/e2e/shadow.spec.ts` walks a mocked job cycle.
- **D6 honest labelling.** `bog-simulated` sits between `target-compiled` and
  `verified` in `readiness.py`, the Home ladder and the README; the LBNL G36
  controller source capability now reports that stage.
- **Calibration kit for Gate G-WB.** `calibration/` (generated by
  `scripts/build_calibration_kit.py`, checked in `make test-native-bog`) holds
  17 small `.bog` files covering all 24 ASSUMED rules of
  `docs/niagara-semantics.md`, each with `steps.json`, the Shadow Runtime's
  expected history per observed point and a README procedure (about two hours in
  Workbench). `scripts/calibrate_shadow_runtime.py` aligns exported histories to
  the expected traces, prints a verdict per rule and writes VERIFIED or
  CONTRADICTED into the semantics document; a CONTRADICTED rule is a failing
  test against the runtime, never a station defect.
- **Open question for a human (protocol rule 6).** In the multizone AHU's
  "unoccupied stops the fan" scenario the LBNL CDL leaves the minimum
  outdoor-air PID integrating with the fan off (`yMinOutDam` climbs 0 → 0.048
  in OCE, the interpreter and the Shadow Runtime alike), although the LBNL
  documentation and G36 §5.16.4 say the loop is disabled with its output at
  zero. The N0 expectation `yMinOutDam == 0` only held while the demo's design
  outdoor-air parameters were zero. It is withdrawn from that scenario (the
  occupied scenario asserts the loop opens the damper) and recorded here for an
  engineer to classify as a library defect or an intended reading before N8
  builds on this controller.
- **Not claimed.** Nothing here is Niagara runtime qualification. The D4 target
  is met for one of two Tier 1 controllers. The calibration kit has not been run.

## N8 results (partial)

- **Every LBNL G36 equipment and zone controller is a configuration.**
  `bactalk.library_tier2.CONFIGURATIONS` lists 22 (single-zone AHU ×2, fan
  coil, nine terminal-unit variants incl. Title 24 and the dual-sensor snap-acting
  box, zone setpoints, control loops, alarms, states, both ventilation standards,
  zone-group status and operation mode), each with the complete parameter set
  LBNL leaves open. `scripts/retain_tier2.py` retains the translation and an
  Open Control Engine reference per configuration (mechanical scenarios: nominal
  point plus one perturbation per input and every operation mode;
  docs/decisions/010); modelica-json output is now cached per controller, which
  turned retention from hours into minutes.
- **Coverage report.** `docs/coverage.md` and `src/bactalk/library_tier2/coverage.json`
  (`make coverage-report`, `GET /api/library/coverage`, the Libraries page) grade
  all 24 rows: D1 and D2 pass on every retained row (18), D3 on 16, D4 at or above
  95 % on 6 (the fan-powered VVF boxes, the dual-sensor snap-acting box and the
  zone control loops); the rest report their measured catch rate. Six rows are
  blocked with the exact reason.
- **Findings.** (1) The Tier 1 AHU's D4 figure in N7 (200 of 200) was an
  artifact: its acceptance suite was failing at the time, so every mutant was
  "caught by the suite". `run_mutation_suite` now refuses a failing baseline and
  the regenerated report reads 45 %. (2) The Shadow Runtime's valve PID lags the
  interpreter and the reference by one scan and then integrates faster on the
  constant-volume fan-powered boxes (`conVal`, first divergence at t = 300 s in
  `DamVal_1`); the interpreter matches OCE exactly, so this is a runtime defect
  to fix before those rows can pass D3. (3) `CDL.Reals.Limiter` and
  `CDL.Conversions.RealToInteger` (round half away from zero; no stock Niagara
  block) are the next importer/module additions; they unblock three rows.
- **Cross-equipment requests.** `ProjectSignalAggregation` (`sum`, `max`, `any`)
  joins the project model; `bactalk.library_tier2.requests` generates zone → AHU
  and AHU → plant request signals from the G36 request table and the project's
  `feeds`/`serves` relationships; the simulator reduces them and the station
  assembler builds kitControl chains in a `Requests` folder
  (`tests/test_native_bog_requests.py`: one AHU with two reheat boxes raises the
  fan on summed pressure requests; nine sources chain three stages).
- **Not done.** Step 1 (pin a Modelica Buildings master commit for `G36/Plants`;
  master `a3cfdde` carries `Plants/Chillers`) and Tier 2b plant templates; the
  three importer gaps; the CVF runtime defect; the single-zone AHU (an OCE ingest
  rejection of LBNL's own CDL).

## Gates

| Gate | Status | File |
|---|---|---|
| G-SDK | WAITING_ON_HUMAN (ready to run after N3) | `gates/G-SDK.md` |
| G-WB | WAITING_ON_HUMAN | `gates/G-WB.md` |
| G-ENG | not yet needed (Tier 3+) | |
