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
  alfalfa_verification_path: z.string().nullable().optional(),
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
  // Why the roles are unconfigured: a missing key, or a configured key whose
  // SDK extra was never installed. The UI shows this instead of guessing.
  unavailable_reason: z.string().nullable().optional(),
}).passthrough();

const optionalCapabilitySchema = z.object({
  distribution: z.string(),
  module: z.string(),
  extra: z.string(),
  capability: z.string(),
  installed: z.boolean(),
  version: z.string().nullable(),
  remediation: z.string().nullable(),
});

const optionalCapabilitiesSchema = z.object({
  schema: z.literal('bactalk.optional-capabilities/v1'),
  dependencies: z.array(optionalCapabilitySchema),
  all_installed: z.boolean(),
  bootstrap_command: z.string(),
});

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
const boptestCatalogSchema = z.object({
  schema: z.literal('bactalk.boptest-catalog/v1'),
  version: z.unknown(),
  test_cases: z.array(z.string()),
  live_building_writes: z.literal(false),
});
const boptestSignalSchema = z.object({
  name: z.string(),
  unit: z.string().nullable(),
  description: z.string().nullable(),
  minimum: z.number().nullable(),
  maximum: z.number().nullable(),
  activation_signal: z.boolean(),
});
const boptestTestCaseContractSchema = z.object({
  schema: z.literal('bactalk.boptest-test-case-contract/v1'),
  version: z.unknown(),
  test_case: z.string(),
  measurements: z.array(boptestSignalSchema),
  inputs: z.array(boptestSignalSchema),
  measurement_count: z.number(),
  input_count: z.number(),
  clean_stop: z.literal(true),
  initialized: z.literal(false),
  live_building_writes: z.literal(false),
});
const boptestRuntimeSchema = z.object({
    runtime: z.string(),
    test_case: z.string(),
    graph_name: z.string(),
    graph_sha256: z.string(),
    step_seconds: z.number(),
    steps: z.number(),
    measurement_catalog_count: z.number(),
    input_catalog_count: z.number(),
    scenario_request: z.record(z.string(), z.unknown()).nullable().optional(),
    scenario_state: z.record(z.string(), z.unknown()).nullable().optional(),
    scenario_initialized_model: z.boolean().optional(),
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
  }).passthrough();
const trajectoryCounterexampleSchema = z.object({
  schema: z.literal('bactalk.trajectory-counterexample/v1'),
  violation_count: z.number().int().positive(),
  first_violation_time: z.number(),
  last_violation_time: z.number(),
  peak_error_time: z.number(),
  peak_error: z.number(),
  peak_absolute_error: z.number().nonnegative(),
  context_samples: z.number().int().nonnegative(),
  window: z.object({
    start_index: z.number().int().nonnegative(),
    end_index: z.number().int().nonnegative(),
    test_times: z.array(z.number()),
    test_values: z.array(z.number()),
  }).passthrough(),
}).passthrough();
const boptestOracleResultSchema = z.object({
    completed: z.boolean(),
    passed: z.boolean(),
    max_error: z.number().nullable(),
    pyfunnel_status_code: z.number(),
    test_times: z.array(z.number()),
    test_values: z.array(z.number()),
    counterexample: trajectoryCounterexampleSchema.nullable().optional(),
    oracle: z.object({
      id: z.string(),
      signal: z.string(),
      signal_kind: z.string(),
      reference_times: z.array(z.number()),
      reference_values: z.array(z.number()),
      absolute_time_tolerance: z.number(),
      absolute_value_tolerance: z.number(),
    }).passthrough(),
  }).passthrough();
