/**
 * Small, client-only UI state that must survive navigation: which panels are
 * open, the command palette mode, and persisted panel sizes per stage.
 */

import { create } from 'zustand';

export type CommandMode = 'search' | 'agent' | null;
export type Stage = 'intake' | 'build' | 'test' | 'review' | 'release';

const SIZES_KEY = 'bactalk.layout.v1';

export type PanelLayout = Record<string, number>;

function readSizes(): Record<string, PanelLayout> {
  try {
    const raw = localStorage.getItem(SIZES_KEY);
    return raw ? (JSON.parse(raw) as Record<string, PanelLayout>) : {};
  } catch {
    return {};
  }
}

interface UiState {
  commandMode: CommandMode;
  assistantOpen: boolean;
  /** A question typed in the agent palette, consumed by the thread once. */
  assistantDraft: string | null;
  railExpanded: boolean;
  /** Schematic panel on the Test stage. */
  schematicOpen: boolean;
  panelSizes: Record<string, PanelLayout>;

  openCommand: (mode: Exclude<CommandMode, null>) => void;
  closeCommand: () => void;
  setAssistantOpen: (open: boolean) => void;
  toggleAssistant: () => void;
  setAssistantDraft: (draft: string | null) => void;
  setRailExpanded: (expanded: boolean) => void;
  setSchematicOpen: (open: boolean) => void;
  savePanelSizes: (key: string, sizes: PanelLayout) => void;
  resetPanelSizes: (key: string) => void;
}

export const useUi = create<UiState>((set, get) => ({
  commandMode: null,
  assistantOpen: false,
  assistantDraft: null,
  railExpanded: false,
  schematicOpen: (() => {
    try {
      return localStorage.getItem('bactalk.schematic.open') !== 'false';
    } catch {
      return true;
    }
  })(),
  panelSizes: readSizes(),

  openCommand(mode) {
    set({ commandMode: mode });
  },
  closeCommand() {
    set({ commandMode: null });
  },
  setAssistantOpen(open) {
    set({ assistantOpen: open });
  },
  toggleAssistant() {
    set({ assistantOpen: !get().assistantOpen });
  },
  setAssistantDraft(draft) {
    set({ assistantDraft: draft });
  },
  setRailExpanded(expanded) {
    set({ railExpanded: expanded });
  },
  setSchematicOpen(open) {
    set({ schematicOpen: open });
    try {
      localStorage.setItem('bactalk.schematic.open', String(open));
    } catch {
      // preference only
    }
  },
  savePanelSizes(key, sizes) {
    const next = { ...get().panelSizes, [key]: sizes };
    set({ panelSizes: next });
    try {
      localStorage.setItem(SIZES_KEY, JSON.stringify(next));
    } catch {
      // ignore
    }
  },
  resetPanelSizes(key) {
    const next = { ...get().panelSizes };
    delete next[key];
    set({ panelSizes: next });
    try {
      localStorage.setItem(SIZES_KEY, JSON.stringify(next));
    } catch {
      // ignore
    }
  },
}));
