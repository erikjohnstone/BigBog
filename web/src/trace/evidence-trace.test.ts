import { describe, expect, it } from 'vitest';

import type { AlfalfaEvidence, BoptestEvidence } from '../api/client';
import { buildAlfalfaTrace, buildBoptestTrace } from './evidence-trace';

const boptest = {
  schema: 'bactalk.boptest-qualification/v1',
  status: 'fail',
  run_id: 'r1',
  approval_allowed: false,
  live_building_writes: false,
  runtime: {
    runtime: 'BOPTEST',
    test_case: 'bestest_air',
    graph_name: 'G',
    graph_sha256: 'x',
    step_seconds: 300,
    steps: 4,
    measurement_catalog_count: 2,
    input_catalog_count: 1,
    kpis: { ener_tot: 1.5, tdis_tot: null },
    mapping: { measurements: [], actuators: [], test_case: 'bestest_air' },
    trajectory: [0, 1, 2, 3].map((i) => ({
      index: i,
      start_time: 1000 + i * 300,
      end_time: 1300 + i * 300,
      graph_inputs: { ZoneTemp: 70 + i },
      controller_outputs: { Damper: i * 25 },
      overrides: { oveFan_u: 1 },
      measurements: { reaTZon_y: 293 + i },
    })),
  },
  oracles: [
    {
      completed: true,
      passed: false,
      max_error: 12,
      pyfunnel_status_code: 1,
      test_times: [300, 600, 900, 1200],
      test_values: [0, 25, 50, 75],
      counterexample: { schema: 'bactalk.trajectory-counterexample/v1', violation_count: 1, first_violation_time: 900, last_violation_time: 900, peak_error_time: 900, peak_error: 12, peak_absolute_error: 12, context_samples: 1, window: { start_index: 2, end_index: 3, test_times: [900, 1200], test_values: [50, 75] } },
      oracle: { id: 'damper', signal: 'Damper', signal_kind: 'graph_output', reference_times: [300, 600, 900, 1200], reference_values: [0, 25, 38, 75], absolute_time_tolerance: 0, absolute_value_tolerance: 5 },
    },
  ],
} as unknown as BoptestEvidence;

describe('buildBoptestTrace', () => {
  const trace = buildBoptestTrace('r1', boptest);

  it('puts the trajectory on an elapsed-seconds axis with namespaced signals', () => {
    expect(Array.from(trace.time)).toEqual([0, 300, 600, 900]);
    expect(trace.engine).toBe('boptest');
    expect(trace.signals.get('in.ZoneTemp')?.source).toBe('input');
    expect(trace.signals.get('out.Damper')?.source).toBe('command');
    expect(trace.signals.get('meas.reaTZon_y')?.source).toBe('measurement');
    expect(trace.signals.get('ovr.oveFan_u')?.source).toBe('override');
    expect(Array.from(trace.signals.get('out.Damper')!.values)).toEqual([0, 25, 50, 75]);
    expect(trace.phases[0]).toMatchObject({ name: 'bestest_air', startIdx: 0, endIdx: 3, stepSeconds: 300 });
    expect(trace.passed).toBe(false);
  });

  it('turns oracles into bands, a sampled reference, and a failing assertion at the peak', () => {
    expect(trace.oracles).toHaveLength(1);
    const band = trace.oracles[0];
    expect(band).toMatchObject({ id: 'damper', signalId: 'out.Damper', referenceSignalId: 'oracle.damper.ref', tolerance: 5, passed: false, maxError: 12 });
    expect(band.window).toEqual({ startIdx: 2, endIdx: 3, peakIdx: 2, peakError: 12 });
    // reference samples are positional: the i-th reference value sits on the i-th trajectory step.
    expect(Array.from(trace.signals.get('oracle.damper.ref')!.values).map((v) => (Number.isNaN(v) ? null : v))).toEqual([0, 25, 38, 75]);
    expect(trace.assertions[0]).toMatchObject({ id: 'damper', passed: false, index: 2, blockIds: ['Damper'], signalId: 'out.Damper' });
  });

  it('concatenates suite cases as phases with continuing time', () => {
    const suite = {
      schema: 'bactalk.boptest-qualification-suite/v1',
      status: 'pass',
      run_id: 'r1',
      approval_allowed: true,
      live_building_writes: false,
      case_count: 2,
      total_steps: 8,
      cases: ['winter', 'summer'].map((id) => ({ id, status: 'pass', runtime: boptest.runtime, oracles: [], oracle_clock: { basis: 'elapsed_seconds_from_run_start', runtime_time_origin: 1000 }, report_directory: id })),
    } as unknown as BoptestEvidence;
    const both = buildBoptestTrace('r1', suite);
    expect(both.time.length).toBe(8);
    expect(Array.from(both.time)).toEqual([0, 300, 600, 900, 1200, 1500, 1800, 2100]);
    expect(both.phases.map((phase) => [phase.name, phase.startIdx, phase.endIdx])).toEqual([
      ['winter', 0, 3],
      ['summer', 4, 7],
    ]);
  });
});