const boptestEvidenceBase = {
  status: z.enum(['pass', 'fail']),
  run_id: z.string(),
  approval_allowed: z.boolean(),
  live_building_writes: z.literal(false),
};
const boptestSingleSchema = z.object({
  schema: z.literal('bactalk.boptest-qualification/v1'),
  ...boptestEvidenceBase,
  runtime: boptestRuntimeSchema,
  oracles: z.array(boptestOracleResultSchema).default([]),
}).passthrough();
const boptestSuiteSchema = z.object({
  schema: z.literal('bactalk.boptest-qualification-suite/v1'),
  ...boptestEvidenceBase,
  case_count: z.number().int().positive(),
  total_steps: z.number().int().positive(),
  cases: z.array(z.object({
    id: z.string(),
    status: z.enum(['pass', 'fail']),
    runtime: boptestRuntimeSchema,
    oracles: z.array(boptestOracleResultSchema).default([]),
    oracle_clock: z.object({
      basis: z.literal('elapsed_seconds_from_run_start'),
      runtime_time_origin: z.number(),
    }).passthrough(),
    report_directory: z.string(),
  }).passthrough()).min(1),
}).passthrough();
const boptestSchema = z.discriminatedUnion('schema', [boptestSingleSchema, boptestSuiteSchema]);

const alfalfaEvidenceSchema = z.object({
  schema: z.literal('bactalk.alfalfa-graph-run/v1'),
  status: z.enum(['pass', 'fail']),
  runtime: z.literal('Alfalfa'),
  run_id: z.string(),
  bactalk_run_id: z.string().optional(),
  approval_allowed: z.boolean(),
  live_building_writes: z.literal(false),
  status_after_start: z.string(),
  status_after_stop: z.string(),
  model_name: z.string(),
  model_sha256: z.string(),
  graph_name: z.string(),
  graph_sha256: z.string(),
  runtime_input_count: z.number().int().nonnegative(),
  runtime_output_count: z.number().int().nonnegative(),
  start: z.string(),
  end: z.string(),
  step_seconds: z.number().positive(),
  steps: z.number().int().positive(),
  clean_stop: z.literal(true),
  control_transport: z.object({
    kind: z.literal('bacnet_ip_loopback'),
    protocol: z.string(),
    controller_runtime: z.string(),
    write_priority: z.number().int(),
    manifest_sha256: z.string(),
    mapped_point_count: z.number().int().nonnegative(),
    read_transaction_count: z.number().int().nonnegative(),
    write_transaction_count: z.number().int().nonnegative(),
    readbacks_matched: z.literal(true),
    bind_scope: z.string(),
    live_network_routes_allowed: z.literal(false),
    writes_affect_virtual_objects_only: z.literal(true),
    licensed_niagara_runtime: z.literal(false),
  }).passthrough().optional(),
  oracles: z.array(z.object({
    completed: z.boolean(),
    passed: z.boolean(),
    max_error: z.number().nullable(),
    pyfunnel_status_code: z.number(),
    test_times: z.array(z.number()),
    test_values: z.array(z.number()),
    counterexample: trajectoryCounterexampleSchema.nullable().optional(),
    report_directory: z.string(),
    oracle: z.object({
      id: z.string(),
      signal_kind: z.enum(['graph_input', 'graph_output', 'fmu_input', 'fmu_output']),
      signal: z.string(),
      reference_times: z.array(z.number()),
      reference_values: z.array(z.number()),
      absolute_time_tolerance: z.number(),
      absolute_value_tolerance: z.number(),
    }).passthrough(),
  }).passthrough()).default([]),
  trajectory: z.array(z.object({
    index: z.number().int().nonnegative(),
    start_time: z.string(),
    end_time: z.string(),
    graph_inputs: numericMap,
    initial_output_values: numericMap,
    controller_outputs: numericMap,
    fmu_inputs: numericMap,
    observed_outputs: numericMap,
    command_echoes: z.record(z.string(), z.object({
      output: z.string(),
      command: z.number(),
      feedback: z.number(),
      matched: z.boolean(),
    }).passthrough()),
  }).passthrough()),
}).passthrough();

