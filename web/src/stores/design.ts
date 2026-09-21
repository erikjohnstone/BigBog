/**
 * Design pipeline state per ctrl-flow template: selections, uploaded files,
 * the retained artifacts from each gate, and the engineer's decisions and
 * authored oracles. In memory only; files cannot persist across reloads.
 */

import { create } from 'zustand';

import type { CtrlFlowBrief, CtrlFlowReconciliation, CtrlFlowSequenceReconciliation, CtrlFlowSequenceReview, SequenceCandidatePreflight, SequenceOracleApproval } from '../api/client';
import type { FacetDraftValues, OracleDraftValues, ReviewDecision } from '../features/intake/design/payloads';

export type DesignStep = 'configure' | 'brief' | 'points' | 'sequence' | 'review' | 'oracles' | 'preflight' | 'candidate';
export const DESIGN_STEPS: Array<{ id: DesignStep; label: string }> = [
  { id: 'configure', label: 'Configure' },
  { id: 'brief', label: 'Brief' },
  { id: 'points', label: 'Points' },
  { id: 'sequence', label: 'Sequence' },
  { id: 'review', label: 'Review' },
  { id: 'oracles', label: 'Oracles' },
  { id: 'preflight', label: 'Preflight' },
  { id: 'candidate', label: 'Candidate' },
];

export interface DesignState {
  selections: Record<string, unknown>;
  pointsFile: File | null;
  sequenceFile: File | null;
  brief: CtrlFlowBrief | null;
  reconciliation: CtrlFlowReconciliation | null;
  sequenceReconciliation: CtrlFlowSequenceReconciliation | null;
  reviewer: string;
  decisions: Record<string, ReviewDecision>;
  review: CtrlFlowSequenceReview | null;
  oracleAuthor: string;
  oracleDrafts: Record<string, OracleDraftValues>;
  facetDrafts: Record<string, FacetDraftValues>;
  approval: SequenceOracleApproval | null;
  parameters: Record<string, string>;
  boundarySelections: Record<string, string>;
  preflight: SequenceCandidatePreflight | null;
  candidate: { name: string; site: string; equipmentName: string };
}

/** Stable empty selections: a selector must never return a fresh object. */
export const EMPTY_SELECTIONS: Record<string, unknown> = Object.freeze({});

export const emptyDesign: DesignState = {
  selections: EMPTY_SELECTIONS,
  pointsFile: null,
  sequenceFile: null,
  brief: null,
  reconciliation: null,
  sequenceReconciliation: null,
  reviewer: '',
  decisions: {},
  review: null,
  oracleAuthor: '',
  oracleDrafts: {},
  facetDrafts: {},
  approval: null,
  parameters: {},
  boundarySelections: {},
  preflight: null,
  candidate: { name: '', site: '', equipmentName: '' },
};

interface DesignStore {
  byTemplate: Record<string, DesignState>;
  get: (templateId: string) => DesignState;
  patch: (templateId: string, patch: Partial<DesignState> | ((current: DesignState) => Partial<DesignState>)) => void;
  reset: (templateId: string) => void;
}

export const useDesign = create<DesignStore>((set, get) => ({
  byTemplate: {},
  get(templateId) {
    return get().byTemplate[templateId] ?? emptyDesign;
  },
  patch(templateId, patch) {
    const current = get().byTemplate[templateId] ?? emptyDesign;
    const next = typeof patch === 'function' ? patch(current) : patch;
    set({ byTemplate: { ...get().byTemplate, [templateId]: { ...current, ...next } } });
  },
  reset(templateId) {
    const byTemplate = { ...get().byTemplate };
    delete byTemplate[templateId];
    set({ byTemplate });
  },
}));

/** Which steps are reachable given what has been retained so far. */
export function reachableSteps(state: DesignState): Set<DesignStep> {
  const steps = new Set<DesignStep>(['configure', 'brief', 'points', 'sequence']);
  if (state.sequenceReconciliation) steps.add('review');
  if (state.review?.ready_for_independent_oracle_authoring) steps.add('oracles');
  if (state.approval?.ready_for_graph_generation) steps.add('preflight');
  if (state.preflight?.ready_for_candidate_generation) steps.add('candidate');
  return steps;
}
