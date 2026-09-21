# 001: Retain LBNL translations as package data; retire the packs at N4, not N0

Status: accepted (N0)

## Context

GOAL-NATIVE-BOG.md asks N0 to make the demo LBNL-sourced and to delete the
hand-written `G36_VAV_REHEAT`, `CUSTOM_AHU_SAFETY_COOLING` and `AHU_DUCT_STATIC_PI`
packs. Two facts in the code cut across that:

1. Translating an LBNL controller needs the vendored toolchain (modelica-json under
   Node, Open Control Engine under Cargo). A base install (`make install`, what a
   contractor's laptop and the CI base job have) cannot run it, so a demo job that
   translates at build time would fail there.
2. `service.create_run` refuses station assembly for any run that emits a
   ProgramObject source package, and until N4 every LBNL controller emits one.
   The whole-building demo project, the recorded contractor workflow and the
   Playwright topology journeys all assemble a station from the AHU, duct-static
   and VAV packs.

## Decision

- The demo candidates (`bactalk demo`, `make demo`, `POST /api/runs/demo`,
  `POST /api/runs/demo/generalist`, `bactalk.library_demo.lbnl_*`) are LBNL-sourced: the
  VAV reheat terminal unit and the multizone VAV AHU. Their translations are
  retained as package data under `bactalk/library_demo/` with full provenance
  (LBNL revision, controller source digest, CXF digest, execution profile, every
  parameter). The integration tier re-translates and fails on drift.
- The VAV reheat controller uses the `host_tick_v1` execution profile: at v13.0.0
  its `CDL.Logical.Pre` blocks make `modelica_exact` untranslatable, and its
  `TrueDelay(delayOnInit=false)` blocks are Niagara-exactness blockers to be
  resolved by N2/N3 (a `bactalkG36` TrueDelay that honours `delayOnInit`).
- The three hand-written packs stay installed until N4 exits, so the project demo
  and its journeys keep working, but they no longer claim Guideline 36 anywhere:
  the intake family reads "Standard VAV with reheat (BACTalk pack)", the
  capability pack is named as bounded and not G36, and the README says so. They
  are deleted in the same change that gives the LBNL controllers a native `.bog`
  that station assembly accepts.
- The pack-built fixtures the tests and scripts still need live behind explicit
  names (`standard_vav_demo_job`, `standard_ahu_demo_job`). `bactalk.demo.demo_job`
  and `generalist_demo_job` stay as aliases of those pack fixtures, because about
  thirty station, BACnet-lab, nhaystack, VOLTTRON, schedule, alarm and topology
  tests are written against their point names; the product demo surfaces
  (`bactalk demo`, the two `/api/runs/demo` routes) call the LBNL jobs directly.

## Consequences

- A base install builds both demo candidates from retained typed IR and produces
  the ProgramObject package (the honest current artifact) until N4.
- A relative-name bug in the CXF importer (`CDL.Logical.Not` not qualified to
  `Buildings.Controls.OBC.CDL.Logical.Not`) was fixed on the way; it had blocked
  every terminal-unit controller.