const qualificationJobSchema = z.object({
  schema_version: z.enum(['bactalk.qualification-job/v1', 'bactalk.qualification-job/v2', 'bactalk.qualification-job/v3']),
  id: z.string(),
  broker_job_id: z.string(),
  run_id: z.string(),
  candidate_artifact_sha256: z.string().nullable(),
  kind: z.enum(['alfalfa', 'boptest']),
  transport: z.enum(['direct', 'bacnet_ip_loopback', 'boptest_rest']),
  status: z.enum(['queued', 'running', 'cancel_requested', 'canceled', 'succeeded', 'failed']),
  model_filename: z.string().nullable(),
  model_sha256: z.string().nullable(),
  request_sha256: z.string(),
  input_sha256: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
  started_at: z.string().nullable(),
  completed_at: z.string().nullable(),
  heartbeat_at: z.string().nullable(),
  lease_expires_at: z.string().nullable(),
  worker_id: z.string().nullable(),
  actor_id: z.string().nullable(),
  tenant_id: z.string().nullable(),
  progress: z.object({
    phase: z.string(),
    completed_steps: z.number().int().nonnegative(),
    total_steps: z.number().int().nonnegative(),
    percent: z.number().min(0).max(100),
  }),
  cancellation_requested: z.boolean(),
  error: z.string().nullable(),
  result_artifact_sha256: z.string().nullable(),
  qualification_passed: z.boolean().nullable(),
}).passthrough();

const fmiVariableSchema = z.object({
  name: z.string(),
  value_reference: z.string().nullable(),
  causality: z.string(),
  variability: z.string().nullable(),
  initial: z.string().nullable(),
  data_type: z.string(),
  unit: z.string().nullable(),
  minimum: z.string().nullable(),
  maximum: z.string().nullable(),
  start: z.string().nullable(),
  description: z.string().nullable(),
});

const fmiModelSchema = z.object({
  schema: z.literal('bactalk.fmi-model-description/v1'),
  filename: z.string(),
  sha256: z.string(),
  bytes: z.number().int().nonnegative(),
  fmi_version: z.string(),
  model_name: z.string(),
  guid: z.string().nullable(),
  instantiation_token: z.string().nullable(),
  generation_tool: z.string().nullable(),
  model_identifiers: z.array(z.string()),
  platforms: z.array(z.string()),
  inputs: z.array(fmiVariableSchema),
  outputs: z.array(fmiVariableSchema),
  parameter_count: z.number().int().nonnegative(),
  local_variable_count: z.number().int().nonnegative(),
  variable_count: z.number().int().nonnegative(),
  live_building_writes: z.literal(false),
});

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

const ctrlFlowFieldSchema = z.object({
  selection_path: z.string(),
  instance_path: z.string(),
  name: z.string(),
  selection_type: z.string(),
  value: z.unknown(),
  choices: z.array(z.object({ value: z.string(), label: z.string() })).optional(),
  boolean_choices: z.array(z.boolean()).optional(),
}).passthrough();

const ctrlFlowConfigurationSchema = z.object({
  schema: z.string(),
  configuration_digest: z.string(),
  accepted_selection_count: z.number(),
  rejected_selection_count: z.number(),
  selections: z.record(z.string(), z.unknown()),
  fields: z.array(ctrlFlowFieldSchema),
}).passthrough();

const ctrlFlowBriefSchema = z.object({
  schema: z.literal('bactalk.ctrl-flow-programming-brief/v1'),
  status: z.string(),
  configuration_digest: z.string(),
  design_binding: z.object({
    equipment_family: z.string(),
    controller_id: z.string(),
  }).passthrough(),
  components: z.array(z.object({
    id: z.string(),
    type: z.string(),
    quantity: z.union([z.string(), z.number()]),
  }).passthrough()),
  point_requirements: z.object({
    required_count: z.number(),
    conditional_count: z.number(),
    points: z.array(z.object({
      id: z.string(),
      label: z.string(),
      role: z.string(),
      data_type: z.string(),
      units: z.string().nullable(),
      required: z.boolean(),
      condition: z.string(),
      subsystem: z.string(),
    }).passthrough()),
  }).passthrough(),
  qualification_plan: z.object({
    scenario_count: z.number(),
    required_count: z.number(),
    scenarios: z.array(z.object({
      id: z.string(),
      title: z.string(),
      level: z.string(),
      status: z.string(),
    }).passthrough()),
    execution_status: z.string(),
  }).passthrough(),
  capability_alignment: z.object({
    candidate_packs: z.array(z.object({
      id: z.string(),
      name: z.string(),
      stage: z.string(),
      status: z.string(),
      production_ready: z.boolean(),
    }).passthrough()),
    reference_controller_available: z.boolean(),
    complete_niagara_job_ready: z.boolean(),
  }).passthrough(),
  release_blockers: z.array(z.string()),
}).passthrough();

