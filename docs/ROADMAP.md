# Delivery roadmap

## Milestone 1 — runnable vertical slice (this repository)

- Job and point schemas.
- Typed graph and deterministic VAV-reheat subset.
- pybog compiler.
- Fast Tier-1 simulation.
- Review and artifact-bound approval UI.

Exit criterion: a developer can create, review, approve, and export the demo `.bog`; automated tests prove that unapproved or modified artifacts cannot be exported.

## Milestone 2 — contractor inputs and template learning

- CSV/XLSX points-list import with a mapping review screen.
- Read-only BACnet scan import using BACpypes3; network scanning must require explicit interface and subnet selection.
- pybog Analyzer ingestion of `.bog`/`.dist` libraries.
- Semantic shop profile: naming, folders, facets, tags, alarms, graphics, and preferred blocks.
- Graph-level comparator with traceability from each change to a requirement.
- Hash-verified contractor environment packs for proprietary modules, palettes, typed component contracts, and graphics templates. **Implemented at the static/compiler boundary; licensed-runtime qualification remains.**

Exit criterion: reproduce an approved contractor pattern without copying stale site identifiers or credentials.

## Milestone 3 — sequence source of truth

- Version-pin LBNL Buildings controls sources.
- Run modelica-json as an external build service to produce CDL JSON/CXF.
- Normalize CXF to the BACTalk IR and preserve clause/source provenance.
- Expand the product-wired ctrl-flow Linkage Schema lane beyond its current multizone AHU and VAV terminal templates. **The three current templates now map into exact LBNL G36 controller IDs, component inventories, conditional point contracts, qualification scenarios, capability candidates, and explicit release blockers; contractor points are reconciled against every generated contract with exact/audited aliases and unit-conversion evidence. Uploaded sequences now receive source-hashed, excerpt-backed facet coverage across every selected scenario and unknown scenario types fail closed. Converting that language into engineer-approved executable requirements, compiling those briefs into complete verified target jobs, and adding more upstream templates remain.**
- Expand the compiler test matrix across Niagara versions and module sets.

Exit criterion: every generated block and test is traceable to an input, shop rule, or versioned sequence requirement.

## Milestone 4 — BOPTEST and actual station execution

- Tier-2 BOPTEST REST adapter with reproducible test-case containers. **The pinned local stack, real FMU lifecycle, complete typed-graph mapping, bounded overrides, and retained four-step closed-loop trajectory are implemented. Qualification now attaches atomically to a normal run through the service/API, enters its signed digest and review bundle, and blocks approval on failure. Production equipment maps and long-horizon scenario suites remain.**
- Tolerance/scoring through pyfunnel. **Implemented as append-once signed run evidence with explicit independent trajectory oracles and actual error interpretation; every production pack still needs its own authoritative reference trajectories and tolerances.**
- Tier-3 Niagara-to-BOPTEST BACnet lab with isolated addressing and write allowlists.
- Loopback BACnet/IP fake-building generation, independent BAC0 probing, and mapped acceptance result capture. **Implemented; licensed Niagara attachment and exact MS/TP hardware remain.**
- Failure minimization: preserve seeds and shrink failing scenarios.

Exit criterion: a real Niagara station executes the generated logic against a simulated building and produces replayable evidence.

## Milestone 5 — agent loop (product-wired prototype)

- Role-separated conversation and coding models constrained to strict typed-IR schemas. **Implemented; Qwen/GPT-OSS provider smoke is executable with `make cerebras-smoke`.**
- Diagnose-test-repair loop with a bounded iteration count and full event log. **Implemented for deterministic acceptance tests.**
- Policy checks for overrides, safeties, simultaneous heating/cooling, alarm floods, and out-of-range commands.
- Engineer-authored acceptance plans and hard stop conditions. **Required for the AI-custom lane.**
- Schema-constrained AI parameter changes for pinned plant controllers. **Implemented; the model cannot rewrite qualified library topology, and every proposal becomes a retested child run.**

Exit criterion: the agent can find and repair seeded defects without weakening a test or changing a safety policy.

## Milestone 6 — broader production scope

- AHUs, central plants, dual-duct, fan-powered boxes, and plant staging. **The 38-model LBNL central-plant source library is now wired into job/test/review/export; licensed Workbench compilation and field qualification remain. AHU breadth and terminal-unit families remain incomplete.**
- Extend the weekly schedule compiler with qualified holiday/special-event calendars; qualify COV history collectors; run generated tag/alarm installers, contractor-template PX, and atomic multi-equipment station assembly through the licensed Niagara matrix; install PX navigation. Typed cross-equipment acceptance scenarios and offline Niagara links are implemented; high-fidelity whole-building physics and licensed runtime qualification remain.
- Brick and Haystack/Xeto validation.
- Signed releases, SBOMs, audit retention, role-based approvals, and multi-tenant isolation.
