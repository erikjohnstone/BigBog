/**
 * Pure builders between the design pipeline's state and the API contracts:
 * requirement review items and decisions, independent oracle authoring,
 * and the candidate request. Nothing here is pre-approved; every value
 * comes from an engineer.
 */

import type { CtrlFlowSequenceReconciliation, CtrlFlowSequenceReview, G36Parameters, SequenceOracleApproval } from '../../../api/client';

export type Disposition = 'approve' | 'reject' | 'resolve';

export interface ReviewDecision {
  disposition?: Disposition;
  selected_point?: string;
  replacement_text?: string;
  note?: string;
}

export interface ReviewItem {
  id: string;
  group: 'quantity' | 'action' | 'policy' | 'unresolved';
  label: string;
  clause: string;
  pointCandidates: string[];
  needsPoint: boolean;
  unresolved: boolean;
}

type Candidates = CtrlFlowSequenceReconciliation['requirement_candidates'];

export function reviewItems(candidates: Candidates | undefined): ReviewItem[] {
  if (!candidates) return [];
  return [
    ...candidates.quantities.map((item) => ({
      id: item.id,
      group: 'quantity' as const,
      label: `${item.kind.replaceAll('-', ' ')} · ${item.canonical.value} ${item.canonical.unit}`,
      clause: item.source.clause,
      pointCandidates: item.input_point_candidates,
      needsPoint: ['threshold', 'parameter'].includes(item.kind),
      unresolved: false,
    })),
    ...candidates.actions.map((item) => ({
      id: item.id,
      group: 'action' as const,
      label: `${item.verb} ${item.subject}`,
      clause: item.source.clause,
      pointCandidates: item.point_candidates,
      needsPoint: true,
      unresolved: false,
    })),
    ...candidates.policies.map((item) => ({
      id: item.id,
      group: 'policy' as const,
      label: item.policy.replaceAll('-', ' '),
      clause: item.source.clause,
      pointCandidates: [] as string[],
      needsPoint: false,
      unresolved: false,
    })),
    ...candidates.unresolved.map((item) => ({
      id: item.id,
      group: 'unresolved' as const,
      label: `${item.kind.replaceAll('-', ' ')} · “${item.text}”`,
      clause: item.source.clause,
      pointCandidates: [] as string[],
      needsPoint: false,
      unresolved: true,
    })),
  ];
}

/** Points a review item may bind to, by role when the candidate lists none. */
export function compatiblePoints(item: ReviewItem, available: Candidates['available_review_points']): Candidates['available_review_points'] {
  if (item.pointCandidates.length > 0) return available.filter((point) => item.pointCandidates.includes(point.id));
  return available.filter((point) => (item.group === 'action' ? ['command', 'alarm'] : ['sensor', 'status', 'setpoint']).includes(point.role));
}

export function decisionComplete(item: ReviewItem, decision: ReviewDecision | undefined): boolean {
  if (!decision?.disposition) return false;
  if (item.unresolved) return decision.disposition === 'resolve' && Boolean(decision.replacement_text?.trim());
  if (decision.disposition === 'reject') return (decision.note?.trim().length ?? 0) >= 2;
  if (decision.disposition === 'approve') return !item.needsPoint || item.pointCandidates.length === 1 || Boolean(decision.selected_point);
  return false;
}

export function reviewComplete(items: ReviewItem[], decisions: Record<string, ReviewDecision>, reviewer: string): boolean {
  return items.length > 0 && reviewer.trim().length >= 2 && items.every((item) => decisionComplete(item, decisions[item.id]));
}

export function buildReviewRequest(candidates: Candidates, items: ReviewItem[], decisions: Record<string, ReviewDecision>, reviewer: string) {
  return {
    candidate_digest: candidates.candidate_digest,
    reviewer: reviewer.trim(),
    decisions: items.map((item) => {
      const decision = decisions[item.id] ?? {};
      const out: Record<string, unknown> = { candidate_id: item.id, disposition: decision.disposition };
      if (decision.selected_point) out.selected_point = decision.selected_point;
      if (decision.replacement_text?.trim()) out.replacement_text = decision.replacement_text.trim();
      if (decision.note?.trim()) out.note = decision.note.trim();
      return out;
    }),
  };
}

// ---- oracles ---------------------------------------------------------------

export interface OracleDraftValues {
  stepSeconds: string;
  baselineInputs: Record<string, string>;
  triggerInputs: Record<string, string>;
  recoveryInputs: Record<string, string>;
  baselineOutputs: Record<string, string>;
  preTriggerOutputs: Record<string, string>;
  recoveryOutputs: Record<string, string>;
}

