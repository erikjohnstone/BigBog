import { CheckCircle2, GitCompare, ThumbsDown, ThumbsUp } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import type { RunDetail } from '../../api/client';
import { useDeliverables, useReleaseSummary, useReport, useSecurityStatus } from '../../api/queries';
import { Button, StatusPill, runStatusTone } from '../../design-system/primitives';
import { MissingEvidence } from '../../design-system/states';
import { DecisionMatrix } from '../coverage/DecisionMatrix';
import { QualificationMatrix } from '../coverage/QualificationMatrix';
import { KeyValue, SectionCard, StageFrame } from '../shared/StageFrame';
import { ApproveDialog, RejectDialog } from './DecisionDialogs';
import { SurfaceAck } from './SurfaceAck';
import { SURFACES, blockersFor, readAcks, writeAcks } from './acks';
import type { SurfaceId } from './acks';

function formatWhen(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

/**
 * Review stage: the candidate's semantic changeset and every evidence
 * surface, each acknowledged by the reviewer, then a decision bound to the
 * artifact digest that was on screen. Acknowledgements are the reviewer's
 * own checklist; the server decides approval against the digest.
 */
export function ReviewStage({ run }: { run: RunDetail }) {
  const report = useReport(run.id);
  const deliverables = useDeliverables(run.id);
  const summary = useReleaseSummary(run.id);
  const security = useSecurityStatus();
  const status = runStatusTone(run.status);
  // The digest the reviewer is looking at; approval is bound to this value.
  const [inspectedDigest] = useState(() => run.artifact_sha256);
  const [acks, setAcks] = useState(() => readAcks(run.id, inspectedDigest));
  const [dialog, setDialog] = useState<'approve' | 'reject' | null>(null);

  const ack = (id: SurfaceId, value: boolean) => {
    const next = new Set(acks);
    if (value) next.add(id);
    else next.delete(id);
    setAcks(next);
    writeAcks(run.id, inspectedDigest, next);
  };

  const blockers = useMemo(() => blockersFor(run, report.data, summary.data), [run, report.data, summary.data]);
  const approvalBlockers = blockers.filter((item) => item.kind === 'approval');
  const deploymentGates = blockers.filter((item) => item.kind === 'deployment');
  const allAcked = SURFACES.every((surface) => acks.has(surface.id));
  const decidable = run.status === 'ready_for_review';
  const selfAsserted = security.data ? !security.data.authentication_enabled : true;
  const changes = run.changes;
  const hasChanges = changes.added.length + changes.modified.length + changes.removed.length > 0;
  const summaryData = summary.data;
  const testTotals = report.data
    ? report.data.scenarios.reduce(
        (acc, scenario) => ({ total: acc.total + scenario.assertions.length, passed: acc.passed + scenario.assertions.filter((item) => item.passed).length }),
        { total: 0, passed: 0 },
      )
    : null;

  return (
    <StageFrame>
      <SectionCard
        title="Decision"
        aside={
          <span className="inline-flex items-center gap-2">
            <StatusPill tone={status.tone}>{status.label}</StatusPill>
            {decidable && (
              <>
                <Button size="sm" variant="outline" onClick={() => setDialog('reject')}>
                  <ThumbsDown size={13} /> Reject
                </Button>
                <Button size="sm" variant="primary" onClick={() => setDialog('approve')} disabled={!allAcked} title={allAcked ? 'Approve against the inspected digest' : 'Mark every surface reviewed first'}>
                  <ThumbsUp size={13} /> Approve
                </Button>
              </>
            )}
          </span>
        }
      >
        <KeyValue
          items={[
            { label: 'Artifact digest', value: <span className="num break-all">{run.artifact_sha256}</span> },
            {
              label: 'Behavior',
              value: report.data ? (
                <span className="inline-flex items-center gap-2">
                  <StatusPill tone={report.data.passed ? 'ok' : 'fail'}>{report.data.passed ? 'Tests passed' : 'Tests failed'}</StatusPill>
                  {testTotals && (
                    <span className="num text-fg-2">
                      {testTotals.passed}/{testTotals.total} assertions
                    </span>
                  )}
                </span>
              ) : (
                <span className="text-fg-2">Loading report</span>
              ),
            },
            {
              label: 'Reviewed',
              value: (
                <span className="inline-flex items-center gap-2">
                  <span className="num">
                    {acks.size}/{SURFACES.length} surfaces
                  </span>
                  <span className="text-xs text-fg-2">Your checklist in this browser tab. The server does not see it.</span>
                </span>
              ),
            },
            ...(run.approval ? [{ label: 'Approved', value: `${run.approval.reviewer} · ${formatWhen(run.approval.approved_at)}` }] : []),
            ...(run.rejection ? [{ label: 'Rejected', value: `${run.rejection.reviewer} · ${formatWhen(run.rejection.rejected_at)}${run.rejection.reason ? ` · ${run.rejection.reason}` : ''}` }] : []),
            ...(run.parent_run_id
              ? [
                  {
                    label: 'Parent candidate',
                    value: (
                      <span className="inline-flex items-center gap-3">
                        <Link to={`/jobs/${run.parent_run_id}/review`} className="text-accent font-mono text-xs">
                          {run.parent_run_id}
                        </Link>
                        <Link to={`/jobs/${run.id}/build?compare=1`} className="inline-flex items-center gap-1 text-xs text-accent">
                          <GitCompare size={12} /> Ghost diff on the wiresheet
                        </Link>
                      </span>
                    ),
                  },
                ]
              : []),
          ]}
        />
        <p className="px-4 pb-3 text-xs text-fg-2">
          Approval is recorded against this exact digest by a named engineer and unlocks export only. It never enables a live write, and it never implies field qualification.
        </p>
      </SectionCard>

      {hasChanges && (
        <SectionCard title="Changes from parent">
          <ul className="px-4 py-3 flex flex-col gap-1 font-mono text-xs">
            {changes.added.map((item) => (
              <li key={`a-${item}`} className="text-ok">
                + {item}
              </li>
            ))}
            {changes.modified.map((item) => (
              <li key={`m-${item}`} className="text-warn">
                ~ {item}
              </li>
            ))}
            {changes.removed.map((item) => (
              <li key={`r-${item}`} className="text-fail">
                − {item}
              </li>
            ))}
          </ul>
        </SectionCard>
      )}

      <SurfaceAck id="tests" title="Tests" acked={acks.has('tests')} onAck={(value) => ack('tests', value)} aside={report.data && <StatusPill tone={report.data.passed ? 'ok' : 'fail'}>{report.data.passed ? 'passed' : 'failed'}</StatusPill>}>
        {report.data ? (
          <div className="px-4 py-3 text-sm">
            <ul className="flex flex-col gap-1">
              {report.data.scenarios.map((scenario) => {
                const failed = scenario.assertions.filter((item) => !item.passed);
                return (
                  <li key={scenario.name} className="flex items-center gap-2 min-w-0">
                    <StatusPill tone={scenario.passed ? 'ok' : 'fail'} icon={null}>
                      {scenario.assertions.length - failed.length}/{scenario.assertions.length}
                    </StatusPill>
                    <span className="truncate text-fg-0">{scenario.name}</span>
                    {failed.length > 0 && <span className="text-xs text-fail truncate">{failed.map((item) => item.name).join(', ')}</span>}
                  </li>
                );
              })}
            </ul>
            <Link to={`/jobs/${run.id}/test`} className="inline-block mt-2 text-xs text-accent">
              Open the Test stage to scrub the evidence
            </Link>
          </div>
        ) : (
          <p className="px-4 py-3 text-sm text-fg-2">Loading report…</p>
        )}
      </SurfaceAck>

      <SurfaceAck id="coverage" title="Decision coverage" acked={acks.has('coverage')} onAck={(value) => ack('coverage', value)}>
        {report.data ? <DecisionMatrix report={report.data} /> : <p className="px-4 py-3 text-sm text-fg-2">Loading report…</p>}
      </SurfaceAck>

      <SurfaceAck id="qualification" title="Qualification matrix" acked={acks.has('qualification')} onAck={(value) => ack('qualification', value)}>
        {report.data ? <QualificationMatrix report={report.data} /> : <p className="px-4 py-3 text-sm text-fg-2">Loading report…</p>}
      </SurfaceAck>

      <SurfaceAck id="deliverables" title="Deliverables" acked={acks.has('deliverables')} onAck={(value) => ack('deliverables', value)} aside={deliverables.data?.state === 'available' && <StatusPill tone={deliverables.data.data.deployment_ready ? 'ok' : 'warn'}>{deliverables.data.data.deployment_ready ? 'deployment ready' : 'not deployment ready'}</StatusPill>}>
        {deliverables.data?.state === 'available' ? (
          <div className="px-4 py-3 text-sm flex flex-col gap-2">
            <ul className="divide-y divide-line-1">
              {deliverables.data.data.artifacts.map((artifact) => (
                <li key={artifact.path} className="flex items-center gap-3 h-8 min-w-0">
                  <span className="font-mono text-xs truncate">{artifact.path}</span>
                  <span className="flex-1" />
                  <span className="num text-fg-2" title={artifact.sha256}>
                    {artifact.sha256.slice(0, 12)}
                  </span>
                </li>
              ))}
            </ul>
            <ul className="grid gap-x-4 gap-y-1 grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] text-xs">
              {Object.entries(deliverables.data.data.coverage).map(([name, item]) => (
                <li key={name} className="flex items-center gap-2 min-w-0">
                  <StatusPill tone={item.emitted ? (item.licensed_runtime_qualified ? 'ok' : 'info') : 'neutral'} icon={null}>
                    {item.emitted ? (item.licensed_runtime_qualified ? 'qualified' : 'emitted') : 'not emitted'}
                  </StatusPill>
                  <span className="truncate text-fg-1">{name}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : deliverables.isLoading ? (
          <p className="px-4 py-3 text-sm text-fg-2">Loading deliverables…</p>
        ) : (
          <MissingEvidence kind="Deliverables" state={deliverables.data?.state === 'invalid' ? 'invalid' : 'missing'} detail={deliverables.data?.state === 'invalid' ? deliverables.data.message : 'No deliverables were generated for this candidate.'} />
        )}
      </SurfaceAck>

      <SurfaceAck id="release" title="Release summary" acked={acks.has('release')} onAck={(value) => ack('release', value)} aside={summaryData && <StatusPill tone={summaryData.integrity.verified ? 'ok' : 'fail'}>{summaryData.integrity.verified ? 'integrity verified' : 'integrity mismatch'}</StatusPill>}>
        {summaryData ? (
          <KeyValue
            items={[
              { label: 'Target', value: <span className="font-mono text-xs">{summaryData.target.artifact_kind}{summaryData.target.filename ? ` · ${summaryData.target.filename}` : ''}</span> },
              { label: 'Licensed runtime', value: summaryData.target.licensed_runtime_qualified ? 'qualified' : 'Not qualified. Manual import into a licensed Workbench is required.' },
              { label: 'Live writes', value: summaryData.safety.live_writes_enabled ? 'enabled' : 'never enabled; approval does not authorize live deployment' },
            ]}
          />
        ) : (
          <p className="px-4 py-3 text-sm text-fg-2">{summary.isError ? 'Release summary unavailable.' : 'Loading release summary…'}</p>
        )}
      </SurfaceAck>

      <SurfaceAck
        id="blockers"
        title="Blockers"
        acked={acks.has('blockers')}
        onAck={(value) => ack('blockers', value)}
        aside={
          <span className="inline-flex items-center gap-1.5">
            <StatusPill tone={approvalBlockers.length === 0 ? 'ok' : 'fail'}>{approvalBlockers.length === 0 ? 'approvable' : `${approvalBlockers.length} block approval`}</StatusPill>
            {deploymentGates.length > 0 && <StatusPill tone="warn">{deploymentGates.length} deployment gates</StatusPill>}
          </span>
        }
      >
        <div className="px-4 py-3 text-sm flex flex-col gap-3">
          {approvalBlockers.length === 0 ? (
            <p className="text-fg-1 inline-flex items-center gap-2">
              <CheckCircle2 size={14} className="text-ok" /> Nothing the server records stands in the way of approval.
            </p>
          ) : (
            <ul className="flex flex-col gap-1">
              {approvalBlockers.map((item) => (
                <li key={item.id} className="flex items-center gap-2">
                  <span className="text-fail">{item.label}</span>
                  {item.stage && (
                    <Link to={`/jobs/${run.id}/${item.stage}`} className="text-xs text-accent">
                      open
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          )}
          {deploymentGates.length > 0 && (
            <div>
              <p className="eyebrow mb-1">Deployment gates</p>
              <p className="text-xs text-fg-2 mb-1">These keep the deliverables from being deployment-ready. Approval is still allowed; the hand-off repeats them.</p>
              <ul className="flex flex-col gap-1">
                {deploymentGates.map((item) => (
                  <li key={item.id} className="flex items-center gap-2">
                    <span className="text-warn">{item.label}</span>
                    {item.stage && (
                      <Link to={`/jobs/${run.id}/${item.stage}`} className="text-xs text-accent">
                        open
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </SurfaceAck>

      {run.agent_attempts.length > 0 && (
        <SectionCard title="Agent attempts">
          <ul className="divide-y divide-line-1">
            {run.agent_attempts.map((attempt) => (
              <li key={attempt.iteration} className="flex items-center gap-3 px-4 h-9 text-sm">
                <span className="num text-fg-2">#{attempt.iteration}</span>
                <StatusPill tone={attempt.passed ? 'ok' : 'fail'}>{attempt.passed ? 'passed' : 'failed'}</StatusPill>
                {attempt.failed_assertions && attempt.failed_assertions.length > 0 && (
                  <span className="text-xs text-fg-2">
                    <span className="num">{attempt.failed_assertions.length}</span> failing assertions
                  </span>
                )}
              </li>
            ))}
          </ul>
        </SectionCard>
      )}

      {dialog === 'approve' && <ApproveDialog run={run} inspectedDigest={inspectedDigest} open onOpenChange={(open) => !open && setDialog(null)} selfAsserted={selfAsserted} />}
      {dialog === 'reject' && <RejectDialog run={run} open onOpenChange={(open) => !open && setDialog(null)} selfAsserted={selfAsserted} />}
    </StageFrame>
  );
}
