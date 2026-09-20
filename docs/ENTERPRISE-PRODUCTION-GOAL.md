# BACTalk enterprise-production goal

## Objective

Build BACTalk into an enterprise-production, human-gated **program any building**
platform for controls contractors. It must turn heterogeneous contractor inputs into
complete, reviewable, tested Niagara deliverables without implying support for any
equipment, control construct, vendor runtime, or verification layer that has not been
executed and evidenced.

The platform must:

1. Validate that the product solves valuable contractor workflows and continuously
   compare its scope with commercial and open alternatives.
2. Ingest arbitrary job documents, point schedules, BACnet inventories, sequence text,
   Guideline 36/CDL sources, and contractor Niagara templates.
3. Model sites, systems, equipment, relationships, points, sequences, alarms, graphics,
   schedules, and commissioning requirements in versioned schemas.
4. Provide a typed, stateful, temporal control IR with explicit units, execution
   semantics, safety constraints, provenance, and target-compiler coverage.
5. Compose versioned capability packs for terminal units, AHUs, RTUs, DOAS, hydronic
   plants, boilers, chillers, heat pumps, cooling towers, pumps, exhaust, lighting,
   meters, and contractor-defined systems.
6. Compile every supported feature into complete Niagara artifacts: control logic,
   point mappings, tags, alarms, schedules, graphics data, template diffs, and import
   instructions.
7. Exercise commercially permissible OSS through real product paths where it provides
   leverage: pybog, Modelica Buildings/OBC, modelica-json, Open Control Engine,
   ConStrain, BOPTEST, pyfunnel, Brick, Haxall/Xeto, Phable, BACpypes3/BAC0,
   Open-FDD, and VOLTTRON.
8. Test generated programs at multiple levels: schema/type checks, graph invariants,
   deterministic vectors, independent reference rules, semantic validation, trajectory
   comparison, simulated buildings, isolated BACnet, Niagara import/runtime, hardware in
   the loop, security, load, recovery, and contractor acceptance.
9. Keep live control default-deny. No generated program or command reaches a live
   building without explicit human approval, artifact binding, policy enforcement, and
   an auditable deployment boundary.
10. Meet enterprise requirements for identity, authorization, tenant isolation,
    secrets, audit retention, observability, compatibility, reproducible builds,
    dependency governance, backups, recovery, supportability, and safe upgrades.

## Non-negotiable truth model

Every capability is tracked independently across these stages:

1. **Discovered** — source or standard is known and license-screened.
2. **Installed** — an exact version/revision is reproducibly available.
3. **Executable** — a real contract invokes it successfully.
4. **Product-wired** — a user workflow invokes it and retains evidence.
5. **Target-compiled** — the behavior is emitted for the selected Niagara target.
6. **Verified** — an independent oracle tests it, including a known-bad negative case.
7. **Field-qualified** — Niagara and/or hardware-in-loop evidence exists for supported
   versions and configurations.
8. **Production-supported** — compatibility, security, operations, rollback, and support
   ownership are defined.

UI labels and export gates must use these stages. Presence in a catalog, an installed
package, generated JSON, or a passing mock is never presented as field support.

## Execution program

### Gate 0 — product and risk validation

- Interview/observe controls contractors across estimating, engineering, programming,
  startup, commissioning, and service.
- Quantify time, rework, risk, and willingness to pay for the highest-value workflows.
- Map alternatives: Niagara templates/macros, vendor engineering tools, supervisory
  platforms, commissioning products, AI coding products, and internal contractor tools.
- Define initial customer profile, supported Niagara versions/modules, deployment model,
  service boundary, liability posture, and success metrics.
- Maintain an architecture decision record and a live risk register.

Exit evidence: design partners confirm the workflow and supply representative, legally
usable job packages and station templates; initial paid/pilot value hypothesis is clear.

### Gate 1 — reproducible OSS and capability ledger

- Pin source revisions, packages, transitive dependencies, licenses, notices, and SBOMs.
- Run positive and negative executable contracts for every selected library.
- Expose machine-readable readiness and block claims when a runtime is absent.
- Keep incompatible/copyleft runtimes isolated behind documented process or service
  boundaries.

Exit evidence: clean-machine bootstrap and integration contract suite pass; no catalog-only
component is labeled active.

### Gate 2 — general building model and intake

- Add multi-equipment/site topology, relationships, quantities/units, schedules, alarm
  policy, graphics intent, network segmentation, and target-platform metadata.
- Import CSV/XLSX, BACnet discovery exports, Brick/Haystack, Niagara archives, and
  structured sequence documents with source-line provenance and ambiguity queues.
- Use Xeto/Brick validation and deterministic unit normalization.

Exit evidence: representative projects for every target equipment family normalize with
no silent data loss and produce an engineer-reviewable ambiguity report.