const ctrlFlowReconciliationSchema = z.object({
  schema: z.literal('bactalk.ctrl-flow-point-reconciliation/v1'),
  point_reconciliation_id: z.string(),
  provided_point_count: z.number(),
  required_point_count: z.number(),
  matched_requirement_count: z.number(),
  missing_required_count: z.number(),
  missing_required: z.array(z.string()),
  ambiguous: z.array(z.record(z.string(), z.unknown())),
  duplicates: z.array(z.record(z.string(), z.unknown())),
  unmatched_provided: z.array(z.record(z.string(), z.unknown())),
  unit_conversions: z.array(z.record(z.string(), z.unknown())),
  blocking_issues: z.array(z.record(z.string(), z.unknown())),
  ready_for_sequence_reconciliation: z.boolean(),
  complete_niagara_job_ready: z.boolean(),
  retention: z.object({
    artifact_digest: z.string(),
    result_digest: z.string(),
    source_sha256: z.string(),
    source_bytes_retained: z.boolean(),
    external_immutable_retention: z.boolean(),
  }).passthrough(),
}).passthrough();

const ctrlFlowSequenceReconciliationSchema = z.object({
  schema: z.literal('bactalk.ctrl-flow-sequence-reconciliation/v1'),
  source_document: z.object({
    filename: z.string(),
    media_type: z.string(),
    sha256: z.string(),
    character_count: z.number(),
  }).passthrough(),
  scenario_count: z.number(),
  all_facets_mentioned_count: z.number(),
  partial_count: z.number(),
  not_mentioned_count: z.number(),
  coverage_rule_missing_count: z.number(),
  missing_facet_count: z.number(),
  language_coverage_complete: z.boolean(),
  scenarios: z.array(z.object({
    id: z.string(),
    title: z.string(),
    level: z.string(),
    coverage_status: z.enum(['all-facets-mentioned', 'partial', 'not-mentioned', 'coverage-rule-missing']),
    facet_count: z.number(),
    mentioned_facet_count: z.number(),
    missing_facets: z.array(z.string()),
    facets: z.array(z.object({
      id: z.string(),
      label: z.string(),
      mentioned: z.boolean(),
      evidence: z.array(z.object({
        matched_text: z.string(),
        start: z.number(),
        end: z.number(),
        excerpt: z.string(),
      })),
    })),
  })),
  requirement_candidates: z.object({
    schema: z.literal('bactalk.sequence-requirement-candidates/v1'),
    candidate_digest: z.string(),
    quantity_count: z.number(),
    duration_count: z.number(),
    threshold_count: z.number(),
    action_count: z.number(),
    policy_count: z.number(),
    unresolved_count: z.number(),
    single_candidate_binding_count: z.number(),
    available_review_points: z.array(z.object({
      id: z.string(),
      label: z.string(),
      role: z.string(),
      data_type: z.string(),
      units: z.string().nullable(),
    })),
    quantities: z.array(z.object({
      id: z.string(),
      kind: z.string(),
      usage: z.string(),
      canonical: z.object({
        value: z.number(),
        unit: z.string(),
        dimension: z.string(),
      }),
      comparison: z.string().nullable(),
      timing_relation: z.string().nullable(),
      input_point_candidates: z.array(z.string()),
      point_binding_status: z.string(),
      source: z.object({ clause: z.string() }).passthrough(),
      approved: z.literal(false),
    }).passthrough()),
    actions: z.array(z.object({
      id: z.string(),
      verb: z.string(),
      subject: z.string(),
      point_candidates: z.array(z.string()),
      point_binding_status: z.string(),
      source: z.object({ clause: z.string() }).passthrough(),
      approved: z.literal(false),
    }).passthrough()),
    policies: z.array(z.object({
      id: z.string(),
      policy: z.string(),
      source: z.object({ clause: z.string() }).passthrough(),
      approved: z.literal(false),
    }).passthrough()),
    unresolved: z.array(z.object({
      id: z.string(),
      kind: z.string(),
      text: z.string(),
      blocking_reason: z.string(),
      source: z.object({ clause: z.string() }).passthrough(),
    }).passthrough()),
    ready_for_graph_generation: z.literal(false),
    approval_required: z.literal(true),
    next_gate: z.string(),
  }),
  gate: z.enum(['engineer-review-required', 'blocked-missing-or-partial-sequence-language']),
  ready_for_code_generation: z.literal(false),
  semantic_validation_complete: z.literal(false),
  engineer_review_required: z.literal(true),
  limitations: z.array(z.string()),
}).passthrough();

