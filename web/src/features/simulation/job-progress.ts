/**
 * Live job progress: a server-sent stream first, polling as the fallback.
 * The tracker is plain TypeScript with injectable transports so it can be
 * tested without a browser; the hook wraps it for React.
 */

import { useEffect, useState } from 'react';

import { api } from '../../api/client';
import type { QualificationJob } from '../../api/client';
import type { Tone } from '../../design-system/primitives';

export const TERMINAL_STATUSES = new Set<QualificationJob['status']>(['succeeded', 'failed', 'canceled']);

export interface ProgressEvent {
  id: string;
  status: QualificationJob['status'];
  progress: QualificationJob['progress'];
  heartbeat_at: string | null;
  updated_at: string;
  error: string | null;
  qualification_passed: boolean | null;
  result_artifact_sha256: string | null;
  cancellation_requested: boolean;
}

export interface ProgressState {
  job: QualificationJob;
  source: 'sse' | 'poll' | 'final';
  terminal: boolean;
}

export interface StreamHandle {
  close: () => void;
}

export interface TrackerTransports {
  /** Open a server-sent stream; call onEvent per progress event, onError when it breaks. Return null when unsupported. */
  openStream: (jobId: string, onEvent: (event: ProgressEvent) => void, onError: () => void, onGone: () => void) => StreamHandle | null;
  fetchJob: (jobId: string) => Promise<QualificationJob>;
  pollIntervalMs?: number;
}

export const HEARTBEAT_WARN_SECONDS = 30;

export function jobTone(job: QualificationJob): { tone: Tone; label: string } {
  switch (job.status) {
    case 'queued':
      return { tone: 'info', label: 'Queued' };
    case 'running':
      return { tone: 'info', label: 'Running' };
    case 'cancel_requested':
      return { tone: 'warn', label: 'Cancelling' };
    case 'canceled':
      return { tone: 'neutral', label: 'Canceled' };
    case 'failed':
      return { tone: 'fail', label: 'Failed' };
    case 'succeeded':
      if (job.qualification_passed === true) return { tone: 'ok', label: 'Qualification passed' };
      if (job.qualification_passed === false) return { tone: 'fail', label: 'Qualification failed' };
      return { tone: 'neutral', label: 'Finished' };
  }
}

export function isTerminal(status: QualificationJob['status']): boolean {
  return TERMINAL_STATUSES.has(status);
}

export function applyEvent(job: QualificationJob, event: ProgressEvent): QualificationJob {
  return { ...job, status: event.status, progress: event.progress, heartbeat_at: event.heartbeat_at, updated_at: event.updated_at, error: event.error, qualification_passed: event.qualification_passed, result_artifact_sha256: event.result_artifact_sha256, cancellation_requested: event.cancellation_requested };
}

/**
 * Follow one job until it ends. Emits every state change to `onChange` and
 * stops on its own at a terminal status; `stop()` cancels early.
 */
export function trackJob(initial: QualificationJob, transports: TrackerTransports, onChange: (state: ProgressState) => void): () => void {
  let current = initial;
  let stopped = false;
  let stream: StreamHandle | null = null;
  let pollTimer: number | null = null;
  const interval = transports.pollIntervalMs ?? 2000;

  const finish = (job: QualificationJob) => {
    current = job;
    onChange({ job, source: 'final', terminal: true });
    stop();
  };

  const poll = async () => {
    if (stopped) return;
    try {
      const job = await transports.fetchJob(current.id);
      if (stopped) return;
      current = job;
      if (isTerminal(job.status)) {
        finish(job);
        return;
      }
      onChange({ job, source: 'poll', terminal: false });
    } catch {
      // A failed poll keeps the last state; the next tick tries again.
    }
    if (!stopped) pollTimer = window.setTimeout(() => void poll(), interval);
  };

  const startPolling = () => {
    if (stopped || pollTimer !== null) return;
    pollTimer = window.setTimeout(() => void poll(), 0);
  };

  if (isTerminal(initial.status)) {
    onChange({ job: initial, source: 'final', terminal: true });
    return () => {};
  }

  stream = transports.openStream(
    initial.id,
    (event) => {
      if (stopped) return;
      const job = applyEvent(current, event);
      current = job;
      if (isTerminal(job.status)) finish(job);
      else onChange({ job, source: 'sse', terminal: false });
    },
    () => {
      // Stream broke or is unavailable: fall back to polling.
      stream?.close();
      stream = null;
      startPolling();
    },
    () => finish({ ...current, status: 'failed', error: current.error ?? 'The job record is no longer available.' }),
  );
  if (!stream) startPolling();

  function stop() {
    stopped = true;
    stream?.close();
    stream = null;
    if (pollTimer !== null) window.clearTimeout(pollTimer);
    pollTimer = null;
  }
  return stop;
}

export function browserTransports(): TrackerTransports {
  return {
    openStream(jobId, onEvent, onError, onGone) {
      if (typeof EventSource === 'undefined') return null;
      const source = new EventSource(`/api/qualification-jobs/${encodeURIComponent(jobId)}/events`);
      source.addEventListener('progress', (message) => {
        try {
          onEvent(JSON.parse((message as MessageEvent<string>).data) as ProgressEvent);
        } catch {
          onError();
        }
      });
      source.addEventListener('gone', () => {
        source.close();
        onGone();
      });
      source.addEventListener('error', () => onError());
      source.onerror = () => onError();
      return { close: () => source.close() };
    },
    fetchJob: (jobId) => api.qualificationJob(jobId),
  };
}

/** React hook: the latest job state, live while it runs. */
export function useJobProgress(initial: QualificationJob | undefined, transports: TrackerTransports = browserTransports()): ProgressState | null {
  const [state, setState] = useState<ProgressState | null>(null);
  const key = initial ? `${initial.id}:${initial.updated_at}` : null;
  useEffect(() => {
    if (!initial) return;
    return trackJob(initial, transports, setState);
    // Re-track when a different job (or a fresher record) arrives.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  if (!initial) return null;
  if (!state || state.job.id !== initial.id) return { job: initial, source: isTerminal(initial.status) ? 'final' : 'poll', terminal: isTerminal(initial.status) };
  return state;
}

export function heartbeatAgeSeconds(job: QualificationJob, now = Date.now()): number | null {
  if (!job.heartbeat_at) return null;
  const at = Date.parse(job.heartbeat_at);
  return Number.isFinite(at) ? Math.max(0, (now - at) / 1000) : null;
}