### Gate 3 — stateful control IR and sequence compiler

- Add timers, delays, hysteresis, edge detection, latches, PID, rate limits, filters,
  integrators, state machines, schedules, resets, lead/lag, staging, safeties, overrides,
  and alarm state semantics.
- Give each construct formal types, units, initialization, scan-cycle behavior, fault
  behavior, simulation semantics, and Niagara lowering rules.
- Translate supported CDL/CXF constructs into the IR and retain source provenance.
- Reject any construct not supported by both interpreter and selected target compiler.

Exit evidence: conformance vectors and mutation tests pass for every construct across the
IR interpreter, Open Control Engine reference behavior where applicable, and Niagara
output inspection/runtime.

### Gate 4 — equipment capability packs

- Build composable packs for zones/terminals, airside systems, central plants, heat
  rejection, heat pumps, pumps, exhaust, lighting, meters, and custom equipment.
- Separate reusable primitives from equipment templates and project-specific policy.
- Declare required/optional points, supported configurations, parameters, alarms,
  graphics views, test suites, semantic constraints, and target compatibility.
- Derive from published sequences where permitted; require engineering review for gaps.

Exit evidence: each advertised pack has positive, boundary, sensor-failure, actuator-failure,
power-cycle, mode-transition, safety, and known-bad mutation evidence.

### Gate 5 — complete Niagara deliverables

- Harden/fork pybog as needed and expand verified palette/module/version coverage.
- Generate station hierarchy, wire sheets, point extensions/mappings, tags, histories,
  alarms, schedules, graphics data, navigation, documentation, and deterministic diffs.
- Analyze contractor libraries and preserve approved shop conventions.
- Test import and execution against licensed Niagara versions in isolated labs.

Exit evidence: clean import, compile, restart, and behavioral tests pass on every supported
Niagara compatibility profile; rollback artifacts and migration notes are generated.

### Gate 6 — simulation, commissioning, and field adapters

- Run fast deterministic tests on every change.
- Execute applicable ConStrain and Open-FDD checks with retained mappings/evidence.
- Run BOPTEST/Modelica trajectories and pyfunnel comparisons for supported archetypes.
- Exercise VOLTTRON, BACpypes3/BAC0, and BOPTEST BACnet in isolated lab networks.
- Add hardware-in-loop rigs and fault injection for supported controller families.

Exit evidence: repeatable lab environments prove normal, abnormal, recovery, and safety
behavior without access to production OT networks.

### Gate 7 — enterprise platform and security

- Add durable database/object storage, organizations/projects, RBAC, SSO, secret vaulting,
  immutable audit events, approvals, artifact signing, retention, and tenant isolation.
- Add queue/workflow durability, idempotency, concurrency controls, cancellation,
  observability, alerting, backups, restore drills, disaster recovery, and support tooling.
- Threat-model prompt injection, malicious archives, dependency compromise, unsafe BACnet,
  confused-deputy approvals, cross-tenant access, and artifact tampering.
- Sandbox untrusted parsers, generated code, model tools, and external runtimes.

Exit evidence: security review, dependency/SBOM policy, penetration tests, load tests,
restore drills, and incident/rollback runbooks pass defined service objectives.

### Gate 8 — contractor qualification and controlled release

- Run complete blinded jobs from design partners and compare against senior programmer
  deliverables and field outcomes.
- Measure engineering time, defects, nuisance alarms, change-review quality, import time,
  commissioning failures, and escaped defects.
- Require engineer approval and shadow-mode deployments before any controlled field write.
- Publish a precise supported-capability matrix and never market beyond it.

Exit evidence: designated contractors sign acceptance results; critical risks have owners;
support and liability boundaries are approved; release readiness audit has no hidden
unsupported path.

## Definition of enterprise-production ready

BACTalk is not enterprise-production ready until all advertised capabilities reach
**Production-supported**, every exported feature has an independent verification path,
the supported Niagara matrix is proven in licensed environments, live-control boundaries
have passed security review, and representative contractor projects complete end to end
with traceable evidence and recoverable deployments.

## Immediate execution slice

1. Finish executable contracts for the installed suite and expose readiness honestly.
2. Add a machine-enforced capability ledger and export gate.
3. Replace the combinational-only IR limitation with a stateful block contract and use
   Open Control Engine as a behavioral oracle.
4. Define pack manifests and implement the first cross-family set: AHU, RTU/heat pump,
   boiler/pump plant, chiller/cooling tower plant, exhaust, lighting, and VAV/terminal.
5. Build one complete multi-equipment sample building through intake, generation,
   semantic checks, simulation, approval, and export.
6. In parallel with implementation, complete product/competitor/library research and
   recruit design partners for Niagara and hardware-in-loop qualification.
