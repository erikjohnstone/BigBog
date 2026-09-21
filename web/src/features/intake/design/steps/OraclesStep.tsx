import { useMutation } from '@tanstack/react-query';

import { api } from '../../../../api/client';
import { cn } from '../../../../design-system/cn';
import { Button, Field, Input, NativeSelect, StatusPill } from '../../../../design-system/primitives';
import { useDesign } from '../../../../stores/design';
import { authorableFacets, buildOracleApproval, facetKey, oraclesComplete } from '../payloads';
import type { FacetDraftValues, OracleDraftValues } from '../payloads';

function ValueInput({ boolean, value, onChange, label }: { boolean: boolean; value: string; onChange: (value: string) => void; label: string }) {
  if (boolean) {
    return (
      <NativeSelect size="sm" value={value} onChange={(event) => onChange(event.target.value)} aria-label={label}>
        <option value="">—</option>
        <option value="true">true</option>
        <option value="false">false</option>
      </NativeSelect>
    );
  }
  return <Input type="number" step="any" value={value} onChange={(event) => onChange(event.target.value)} aria-label={label} mono className="h-7 text-xs" />;
}

export function OraclesStep({ templateId }: { templateId: string }) {
  const state = useDesign((store) => store.byTemplate[templateId]);
  const patch = useDesign((store) => store.patch);
  const review = state?.review ?? null;
  const drafts = state?.oracleDrafts ?? {};
  const facetDrafts = state?.facetDrafts ?? {};
  const author = state?.oracleAuthor ?? '';
  const approval = state?.approval ?? null;
  const approve = useMutation({
    mutationFn: () => {
      if (!review) throw new Error('Retain a requirement review before authoring oracles.');
      return api.approveSequenceOracles(review.review_id, buildOracleApproval(review, drafts, facetDrafts, author));
    },
    onSuccess: (result) => patch(templateId, { approval: result, preflight: null }),
  });
  if (!review) return null;
  const complete = oraclesComplete(review, drafts, facetDrafts, author, state?.reviewer ?? '');
  const facets = authorableFacets(review);
  const points = review.point_contract.points;

  const updateDraft = (id: string, patchDraft: (draft: OracleDraftValues) => OracleDraftValues) =>
    patch(templateId, (current) => ({ oracleDrafts: { ...current.oracleDrafts, [id]: patchDraft(current.oracleDrafts[id]) } }));
  const updateFacet = (id: string, patchFacet: Partial<FacetDraftValues>) =>
    patch(templateId, (current) => ({ facetDrafts: { ...current.facetDrafts, [id]: { ...current.facetDrafts[id], ...patchFacet } } }));

  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-start gap-3 flex-wrap">
        <div className="flex-1 min-w-64">
          <p className="eyebrow">Gate 6</p>
          <h2 className="text-xl font-semibold tracking-tight">Independent acceptance trajectories</h2>
          <p className="text-sm text-fg-1 mt-1">A second engineer authors the stimulus and the expected response for every trajectory. The requirement after the trigger is locked from the review; you supply the baseline, the pre-trigger window, and the recovery.</p>
        </div>
        <Field label="Independent test author" hint="Must differ from the requirement reviewer." htmlFor="design-author" className="w-64">
          <Input id="design-author" value={author} onChange={(event) => patch(templateId, { oracleAuthor: event.target.value })} placeholder="Named test engineer" aria-label="Independent oracle author" />
        </Field>
      </div>

      <ul className="flex flex-col gap-3" aria-label="Oracle drafts">
        {review.oracle_drafts.map((draft) => {
          const authored = drafts[draft.id];
          if (!authored) return null;
          const duration = Math.max(0, ...draft.durations.map((item) => item.seconds));
          return (
            <li key={draft.id} className="panel p-3 flex flex-col gap-3">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-mono text-xs">{draft.id}</span>
                {draft.conditions.map((condition) => (
                  <StatusPill key={condition.point} tone="neutral" icon={null}>
                    {condition.point} {condition.operator} {condition.value} {condition.unit}
                  </StatusPill>
                ))}
                {duration > 0 && <StatusPill tone="neutral" icon={null}>for {duration} s</StatusPill>}
                <label className="ml-auto text-xs text-fg-1 inline-flex items-center gap-2">
                  Step seconds
                  <Input type="number" min={0.001} step="any" value={authored.stepSeconds} onChange={(event) => updateDraft(draft.id, (current) => ({ ...current, stepSeconds: event.target.value }))} aria-label={`Step seconds for ${draft.id}`} mono className="h-7 w-24 text-xs" />
                </label>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {draft.conditions.map((condition) => (
                  <fieldset key={condition.point} className="rounded-control border border-line-1 p-2">
                    <legend className="px-1 text-2xs text-fg-2">{condition.point} stimulus</legend>
                    <div className="grid grid-cols-3 gap-2 text-2xs text-fg-2">
                      <label className="flex flex-col gap-1">Baseline<ValueInput boolean={false} value={authored.baselineInputs[condition.point]} onChange={(value) => updateDraft(draft.id, (current) => ({ ...current, baselineInputs: { ...current.baselineInputs, [condition.point]: value } }))} label={`${draft.id} ${condition.point} baseline`} /></label>
                      <label className="flex flex-col gap-1">Trigger<ValueInput boolean={false} value={authored.triggerInputs[condition.point]} onChange={(value) => updateDraft(draft.id, (current) => ({ ...current, triggerInputs: { ...current.triggerInputs, [condition.point]: value } }))} label={`${draft.id} ${condition.point} trigger`} /></label>
                      <label className="flex flex-col gap-1">Recovery<ValueInput boolean={false} value={authored.recoveryInputs[condition.point]} onChange={(value) => updateDraft(draft.id, (current) => ({ ...current, recoveryInputs: { ...current.recoveryInputs, [condition.point]: value } }))} label={`${draft.id} ${condition.point} recovery`} /></label>
                    </div>
                  </fieldset>
                ))}
                {draft.expectations.map((expectation) => {
                  const boolean = typeof expectation.value === 'boolean';
                  return (
                    <fieldset key={expectation.point} className="rounded-control border border-line-1 p-2">
                      <legend className="px-1 text-2xs text-fg-2">{expectation.point} response</legend>
                      <div className={cn('grid gap-2 text-2xs text-fg-2', duration > 0 ? 'grid-cols-4' : 'grid-cols-3')}>
                        <label className="flex flex-col gap-1">Baseline<ValueInput boolean={boolean} value={authored.baselineOutputs[expectation.point]} onChange={(value) => updateDraft(draft.id, (current) => ({ ...current, baselineOutputs: { ...current.baselineOutputs, [expectation.point]: value } }))} label={`${draft.id} ${expectation.point} baseline`} /></label>
                        {duration > 0 && <label className="flex flex-col gap-1">Before timer<ValueInput boolean={boolean} value={authored.preTriggerOutputs[expectation.point]} onChange={(value) => updateDraft(draft.id, (current) => ({ ...current, preTriggerOutputs: { ...current.preTriggerOutputs, [expectation.point]: value } }))} label={`${draft.id} ${expectation.point} before timer`} /></label>}
                        <div className="flex flex-col gap-1">
                          After trigger · locked
                          <span className="h-7 inline-flex items-center px-2 rounded-control bg-bg-2 font-mono text-xs text-fg-0">
                            {String(expectation.value)} · {expectation.verb}
                          </span>
                        </div>
                        <label className="flex flex-col gap-1">Recovery<ValueInput boolean={boolean} value={authored.recoveryOutputs[expectation.point]} onChange={(value) => updateDraft(draft.id, (current) => ({ ...current, recoveryOutputs: { ...current.recoveryOutputs, [expectation.point]: value } }))} label={`${draft.id} ${expectation.point} recovery`} /></label>
                      </div>
                    </fieldset>
                  );
                })}
              </div>
            </li>
          );
        })}
      </ul>

      {facets.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-medium">Event and mode trajectories</h3>
          <p className="text-2xs text-fg-2">Source-mentioned facets without numeric extraction still require explicit input and output transitions.</p>
          <ul className="flex flex-col gap-3" aria-label="Facet oracle drafts">
            {facets.map((requirement) => {
              const id = facetKey(requirement);
              const authored = facetDrafts[id];
              if (!authored) return null;
              const inputPoint = points.find((point) => point.id === authored.inputPoint);
              const outputPoint = points.find((point) => point.id === authored.outputPoint);
              return (
                <li key={id} className="panel p-3 flex flex-col gap-3">
                  <div>
                    <span className="eyebrow">{requirement.scenario_title}</span>
                    <span className="block text-sm font-medium">{requirement.facet_label}</span>
                    {requirement.source_evidence[0] && <span className="block text-2xs text-fg-2 truncate">“{requirement.source_evidence[0].excerpt}”</span>}
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-2xs text-fg-2">
                    <label className="flex flex-col gap-1">
                      Trigger input point
                      <NativeSelect size="sm" value={authored.inputPoint} onChange={(event) => updateFacet(id, { inputPoint: event.target.value, baselineInput: '', triggerInput: '', recoveryInput: '' })} aria-label={`Trigger input point for ${requirement.facet_label}`}>
                        <option value="">Select input…</option>
                        {points.filter((point) => requirement.input_point_candidates.includes(point.id)).map((point) => (
                          <option key={point.id} value={point.id}>
                            {point.id} · {point.data_type}
                          </option>
                        ))}
                      </NativeSelect>
                    </label>
                    <label className="flex flex-col gap-1">
                      Observed output point
                      <NativeSelect size="sm" value={authored.outputPoint} onChange={(event) => updateFacet(id, { outputPoint: event.target.value, baselineOutput: '', triggerOutput: '', recoveryOutput: '' })} aria-label={`Observed output point for ${requirement.facet_label}`}>
                        <option value="">Select output…</option>
                        {points.filter((point) => requirement.output_point_candidates.includes(point.id)).map((point) => (
                          <option key={point.id} value={point.id}>
                            {point.id} · {point.data_type}
                          </option>
                        ))}
                      </NativeSelect>
                    </label>
                    <label className="flex flex-col gap-1">
                      Step seconds
                      <Input type="number" min={0.001} step="any" value={authored.stepSeconds} onChange={(event) => updateFacet(id, { stepSeconds: event.target.value })} aria-label={`Step seconds for ${requirement.facet_label}`} mono className="h-7 text-xs" />
                    </label>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {inputPoint && (
                      <fieldset className="rounded-control border border-line-1 p-2">
                        <legend className="px-1 text-2xs text-fg-2">{inputPoint.id} stimulus</legend>
                        <div className="grid grid-cols-3 gap-2 text-2xs text-fg-2">
                          <label className="flex flex-col gap-1">Baseline<ValueInput boolean={inputPoint.data_type === 'boolean'} value={authored.baselineInput} onChange={(value) => updateFacet(id, { baselineInput: value })} label={`${requirement.facet_label} input baseline`} /></label>
                          <label className="flex flex-col gap-1">Trigger<ValueInput boolean={inputPoint.data_type === 'boolean'} value={authored.triggerInput} onChange={(value) => updateFacet(id, { triggerInput: value })} label={`${requirement.facet_label} input trigger`} /></label>
                          <label className="flex flex-col gap-1">Recovery<ValueInput boolean={inputPoint.data_type === 'boolean'} value={authored.recoveryInput} onChange={(value) => updateFacet(id, { recoveryInput: value })} label={`${requirement.facet_label} input recovery`} /></label>
                        </div>
                      </fieldset>
                    )}
                    {outputPoint && (
                      <fieldset className="rounded-control border border-line-1 p-2">
                        <legend className="px-1 text-2xs text-fg-2">{outputPoint.id} expected response</legend>
                        <div className="grid grid-cols-3 gap-2 text-2xs text-fg-2">
                          <label className="flex flex-col gap-1">Baseline<ValueInput boolean={outputPoint.data_type === 'boolean'} value={authored.baselineOutput} onChange={(value) => updateFacet(id, { baselineOutput: value })} label={`${requirement.facet_label} output baseline`} /></label>
                          <label className="flex flex-col gap-1">Trigger<ValueInput boolean={outputPoint.data_type === 'boolean'} value={authored.triggerOutput} onChange={(value) => updateFacet(id, { triggerOutput: value })} label={`${requirement.facet_label} output trigger`} /></label>
                          <label className="flex flex-col gap-1">Recovery<ValueInput boolean={outputPoint.data_type === 'boolean'} value={authored.recoveryOutput} onChange={(value) => updateFacet(id, { recoveryOutput: value })} label={`${requirement.facet_label} output recovery`} /></label>
                        </div>
                      </fieldset>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <div className="flex items-center gap-3">
        <Button variant="primary" disabled={!complete || approve.isPending} onClick={() => approve.mutate()}>
          {approve.isPending ? 'Validating independent trajectories…' : `Approve ${review.oracle_draft_count + facets.length} test trajectories`}
        </Button>
      </div>
      {approve.isError && <div role="alert" className="rounded-panel border border-fail/40 bg-fail-soft p-3 text-sm text-fail">{approve.error instanceof Error ? approve.error.message : 'The oracles were rejected.'}</div>}
      {approval && (
        <div className={cn('rounded-panel border p-3 text-sm', approval.ready_for_graph_generation ? 'border-ok/40' : 'border-warn/40')}>
          <strong>{approval.ready_for_graph_generation ? 'Independent oracle gate passed; graph generation enabled' : 'Local oracles approved; whole-system coverage still blocked'}</strong>
          <p className="text-xs text-fg-2 mt-1">
            {approval.case_count} cases · approval <span className="num">{approval.oracle_approval_id.slice(0, 12)}</span> · {approval.scenario_oracle_gap_count ?? 0} scenario facets still lack executable oracles · deployment remains blocked · next gate: {approval.next_gate}
          </p>
        </div>
      )}
    </section>
  );
}
