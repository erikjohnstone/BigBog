import { describe, expect, it } from 'vitest';

import type { RunDetail, ShadowEvidence } from '../api/client';
import { SHADOW_TRACE_LABEL, buildShadowTrace, shadowTraceId } from './shadow-trace';

const run = {
  id: 'r1',
  created_at: '2026-01-01T00:00:00Z',
  origin: 'contractor',
  status: 'ready_for_review',
  artifact_sha256: 'abc',
  job: {
    name: 'VAV-1',
    site: 'Site',
    equipment_name: 'VAV_1',
    sequence: { family: 'G36_VAV', version: '1' },
    points: [],
    acceptance_tests: [
      { name: 'cooling', repeat: 4, step_seconds: 30, expectations: [{ target: 'yDam' }], faults: [], timeline: [] },
      { name: 'heating', repeat: 3, step_seconds: 30, expectations: [{ target: 'yVal' }], faults: [], timeline: [] },
    ],
  },
  changes: { added: [], modified: [], removed: [] },
  agent_attempts: [],
} as unknown as RunDetail;

const evidence: ShadowEvidence = {
  schema: 'bactalk.shadow-qualification/v1',
  status: 'fail',
  run_id: 'r1',
  tier: 'bog-simulated',
  engine: 'Niagara Shadow Runtime (bog-simulated, policy default, kernels python)',
  policy: 'default',
  kernel_backend: 'python',
  band_set: 'default',
  bog_sha256: 'a'.repeat(64),
  artifact_sha256_before_qualification: 'b'.repeat(64),
  approval_allowed: false,
  live_building_writes: false,
  report: {
    engine: 'Niagara Shadow Runtime',
    passed: true,
    coverage: null,
    scenarios: [
      {
        name: 'cooling',
        passed: true,
        assertions: [{ name: 'cooling: yDam', observed: '0.5', expected: 'ge 0.3', passed: true }],
        samples: [0, 1, 2, 3].map((i) => ({ step: i + 1, yDam: 0.1 * (i + 1) })),
      },
      {
        name: 'heating',
        passed: true,
        assertions: [{ name: 'heating: yVal', observed: '1', expected: 'eq 1', passed: true }],
        samples: [0, 1, 2].map((i) => ({ step: i + 1, yVal: i })),
      },
    ],
  },
  differential: {
    schema: 'bactalk.three-way-differential/v1',
    controller_id: 'TerminalUnits.Reheat.Controller',
    passed: false,
    reference_available: true,
    engines: { shadow: 'shadow', interpreter: 'interpreter', reference: 'Open Control Engine 1.0' },
    cases: [
      {
        name: 'cooling',
        passed: false,
        legs_available: ['shadow', 'interpreter', 'reference'],
        signals: [
          {
            signal: 'yDam',
            passed: false,
            band: { kind: 'numeric', atolx: 2, atoly: 0.02, rationale: 'damper', source: 'default' },
            legs: {
              'shadow-vs-interpreter': { leg: 'shadow-vs-interpreter', passed: false, max_error: 0.2, first_violation_time: 60, engine: 'pure' },
              'shadow-vs-reference': { leg: 'shadow-vs-reference', passed: true, max_error: 0.01, first_violation_time: null, engine: 'pyfunnel' },
            },
          },
        ],
        first_divergence: { time_seconds: 60, block: 'yDam', slot: 'out', shadow: 0.5, interpreter: 0.7, band: 0.02 },
      },
      {
        name: 'heating',
        passed: true,
        legs_available: ['shadow', 'interpreter'],
        signals: [{ signal: 'yVal', passed: true, band: { kind: 'numeric', atolx: 2, atoly: 0.05, rationale: 'valve', source: 'default' }, legs: { 'shadow-vs-interpreter': { leg: 'shadow-vs-interpreter', passed: true, max_error: 0, first_violation_time: null, engine: 'pure' } } }],
        first_divergence: null,
      },
    ],
    failing_cases: ['cooling'],
  },
  reference: {
    cooling: { yDam: { times: [0, 45, 100], values: [0.1, 0.25, 0.4] } },
  },
};