const alfalfa = {
  schema: 'bactalk.alfalfa-graph-run/v1',
  status: 'pass',
  runtime: 'Alfalfa',
  run_id: 'alf',
  approval_allowed: true,
  live_building_writes: false,
  status_after_start: 'RUNNING',
  status_after_stop: 'COMPLETE',
  model_name: 'building.fmu',
  model_sha256: 'x',
  graph_name: 'G',
  graph_sha256: 'y',
  runtime_input_count: 1,
  runtime_output_count: 1,
  start: '2026-01-01T00:00:00Z',
  end: '2026-01-01T00:02:00Z',
  step_seconds: 60,
  steps: 3,
  clean_stop: true,
  oracles: [
    { completed: true, passed: true, max_error: 0.1, pyfunnel_status_code: 0, test_times: [60, 120, 180], test_values: [1, 1, 1], counterexample: null, report_directory: 'd', oracle: { id: 'fan', signal_kind: 'graph_output', signal: 'Fan', reference_times: [60, 120, 180], reference_values: [1, 1, 1], absolute_time_tolerance: 0, absolute_value_tolerance: 0.5 } },
  ],
  trajectory: [0, 1, 2].map((i) => ({
    index: i,
    start_time: `2026-01-01T00:0${i}:00Z`,
    end_time: `2026-01-01T00:0${i + 1}:00Z`,
    graph_inputs: { ZoneTemp: 72 },
    initial_output_values: {},
    controller_outputs: { Fan: 1 },
    fmu_inputs: { fan_cmd: 1 },
    observed_outputs: { zone_temp: 72 - i },
    command_echoes: { Fan: { output: 'Fan', command: 1, feedback: i === 1 ? 0 : 1, matched: i !== 1 } },
  })),
} as unknown as AlfalfaEvidence;

describe('buildAlfalfaTrace', () => {
  const trace = buildAlfalfaTrace('alf', alfalfa);

  it('converts ISO timestamps to seconds and keeps echo command, feedback, and matched', () => {
    expect(Array.from(trace.time)).toEqual([0, 60, 120]);
    expect(trace.signals.get('echo.Fan.matched')?.kind).toBe('boolean');
    expect(Array.from(trace.signals.get('echo.Fan.matched')!.values)).toEqual([1, 0, 1]);
    expect(Array.from(trace.signals.get('echo.Fan.feedback')!.values)).toEqual([1, 0, 1]);
    expect(trace.signals.get('fmu.fan_cmd')?.source).toBe('command');
    expect(trace.signals.get('meas.zone_temp')?.source).toBe('measurement');
    expect(trace.assertions[0]).toMatchObject({ id: 'fan', passed: true, index: 2, signalId: 'out.Fan' });
    expect(trace.passed).toBe(true);
  });
});
