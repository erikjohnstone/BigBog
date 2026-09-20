import { z } from 'zod';

const healthSchema = z.object({
  status: z.string(),
  mode: z.string(),
});

const runSchema = z.object({
  id: z.string(),
  created_at: z.string(),
  origin: z.string(),
  status: z.enum(['failed', 'ready_for_review', 'approved', 'rejected']),
  artifact_sha256: z.string(),
  bacnet_lab_manifest_path: z.string().nullable().optional(),
  boptest_verification_path: z.string().nullable().optional(),
  environment_manifest_path: z.string().nullable().optional(),
  deliverable_manifest_path: z.string().nullable().optional(),
  job: z.object({
    name: z.string(),
    site: z.string(),
    equipment_name: z.string(),
    sequence: z.object({
      family: z.string(),
      version: z.string(),
    }).passthrough(),
  }).passthrough(),
}).passthrough();

const pointSchema = z.object({
  name: z.string(),
  label: z.string(),
  data_type: z.enum(['boolean', 'numeric', 'string', 'integer']).or(z.string()),
  role: z.string(),
  units: z.string().nullable().optional(),
  required: z.boolean().optional(),
  bacnet_device_instance: z.number().nullable().optional(),
  bacnet_object: z.string().nullable().optional(),
  niagara_ord: z.string().nullable().optional(),
  brick_class: z.string().nullable().optional(),
}).passthrough();

const runDetailSchema = runSchema.extend({
  target_artifact_kind: z.string().nullable().optional(),
  parent_run_id: z.string().nullable().optional(),
  approval: z.object({
    reviewer: z.string(),
    approved_at: z.string(),
  }).passthrough().nullable().optional(),
  rejection: z.object({
    reviewer: z.string(),
    rejected_at: z.string(),
    reason: z.string().nullable().optional(),
  }).passthrough().nullable().optional(),
  changes: z.object({
    added: z.array(z.string()).default([]),
    modified: z.array(z.string()).default([]),
    removed: z.array(z.string()).default([]),
  }).default({ added: [], modified: [], removed: [] }),
  agent_attempts: z.array(z.object({
    iteration: z.number(),
    passed: z.boolean(),
    failed_assertions: z.array(z.unknown()).optional(),
  }).passthrough()).default([]),
  job: runSchema.shape.job.extend({
    points: z.array(pointSchema).default([]),
  }),
}).passthrough();

const aiStatusSchema = z.object({
  configured: z.boolean(),
  provider: z.string().nullable(),
  authority: z.literal('proposal-only'),
  roles: z.object({
    conversation: z.object({
      configured: z.boolean(),
      model: z.string().nullable(),
      authority: z.string(),
    }),
    coding: z.object({
      configured: z.boolean(),
      model: z.string().nullable(),
      authority: z.string(),
    }),
  }),
}).passthrough();

const chatTurnSchema = z.object({
  role: z.enum(['user', 'assistant']),
  content: z.string(),
});

const chatResponseSchema = z.object({
  message: z.string(),
  intent: z.enum(['answer', 'propose_change']),
  assumptions: z.array(z.string()),
  source_run_id: z.string(),
  new_run: runDetailSchema.nullable(),
});

const graphSchema = z.object({
  name: z.string(),
  blocks: z.array(z.object({
    id: z.string(),
    kind: z.string(),
    label: z.string(),
    x: z.number(),
    y: z.number(),
    config: z.record(z.string(), z.unknown()).default({}),
  }).passthrough()),
  links: z.array(z.object({
    source: z.string(),
    source_slot: z.string(),
    target: z.string(),
    target_slot: z.string(),
  }).passthrough()),
}).passthrough();

const assertionSchema = z.object({
  name: z.string(),
  observed: z.union([z.string(), z.number(), z.boolean(), z.null()]).transform(String),
  expected: z.union([z.string(), z.number(), z.boolean(), z.null()]).transform(String),
  passed: z.boolean(),
}).passthrough();

const faultCoverageSchema = z.object({
  schema: z.string(),
  activation_count: z.number(),
  fault_case_count: z.number(),
  fault_cases_passed: z.number(),
  kinds: z.array(z.string()),
  targets: z.array(z.string()),
  quality_targets: z.array(z.string()),
  recovery_phases: z.array(z.string()),
  declarations: z.array(z.object({
    case: z.string(),
    phase: z.string().nullable(),
    id: z.string(),
    kind: z.string(),
    target: z.string(),
    quality_target: z.string().nullable(),
  })),
  interpretation: z.string(),
}).passthrough();

