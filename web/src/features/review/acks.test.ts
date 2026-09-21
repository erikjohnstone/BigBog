import { beforeEach, describe, expect, it } from 'vitest';

import type { ReleaseSummary, RunDetail, TestReport } from '../../api/client';
import { blockersFor, readAcks, writeAcks } from './acks';

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
});