const ctrlFlowSequenceReviewSchema = z.object({
  schema: z.literal('bactalk.sequence-requirement-review/v1'),
  review_id: z.string(),
  candidate_digest: z.string(),
  review_digest: z.string(),
  configuration_digest: z.string(),
  source_sha256: z.string(),
  point_contract: z.object({
    schema: z.literal('bactalk.sequence-review-point-contract/v1'),
    points: z.array(z.object({
      id: z.string(),
      label: z.string(),
      role: z.string(),
      data_type: z.enum(['numeric', 'boolean']),
      units: z.string().nullable().optional(),
      required: z.boolean(),
    }).passthrough()),
  }),
  review: z.object({
    reviewer: z.string(),
    authentication: z.string(),
    reviewed_at: z.string(),
    decision_count: z.number(),
    decisions: z.array(z.record(z.string(), z.unknown())),
  }).passthrough(),
  oracle_draft_count: z.number(),
  authorable_manual_facet_count: z.number(),
  oracle_drafts: z.array(z.object({
    id: z.string(),
    conditions: z.array(z.object({
      point: z.string(),
      operator: z.enum(['lt', 'le', 'gt', 'ge', 'eq']),
      value: z.number(),
      unit: z.string(),
      point_unit: z.string().nullable().optional(),
    }).passthrough()),
    durations: z.array(z.object({
      seconds: z.number(),
      relation: z.string(),
    }).passthrough()),
    expectations: z.array(z.object({
      point: z.string(),
      operator: z.literal('eq'),
      value: z.union([z.number(), z.boolean()]),
      verb: z.string(),
    }).passthrough()),
    status: z.literal('draft-independent-oracle-required'),
    executable: z.literal(false),
  }).passthrough()),
  scenario_oracle_coverage: z.array(z.object({
    id: z.string(),
    title: z.string(),
    phrase_coverage_status: z.string(),
    all_facets_have_oracle_drafts: z.boolean(),
    facets: z.array(z.object({
      id: z.string(),
      label: z.string(),
      phrase_mentioned: z.boolean(),
      oracle_draft_ids: z.array(z.string()),
      executable_oracle_draft_present: z.boolean(),
    }).passthrough()),
  }).passthrough()),
  all_scenario_facets_have_oracle_drafts: z.boolean(),
  scenario_oracle_gap_count: z.number(),
  manual_facet_oracle_requirements: z.array(z.object({
    scenario_id: z.string(),
    scenario_title: z.string(),
    facet_id: z.string(),
    facet_label: z.string(),
    phrase_mentioned: z.boolean(),
    source_evidence: z.array(z.object({
      start: z.number(),
      end: z.number(),
      excerpt: z.string(),
    }).passthrough()),
    input_point_candidates: z.array(z.string()),
    output_point_candidates: z.array(z.string()),
    io_contract_status: z.string(),
    authoring_allowed: z.boolean(),
    blocking_reason: z.string(),
  }).passthrough()),
  skipped_relationships: z.array(z.record(z.string(), z.unknown())),
  blockers: z.array(z.string()),
  ready_for_independent_oracle_authoring: z.boolean(),
  ready_for_graph_generation: z.literal(false),
  ready_for_deployment: z.literal(false),
  next_gate: z.string(),
  retention: z.object({
    schema: z.literal('bactalk.sequence-requirement-review-record/v1'),
    artifact_digest: z.string(),
    created_at: z.string(),
    source_bytes_retained: z.literal(true),
    storage: z.literal('append-only-local-hash-verified'),
    external_immutable_retention: z.literal(false),
  }),
}).passthrough();

