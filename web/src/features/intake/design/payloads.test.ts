import { describe, expect, it } from 'vitest';

import type { CtrlFlowSequenceReconciliation, CtrlFlowSequenceReview, SequenceOracleApproval } from '../../../api/client';
import {
  buildCandidateRequest,
  buildOracleApproval,
  buildReviewRequest,
  compatiblePoints,
  decisionComplete,
  initialFacetDrafts,
  initialOracleDrafts,
  oraclesComplete,
  parseParameter,
  reviewComplete,
  reviewItems,
} from './payloads';

const candidates = {
  schema: 'bactalk.sequence-requirement-candidates/v1',
  candidate_digest: 'a'.repeat(64),
  quantity_count: 1,
  duration_count: 0,
  threshold_count: 1,
  action_count: 1,
  policy_count: 1,
  unresolved_count: 1,
  single_candidate_binding_count: 0,
  available_review_points: [
    { id: 'MixedAirTemp', label: 'MAT', role: 'sensor', data_type: 'numeric', units: '°F' },
    { id: 'SupplyFanCommand', label: 'Fan', role: 'command', data_type: 'boolean', units: null },
    { id: 'DuctStatic', label: 'Static', role: 'sensor', data_type: 'numeric', units: 'inH2O' },
  ],
  quantities: [{ id: 'seqreq-0000000000000001', kind: 'threshold', usage: 'u', canonical: { value: 38, unit: 'degF', dimension: 'temperature' }, comparison: 'lt', timing_relation: null, input_point_candidates: ['MixedAirTemp'], point_binding_status: 'single', source: { clause: 'below 38 °F' }, approved: false as const }],
  durations: [],
  thresholds: [],
  actions: [{ id: 'seqreq-0000000000000002', verb: 'stop', subject: 'supply fan', point_candidates: [], point_binding_status: 'none', source: { clause: 'stop the supply fan' }, approved: false as const }],
  policies: [{ id: 'seqreq-0000000000000003', policy: 'fail-safe', source: { clause: 'fail safe' }, approved: false as const }],
  unresolved: [{ id: 'seqreq-0000000000000004', kind: 'vague-duration', text: 'a while', blocking_reason: 'no number', source: { clause: 'for a while' } }],
  ready_for_graph_generation: false as const,
  approval_required: true as const,
  next_gate: 'review',
} as unknown as CtrlFlowSequenceReconciliation['requirement_candidates'];

describe('requirement review', () => {
  const items = reviewItems(candidates);

  it('derives one item per candidate with point needs', () => {
    expect(items.map((item) => item.group)).toEqual(['quantity', 'action', 'policy', 'unresolved']);
    expect(items[0].needsPoint).toBe(true);
    expect(items[1].needsPoint).toBe(true);
    expect(items[3].unresolved).toBe(true);
    expect(compatiblePoints(items[1], candidates.available_review_points).map((point) => point.id)).toEqual(['SupplyFanCommand']);
    expect(compatiblePoints(items[0], candidates.available_review_points).map((point) => point.id)).toEqual(['MixedAirTemp']);
  });

  it('requires an explicit, justified decision for every item', () => {
    expect(decisionComplete(items[0], undefined)).toBe(false);
    expect(decisionComplete(items[0], { disposition: 'approve' })).toBe(true);
    expect(decisionComplete(items[1], { disposition: 'approve' })).toBe(false);
    expect(decisionComplete(items[1], { disposition: 'approve', selected_point: 'SupplyFanCommand' })).toBe(true);
    expect(decisionComplete(items[2], { disposition: 'reject', note: 'x' })).toBe(false);
    expect(decisionComplete(items[2], { disposition: 'reject', note: 'not in scope' })).toBe(true);
    expect(decisionComplete(items[3], { disposition: 'approve' })).toBe(false);
    expect(decisionComplete(items[3], { disposition: 'resolve', replacement_text: 'for 5 minutes' })).toBe(true);
    const decisions = {
      [items[0].id]: { disposition: 'approve' as const },
      [items[1].id]: { disposition: 'approve' as const, selected_point: 'SupplyFanCommand' },
      [items[2].id]: { disposition: 'reject' as const, note: 'not in scope' },
      [items[3].id]: { disposition: 'resolve' as const, replacement_text: 'for 5 minutes' },
    };
    expect(reviewComplete(items, decisions, 'E')).toBe(false);
    expect(reviewComplete(items, decisions, 'Engineer')).toBe(true);
    const request = buildReviewRequest(candidates, items, decisions, 'Engineer ');
    expect(request.reviewer).toBe('Engineer');
    expect(request.decisions[1]).toEqual({ candidate_id: items[1].id, disposition: 'approve', selected_point: 'SupplyFanCommand' });
    expect(request.decisions[3]).toEqual({ candidate_id: items[3].id, disposition: 'resolve', replacement_text: 'for 5 minutes' });
  });
});

