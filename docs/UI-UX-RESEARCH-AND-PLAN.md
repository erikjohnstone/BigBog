# BACTalk Enterprise UI/UX Research and Production Plan

Status: implemented. The React workbench owns `/`; the retired static workbench is served at `/legacy/`
for one transition period. Backend control logic remains authoritative; the only backend additions were
the block catalog, the qualification-job event stream, and the static mounts.

Implementation record (web/src): one clock (`stores/timeCursor`), a typed-array trace store with
frame fan-out and level-of-detail binding groups (`stores/trace`), trace builders for generic, legacy
G36, BOPTEST, Alfalfa, and whole-project evidence (`trace/`), the wiresheet with catalog-declared ports,
value chips, wire flow, tidy layout, materialize intro, and ghost diff (`features/wiresheet`), the
master timeline and transport (`features/timeline`), uPlot trend panes with fault windows, oracle bands,
counterexample windows, and boolean lanes (`features/trends`), parametric HVAC schematics and the
system map (`features/schematic`), the AI thread with proposal cards (`features/assistant`), guided
intake and the promoted ctrl-flow design pipeline (`features/intake`), the Simulation Center with live
job progress (`features/simulation`), acknowledged review surfaces with digest-bound approval and
rejection (`features/review`, `features/release`), the project cockpit with whole-building intake and
lazy 3D massing (`features/projects`, `features/massing`), and the library, connection, and
administration workspaces. Quality gates: vitest coverage thresholds on `trace/`, `stores/`, and
`wiresheet/diff`; Playwright journeys on desktop and tablet with axe on every page and pixel baselines
under reduced motion; a bundle budget with lazy canvas runtimes; a 500-block scrub performance harness.

## Executive decision

BACTalk should not look like a generic SaaS dashboard with a flowchart bolted on. It should feel
like an engineering IDE for buildings: the spatial clarity of a controls wiresheet, the execution
visibility of a workflow debugger, the evidence discipline of a code-review system, and the trend
analysis of an observability product.

The rewrite will use a new React/TypeScript application beside the existing static UI. It will
consume the current FastAPI contracts and never reimplement compiler, simulator, safety, approval,
or artifact-integrity rules in the browser. The existing UI remains available until each workflow
has parity tests and the replacement passes the release gates below.

The core experience is a five-stage job rail:

1. **Intake** — upload, inspect, normalize, resolve, and acknowledge assumptions.
2. **Build** — inspect or edit the typed control graph with the AI agent beside it.
3. **Test** — replay scenarios against the deterministic plant, virtual BACnet, and BOPTEST.
4. **Review** — examine exact graph, point, artifact, and evidence changes.
5. **Release** — approve one immutable digest and export the target plus review bundle.

This is the product's primary mental model. Libraries, connections, projects, and administration
support it; they do not compete with it.

## What the current UI audit found

The current UI is useful evidence, not a production foundation:

- It is a 241-line HTML file, 364-line stylesheet, and 796-line global JavaScript file with no
  component boundary, static type checking, application router, or frontend test suite.
- It exposes the run list, intake form, graph, deterministic report, artifacts, points, edge
  manifests, readiness ledger, agent chat, and approval. That behavior must be preserved.
- The backend exposes 70 operations across 68 paths. Projects, controller libraries, semantics,
  CXF execution, BOPTEST qualification, verification tools, and project export are largely absent
  or buried in the UI.
- The only primary entity is a run selector. A contractor thinks in customers, sites, projects,
  systems, equipment, revisions, issues, and releases.
- The wiresheet is read-only and manually rendered. It has no search, minimap, grouping,
  hierarchical drill-down, value overlays, test-path highlighting, diff overlay, keyboard editing,
  or scalable layout strategy.
- Test results are assertions in a list. There is no synchronized timeline, state ribbon,
  setpoint/tolerance band, node-value replay, BOPTEST KPI surface, fault injection, comparison run,
  or failure-to-source navigation.
- Generated graphics are represented as artifacts rather than a visual engineering workspace.
- Agent chat hides the plan, actions, tool evidence, assumptions, checkpoints, and per-change
  accept/reject controls needed for trustworthy engineering collaboration.
