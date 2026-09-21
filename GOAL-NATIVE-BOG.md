# Goal: Any Verified Control Logic → One Native Niagara `.bog`, Proven in a Niagara Shadow Runtime

> Repo root, `GOAL-NATIVE-BOG.md`. This is a focused goal for an executing agent. It
> takes precedence over broader goal documents for the work it covers. BACTalk is a
> web app: everything below runs server-side and surfaces in the React UI at `web/`.
> Every claim in "Where the code stands" was verified against the tree at the commit
> that added this file. Re-verify before trusting a number; the code moves.

## Where the code stands (verified)

BACTalk compiles a typed control graph (the IR in `src/bactalk/domain.py`, 58 block
kinds in `BlockKind`) into one of two Niagara artifacts. The choice is made in
`src/bactalk/service.py` (`create_run`, around line 159):

- **`niagara_bog`**: emitted only when every block kind in the graph is in
  `NiagaraCompiler.SLOT_NAMES` (`src/bactalk/compiler.py`). The compiler drives
  pybog 0.1.6 (`bog_builder.BogFolderBuilder`) and reaches into its private `_links`
  list to add typed links. Custom Niagara types come only from a contractor
  environment pack (`_custom_registry`), never from BACTalk itself.
- **`niagara_program_source_package`**: emitted when any block kind is outside
  `SLOT_NAMES` and the job came from a library. `NiagaraProgramPackageBuilder`
  (`src/bactalk/integrations/niagara_program_codegen.py`, ~4,400 lines) generates
  Java ProgramObject source per block, `slots.json`, `wiring-plan.json` and a README
  that tells the contractor to assemble it by hand in Workbench. Twenty-five block
  kinds take this path, including `pid_with_reset`, `trim_and_respond`,
  `hysteresis`, `boolean_true_false_hold`, `timer*`, `moving_average`,
  `numeric_sampler`, the latches and edge detectors, and the six `plant_*` kinds.
  Station assembly is refused for this artifact kind.

What that means in practice:

- **The five hand-written packs** in `src/bactalk/sequences/` (`g36_vav.py`,
  `ahu_safety.py`, `ahu_static_pressure.py`, `exhaust_fan.py`, `pump_selector.py`)
  use only stock kinds, so they export a real `.bog`. They are not Guideline 36. The
  VAV pack's own docstring says it is "a small, auditable subset … not represented as
  full Guideline 36 compliance": a proportional error times a gain, clamped, with no
  airflow loop, no dual-maximum heating and no AHU requests. The AHU safety pack's
  high-static condition is a bare `greater_than_or_equal` with no latch, so the trip
  clears itself the moment pressure drops.
- **The LBNL G36 lane** (`src/bactalk/integrations/g36_library.py`, family
  `LBNL_G36_CONTROLLER`; modelica-json → CXF → Open Control Engine → expanded IR)
  always contains non-stock kinds, so it always exports the ProgramObject kit. The
  test fixture records 55 generated programs for the multizone VAV AHU. The plant
  lane (`plant_controls_library.py`, 38 product-wired controllers) is the same.
- **Units are dropped.** `NiagaraCompiler` never passes point or parameter units to
  pybog, and `src/bactalk/niagara_extensions.py` hard-codes `units=u:null` into
  history facets. `PointSpec.units` exists and is populated by intake; it just never
  reaches the file. No test guards this.
- **Points are linked, but through generated Java.** `niagara_bindings.py` emits
  `BactalkPointBinder_<equipment>.java` plus `niagara-point-bindings.json`, and
  `niagara_station.py` (`assemble_station_bog`, `_rebase_program_handles`,
  `_collect_handles`) inserts the program into a contractor station with handle
  validation and de-duplication. The station tool is worth keeping; the Java binder
  is what this goal retires.
- **Nothing has executed in Niagara.** The strongest current claim is "the IR
  interpreter matched the LBNL reference within pyfunnel bands" (`make oce-contract`,
  `make cdl-oce-contract`, `make g36-audit`). The file that ships is never run.
- **Evidence tiers** live in `src/bactalk/integrations/readiness.py` (`STAGES`:
  discovered, installed, executable, product-wired, target-compiled, verified,
  field-qualified, production-supported). There is no tier for "the exported file was
  executed in a model of Niagara".
- **Pinned inputs** are in `ops/stack.lock.json`: Modelica Buildings at exactly
  `v13.0.0` (revision `55abf579…`), which has `G36/{AHUs,FanCoilUnits,Generic,
  TerminalUnits/{CoolingOnly,Reheat,ParallelFanCVF,ParallelFanVVF,SeriesFanCVF,
  SeriesFanVVF,DualDuctSnapActing,DualDuctMixConInletSensor,
  DualDuctMixConDischargeSensor,DualDuctColdDuctMin},ThermalZones,VentilationZones,
  ZoneGroups}` and **no `G36/Plants`**; modelica-json; Open Control Engine with 46
  G36 golden traces under `.vendor/open-control-engine/tools/golden-gen/goldens/G36`;
  pybog source; nhaystack (a complete open-source Niagara 4 module with a Gradle
  `-rt`/`-wb` split); ConStrain; pyfunnel. `hypothesis` is already a test dependency.
  The 20 MIT ProgramObject archives are served by `niagara_program_library.py`.
