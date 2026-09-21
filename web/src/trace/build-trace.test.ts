import { describe, expect, it } from 'vitest';

import type { RunDetail, TestReport } from '../api/client';
import { buildTrace, signalIdForOutput } from './build-trace';

const run = {
  id: 'r1',
  created_at: '2026-01-01T00:00:00Z',
  origin: 'contractor',
  status: 'ready_for_review',
  artifact_sha256: 'abc',
  job: {
    name: 'EF-1',
    site: 'Site',
    equipment_name: 'EF_1',
    sequence: { family: 'EXHAUST_FAN_PROOF', version: '1' },
    points: [
      { name: 'Enable', label: 'AHU enable', data_type: 'boolean', role: 'status' },
      { name: 'ZoneTemp', label: 'Zone temp', data_type: 'numeric', role: 'sensor', units: 'degF' },
    ],
    acceptance_tests: [
      { name: 'proof ok', repeat: 3, step_seconds: 2, expectations: [{ target: 'FanCommand', operator: 'eq', value: true }], faults: [], timeline: [] },
      { name: 'proof fails', repeat: 2, step_seconds: 5, expectations: [{ target: 'FanProofAlarm', operator: 'eq', value: true }], faults: [], timeline: [] },
    ],
  },
  changes: { added: [], modified: [], removed: [] },
  agent_attempts: [],
} as unknown as RunDetail;

const graph = {
  name: 'EF_1',
  blocks: [
    { id: 'Enable', kind: 'boolean_input', label: 'AHU enable', x: 0, y: 0, config: {} },
    { id: 'ProofDelay', kind: 'boolean_delay', label: 'Delay', x: 0, y: 0, config: {} },
    { id: 'FanCommand', kind: 'boolean_output', label: 'Fan command', x: 0, y: 0, config: {} },
    { id: 'FanProofAlarm', kind: 'boolean_output', label: 'Alarm', x: 0, y: 0, config: {} },
  ],
  links: [],
};

const report: TestReport = {
  engine: 'generic',
  passed: false,
  coverage: {
    fault_injection: {
      schema: 's',
      activation_count: 1,
      fault_case_count: 1,
      fault_cases_passed: 0,
      kinds: ['stuck'],
      targets: ['Enable'],
      quality_targets: [],
      recovery_phases: [],
      declarations: [{ case: 'proof fails', phase: null, id: 'f1', kind: 'stuck', target: 'Enable', quality_target: null }],
      interpretation: '',
    },
  },
  scenarios: [
    {
      name: 'proof ok',
      passed: true,
      assertions: [{ name: 'proof ok: FanCommand', observed: 'True', expected: 'eq True', passed: true }],
      samples: [
        { step: 1, Enable: true, 'Enable.out': true, ProofDelay: false, 'ProofDelay.out': false, FanCommand: true, 'FanCommand.out': true, ZoneTemp: 70.5 },
        { step: 2, Enable: true, 'Enable.out': true, ProofDelay: false, 'ProofDelay.out': false, FanCommand: true, 'FanCommand.out': true, ZoneTemp: 71 },
        { step: 3, Enable: true, 'Enable.out': true, ProofDelay: true, 'ProofDelay.out': true, FanCommand: true, 'FanCommand.out': true, ZoneTemp: 71.5 },
      ],
    },
    {
      name: 'proof fails',
      passed: false,
      assertions: [{ name: 'proof fails: FanProofAlarm', observed: 'False', expected: 'eq True', passed: false }],
      samples: [
        { step: 1, Enable: true, 'fault.f1.active': true, 'effective.Enable': false, FanProofAlarm: false, ZoneTemp: null },
        { step: 2, Enable: true, 'fault.f1.active': false, 'effective.Enable': true, FanProofAlarm: false, ZoneTemp: 72 },
      ],
    },
  ],
};

describe('buildTrace', () => {
  const trace = buildTrace(run, report, { graph });

  it('concatenates scenarios on one seconds axis from step_seconds', () => {
    expect(Array.from(trace.time)).toEqual([0, 2, 4, 6, 11]);
    expect(trace.axisReconstructed).toBe(false);
    expect(trace.engine).toBe('generic');
    expect(trace.phases.map((phase) => [phase.name, phase.startIdx, phase.endIdx])).toEqual([
      ['proof ok', 0, 2],
      ['proof fails', 3, 4],
    ]);
  });

  it('classifies signals and types them from the graph', () => {
    expect(trace.signals.get('Enable')?.source).toBe('input');
    expect(trace.signals.get('Enable')?.kind).toBe('boolean');
    expect(trace.signals.get('ProofDelay.out')?.source).toBe('slot');
    expect(trace.signals.get('ProofDelay.out')?.blockId).toBe('ProofDelay');
    expect(trace.signals.get('fault.f1.active')?.source).toBe('fault');
    expect(trace.signals.get('effective.Enable')?.source).toBe('effective');
    expect(trace.signals.get('ZoneTemp')?.unit).toBe('degF');
    expect(Array.from(trace.signals.get('ZoneTemp')!.values)).toEqual([70.5, 71, 71.5, Number.NaN, 72]);
    expect(Array.from(trace.signals.get('ProofDelay')!.values)).toEqual([0, 0, 1, 255, 255]);
    expect(trace.signals.get('ZoneTemp')?.min).toBe(70.5);
    expect(trace.signals.get('ZoneTemp')?.max).toBe(72);
  });

  it('places assertions at the end of their phase with the target block', () => {
    expect(trace.assertions).toHaveLength(2);
    expect(trace.assertions[1]).toMatchObject({ passed: false, index: 4, phaseIndex: 1, blockIds: ['FanProofAlarm'] });
    expect(trace.passed).toBe(false);
  });

  it('derives fault windows from fault.<id>.active and the declarations', () => {
    expect(trace.faultWindows).toEqual([{ id: 'f1', kind: 'stuck', target: 'Enable', qualityTarget: null, startIdx: 3, endIdx: 3 }]);
    expect(trace.phases[1].faults[0]?.id).toBe('f1');
  });

  it('flags a reconstructed axis when a scenario has no case', () => {
    const orphan = buildTrace(run, { ...report, scenarios: [{ ...report.scenarios[0], name: 'unknown' }] }, { graph });
    expect(orphan.axisReconstructed).toBe(true);
    expect(Array.from(orphan.time)).toEqual([0, 1, 2]);
  });

  it('handles the legacy minute axis', () => {
    const legacy = buildTrace(run, {
      engine: 'legacy',
      passed: true,
      scenarios: [
        {
          name: 'cooling',
          passed: true,
          assertions: [],
          samples: [
            { minute: 0, ZoneTemp: 76, DamperCommand: 100 },
            { minute: 1, ZoneTemp: 75, DamperCommand: 90 },
          ],
        },
      ],
    });
    expect(legacy.engine).toBe('g36-legacy');
    expect(Array.from(legacy.time)).toEqual([0, 60]);
    expect(legacy.signals.get('ZoneTemp')?.source).toBe('input');
    expect(legacy.signals.get('DamperCommand')?.source).toBe('block');
  });

  it('resolves the signal carrying a link', () => {
    expect(signalIdForOutput(trace, 'ProofDelay', 'out', 'out')).toBe('ProofDelay.out');
    expect(signalIdForOutput(trace, 'Enable', 'out', 'out')).toBe('Enable.out');
    expect(signalIdForOutput(trace, 'FanProofAlarm', 'out', 'out')).toBe('FanProofAlarm');
    expect(signalIdForOutput(trace, 'Nope', 'out', 'out')).toBeUndefined();
  });
});
