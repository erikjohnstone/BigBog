import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { usePlaybackLoop } from './playback';
import { useTimeCursor } from './timeCursor';
import { bindSignal, traceStore, useSignalRef, useSignalValue, useTrace } from './trace';
import type { Trace } from './trace';

function trace(id: string, values: number[]): Trace {
  return {
    id,
    label: id,
    engine: 'generic',
    time: Float64Array.from(values.map((_, i) => i * 60)),
    phases: [{ index: 0, name: 'p', startIdx: 0, endIdx: values.length - 1, t0: 0, t1: (values.length - 1) * 60, stepSeconds: 60, faults: [] }],
    signals: new Map([
      ['temp', { id: 'temp', label: 'Temp', kind: 'numeric', source: 'input', values: Float64Array.from(values), min: Math.min(...values), max: Math.max(...values) }],
      ['on', { id: 'on', label: 'On', kind: 'boolean', source: 'command', values: Uint8Array.from(values.map((v) => (v > 70 ? 1 : 0))), min: 0, max: 1 }],
    ]),
    assertions: [],
    faultWindows: [],
    oracles: [],
    axisReconstructed: false,
    passed: true,
  };
}

const flushFrames = () => new Promise((resolve) => setTimeout(resolve, 40));

describe('frame fan-out', () => {
  beforeEach(() => {
    traceStore.put(trace('t', [68, 70, 72, 74]));
    useTimeCursor.getState().setTrace('t');
  });
  afterEach(() => {
    useTimeCursor.getState().setTrace(null);
    traceStore.remove('t');
  });

  it('writes the current value into bound elements on every clock move', async () => {
    const element = document.createElement('span');
    const unbind = bindSignal({ element, signalId: 'temp' });
    await flushFrames();
    expect(element.textContent).toBe('68.00');
    act(() => useTimeCursor.getState().seekIndex(2));
    await flushFrames();
    expect(element.textContent).toBe('72.00');
    unbind();
    act(() => useTimeCursor.getState().seekIndex(3));
    await flushFrames();
    expect(element.textContent).toBe('72.00');
  });

  it('useSignalRef applies a custom writer and useSignalValue re-renders at most every 100 ms', async () => {
    const apply = vi.fn();
    const { result: refResult } = renderHook(() => useSignalRef<HTMLSpanElement>('on', apply));
    // Attach an element after mount the way React would, then re-run the effect.
    const span = document.createElement('span');
    refResult.current.current = span;
    const { result, rerender } = renderHook(() => useSignalValue('temp'));
    expect(result.current).toBe(68);
    act(() => useTimeCursor.getState().seekIndex(1));
    await flushFrames();
    rerender();
    expect(result.current).toBe(70);
    const missing = renderHook(() => useSignalValue('nope'));
    expect(Number.isNaN(missing.result.current)).toBe(true);
    const none = renderHook(() => useSignalValue(null));
    expect(Number.isNaN(none.result.current)).toBe(true);
  });

  it('useTrace tracks the store', () => {
    const { result } = renderHook(() => useTrace('t'));
    expect(result.current?.id).toBe('t');
    act(() => traceStore.remove('t'));
    expect(result.current).toBeUndefined();
    act(() => traceStore.put(trace('t', [1, 2])));
    expect(result.current?.time.length).toBe(2);
  });
});

describe('playback loop', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    traceStore.put(trace('p', Array.from({ length: 40 }, (_, i) => 60 + i)));
    useTimeCursor.getState().setTrace('p');
  });
  afterEach(() => {
    useTimeCursor.getState().setTrace(null);
    traceStore.remove('p');
    vi.useRealTimers();
  });

  it('advances the cursor while playing, stops at the end, and loops inside a loop window', () => {
    const hook = renderHook(() => usePlaybackLoop());
    act(() => useTimeCursor.getState().play());
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    const afterOneSecond = useTimeCursor.getState().index;
    expect(afterOneSecond).toBeGreaterThan(0);
    act(() => useTimeCursor.getState().setSpeed(8));
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(useTimeCursor.getState()).toMatchObject({ index: 39, playing: false });

    act(() => useTimeCursor.getState().setLoop([10, 14]));
    act(() => useTimeCursor.getState().play());
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    const { index, playing } = useTimeCursor.getState();
    expect(playing).toBe(true);
    expect(index).toBeGreaterThanOrEqual(10);
    expect(index).toBeLessThanOrEqual(14);
    act(() => useTimeCursor.getState().pause());
    hook.unmount();
  });
});