- **The web UI already carries most of the review surface this goal needs.** The Test
  stage (`web/src/features/test/TestStage.tsx`) runs every evidence trace on one clock
  with a source switcher (`run`, `boptest`, `alfalfa`), trend panes that draw a
  reference trajectory with tolerance bands, counterexample windows and the peak
  error (`web/src/features/trends/TrendPane.tsx`, `OracleBand` in
  `web/src/stores/trace.ts`), and the Simulation Center streams job progress over
  SSE (`web/src/features/simulation/`). Review binds approval to the artifact digest
  (`web/src/features/review/`). A Shadow Runtime report is one more evidence source on
  these screens, not a new screen. Folder wiresheet previews are the only new surface.
- **What does not exist:** `STATUS.md`, `gates/`, `docs/decisions/`,
  `docs/niagara-semantics.md`, `data/niagara-catalog/`, a `.bog` validator, a
  `bactalkG36` module, a Shadow Runtime, `make test-native-bog`, and any unit test on
  facets.

## The goal

Build a **general pipeline** that turns any verified BACTalk control program into
**one importable, readable, native Niagara `.bog`**. Prove it first on G36 VAV
equipment, then expand coverage to everything G36 defines, then to common non-G36
equipment and job-specific custom sequences. Nothing in the pipeline may be specific
to one equipment type; equipment knowledge lives only in the library.

Each exported `.bog` is:

- built from stock Niagara blocks plus one small BACTalk module (`bactalkG36`) for
  the few primitives Niagara lacks;
- carrying correct units on every point, parameter and history;
- linked to the job's points without generated Java.

Then build a **Niagara Shadow Runtime**: a simulator that loads the exported `.bog`
file itself and executes it the way Niagara would, so the file, not just the logic
behind it, is shown to behave like its source of truth across every test scenario.

## Done means

All of the following pass in CI (`make test-native-bog` inside the
`test-integration` tier), and each has a committed report under `artifacts/native-bog/`:

1. **D1 Native by default.** For every supported configuration, the default export
   is a single `.bog` using only catalogued stock Niagara types and declared
   `bactalkG36` types. No ProgramObjects on the default path. The `.bog` is
   deterministic: the same job spec produces byte-identical output.
2. **D2 Statically valid.** Every exported `.bog` passes the validator: every type,
   slot, link, facet, unit and handle checks out against the Niagara type/slot
   catalog, and every rule has a known-bad fixture that fails it.
3. **D3 Three-way agreement.** The Shadow Runtime executes every exported `.bog`.
   For every acceptance scenario, three runs agree within documented pyfunnel bands:
   the `.bog` in the Shadow Runtime; the BACTalk IR interpreter; and the item's source
   of truth (the LBNL/OCE reference for Tiers 1–2, the requirement-traced generated
   suite for Tiers 3–5). A disagreement names the first diverging block and slot.
4. **D4 Mutations are caught.** Deliberately broken `.bog` files (swapped link slots,
   wrong block types, missing links, wrong constants, reversed loop action, dropped
   facets, wrong priority level) are caught by the validator or the Shadow Runtime at
   least 95% of the time. Survivors are listed for review.
5. **D5 Visible in the web app.** For any job: folder wiresheet previews, Shadow
   Runtime trajectories against the reference on the shared clock, pass/fail per
   scenario, first-divergence detail, and the report inside the approval digest.
   Export is blocked while any scenario fails.
6. **D6 Honestly labelled.** The evidence tier is `bog-simulated`, placed below
   `runtime-qualified` in `readiness.py` and shown that way in the UI and README. A
   calibration kit lets a human with a licensed Workbench confirm every Shadow
   Runtime assumption in one session.

## Scope

Coverage grows in tiers. The pipeline (N0–N7) is built once and is equipment-neutral.
Every later tier is library work that reuses it unchanged.

| Tier | Equipment | Source of truth | Milestone |
|---|---|---|---|
| 1. Pipeline proof | VAV reheat, VAV cooling-only, multizone VAV AHU, and one AHU plus N VAVs with request links | LBNL G36 CDL at the pinned v13.0.0 | N0–N7 |
| 2. All LBNL G36 | The eight remaining terminal types present at v13.0.0 (parallel fan CVF/VVF, series fan CVF/VVF, dual-duct snap-acting, dual-duct mixing with inlet sensor, dual-duct mixing with discharge sensor, dual-duct cold-duct minimum), single-zone VAV AHU, fan coil units, zone groups, ventilation zones (62.1 and Title 24), and the G36 chilled water plant | LBNL G36 CDL. The chiller plant is **not in v13.0.0**; pin a specific `master` commit for it and label it `pre-release` until LBNL ships it in a release | N8 |
| 2b. LBNL plant templates | The 38 controllers already product-wired in `plant_controls_library.py` | LBNL `Templates.Plants.Controls` | N8 |
| 3. G36 without an LBNL reference | Hot water/boiler plant; 2024-edition humidity and outdoor-air-pollution modules where LBNL has no CDL | The G36 text. Tests generated under the Test Generation Protocol; an engineer approves the requirements (Gate G-ENG) | N9 |
| 4. Common non-G36 equipment | RTUs, DOAS/ERVs, water- and air-source heat pumps, unit and cabinet heaters, exhaust and supply fans, standalone pumps, cooling towers without a full plant, domestic hot water, basic schedule control | A BACTalk sequence document per type; generated tests; Gate G-ENG | N10 |
| 5. Custom sequences | Anything job-specific | The job spec plus the contractor's prompts; generated tests; the contractor approves the requirements | N11 |