export interface FacetDraftValues {
  inputPoint: string;
  outputPoint: string;
  stepSeconds: string;
  baselineInput: string;
  triggerInput: string;
  recoveryInput: string;
  baselineOutput: string;
  triggerOutput: string;
  recoveryOutput: string;
}

export function initialOracleDrafts(review: CtrlFlowSequenceReview): Record<string, OracleDraftValues> {
  return Object.fromEntries(
    review.oracle_drafts.map((draft) => [
      draft.id,
      {
        stepSeconds: '',
        baselineInputs: Object.fromEntries(draft.conditions.map((condition) => [condition.point, ''])),
        triggerInputs: Object.fromEntries(draft.conditions.map((condition) => [condition.point, ''])),
        recoveryInputs: Object.fromEntries(draft.conditions.map((condition) => [condition.point, ''])),
        baselineOutputs: Object.fromEntries(draft.expectations.map((expectation) => [expectation.point, ''])),
        preTriggerOutputs: Object.fromEntries(draft.expectations.map((expectation) => [expectation.point, ''])),
        recoveryOutputs: Object.fromEntries(draft.expectations.map((expectation) => [expectation.point, ''])),
      },
    ]),
  );
}

export function authorableFacets(review: CtrlFlowSequenceReview) {
  return review.manual_facet_oracle_requirements.filter((requirement) => requirement.authoring_allowed);
}

export function facetKey(requirement: { scenario_id: string; facet_id: string }): string {
  return `${requirement.scenario_id}/${requirement.facet_id}`;
}

export function initialFacetDrafts(review: CtrlFlowSequenceReview): Record<string, FacetDraftValues> {
  return Object.fromEntries(
    authorableFacets(review).map((requirement) => [
      facetKey(requirement),
      { inputPoint: '', outputPoint: '', stepSeconds: '', baselineInput: '', triggerInput: '', recoveryInput: '', baselineOutput: '', triggerOutput: '', recoveryOutput: '' },
    ]),
  );
}

const filled = (value: string | undefined) => value !== undefined && value.trim() !== '';

export function oracleDraftComplete(review: CtrlFlowSequenceReview, drafts: Record<string, OracleDraftValues>): boolean {
  return review.oracle_drafts.every((draft) => {
    const authored = drafts[draft.id];
    if (!authored) return false;
    const duration = Math.max(0, ...draft.durations.map((item) => item.seconds));
    const maps = [authored.baselineInputs, authored.triggerInputs, authored.recoveryInputs, authored.baselineOutputs, authored.recoveryOutputs, ...(duration > 0 ? [authored.preTriggerOutputs] : [])];
    return filled(authored.stepSeconds) && Number(authored.stepSeconds) > 0 && maps.every((map) => Object.values(map).every(filled));
  });
}

export function facetDraftsComplete(review: CtrlFlowSequenceReview, drafts: Record<string, FacetDraftValues>): boolean {
  return authorableFacets(review).every((requirement) => {
    const authored = drafts[facetKey(requirement)];
    return Boolean(
      authored &&
        authored.inputPoint &&
        authored.outputPoint &&
        filled(authored.stepSeconds) &&
        Number(authored.stepSeconds) > 0 &&
        [authored.baselineInput, authored.triggerInput, authored.recoveryInput, authored.baselineOutput, authored.triggerOutput, authored.recoveryOutput].every(filled),
    );
  });
}

export function oraclesComplete(review: CtrlFlowSequenceReview, drafts: Record<string, OracleDraftValues>, facetDrafts: Record<string, FacetDraftValues>, author: string, reviewer: string): boolean {
  return author.trim().length >= 2 && author.trim() !== reviewer.trim() && oracleDraftComplete(review, drafts) && facetDraftsComplete(review, facetDrafts);
}

