# Architecture

## Design rule

An AI model never writes a live device and never bypasses deterministic validation. It proposes a typed intermediate representation (IR). Every edge in the IR has a known source and destination type, and each target input has exactly one driver.

## Pipeline

1. **Ingest** — points, sequence selection, shop settings, template reference, BACnet scan, and optional contractor Niagara environment pack are normalized and content-addressed.
2. **Plan** — a sequence pack or AI planner emits `ControlGraph` plus traceable assumptions. For supported system templates, the ctrl-flow adapter first invokes the pinned upstream Linkage Schema interpreter to expose only currently applicable engineering choices, reject invalid selections, and retain evaluated configuration evidence. A deterministic product binding then expands the selected AHU or terminal configuration into components, conditional point requirements, required fault/safety/recovery scenarios, the exact matching LBNL G36 controller, installed capability candidates, and release blockers. Contractor points are reconciled against that conditional contract. Sequence prose is separately reconciled against every scenario, with excerpt evidence, and its thresholds, units, timing, actions, policies, and clause relationships are emitted only as unapproved structured candidates; ambiguous point bindings and vague terms remain blocking. Those choices and candidates do not become executable logic until an engineer approves a normalized requirement set, independent test oracles are generated, and a verified controller/target lane consumes them.
3. **Validate** — Pydantic schema validation and graph invariants reject malformed or unsafe topology.
4. **Compile** — `NiagaraCompiler` maps exactly supported IR to stock Niagara blocks through pybog. A contractor environment may implement any IR behavior with a declared proprietary component only when its module, type, logical behavior, typed slots, physical Niagara slots, static properties, and config-to-property mappings form a complete contract. Unsupported behavior auto-selects only one exact candidate; ambiguity fails closed. For exact non-stock PID and temporal behaviors, BACTalk can alternatively emit ProgramObject source, slot definitions, and independently compilable Java parity kernels, but never fabricates compiled Niagara bytecode. Initialization-sensitive primitives require an explicit source semantic contract; no approximate lowering is allowed.
5. **Test** — Tier 1 interprets the same IR against a deterministic plant. Every scan can also become a loopback-only BACpypes3 fake building; its runner drives mapped inputs and captures controller outputs over BACnet/UDP. Tier 2 runs the pinned BOPTEST service locally. `BoptestGraphRunner` requires a complete explicit graph-to-FMU map, feeds each measurement snapshot into the same typed IR interpreter, bounds outgoing commands against the advertised BOPTEST inputs, advances the FMU, records KPIs, and stops it in a `finally` path. `WorkbenchService.qualify_with_boptest` executes the exact signed run graph, grades independent trajectory oracles with pyfunnel, atomically appends the runtime evidence and all comparison CSVs, recomputes the artifact digest, and changes the run to failed when any oracle escapes its funnel. The product API exposes both qualification and retained evidence. A retained ordinary contractor run proves changing `bestest_air` state, a zero-error oracle, denied pre-approval export, evidence in the signed review bundle, and approved export under a test identity. Equipment-pack-specific scenario coverage and failure minimization remain. The final tier connects the generated station in a licensed Niagara lab to those isolated buildings.
6. **Package and review** — the UI presents job context, point mapping, wiresheet, exact changes, individual assertions, and signed manifests for tags, alarms, schedules, and graphics intent.
7. **Approve** — a named human approves one exact content hash.
8. **Export** — only an unchanged, approved target may be downloaded: either a `.bog`, or an exact ProgramObject source-and-wiring package that still requires licensed Workbench compilation.

AI changes never mutate their parent run. The contractor-facing conversation model can explain and route a requested change but its schema contains no graph field. A separate coding model drafts or repairs the typed graph and never talks directly to the contractor. A proposal is compiled and tested as a new child candidate with inherited contractor evidence and an exact graph diff. A named engineer either approves that artifact-bound candidate or rejects it into the retained audit trail.

For equipment without an installed deterministic pack, `AI_CUSTOM` intake starts from the contractor's extracted sequence and exact point list. It is allowed only when the request includes engineer-authored acceptance cases. The model proposes and, within a bounded loop, repairs the graph; it cannot alter the test oracle. The resulting first-run proposal records the model, assumptions, and explanation inside signed graph metadata.

