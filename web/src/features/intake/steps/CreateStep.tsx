import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ShieldCheck } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { api } from '../../../api/client';
import { keys } from '../../../api/queries';
import { Button, StatusPill } from '../../../design-system/primitives';
import { useIntake } from '../../../stores/intake';
import { buildImportForm } from '../build-import-form';
import { familyById } from '../families';

export function CreateStep({ errors }: { errors: Record<string, string> }) {
  const draft = useIntake((state) => state.draft);
  const files = useIntake((state) => state.files);
  const inspection = useIntake((state) => state.inspection);
  const reset = useIntake((state) => state.reset);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const family = familyById(draft.sequenceFamily);
  const create = useMutation({
    mutationFn: () => api.importRun(buildImportForm(draft, files)),
    onSuccess: async (run) => {
      await queryClient.invalidateQueries({ queryKey: keys.runs });
      reset();
      navigate(`/jobs/${run.id}/build`);
    },
  });
  const blocked = Object.keys(errors).length > 0;

  return (
    <section className="flex flex-col gap-4">
      <div>
        <p className="eyebrow">Step 5</p>
        <h2 className="text-xl font-semibold tracking-tight">Create the candidate</h2>
        <p className="text-sm text-fg-1 mt-1">BACTalk builds the typed graph, compiles the target, and runs the deterministic tests. The candidate then waits for a named engineer.</p>
      </div>
      <dl className="panel grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1.5 p-4 text-sm">
        <dt className="text-fg-2">Job</dt>
        <dd>
          {draft.name} · {draft.site} · <span className="font-mono text-xs">{draft.equipmentName}</span>
        </dd>
        <dt className="text-fg-2">Family</dt>
        <dd>
          {family?.label ?? draft.sequenceFamily} <span className="font-mono text-2xs text-fg-2">{draft.sequenceFamily}</span>
          {family?.library && <span className="font-mono text-xs"> · {draft.controllerId}</span>}
        </dd>
        <dt className="text-fg-2">Points</dt>
        <dd>
          {files.points?.name ?? '—'}
          {inspection && (
            <span className="text-fg-2">
              {' '}
              · <span className="num">{inspection.point_count}</span> points, <span className="num">{inspection.mapped_bacnet_points}</span> BACnet mapped
            </span>
          )}
        </dd>
        <dt className="text-fg-2">Sequence</dt>
        <dd>{files.sequence?.name ?? <span className="text-fg-2">none attached</span>}</dd>
        <dt className="text-fg-2">Acceptance tests</dt>
        <dd>
          <span className="num">{draft.acceptanceTests.length}</span> engineer-authored{family?.requiresTests ? '' : ' plus the family suite'}
        </dd>
        <dt className="text-fg-2">Other files</dt>
        <dd className="text-fg-1">{[files.bacnet && 'BACnet scan', files.template && 'station template', files.environment && 'environment pack'].filter(Boolean).join(', ') || 'none'}</dd>
      </dl>
      {blocked && (
        <ul className="text-xs text-fail flex flex-col gap-0.5" role="alert">
          {Object.values(errors).map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      )}
      {create.isError && (
        <div role="alert" className="rounded-panel border border-fail/40 bg-fail-soft p-3 text-sm text-fail">
          {create.error instanceof Error ? create.error.message : 'The server rejected the job.'}
        </div>
      )}
      <div className="flex items-center gap-3">
        <Button variant="primary" size="lg" disabled={blocked || create.isPending} onClick={() => create.mutate()}>
          {create.isPending ? 'Building candidate…' : 'Create job and build'}
        </Button>
        <StatusPill tone="offline" icon={<ShieldCheck size={12} />}>
          offline · no live writes
        </StatusPill>
      </div>
    </section>
  );
}
