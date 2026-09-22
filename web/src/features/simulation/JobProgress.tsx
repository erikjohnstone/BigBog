import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Radio, XCircle } from 'lucide-react';
import { useEffect, useState } from 'react';

import { api } from '../../api/client';
import { keys, useLatestQualificationJob } from '../../api/queries';
import { Button, StatusPill } from '../../design-system/primitives';
import { MissingEvidence } from '../../design-system/states';
import { HEARTBEAT_WARN_SECONDS, heartbeatAgeSeconds, isTerminal, jobKindLabel, jobTone, useJobProgress } from './job-progress';

/** A clock that ticks only while something is worth timing. */
function useNow(active: boolean, everyMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(Date.now()), everyMs);
    return () => window.clearInterval(timer);
  }, [active, everyMs]);
  return now;
}

/**
 * The latest qualification job for a run, followed live over the server
 * stream (polling when the stream is unavailable). Every one of the six
 * states is spelled out; a stale heartbeat is called out rather than hidden.
 */
export function JobProgress({ runId }: { runId: string }) {
  const latest = useLatestQualificationJob(runId);
  const initial = latest.data?.state === 'available' ? latest.data.data : undefined;
  const progress = useJobProgress(initial);
  const queryClient = useQueryClient();
  const job = progress?.job;
  const running = Boolean(job && !isTerminal(job.status));
  const now = useNow(running);

  // When a job ends, the evidence it produced is new: refetch it.
  const settledKey = job && progress?.terminal ? `${job.id}:${job.status}` : null;
  useEffect(() => {
    if (!settledKey) return;
    void queryClient.invalidateQueries({ queryKey: keys.boptest(runId) });
    void queryClient.invalidateQueries({ queryKey: keys.alfalfa(runId) });
    void queryClient.invalidateQueries({ queryKey: keys.shadow(runId) });
    void queryClient.invalidateQueries({ queryKey: keys.niagaraPreviews(runId) });
    void queryClient.invalidateQueries({ queryKey: keys.releaseSummary(runId) });
    void queryClient.invalidateQueries({ queryKey: keys.report(runId) });
    void queryClient.invalidateQueries({ queryKey: keys.run(runId) });
  }, [settledKey, queryClient, runId]);

  const cancel = useMutation({
    mutationFn: (jobId: string) => api.cancelQualificationJob(jobId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: keys.latestJob(runId) }),
  });

  if (latest.isLoading) return <p className="px-4 py-3 text-sm text-fg-2">Checking for qualification jobs…</p>;
  if (latest.data?.state === 'invalid') return <MissingEvidence kind="Qualification job" state="invalid" detail={latest.data.message} />;
  if (!job) {
    return (
      <div className="px-4 py-4 text-sm text-fg-1">
        <p>No qualification job has been queued for this candidate.</p>
        <p className="mt-1 text-xs text-fg-2">Start one with a BOPTEST case, an FMU, or the Shadow Runtime; progress streams here while it runs.</p>
      </div>
    );
  }

  const { tone, label } = jobTone(job);
  const heartbeat = heartbeatAgeSeconds(job, now);
  const stale = running && heartbeat !== null && heartbeat > HEARTBEAT_WARN_SECONDS;
  const percent = Math.round(job.progress.percent);
  const cancellable = job.status === 'queued' || job.status === 'running';

  return (
    <div className="px-4 py-3 flex flex-col gap-3" data-testid="job-progress" data-status={job.status}>
      <div className="flex items-center gap-2 flex-wrap">
        <StatusPill tone={tone}>{label}</StatusPill>
        <StatusPill tone="sim">{jobKindLabel(job.kind)} · {job.transport.replaceAll('_', ' ')}</StatusPill>
        {job.cancellation_requested && job.status !== 'canceled' && <StatusPill tone="warn">Cancel requested</StatusPill>}
        <span className="flex-1" />
        <span className="inline-flex items-center gap-1 text-2xs text-fg-2" title="How progress reaches this page">
          <Radio size={11} aria-hidden />
          {progress?.source === 'sse' ? 'live stream' : progress?.source === 'poll' ? 'polling' : 'final'}
        </span>
        {cancellable && (
          <Button size="xs" variant="outline" onClick={() => cancel.mutate(job.id)} disabled={cancel.isPending}>
            <XCircle size={12} /> Cancel
          </Button>
        )}
      </div>
      <div>
        <div className="flex items-baseline justify-between text-xs">
          <span className="text-fg-1">{job.progress.phase.replaceAll('_', ' ')}</span>
          <span className="num text-fg-2">
            {job.progress.completed_steps}/{job.progress.total_steps} steps · {percent}%
          </span>
        </div>
        <div
          role="progressbar"
          aria-label="Qualification progress"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
          className="mt-1 h-1.5 rounded-pill bg-bg-3 overflow-hidden"
        >
          <div
            className={tone === 'fail' ? 'h-full bg-fail' : tone === 'ok' ? 'h-full bg-ok' : 'h-full bg-accent'}
            style={{ width: `${percent}%`, transition: 'width var(--duration-state) var(--ease-out)' }}
          />
        </div>
      </div>
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-xs">
        <dt className="text-fg-2">Heartbeat</dt>
        <dd className={stale ? 'text-warn' : 'text-fg-1'}>
          {heartbeat === null ? 'none yet' : `${Math.round(heartbeat)} s ago`}
          {stale && ' — the worker has gone quiet'}
        </dd>
        <dt className="text-fg-2">Worker</dt>
        <dd className="text-fg-1 truncate">{job.worker_id ?? '—'}</dd>
        <dt className="text-fg-2">Job</dt>
        <dd className="num text-fg-1 truncate" title={job.id}>
          {job.id}
        </dd>
        {job.result_artifact_sha256 && (
          <>
            <dt className="text-fg-2">Result digest</dt>
            <dd className="num text-fg-1 truncate" title={job.result_artifact_sha256}>
              {job.result_artifact_sha256.slice(0, 16)}…
            </dd>
          </>
        )}
      </dl>
      {job.error && (
        <p role="alert" className="text-xs text-fail break-words">
          {job.error}
        </p>
      )}
      {cancel.isError && (
        <p role="alert" className="text-xs text-fail">
          {(cancel.error as Error).message}
        </p>
      )}
    </div>
  );
}
