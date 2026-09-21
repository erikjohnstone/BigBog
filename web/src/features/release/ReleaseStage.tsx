import type { RunDetail } from '../../api/client';
import { useReleaseSummary } from '../../api/queries';
import { StatusPill } from '../../design-system/primitives';
import { ErrorState, LoadingState } from '../../design-system/states';
import { KeyValue, SectionCard, StageFrame } from '../shared/StageFrame';
import { ExportHandoff } from './ExportHandoff';

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Release stage: the server's release summary and the hand-off, downloads only once approved. */
export function ReleaseStage({ run }: { run: RunDetail }) {
  const summary = useReleaseSummary(run.id);
  if (summary.isLoading) return <LoadingState label="Loading release summary" />;
  if (summary.isError || !summary.data) {
    return <ErrorState error={summary.error ?? 'Release summary unavailable'} onRetry={() => summary.refetch()} />;
  }
  const data = summary.data;
  const approved = data.status === 'approved';

  return (
    <StageFrame>
      <SectionCard
        title="Release"
        aside={<StatusPill tone={approved ? 'ok' : 'neutral'}>{approved ? 'Approved' : 'Export locked'}</StatusPill>}
      >
        <KeyValue
          items={[
            {
              label: 'Integrity',
              value: (
                <span className="inline-flex items-center gap-2">
                  <StatusPill tone={data.integrity.verified ? 'ok' : 'fail'}>{data.integrity.verified ? 'verified' : 'mismatch'}</StatusPill>
                  <span className="num">{data.integrity.artifact_sha256}</span>
                </span>
              ),
            },
            {
              label: 'Behavior',
              value: (
                <span className="num">
                  {data.behavior.passed_assertion_count} / {data.behavior.assertion_count} assertions across {data.behavior.scenario_count} scenarios
                </span>
              ),
            },
            { label: 'Target', value: <span className="font-mono text-xs">{data.target.artifact_kind}{data.target.filename ? ` · ${data.target.filename}` : ''}</span> },
            {
              label: 'Licensed runtime',
              value: data.target.licensed_runtime_qualified ? (
                <StatusPill tone="ok">qualified</StatusPill>
              ) : (
                <span className="text-fg-1">Not qualified. Manual import into a licensed Workbench is required.</span>
              ),
            },
            ...(data.approval ? [{ label: 'Approved by', value: `${data.approval.reviewer} · ${data.approval.approved_at}` }] : []),
          ]}
        />
      </SectionCard>

      {data.deliverables.blocking_gates.length > 0 && (
        <SectionCard title="Blocking gates">
          <ul className="px-4 py-3 text-sm flex flex-col gap-1">
            {data.deliverables.blocking_gates.map((gate) => (
              <li key={gate} className="text-warn">{gate}</li>
            ))}
          </ul>
        </SectionCard>
      )}

      <SectionCard title="Artifacts">
        {data.deliverables.artifacts.length === 0 ? (
          <p className="px-4 py-3 text-sm text-fg-2">No deliverable artifacts retained.</p>
        ) : (
          <ul className="divide-y divide-line-1">
            {data.deliverables.artifacts.map((artifact) => (
              <li key={artifact.path} className="flex items-center gap-3 px-4 h-9 text-sm">
                <span className="font-mono text-xs truncate">{artifact.path}</span>
                <span className="flex-1" />
                <span className="num text-fg-2">{formatBytes(artifact.bytes)}</span>
                <span className="num text-fg-2" title={artifact.sha256}>{artifact.sha256.slice(0, 12)}</span>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>

      <ExportHandoff summary={data} />
    </StageFrame>
  );
}