Out of scope: non-Niagara targets, live BACnet writes, hosting and tenancy.

**The rule that keeps "all buildings" honest.** The pipeline proves a `.bog` matches
its logic. It cannot prove the logic is right. Each library item's correctness comes
from its source of truth, and the UI must always show which one applies.

## Rules for the executing agent

1. **Go milestone by milestone.** Create `STATUS.md` in N0 and update it in the same
   commit as the work: milestone, status, the exact command that proves it, blockers.
2. **Tests are the contract.** `make test-native-bog` covers every milestone, runs in
   CI on every commit, and passes. Every validator rule and every oracle gets a
   known-bad negative test in the same commit as the rule.
3. **Never claim Niagara runtime qualification.** The Shadow Runtime is a model of
   Niagara, not Niagara. The tier is `bog-simulated`; the word "qualified" is reserved
   for evidence from a licensed runtime.
4. **Label assumptions; never guess silently.** Every behavior you assume about
   Niagara goes into `docs/niagara-semantics.md` with a source: a Tridium guide, a real
   `.bog` in the catalog, or `ASSUMED: verify at Gate G-WB`. Assumed behaviors are
   exercised under several plausible variants (see N6) so the result is robust to the
   unknown, not dependent on the guess.
5. **Human gates.** Where a step needs a licensed Workbench, the Niagara SDK or a
   signing certificate, write `gates/<id>.md` with the exact steps and the expected
   evidence files, mark it `WAITING_ON_HUMAN`, and keep going. Never mark a gate
   passed yourself. Never fabricate evidence.
6. **Record decisions** in `docs/decisions/NNN-<slug>.md` and continue. Stop and ask
   only if a decision changes scope. The decisions this goal already expects are
   listed at the end.
7. **Repo conventions, which are not optional.**
   - Python 3.11–3.13 (`make install PYTHON=python3.13` if `python3` is 3.14).
     `ruff check src tests scripts` must pass. Tests are tiered by pytest markers:
     `minimal` (base install), default (`test-integration`, needs the vendored stack
     and runs with `BACTALK_REQUIRE_FULL_STACK=1`), `docker`, `licensed`.
   - The web bundle in `src/bactalk/static-next/` is tracked and served by the API;
     rebuild it (`make web-build`) in the same commit as any `web/` change. Playwright
     journeys live in `web/e2e/`, with axe on every page.
   - Never delete or weaken an existing test to get green. Replace fixtures; do not
     drop coverage.
   - Backend behavior changes that are not additive need a decision record.

## Milestones

### N0: Clear the ground

1. **Retire the hand-written packs safely.** `src/bactalk/sequences/` is imported by
   `src/bactalk/agent.py` (the family router) and `src/bactalk/demo.py`
   (`demo_job` builds `VAV_12` with `G36_VAV_REHEAT`; `generalist_demo_job` builds
   `AHU_1`), and is exercised by `tests/test_sequence.py`, the demo project used by
   `scripts/verify_contractor_workflow.py`, `web/scripts/record-complex-workflow.mjs`,
   and the Playwright journeys (`web/e2e/shell.spec.ts` picks `AHU_1`, `EF_1`,
   `VAV_12`). Replacing them is a migration, not a deletion:
   - Add an LBNL-sourced VAV reheat demo job and an LBNL multizone AHU demo job
     (family `LBNL_G36_CONTROLLER`, via `G36Library`) and point `demo_job`,
     `generalist_demo_job`, the demo project, and the e2e fixtures at them.
   - Keep the exhaust fan and pump packs only if the demo project still needs them
     for topology; label them `BACTALK_STANDARD_SEQUENCE` and move them under Tier 4
     rules (a sequence document, generated tests, Gate G-ENG) rather than calling
     them G36. Delete `g36_vav.py`, `ahu_safety.py` and `ahu_static_pressure.py`.
   - Run `make test-integration` and the Playwright suite; both stay green.
2. **Fix units.** Carry `PointSpec.units` and parameter units into `.bog` facets
   (`degF`, `percent`, `cfm`, `inH2O`, and so on, using Niagara unit names). Replace
   the `units=u:null` literal in `niagara_extensions.py`. Add
   `tests/test_native_bog_units.py`: it fails if any point with declared units emits
   `u:null` or no `units` facet.