const sequenceOracleApprovalSchema = z.object({
  schema: z.literal('bactalk.sequence-oracle-approval/v1'),
  oracle_approval_id: z.string(),
  review_id: z.string(),
  review_artifact_digest: z.string(),
  review_digest: z.string(),
  source_sha256: z.string(),
  oracle_digest: z.string(),
  approval: z.object({
    author: z.string(),
    approved_at: z.string(),
    independent_from_requirement_reviewer: z.literal(true),
  }).passthrough(),
  case_count: z.number(),
  acceptance_cases: z.array(z.record(z.string(), z.unknown())),
  validation_evidence: z.array(z.record(z.string(), z.unknown())),
  approved_oracle_gate_passed: z.literal(true),
  sequence_requirement_gate_passed: z.boolean(),
  ready_for_graph_generation: z.boolean(),
  ready_for_deployment: z.literal(false),
  scenario_oracle_gap_count: z.number().nullable(),
  next_gate: z.string(),
  retention: z.object({
    schema: z.literal('bactalk.sequence-oracle-approval-record/v1'),
    artifact_digest: z.string(),
    created_at: z.string(),
    storage: z.literal('append-only-local-hash-verified'),
    external_immutable_retention: z.literal(false),
  }),
}).passthrough();

const g36ParameterSchema = z.object({
  schema: z.literal('bactalk.g36-parameter-schema/v1'),
  controller: z.object({ id: z.string(), name: z.string() }).passthrough(),
  parameterization: z.object({
    required_parameters: z.array(z.string()),
    parameters: z.array(z.object({
      name: z.string(),
      data_type: z.string(),
      is_array: z.boolean(),
      required: z.boolean(),
      value: z.unknown().nullable(),
      description: z.string().nullable(),
      unit: z.string().nullable(),
    }).passthrough()),
  }).passthrough(),
}).passthrough();

const sequenceCandidatePreflightSchema = z.object({
  schema: z.literal('bactalk.sequence-candidate-preflight/v1'),
  oracle_approval_id: z.string(),
  controller_id: z.string(),
  execution_profile: z.string(),
  parameter_contract: g36ParameterSchema,
  provided_parameter_names: z.array(z.string()),
  point_bindings: z.record(z.string(), z.string()),
  translation: z.record(z.string(), z.unknown()),
  candidate_graph: z.object({
    sha256: z.string(),
    block_count: z.number(),
    link_count: z.number(),
    boundary_count: z.number(),
  }).passthrough().nullable(),
  graph_boundary_contract: z.array(z.object({
    id: z.string(),
    label: z.string(),
    direction: z.enum(['input', 'output']),
    data_type: z.enum(['numeric', 'boolean']),
    selected_design_point: z.string().nullable().optional(),
    compatible_design_points: z.array(z.string()),
  }).passthrough()).optional(),
  boundary_bindings: z.array(z.object({
    design_point: z.string(),
    graph_boundary: z.string(),
    contractor_source: z.string(),
  }).passthrough()).optional(),
  test_report: reportSchema.nullable(),
  blockers: z.array(z.object({
    code: z.string(),
    message: z.string(),
    details: z.record(z.string(), z.unknown()),
  }).passthrough()),
  ready_for_candidate_generation: z.boolean(),
  ready_for_deployment: z.literal(false),
}).passthrough();

