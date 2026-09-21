import { useMutation } from '@tanstack/react-query';

import { api } from '../../../../api/client';
import { useG36Parameters } from '../../../../api/queries';
import { cn } from '../../../../design-system/cn';
import { Button, Input, NativeSelect, StatusPill } from '../../../../design-system/primitives';
import { LoadingState } from '../../../../design-system/states';
import { useDesign } from '../../../../stores/design';
import { buildCandidateRequest } from '../payloads';

export function PreflightStep({ templateId }: { templateId: string }) {
  const state = useDesign((store) => store.byTemplate[templateId]);
  const patch = useDesign((store) => store.patch);
  const approval = state?.approval ?? null;
  const controllerId = state?.brief?.design_binding.controller_id;
  const parameters = useG36Parameters(controllerId);
  const required = parameters.data?.parameterization.parameters.filter((parameter) => parameter.required) ?? [];
  const values = state?.parameters ?? {};
  const bindings = state?.boundarySelections ?? {};
  const result = state?.preflight ?? null;

  const run = useMutation({
    mutationFn: () => {
      if (!approval) throw new Error('Approve the independent oracles first.');
      return api.preflightSequenceCandidate(approval.oracle_approval_id, buildCandidateRequest(approval, required, values, bindings));
    },
    onSuccess: (data) =>
      patch(templateId, (current) => ({
        preflight: data,
        boundarySelections: {
          ...Object.fromEntries((data.graph_boundary_contract ?? []).filter((boundary) => boundary.selected_design_point).map((boundary) => [boundary.id, boundary.selected_design_point!])),
          ...current.boundarySelections,
        },
      })),
  });
  if (!approval) return null;
  if (parameters.isLoading) return <LoadingState label="Loading the controller's parameter contract" />;
  const allFilled = required.every((parameter) => (values[parameter.name] ?? '').trim());

  return (
    <section className="flex flex-col gap-4">
      <div>
        <p className="eyebrow">Gate 7</p>
        <h2 className="text-xl font-semibold tracking-tight">Compiler preflight</h2>
        <p className="text-sm text-fg-1 mt-1">
          Exact translation of <span className="font-mono text-xs">{controllerId}</span>, target compile, boundary bindings, and the approved oracle replay. Nothing is retained as a candidate yet.
        </p>
      </div>
      {required.length > 0 && (
        <div className="panel">
          <header className="px-4 h-9 flex items-center gap-2 hairline-b">
            <h3 className="text-sm font-medium">Required controller parameters</h3>
            <span className="num text-fg-2">{required.length}</span>
          </header>
          <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-3">
            {required.map((parameter) => (
              <label key={parameter.name} className="flex flex-col gap-1 text-xs text-fg-1">
                <span>
                  <span className="font-mono">{parameter.name}</span> <span className="text-fg-2">{parameter.data_type}{parameter.is_array ? '[]' : ''}{parameter.unit ? ` · ${parameter.unit}` : ''}</span>
                </span>
                <Input value={values[parameter.name] ?? ''} onChange={(event) => patch(templateId, (current) => ({ parameters: { ...current.parameters, [parameter.name]: event.target.value } }))} placeholder={parameter.is_array ? '[1, 2]' : parameter.data_type === 'Boolean' ? 'true' : '0'} aria-label={`Parameter ${parameter.name}`} mono />
                {parameter.description && <span className="text-2xs text-fg-2">{parameter.description}</span>}
              </label>
            ))}
          </div>
        </div>
      )}
      {result?.graph_boundary_contract && result.graph_boundary_contract.length > 0 && (
        <div className="panel">
          <header className="px-4 h-9 flex items-center gap-2 hairline-b">
            <h3 className="text-sm font-medium">Graph boundary bindings</h3>
            <span className="text-2xs text-fg-2">each contractor design point binds to one boundary</span>
          </header>
          <ul className="divide-y divide-line-1">
            {result.graph_boundary_contract.map((boundary) => (
              <li key={boundary.id} className="px-4 py-2 grid grid-cols-[1fr_260px] gap-3 items-center text-xs">
                <span>
                  <span className="font-mono">{boundary.id}</span> <span className="text-fg-2">{boundary.direction} · {boundary.data_type} · {boundary.label}</span>
                </span>
                <NativeSelect size="sm" value={bindings[boundary.id] ?? ''} onChange={(event) => patch(templateId, (current) => ({ boundarySelections: { ...current.boundarySelections, [boundary.id]: event.target.value } }))} aria-label={`Design point for ${boundary.id}`}>
                  <option value="">unbound</option>
                  {boundary.compatible_design_points.map((point) => (
                    <option key={point} value={point}>
                      {point}
                    </option>
                  ))}
                </NativeSelect>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="flex items-center gap-3">
        <Button variant="primary" disabled={!allFilled || run.isPending} onClick={() => run.mutate()}>
          {run.isPending ? 'Translating and compiling…' : result ? 'Run preflight again' : 'Run preflight'}
        </Button>
      </div>
      {run.isError && <div role="alert" className="rounded-panel border border-fail/40 bg-fail-soft p-3 text-sm text-fail">{run.error instanceof Error ? run.error.message : 'Preflight failed.'}</div>}
      {result && (
        <div className={cn('rounded-panel border p-3 text-sm flex flex-col gap-1', result.ready_for_candidate_generation ? 'border-ok/40' : 'border-warn/40')}>
          <div className="flex items-center gap-2 flex-wrap">
            <StatusPill tone={result.ready_for_candidate_generation ? 'ok' : 'warn'}>{result.ready_for_candidate_generation ? 'Exact graph, target, bindings, and oracle replay passed' : `${result.blockers.length} compiler gate${result.blockers.length === 1 ? '' : 's'} remain`}</StatusPill>
            {result.test_report && <StatusPill tone={result.test_report.passed ? 'ok' : 'fail'}>{result.test_report.passed ? 'oracle replay passed' : 'oracle replay failed'}</StatusPill>}
          </div>
          <p className="text-xs text-fg-2">
            {result.candidate_graph ? `${result.candidate_graph.block_count} blocks · ${result.candidate_graph.link_count} links · ${result.candidate_graph.boundary_count} boundaries · digest ${result.candidate_graph.sha256.slice(0, 12)}` : 'Translation has not reached an executable graph.'}
          </p>
          {result.blockers.length > 0 && (
            <ul className="text-xs list-disc pl-4 text-warn">
              {result.blockers.map((blocker) => (
                <li key={blocker.code}>
                  <span className="font-mono">{blocker.code.replaceAll('-', ' ')}</span> · {blocker.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