3. **Create `make test-native-bog`** (`pytest -m native_bog`, a new marker) and add
   it to `.github/workflows/ci.yml` in the integration job. Add `STATUS.md` with the
   baseline (`make test-minimal`, `make test-integration`, `cd web && npm test && npx
   playwright test --project=chromium-desktop`).
4. **Write `gates/G-SDK.md` and `gates/G-WB.md` now**, so license procurement starts
   while engineering continues.

Exit: CI green, the demo is LBNL-sourced, the units test passes, `STATUS.md` exists.

### N1: Niagara type and slot catalog, plus the static validator

1. **Build `data/niagara-catalog/`** from real `.bog` files: the 20 MIT ProgramObject
   archives (`niagara_program_library.py` already parses them), pybog's 21 examples in
   `.vendor/pybog`, the nhaystack test stations, and any license-compatible public
   `.bog`. For every component type seen, record module and type name, property and
   slot names with value types, which slots are link targets in practice, facet
   formats, and provenance (source file and hash). Supplement from Tridium
   documentation; anything seen only in documentation is marked `doc-only`.
2. **Write `src/bactalk/niagara/validate.py`.** It checks: well-formed
   `bajaObjectGraph` XML; every `t=` type is in the catalog or a declared
   `bactalkG36` type; `m=` module declarations are consistent; handles are unique
   (reuse `_collect_handles` from `niagara_station.py`); every link `sourceOrd`
   resolves inside the file; source and target slots exist on those types; no
   double-driven targets; facets parse and units are Niagara unit names; numeric and
   boolean slot types match across links.
3. **Negative tests:** one known-bad fixture per rule under
   `tests/fixtures/native-bog/bad/`.
4. **Wire it in:** the validator runs on every `.bog` the service produces, and
   `make test-native-bog` runs it on every fixture.

Exit: the validator runs in CI on every generated `.bog`. Current stock-only output
passes.

### N2: Lowering matrix and equivalence policy

1. **Classify every `BlockKind`** into `STOCK_EXACT` (a stock block with identical
   behavior), `STOCK_WITHIN_BANDS` (documented deviation, passes every scenario within
   tolerance; e.g. `kitControl:LoopPoint` for `pid_with_reset` if it holds),
   `MODULE` (needs a `bactalkG36` block), or `UNSUPPORTED`. The 25 kinds that go to
   ProgramObjects today are the ones to decide. Generate
   `docs/niagara-lowering-matrix.md` from code (`src/bactalk/niagara/lowering.py`),
   never by hand.
2. **Document each `STOCK_WITHIN_BANDS` choice** with the exact deviation and the
   scenarios that bound it (saturation, reset, windup, start-up). They stay
   provisional until N7 proves them in the Shadow Runtime.
3. **Policy:** stock first, then module, then fail closed. ProgramObjects survive only
   behind `--expert-program-objects`, using the existing
   `NiagaraProgramPackageBuilder`. A new `UNSUPPORTED` kind blocks that library item,
   never the pipeline.

Exit: no `UNSUPPORTED` entries for Tier 1 configurations; the matrix regenerates in
`make test-native-bog` and a stale committed copy fails the build.

### N3: The `bactalkG36` Niagara module (source and kernels)

1. **Create `niagara-module/bactalkG36/`** as a Gradle project in the nhaystack
   layout (`-rt` and `-wb`). Implement only the `MODULE` blocks from N2; expect
   `TrimAndRespond` (with and without hold), `TrueFalseHold`, `TrueDelay`,
   `Timer`/`TimerWithReset`/`TimerAccumulating`, `MovingAverage`, `Sampler`,
   `Hysteresis` if `kitControl` cannot express it, and a CDL-exact `PIDWithReset` as
   an option.
2. **One computational kernel per block** in plain Java with no Niagara
   dependencies, harvested from the kernel members in `niagara_program_codegen.py`
   (`_pid_kernel_members`, `_trim_and_respond_kernel_members`, and the rest). The
   Niagara component wraps the kernel.
3. **Each component defines** typed `StatusNumeric`/`StatusBoolean` slots with
   facets, status handling for null/fault/stale inputs, an execution-period property,
   and palette and doc entries.
4. **Kernel contract.** The kernels' behavior is pinned by the OCE golden traces and
   by BACTalk's existing IR interpreter tests. CI compiles the kernels with `javac`
   and runs them against those goldens. Component wrappers compile against stub
   interfaces in CI. Building and signing the real module is **Gate G-SDK**.

Exit: every kernel passes its goldens in CI; `gates/G-SDK.md` lists the exact build
and signing steps and the evidence files expected back.

### N4: Native `.bog` compiler for LBNL G36

1. **Rewrite the default compile path** (`src/bactalk/niagara/emit.py`, called from
   `NiagaraCompiler`). An LBNL controller becomes one `.bog` with: folders by G36
   section mapped from the originating CDL composites (the expanded IR keeps the
   composite path; if it does not, add it in `g36_library.py` first); a
   `Parameters` folder of writable points with units, defaults and the G36 section
   in their descriptions; `Inputs` and `Outputs` boundary folders; stock and
   `bactalkG36` blocks only, per the matrix; human-readable block names; a
   deterministic left-to-right layered layout with no overlaps and at most about 60
   blocks per folder, splitting into subfolders when needed.
