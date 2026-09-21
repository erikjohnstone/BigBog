/**
 * Small, client-only UI state that must survive navigation: which panels are
 * open, the command palette mode, and persisted panel sizes per stage.
 */

import { create } from 'zustand';

export type CommandMode = 'search' | 'agent' | null;
export type Stage = 'intake' | 'build' | 'test' | 'review' | 'release';

const SIZES_KEY = 'bactalk.layout.v1';

function readSizes(): Record<string, number[]> {
  try {
    const raw = localStorage.getItem(SIZES_KEY);
    return raw ? (JSON.parse(raw) as Record<string, number[]>) : {};
  } catch {
    return {};
  }
}

interface UiState {
  commandMode: CommandMode;
  assistantOpen: boolean;
  railExpanded: boolean;
  panelSizes: Record<string, number[]>;

  openCommand: (mode: Exclude<CommandMode, null>) => void;
  closeCommand: () => void;
  setAssistantOpen: (open: boolean) => void;
  toggleAssistant: () => void;
  setRailExpanded: (expanded: boolean) => void;
  savePanelSizes: (key: string, sizes: number[]) => void;
  resetPanelSizes: (key: string) => void;
}

export const useUi = create<UiState>((set, get) => ({
  commandMode: null,
  assistantOpen: false,
  railExpanded: false,
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
  setRailExpanded(expanded) {
    set({ railExpanded: expanded });
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
