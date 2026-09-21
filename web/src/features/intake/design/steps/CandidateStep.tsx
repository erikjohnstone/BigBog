import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';

import { api } from '../../../../api/client';
import { useG36Parameters, keys } from '../../../../api/queries';
import { Button, Field, Input, StatusPill } from '../../../../design-system/primitives';
import { useDesign } from '../../../../stores/design';
import { EQUIPMENT_PATTERN } from '../../build-import-form';
import { buildCandidateRequest } from '../payloads';

export function CandidateStep({ templateId }: { templateId: string }) {
  const state = useDesign((store) => store.byTemplate[templateId]);
  const patch = useDesign((store) => store.patch);
  const reset = useDesign((store) => store.reset);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const approval = state?.approval ?? null;
  const parameters = useG36Parameters(state?.brief?.design_binding.controller_id);
  const required = parameters.data?.parameterization.parameters.filter((parameter) => parameter.required) ?? [];
  const candidate = state?.candidate ?? { name: '', site: '', equipmentName: '' };
  const complete = Boolean(candidate.name.trim() && candidate.site.trim() && EQUIPMENT_PATTERN.test(candidate.equipmentName));
  const generate = useMutation({
    mutationFn: () => {
      if (!approval || !state) throw new Error('Preflight must pass first.');
      return api.generateSequenceCandidate(
        approval.oracle_approval_id,
        buildCandidateRequest(approval, required, state.parameters, state.boundarySelections, { name: candidate.name.trim(), site: candidate.site.trim(), equipment_name: candidate.equipmentName.trim() }),
      );
    },
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: keys.runs });
      reset(templateId);
      navigate(`/jobs/${result.run.id}/build`);
    },
  });
  if (!approval || !state?.preflight) return null;

  return (
    <section className="flex flex-col gap-4">
      <div>
        <p className="eyebrow">Gate 8</p>
        <h2 className="text-xl font-semibold tracking-tight">Generate the candidate</h2>
        <p className="text-sm text-fg-1 mt-1">The preflighted graph becomes a retained candidate with its own tests and evidence. It waits for a named engineer like any other job; it never authorizes deployment.</p>
      </div>
      <div className="panel p-4 grid grid-cols-1 md:grid-cols-3 gap-3">
        <Field label="Job name" htmlFor="candidate-name">
          <Input id="candidate-name" value={candidate.name} onChange={(event) => patch(templateId, (current) => ({ candidate: { ...current.candidate, name: event.target.value } }))} placeholder="AHU-1 multizone VAV" />
        </Field>
        <Field label="Site" htmlFor="candidate-site">
          <Input id="candidate-site" value={candidate.site} onChange={(event) => patch(templateId, (current) => ({ candidate: { ...current.candidate, site: event.target.value } }))} placeholder="Riverview Medical Office" />
        </Field>
        <Field label="Equipment identifier" htmlFor="candidate-equipment" error={candidate.equipmentName && !EQUIPMENT_PATTERN.test(candidate.equipmentName) ? 'Letters, digits, underscores; not starting with a digit.' : undefined}>
          <Input id="candidate-equipment" value={candidate.equipmentName} onChange={(event) => patch(templateId, (current) => ({ candidate: { ...current.candidate, equipmentName: event.target.value } }))} placeholder="AHU_1" mono />
        </Field>
      </div>
      <div className="flex items-center gap-3 flex-wrap">
        <Button variant="primary" size="lg" disabled={!complete || generate.isPending} onClick={() => generate.mutate()}>
          {generate.isPending ? 'Generating and testing…' : 'Generate candidate'}
        </Button>
        <StatusPill tone="offline">human approval required · no live writes</StatusPill>
      </div>
      {generate.isError && <div role="alert" className="rounded-panel border border-fail/40 bg-fail-soft p-3 text-sm text-fail">{generate.error instanceof Error ? generate.error.message : 'Candidate generation failed.'}</div>}
    </section>
  );
}
