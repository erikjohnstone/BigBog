/**
 * The single playback loop.
 *
 * When the clock is playing, one requestAnimationFrame loop advances the
 * cursor index at `speed` scans per real second (scaled so a 1x playback of
 * a 60-second-per-scan case still moves visibly). Nothing else in the app
 * uses timers to move time.
 */

import { useEffect } from 'react';

import { useTimeCursor } from './timeCursor';

/** Base scans per second at 1x; higher speeds multiply this. */
const BASE_SCANS_PER_SECOND = 8;

let rafId: number | null = null;
let lastTs = 0;
let accumulator = 0;

function tick(ts: number): void {
  const state = useTimeCursor.getState();
  if (!state.playing) {
    rafId = null;
    return;
  }
  if (lastTs === 0) lastTs = ts;
  const dt = (ts - lastTs) / 1000;
  lastTs = ts;
  accumulator += dt * BASE_SCANS_PER_SECOND * state.speed;
  const whole = Math.floor(accumulator);
  if (whole >= 1) {
    accumulator -= whole;
    const end = state.loop ? state.loop[1] : state.length - 1;
    const start = state.loop ? state.loop[0] : 0;
    let next = state.index + whole;
    if (next > end) {
      // Loop when a loop range is set; otherwise stop at the end.
      if (state.loop) next = start + ((next - start) % (end - start + 1));
      else {
        state.seekIndex(end);
        state.pause();
        rafId = null;
        return;
      }
    }
    state.seekIndex(next);
  }
  rafId = requestAnimationFrame(tick);
}

function start(): void {
  if (rafId !== null) return;
  lastTs = 0;
  accumulator = 0;
  rafId = requestAnimationFrame(tick);
}

let installed = false;

/** Mount once near the root; keeps the loop alive while `playing` is true. */
export function usePlaybackLoop(): void {
  useEffect(() => {
    if (installed) return;
    installed = true;
    const unsubscribe = useTimeCursor.subscribe((state, previous) => {
      if (state.playing && !previous.playing) start();
    });
    if (useTimeCursor.getState().playing) start();
    return () => {
      unsubscribe();
      installed = false;
      if (rafId !== null) cancelAnimationFrame(rafId);
      rafId = null;
    };
  }, []);
}