2. **Cross-folder signals** are proper Niagara links between folders. No dangling or
   duplicate links.
3. **Multi-equipment output.** An AHU plus N VAVs is one `.bog`: one folder per VAV
   instance, request aggregation linked into the AHU's reset logic.
4. **pybog decision.** pybog 0.1.6 has no folder nesting or custom-type API (today's
   compiler pokes its private `_links`). Decide early, with a decision record:
   extend pybog upstream, or emit `bajaObjectGraph` XML directly with golden-file
   tests. The default recommendation is direct XML behind a small typed emitter, with
   pybog kept for its layout helpers if useful.
5. **Wiresheet previews.** Produce an SVG per folder for the review screen
   (`src/bactalk/niagara/preview.py`), deterministic so it can be snapshot-tested.
6. **Readability tests:** no overlaps, the per-folder limit, readable names, every
   link resolved, byte-identical output for identical input.

Exit: every Tier 1 configuration exports one `.bog` that passes N1 and the
readability tests.

### N5: Link to the job's points

1. **Accept a contractor station `.bog`** with its BACnet network, devices and proxy
   points, parsed as data only (extend `niagara_station.py`; keep its handle checks).
2. **Mapping suggestions:** propose matches to the canonical points from normalized
   names, an abbreviation dictionary, BACnet object type, units and device grouping.
   A human confirms matches in the UI (the Intake stage's Normalize step is the
   place); nothing binds without confirmation.
3. **Link inside the exported `.bog`:** proxy points into logic inputs; logic outputs
   into writable proxies at a configurable priority level (never 1, never implicit);
   collision checks; handle rebasing through `_rebase_program_handles`.
4. **Retire the Java binders.** `niagara_bindings.py` leaves the default path;
   `BactalkPointBinder_*.java` is emitted only under `--expert-program-objects`.
5. **Fallback.** With no station supplied, the `Inputs`/`Outputs` folders are
   writable points with units, ready to link in Workbench.

Exit: a fixture station with one AHU and 25 VAVs and messy real-world names exports
as a linked `.bog` that passes the validator with no generated Java.

### N6: Niagara Shadow Runtime

Build `src/bactalk/niagara/shadow/`: a runtime that loads **the exported `.bog`
file** and executes it with Niagara-like semantics. It never reads BACTalk's IR; the
file is its only input.

1. **Loader:** parse `bajaObjectGraph`, build the component tree, resolve handles and
   ORDs, instantiate each component from a registry keyed by Niagara type
   (`kitControl:Add`, `kitControl:LoopPoint`, `control:NumericWritable`,
   `bactalkG36:TrimAndRespond`, …), reject unknown types.
2. **Semantics, each documented in `docs/niagara-semantics.md`:** status values on
   every slot (ok, null, fault, stale, down, overridden) with kitControl propagation
   rules; writable points with a 16-level priority array, fallback, level 1 and 8
   override behavior, and BooleanWritable minimum on/off times; event-driven link
   propagation with loop detection; timed and periodic blocks on a simulated clock
   (BooleanDelay, OneShot, LoopPoint at its interval, module blocks at their period);
   `sch:*` schedules and histories on the same clock.
3. **Uncertainty is a robustness requirement.** Execution order and cycle timing
   are configurable. Where Niagara's exact behavior is `ASSUMED`, every scenario runs
   under several plausible orderings and timings, and results must stay within bands
   under all of them.
4. **Block library:** every stock type the compiler emits for any library item, each
   with per-block unit tests citing the documented behavior.
5. **Module blocks: one contract, provable both ways.** The Java kernels from N3
   are the module's truth. The Shadow Runtime executes them through a JVM sidecar
   when Java is available (CI and production images), and CI also runs a Python port
   of each kernel against the same goldens so the runtime works without a JVM in a
   base install. Both implementations must pass identical golden traces; a drift
   fails the build. Record this as a decision.
6. **Scenario driver:** apply each acceptance scenario's input trajectories to the
   `.bog`'s input points (or linked proxies), advance the clock, capture every output
   and key internal slot into the same trace shape the web UI already reads.
7. **Performance:** an AHU plus 25 VAVs through the full scenario suite in under
   five minutes on a CI runner, parallelized through the existing RQ worker path.

Exit: the Shadow Runtime loads and runs every Tier 1 export; every stock block's unit
tests pass; `docs/niagara-semantics.md` lists every assumption with its source.

### N7: Prove it

1. **Three-way differential testing (D3)** with pyfunnel bands. A disagreement fails
   the build and names the first diverging block and slot. Widening a band needs a
   decision record with an engineering rationale.
2. **Property-based testing.** `hypothesis` generates random valid IR graphs from
   the supported block set; compile to `.bog`, run in the Shadow Runtime, compare with
   the IR interpreter.
3. **Mutation testing (D4)** with a `.bog` mutator (`src/bactalk/niagara/mutate.py`):
   swap link slots, change block types, delete links, alter constants, flip
   `loopAction`, drop facets, change priority levels. Report the catch rate (≥ 95%)
   and list every survivor.
