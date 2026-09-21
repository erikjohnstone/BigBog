# BACTalk

BACTalk is a human-gated programming workbench for building controls: the controls-industry analogue of an AI coding agent. It turns a controls job into a typed program, emits either a Niagara `.bog` or an exact ProgramObject source-and-wiring package, tests the behavior, and exposes the proposed artifact and evidence for engineering approval.

This repository is an expanding product foundation, **not yet a program-any-building product, a complete implementation of ASHRAE Guideline 36, or production-certified control logic**. Machine-readable readiness and capability ledgers make that boundary explicit.

## What works now

- A strict job schema for points, sequence parameters, BACnet object references, and Brick classes.
- Contractor intake for CSV/XLSX point schedules and TXT/Markdown/JSON/DOCX/PDF sequence documents, with bounded parsing, deterministic normalization, a pre-build mapping preview, audited common-name aliases, source hashes, and exact uploaded files retained inside the immutable approval digest.
- A provider-neutral typed control graph. It rejects bad slots, duplicate drivers, type mismatches, and combinational cycles while allowing explicit sampled loop cuts. Its deterministic interpreter covers algebra, logic, edge/change detection, delays, latches, moving-window averages, periodic samplers, unit delays, reset, and PI behavior.
- An equipment-neutral custom-graph lane with mandatory acceptance oracles.
- Six deterministic Niagara-targeted prototype/qualifying packs: a bounded `G36_VAV_REHEAT` subset, AHU safety/cooling, AHU duct-static PI control, exhaust-fan command/proof alarm, fail-closed two-pump duty/standby selection, and the 38-model LBNL plant-controls library.
- Stateful acceptance timelines that verify transitions such as startup grace, proof timeout, alarm assertion, and recovery across scan cycles.
- Typed fault contracts for force, bias, scale, drift, stuck, stale, dropout, and Boolean-inversion failures. Faults can independently drive a Boolean quality input, preserve raw/effective scan evidence, and require explicit fallback and recovery assertions; the complex demo now proves lost fan proof plus single- and dual-pump unavailability rather than merely setting those inputs by hand.
- Versioned equipment qualification profiles turn normal, safety, failure, alarm, override, restart, and recovery expectations into a visible matrix. Passing cases receive credit only when explicitly tagged; requirements that call for a fault or recovery phase are mechanically checked; conditional hazards remain open until the contractor supplies evidence or a contractor-owned profile marks them not applicable. Built-in profiles cover the current VAV, AHU safety, duct-static, exhaust-proof, and duty/standby-pump packs, while `JobSpec.qualification_profile` accepts project-specific profiles for custom equipment.
- A pinned LBNL ctrl-flow design lane runs the real upstream Linkage Schema interpreter for multizone VAV AHUs, cooling-only VAV terminals, and reheat VAV terminals. Approved equipment choices expand into an explicit programming brief: selected component inventory, 31–61 conditional point obligations, 12–19 normal/fault/recovery scenarios, the matching LBNL G36 controller, installed BACTalk capability candidates, deliverables, and release blockers. A fail-closed reconciler then compares contractor points with that exact brief: only canonical names and audited aliases map automatically; missing, ambiguous, duplicate, role/type-invalid, or unit-invalid points block progress, while compatible SI/IP units require an explicit converter. Every uploaded CSV/XLSX inspection is now retained append-only with its exact source bytes, configuration, canonical mappings, result hash, artifact hash, actor, and tenant; sequence approval requires the exact passing reconciliation ID and rejects changed selections or a different template. A second source-hashed reconciler breaks every selected scenario into audited sequence facets, links every mention to bounded contractor-document excerpts, exposes missing fire/smoke, freeze, communications, proof, override, restart, plant, sensor, actuator, and recovery language, and fails closed for unknown future scenarios. Its structured extraction layer normalizes numeric thresholds, comparison direction, durations, persistence/delay/deadline meaning, output values, actions, reset/latch/priority policy, and clause relationships; it proposes canonical point bindings while preserving ambiguity, design-incompatible references, and vague language such as “short delay” or “as required.” Every extracted item remains an unapproved candidate and cannot generate a graph. An approver-only review boundary re-derives those candidates from the original upload, verifies the candidate digest, binds the retained contractor-point artifact into the review digest, requires a decision for every item, forces explicit point selection for ambiguous commands, rejects silent resolution of vague source language, and emits source-bound condition/duration/action oracle drafts. Each completed review is retained append-only with the exact original bytes, configuration, identity, results, and independently checked source/candidate/review/artifact hashes; retrieval is tenant-filtered when authentication is enabled, while external immutable retention remains explicitly unimplemented. A separate engineer can now author and approve exhaustive executable acceptance trajectories in the React workspace. The server requires a distinct identity, rechecks the retained artifact, validates point types and engineering-unit conversion, proves every trigger false→true→false, calculates pre-expiration and post-expiration timing steps, forbids weakening required outcomes, and requires recovery evidence. Each scenario facet is separately traced to overlapping source-bound oracle drafts. For non-numeric Boolean, mode, and event behavior, the UI exposes source-bound manual facet trajectories with explicit typed input/output bindings; event-only sequences are first-class and no longer require an invented numeric case. Each scenario supplies an audited trigger/observed-point allowlist, and the server rejects arbitrary but type-compatible I/O outside that contract. All three phases must use coherent points and prove both a controlled transition and recovery. Source-unmentioned facets cannot be bypassed with a manually invented test. Approved local `AcceptanceCase` timelines are retained, but the whole-system graph-generation gate opens only when every selected operating, fault, safety, and recovery facet has an executable oracle; deployment always remains closed. Phrase coverage is explicitly not semantic validation. The retained contract exercises all 44 currently exposed first-order variants, 2,229 generated required-point obligations, 767 scenario and I/O contracts, and the reciprocal draw-through/blow-through fan dependency. This closes the design-to-planning, retained contractor-I/O-contract, initial sequence-omission, candidate-review, numeric-oracle, and constrained event/mode-oracle gaps; consuming those immutable oracles in automatic graph planning and complete target lowering remain before text can drive deployable Niagara code.
- An approved-sequence candidate workflow now consumes that exact immutable chain instead of starting a disconnected generator. Its preflight verifies the oracle, review, point artifact, ctrl-flow configuration, required G36 parameters, explicit unit-converter work, complete canonical-point-to-graph boundary bindings, Niagara target assessment, output-to-oracle coverage, and every approved executable trajectory. Translation failures are returned as bounded, hashed compiler diagnostics. A separate generation endpoint retains the exact contractor inputs and approved evidence in a normal signed candidate run only after those gates pass, reruns the acceptance suite against the bound job, and leaves deployment closed pending human review and approval. This compiles the selected authoritative LBNL controller; it does not invent unsupported logic from prose.
- Generic sequence phrases are context-scoped before they can earn facet coverage. Words such as “shutdown,” “outdoor air,” “fallback,” and “alarm” count only when the same sentence also contains the audited scenario anchor, and retained evidence includes the exact anchor span. The matcher searches past earlier unrelated occurrences, so smoke, economizer, or proof language cannot be silently reused as unoccupied or sensor-failure evidence.
- Decision/outcome coverage for custom programs, including boolean logic and switch selectors, so reviewers can see passing assertions that still leave one side of an interlock or branch untested.
- A whole-building `ProjectSpec` workflow for multiple equipment jobs and explicit topology relationships. It preflights every item, builds and tests every equipment program, binds them into one project digest, requires named human approval, and exports a deterministic review bundle.
- Typed cross-equipment signal bindings execute a complete project in topological scan order, feed exact upstream outputs into downstream inputs, require independent multi-phase project acceptance tests, and compile into exact offline Niagara station links without double-driving a target.
- A bounded plan → test → diagnose → revise agent loop. The included sequence-pack planner passes on its first attempt; a seeded-defect regression test proves that a planner can repair and retest without bypassing graph validation.
- Niagara `.bog` generation through pinned `pybog==0.1.6`.
- Contractor Niagara environment packs: a ZIP can declare exact Niagara/runtime versions, proprietary or vendor `.jar` modules, palettes, typed component slot contracts, config-to-property mappings, and graphics templates. BACTalk rejects undeclared files, traversal, hash mismatches, unknown modules, and uncontracted custom types; it never executes uploaded Java. Any exact IR behavior can compile to one uniquely declared custom component with exact physical slots and parameters; ambiguous or missing implementations fail closed.
- Exact source generation now covers CDL `PID`, `PIDWithReset`, `Hysteresis`, `TrueDelay`, `TrueFalseHold`, `Latch`, `Timer`, `MovingAverage`, `FirstOrderHold`, `FallingEdge`, `SampleTrigger`, `Sampler`, `TriggeredSampler`, `UnitDelay`, warning-level `Assert`, the plant first-scan `Initialization` and resettable-timer primitives, and both common `TrimAndRespond` variants. The `have_hol=true` variant has a typed hold input, minimum hold duration, and sample-boundary release; its interpreter and generated Java match the 44-block expanded pinned LBNL source in Open Control Engine across a 17-point hold/release trajectory. An explicit `host_tick_v1` generator also covers `Pre` as a sampled Niagara scan projection without claiming Modelica same-time event iteration. Each generator emits deterministic Niagara ProgramObject source, typed slots, and a dependency-free Java qualification kernel. Imported temporal blocks carry explicit semantic contracts so similarly shaped generic blocks cannot enter this lane. A package is refused if even one target exactness blocker lacks an explicit generator/profile. Generated source still requires licensed Workbench compilation and runtime/timing parity evidence.
- A source-bound, resumable audit of all 241 pinned G36 Modelica files. Of the 116 non-validation sequence/source models, 28 currently lower completely to exact typed IR and nine use only qualified stock Niagara targets; the other 19 produce complete deterministic ProgramObject source packages, so all 28 translated models have a source-level target path. Configured controllers with a complete target can now enter the same point-contract, independent-test, review, approval, and export workflow through `LBNL_G36_CONTROLLER`; incomplete controllers fail closed during planning. Eighty-four additional models explicitly request missing job-specific design parameters rather than being mislabeled as translator failures. Four translated models remain blocked from the exact lane only by Modelica `pre()` event-iteration semantics; each has an explicit, non-equivalent `host_tick_v1` sampled-scan package when that deployment profile is knowingly selected. There are zero current CXF/elaboration failures. Fixed component arrays, indexed boundaries, Boolean/real vector filters and replicators, reductions, matrix gains, and limiters are scalarized with strict dimension and mask checks. Separately emitted composite classes are now assembled with exact parent-scope parameter binding and independently resolved through Open Control Engine before projection to flat typed IR. The configured multizone VAV AHU expands 14 composite instances across 13 classes and two levels, prunes 310 guard-inactive nodes, validates 407 OCE blocks with zero warnings, lowers to 566 typed blocks, and produces a complete 55-ProgramObject source target; all 19 public outputs match OCE at the retained regression sample. Source-level target completion is not licensed Niagara runtime qualification.
- Typed G36 job parameterization: the API exposes each controller's public parameter names, types, required/default state, units, quantities, descriptions, and override eligibility. Missing CXF enum declarations are recovered only from the exact pinned root Modelica source; enum overrides must match their declared type. Scalar, array, and matrix job values are type-checked and encoded deterministically. Translation, execution, and ProgramObject packaging accept only root declarations, reject unknown/final/type-invalid values, and bind the chosen design values before OCE validation. Controllers with intentionally required design inputs therefore remain fail-closed in the generic audit but are usable for configured jobs.
- A product-wired LBNL plant-controls API and contractor-job lane over all 73 pinned `Buildings.Templates.Plants.Controls` source models. All 38 non-validation controls pass the retained configured product audit and can now enter the normal point-contract, acceptance-test, immutable review, approval, and export workflow through `LBNL_PLANT_CONTROLLER`. Stock-only models emit `.bog`; stateful models emit exact ProgramObject source, slots, complete graph, and wiring plan and are explicitly labeled as requiring licensed Workbench compilation. Coverage includes plant enable/disable; heat-recovery-chiller enable, mode, and parent control; plant reset and minimum-flow control; local/remote differential-pressure control; dedicated, headered, fixed-speed, variable-speed, and runtime-rotated pumps; stage availability, stage index, stage change, stage completion, equipment availability, equipment enable, event sequencing, load averaging, and failsafes; typed utility/reduction/placeholder blocks; and the complete air-to-water heat-pump plant supervisor. The air-to-water controller composes mode enabling, fixed/alternate staging, lead/lag rotation, valve and pump proof, plant reset, primary and secondary pump control, primary-only minimum-flow bypass, and optional sidestream heat recovery for heating-only, cooling-only, reversible, primary-only, primary-secondary, headered, and dedicated configurations. `make plant-job-contract` proves a real 25-point contractor job through a 480-block/715-link graph, all 12 outputs, 59 deterministic Niagara ProgramObjects, export denial before approval, and signed export after approval. A dual-loop heat-recovery topology contains about 1,200 typed blocks and 143 ProgramObjects. This is source-package completion, not licensed Niagara runtime or field qualification.
- A pinned Apache-2.0 Rumoca compiler path exposed through the G36 API. It resolves, instantiates, and emits flattened JSON IR for selected G36 models against pinned BSD-3-Clause MSL 4.1.0; full-controller conditional elaboration and flat-IR-to-BACTalk lowering remain explicit gates.
- Exact Niagara point binding: point schedules may supply `niagara_ord`/`station_ord` and `niagara_write_priority`. BACTalk emits a signed link plan, readback contract, and Niagara SDK installer source that wires existing proxy points to the imported program, refuses missing slots, and never overwrites a conflicting target link.
- Boolean and numeric weekly schedules compile into real Niagara `sch:*Schedule` components and link to typed control inputs; overlapping periods and unsupported holiday/special-event lowering fail closed, while station-timezone/runtime parity remains gated.
- Fixed-interval numeric and boolean history requirements compile into real Niagara `history:*IntervalHistoryExt` children with interval and rolling record capacity derived from retention days. COV serialization and licensed-runtime behavior remain gated.
- A pinned Open Control Library integration: all 137 CXF fault routines across 14 equipment families import into typed IR and pass their upstream vectors; 113 also compile to non-empty stock-block Niagara `.bog` files. The other 24 remain fail-closed at the Niagara boundary pending runtime-qualified temporal lowering.
- A pinned MIT Niagara ProgramObject library with 20 `.bog` archives and 36 inspectable ProgramObjects for G36, central plants, scheduling, FDD, and optimization. Archive integrity, source hashes, compiled-class presence, and dependencies are exposed without claiming licensed runtime qualification.
- Tier-1 closed-loop tests for occupied cooling, occupied heating, unoccupied shutdown, limits, and alarm gating.
- A local review UI with wiresheet visualization, test evidence, point mapping, changes, approval, and `.bog` or source-package export.
- A signed contractor review package containing the target artifact, exact source uploads, point-map CSV, Brick/tag data, alarm and schedule requirement manifests, vendor-neutral graphics data, engineering summary, provenance, and deterministic test evidence. The package exposes target gaps rather than treating review data as deployed Niagara objects.
- Versioned deliverable requirements for alarm class/priority/delay/routing, IANA-timezone weekly schedules, fixed-interval or COV histories, graphics views, and shop profile conventions, with cross-references validated against the job points.
- Approval-hashed, observation-only VOLTTRON Platform Driver artifacts for every imported BACnet scan; all registry points are forced read-only.
- An executable, loopback-only fake-building package for every imported BACnet scan. BACpypes3 hosts virtual analog, binary, and multistate devices; BAC0 independently reads them; mapped acceptance phases inject sensor values and capture controller commands over real BACnet/UDP. Reviewed valve and damper bindings can now couple a writable BACnet command to dynamic position feedback and open/closed proofs with asymmetric stroke times, travel limits, fail position, command deadband, leakage, nonlinear flow characteristic, persistent mismatch alarms, command-loss behavior, stuck position, feedback bias/freeze, and proof-switch faults. A separate fail-closed protocol-capacity harness creates a synthetic campus, verifies every identity with targeted Who-Is/I-Am, polls every point with ReadPropertyMultiple, performs priority-8 writes with readback, qualifies confirmed COV subscriptions and synchronized change bursts, takes one controller offline, and proves restart recovery. The retained development-host profile passes 500 controllers, 10,000 points, 1,000 batched polls/20,000 property reads, 500 writes, 100 confirmed subscriptions, and two 100-notification COV bursts with zero errors in 49.38 seconds. Every scan also projects into the pinned MIT [BACnet Simulator](https://github.com/quentinnippert/bacnet-simulator) as an independent priority-array, relinquish, COV, scenario, offline-recovery, and REST-observation oracle. Its 66 selected upstream tests plus BACTalk's device/object projection contract pass. Source addresses are never bound and live routes are forbidden; routed broadcast discovery, BBMD/BACnet-SC, larger/longer COV loads, exact MS/TP, licensed Niagara capacity, high-fidelity networks, and HIL remain separate qualification gates.
- Product adapters and real contracts for Haxall/Xeto, Phable, PNNL ConStrain, Open-FDD, BuildingMOTIF, Open Control Engine, modelica-json/CDL, LBNL ctrl-flow system configuration, pyfunnel, BACpypes3/BAC0, the independent BACnet Simulator, VOLTTRON, a locally executed BOPTEST building-physics runtime, a hardened Alfalfa v1.0.0 whole-building FMU runtime with complete typed graph mapping, command/feedback proof, and a real loopback BACnet/IP control boundary, and LBNL DFLEXLIBS reference controls.
- Native Open Control Engine execution of stateful CXF/G36 trajectories, with explicit typed inputs, monotonic simulation time, selected output capture, and bounded scenario admission—not merely source parsing.
- A sparse, source-only MIT AixOCAT integration with 211 typed IEC 61131-3 control/equipment patterns. Six common scaling, manual override, deadband/dead-zone, timed mutual-interlock, and hydronic heating-curve patterns are source-bound, behavior-tested, lowered to typed IR, and Niagara-target compiled; unmapped Structured Text remains fail-closed.
- A pinned BuildingMOTIF catalog with real expansion of G36, chiller-plant, and ASHRAE 223P semantic equipment templates.
- A capability/evidence UI that distinguishes discovered, installed, executable, product-wired, target-compiled, verified, field-qualified, and production-supported stages.
- A role-separated Cerebras workflow when `CEREBRAS_API_KEY` is present in `.env`: `gpt-oss-120b` handles contractor conversation and routing, while `qwen-3.8-27b` is the proposal-only coding model. Coding proposals pass deterministic gates, inherit source evidence, record parent/child lineage, expose exact graph diffs, and become separate candidates that a named engineer can approve or reject.
- An AI-custom intake lane for equipment without an installed deterministic pack: the contractor supplies the real sequence, points, and engineer-authored acceptance tests; Cerebras drafts the first complete typed graph and may repair it against those immutable tests, while the normal compiler, evidence, and approval gates remain authoritative. For pinned plant-library jobs, AI changes are constrained to the controller's declared parameter schema; the model cannot rewrite the expanded topology, and every proposal is rebuilt and retested as a separate candidate.
- An immutable approval gate: export is refused until a named human approves the exact SHA-256-addressed artifact. Changing the graph, report, `.bog`, or ProgramObject source package invalidates export.
- No endpoint or code path that writes to a live building.

## Quick start

### Minimal install

A base install is a supported configuration. It needs only Python 3.11+ and
gives you the whole contractor workflow -- intake, typed graph generation,
deterministic tests, review, approval, and export -- with the optional
simulation and AI capabilities reported as unavailable rather than crashing.

```bash
make install            # ~2 minutes, ~400 MB
make test-minimal       # the tier that must pass on a base install
make demo
make serve              # http://127.0.0.1:8000
```

### Full install from a clean clone

`make bootstrap-full` reconstructs the entire pinned stack from
`ops/stack.lock.json`: it clones every selected upstream at its exact locked
revision, verifies licenses and digests, applies the tracked patches under
`ops/`, builds the Rust and Node helpers, creates the isolated Python
environments, and installs the frontend toolchain. It is idempotent -- rerun
it any time and it skips what is already installed.

```bash
make doctor             # what this machine has, and how to fix what it lacks
make bootstrap-full     # ~30-60 minutes on a warm network, ~9 GB installed
make doctor             # confirm every selected capability is ready
make test-integration   # everything that does not need containers
```

Prerequisites, and what each unlocks:

| Prerequisite | Needed for | Install |
| --- | --- | --- |
| Python 3.11+ | everything | your platform's package manager |
| Node.js 20+ and npm | frontend, ctrl-flow, modelica-json, Haxall | <https://nodejs.org> |
| Rust with `rustup` | Open Control Engine runner, Rumoca flattener | <https://rustup.rs> |
| JDK with `javac` | compiling generated ProgramObject qualification kernels | `apt install default-jdk` |
| Maven | building modelica-json's Java parser for the ctrl-flow lane | `apt install maven` |
| `libudev-dev`, `pkg-config` | the Rumoca build (Linux only) | `apt install libudev-dev pkg-config` |
| Container runtime + registry access | BOPTEST and Alfalfa simulation tiers | Docker Engine or Colima |

`make doctor` checks all of these and prints the exact remediation for
anything missing, so run it first on a new machine.

### Expected time and storage

| Step | Time | Disk |
| --- | --- | --- |
| `make install` | 1-3 min | ~400 MB |
| `make bootstrap-full` | 30-60 min | ~9 GB installed; allow ~20 GB free, since the Rust builds peak higher before their caches are cleaned |
| `make test-integration` | 8-15 min | - |
| `make suite-contract` | 25-40 min | - |
| BOPTEST / Alfalfa images | 20-60 min | ~20 GB additional |

Measured on a 4-core Linux host: `.vendor/` 5.9 GB, the five virtual
environments 2.3 GB, `node_modules` 464 MB, Rust build output 69 MB.

Nothing `bootstrap-full` downloads is committed: `.vendor/`, every virtual
environment, and `node_modules/` are ignored by git. A clean clone plus
`make bootstrap-full` is the only supported way to rebuild the stack.

### Running and proving the whole stack

```bash
make full-stack-up      # queue, RQ worker, API, and physics services if available
make full-stack-smoke   # prove each integration by making it do real work
make full-stack-down
```

`full-stack-smoke` reports each integration as `ready`, `blocked`, or
`missing`. A `blocked` result records an external constraint -- no container
registry, no licensed runtime -- and is never counted as a pass.

To prove the contractor workflow end to end through the real HTTP API:

```bash
.venv/bin/python scripts/verify_contractor_workflow.py
```

It uploads a real point schedule and sequence document, builds and tests a
candidate, checks that export and the review bundle are refused before
approval, approves one exact digest, downloads the approved artifact and
review bundle, and proves that tampering with a signed artifact invalidates
the approval.

### Test tiers

| Command | Tier | Requires |
| --- | --- | --- |
| `make test-minimal` | base install only | `make install` |
| `make test-integration` | everything except containers and licensed runtimes | `make bootstrap-full` |
| `make test-docker` | BOPTEST/Alfalfa physics | container runtime with registry access |
| `make test-all` | both of the above | all of the above |

A minimal install reports optional integrations as unavailable; it must never
crash. After `make bootstrap-full` the vendor-dependent tests execute rather
than skip: `make test-integration` sets `BACTALK_REQUIRE_FULL_STACK=1`, which
turns a missing requirement into a failure instead of a silent skip. Use
`make test-integration-lenient` on a partially bootstrapped machine.

The browser suite drives the real API and is run separately:

```bash
cd web && npx playwright test
```

On a machine where browsers were provisioned out of band, set
`PLAYWRIGHT_BROWSERS_PATH` (or `BACTALK_CHROMIUM_PATH` for an exact binary)
and the config will use them instead of downloading.

### Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `ModuleNotFoundError` for an optional package | That extra is not installed. `GET /api/system/optional-capabilities` lists each one and its install command; `make bootstrap-full` installs them all. |
| A capability returns HTTP 503 with a `remediation` field | Working as designed on a partial install: the response names the extra to install. |
| `checkout is not at the pinned revision` from `make doctor` | A vendored tree drifted. Rerun `make bootstrap-full`, which re-checks out the locked revision. |
| `tracked patch does not apply cleanly` | Upstream moved under a pin. Re-pin the component in `ops/stack.lock.json` and regenerate the patch under `ops/`. |
| Rumoca build fails in `libudev-sys` | Install `libudev-dev` and `pkg-config`, then rerun `make bootstrap-full`. |
| ctrl-flow parser tests fail with `Cannot read properties of undefined` | The parser jar is missing (install Maven and rerun `make bootstrap-full`), or a JVM banner is corrupting its output. `JAVA_TOOL_OPTIONS` set in your environment causes the latter; the contract unsets it for that call. |
| OCE runner fails with `requires rustc 1.97` | Run `make bootstrap-full`, which installs the pinned toolchain via rustup. |
| `denied` or `403` pulling container images | Your network blocks the registry. The BOPTEST/Alfalfa tiers cannot run there; everything else still works. `make doctor` reports this as `blocked`. |
| Queue will not start | `make queue-up` prefers the pinned container and falls back to a loopback-only native `redis-server`. Install one with `apt install redis-server`. |
| A pinned revision no longer resolves | Run `.venv/bin/python scripts/verify_lock_resolves.py` to see which upstream dropped the commit. |

For AI programming, copy `.env.example` to `.env`, add the Cerebras key locally, and keep the two roles separate. `CEREBRAS_CHAT_MODEL=gpt-oss-120b` talks to the contractor; `CEREBRAS_CODING_MODEL=qwen-3.8-27b` writes and repairs typed control-graph proposals. Verify model entitlements, strict schemas, the coding pipeline, and chat isolation with `make cerebras-smoke`.

Open [http://127.0.0.1:8000](http://127.0.0.1:8000), click **Build demo job**, inspect the graph and test results, enter a reviewer name, and approve the artifact. Generated runs live under `.bactalk/runs/` and are ignored by git.

The enterprise UI rewrite is available side-by-side at [http://127.0.0.1:8000/next/](http://127.0.0.1:8000/next/). It guides a contractor through scope and source-package intake, performs real point normalization and mapping preflight, and opens retained candidates in a typed wiresheet, deterministic Test Lab, multi-fidelity Simulation Lab, Graphics Studio, and digest-bound Review & Release workspace. The Test Lab distinguishes normal passing behavior from fault qualification, flags candidates with no injected failures, and exposes each injected fault as raw value → effective value/quality → controller response plus credited recovery phases. `/next/projects/new` is the complete whole-building lane: upload one coordinated project contract plus an optional/required contractor station `.bog`, inspect every equipment pack and topology contract in server preflight, compile and test all child programs, execute cross-program acceptance phases, atomically assemble the station, review the system topology and artifacts, sign the exact project digest, and download one approved station bundle. Whole-building projects expose equipment topology and cross-program evidence; the library, environment, and administration workspaces expose installed OSS, contractor Niagara inputs, maturity stages, blockers, and audit integrity. The Library workspace includes a live LBNL system configurator: applicable choices update through the real ctrl-flow interpreter, the UI renders the resulting components/points/tests/blockers, an uploaded CSV/XLSX points list is reconciled against that exact design, and an uploaded sequence document produces a scenario-by-scenario facet matrix with missing language and evidence excerpts. Global search and the AI launcher route directly into retained programs. The release workspace verifies the signed artifact set on the server, inventories every handoff file and SHA-256 digest, distinguishes engineering approval from deployment qualification, and offers separate target and full-review-bundle downloads. A connected AI controls-engineer drawer keeps conversation and coding roles visibly separate and presents every proposed change as a new tested candidate. The existing workbench remains at `/` while each proven workflow is migrated, so no controls capability is removed during the transition. To develop and verify the React/TypeScript frontend:

```bash
make web-install
make web-build
make web-test
make web-lint
make web-sbom
```

The build regenerates TypeScript API types from FastAPI's OpenAPI document before compiling. Browser tests cover desktop and tablet layouts, the real intake-normalization path, the legacy workbench migration boundary, and automated accessibility checks.

To generate and record the reproducible six-program contractor acceptance workflow, run the server on port 8011 and then:

```bash
make record-demo
```

The workflow uploads an AHU, duct-static PI loop, two VAVs, duty/standby pump pair, and exhaust proof sequence; preflights six installed Niagara-target packs; compiles five topology relationships and one typed cross-program link; exercises stateful cross-equipment proof loss/recovery; drills through the wiresheet, Cerebras explanation, Test Lab, isolated BACnet/IP proof, Graphics Studio, and release evidence; signs the entire building candidate; and downloads the deterministic 200-file station bundle. The ignored recording, approved ZIP, and generated input package are written beneath `artifacts/`.

You can also submit a job directly:

```bash
curl -X POST http://127.0.0.1:8000/api/runs \
  -H 'Content-Type: application/json' \
  --data @examples/vav-reheat-job.json
```

The plant-library job lane uses the same endpoint:

```bash
curl -X POST http://127.0.0.1:8000/api/runs \
  -H 'Content-Type: application/json' \
  --data @examples/plant-hold-job.json
```

## Capability status

Every capability is tracked against the maturity ladder in
[docs/ENTERPRISE-PRODUCTION-GOAL.md](docs/ENTERPRISE-PRODUCTION-GOAL.md). The
live, machine-readable source is `GET /api/system/readiness`; this table is a
summary. Being installed is deliberately not treated as production support.

| Capability | Status | What that means here |
| --- | --- | --- |
| Typed control IR, validation, interpreter | Verified | Passes all 137 pinned Open Control Library vectors; reproducible from a clean clone. |
| Contractor intake, mapping, review, approval, export | Product-wired | Proven end to end by `scripts/verify_contractor_workflow.py` against the real API. |
| Immutable approval and artifact binding | Verified | Approval names one exact digest; a changed artifact invalidates export. |
| Niagara `.bog` and ProgramObject source generation | Target-compiled (offline) | Deterministic source and archives are produced. **Not** compiled or run in a licensed Niagara environment. |
| Deterministic equipment packs | Prototype / qualifying | Bounded VAV reheat, AHU safety, duct-static PI, exhaust proof, two-pump selection, plus the pinned LBNL plant and G36 controller lanes. No pack is field-qualified. |
| BOPTEST / Alfalfa simulation tiers | Product-wired, container-gated | Real physics through pinned services. Requires a container runtime with registry access; blocked networks cannot run this tier. |
| Loopback BACnet/IP lab and capacity harness | Product-wired | Runs on plain loopback UDP with no containers. |
| Durable qualification queue and workers | Product-wired | Pinned container, with a loopback-only native `redis-server` fallback. |
| Semantic and independent verification (Haxall/Xeto, BuildingMOTIF, ConStrain, Open-FDD, Brick) | Product-wired | Each runs real checks behind a process boundary. |
| AI conversation and coding roles | Product-wired, proposal-only | The chat model has no graph field; every coding proposal is revalidated, retested, and approved separately. |
| **Licensed Niagara runtime qualification** | **Not available** | No licensed Workbench or station is bundled, and none of this repository's evidence claims runtime or field qualification. Generated artifacts require licensed compilation and station testing outside BACTalk. |

## Safety boundary

The execution pipeline is intentionally one-way:

```text
job inputs -> typed IR -> static validation -> target builder -> simulation
                                                |              |
                                                v              v
                                      .bog or source package  test report
                                                |
                                                v
engineer review -> artifact-bound approval -> download for manual Workbench import
```

The approval is bound to the graph, target artifact, and test-report hashes. BACTalk does not deploy, enable, or command live equipment. Hardware-in-the-loop and live BACnet capabilities must remain separate, explicitly configured test modes with their own interlocks.

## Architecture

The central contract is `ControlGraph`, not generated Python or Niagara XML. An AI planner will be allowed to propose this IR, while deterministic validators and compilers remain in control of what becomes an artifact. This also keeps Niagara, BOPTEST, and other targets replaceable.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/INTEGRATION-STATUS.md](docs/INTEGRATION-STATUS.md), [docs/NIAGARA-ENVIRONMENT-PACK.md](docs/NIAGARA-ENVIRONMENT-PACK.md), [docs/VOLTTRON-EVALUATION.md](docs/VOLTTRON-EVALUATION.md), [docs/ROADMAP.md](docs/ROADMAP.md), and [docs/OSS-REVIEW.md](docs/OSS-REVIEW.md).

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/runs` | Validate, compile, and test a submitted job |
| `POST` | `/api/intake/inspect` | Normalize points and inspect sequence documents without starting a build |
| `POST` | `/api/runs/import` | Build from contractor point, sequence, BACnet, Niagara-template, and environment-pack uploads |
| `POST` | `/api/projects/preflight` | Validate multi-equipment topology and installed build coverage |
| `POST` | `/api/projects/build` | Build and test every program in a multi-equipment project |
| `POST` | `/api/projects/build-import` | Build all programs and atomically assemble a supplied contractor station BOG |
| `POST` | `/api/projects/{id}/approve` | Approve the exact whole-building artifact set |
| `GET` | `/api/projects/{id}/export` | Download the reviewed project bundle; approval required |
| `POST` | `/api/runs/demo` | Build the synthetic example job |
| `GET` | `/api/capability-packs` | Read truthful equipment-pack and artifact coverage |
| `GET` | `/api/capability-packs/{id}/release-gates` | Read every passed and blocking production gate for a pack |
| `GET` | `/api/system/readiness` | Read integration stages and explicit blockers |
| `GET` | `/api/system/optional-capabilities` | Read which optional extras are installed and how to add the rest |
| `POST` | `/api/translate/cxf` | Lower ASHRAE 231P CXF into typed IR and optionally replay vectors |
| `POST` | `/api/execute/cxf` | Execute a bounded typed/stateful CXF trajectory in Open Control Engine |
| `GET` | `/api/library/g36/controllers` | Browse the allowlisted LBNL Guideline 36 controller source catalog |
| `POST` | `/api/library/g36/controllers/{id}/translate` | Translate a selected G36 controller to CXF and validate it in OCE |
| `GET` | `/api/library/g36/controllers/{id}/parameters` | Inspect typed required/default G36 design parameters before translation |
| `POST` | `/api/library/g36/controllers/{id}/flatten` | Resolve and flatten a selected G36 controller with the pinned Rumoca/MSL toolchain |
| `POST` | `/api/library/g36/controllers/{id}/execute` | Execute a selected G36 controller through its public named interface |
| `POST` | `/api/library/g36/controllers/{id}/niagara-program-package` | Download exact non-stock ProgramObject source, slots, manifest, and Java parity kernel |
| `POST` | `/api/sequence-oracle-approvals/{id}/candidate-preflight` | Verify the immutable sequence/points chain, lower and bind a reference candidate, and replay every approved oracle without authorizing deployment |
| `GET/POST` | `/api/library/plant-controls/controllers...` | Catalog, parameterize, translate, execute, or package proven LBNL plant controllers |
| `POST` | `/api/library/plant-controls/controllers/{id}/job-template` | Generate the exact point-list CSV and acceptance-output contract for a configured plant controller |
| `POST` | `/api/library/g36/controllers/{id}/job-template` | Generate the exact point-list CSV and acceptance-output contract for a configured G36 controller |
| `GET/POST` | `/api/library/aixocat/patterns...` | Browse typed Structured Text patterns or lower reviewed patterns to verified IR |
| `GET/POST` | `/api/library/open-control/faults...` | Catalog or translate 137 pinned executable fault routines |
| `GET` | `/api/library/niagara-programs...` | Catalog or inspect pinned Niagara ProgramObject source |
| `GET/POST` | `/api/semantics/buildingmotif/...` | Catalog or instantiate pinned semantic templates |
| `POST` | `/api/verify/haxall` | Validate a Haystack/Xeto graph |
| `POST` | `/api/verify/constrain` | Run an isolated ConStrain rule |
| `POST` | `/api/verify/open-fdd` | Run an Open-FDD rule |
| `GET` | `/api/runs/{id}/graph` | Read the proposed typed graph |
| `GET` | `/api/runs/{id}/report` | Read test evidence |
| `GET` | `/api/runs/{id}/deliverables` | Read generated artifact coverage and explicit target blockers |
| `GET` | `/api/runs/{id}/release-summary` | Re-hash the retained candidate and read its signed release, download, and safety contract |
| `GET` | `/api/runs/{id}/volttron-manifest` | Read the observation-only edge artifact manifest |
| `GET` | `/api/runs/{id}/bacnet-lab-manifest` | Read the executable isolated fake-building manifest |
| `GET` | `/api/runs/{id}/environment-manifest` | Read the validated contractor Niagara environment and compatibility report |
| `GET` | `/api/runs/{id}/station-assembly` | Read offline station insertion/replacement and handle-rebase evidence |
| `POST` | `/api/runs/{id}/approve` | Approve the exact artifact hash |
| `POST` | `/api/runs/{id}/reject` | Reject and retain a candidate with a named audit decision |
| `GET` | `/api/runs/{id}/export` | Download the `.bog` or ProgramObject source package; approval required |
| `GET` | `/api/runs/{id}/review-bundle` | Download all signed contractor inputs and outputs; approval required |

FastAPI also exposes interactive API documentation at `/docs` before the root static mount in development integrations. The existing product UI is served at `/`; the progressively migrated enterprise interface is served at `/next/`.

## Important limitations

- The stock-block compiler covers 113/137 pinned Open Control Library routines. Exact IR execution covers all 137; moving averages, periodic samplers, unit delays, and numeric change detection require the separately gated ProgramObject/custom-module target lane before Niagara deployment. Every supported Niagara version still needs licensed runtime fixtures and qualification.
- G36 SupplySignals now has an exact typed/executable lowering. Its stock-block portion target-compiles, but stock `kitControl:LoopPoint` is deliberately rejected for `PIDWithReset` because reset, `Ni` anti-windup, and `Nd` derivative semantics differ. A typed contractor component can complete the `.bog`, or BACTalk can generate reviewable ProgramObject source; neither path is runtime-qualified until licensed Workbench compilation and trajectory replay pass.
- Whole-building intake/build/export can execute typed cross-equipment signals, test independent multi-phase project acceptance cases, emit separately tested `.bog` programs, and atomically insert/replace and link them in one contractor station template with collision checks and handle rebasing. High-fidelity whole-building physics and licensed whole-station execution are not complete.
- VAV-reheat, AHU safety/cooling, AHU duct-static PI, exhaust-fan proof, two-pump selection, and contractor-supplied typed graphs have compiler paths. They are prototypes, not field-qualified packs; the equipment-family matrix deliberately marks the rest as discovered until complete packs exist.
- AI-custom intake can draft beyond installed packs, but it intentionally requires an independently authored acceptance oracle and still cannot claim equipment-family support or field qualification. AI-generated tests are not accepted as proof of the AI-generated program.
- The local plant is meant to catch sign, enable, wiring, clamping, and basic response defects. It is not a physical validation or a substitute for BOPTEST.
- BOPTEST now runs locally through Colima/Docker with digest-pinned Redis and MinIO dependencies. Beyond the service smoke, `BoptestGraphRunner` checks a complete explicit mapping, feeds live FMU measurements into a typed BACTalk graph, bounds every override against BOPTEST metadata, advances the physical model, retains KPIs, and always stops the test case. Simulation Center authors the fail-closed contract visually: every typed graph boundary, unit transform, activation channel, external-clock horizon, native peak/typical-day and energy-price condition, seeded weather uncertainty, expected controller/building trajectory, and pyfunnel tolerance is reviewed before deterministic canonical JSON is generated. Contractors can stage up to 50 independently scored operating conditions as one acceptance matrix, while retaining a shared reviewed model boundary. Scenario requests are read back from BOPTEST exactly; a mismatch fails before physics steps. Imported shop contracts are rehydrated into the same form and rechecked against a freshly inspected model boundary. Duplicate mappings, activation collisions, unadvertised signals, incomplete trajectories, invalid timing, nonfinite values, duplicate case IDs, and ambiguous single-run/suite requests cannot be queued. BOPTEST qualification uses the same RQ/Valkey job plane, external spawn worker, heartbeat lease, global matrix progress, cancellation, and orphan failure semantics as Alfalfa. Each queued request is bound to the exact pre-qualification candidate digest; a worker refuses a candidate that changed while waiting. pyfunnel grades explicitly supplied independent trajectories on an elapsed-time clock, so nonzero model/scenario dates cannot misalign the oracle; one failing oracle in any condition blocks the entire candidate, and all case evidence plus pyfunnel CSVs enter the run's signed digest and review bundle. A failed oracle also retains a signed minimal counterexample with its violation span, peak error, and bounded trajectory context; Simulation Center renders it directly and the integrity-checked summary is supplied to both AI roles for a repair proposal without letting the model grade its own work. Passing BOPTEST and Alfalfa tiers may accumulate sequentially on the same candidate; neither overwrites the other's evidence, and the evolving combined digest is what the human approves. `make boptest-graph-runtime` proves the complete queued contractor lane. `make boptest-scenario-runtime` proves a live `bestest_air` peak-cooling day with dynamic price and seeded weather uncertainty. `make boptest-scenario-suite-runtime` proves peak-cooling and peak-heating days sequentially in one durable job, including exact scenario readback, native model warmups under a bounded long-call timeout, changing room temperatures in both cases, independent passing oracles, signed qualification, approval, and export. `make boptest-scale-runtime` remains a separate concurrent capacity gate. Production equipment-specific maps, authoritative long-horizon reference suites, real human review, and licensed Niagara attachment remain.
- BOPTEST model discovery is product-wired rather than hard-coded. Simulation Center reads the running service's advertised test cases, selects a reviewed case only long enough to inventory its exact measurements, inputs, units, bounds, descriptions, and activation signals, and then requires a clean stop without initialization or model advancement. Those exact signals populate visual graph-input, command, activation, simulation-horizon, and multi-oracle trajectory controls; canonical JSON is now an audit view rather than a required authoring surface. The retained `make boptest-graph-runtime` evidence currently finds 12 installed cases and inspects `bestest_air` as 31 measurements and eight inputs before running qualification.
- Alfalfa qualification is now a first-class contractor workflow rather than a standalone runtime demonstration. A passing candidate can upload a job-specific `.fmu` through Simulation Center, where BACTalk validates and inspects its FMI metadata without executing model code, shows its declared inputs/outputs, units, bounds, platform, and digest, and provides a reviewed visual mapper for every typed graph input and output. An existing mapping JSON can still be imported. The reviewer must also define at least one acceptance oracle for a graph or FMU signal; expected values, sample times, and tolerances are explicit rather than generated by the controller under test. Simulation Center submits the FMU and contract to a durable RQ/Valkey job plane, then shows retained worker identity, phase/step progress, input digest, terminal result, failure detail, and cooperative cancellation without keeping the web request open. The exact FMU and request are persisted before dispatch and re-hashed by the worker; changed inputs fail visibly. BACTalk requires exact boundary coverage, bounds every command, advances on the external clock, verifies mapped command echoes, requires a clean stop, grades every trajectory with pyfunnel, and atomically signs the FMU, complete trajectory, comparison CSVs, and any minimized failure counterexample into the candidate digest and review bundle. Any failed or incomplete oracle marks the run failed and blocks approval/export. When the job includes a BACnet scan, the reviewer can select the BACnet/IP transport: BACTalk derives a fresh-port runtime fixture from the signed scan, injects every FMU measurement into its exact virtual object, makes the graph controller read it over real loopback UDP, writes every graph command at priority 8, requires protocol readback, and only then applies the command to the FMU. The retained evidence distinguishes this BACTalk GraphInterpreter controller from a licensed Niagara runtime. Simulation Center exposes model/graph hashes, every trace, protocol transaction count, command feedback, tick-zero substitutions, timing, oracle results, and minimized failures without implying Niagara or field qualification. `make qualification-queue-up alfalfa-product-smoke` proves the complete queued product boundary against the real retained whole-building FMU: read-only inspection of 49,669 declared variables, normal candidate creation, denied pre-approval export, immutable multipart FMU/map admission, external worker execution, five closed-loop minutes across 29 runtime inputs and 95 outputs through real BACnet/IP reads, priority writes, and readbacks, independent zone-temperature trajectory acceptance within 0.05 K, evidence retrieval, explicit test-identity approval, and approved artifact/review-bundle export.
- Point discovery is represented in the job schema, but active BACnet scanning is not enabled in this milestone.
- Imported scans now produce real loopback BACnet/IP devices and an automatic scenario/result-capture runner. MS/TP-origin identities can be mirrored through BACnet/IP, but exact token passing, baud, routers, and electrical behavior still require a serial hardware-in-loop lane.
- Proprietary modules, palettes, and graphics can be ingested, signed, statically checked, and used through explicit typed component contracts. Contractor PX templates compile with complete exact-ORD point bindings while preserving the shop's visual standard. BACTalk does not install, render, or execute those assets; exact dependency closure and behavior must pass the licensed Niagara version/runtime matrix before field use.
- BACnet object identifiers alone do not identify an existing Niagara proxy component. Automatic station binding therefore requires an exact reviewed `niagara_ord`; otherwise the package explicitly lists the point as unbound. Generated installer source is not executed by BACTalk and remains subject to licensed-SDK and disposable-station qualification.
- Review-data manifests cover graphics, alarms, histories, schedules, and tags. Boolean/numeric weekly schedules and fixed-interval numeric/boolean histories compile into the `.bog`. Alarm and nHaystack semantic-tag installers are emitted as deterministic, collision-denying Niagara SDK source with exact component ORDs. Contractor PX templates compile into signed `.px` files with complete exact-ORD binding contracts. None are executed by BACTalk. Holiday/special-event calendars, COV histories, complete station hierarchy, and exact licensed-runtime execution remain roadmap work.
- VOLTTRON is pinned as a separate Python 3.11/Linux edge profile. Current modular releases are pre-stable and are not a live-write safety authority.
- This repository is technical work, not legal advice; dependency and standards licensing should receive counsel review before commercial distribution.