Generic acceptance reports also calculate typed decision coverage. Boolean-producing logic blocks and each numeric/boolean switch selector are checked for both outcomes across all scenarios and timeline scans. A passing oracle can therefore still expose untested branches; coverage is evidence, not a substitute for dynamic-building or field qualification.

Acceptance cases also carry typed input-fault contracts. The Tier-1 interpreter can inject force, bias, scale, drift, stuck, stale, dropout, and Boolean-inversion faults at exact scan phases. An optional Boolean quality target is driven invalid separately from the numeric or Boolean process value, so sensor reliability is never inferred from a magic number. Reports retain the raw value, effective value, elapsed fault duration, quality state, explicit output assertions, and later no-fault recovery phases. Fault coverage is an independent release gate: ordinary passing scenarios do not imply fault qualification.

Each installed equipment application can bind a versioned `QualificationProfile`; custom jobs can carry a contractor-owned profile in the signed `JobSpec`. Requirements are classified as required, conditional, or explicitly not applicable and cover categories such as high-pressure shutdown, fire/smoke, freeze protection, invalid/stale sensors, communications loss, actuator proof, unavailable equipment, overrides, restart, rotation, alarms, and recovery. Acceptance cases opt into categories explicitly. The assessor credits only passing tagged cases, verifies required fault injection and recovery mechanics, and leaves every unresolved conditional visible. Completing this engineering matrix does not imply Niagara-runtime, hardware, or field qualification.

Review manifests deliberately distinguish requirements/data from deployed Niagara components. A generated `alarms.json` or `graphics-model.json` is useful contractor evidence, but does not pass the corresponding target gate until a supported compiler emits the Niagara extension/PX object and licensed-runtime evidence confirms it.

Contractor environment packs are treated as untrusted supply-chain input. Archive paths, sizes, declarations, and SHA-256 hashes are checked before extraction. JARs are inventoried as ZIP content but never class-loaded. The original pack, extracted declared assets, normalized descriptor, compatibility report, and generated program are all included in the approval digest. Static compatibility is not runtime qualification.

Point binding is explicit rather than guessed. A BACnet device/object tuple is enough to build a fake device, but it is not an address of a component already installed in a contractor station. When the point schedule supplies an exact `station:|slot:` ORD, the deliverable generator emits a Niagara SDK binder. Inputs link proxy `out` to the program boundary `in16`; outputs link the program boundary `out` to the declared priority input on the proxy. The binder validates both components and slots, treats any different existing target link as a collision, and stops instead of replacing it.

Semantic tagging follows the same fail-closed rule. A shop profile may declare exact Niagara site and equipment ORDs; otherwise the known generated program root is used as the equipment and an undeclared site relationship is omitted. BACTalk emits a Niagara SDK installer using nHaystack's `BHDict` annotation contract. It adds only missing dictionaries, accepts an exact existing dictionary as idempotent, and refuses to overwrite a different contractor dictionary. Runtime-derived tags such as `cur`, value kind, and history state are verified through the expected readback rather than hard-coded into the annotation.

Graphics are template-compiled rather than visually reinvented. A contractor environment pack supplies hash-declared PX XML and each job view names the exact template and point set. Only explicit typed placeholders are replaced; every declared point requires an ORD binding and any unknown point, missing binding, script, DTD/entity, or remote/active URI stops compilation. The generated PX and binding plan join the approval digest. Rendering, navigation installation, module compatibility, and live-value readback remain licensed-runtime gates.

Station assembly is an explicit offline operation, never an implicit overwrite. `compare_only` preserves the original template-analysis behavior. `insert` requires the exact parent component path and refuses a same-name target. `replace` requires the target to exist and refuses replacement if any component outside that subtree holds one of its handles. The assembler carries inherited module declarations, deterministically rebases all generated handles and internal handle references, validates global uniqueness/resolution, preserves unrelated station components, and signs both the assembled BOG and assembly manifest. Project assembly applies the same operation to all independently tested programs in deterministic target-ORD order and emits no partial artifact if a step fails. An approved export returns the assembled artifact when present.