4. **Web app integration (D5).** The Shadow Runtime runs as a worker job for every
   build, using the qualification-job machinery (`qualification_jobs.py`, the SSE
   stream, `JobProgress`). Its trace is a new source on the Test stage's clock
   switcher (`shadow`), drawn against the reference with bands; folder SVGs appear on
   the Build stage; per-scenario pass/fail and first-divergence detail appear in the
   Review stage's surfaces; the report joins the approval digest
   (`artifact_hash`, `_record_artifact_paths` in `service.py`); export is blocked
   while any scenario fails. Add a Playwright journey with a mocked job cycle.
5. **Honest labelling (D6).** Add `bog-simulated` to `readiness.py` `STAGES` below
   `verified` and above `product-wired`, and label it in the UI and README.
6. **Calibration kit** (`gates/G-WB.md` plus `calibration/`): one small `.bog` per
   assumption in `niagara-semantics.md`, the expected Shadow Runtime trace for each,
   a step-by-step Workbench procedure a human runs once, and a script that compares
   the exported histories with the expected traces and marks each assumption
   `VERIFIED` or `CONTRADICTED`. A contradicted assumption becomes a failing test.

Exit: D1–D6 pass in CI for Tier 1, `STATUS.md` shows N0–N7 complete, and
`gates/G-WB.md` and `gates/G-SDK.md` are ready for a human.

### N8: Every LBNL G36 and plant-template controller (Tiers 2 and 2b)

1. **Pin the chiller plant.** Add a second Modelica Buildings entry to
   `ops/stack.lock.json` at a specific `master` commit containing `G36/Plants`. Keep
   v13.0.0 as the default until the newer pin passes the whole suite. Label anything
   from an unreleased commit `pre-release` in the UI.
2. **Enumerate configurations** per family (fan arrangement, economizer type, coil
   types, sensor options; plant arrangements: primary-only or primary-secondary,
   headered or dedicated pumps, waterside economizer). Use ctrl-flow where it models
   the family, else the controller's declared parameters.
3. **Run each configuration through the existing lane** (CXF, OCE, parameter schema,
   point contract, scenario suite covering every G36 section: normal operation, every
   mode, every alarm, sensor failures and recovery).
4. **Push each through the unchanged N4–N7 pipeline.** Adding a block to the matrix,
   the module, or the Shadow Runtime is allowed. Equipment-specific code in the
   compiler or runtime is not.
5. **Mixed-equipment stations.** One `.bog` can hold any combination, with
   cross-equipment request links generated from the G36 request definitions.
6. **Coverage report.** Generate `docs/coverage.md` from the library: every family
   and variant, its source of truth, its tier, and D1–D4 status.

Exit: every Tier 2/2b configuration LBNL implements passes D1–D4 or is listed in
`docs/coverage.md` with its exact blocker.

### Test Generation Protocol (N9, N10, N11)

AI writes all tests for Tiers 3–5. Humans supply intent and approve requirements;
they never write test code. The rules below are what make AI-written tests stronger
than the AI's own blind spots.

1. **Requirements first, in plain language.** Every sequence starts as a numbered
   list: inputs, conditions, timing, expected outputs, alarms, failure behavior,
   recovery. Each cites its source. AI drafts it; a human approves it in the web app
   (the one human step, because someone must decide what "correct" means).
2. **Strict separation.** Two AI roles in separate sessions: the **logic author**
   sees requirements and sources and builds the IR; the **test author** sees
   requirements and sources, never the IR or the `.bog`, and builds the tests.
   Enforce it in code: the test-generation worker has no API access to the logic.
   Use different models or providers for the two roles where available.
3. **Tests are built mechanically from requirements.** Per requirement: a positive
   scenario, a negative scenario, timing boundaries just before and after every delay
   and persistence window, value boundaries at every threshold and deadband edge,
   failure cases per input (null, stale, fault, stuck, out of range), and recovery.
   Plus **invariants** that must hold at every step of every scenario and across
   randomly generated input sequences.
4. **Traceability.** Every test references its requirement; every requirement has
   tests; a requirement with no test blocks the item.
5. **Adequacy is proven.** A suite is accepted only when mutation testing of the
   logic kills ≥ 95% of mutants, every decision branch is exercised (the existing
   decision/outcome coverage), and every invariant held across ≥ 10,000 randomized
   sequences. Survivors go back to the test author, which adds tests without seeing
   the logic, or flags the requirement as ambiguous.
6. **Disagreements go to a human as a question, never a silent fix.** A third AI
   step classifies a failure as a logic bug, a test bug, or an ambiguous requirement,
   and only the last becomes a specific question in the web app. The logic author may
   never edit tests; the test author may never edit logic.
7. **Readable test plan** in the web app: requirement → scenarios → expected result
   → pass/fail, plus mutation and invariant results, included in the approval digest
   and reusable as the commissioning functional test plan.

### N9: G36 sequences with no LBNL reference (Tier 3)

1. Add `docs/library-authoring.md`. Engineers (human or agent) implement the
   sequence in the typed IR directly from the G36 text; every block group cites the
   section and paragraph.
