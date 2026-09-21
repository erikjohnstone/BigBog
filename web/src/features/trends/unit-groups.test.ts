import { describe, expect, it } from 'vitest';

import type { Signal, Trace } from '../../stores/trace';
import { composeDefaultTrends } from './unit-groups';

function signal(partial: Partial<Signal> & { id: string; kind: Signal['kind']; source: Signal['source'] }): Signal {
  return { label: partial.id, values: partial.kind === 'boolean' ? new Uint8Array(2) : new Float64Array(2), min: 0, max: 1, ...partial };
}

const trace: Trace = {
  id: 't',
  label: 't',
  engine: 'generic',
  time: Float64Array.from([0, 1]),
  phases: [],
  signals: new Map(
    [
      signal({ id: 'ZoneTemp', kind: 'numeric', source: 'input', unit: 'degF' }),
      signal({ id: 'Setpoint', kind: 'numeric', source: 'input', unit: 'degF' }),
      signal({ id: 'Damper', kind: 'numeric', source: 'block', unit: '%' }),
      signal({ id: 'Gain', kind: 'numeric', source: 'block' }),
      signal({ id: 'Gain.out', kind: 'numeric', source: 'slot', blockId: 'Gain', slot: 'out' }),
      signal({ id: 'Occupied', kind: 'boolean', source: 'input' }),
      signal({ id: 'Fan', kind: 'boolean', source: 'block' }),
      signal({ id: 'fault.f1.active', kind: 'boolean', source: 'fault', group: 'f1' }),
      signal({ id: 'fault.f1.applied', kind: 'boolean', source: 'fault', group: 'f1' }),
    ].map((item) => [item.id, item]),
  ),
  assertions: [{ id: 'a', name: 'a', passed: true, observed: '', expected: '', index: 1, phaseIndex: 0, blockIds: ['Damper'], signalId: 'Damper' }],
  faultWindows: [],
  oracles: [],
  axisReconstructed: false,
  passed: true,
};

describe('composeDefaultTrends', () => {
  const trends = composeDefaultTrends(trace);

  it('makes one pane per unit with first-look signals switched on', () => {
    expect(trends.panes.map((pane) => pane.title)).toEqual(['%', 'degF', 'Values']);
    expect(trends.panes[0].signalIds).toEqual(['Damper']);
    expect(trends.panes[1].signalIds).toEqual(['Setpoint', 'ZoneTemp']);
    // Internal block values are available but only a few are on by default.
    expect(trends.panes[2].signalIds).toEqual(['Gain']);
  });

  it('puts points, targets, and fault activity on the ribbon but not fault internals', () => {
    expect(trends.ribbon).toEqual(['Occupied', 'fault.f1.active']);
  });
});
