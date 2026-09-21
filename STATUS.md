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
| N1 Catalog + validator | not started | | |
| N2 Lowering matrix | not started | | Tier 1 blockers listed under N0 results |
| N3 bactalkG36 kernels | not started | | Gate G-SDK written |
| N4 Native emitter | not started | | |
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

## Gates

| Gate | Status | File |
|---|---|---|
| G-SDK | WAITING_ON_HUMAN | `gates/G-SDK.md` |
| G-WB | WAITING_ON_HUMAN | `gates/G-WB.md` |
| G-ENG | not yet needed (Tier 3+) | |
