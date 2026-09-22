/**
 * Guided intake draft. Text fields persist in localStorage so a reload keeps
 * the job description; files cannot persist and must be attached again.
 */

import { create } from 'zustand';

import type { IntakeInspection } from '../api/client';

export type IntakeStep = 'job' | 'sources' | 'normalize' | 'strategy' | 'create';
export const INTAKE_STEPS: Array<{ id: IntakeStep; label: string }> = [
  { id: 'job', label: 'Job' },
  { id: 'sources', label: 'Sources' },
  { id: 'normalize', label: 'Normalize' },
  { id: 'strategy', label: 'Strategy' },
  { id: 'create', label: 'Create' },
];

export type Operator = 'eq' | 'lt' | 'le' | 'gt' | 'ge' | 'between';

export interface Expectation {
  target: string;
  operator: Operator;
  value: number | boolean;
  upper?: number | null;
  tolerance?: number;
}

export interface AcceptanceCase {
  name: string;
  inputs: Record<string, number | boolean>;
  expectations: Expectation[];
  repeat: number;
  step_seconds: number;
}

export interface IntakeDraft {
  name: string;
  site: string;
  equipmentName: string;
  sequenceFamily: string;
  sequenceVersion: string;
  controllerId: string;
  executionProfile: 'modelica_exact' | 'host_tick_v1';
  parameters: Array<{ key: string; value: string }>;
  deliverableRequirements: string;
  acceptanceTests: AcceptanceCase[];
  notes: string;
}

/** A binding the engineer confirmed in the Normalize step; nothing links without one. */
export interface ConfirmedBinding {
  niagara_ord: string;
  write_priority: number | null;
}

export interface IntakeFiles {
  points: File | null;
  sequence: File | null;
  bacnet: File | null;
  template: File | null;
  environment: File | null;
}

export const emptyDraft: IntakeDraft = {
  name: '',
  site: '',
  equipmentName: '',
  sequenceFamily: 'AUTO',
  sequenceVersion: 'Contractor sequence of operations',
  controllerId: '',
  executionProfile: 'modelica_exact',
  parameters: [],
  deliverableRequirements: '{}',
  acceptanceTests: [],
  notes: '',
};

const emptyFiles: IntakeFiles = { points: null, sequence: null, bacnet: null, template: null, environment: null };

interface IntakeState {
  draft: IntakeDraft;
  files: IntakeFiles;
  inspection: IntakeInspection | null;
  bindings: Record<string, ConfirmedBinding>;
  update: (patch: Partial<IntakeDraft>) => void;
  setFile: (key: keyof IntakeFiles, file: File | null) => void;
  setInspection: (inspection: IntakeInspection | null) => void;
  confirmBinding: (point: string, binding: ConfirmedBinding | null) => void;
  reset: () => void;
}

const KEY = 'bactalk.intake.draft.v1';

function readDraft(): IntakeDraft {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? { ...emptyDraft, ...(JSON.parse(raw) as Partial<IntakeDraft>) } : emptyDraft;
  } catch {
    return emptyDraft;
  }
}

function persist(draft: IntakeDraft): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(draft));
  } catch {
    // Draft persistence is a convenience only.
  }
}

export const useIntake = create<IntakeState>((set, get) => ({
  draft: readDraft(),
  files: emptyFiles,
  inspection: null,
  bindings: {},
  update(patch) {
    const draft = { ...get().draft, ...patch };
    set({ draft });
    persist(draft);
  },
  setFile(key, file) {
    set({
      files: { ...get().files, [key]: file },
      inspection: key === 'points' || key === 'sequence' ? null : get().inspection,
      // Bindings point into a specific station: a new station or points list voids them.
      bindings: key === 'template' || key === 'points' ? {} : get().bindings,
    });
  },
  setInspection(inspection) {
    set({ inspection });
  },
  confirmBinding(point, binding) {
    const next = { ...get().bindings };
    if (binding) next[point] = binding;
    else delete next[point];
    set({ bindings: next });
  },
  reset() {
    set({ draft: emptyDraft, files: emptyFiles, inspection: null, bindings: {} });
    try {
      localStorage.removeItem(KEY);
    } catch {
      // ignore
    }
  },
}));
