/**
 * Structural diff of two control graphs, used to render an AI proposal as a
 * ghost overlay on the parent wiresheet. The server's `changes` list is the
 * record; this diff is what the canvas draws and it never applies anything.
 */

import type { ControlGraph } from '../../../api/client';
import { linkKey } from '../../../stores/selection';

export type DiffStatus = 'added' | 'removed' | 'modified';

export interface BlockChange {
  id: string;
  fields: Array<{ field: string; before: unknown; after: unknown }>;
}

export interface GraphDiff {
  addedBlocks: Set<string>;
  removedBlocks: Set<string>;
  modifiedBlocks: Map<string, BlockChange>;
  addedLinks: Set<string>;
  removedLinks: Set<string>;
  /** True when nothing differs. */
  empty: boolean;
}

function stable(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`;
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${stable(record[key])}`)
    .join(',')}}`;
}

export function computeDiff(parent: ControlGraph, child: ControlGraph): GraphDiff {
  const before = new Map(parent.blocks.map((block) => [block.id, block]));
  const after = new Map(child.blocks.map((block) => [block.id, block]));
  const addedBlocks = new Set<string>();
  const removedBlocks = new Set<string>();
  const modifiedBlocks = new Map<string, BlockChange>();

  for (const [id, block] of after) {
    const previous = before.get(id);
    if (!previous) {
      addedBlocks.add(id);
      continue;
    }
    const fields: BlockChange['fields'] = [];
    if (previous.kind !== block.kind) fields.push({ field: 'kind', before: previous.kind, after: block.kind });
    if (previous.label !== block.label) fields.push({ field: 'label', before: previous.label, after: block.label });
    const keys = new Set([...Object.keys(previous.config ?? {}), ...Object.keys(block.config ?? {})]);
    for (const key of keys) {
      const a = previous.config?.[key];
      const b = block.config?.[key];
      if (stable(a) !== stable(b)) fields.push({ field: `config.${key}`, before: a, after: b });
    }
    if (fields.length > 0) modifiedBlocks.set(id, { id, fields });
  }
  for (const id of before.keys()) if (!after.has(id)) removedBlocks.add(id);

  const linkSet = (graph: ControlGraph) =>
    new Set(graph.links.map((link) => linkKey(link.source, link.source_slot, link.target, link.target_slot)));
  const beforeLinks = linkSet(parent);
  const afterLinks = linkSet(child);
  const addedLinks = new Set([...afterLinks].filter((key) => !beforeLinks.has(key)));
  const removedLinks = new Set([...beforeLinks].filter((key) => !afterLinks.has(key)));

  return {
    addedBlocks,
    removedBlocks,
    modifiedBlocks,
    addedLinks,
    removedLinks,
    empty:
      addedBlocks.size === 0 &&
      removedBlocks.size === 0 &&
      modifiedBlocks.size === 0 &&
      addedLinks.size === 0 &&
      removedLinks.size === 0,
  };
}

/**
 * Cross-check the structural diff against the server's `changes` record
 * (`block:<id>` and `link:<s>.<slot>-><t>.<slot>` entries). Returns entries
 * the server lists that the diff did not find, so the UI can say so instead
 * of silently trusting either side.
 */
export function unexplainedChanges(
  diff: GraphDiff,
  changes: { added: string[]; modified: string[]; removed: string[] },
): string[] {
  const missing: string[] = [];
  const check = (entries: string[], blocks: Set<string> | Map<string, unknown>, links: Set<string> | null) => {
    for (const entry of entries) {
      if (entry.startsWith('block:')) {
        if (!blocks.has(entry.slice(6))) missing.push(entry);
      } else if (entry.startsWith('link:')) {
        if (links && !links.has(entry.slice(5))) missing.push(entry);
      }
    }
  };
  check(changes.added, diff.addedBlocks, diff.addedLinks);
  check(changes.removed, diff.removedBlocks, diff.removedLinks);
  check(changes.modified, diff.modifiedBlocks, null);
  return missing;
}
