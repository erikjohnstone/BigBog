import { Link } from 'react-router-dom';

import type { RunDetail } from '../../api/client';
import { useReport } from '../../api/queries';
import { StatusPill, runStatusTone } from '../../design-system/primitives';
import { KeyValue, SectionCard, StageFrame } from '../shared/StageFrame';

/**
 * Review stage. Phase 8 adds acknowledgement, approval bound to the digest,
 * and rejection. This shows what the server records about the candidate.
 */
export function ReviewStage({ run }: { run: RunDetail }) {
  const report = useReport(run.id);
  const status = runStatusTone(run.status);
  const changes = run.changes;
  const hasChanges = changes.added.length + changes.modified.length + changes.removed.length > 0;

  return (
    <StageFrame>
      <SectionCard title="Decision" aside={<StatusPill tone={status.tone}>{status.label}</StatusPill>}>
        <KeyValue
          items={[
            { label: 'Artifact digest', value: <span className="num">{run.artifact_sha256}</span> },
            {
              label: 'Behavior',
              value: report.data ? (
                <StatusPill tone={report.data.passed ? 'ok' : 'fail'}>{report.data.passed ? 'Tests passed' : 'Tests failed'}</StatusPill>
              ) : (
                <span className="text-fg-2">Loading report</span>
              ),
            },
            ...(run.approval
              ? [{ label: 'Approved', value: `${run.approval.reviewer} · ${run.approval.approved_at}` }]
              : []),
            ...(run.rejection
              ? [
                  {
                    label: 'Rejected',
                    value: `${run.rejection.reviewer} · ${run.rejection.rejected_at}${run.rejection.reason ? ` · ${run.rejection.reason}` : ''}`,
                  },
                ]
              : []),
            ...(run.parent_run_id
              ? [
                  {
                    label: 'Parent candidate',
                    value: (
                      <Link to={`/jobs/${run.parent_run_id}/review`} className="text-accent font-mono text-xs">
                        {run.parent_run_id}
                      </Link>
                    ),
                  },
                ]
              : []),
          ]}
        />
        <p className="px-4 pb-3 text-xs text-fg-2">
          Approval is recorded against this exact digest by a named engineer. It never enables a live write.
        </p>
      </SectionCard>

      {hasChanges && (
        <SectionCard title="Changes from parent">
          <ul className="px-4 py-3 text-sm flex flex-col gap-1 font-mono text-xs">
            {changes.added.map((item) => (
              <li key={`a-${item}`} className="text-ok">+ {item}</li>
            ))}
            {changes.modified.map((item) => (
              <li key={`m-${item}`} className="text-warn">~ {item}</li>
            ))}
            {changes.removed.map((item) => (
              <li key={`r-${item}`} className="text-fail">− {item}</li>
            ))}
          </ul>
        </SectionCard>
      )}

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
    </StageFrame>
  );
}
