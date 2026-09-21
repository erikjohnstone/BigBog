import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { QualificationJob } from '../../api/client';
import { heartbeatAgeSeconds, trackJob } from './job-progress';
import type { ProgressEvent, ProgressState, TrackerTransports } from './job-progress';

const base: QualificationJob = {
  schema_version: 'bactalk.qualification-job/v3',
  id: 'job-1',
  broker_job_id: 'b',
  run_id: 'r',
  candidate_artifact_sha256: null,
  kind: 'boptest',
  transport: 'boptest_rest',
  status: 'queued',
  model_filename: null,
  model_sha256: null,
  request_sha256: 'x',
  input_sha256: 'y',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  started_at: null,
  completed_at: null,
  heartbeat_at: null,
  lease_expires_at: null,
  worker_id: null,
  actor_id: null,
  tenant_id: null,
  progress: { phase: 'queued', completed_steps: 0, total_steps: 10, percent: 0 },
  cancellation_requested: false,
  error: null,
  result_artifact_sha256: null,
  qualification_passed: null,
};

function event(status: QualificationJob['status'], completed: number): ProgressEvent {
  return { id: 'job-1', status, progress: { phase: status, completed_steps: completed, total_steps: 10, percent: completed * 10 }, heartbeat_at: '2026-01-01T00:00:05Z', updated_at: '2026-01-01T00:00:05Z', error: null, qualification_passed: status === 'succeeded' ? true : null, result_artifact_sha256: null, cancellation_requested: false };
}

describe('trackJob', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('follows the stream and stops by itself at a terminal status', () => {
    const states: ProgressState[] = [];
    let closed = false;
    let emit: ((event: ProgressEvent) => void) | null = null;
    const transports: TrackerTransports = {
      openStream: (_id, onEvent) => {
        emit = onEvent;
        return { close: () => { closed = true; } };
      },
      fetchJob: vi.fn(),
    };
    trackJob(base, transports, (state) => states.push(state));
    emit!(event('running', 3));
    emit!(event('running', 7));
    emit!(event('succeeded', 10));
    emit!(event('running', 9)); // ignored after stop
    expect(states.map((state) => [state.source, state.job.status, state.job.progress.completed_steps])).toEqual([
      ['sse', 'running', 3],
      ['sse', 'running', 7],
      ['final', 'succeeded', 10],
    ]);
    expect(states[2].terminal).toBe(true);
    expect(closed).toBe(true);
    expect(transports.fetchJob).not.toHaveBeenCalled();
  });

  it('falls back to polling when the stream breaks and stops at the end', async () => {
    const states: ProgressState[] = [];
    let fail: (() => void) | null = null;
    const answers: QualificationJob[] = [{ ...base, status: 'running', progress: { phase: 'simulating', completed_steps: 4, total_steps: 10, percent: 40 } }, { ...base, status: 'failed', error: 'boom' }];
    const fetchJob = vi.fn(async () => answers.shift() ?? answers[0]);
    const transports: TrackerTransports = {
      openStream: (_id, _onEvent, onError) => {
        fail = onError;
        return { close: () => {} };
      },
      fetchJob,
      pollIntervalMs: 1000,
    };
    trackJob(base, transports, (state) => states.push(state));
    fail!();
    await vi.advanceTimersByTimeAsync(0);
    expect(states.at(-1)).toMatchObject({ source: 'poll', job: { status: 'running' } });
    await vi.advanceTimersByTimeAsync(1000);
    expect(states.at(-1)).toMatchObject({ source: 'final', terminal: true, job: { status: 'failed', error: 'boom' } });
    const calls = fetchJob.mock.calls.length;
    await vi.advanceTimersByTimeAsync(5000);
    expect(fetchJob.mock.calls.length).toBe(calls);
  });

  it('polls immediately when streams are unsupported and honours stop()', async () => {
    const fetchJob = vi.fn(async () => ({ ...base, status: 'running' as const }));
    const stop = trackJob(base, { openStream: () => null, fetchJob, pollIntervalMs: 500 }, () => {});
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchJob).toHaveBeenCalledTimes(1);
    stop();
    await vi.advanceTimersByTimeAsync(2000);
    expect(fetchJob).toHaveBeenCalledTimes(1);
  });

  it('reports a terminal initial job once without opening anything', () => {
    const openStream = vi.fn();
    const states: ProgressState[] = [];
    trackJob({ ...base, status: 'canceled' }, { openStream, fetchJob: vi.fn() }, (state) => states.push(state));
    expect(openStream).not.toHaveBeenCalled();
    expect(states).toEqual([{ job: { ...base, status: 'canceled' }, source: 'final', terminal: true }]);
  });

  it('computes heartbeat age', () => {
    expect(heartbeatAgeSeconds(base)).toBeNull();
    expect(heartbeatAgeSeconds({ ...base, heartbeat_at: '2026-01-01T00:00:00Z' }, Date.parse('2026-01-01T00:00:45Z'))).toBe(45);
  });
});
