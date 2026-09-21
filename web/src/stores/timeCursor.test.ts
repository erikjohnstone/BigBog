import { beforeEach, describe, expect, it } from 'vitest';

import { useTimeCursor } from './timeCursor';
import { bindSignal, setBindingGroupActive, traceStore } from './trace';
import type { Trace } from './trace';

function makeTrace(): Trace {
  const time = Float64Array.from([0, 60, 120, 180, 240, 300]);
  return {
    id: 'trace-1',
    label: 'test',
    engine: 'generic',
    time,
    phases: [
      { index: 0, name: 'warm', startIdx: 0, endIdx: 2, t0: 0, t1: 120, stepSeconds: 60, faults: [] },
      { index: 1, name: 'fault', startIdx: 3, endIdx: 5, t0: 180, t1: 300, stepSeconds: 60, faults: [] },
    ],
    signals: new Map([
      [
        'zone',
        {
          id: 'zone',
          label: 'Zone temp',
          kind: 'numeric',
          source: 'input',
          unit: '°F',
          values: Float64Array.from([70, 71, 72, 73, 74, 75]),
          min: 70,
          max: 75,
        },
      ],
      [
        'fan',
        {
          id: 'fan',
          label: 'Fan',
          kind: 'boolean',
          source: 'block',
          values: Uint8Array.from([0, 1, 1, 255, 0, 1]),
          min: 0,
          max: 1,
        },
      ],
    ]),
    assertions: [
      { id: 'a0', name: 'warm ok', passed: true, observed: '72', expected: '<80', index: 2, phaseIndex: 0, blockIds: [] },
      { id: 'a1', name: 'fault fail', passed: false, observed: '75', expected: '<74', index: 5, phaseIndex: 1, blockIds: ['Fan'] },
    ],
    faultWindows: [],
    oracles: [],
    axisReconstructed: false,
    passed: false,
  };
}

describe('timeCursor', () => {
  beforeEach(() => {
    traceStore.put(makeTrace());
    useTimeCursor.getState().setTrace('trace-1');
  });

  it('starts at index 0 with the full range', () => {
    const state = useTimeCursor.getState();
    expect(state.length).toBe(6);
    expect(state.index).toBe(0);
    expect(state.t).toBe(0);
    expect(state.range).toEqual([0, 300]);
    expect(state.playing).toBe(false);
  });

  it('clamps seekIndex to the trace and updates t', () => {
    useTimeCursor.getState().seekIndex(99);
    expect(useTimeCursor.getState().index).toBe(5);
    expect(useTimeCursor.getState().t).toBe(300);
    useTimeCursor.getState().seekIndex(-4);
    expect(useTimeCursor.getState().index).toBe(0);
    useTimeCursor.getState().seekIndex(2.4);
    expect(useTimeCursor.getState().index).toBe(2);
  });

  it('seekTime picks the last sample at or before t', () => {
    useTimeCursor.getState().seekTime(125);
    expect(useTimeCursor.getState().index).toBe(2);
    useTimeCursor.getState().seekTime(180);
    expect(useTimeCursor.getState().index).toBe(3);
    useTimeCursor.getState().seekTime(-10);
    expect(useTimeCursor.getState().index).toBe(0);
    useTimeCursor.getState().seekTime(10_000);
    expect(useTimeCursor.getState().index).toBe(5);
  });

  it('respects a loop window when stepping', () => {
    useTimeCursor.getState().setLoop([1, 3]);
    useTimeCursor.getState().seekIndex(0);
    expect(useTimeCursor.getState().index).toBe(1);
    useTimeCursor.getState().step(10);
    expect(useTimeCursor.getState().index).toBe(3);
  });

  it('jumpToFailure seeks to the assertion and loops its phase', () => {
    useTimeCursor.getState().jumpToFailure('a1');
    const state = useTimeCursor.getState();
    expect(state.index).toBe(5);
    expect(state.loop).toEqual([3, 5]);
    expect(state.playing).toBe(false);
  });

  it('jumpToNextFailure wraps around failing assertions only', () => {
    useTimeCursor.getState().jumpToNextFailure(1);
    expect(useTimeCursor.getState().index).toBe(5);
    useTimeCursor.getState().jumpToNextFailure(1);
    expect(useTimeCursor.getState().index).toBe(5);
    useTimeCursor.getState().jumpToNextFailure(-1);
    expect(useTimeCursor.getState().index).toBe(5);
  });

  it('play refuses a single-sample trace', () => {
    traceStore.put({ ...makeTrace(), id: 'one', time: Float64Array.from([0]) });
    useTimeCursor.getState().setTrace('one');
    useTimeCursor.getState().play();
    expect(useTimeCursor.getState().playing).toBe(false);
  });

  it('resets when the trace is cleared', () => {
    useTimeCursor.getState().seekIndex(4);
    useTimeCursor.getState().setTrace(null);
    const state = useTimeCursor.getState();
    expect(state.length).toBe(0);
    expect(state.index).toBe(0);
    expect(state.range).toEqual([0, 0]);
  });
});

describe('traceStore.valueAt', () => {
  beforeEach(() => {
    traceStore.put(makeTrace());
  });

  it('reads numeric values and NaN outside the trace', () => {
    expect(traceStore.valueAt('trace-1', 'zone', 3)).toBe(73);
    expect(traceStore.valueAt('trace-1', 'zone', -1)).toBeNaN();
    expect(traceStore.valueAt('trace-1', 'zone', 6)).toBeNaN();
    expect(traceStore.valueAt('trace-1', 'missing', 0)).toBeNaN();
    expect(traceStore.valueAt('nope', 'zone', 0)).toBeNaN();
  });

  it('maps the boolean sentinel 255 to NaN', () => {
    expect(traceStore.valueAt('trace-1', 'fan', 1)).toBe(1);
    expect(traceStore.valueAt('trace-1', 'fan', 3)).toBeNaN();
  });

  it('notifies subscribers on put and remove', () => {
    let calls = 0;
    const unsubscribe = traceStore.subscribe(() => {
      calls += 1;
    });
    traceStore.put(makeTrace());
    traceStore.remove('trace-1');
    unsubscribe();
    traceStore.put(makeTrace());
    expect(calls).toBe(2);
  });
});

describe('binding groups', () => {
  beforeEach(() => {
    traceStore.put(makeTrace());
    useTimeCursor.getState().setTrace('trace-1');
  });

  it('skips paused groups and repaints them on resume', async () => {
    const paint = () => new Promise((resolve) => requestAnimationFrame(resolve));
    const chip = document.createElement('span');
    const live = document.createElement('span');
    const unbindChip = bindSignal({ element: chip, signalId: 'zone', group: 'lod' });
    const unbindLive = bindSignal({ element: live, signalId: 'zone' });
    await paint();
    expect(chip.textContent).toBe('70.00');
    setBindingGroupActive('lod', false);
    useTimeCursor.getState().seekIndex(3);
    await paint();
    expect(live.textContent).toBe('73.00');
    expect(chip.textContent).toBe('70.00');
    setBindingGroupActive('lod', true);
    await paint();
    expect(chip.textContent).toBe('73.00');
    unbindChip();
    unbindLive();
  });
});