2. Tests follow the protocol from the G36 text alone.
3. **Gate G-ENG:** a qualified controls engineer approves the requirements list.
   Until then the item is `unapproved` and export is blocked.
4. Start with the hot water/boiler plant (staging, lead/lag rotation, supply
   temperature reset, pumps, minimum flow, alarms), then the 2024-edition humidity
   and pollution modules if the pinned LBNL revision lacks them.
5. If LBNL later publishes CDL for a Tier 3 item, it becomes the reference and the
   BACTalk version must pass three-way testing against it or be replaced.

Exit: the boiler plant passes D1–D4 plus G-ENG; other Tier 3 items are done or listed
in `docs/coverage.md`.

### N10: Common non-G36 equipment (Tier 4)

1. Same process as N9 with a BACTalk sequence document per equipment type, written
   first in plain language in the style of G36 with cited sources, through G-ENG
   before implementation. The exhaust fan and pump packs kept in N0 are the first
   two items.
2. **Configurable, not forked:** declared options generate the right logic from one
   implementation.
3. Priority: RTUs, heat pumps, DOAS/ERVs, exhaust and supply fans, unit and cabinet
   heaters, standalone pumps, then the rest.
4. Label them "BACTalk standard sequence (engineer-approved requirements)", never
   "G36".

Exit: RTU, heat pump, DOAS and exhaust fan pass D1–D4 plus G-ENG.

### N11: Custom sequences (Tier 5)

1. The contractor uploads the spec section; AI drafts a typed IR program citing the
   spec text per block group; it goes through every normal gate.
2. Tests follow the protocol from the contractor's plain-language description and
   the spec paragraphs; the contractor approves the requirements list.
3. The custom program must pass its scenarios in the IR interpreter and the Shadow
   Runtime, pass mutation testing, and appear in the approval digest, labelled
   "custom, job-specific".
4. Composition with library equipment in the same `.bog` through declared typed
   signals only (the project signal-binding machinery already exists).
5. A custom program reused across jobs can be promoted to Tier 4 through N10.

Exit: a fixture job combining Tier 1 equipment with two custom sequences exports one
`.bog` that passes D1–D4, with every test traced to an approved requirement.

## UI surfaces: what exists, what is new

The React workbench (`web/src/features/`) already covers roughly half of what this
goal needs. Reuse is mandatory where a surface exists; new surfaces go through the
same design system (`web/src/design-system/`), the Playwright suite with axe, and the
visual baselines.

| Surface the goal needs | Status | Where |
|---|---|---|
| Trajectories on a shared clock, reference with tolerance bands, counterexample window, peak error | Exists | `features/trends/TrendPane.tsx`, `stores/trace.ts` (`OracleBand`) |
| Switching between evidence sources on the clock | Exists; add a `shadow` source | `features/test/TestStage.tsx` clock source switcher |
| Live worker-job progress (phase, steps, heartbeat, cancel) | Exists | `features/simulation/JobProgress.tsx`, SSE route |
| Evidence surfaces with acknowledgement and digest-bound approval | Exists; add a Shadow Runtime surface | `features/review/` |
| Export gated by server state | Exists; add "blocked while a scenario fails" | `features/release/ExportHandoff.tsx` |
| IR wiresheet with live values | Exists; it shows BACTalk IR blocks, not Niagara blocks | `features/wiresheet/` |
| Point normalization and mapping review | Exists for job points | Intake Normalize step; design `PointsStep` |
| Maturity ladder and readiness | Exists; add the `bog-simulated` tier | `features/admin/Admin.tsx` |
| Library catalogs with provenance | Exists; add D1–D4 columns from `docs/coverage.md` | `features/libraries/Libraries.tsx` |
| **Niagara folder previews** (the `.bog` as Workbench will show it: folders, kitControl and `bactalkG36` blocks, links) | **New** (N4, D5). Server renders deterministic SVG per folder; the Build stage gets a "Niagara view" tab beside the IR wiresheet | `features/wiresheet/NiagaraFolders.tsx` |
| **First-divergence detail**: which block and slot diverged first, jump to it in both the IR wiresheet and the Niagara folder view | **New** (N7) | Test stage, Assertions panel |
| **Mutation report**: catch rate, surviving mutants, each opened as a diff on the folder view | **New** (N7) | Review stage surface |
| **Station point matching**: proxy points from a contractor station against canonical points, with device grouping, unit and object-type hints, and explicit confirmation before anything binds | **New** (N5); builds on the Points step pattern | Intake |
| **Requirements approval**: the numbered plain-language requirements list, edit and approve, with source citations; the human step of the Test Generation Protocol and Gate G-ENG | **New** (N9–N11) | a `Requirements` step in the design pipeline and the custom lane |
| **Question inbox**: ambiguous-requirement questions from the classifier step, answered in the web app | **New** (protocol rule 6) | Home review queue plus the job's Intake stage |
| **Readable test plan**: requirement → scenarios → expected → pass/fail, invariants, mutation results; exported into the submittal | **New** (protocol rule 7) | Test stage tab and Review surface |
| **Gate status and calibration results**: G-SDK, G-ENG, G-WB state; per-assumption VERIFIED / CONTRADICTED after a Workbench session | **New** (N7) | Admin |
| **Coverage matrix** by family and variant with tier, source of truth and D1–D4 | **New** (N8), generated from the library | Libraries |