- A fixed approval bar competes with the workspace. Approval needs a dedicated, auditable review
  flow with a checklist and explicit unresolved blockers.

## Research synthesis

### Controls engineering products

- Niagara WebWiresheet emphasizes browser access, tag-based linking/relating, remembered link
  choices, multi-selection, and mobile drag/drop. The useful lesson is not to clone Workbench; it is
  to preserve wiresheet fluency while making relationships and repetitive actions fast.
  [Tridium WebWiresheet 2.0](https://www.tridium.com/us/en/services-support/events/2022/05/2022-05-12-niagara-4-12-webwiresheet)
- Niagara 4.15 brings PX editing to HTML5 with customizable widgets, real-time data binding, and
  responsive pages. BACTalk needs a browser-native graphics workflow and responsive preview, while
  clearly distinguishing generated intent from licensed Niagara rendering.
  [Tridium UX Builder](https://www.tridium.com/us/en/services-support/events/2025/02/2025-02-20-niagara-ux-builder)
- Johnson Controls separates Configure, Simulate, and Commission modes and exposes additional live
  properties only in the latter modes. BACTalk should use explicit modes so engineers always know
  whether they are editing a proposal, replaying a model, or inspecting qualified evidence.
  [JCI PID/PRAC simulation and commissioning](https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/13.1/PID-PRAC-Commissioning-Overview/PID-Control-and-PRAC-Adaptive-Tuning-within-CCT/PCT?contentId=1iIFz3Y4Ocm3ZVHMMCtpfA)
- Schneider's editor combines a work area with object, property, layer, binds/links, test,
  equipment, component, and snippet panes. The key lesson is contextual tools around one stable
  canvas, not a separate page for every small operation.
  [Schneider Graphics Editor](https://product-help.schneider-electric.com/EcoStruxure-Power-Operation-2022/content/6%20operating/graphicseditor/graphicseditor.htm)
- Siemens uses standardized graphic templates that automatically recognize control functions and
  supports topology, plant, floor, viewport, and equipment-specific views. BACTalk should generate
  views from semantic equipment identity and bindings before asking users to draw from scratch.
  [Siemens graphics pages and templates](https://mybuilding.siemens.com/d025938170736/help/engineeringhelp/en-US/14116338187.html)

### Node and workflow editors

- Node-RED organizes the editor around a header, center workspace, node palette, and configurable
  sidebars. Its minimap, quick-add, grouping, node status, errors on nodes, selection inspector, and
  filtered debug stream are directly relevant.
  [Node-RED editor](https://nodered.org/docs/user-guide/editor/),
  [workspace](https://nodered.org/docs/user-guide/editor/workspace/), and
  [debug sidebar](https://nodered.org/docs/user-guide/editor/sidebar/debug)
- n8n can load data from a previous execution into the canvas and retry with either original or
  current workflow logic. BACTalk needs the controls equivalent: replay a captured scenario against
  the approved graph or the current candidate without rewriting the test case.
  [n8n execution history](https://docs.n8n.io/workflows/executions/all-executions/)
- React Flow's MIT core provides typed custom nodes, multiple handles, minimap, controls, subflows,
  grouping, selection, and scalable interaction primitives. It is the correct canvas foundation;
  BACTalk will own the controls semantics and visual language.
  [React Flow feature overview](https://reactflow.dev/examples/overview) and
  [MIT licensing statement](https://xyflow.com/open-source)

### Testing and observability

- Grafana's time series, zoom, brushing, linked views, and event annotations are the right model for
  synchronized input/output trends, state transitions, alarms, setpoint changes, and assertion
  failures. [Grafana time series](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/time-series/)
- Playwright Trace Viewer combines a filmstrip/timeline with actions, before/after snapshots,
  source, logs, errors, console, network, and attachments. BACTalk's scenario viewer should do the
  same for control scans: time cursor, physical state, graph values, command outputs, assertions,
  and the exact requirement or block involved.
  [Playwright Trace Viewer](https://playwright.dev/docs/trace-viewer)
- BOPTEST provides measurements, inputs with bounds, scenarios, forecasts, histories, and normalized
  energy, cost, emissions, peak-demand, IAQ, comfort, and runtime KPIs. Those belong in a first-class
  qualification cockpit rather than raw JSON.
  [BOPTEST API](https://ibpsa.github.io/project1-boptest/docs-userguide/api.html) and
  [test-case catalog](https://ibpsa.github.io/project1-boptest/testcases/)

### AI engineering and review

- GitHub's agent sessions expose progress, logs, tools, validation, provenance, and steering, while
  human review remains the merge gate. BACTalk should show what the controls agent is doing and why,
  rather than presenting only a chat transcript.
  [GitHub agent sessions](https://docs.github.com/en/copilot/how-tos/copilot-on-github/use-copilot-agents/manage-and-track-agents)
- Cursor's review surface supports familiar diffs and selective acceptance. BACTalk needs semantic
  equivalents: accept or reject blocks, links, mappings, setpoints, alarms, graphics bindings, and
  assumptions—not raw JSON lines.
  [Cursor diffs and review](https://docs.cursor.com/en/agent/review)
- Replit's task board separates Draft, Active, Ready, and Done work and keeps isolated changes out of
  the main project until applied. BACTalk already creates separate proposal runs; the UI should make
  that branch/checkpoint model obvious.
  [Replit task board](https://docs.replit.com/references/agent/task-board)
- GitHub's pull-request review tracks reviewed files and review progress. BACTalk should track every
  changed engineering surface as reviewed and invalidate that state if the candidate changes.
  [GitHub change review](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/reviewing-proposed-changes-in-a-pull-request)

### Accessibility and field usability

The target is WCAG 2.2 AA, with enhanced 44px targets on frequent or consequential actions. Color
will never be the only signal, keyboard alternatives will exist for drag operations, focus will not
be obscured by sticky bars, and the visual/DOM order will agree.
[WCAG 2.2](https://www.w3.org/TR/WCAG22/) and
[WCAG target-size guidance](https://www.w3.org/WAI/WCAG22/Understanding/target-size-enhanced)

## Product information architecture

### Global shell

- Organization/site/project switcher
- Global command palette (`⌘/Ctrl K`)
- Universal search across equipment, points, runs, libraries, tests, and artifacts
- Notifications and background-task center
- Environment badge: Offline, Simulation, Isolated BACnet Lab, or Licensed Niagara Lab
- Persistent safety boundary; never a vague green “connected” dot
- User, tenant, role, and audit access

### Primary navigation

1. **Home** — assigned reviews, active jobs, failing qualifications, recent releases.
2. **Projects** — site/system hierarchy, scope, revisions, project-wide builds and releases.
3. **Studio** — intake, graph, agent, tests, review, and release for the current job.
4. **Libraries** — G36, plant, OCL, AixOCAT, Niagara templates, shop assets, provenance, coverage.
5. **Simulations** — scenario catalog, deterministic runs, virtual BACnet, BOPTEST, comparisons.
6. **Connections** — environment packs, BACnet inventories, VOLTTRON, Niagara lab contracts.
7. **Administration** — users, roles, tenants, policies, audit log, retention, and integrations.

## Detailed workspace designs

### 1. Project cockpit

- Building/system tree at left; status and blockers on every node.
- Project pipeline showing Intake → Build → Test → Review → Release.
- Coverage matrix by equipment and deliverable, not a single misleading percentage.
- Release ledger with digest, reviewer, target Niagara version, environment pack, and evidence.
- “Needs attention” queue that links to the exact unresolved item.

### 2. Intake Studio

- Guided, resumable steps: scope, documents, points, topology, environment, requirements, tests,
  preflight.
- Drag/drop files with hash, parser status, source-page references, and replacement history.
- Virtualized point grid with bulk mapping, confidence, unit/type conflict indicators, filters, and
  keyboard editing.
- Split source viewer: original sequence paragraph on the left, extracted requirement and proposed
  implementation/test on the right.
- Semantic topology viewer for equipment and cross-equipment relationships.
- Explicit assumption inbox; unresolved material assumptions prevent build.
- Preflight report that distinguishes errors, warnings, missing optional data, and unsupported
  requested capabilities.

### 3. Control Studio

- Center: React Flow canvas with typed ports, orthogonal/selectable wires, minimap, search, fit,
  breadcrumbs, groups/subflows, and collapsed equipment modules.
- Left: searchable block/library palette and equipment hierarchy.
- Right: selection inspector with properties, units, provenance, requirements, incoming/outgoing
  links, mappings, validation, and docs.
- Bottom: problems, tests, execution trace, agent activity, and artifact console.
- Modes: **Inspect**, **Edit candidate**, **Simulate**, and **Review diff**. Mode is always visible.
- Node badges show compile target, test coverage, runtime values, warnings, and provenance.
- “Explain this path” traces an output backward to inputs and sequence requirements.
- No direct mutation of an approved run. Editing creates a candidate derived from that run.

### 4. AI controls agent

- Dockable panel, not a modal chat island.
- Messages can reference selected nodes, points, requirements, traces, test failures, or artifacts.
- Every change request first shows plan, assumptions, affected surfaces, and proposed verification.
- Activity timeline exposes bounded stages: inspect → propose → validate → compile → test → repair.
- Generated changes appear as a semantic patch with per-change accept/reject and “ask why.”
- The user can steer or stop the agent. Existing artifacts remain unchanged until a new run passes.
- Separate chat and coding-model identity remain visible.

### 5. Simulation and Test Lab

- Scenario matrix with rows for scenarios and columns for requirements/outputs; drill into any cell.
- Synchronized time-series chart, discrete-state ribbon, alarm lane, schedule/occupancy lane, and
  assertion tolerance bands.
- Scrubbing the time cursor updates value badges on the control graph and building schematic.
- Playback controls: jump to failure, step scan, play, compare, and loop selected interval.
- Side-by-side Approved vs Candidate overlays with delta plot and KPI cards.
- Fault injection builder for sensor bias/freeze/dropout, actuator stuck/limited, proof failure,
  communication loss, schedule transition, and plant availability.
- Runtime selector explains fidelity: truth-table, local plant, BACnet lab, BOPTEST, or licensed lab.
- BOPTEST cockpit shows case/scenario, measurement/actuator bindings, bounds, worker state, KPIs,
  pyfunnel band, failing intervals, and retained evidence paths.
- Failed tests link directly to the responsible graph path and source requirement.

### 6. Graphics Studio

- Auto-generated system graphic from semantic topology, with standardized HVAC symbols first.
- Canvas, layer tree, component palette, binding inspector, responsive breakpoints, and test mode.
- Views: plant schematic, floor/zone, equipment detail, point card, trends, alarm summary.
- Binding health shows exact Niagara ORD, BACnet identity, point type/units, fallback state, and
  unbound/ambiguous points.
- Preview simulation drives animations without touching a live station.
- Side-by-side contractor template and generated candidate, with binding and layout diff.
- Export continues to produce declarative graphics plans/bindings until licensed Niagara rendering
  and import are qualified. The UI must state this boundary plainly.

### 7. Review and Release

- Review queue organized by graph, points, mappings, alarms, schedules, histories, graphics,
  simulation, dependencies, and target artifact.
- Semantic before/after graph diff with added/removed/modified nodes and rewired paths.
- “Reviewed” state per surface; any regenerated candidate invalidates affected acknowledgements.
- Required evidence checklist and blocker list generated from backend release gates.
- Approval dialog displays target environment, digest, reviewer identity, and irreversible meaning.
- Export page offers the target artifact, review bundle, evidence index, and licensed-lab handoff.

### 8. Library and connection workspaces

- Searchable controller/pattern catalog with interface, parameters, provenance, license, exactness,
  compiler target, test evidence, known limits, and “start job from this” action.
- Capability maturity is shown as a ladder, never a binary installed/not-installed badge.
- Connection cards show type, scope, environment, health, last verification, and permitted actions.
- Live-capable connections use an unmistakable boundary and cannot silently inherit lab authority.

## Visual language

- Dense enough for engineers, calm enough for all-day use. Default 14px body text; monospace only
  for identifiers, values, hashes, and source.
- Neutral graphite/navy surfaces with equipment colors used sparingly. Red, amber, green, and blue
  always pair with icon and text.
- Cards are for independent objects, not every rectangle. Data-heavy surfaces use panes, splitters,
  tables, and direct manipulation.
- Light and dark themes share semantic tokens. Dark mode is especially useful for controls rooms,
  but light remains the review/print default.
- Motion explains state changes and navigation; it never decorates. Respect reduced-motion settings.
- HVAC schematics use a versioned symbol system with design tokens for air, water, steam,
  refrigerant, electrical, commands, status, alarm, offline, and simulation state.

## Selected frontend stack and commercial-use review

| Package | Role | License | Decision |
|---|---|---:|---|
| React + TypeScript + Vite | typed application and build | MIT / Apache-2.0 / MIT | Adopt |
| React Router | nested, URL-addressable workspaces | MIT | Adopt |
| TanStack Query | server-state cache and mutation lifecycle | MIT | Adopt |
| Zustand | small client-only workspace state | MIT | Adopt |
| Zod | runtime validation at API/UI boundaries | MIT | Adopt |
| React Flow (`@xyflow/react`) | wiresheet and topology canvas | MIT | Adopt core only; no Pro dependency |
| Apache ECharts | trends, state timelines, bands, KPI comparisons | Apache-2.0 | Adopt |
| TanStack Table + Virtual | point/artifact/library grids | MIT | Adopt |
| Radix primitives | accessible dialogs, tabs, tooltips, menus | MIT | Adopt selectively |
| React Resizable Panels | IDE-style panes | MIT | Adopt |
| Dagre | initial automatic graph layout | MIT | Adopt; preserve authored positions |
| Lucide | consistent icons | ISC | Adopt |
| React Hook Form | performant guided forms | MIT | Adopt |
| React Markdown + remark-gfm | safe, readable model explanations and evidence tables | MIT / MIT | Adopt; raw HTML remains disabled |
| openapi-typescript | generated API contract types | MIT | Adopt |
| Vitest + Testing Library | component/unit tests | MIT | Adopt |
| Playwright | browser workflows, traces, visual baselines | Apache-2.0 | Adopt |
| axe-core Playwright | automated accessibility checks | MPL-2.0 | Dev/test only; adopt |
| MSW | deterministic API fixtures | MIT | Adopt for component/browser tests |

All versions are pinned in the lockfile. The build must generate an OSS notice/SBOM, and no copied
React Flow Pro examples or assets enter the repository. No GPL/AGPL frontend dependency is selected.

## Frontend architecture

```text
web/
  src/
    app/               router, providers, error boundaries, permissions
    api/               generated OpenAPI types, typed client, query keys
    components/        accessible product primitives
    design-system/     tokens, icons, typography, themes, HVAC symbols
    features/
      intake/
      control-studio/
      agent/
      simulations/
      graphics/
      review/
      libraries/
      connections/
      projects/
    test/              fixtures, MSW handlers, accessibility helpers
  e2e/                 Playwright user journeys
```

Rules:

- FastAPI/OpenAPI is the contract source. Generated TypeScript is checked for drift in CI.
- Domain decisions stay server-side. UI-derived states are display hints, never authorization.
- Mutations invalidate exact query keys and show server-returned records; no optimistic approval.
- Long-running build/test operations will use an explicit task resource and server events rather
  than holding one request open.
- Every page is URL-addressable; selected project/job/run/mode/test/time cursor can be shared.
- Feature folders own UI and adapters, never duplicate domain models.
- The production build is emitted into a versioned static directory and served by FastAPI. The
  legacy UI remains a fallback until migration is complete.

## Backend/API additions required for the best UX

These are additive contracts; existing compiler and verification logic remains untouched.

1. Project/site/system summary endpoints optimized for navigation and queues.
2. Background operation resource: queued/running/needs-input/failed/complete, progress events,
   cancellation, logs, and retained outputs.
3. Rich execution trace schema: sample time, graph inputs, block outputs, state transitions,
   assertions, requirement references, alarms, and runtime provenance.
4. Semantic graph diff endpoint, including affected downstream outputs and tests.
5. Intake draft resource so mappings and assumptions can be resolved before creating a run.
6. Review checklist/acknowledgement resource bound to candidate digest.
7. Graphics document schema, symbol library, binding validation, preview data, and generated
   artifact diff.
8. Search endpoint across projects, points, equipment, libraries, runs, and artifacts.
9. Signed artifact index endpoint instead of exposing filesystem-shaped paths to the UI.
10. BOPTEST catalog/scenario/binding-preview endpoints and asynchronous qualification runs.

## Migration plan and exit gates

### Phase 0 — Foundation and parity harness

- Create the Vite/React/TypeScript workspace and pin the selected dependencies.
- Generate API types from the real OpenAPI document.
- Establish tokens, themes, typography, icon rules, app shell, routing, query/error handling.
- Add Vitest, MSW, Playwright traces, axe checks, and visual baseline infrastructure.
- Capture the current UI behaviors as a parity checklist.

Exit: CI builds both Python and frontend; no existing test changes; the new shell can read health,
security, AI status, runs, projects, readiness, and capabilities.

### Phase 1 — Project cockpit and guided intake

- Implement projects/home navigation and resumable intake.
- Build virtualized point mapping and source-to-requirement review.
- Preserve all current import fields and exact uploaded evidence.

Exit: a contractor can complete the existing generalist and plant-controller import flows without
typing JSON into a textarea; advanced JSON remains available behind an expert disclosure.

### Phase 2 — Control Studio and agent workbench

- Ship the React Flow canvas, hierarchy, palette, inspector, problems, search, minimap, layout, and
  semantic diff overlay.
- Add agent plan/activity/proposal UX and selection-aware context.

Exit: existing graphs from small VAVs through the 480-block plant proof remain navigable at usable
frame rates; all change proposals still create separate server-side runs.

### Phase 3 — Simulation and qualification cockpit

- Add trace schema/API and ECharts synchronized views.
- Integrate deterministic tests, virtual BACnet, BOPTEST mappings, KPIs, pyfunnel bands, replay,
  comparison, and failure navigation.

Exit: the retained contractor/BOPTEST proof is fully reviewable without opening JSON or CSV files,
and a failed oracle visibly prevents review completion and approval.

### Phase 4 — Graphics Studio

- Implement semantic auto-layout, symbol library, binding inspector, layer tree, responsive preview,
  simulated animation, and contractor-template comparison.

Exit: a contractor can review and adjust every generated graphic binding and layout intent; export
boundaries remain truthful until licensed Niagara render/import tests exist.

### Phase 5 — Review, release, libraries, and connections

- Complete semantic review queues, acknowledgement tracking, release handoff, library explorer,
  connection inventory, environment compatibility, and audit views.

Exit: every backend capability selected for production has a discoverable workflow and evidence
surface; no hidden JSON-only feature is counted as product-complete.

### Phase 6 — Enterprise qualification

- WCAG 2.2 AA manual and automated audit.
- Keyboard-only, screen-reader, zoom/reflow, high-contrast, and reduced-motion verification.
- Performance budgets for 500/2,000/10,000-node and 10k/100k-point datasets.
- Browser matrix, network interruption, session expiry, permission, and concurrent-review tests.
- Usability sessions with controls programmers, project engineers, reviewers, and commissioning
  technicians; instrument task completion and error recovery.

Exit: pilot users complete the primary job without coaching, understand every safety boundary, find
the cause of a failed scenario, and approve/export only the intended digest.

## Non-negotiable quality gates

- No regression to current Python tests, suite contracts, signed artifacts, or default-deny writes.
- Every new route has loading, empty, failure, forbidden, stale, and offline states.
- No approval or export based on client state; the server always revalidates status and integrity.
- Every consequential action is named, scoped, reversible where possible, and audit-visible.
- No raw JSON is required for the common workflow.
- No green status without a named check, timestamp, source, and drill-down evidence.
- No chart without units, legend, accessible description, and tabular alternative.
- No canvas-only operation without keyboard/list alternative.
- No product-ready claim from an installed library or rendered mockup.

## Success measures

- New contractor job to tested candidate: under 15 minutes excluding simulation runtime.
- Find why a test failed: under 60 seconds from the scenario matrix.
- Review a routine VAV candidate: under 10 minutes with every surface acknowledged.
- Zero accidental approvals in usability tests; users can state which digest/environment they signed.
- At least 90% of pilot tasks completed without facilitator intervention.
- WCAG 2.2 AA automated checks clean, followed by manual assistive-technology verification.
- 60 fps pan/zoom on a representative 500-node graph and interactive navigation at 2,000 nodes;
  larger programs use hierarchy and virtualization rather than pretending one canvas is usable.

## First implementation slice

The first slice should be vertical, not a collection of disconnected components:

1. New application shell and project/run navigation.
2. Open a real run from the current API.
3. Render its graph in React Flow with minimap, search, fit, and inspector.
4. Render deterministic test results and BOPTEST evidence as a synchronized ECharts timeline.
5. Show semantic changes and signed artifacts in a review checklist.
6. Exercise approve/export through the unchanged backend gate.
7. Cover the entire path with Playwright, axe, and a retained trace.

That slice proves the architecture, preserves all safety logic, and produces something contractors
can react to immediately before the broader migration continues.

## Implementation status — 2026-09-20

The foundation and the review half of the first vertical slice are now implemented side-by-side
with the existing workbench:

- The React/TypeScript shell, responsive navigation, design tokens, generated OpenAPI types,
  query cache, route-level code loading, production build, SBOM, unit tests, Playwright, and axe
  gates are installed and running.
- `/next/` is the new enterprise shell; `/` remains the proven legacy workbench while migration is
  incomplete. Extensionless `/next/*` routes return the React entry point, so copied Control Studio
  links survive refresh and direct navigation.
- A real retained run opens in Control Studio with a typed React Flow wiresheet, exact named ports,
  selectable program outline, search highlighting, minimap, fit/zoom controls, and a configuration/
  driver/destination inspector.
- Test Lab renders the retained deterministic scenarios, assertion evidence, unit-separated analog
  traces, binary state lanes, and an accessible trace table. It never converts a failed report into
  a green UI state.
- Review & Release shows the semantic changeset, exact SHA-256 candidate, mandatory engineer
  acknowledgements, server-authoritative approval, and approval-gated export. It repeats the manual
  licensed-Workbench import boundary at the decision point.
- Guided contractor intake now covers job scope, sequence strategy, CSV/XLSX points, sequence
  documents, BACnet scans, shop `.bog` templates, and Niagara environment packs. It calls the real
  preflight endpoint before build, exposes canonical aliases and missing required points, and keeps
  candidate generation disabled until the server-normalized contract is complete. AI-custom work
  explicitly requires an independent acceptance-test array.
- Control Studio now includes a connected AI controls-engineer drawer. It reads the server-reported
  Cerebras role configuration, visibly separates explain-and-route authority from proposal-only
  coding authority, renders long technical answers as safe Markdown, records assumptions, and links
  any model-authored child run as a separate tested candidate instead of mutating the source.
- Desktop and tablet browser tests exercise home, the legacy migration boundary, the real
  intake-normalization path, AI proposal/result path, wiresheet/test/review path, the blocked failed-
  candidate path, direct deep links, and automated accessibility checks.

Still required before the old workbench can be retired: persisted conversation/activity history;
BOPTEST and virtual-BACnet trace detail; project-level topology; Graphics Studio; searchable library,
environment, and connection workspaces; rejection and review-bundle flows; enterprise identity,
permissions, and audit UX; manual assistive-technology testing; and the large-graph/data performance
qualification described above.
