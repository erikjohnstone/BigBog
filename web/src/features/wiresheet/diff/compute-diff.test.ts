import { describe, expect, it } from 'vitest';

import type { ControlGraph } from '../../../api/client';
import { computeDiff, unexplainedChanges } from './compute-diff';

const parent: ControlGraph = {
  name: 'G',
  blocks: [
    { id: 'A', kind: 'numeric_input', label: 'A', x: 0, y: 0, config: { default: 1 } },
    { id: 'B', kind: 'add', label: 'B', x: 0, y: 0, config: {} },
    { id: 'C', kind: 'numeric_output', label: 'C', x: 0, y: 0, config: {} },
  ],
  links: [
    { source: 'A', source_slot: 'out', target: 'B', target_slot: 'a' },
    { source: 'B', source_slot: 'out', target: 'C', target_slot: 'in' },
  ],
};

const child: ControlGraph = {
  name: 'G',
  blocks: [
    { id: 'A', kind: 'numeric_input', label: 'A', x: 0, y: 0, config: { default: 2 } },
    { id: 'B', kind: 'add', label: 'B', x: 0, y: 0, config: {} },
    { id: 'D', kind: 'numeric_const', label: 'D', x: 0, y: 0, config: { value: 5 } },
    { id: 'C', kind: 'numeric_output', label: 'C renamed', x: 0, y: 0, config: {} },
  ],
  links: [
    { source: 'A', source_slot: 'out', target: 'B', target_slot: 'a' },
    { source: 'D', source_slot: 'out', target: 'B', target_slot: 'b' },
    { source: 'B', source_slot: 'out', target: 'C', target_slot: 'in' },
  ],
};

describe('computeDiff', () => {
  it('finds added, removed, and modified blocks and links', () => {
    const diff = computeDiff(parent, child);
    expect([...diff.addedBlocks]).toEqual(['D']);
    expect([...diff.removedBlocks]).toEqual([]);
    expect(diff.modifiedBlocks.get('A')?.fields).toEqual([{ field: 'config.default', before: 1, after: 2 }]);
    expect(diff.modifiedBlocks.get('C')?.fields).toEqual([{ field: 'label', before: 'C', after: 'C renamed' }]);
    expect([...diff.addedLinks]).toEqual(['D.out->B.b']);
    expect(diff.removedLinks.size).toBe(0);
    expect(diff.empty).toBe(false);
  });

  it('is empty for identical graphs regardless of key order', () => {
    const reordered: ControlGraph = { ...parent, blocks: parent.blocks.map((block) => ({ ...block, config: { ...block.config } })) };
    expect(computeDiff(parent, reordered).empty).toBe(true);
  });

  it('reports removed blocks and their links', () => {
    const diff = computeDiff(child, parent);
    expect([...diff.removedBlocks]).toEqual(['D']);
    expect([...diff.removedLinks]).toEqual(['D.out->B.b']);
  });

  it('flags server-listed changes the structural diff did not find', () => {
    const diff = computeDiff(parent, child);
    expect(unexplainedChanges(diff, { added: ['block:D', 'block:Z'], modified: ['block:A'], removed: ['link:Q.out->B.b'] })).toEqual([
      'block:Z',
      'link:Q.out->B.b',
    ]);
  });
});
