/**
 * Review acknowledgements and blockers. The acknowledgement checklist is a
 * reviewer's own record in sessionStorage, keyed by run and artifact digest so
 * a changed artifact clears it. It gates nothing on the server: approval is
 * decided there, against the digest, by a named engineer.
 */

import type { ReleaseSummary, RunDetail, ShadowEvidence, TestReport } from '../../api/client';

export const SURFACES = [
  { id: 'tests', label: 'Tests' },
  { id: 'coverage', label: 'Decision coverage' },
  { id: 'qualification', label: 'Qualification matrix' },
  { id: 'deliverables', label: 'Deliverables' },
  { id: 'release', label: 'Release summary' },
  { id: 'shadow', label: 'Shadow Runtime' },
  { id: 'blockers', label: 'Blockers' },
] as const;
export type SurfaceId = (typeof SURFACES)[number]['id'];

export function ackKey(runId: string, digest: string): string {
  return `bactalk.review-ack.v1:${runId}:${digest}`;
}

export function readAcks(runId: string, digest: string): Set<SurfaceId> {
  try {
    const raw = sessionStorage.getItem(ackKey(runId, digest));
    return new Set(raw ? (JSON.parse(raw) as SurfaceId[]) : []);
  } catch {
    return new Set();
  }
}

export function writeAcks(runId: string, digest: string, acks: Set<SurfaceId>): void {
  try {
    sessionStorage.setItem(ackKey(runId, digest), JSON.stringify([...acks]));
  } catch {
    // A reviewer's convenience only.
  }
}

export interface Blocker {
  id: string;
  label: string;
  /** Approval blockers stop the decision; deployment gates only stop deployment readiness. */
  kind: 'approval' | 'deployment';
  /** Where the reviewer goes to look. */
  stage?: 'build' | 'test' | 'release';
}

/** Everything that stands between this candidate and approval, from the server's own records. */
export function blockersFor(run: RunDetail, report: TestReport | undefined, summary: ReleaseSummary | undefined, shadow?: ShadowEvidence): Blocker[] {
  const blockers: Blocker[] = [];
  if (run.status === 'failed') blockers.push({ id: 'status-failed', label: 'The candidate failed its acceptance tests; only a passing candidate can be approved.', kind: 'approval', stage: 'test' });
  if (run.status === 'rejected') blockers.push({ id: 'status-rejected', label: 'The candidate was rejected. A new candidate is needed.', kind: 'approval' });
  if (report && !report.passed) {
    const failing = report.scenarios.flatMap((scenario) => scenario.assertions.filter((item) => !item.passed).map((item) => `${scenario.name}: ${item.name}`));
    for (const name of failing.slice(0, 8)) blockers.push({ id: `assertion:${name}`, label: `Failing assertion — ${name}`, kind: 'approval', stage: 'test' });
    if (failing.length > 8) blockers.push({ id: 'assertion:more', label: `${failing.length - 8} more failing assertions`, kind: 'approval', stage: 'test' });
  }
  if (summary && !summary.integrity.verified) blockers.push({ id: 'integrity', label: 'The retained artifact does not match its recorded digest.', kind: 'approval', stage: 'release' });
  for (const item of shadow?.differential.cases ?? []) {
    if (item.passed) continue;
    const divergence = item.first_divergence;
    blockers.push({
      id: `shadow:${item.name}`,
      label: divergence ? `Shadow Runtime — ${item.name}: first divergence at t=${divergence.time_seconds} s in ${divergence.block}.${divergence.slot}` : `Shadow Runtime — ${item.name} failed`,
      kind: 'approval',
      stage: 'test',
    });
  }
  for (const gate of summary?.deliverables.blocking_gates ?? []) blockers.push({ id: `gate:${gate}`, label: gate, kind: 'deployment', stage: 'release' });
  return blockers;
}
