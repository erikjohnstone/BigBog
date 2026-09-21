import { describe, expect, it } from 'vitest';

import { delayFor, materializeOrder } from './materialize';

describe('materializeOrder', () => {
  it('ranks inputs before their consumers and tolerates loops', () => {
    const order = materializeOrder(
      {
        blocks: [
          { id: 'A', kind: 'numeric_input', label: '', x: 0, y: 0, config: {} },
          { id: 'B', kind: 'add', label: '', x: 0, y: 0, config: {} },
          { id: 'C', kind: 'numeric_output', label: '', x: 0, y: 0, config: {} },
          { id: 'P', kind: 'numeric_unit_delay', label: '', x: 0, y: 0, config: {} },
        ],
        links: [
          { source: 'A', source_slot: 'out', target: 'B', target_slot: 'a' },
          { source: 'B', source_slot: 'out', target: 'C', target_slot: 'in' },
          { source: 'B', source_slot: 'out', target: 'P', target_slot: 'in' },
          { source: 'P', source_slot: 'out', target: 'B', target_slot: 'b' },
        ],
      },
      new Set(['numeric_unit_delay']),
    );
    expect(order.get('A')).toBe(0);
    expect(order.get('B')).toBe(1);
    expect(order.get('C')).toBe(2);
    expect(order.get('P')).toBe(2);
  });

  it('caps the delay', () => {
    expect(delayFor(0)).toBe(0);
    expect(delayFor(3)).toBe(60);
    expect(delayFor(500)).toBe(1100);
  });
});
