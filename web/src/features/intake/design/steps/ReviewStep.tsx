import { useMutation } from '@tanstack/react-query';
import { ShieldCheck } from 'lucide-react';
import { useMemo } from 'react';

import { api } from '../../../../api/client';
import { cn } from '../../../../design-system/cn';
import { Button, Field, Input, NativeSelect, StatusPill, Textarea } from '../../../../design-system/primitives';
import { useDesign } from '../../../../stores/design';
import { buildReviewRequest, compatiblePoints, decisionComplete, initialFacetDrafts, initialOracleDrafts, reviewComplete, reviewItems } from '../payloads';
import type { ReviewDecision } from '../payloads';

export function ReviewStep({ templateId }: { templateId: string }) {
  const state = useDesign((store) => store.byTemplate[templateId]);
  const patch = useDesign((store) => store.patch);
  const candidates = state?.sequenceReconciliation?.requirement_candidates;
  const items = useMemo(() => reviewItems(candidates), [candidates]);
  const decisions = state?.decisions ?? {};
  const reviewer = state?.reviewer ?? '';
  const review = state?.review ?? null;
  const complete = reviewComplete(items, decisions, reviewer);

  const submit = useMutation({
    mutationFn: () => {
      if (!state?.sequenceFile || !candidates) throw new Error('Inspect a sequence before review.');
      if (!state.reconciliation?.ready_for_sequence_reconciliation) throw new Error('Retain a passing contractor point reconciliation before review.');
      return api.approveCtrlFlowSequenceRequirements(templateId, state.selections, state.sequenceFile, state.reconciliation.point_reconciliation_id, buildReviewRequest(candidates, items, decisions, reviewer));
    },
    onSuccess: (result) => patch(templateId, { review: result, oracleAuthor: '', oracleDrafts: initialOracleDrafts(result), facetDrafts: initialFacetDrafts(result), approval: null, preflight: null }),
  });

  const update = (id: string, patchDecision: Partial<ReviewDecision>) =>
    patch(templateId, (current) => ({ decisions: { ...current.decisions, [id]: { ...current.decisions[id], ...patchDecision } } }));

  if (!candidates) return null;

  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-start gap-3 flex-wrap">
        <div className="flex-1 min-w-64">
          <p className="eyebrow">Gate 5</p>
          <h2 className="text-xl font-semibold tracking-tight">Engineer requirement review</h2>
          <p className="text-sm text-fg-1 mt-1">Every candidate needs an explicit decision. Nothing is pre-approved; rejections need a reason and unresolved language needs replacement text.</p>
        </div>
        <Field label="Requirement reviewer" htmlFor="design-reviewer" className="w-64">
          <Input id="design-reviewer" value={reviewer} onChange={(event) => patch(templateId, { reviewer: event.target.value })} placeholder="Named engineer" aria-label="Requirement reviewer" />
        </Field>
      </div>

      <ul className="flex flex-col gap-2" aria-label="Requirement candidates">
        {items.map((item) => {
          const decision = decisions[item.id];
          const done = decisionComplete(item, decision);
          const points = compatiblePoints(item, candidates.available_review_points);
          return (
            <li key={item.id} className={cn('panel p-3 grid grid-cols-1 md:grid-cols-[1fr_220px_1fr] gap-3 items-start', done && 'border-ok/40')}>
              <div className="min-w-0">
                <span className="eyebrow">{item.group}</span>
                <span className="block text-sm font-medium">{item.label}</span>
                <span className="block text-2xs text-fg-2 truncate" title={item.clause}>
                  “{item.clause}”
                </span>
              </div>
              <NativeSelect
                value={decision?.disposition ?? ''}
                onChange={(event) => update(item.id, { disposition: (event.target.value || undefined) as ReviewDecision['disposition'], selected_point: undefined, replacement_text: undefined, note: undefined })}
                aria-label={`Decision for ${item.label}`}
              >
                <option value="">Choose…</option>
                {item.unresolved ? (
                  <option value="resolve">Resolve in revised source</option>
                ) : (
                  <>
                    <option value="approve">Approve candidate</option>
                    <option value="reject">Reject candidate</option>
                  </>
                )}
              </NativeSelect>
              <div className="min-w-0">
                {decision?.disposition === 'approve' && item.needsPoint && item.pointCandidates.length !== 1 && (
                  <NativeSelect value={decision.selected_point ?? ''} onChange={(event) => update(item.id, { selected_point: event.target.value || undefined })} aria-label={`Point for ${item.label}`}>
                    <option value="">Select point…</option>
                    {points.map((point) => (
                      <option key={point.id} value={point.id}>
                        {point.id} · {point.role}
                      </option>
                    ))}
                  </NativeSelect>
                )}
                {decision?.disposition === 'reject' && <Input value={decision.note ?? ''} onChange={(event) => update(item.id, { note: event.target.value })} placeholder="Engineering reason required" aria-label={`Rejection note for ${item.label}`} />}
                {decision?.disposition === 'resolve' && (
                  <Textarea rows={2} value={decision.replacement_text ?? ''} onChange={(event) => update(item.id, { replacement_text: event.target.value })} placeholder="Exact replacement language for the revised source" aria-label={`Resolution for ${item.label}`} />
                )}
              </div>
            </li>
          );
        })}
      </ul>

      <div className="flex items-center gap-3 flex-wrap">
        <Button variant="primary" disabled={!complete || submit.isPending} onClick={() => submit.mutate()}>
          {submit.isPending ? 'Re-deriving and validating…' : `Submit ${items.length} decisions`}
        </Button>
        <StatusPill tone="offline" icon={<ShieldCheck size={12} />}>
          retained with a digest
        </StatusPill>
      </div>
      {submit.isError && <div role="alert" className="rounded-panel border border-fail/40 bg-fail-soft p-3 text-sm text-fail">{submit.error instanceof Error ? submit.error.message : 'The review was rejected.'}</div>}
      {review && (
        <div className={cn('rounded-panel border p-3 text-sm', review.ready_for_independent_oracle_authoring ? 'border-ok/40' : 'border-warn/40')}>
          <strong>
            {review.ready_for_independent_oracle_authoring
              ? `${review.oracle_draft_count + review.authorable_manual_facet_count} local test trajectories ready for independent authoring`
              : 'Requirement review remains blocked'}
          </strong>
          <p className="text-xs text-fg-2 mt-1">
            Retained review <span className="num">{review.review_id.slice(0, 12)}</span> · artifact <span className="num">{review.retention.artifact_digest.slice(0, 12)}</span> · {review.scenario_oracle_gap_count} required scenario facets still lack executable oracles · graph generation remains disabled
          </p>
          {review.blockers.length > 0 && (
            <ul className="mt-1 text-xs text-warn list-disc pl-4">
              {review.blockers.map((blocker) => (
                <li key={blocker}>{blocker}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
