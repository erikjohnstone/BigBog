import { describe, expect, it } from 'vitest';

import { needsLayout, tidy } from './tidy';

const graph = {
  blocks: [
    { id: 'In', kind: 'numeric_input', label: 'In', x: 0, y: 0, config: {} },
    { id: 'K', kind: 'numeric_const', label: 'K', x: 0, y: 0, config: {} },
    { id: 'Sum', kind: 'add', label: 'Sum', x: 0, y: 0, config: {} },
    { id: 'Out', kind: 'numeric_output', label: 'Out', x: 0, y: 0, config: {} },
    { id: 'Prev', kind: 'numeric_unit_delay', label: 'Prev', x: 0, y: 0, config: {} },
  ],
  links: [
    { source: 'In', source_slot: 'out', target: 'Sum', target_slot: 'a' },
    { source: 'K', source_slot: 'out', target: 'Sum', target_slot: 'b' },
    { source: 'Sum', source_slot: 'out', target: 'Out', target_slot: 'in' },
    { source: 'Sum', source_slot: 'out', target: 'Prev', target_slot: 'in' },
    { source: 'Prev', source_slot: 'out', target: 'Sum', target_slot: 'a' },
  ],
};

describe('tidy', () => {
  it('is deterministic and ranks left to right', () => {
    const a = tidy(graph, new Map(), new Set(['numeric_unit_delay']));
    const b = tidy(graph, new Map(), new Set(['numeric_unit_delay']));
    expect([...a.entries()]).toEqual([...b.entries()]);
    expect(a.get('In')!.x).toBeLessThan(a.get('Sum')!.x);
    expect(a.get('Sum')!.x).toBeLessThan(a.get('Out')!.x);
  });

  it('never overlaps nodes', () => {
    const positions = tidy(graph, new Map(), new Set(['numeric_unit_delay']));
    const boxes = [...positions.values()].map((p) => ({ x1: p.x, y1: p.y, x2: p.x + 190, y2: p.y + 88 }));
    for (let i = 0; i < boxes.length; i += 1) {
      for (let j = i + 1; j < boxes.length; j += 1) {
        const a = boxes[i];
        const b = boxes[j];
        const overlap = a.x1 < b.x2 && b.x1 < a.x2 && a.y1 < b.y2 && b.y1 < a.y2;
        expect(overlap).toBe(false);
      }
    }
  });

  it('detects graphs without positions', () => {
    expect(needsLayout(graph)).toBe(true);
    expect(needsLayout({ blocks: graph.blocks.map((block, i) => ({ ...block, x: 40 + i * 200, y: 50 })) })).toBe(false);
    expect(needsLayout({ blocks: [] })).toBe(false);
  });
});