## Human gates

| Gate | What a human provides | What it confirms |
|---|---|---|
| G-SDK | Niagara SDK access and a code-signing certificate | Builds and signs the real `bactalkG36` module |
| G-ENG | A qualified controls engineer approves the plain-language requirements for each Tier 3 and Tier 4 sequence (not tests, not code) | Tier 3 and 4 items can export |
| G-WB | A licensed Workbench with a localhost station (later a JACE); runs the calibration kit and imports the in-scope `.bog` files | Promotes Shadow Runtime assumptions to verified and moves evidence from `bog-simulated` toward `runtime-qualified` |

## Decisions this goal already expects (write each as `docs/decisions/NNN-*.md`)

1. Direct `bajaObjectGraph` XML emission versus extending pybog (N4).
2. Kernel execution in the Shadow Runtime: JVM sidecar plus a golden-checked Python
   port (N6).
3. Which `BlockKind`s are `STOCK_WITHIN_BANDS` and the bands that justify each (N2).
4. The `master` commit pinned for the chiller plant (N8).
5. Any widened pyfunnel band (N7), with the engineering rationale.

## First session checklist

1. Read this file, `README.md`, `docs/ARCHITECTURE.md`, `src/bactalk/compiler.py`,
   `src/bactalk/service.py` (`create_run`), `src/bactalk/integrations/g36_library.py`,
   `src/bactalk/integrations/niagara_program_codegen.py` (skim; note the kernel
   members), `src/bactalk/integrations/niagara_station.py`, and
   `web/src/features/test/TestStage.tsx`.
2. Bootstrap and record the baseline:
   ```bash
   make install PYTHON=python3.13
   make doctor
   make test-minimal
   make bootstrap-full            # vendored stack; needed for test-integration
   make test-integration
   cd web && npm ci && npm run build && npm test && npx playwright test --project=chromium-desktop
   ```
   Put the results in `STATUS.md` as the baseline.
3. Do N0 completely. Then start N1 and, in parallel, write `gates/G-SDK.md` and
   `gates/G-WB.md`.

## Reference resources

| Resource | What it gives you | Use in |
|---|---|---|
| [LBNL Modelica Buildings](https://github.com/lbl-srg/modelica-buildings) (BSD-3; pinned v13.0.0) | Reference G36 and plant controls in CDL; `master` adds `G36/Plants/Chillers` | N0–N8 |
| [modelica-json](https://github.com/lbl-srg/modelica-json) (pinned) | CDL → CXF | N1, N8 |
| [Open Control Engine](https://github.com/jscott3201/open-control-engine) (pinned; 46 G36 goldens vendored) | Deterministic CXF execution; the reference oracle | N3, N7 |
| [OBC code generation spec](https://obc.lbl.gov/specification/codeGeneration.html) | LBNL's documented CXF-to-vendor approaches; their Niagara translator is not public, so ask the OBC team | N2, N4 |
| [lbl-srg/cdl-plc](https://github.com/lbl-srg/cdl-plc) | A public block-by-block CXF translator to copy the structure of | N2, N4 |
| [bbartling/pybog](https://github.com/bbartling/pybog) (MIT; pinned 0.1.6) | Python `.bog` builder and 21 examples | N1, N4 |
| [nhaystack](https://github.com/ci-richard-mcelhinney/nhaystack) (AFL-3.0; vendored) | A complete open-source Niagara 4 module with a Gradle `-rt`/`-wb` split | N3 |
| The 20 MIT ProgramObject archives (`niagara_program_library.py`) and public `.bog` files | Real `.bog` XML to mine types and slots from | N1 |
| Tridium kitControl, Component, Alarm, History and Tagging guides | Documented block behavior | N1, N6 |
| [LBNL guideline36_conformance_test](https://github.com/LBNL-ETA/guideline36_conformance_test) | Vendor-independent G36 conformance cases | N7, N8 |
| [pyfunnel](https://github.com/lbl-srg/funnel) (pinned) | Tolerance-band comparison | N7 |
| [PNNL ConStrain](https://github.com/pnnl/ConStrain) (vendored) | ASHRAE 90.1 control verification rules | N10 |
| [Hypothesis](https://hypothesis.readthedocs.io/) (already a test dependency) | Property-based testing | N7, protocol |
| [mutmut](https://github.com/boxed/mutmut) or a custom mutator | Mutation testing of IR and `.bog` | N7, protocol |
| [ASHRAE 231 / CXF](https://data.ashrae.org/standard231/) | The CDL/CXF standard | future multi-vendor output |

No public format exists for Honeywell Spyder/IRM, Siemens ABT Site/PXC, Distech
EC-gfxProgram, ALC EIKON or JCI CCT logic. Each of those is a human gate, not a
milestone.