const qualificationMatrixSchema = z.object({
  schema: z.string(),
  sequence_family: z.string().nullable(),
  profile: z.object({
    id: z.string(),
    version: z.string(),
    source: z.string(),
  }).nullable(),
  required_passed: z.number(),
  required_count: z.number(),
  conditional_addressed: z.number(),
  conditional_count: z.number(),
  engineering_matrix_complete: z.boolean(),
  requirements: z.array(z.object({
    category: z.string(),
    level: z.string(),
    description: z.string(),
    fault_required: z.boolean(),
    recovery_required: z.boolean(),
    status: z.string(),
    reason: z.string(),
    evidence_cases: z.array(z.string()),
  }).passthrough()),
  blockers: z.array(z.string()),
  interpretation: z.string().optional(),
}).passthrough();

const reportSchema = z.object({
  engine: z.string(),
  passed: z.boolean(),
  coverage: z.object({
    schema: z.string().optional(),
    percent: z.number().optional(),
    interpretation: z.string().optional(),
    outcomes_observed: z.number().optional(),
    outcomes_possible: z.number().optional(),
    gaps: z.array(z.string()).optional(),
    fault_injection: faultCoverageSchema.optional(),
    qualification_matrix: qualificationMatrixSchema.optional(),
  }).passthrough().nullable().optional(),
  scenarios: z.array(z.object({
    name: z.string(),
    passed: z.boolean(),
    assertions: z.array(assertionSchema),
    samples: z.array(z.record(z.string(), z.union([z.number(), z.boolean(), z.string(), z.null()]))).default([]),
  }).passthrough()),
}).passthrough();

const intakeInspectionSchema = z.object({
  schema: z.string(),
  point_count: z.number(),
  points: z.array(pointSchema),
  mapped_bacnet_points: z.number(),
  selected_sequence_family: z.string().nullable(),
  canonical_point_mappings: z.array(z.object({
    source_name: z.string(),
    canonical_name: z.string(),
  }).passthrough()),
  missing_required_points: z.array(z.string()),
  sequence: z.object({
    filename: z.string().optional(),
    media_type: z.string().optional(),
    text: z.string().optional(),
    suggested_sequence_families: z.array(z.object({
      family: z.string(),
      confidence: z.number(),
    }).passthrough()).optional(),
  }).passthrough().nullable(),
  build_started: z.boolean(),
  writes_enabled: z.boolean(),
}).passthrough();

const readinessSchema = z.object({
  production_ready: z.boolean(),
  policy: z.string(),
  components: z.array(z.object({
    id: z.string(),
    name: z.string(),
    stage: z.string(),
    selected: z.boolean(),
    installed: z.boolean(),
    version: z.string().nullable().optional(),
    license: z.string(),
    role: z.string(),
    product_path: z.string().nullable().optional(),
    evidence_command: z.string().nullable().optional(),
    blocker: z.string().nullable().optional(),
  }).passthrough()),
}).passthrough();

const integrationAuditSchema = z.object({
  schema: z.string(),
  passed: z.boolean(),
  policy: z.string(),
  pinned_component_count: z.number(),
  bound_component_count: z.number(),
  missing_bindings: z.array(z.string()),
  stale_bindings: z.array(z.string()),
  components: z.array(z.object({
    id: z.string(),
    license: z.string().nullable().optional(),
    revision_or_package: z.string().nullable().optional(),
    bound: z.boolean(),
    mode: z.string().nullable().optional(),
    product_path: z.string().nullable().optional(),
    proof: z.string().nullable().optional(),
  }).passthrough()),
}).passthrough();

const securityStatusSchema = z.object({
  schema: z.string(),
  authentication_enabled: z.boolean(),
  mode: z.string(),
  https_required: z.boolean(),
  configured_credentials: z.number(),
  review_identity: z.string(),
  live_writes_enabled: z.boolean(),
}).passthrough();

const auditStatusSchema = z.object({
  schema: z.string(),
  valid: z.boolean(),
  event_count: z.number(),
  head_hash: z.string(),
  external_immutable_retention: z.boolean(),
}).passthrough();

const projectJobSchema = z.object({
  name: z.string(),
  site: z.string(),
  equipment_name: z.string(),
  equipment_brick_class: z.string().nullable().optional(),
  sequence: z.object({
    family: z.string(),
    version: z.string(),
  }).passthrough(),
  points: z.array(pointSchema).default([]),
}).passthrough();

