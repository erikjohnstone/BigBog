/**
 * Cross-view selection.
 *
 * The wiresheet, trends, schematic, timeline, and the AI thread all read the
 * same selection so that clicking a block highlights its trend, clicking a
 * failed assertion highlights the responsible path, and the assistant is
 * told what the engineer is looking at.
 */

import { create } from 'zustand';

export type SelectMode = 'replace' | 'toggle' | 'add';

export interface SelectionState {
  blockIds: ReadonlySet<string>;
  signalIds: ReadonlySet<string>;
  assertionId: string | null;
  hoverBlockId: string | null;
  /** Upstream path highlighted after "jump to failure". */
  highlightedBlockIds: ReadonlySet<string>;
  highlightedLinkKeys: ReadonlySet<string>;

  selectBlocks: (ids: Iterable<string>, mode?: SelectMode) => void;
  selectSignals: (ids: Iterable<string>, mode?: SelectMode) => void;
  setAssertion: (id: string | null) => void;
  setHover: (id: string | null) => void;
  setHighlight: (blockIds: Iterable<string>, linkKeys: Iterable<string>) => void;
  clear: () => void;
}

function applyMode(current: ReadonlySet<string>, ids: Iterable<string>, mode: SelectMode): Set<string> {
  const incoming = new Set(ids);
  if (mode === 'replace') return incoming;
  const next = new Set(current);
  for (const id of incoming) {
    if (mode === 'toggle' && next.has(id)) next.delete(id);
    else next.add(id);
  }
  return next;
}

const EMPTY: ReadonlySet<string> = new Set();

export const useSelection = create<SelectionState>((set, get) => ({
  blockIds: EMPTY,
  signalIds: EMPTY,
  assertionId: null,
  hoverBlockId: null,
  highlightedBlockIds: EMPTY,
  highlightedLinkKeys: EMPTY,

  selectBlocks(ids, mode = 'replace') {
    set({ blockIds: applyMode(get().blockIds, ids, mode) });
  },
  selectSignals(ids, mode = 'replace') {
    set({ signalIds: applyMode(get().signalIds, ids, mode) });
  },
  setAssertion(id) {
    set({ assertionId: id });
  },
  setHover(id) {
    if (get().hoverBlockId !== id) set({ hoverBlockId: id });
  },
  setHighlight(blockIds, linkKeys) {
    set({ highlightedBlockIds: new Set(blockIds), highlightedLinkKeys: new Set(linkKeys) });
  },
  clear() {
    set({
      blockIds: EMPTY,
      signalIds: EMPTY,
      assertionId: null,
      highlightedBlockIds: EMPTY,
      highlightedLinkKeys: EMPTY,
    });
  },
}));

export function linkKey(source: string, sourceSlot: string, target: string, targetSlot: string): string {
  return `${source}.${sourceSlot}->${target}.${targetSlot}`;
}