export function buildOracleApproval(review: CtrlFlowSequenceReview, drafts: Record<string, OracleDraftValues>, facetDrafts: Record<string, FacetDraftValues>, author: string) {
  const cases = review.oracle_drafts.map((draft) => {
    const authored = drafts[draft.id];
    const parseOutput = (point: string, value: string) => {
      const reference = draft.expectations.find((item) => item.point === point)?.value;
      return typeof reference === 'boolean' ? value === 'true' : Number(value);
    };
    const outputExpectations = (values: Record<string, string>) =>
      draft.expectations.map((expectation) => ({ target: expectation.point, operator: 'eq', value: parseOutput(expectation.point, values[expectation.point]) }));
    const numeric = (map: Record<string, string>) => Object.fromEntries(Object.entries(map).map(([point, value]) => [point, Number(value)]));
    return {
      oracle_id: draft.id,
      name: `Independent trajectory for ${draft.id}`,
      baseline_inputs: numeric(authored.baselineInputs),
      trigger_inputs: numeric(authored.triggerInputs),
      recovery_inputs: numeric(authored.recoveryInputs),
      step_seconds: Number(authored.stepSeconds),
      baseline_expectations: outputExpectations(authored.baselineOutputs),
      pre_trigger_expectations: draft.durations.length > 0 ? outputExpectations(authored.preTriggerOutputs) : [],
      post_trigger_expectations: draft.expectations.map((expectation) => ({ target: expectation.point, operator: 'eq', value: expectation.value })),
      recovery_expectations: outputExpectations(authored.recoveryOutputs),
    };
  });
  const pointById = Object.fromEntries(review.point_contract.points.map((point) => [point.id, point]));
  const valueFor = (pointId: string, value: string) => (pointById[pointId]?.data_type === 'boolean' ? value === 'true' : Number(value));
  const facet_cases = authorableFacets(review).map((requirement) => {
    const authored = facetDrafts[facetKey(requirement)];
    return {
      scenario_id: requirement.scenario_id,
      facet_id: requirement.facet_id,
      name: `${requirement.scenario_title} · ${requirement.facet_label}`,
      baseline_inputs: { [authored.inputPoint]: valueFor(authored.inputPoint, authored.baselineInput) },
      trigger_inputs: { [authored.inputPoint]: valueFor(authored.inputPoint, authored.triggerInput) },
      recovery_inputs: { [authored.inputPoint]: valueFor(authored.inputPoint, authored.recoveryInput) },
      step_seconds: Number(authored.stepSeconds),
      baseline_expectations: [{ target: authored.outputPoint, operator: 'eq', value: valueFor(authored.outputPoint, authored.baselineOutput) }],
      trigger_expectations: [{ target: authored.outputPoint, operator: 'eq', value: valueFor(authored.outputPoint, authored.triggerOutput) }],
      recovery_expectations: [{ target: authored.outputPoint, operator: 'eq', value: valueFor(authored.outputPoint, authored.recoveryOutput) }],
    };
  });
  return { review_artifact_digest: review.retention.artifact_digest, author: author.trim(), cases, facet_cases };
}

// ---- candidate -------------------------------------------------------------

export type RequiredParameter = G36Parameters['parameterization']['parameters'][number];

export function parseParameter(parameter: RequiredParameter, raw: string): unknown {
  const text = raw.trim();
  if (!text) throw new Error(`Supply required controller parameter ${parameter.name}.`);
  if (parameter.is_array) return JSON.parse(text);
  if (parameter.data_type === 'Real' || parameter.data_type === 'Integer') {
    const value = Number(text);
    if (!Number.isFinite(value) || (parameter.data_type === 'Integer' && !Number.isInteger(value))) throw new Error(`${parameter.name} must be a valid ${parameter.data_type.toLowerCase()}.`);
    return value;
  }
  if (parameter.data_type === 'Boolean') {
    if (!['true', 'false'].includes(text.toLowerCase())) throw new Error(`${parameter.name} must be true or false.`);
    return text.toLowerCase() === 'true';
  }
  return text;
}

export function buildCandidateRequest(
  approval: SequenceOracleApproval,
  required: RequiredParameter[],
  parameters: Record<string, string>,
  boundarySelections: Record<string, string>,
  metadata?: { name: string; site: string; equipment_name: string },
) {
  if (!approval.ready_for_graph_generation) throw new Error('The independent oracle gate must pass first.');
  const controller_parameters = Object.fromEntries(required.map((parameter) => [parameter.name, parseParameter(parameter, parameters[parameter.name] ?? '')]));
  const chosen = Object.values(boundarySelections).filter(Boolean);
  if (new Set(chosen).size !== chosen.length) throw new Error('Each contractor design point can bind to only one graph boundary.');
  const point_bindings = Object.fromEntries(
    Object.entries(boundarySelections)
      .filter(([, designPoint]) => Boolean(designPoint))
      .map(([boundary, designPoint]) => [designPoint, boundary]),
  );
  return {
    oracle_artifact_digest: approval.retention.artifact_digest,
    controller_parameters,
    point_bindings,
    execution_profile: 'modelica_exact',
    ...(metadata ?? {}),
  };
}