const projectRecordSchema = z.object({
  id: z.string(),
  created_at: z.string(),
  status: z.enum(['failed', 'ready_for_review', 'approved', 'rejected']),
  artifact_sha256: z.string(),
  assembled_station_path: z.string().nullable().optional(),
  approval: z.object({
    reviewer: z.string(),
    approved_at: z.string(),
  }).passthrough().nullable().optional(),
  project: z.object({
    name: z.string(),
    site: z.string(),
    equipment: z.array(projectJobSchema),
    relationships: z.array(z.object({
      source: z.string(),
      relation: z.string(),
      target: z.string(),
    }).passthrough()).default([]),
    signal_bindings: z.array(z.object({
      source_equipment: z.string(),
      source_point: z.string(),
      target_equipment: z.string(),
      target_point: z.string(),
    }).passthrough()).default([]),
    acceptance_tests: z.array(z.unknown()).default([]),
    station_assembly_mode: z.enum(['none', 'insert', 'replace']),
  }).passthrough(),
  equipment_runs: z.array(z.object({
    equipment_name: z.string(),
    run_id: z.string(),
    status: z.enum(['failed', 'ready_for_review', 'approved', 'rejected']),
    artifact_sha256: z.string(),
  }).passthrough()),
}).passthrough();

const projectPreflightSchema = z.object({
  accepted_for_build: z.boolean(),
  production_ready: z.boolean(),
  project: z.string(),
  site: z.string(),
  equipment_count: z.number(),
  relationship_count: z.number(),
  signal_binding_count: z.number(),
  project_acceptance_case_count: z.number(),
  equipment: z.array(z.object({
    equipment_name: z.string(),
    sequence_family: z.string(),
    pack_id: z.string().nullable(),
    pack_stage: z.string().nullable(),
    preflight_passed: z.boolean(),
    blockers: z.array(z.string()),
  }).passthrough()),
  next_gate: z.string(),
}).passthrough();

const bacnetLabSchema = z.object({
  format: z.string(),
  mode: z.literal('isolated-loopback'),
  source: z.string(),
  bacpypes3_version: z.string().nullable().optional(),
  devices: z.array(z.object({
    device_instance: z.number(),
    device_name: z.string(),
    source_transport: z.string(),
    emulation_transport: z.string(),
    network_address: z.string(),
    object_count: z.number(),
    scenario_injectable_objects: z.number(),
    command_capture_objects: z.number(),
  }).passthrough()),
  point_index: z.record(z.string(), z.object({
    device_instance: z.number(),
    network_address: z.string(),
    object_identifier: z.string(),
    data_type: z.string(),
    scenario_injectable: z.boolean(),
    command_capture: z.boolean(),
  }).passthrough()),
  independent_protocol_oracle: z.object({
    implementation: z.string(),
    license: z.string(),
    revision: z.string(),
    capabilities: z.array(z.string()),
    limitations: z.string(),
  }).passthrough(),
  safety: z.object({
    bind_scope: z.string(),
    live_network_discovery_performed: z.boolean(),
    live_network_routes_allowed: z.boolean(),
    writes_affect_virtual_objects_only: z.boolean(),
    source_addresses_never_bound: z.boolean(),
    human_approval_does_not_enable_live_writes: z.boolean(),
  }).passthrough(),
  transport_boundary: z.record(z.string(), z.string()),
}).passthrough();

const probeSchema = z.object({
  format: z.string(),
  passed: z.boolean(),
  point_count: z.number(),
  values: z.record(z.string(), z.union([z.string(), z.number(), z.boolean()])),
  run_id: z.string(),
  lab_mode: z.literal('isolated-loopback'),
  live_network_routes_allowed: z.literal(false),
}).passthrough();