describe('buildShadowTrace', () => {
  const trace = buildShadowTrace(run, evidence);

  it('is the shadow engine on the run-style axis, failing with the evidence status', () => {
    expect(trace.id).toBe(shadowTraceId('r1'));
    expect(trace.id).toBe('shadow:r1');
    expect(trace.engine).toBe('shadow');
    expect(trace.label).toBe(SHADOW_TRACE_LABEL);
    expect(trace.label).toBe('Shadow Runtime · bog-simulated');
    expect(trace.passed).toBe(false);
    expect(Array.from(trace.time)).toEqual([0, 30, 60, 90, 120, 150, 180]);
    expect(trace.phases.map((phase) => [phase.name, phase.startIdx, phase.endIdx])).toEqual([
      ['cooling', 0, 3],
      ['heating', 4, 6],
    ]);
    expect(trace.signals.get('yDam')?.source).toBe('block');
  });

  it('resamples the reference trajectory onto the scenario phase with nearest earlier samples', () => {
    const reference = trace.signals.get('ref.yDam');
    expect(reference).toBeDefined();
    expect(reference?.source).toBe('reference');
    expect(reference?.label).toBe('yDam reference');
    const values = Array.from(reference!.values).map((value) => (Number.isNaN(value) ? null : value));
    // t = 0, 30 → sample at 0; t = 60, 90 → sample at 45; heating phase carries no reference.
    expect(values).toEqual([0.1, 0.1, 0.25, 0.25, null, null, null]);
    expect(trace.oracles).toHaveLength(1);
    expect(trace.oracles[0]).toMatchObject({ id: 'shadow:cooling:yDam', signalId: 'yDam', referenceSignalId: 'ref.yDam', tolerance: 0.02, passed: false, maxError: 0.2 });
    expect(trace.oracles[0].window).toEqual({ startIdx: 0, endIdx: 3, peakIdx: 2, peakError: 0.2 });
  });

  it('adds one assertion per compared signal so jump-to-failure reaches the divergence', () => {
    const band = trace.assertions.filter((item) => item.id.startsWith('shadow:'));
    expect(band.map((item) => item.name)).toEqual(['cooling: yDam within band', 'heating: yVal within band']);
    expect(band[0]).toMatchObject({ passed: false, index: 2, phaseIndex: 0, blockIds: ['yDam'], signalId: 'yDam', expected: '≤ 0.02', observed: 'max error 0.200' });
    expect(band[1]).toMatchObject({ passed: true, index: 6, phaseIndex: 1, blockIds: ['yVal'], signalId: 'yVal' });
    // The report's own assertions are kept ahead of the differential ones.
    expect(trace.assertions.slice(0, 2).map((item) => item.name)).toEqual(['cooling: yDam', 'heating: yVal']);
  });

  it('places a failed comparison without leg timing at the case-level first divergence', () => {
    const noLegTiming: ShadowEvidence = {
      ...evidence,
      reference: undefined,
      differential: {
        ...evidence.differential,
        cases: [{ ...evidence.differential.cases[0], signals: [{ ...evidence.differential.cases[0].signals[0], legs: {} }], first_divergence: { time_seconds: 90, block: 'yDam', slot: 'out', shadow: 0.5, interpreter: 0.7, band: 0.02 } }],
      },
    };
    const other = buildShadowTrace(run, noLegTiming);
    expect(other.signals.has('ref.yDam')).toBe(false);
    expect(other.oracles).toEqual([]);
    const assertion = other.assertions.find((item) => item.id === 'shadow:cooling:yDam');
    expect(assertion).toMatchObject({ passed: false, index: 3, observed: 'diverged' });
  });
});
