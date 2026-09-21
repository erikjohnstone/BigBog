/**
 * The one clock.
 *
 * Every time-aware view (wiresheet value chips, schematic animation, trend
 * cursors, the master timeline needle, 3D) reads from this store and none of
 * them owns time. Scrubbing anywhere moves everything.
 *
 * `index` is authoritative: it is a sample index into the active trace. `t`
 * is derived from the trace's time axis so views that think in seconds
 * (trends) and views that think in scans (wiresheet stepping) agree exactly.
 */

import { create } from 'zustand';

import { traceStore } from './trace';

export type PlaybackSpeed = 0.25 | 0.5 | 1 | 2 | 4 | 8;

export interface TimeCursorState {
  traceId: string | null;
  length: number;
  index: number;
  t: number;
  range: [number, number];
  loop: [number, number] | null;
  playing: boolean;
  speed: PlaybackSpeed;

  setTrace: (traceId: string | null) => void;
  seekIndex: (index: number) => void;
  seekTime: (t: number) => void;
  step: (delta: number) => void;
  play: () => void;
  pause: () => void;
  toggle: () => void;
  setSpeed: (speed: PlaybackSpeed) => void;
  setLoop: (loop: [number, number] | null) => void;
  setRange: (range: [number, number]) => void;
  jumpToFailure: (assertionId: string) => void;
  jumpToNextFailure: (direction: 1 | -1) => void;
}

function clamp(value: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, value));
}

function timeAt(traceId: string | null, index: number): number {
  const trace = traceId ? traceStore.get(traceId) : undefined;
  if (!trace || trace.time.length === 0) return 0;
  return trace.time[clamp(index, 0, trace.time.length - 1)];
}

export const useTimeCursor = create<TimeCursorState>((set, get) => ({
  traceId: null,
  length: 0,
  index: 0,
  t: 0,
  range: [0, 0],
  loop: null,
  playing: false,
  speed: 1,

  setTrace(traceId) {
    const trace = traceId ? traceStore.get(traceId) : undefined;
    const length = trace?.time.length ?? 0;
    const last = length > 0 ? trace!.time[length - 1] : 0;
    set({
      traceId,
      length,
      index: 0,
      t: timeAt(traceId, 0),
      range: [0, last],
      loop: null,
      playing: false,
    });
  },

  seekIndex(index) {
    const { traceId, length, loop } = get();
    if (length === 0) return;
    let next = clamp(Math.round(index), 0, length - 1);
    if (loop) next = clamp(next, loop[0], loop[1]);
    set({ index: next, t: timeAt(traceId, next) });
  },

  seekTime(t) {
    const { traceId } = get();
    const trace = traceId ? traceStore.get(traceId) : undefined;
    if (!trace || trace.time.length === 0) return;
    // Binary search for the last sample at or before t.
    const time = trace.time;
    let lo = 0;
    let hi = time.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (time[mid] <= t) lo = mid;
      else hi = mid - 1;
    }
    get().seekIndex(lo);
  },

  step(delta) {
    get().seekIndex(get().index + delta);
  },

  play() {
    if (get().length > 1) set({ playing: true });
  },
  pause() {
    set({ playing: false });
  },
  toggle() {
    if (get().playing) get().pause();
    else get().play();
  },
  setSpeed(speed) {
    set({ speed });
  },

  setLoop(loop) {
    const { length } = get();
    if (!loop) {
      set({ loop: null });
      return;
    }
    const start = clamp(Math.min(loop[0], loop[1]), 0, Math.max(0, length - 1));
    const end = clamp(Math.max(loop[0], loop[1]), 0, Math.max(0, length - 1));
    set({ loop: [start, end] });
    get().seekIndex(clamp(get().index, start, end));
  },

  setRange(range) {
    set({ range: [Math.min(range[0], range[1]), Math.max(range[0], range[1])] });
  },

  jumpToFailure(assertionId) {
    const { traceId } = get();
    const trace = traceId ? traceStore.get(traceId) : undefined;
    const assertion = trace?.assertions.find((item) => item.id === assertionId);
    if (!assertion) return;
    const phase = trace!.phases[assertion.phaseIndex];
    set({ playing: false, loop: phase ? [phase.startIdx, phase.endIdx] : null });
    get().seekIndex(assertion.index);
  },

  jumpToNextFailure(direction) {
    const { traceId, index } = get();
    const trace = traceId ? traceStore.get(traceId) : undefined;
    if (!trace) return;
    const failures = trace.assertions.filter((item) => !item.passed).sort((a, b) => a.index - b.index);
    if (failures.length === 0) return;
    const next =
      direction === 1
        ? (failures.find((item) => item.index > index) ?? failures[0])
        : ([...failures].reverse().find((item) => item.index < index) ?? failures[failures.length - 1]);
    get().jumpToFailure(next.id);
  },
}));