const numericMap = z.record(z.string(), z.union([z.number(), z.boolean(), z.null()]));
const boptestSchema = z.object({
  schema: z.string(),
  status: z.enum(['pass', 'fail']),
  run_id: z.string(),
  approval_allowed: z.boolean(),
  live_building_writes: z.literal(false),
  runtime: z.object({
    runtime: z.string(),
    test_case: z.string(),
    graph_name: z.string(),
    graph_sha256: z.string(),
    step_seconds: z.number(),
    steps: z.number(),
    measurement_catalog_count: z.number(),
    input_catalog_count: z.number(),
    kpis: z.record(z.string(), z.number().nullable()),
    mapping: z.object({
      measurements: z.array(z.object({
        graph_input: z.string(),
        measurement: z.string(),
        scale: z.number(),
        offset: z.number(),
      }).passthrough()),
      actuators: z.array(z.object({
        graph_output: z.string(),
        actuator: z.string(),
        activation_actuator: z.string().nullable(),
        scale: z.number(),
        offset: z.number(),
      }).passthrough()),
      test_case: z.string(),
    }).passthrough(),
    trajectory: z.array(z.object({
      index: z.number(),
      start_time: z.number(),
      end_time: z.number(),
      graph_inputs: numericMap,
      controller_outputs: numericMap,
      overrides: numericMap,
      measurements: numericMap,
    }).passthrough()),
  }).passthrough(),
  oracles: z.array(z.object({
    completed: z.boolean(),
    passed: z.boolean(),
    max_error: z.number().nullable(),
    pyfunnel_status_code: z.number(),
    test_times: z.array(z.number()),
    test_values: z.array(z.number()),
    oracle: z.object({
      id: z.string(),
      signal: z.string(),
      signal_kind: z.string(),
      reference_times: z.array(z.number()),
      reference_values: z.array(z.number()),
      absolute_time_tolerance: z.number(),
      absolute_value_tolerance: z.number(),
    }).passthrough(),
  }).passthrough()),
}).passthrough();

const deliverablesSchema = z.object({
  schema: z.string(),
  equipment_name: z.string(),
  deployment_ready: z.boolean(),
  artifacts: z.array(z.object({
    path: z.string(),
    bytes: z.number(),
    sha256: z.string(),
  }).passthrough()),
  coverage: z.record(z.string(), z.object({
    emitted: z.boolean().optional(),
    target: z.string().nullable().optional(),
    target_compiled: z.boolean().optional(),
    licensed_runtime_qualified: z.boolean().optional(),
  }).passthrough()),
  blocking_gates: z.array(z.string()),
}).passthrough();

const releaseSummarySchema = z.object({
  schema: z.literal('bactalk.release-summary/v1'),
  run_id: z.string(),
  status: z.enum(['failed', 'ready_for_review', 'approved', 'rejected']),
  integrity: z.object({
    verified: z.boolean(),
    artifact_sha256: z.string(),
  }),
  behavior: z.object({
    passed: z.boolean(),
    scenario_count: z.number(),
    assertion_count: z.number(),
    passed_assertion_count: z.number(),
  }),
  target: z.object({
    artifact_kind: z.string(),
    filename: z.string().nullable(),
    manual_import_required: z.boolean(),
    licensed_runtime_qualified: z.boolean(),
  }),
  deliverables: z.object({
    available: z.boolean(),
    deployment_ready: z.boolean(),
    artifacts: z.array(z.object({
      path: z.string(),
      bytes: z.number(),
      sha256: z.string(),
    }).passthrough()),
    coverage: z.record(z.string(), z.object({
      emitted: z.boolean().optional(),
      target: z.string().nullable().optional(),
      target_compiled: z.boolean().optional(),
      licensed_runtime_qualified: z.boolean().optional(),
    }).passthrough()),
    blocking_gates: z.array(z.string()),
  }),
  approval: z.object({
    reviewer: z.string(),
    approved_at: z.string(),
    artifact_sha256: z.string(),
  }).passthrough().nullable(),
  downloads: z.object({
    available: z.boolean(),
    target_url: z.string().nullable(),
    review_bundle_url: z.string().nullable(),
  }),
  safety: z.object({
    live_writes_enabled: z.literal(false),
    approval_authorizes_live_deployment: z.literal(false),
  }),
}).passthrough();

const catalogSchema = z.object({
  schema: z.string().nullable().optional(),
  source: z.string().optional(),
  license: z.string().optional(),
}).passthrough();