const review = {
  review_id: 'r'.repeat(32),
  retention: { artifact_digest: 'b'.repeat(64) },
  point_contract: {
    points: [
      { id: 'MixedAirTemp', data_type: 'numeric' },
      { id: 'OaDamper', data_type: 'numeric' },
      { id: 'Occupied', data_type: 'boolean' },
      { id: 'SupplyFanCommand', data_type: 'boolean' },
    ],
  },
  oracle_drafts: [
    {
      id: 'oracle-0000000000000001',
      conditions: [{ point: 'MixedAirTemp', operator: 'lt', value: 38, unit: 'degF' }],
      durations: [{ seconds: 300, relation: 'for' }],
      expectations: [{ point: 'OaDamper', operator: 'eq', value: 0, verb: 'close' }],
    },
  ],
  manual_facet_oracle_requirements: [
    { scenario_id: 'occupied', scenario_title: 'Occupied', facet_id: 'fan-runs', facet_label: 'Fan runs', authoring_allowed: true, input_point_candidates: ['Occupied'], output_point_candidates: ['SupplyFanCommand'] },
    { scenario_id: 'x', scenario_title: 'X', facet_id: 'y', facet_label: 'Y', authoring_allowed: false, input_point_candidates: [], output_point_candidates: [] },
  ],
} as unknown as CtrlFlowSequenceReview;

describe('oracle authoring', () => {
  it('drafts empty values for every condition and expectation', () => {
    const drafts = initialOracleDrafts(review);
    expect(drafts['oracle-0000000000000001'].baselineInputs).toEqual({ MixedAirTemp: '' });
    expect(drafts['oracle-0000000000000001'].preTriggerOutputs).toEqual({ OaDamper: '' });
    expect(Object.keys(initialFacetDrafts(review))).toEqual(['occupied/fan-runs']);
  });

  it('is complete only when every value is authored by a different person', () => {
    const drafts = {
      'oracle-0000000000000001': { stepSeconds: '60', baselineInputs: { MixedAirTemp: '50' }, triggerInputs: { MixedAirTemp: '30' }, recoveryInputs: { MixedAirTemp: '50' }, baselineOutputs: { OaDamper: '100' }, preTriggerOutputs: { OaDamper: '100' }, recoveryOutputs: { OaDamper: '100' } },
    };
    const facets = { 'occupied/fan-runs': { inputPoint: 'Occupied', outputPoint: 'SupplyFanCommand', stepSeconds: '1', baselineInput: 'false', triggerInput: 'true', recoveryInput: 'false', baselineOutput: 'false', triggerOutput: 'true', recoveryOutput: 'false' } };
    expect(oraclesComplete(review, drafts, facets, 'Tester', 'Reviewer')).toBe(true);
    expect(oraclesComplete(review, drafts, facets, 'Reviewer', 'Reviewer')).toBe(false);
    expect(oraclesComplete(review, { ...drafts, 'oracle-0000000000000001': { ...drafts['oracle-0000000000000001'], stepSeconds: '' } }, facets, 'Tester', 'Reviewer')).toBe(false);
    const payload = buildOracleApproval(review, drafts, facets, 'Tester');
    expect(payload.review_artifact_digest).toBe('b'.repeat(64));
    expect(payload.cases[0]).toMatchObject({
      oracle_id: 'oracle-0000000000000001',
      baseline_inputs: { MixedAirTemp: 50 },
      trigger_inputs: { MixedAirTemp: 30 },
      step_seconds: 60,
      pre_trigger_expectations: [{ target: 'OaDamper', operator: 'eq', value: 100 }],
      post_trigger_expectations: [{ target: 'OaDamper', operator: 'eq', value: 0 }],
    });
    expect(payload.facet_cases[0]).toMatchObject({
      scenario_id: 'occupied',
      facet_id: 'fan-runs',
      baseline_inputs: { Occupied: false },
      trigger_inputs: { Occupied: true },
      trigger_expectations: [{ target: 'SupplyFanCommand', operator: 'eq', value: true }],
    });
  });
});

describe('candidate request', () => {
  const approval = { ready_for_graph_generation: true, retention: { artifact_digest: 'c'.repeat(64) } } as unknown as SequenceOracleApproval;
  const params = [
    { name: 'kp', data_type: 'Real', is_array: false, required: true, value: null, description: null, unit: null },
    { name: 'n', data_type: 'Integer', is_array: false, required: true, value: null, description: null, unit: null },
    { name: 'on', data_type: 'Boolean', is_array: false, required: true, value: null, description: null, unit: null },
    { name: 'arr', data_type: 'Real', is_array: true, required: true, value: null, description: null, unit: null },
  ];

  it('parses typed parameters and rejects bad ones', () => {
    expect(parseParameter(params[0], '1.5')).toBe(1.5);
    expect(parseParameter(params[1], '3')).toBe(3);
    expect(() => parseParameter(params[1], '3.5')).toThrow(/integer/);
    expect(parseParameter(params[2], 'True')).toBe(true);
    expect(() => parseParameter(params[2], 'yes')).toThrow(/true or false/);
    expect(parseParameter(params[3], '[1,2]')).toEqual([1, 2]);
    expect(() => parseParameter(params[0], '')).toThrow(/Supply/);
  });

  it('inverts boundary selections into point bindings and refuses duplicates', () => {
    const request = buildCandidateRequest(approval, params, { kp: '1', n: '2', on: 'false', arr: '[0]' }, { Boundary1: 'PointA', Boundary2: '' }, { name: 'n', site: 's', equipment_name: 'E' });
    expect(request).toMatchObject({ oracle_artifact_digest: 'c'.repeat(64), controller_parameters: { kp: 1, n: 2, on: false, arr: [0] }, point_bindings: { PointA: 'Boundary1' }, execution_profile: 'modelica_exact', name: 'n' });
    expect(() => buildCandidateRequest(approval, params, { kp: '1', n: '2', on: 'false', arr: '[0]' }, { B1: 'P', B2: 'P' })).toThrow(/only one/);
    expect(() => buildCandidateRequest({ ...approval, ready_for_graph_generation: false } as SequenceOracleApproval, params, {}, {})).toThrow(/gate/);
  });
});