const sequenceCandidateGenerationSchema = z.object({
  schema: z.literal('bactalk.sequence-candidate-generation/v1'),
  preflight: sequenceCandidatePreflightSchema,
  run: runDetailSchema,
  safety: z.object({
    live_writes_enabled: z.literal(false),
    human_approval_required: z.literal(true),
    candidate_retained: z.literal(true),
    candidate_authorizes_deployment: z.literal(false),
  }).passthrough(),
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
export type OptionalCapabilities = z.infer<typeof optionalCapabilitiesSchema>;
export type ChatTurn = z.infer<typeof chatTurnSchema>;
export type ChatResponse = z.infer<typeof chatResponseSchema>;
export type ProjectRecord = z.infer<typeof projectRecordSchema>;
export type ProjectPreflight = z.infer<typeof projectPreflightSchema>;
export type BacnetLab = z.infer<typeof bacnetLabSchema>;
export type BacnetProbe = z.infer<typeof probeSchema>;
export type BoptestEvidence = z.infer<typeof boptestSchema>;
export type BoptestCatalog = z.infer<typeof boptestCatalogSchema>;
export type BoptestSignal = z.infer<typeof boptestSignalSchema>;
export type BoptestTestCaseContract = z.infer<typeof boptestTestCaseContractSchema>;
export type AlfalfaEvidence = z.infer<typeof alfalfaEvidenceSchema>;
export type QualificationJob = z.infer<typeof qualificationJobSchema>;
export type FmiVariable = z.infer<typeof fmiVariableSchema>;
export type FmiModel = z.infer<typeof fmiModelSchema>;
export type Deliverables = z.infer<typeof deliverablesSchema>;
export type ReleaseSummary = z.infer<typeof releaseSummarySchema>;
export type Catalog = z.infer<typeof catalogSchema>;
export type CtrlFlowConfiguration = z.infer<typeof ctrlFlowConfigurationSchema>;
export type CtrlFlowBrief = z.infer<typeof ctrlFlowBriefSchema>;
export type CtrlFlowReconciliation = z.infer<typeof ctrlFlowReconciliationSchema>;
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
    const payload = await response.json().catch(() => null) as { detail?: unknown; message?: unknown } | null;
    const detail = payload?.detail ?? payload?.message;
    throw new Error(typeof detail === 'string' ? detail : detail ? JSON.stringify(detail) : `Request failed with status ${response.status}`);
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
  async optionalCapabilities() {
    return optionalCapabilitiesSchema.parse(await getJson('/api/system/optional-capabilities'));
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
  async boptestCatalog() {
    return boptestCatalogSchema.parse(await getJson('/api/integrations/boptest/catalog'));
  },
  async inspectBoptestTestCase(testCase: string) {
    return boptestTestCaseContractSchema.parse(
      await getJson(`/api/integrations/boptest/catalog/${encodeURIComponent(testCase)}`),
    );
  },
  async alfalfa(runId: string) {
    return getArtifact(`/api/runs/${runId}/verify/alfalfa`, alfalfaEvidenceSchema);
  },
  async enqueueAlfalfaQualification(runId: string, model: File, qualification: { mapping: unknown; oracles: unknown[]; steps: number; step_seconds: number; start: string; transport?: 'direct' | 'bacnet_ip_loopback' }) {
    const body = new FormData();
    body.append('model_file', model);
    body.append('qualification', JSON.stringify(qualification));
    return qualificationJobSchema.parse(
      await postForm(`/api/runs/${runId}/qualification-jobs/alfalfa`, body),
    );
  },
  async enqueueBoptestQualification(runId: string, qualification: { mapping: unknown; cases?: unknown[]; oracles?: unknown[]; steps?: number; step_seconds?: number; start_time?: number; warmup_period?: number; scenario?: Record<string, unknown> }) {
    return qualificationJobSchema.parse(
      await postJson(`/api/runs/${runId}/qualification-jobs/boptest`, qualification),
    );
  },
  async latestQualificationJob(runId: string) {
    return getArtifact(`/api/runs/${runId}/qualification-jobs/latest`, qualificationJobSchema);
  },
  async cancelQualificationJob(jobId: string) {
    return qualificationJobSchema.parse(
      await postJson(`/api/qualification-jobs/${jobId}/cancel`, {}),
    );
  },
  async inspectAlfalfaFmu(model: File) {
    const body = new FormData();
    body.append('model_file', model);
    return fmiModelSchema.parse(
      await postForm('/api/integrations/alfalfa/inspect-fmu', body),
    );
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
  async ctrlFlowConfigure(templateId: string, selections: Record<string, unknown>) {
    return ctrlFlowConfigurationSchema.parse(await postJson(
      `/api/library/ctrl-flow/templates/${encodeURIComponent(templateId)}/configure`,
      { selections },
    ));
  },
  async ctrlFlowProgrammingBrief(templateId: string, selections: Record<string, unknown>) {
    return ctrlFlowBriefSchema.parse(await postJson(
      `/api/library/ctrl-flow/templates/${encodeURIComponent(templateId)}/programming-brief`,
      { selections },
    ));
  },
  async inspectCtrlFlowPoints(templateId: string, selections: Record<string, unknown>, file: File) {
    const body = new FormData();
    body.append('selections', JSON.stringify(selections));
    body.append('points_file', file);
    return ctrlFlowReconciliationSchema.parse(await postForm(
      `/api/library/ctrl-flow/templates/${encodeURIComponent(templateId)}/inspect-points`,
      body,
    ));
  },
  async inspectCtrlFlowSequence(templateId: string, selections: Record<string, unknown>, file: File) {
    const body = new FormData();
    body.append('selections', JSON.stringify(selections));
    body.append('sequence_document', file);
    return ctrlFlowSequenceReconciliationSchema.parse(await postForm(
      `/api/library/ctrl-flow/templates/${encodeURIComponent(templateId)}/inspect-sequence`,
      body,
    ));
  },
  async approveCtrlFlowSequenceRequirements(templateId: string, selections: Record<string, unknown>, file: File, pointReconciliationId: string, review: Record<string, unknown>) {
    const body = new FormData();
    body.append('selections', JSON.stringify(selections));
    body.append('review', JSON.stringify(review));
    body.append('sequence_document', file);
    body.append('point_reconciliation_id', pointReconciliationId);
    return ctrlFlowSequenceReviewSchema.parse(await postForm(
      `/api/library/ctrl-flow/templates/${encodeURIComponent(templateId)}/review-requirements/approve`,
      body,
    ));
  },
  async approveSequenceOracles(reviewId: string, approval: Record<string, unknown>) {
    return sequenceOracleApprovalSchema.parse(await postJson(
      `/api/sequence-requirement-reviews/${encodeURIComponent(reviewId)}/oracles/approve`,
      approval,
    ));
  },
  async g36Parameters(controllerId: string) {
    return g36ParameterSchema.parse(await getJson(
      `/api/library/g36/controllers/${encodeURIComponent(controllerId)}/parameters`,
    ));
  },
  async preflightSequenceCandidate(approvalId: string, request: Record<string, unknown>) {
    return sequenceCandidatePreflightSchema.parse(await postJson(
      `/api/sequence-oracle-approvals/${encodeURIComponent(approvalId)}/candidate-preflight`,
      request,
    ));
  },
  async generateSequenceCandidate(approvalId: string, request: Record<string, unknown>) {
    return sequenceCandidateGenerationSchema.parse(await postJson(
      `/api/sequence-oracle-approvals/${encodeURIComponent(approvalId)}/candidate`,
      request,
    ));
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