const graphicsModelSchema = z.object({
  schema: z.string(),
  equipment_name: z.string(),
  equipment_brick_class: z.string().nullable().optional(),
  site: z.string(),
  target: z.string(),
  requirements_status: z.string(),
  niagara_px_emitted: z.boolean(),
  niagara_px_count: z.number(),
  all_declared_views_target_compiled: z.boolean(),
  blocker: z.string().nullable().optional(),
  shop_profile: z.object({
    name: z.string(),
    version: z.string(),
    graphics_theme: z.string().nullable().optional(),
    station_folder: z.string(),
    niagara_site_ord: z.string().nullable().optional(),
  }).passthrough().nullable().optional(),
  views: z.array(z.object({
    id: z.string(),
    title: z.string(),
    template: z.string(),
    navigation_parent: z.string().nullable().optional(),
    widgets: z.array(z.object({
      id: z.string(),
      label: z.string(),
      kind: z.string(),
      data_type: z.string(),
      units: z.string().nullable().optional(),
      brick_class: z.string().nullable().optional(),
      layout_hint: z.object({ x: z.number(), y: z.number() }),
      bacnet: z.object({ device_instance: z.number(), object_id: z.string() }).nullable().optional(),
    }).passthrough()),
  }).passthrough()),
}).passthrough();

const graphicsPlanSchema = z.object({
  schema: z.string(),
  equipment_name: z.string(),
  declared_view_count: z.number(),
  emitted_px_count: z.number(),
  all_declared_views_target_compiled: z.boolean(),
  runtime_gate: z.string(),
  views: z.array(z.object({
    id: z.string(),
    template: z.string(),
    status: z.string(),
    reason: z.string().nullable().optional(),
    points: z.array(z.string()).default([]),
  }).passthrough()),
  safety: z.record(z.string(), z.boolean()),
}).passthrough();

export type RunSummary = z.infer<typeof runSchema>;
export type Readiness = z.infer<typeof readinessSchema>;
export type IntegrationAudit = z.infer<typeof integrationAuditSchema>;
export type SecurityStatus = z.infer<typeof securityStatusSchema>;
export type AuditStatus = z.infer<typeof auditStatusSchema>;
export type RunDetail = z.infer<typeof runDetailSchema>;
export type ControlGraph = z.infer<typeof graphSchema>;
export type TestReport = z.infer<typeof reportSchema>;
export type Point = z.infer<typeof pointSchema>;
export type IntakeInspection = z.infer<typeof intakeInspectionSchema>;
export type AIStatus = z.infer<typeof aiStatusSchema>;
export type ChatTurn = z.infer<typeof chatTurnSchema>;
export type ChatResponse = z.infer<typeof chatResponseSchema>;
export type ProjectRecord = z.infer<typeof projectRecordSchema>;
export type ProjectPreflight = z.infer<typeof projectPreflightSchema>;
export type BacnetLab = z.infer<typeof bacnetLabSchema>;
export type BacnetProbe = z.infer<typeof probeSchema>;
export type BoptestEvidence = z.infer<typeof boptestSchema>;
export type Deliverables = z.infer<typeof deliverablesSchema>;
export type ReleaseSummary = z.infer<typeof releaseSummarySchema>;
export type Catalog = z.infer<typeof catalogSchema>;
export type GraphicsModel = z.infer<typeof graphicsModelSchema>;
export type GraphicsPlan = z.infer<typeof graphicsPlanSchema>;
export type ArtifactState<T> =
  | { state: 'available'; data: T }
  | { state: 'missing' }
  | { state: 'invalid'; message: string };

