import { useMutation } from '@tanstack/react-query';
import { useEffect, useMemo } from 'react';

import { api } from '../../../../api/client';
import { useCtrlFlowConfiguration } from '../../../../api/queries';
import { Button, StatusPill } from '../../../../design-system/primitives';
import { ErrorState, LoadingState } from '../../../../design-system/states';
import { EMPTY_SELECTIONS, useDesign } from '../../../../stores/design';
import { layoutFromBrief } from '../../../schematic/layout/from-brief';
import { Schematic } from '../../../schematic/Schematic';

export function BriefStep({ templateId }: { templateId: string }) {
  const selections = useDesign((store) => store.byTemplate[templateId]?.selections ?? EMPTY_SELECTIONS);
  const brief = useDesign((store) => store.byTemplate[templateId]?.brief ?? null);
  const patch = useDesign((store) => store.patch);
  const configuration = useCtrlFlowConfiguration(templateId, selections);
  const effective = configuration.data?.selections ?? selections;
  const generate = useMutation({ mutationFn: () => api.ctrlFlowProgrammingBrief(templateId, effective), onSuccess: (result) => patch(templateId, { brief: result }) });
  const { mutate } = generate;
  useEffect(() => {
    if (!brief && configuration.data && !generate.isPending) mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brief, configuration.data]);
  const layout = useMemo(() => (brief ? layoutFromBrief(brief) : null), [brief]);

  if (!brief && (generate.isPending || configuration.isLoading)) return <LoadingState label="Generating the programming brief" />;
  if (!brief && generate.isError) return <ErrorState error={generate.error} onRetry={() => mutate()} />;
  if (!brief) return <LoadingState label="Waiting for configuration" />;

  const required = brief.point_requirements.points.filter((point) => point.required);
  const conditional = brief.point_requirements.points.filter((point) => !point.required);

  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-start gap-3 flex-wrap">
        <div className="flex-1 min-w-64">
          <p className="eyebrow">Gate 2</p>
          <h2 className="text-xl font-semibold tracking-tight">Programming brief</h2>
          <p className="text-sm text-fg-1 mt-1">
            Bound to <span className="font-mono text-xs">{brief.design_binding.controller_id}</span> for {brief.design_binding.equipment_family}. This is what the candidate must satisfy; it is not deployable.
          </p>
        </div>
        <div className="flex gap-2 flex-wrap items-center">
          <StatusPill tone={brief.status === 'ready' ? 'ok' : 'warn'}>{brief.status}</StatusPill>
          <Button variant="outline" size="sm" onClick={() => mutate()} disabled={generate.isPending}>
            Regenerate
          </Button>
        </div>
      </div>

      {layout && (
        <div className="panel p-3">
          <h3 className="eyebrow mb-2">System components · preview</h3>
          <div className="h-44">
            <Schematic layout={layout} />
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="panel">
          <header className="px-4 h-9 flex items-center gap-2 hairline-b">
            <h3 className="text-sm font-medium">Required points</h3>
            <span className="num text-fg-2">{required.length}</span>
            <span className="text-2xs text-fg-2">· {conditional.length} conditional</span>
          </header>
          <ul className="divide-y divide-line-1 max-h-80 overflow-auto">
            {[...required, ...conditional].map((point) => (
              <li key={point.id} className="px-4 py-1.5 text-xs flex items-center gap-2">
                <span className="font-mono">{point.id}</span>
                <span className="text-fg-2 truncate flex-1">{point.label}</span>
                <span className="text-fg-2">{point.role}</span>
                <span className="text-fg-2">{point.units ?? ''}</span>
                {!point.required && <StatusPill tone="neutral" icon={null}>{point.condition || 'conditional'}</StatusPill>}
              </li>
            ))}
          </ul>
        </div>
        <div className="flex flex-col gap-4">
          <div className="panel">
            <header className="px-4 h-9 flex items-center gap-2 hairline-b">
              <h3 className="text-sm font-medium">Test scenarios</h3>
              <span className="num text-fg-2">{brief.qualification_plan.scenario_count}</span>
              <span className="text-2xs text-fg-2">· {brief.qualification_plan.execution_status}</span>
            </header>
            <ul className="divide-y divide-line-1 max-h-56 overflow-auto">
              {brief.qualification_plan.scenarios.map((scenario) => (
                <li key={scenario.id} className="px-4 py-1.5 text-xs flex items-center gap-2">
                  <span className="flex-1 truncate">{scenario.title}</span>
                  <span className="text-fg-2">{scenario.level}</span>
                  <StatusPill tone={scenario.status === 'passed' ? 'ok' : 'neutral'} icon={null}>{scenario.status}</StatusPill>
                </li>
              ))}
            </ul>
          </div>
          <div className="panel p-4 text-xs flex flex-col gap-2">
            <h3 className="text-sm font-medium">Why this is not deployable yet</h3>
            <ul className="list-disc pl-4 text-fg-1 flex flex-col gap-0.5">
              {brief.release_blockers.map((blocker) => (
                <li key={blocker}>{blocker}</li>
              ))}
            </ul>
            <p className="text-fg-2">
              Capability packs: {brief.capability_alignment.candidate_packs.map((pack) => `${pack.name} (${pack.stage})`).join(', ') || 'none'} · reference controller {brief.capability_alignment.reference_controller_available ? 'available' : 'unavailable'}
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