Whole-building execution uses explicit typed signal bindings between equipment boundaries. The project validator rejects missing endpoints, role/type mismatches, multiple drivers, driver collisions with BACnet/ORD/schedule bindings, and equipment cycles. The simulator executes equipment in topological scan order across engineer-authored phases, propagates upstream output values into downstream inputs, and requires every downstream output to be observed by the independent project oracle. Station assembly lowers the same bindings into exact handle-based Niagara links and signs their source/target ORDs, slots, and types.

The fake-building package is deliberately incapable of reaching a field network: generated devices bind only to `127.0.0.1/32`, source addresses are retained as metadata, and the runner accepts only points mapped as injectable inputs while grading only mapped command outputs/values. BACnet/IP behavior is executable. MS/TP device identity can be mirrored over IP, but serial timing and router behavior remain hardware-in-loop work.

`DeliverableRequirements` is the versioned contract between contractor standards and target compilers. It validates alarm classes/priorities/delays/routing, schedule timezones and non-overlapping weekly periods, history mode/retention, graphics point references, and shop conventions against the canonical job points before compilation.

The Niagara compiler currently lowers declared boolean/numeric weekly schedules into `sch:BooleanSchedule` or `sch:NumericSchedule` components and links their output to the corresponding typed input. Holiday/special-event calendars fail closed; the declared IANA timezone remains a deployment assertion until licensed runtime evidence proves station-timezone parity.

Fixed-interval history requirements are lowered from real Niagara 4 examples into numeric or boolean interval-history extensions. Retention days become an explicit rolling record capacity (`ceil(days × 86400 / interval)`); COV histories remain review-only until their collector serialization is qualified, and licensed-runtime acceptance remains mandatory.

## Trust boundaries

| Boundary | Enforcement |
| --- | --- |
| Model output to executable graph | Strict schema plus graph/type validation |
| Contractor conversation to code generation | Distinct role-scoped models and schemas; chat has no graph field, code output is never presented as proof |
| Graph to Niagara | Fixed compiler mapping plus pybog validation |
| Contractor modules to graph/compiler | Hash-verified archive, module/type closure, and exact typed slot contracts; uploaded Java is never executed |
| Point list to existing Niagara proxy | Exact reviewed component ORD, typed graph boundary, explicit command priority, collision-denying installer and readback plan |
| Semantic intent to Niagara tags | Exact site/equipment/program ORDs, deterministic `BHDict` annotations, no overwrite of differing tags, licensed-runtime readback gate |
| Contractor PX template to generated graphic | Hash-declared template, typed placeholders, complete exact-ORD coverage, unsafe XML/content rejection, licensed-runtime render gate |
| Generated program to contractor station BOG | Explicit insert/replace mode, exact existing parent/target, collision and external-reference refusal, deterministic handle rebasing, approval-bound export |
| Temporal IR to Niagara | Explicit target-capability check; no approximate substitution; licensed runtime qualification required for ProgramObject/module lowering |
| Generated ProgramObject source to executable Niagara code | Deterministic source/slot manifest plus Java oracle parity; licensed Workbench compilation and runtime trajectory replay remain mandatory |
| Artifact to reviewer | SHA-256 over graph, target artifact, and report |
| Reviewer to export | Named approval tied to that hash |
| Export to building | Manual Workbench import outside BACTalk |
| Future edge command to transport | Independent default-deny policy kernel; no generated agent owns the write primitive |
| Fake building to field network | Loopback-only bind addresses; imported source addresses are never bound or discovered |

## Target packages

- `domain.py` — durable product contracts and invariants.
- `agent.py` — bounded planner/reviser loop; every revision returns to typed validation and testing.
- `sequences/` — versioned, deterministic sequence packs.
- `compiler.py` — Niagara target adapter.
- `simulator.py` — fast local IR interpreter and plant.
- `integrations/` — BOPTEST, BACnet, CDL/CXF, Brick/Haystack, and template analysis adapters.
- `service.py` — workflow and approval gate.
- `safety.py` — transport-free command authorization kernel for simulation and isolated labs only.
- `api.py` and `static/` — local review application.

## Why not let the LLM generate `.bog` XML?

Raw generation would couple reasoning to a vendor serialization format, make tests difficult, and remove the strongest safety boundary. The IR permits multiple front ends and back ends while keeping type checking, provenance, tests, and diffs deterministic.