async function getJson(path: string): Promise<unknown> {
  const response = await fetch(path, { headers: { Accept: 'application/json' } });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Request failed with status ${response.status}`);
  }
  return response.json();
}

async function postJson(path: string, body: unknown): Promise<unknown> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(payload?.detail ?? `Request failed with status ${response.status}`);
  }
  return response.json();
}

async function postForm(path: string, body: FormData): Promise<unknown> {
  const response = await fetch(path, { method: 'POST', headers: { Accept: 'application/json' }, body });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(payload?.detail ?? `Request failed with status ${response.status}`);
  }
  return response.json();
}

async function getArtifact<T>(path: string, schema: z.ZodType<T>): Promise<ArtifactState<T>> {
  const response = await fetch(path, { headers: { Accept: 'application/json' } });
  if (response.status === 404) return { state: 'missing' };
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    return { state: 'invalid', message: body?.detail ?? `Artifact check failed with status ${response.status}` };
  }
  return { state: 'available', data: schema.parse(await response.json()) };
}

export const api = {
  async health() {
    return healthSchema.parse(await getJson('/api/health'));
  },
  async runs() {
    return z.array(runSchema).parse(await getJson('/api/runs'));
  },
  async readiness() {
    return readinessSchema.parse(await getJson('/api/system/readiness'));
  },
  async integrationAudit() {
    return integrationAuditSchema.parse(await getJson('/api/system/integration-audit'));
  },
  async securityStatus() {
    return securityStatusSchema.parse(await getJson('/api/security/status'));
  },
  async securityAuditStatus() {
    return auditStatusSchema.parse(await getJson('/api/security/audit/status'));
  },
  async projects() {
    return z.array(projectRecordSchema).parse(await getJson('/api/projects'));
  },
  async project(projectId: string) {
    return projectRecordSchema.parse(await getJson(`/api/projects/${projectId}`));
  },
  async projectReport(projectId: string) {
    return reportSchema.parse(await getJson(`/api/projects/${projectId}/report`));
  },
  async preflightProject(project: unknown) {
    return projectPreflightSchema.parse(await postJson('/api/projects/preflight', project));
  },
  async buildProject(project: unknown, stationTemplate?: File | null) {
    if (stationTemplate) {
      const body = new FormData();
      body.append('project_json', JSON.stringify(project));
      body.append('station_template', stationTemplate);
      return projectRecordSchema.parse(await postForm('/api/projects/build-import', body));
    }
    return projectRecordSchema.parse(await postJson('/api/projects/build', project));
  },
  async approveProject(projectId: string, reviewer: string) {
    return projectRecordSchema.parse(await postJson(`/api/projects/${projectId}/approve`, { reviewer }));
  },
  async aiStatus() {
    return aiStatusSchema.parse(await getJson('/api/ai/status'));
  },
  async run(runId: string) {
    return runDetailSchema.parse(await getJson(`/api/runs/${runId}`));
  },
  async graph(runId: string) {
    return graphSchema.parse(await getJson(`/api/runs/${runId}/graph`));
  },
  async report(runId: string) {
    return reportSchema.parse(await getJson(`/api/runs/${runId}/report`));
  },
  async bacnetLab(runId: string) {
    return getArtifact(`/api/runs/${runId}/bacnet-lab-manifest`, bacnetLabSchema);
  },
  async probeBacnetLab(runId: string) {
    return probeSchema.parse(await postJson(`/api/runs/${runId}/bacnet-lab/probe`, {}));
  },
  async boptest(runId: string) {
    return getArtifact(`/api/runs/${runId}/verify/boptest`, boptestSchema);
  },
  async deliverables(runId: string) {
    return getArtifact(`/api/runs/${runId}/deliverables`, deliverablesSchema);
  },
  async releaseSummary(runId: string) {
    return releaseSummarySchema.parse(await getJson(`/api/runs/${runId}/release-summary`));
  },
  async graphicsModel(runId: string) {
    return getArtifact(`/api/runs/${runId}/graphics-model`, graphicsModelSchema);
  },
  async graphicsPlan(runId: string) {
    return getArtifact(`/api/runs/${runId}/niagara-graphics-plan`, graphicsPlanSchema);
  },
  async environment(runId: string) {
    return getArtifact(`/api/runs/${runId}/environment-manifest`, z.record(z.string(), z.unknown()));
  },
  async libraryCatalogs() {
    const [g36, plant, faults, aixocat, niagara, ctrlFlow] = await Promise.all([
      getJson('/api/library/g36/controllers'),
      getJson('/api/library/plant-controls/controllers'),
      getJson('/api/library/open-control/faults'),
      getJson('/api/library/aixocat/patterns'),
      getJson('/api/library/niagara-programs'),
      getJson('/api/library/ctrl-flow/templates'),
    ]);
    return {
      g36: catalogSchema.parse(g36),
      plant: catalogSchema.parse(plant),
      faults: catalogSchema.parse(faults),
      aixocat: catalogSchema.parse(aixocat),
      niagara: catalogSchema.parse(niagara),
      ctrlFlow: catalogSchema.parse(ctrlFlow),
    };
  },
  async approve(runId: string, reviewer: string) {
    return runDetailSchema.parse(await postJson(`/api/runs/${runId}/approve`, { reviewer }));
  },
  async inspectIntake(body: FormData) {
    return intakeInspectionSchema.parse(await postForm('/api/intake/inspect', body));
  },
  async importRun(body: FormData) {
    return runDetailSchema.parse(await postForm('/api/runs/import', body));
  },
  async chat(runId: string, message: string, history: ChatTurn[]) {
    const safeHistory = z.array(chatTurnSchema).max(20).parse(history);
    return chatResponseSchema.parse(await postJson(`/api/runs/${runId}/chat`, { message, history: safeHistory }));
  },
};
