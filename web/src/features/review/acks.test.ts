import { beforeEach, describe, expect, it } from 'vitest';

import type { ReleaseSummary, RunDetail, ShadowEvidence, TestReport } from '../../api/client';
import { SURFACES, blockersFor, readAcks, writeAcks } from './acks';

const run = { id: 'r1', status: 'ready_for_review', artifact_sha256: 'a'.repeat(64) } as unknown as RunDetail;

describe('acks', () => {
  beforeEach(() => sessionStorage.clear());

  it('are scoped to the run and digest so a changed artifact clears them', () => {
    writeAcks('r1', 'a', new Set(['tests', 'coverage']));
    expect([...readAcks('r1', 'a')]).toEqual(['tests', 'coverage']);
    expect(readAcks('r1', 'b').size).toBe(0);
    expect(readAcks('r2', 'a').size).toBe(0);
  });
});

describe('blockersFor', () => {
  it('is empty for a passing, verified candidate with no gates', () => {
    const report = { passed: true, scenarios: [] } as unknown as TestReport;
    const summary = { integrity: { verified: true }, deliverables: { blocking_gates: [] } } as unknown as ReleaseSummary;
    expect(blockersFor(run, report, summary)).toEqual([]);
  });

  it('names failing assertions, integrity mismatches, and gates', () => {
    const report = { passed: false, scenarios: [{ name: 'cooling', assertions: [{ name: 'damper opens', passed: false }, { name: 'fan on', passed: true }] }] } as unknown as TestReport;
    const summary = { integrity: { verified: false }, deliverables: { blocking_gates: ['whole-system coverage'] } } as unknown as ReleaseSummary;
    const blockers = blockersFor({ ...run, status: 'failed' } as RunDetail, report, summary);
    expect(blockers.map((item) => item.id)).toEqual(['status-failed', 'assertion:cooling: damper opens', 'integrity', 'gate:whole-system coverage']);
  });

  it('names every failing Shadow Runtime case with its first divergence', () => {
    const report = { passed: true, scenarios: [] } as unknown as TestReport;
    const summary = { integrity: { verified: true }, deliverables: { blocking_gates: [] } } as unknown as ReleaseSummary;
    const shadow = {
      status: 'fail',
      differential: {
        cases: [
          { name: 'cooling', passed: false, first_divergence: { time_seconds: 90, block: 'yDam', slot: 'out', shadow: 0.5, interpreter: 0.7, band: 0.02 } },
          { name: 'heating', passed: false, first_divergence: null },
          { name: 'idle', passed: true, first_divergence: null },
        ],
      },
    } as unknown as ShadowEvidence;
    const blockers = blockersFor(run, report, summary, shadow);
    expect(blockers).toEqual([
      { id: 'shadow:cooling', label: 'Shadow Runtime — cooling: first divergence at t=90 s in yDam.out', kind: 'approval', stage: 'test' },
      { id: 'shadow:heating', label: 'Shadow Runtime — heating failed', kind: 'approval', stage: 'test' },
    ]);
    expect(blockersFor(run, report, summary, undefined)).toEqual([]);
  });
});

describe('SURFACES', () => {
  it('includes the Shadow Runtime surface the reviewer must acknowledge', () => {
    expect(SURFACES.map((surface) => surface.id)).toContain('shadow');
    expect(SURFACES.find((surface) => surface.id === 'shadow')?.label).toBe('Shadow Runtime');
  });
});
