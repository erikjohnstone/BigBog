import { useMutation } from '@tanstack/react-query';
import { FileSpreadsheet } from 'lucide-react';

import { api } from '../../../../api/client';
import { Button, StatusPill } from '../../../../design-system/primitives';
import { useDesign } from '../../../../stores/design';

function IssueList({ title, items }: { title: string; items: Array<Record<string, unknown>> }) {
  if (items.length === 0) return null;
  return (
    <div className="panel">
      <header className="px-4 h-9 flex items-center gap-2 hairline-b">
        <h3 className="text-sm font-medium">{title}</h3>
        <span className="num text-fg-2">{items.length}</span>
      </header>
      <ul className="divide-y divide-line-1 max-h-64 overflow-auto">
        {items.map((item, index) => (
          <li key={index} className="px-4 py-1.5 font-mono text-2xs text-fg-1 break-all">
            {Object.entries(item)
              .map(([key, value]) => `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`)
              .join(' · ')}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function PointsStep({ templateId }: { templateId: string }) {
  const state = useDesign((store) => store.byTemplate[templateId]);
  const patch = useDesign((store) => store.patch);
  const file = state?.pointsFile ?? null;
  const result = state?.reconciliation ?? null;
  const check = useMutation({
    mutationFn: () => {
      if (!file) throw new Error('Choose a points CSV or XLSX file first.');
      return api.inspectCtrlFlowPoints(templateId, state?.selections ?? {}, file);
    },
    onSuccess: (data) => patch(templateId, { reconciliation: data }),
  });

  return (
    <section className="flex flex-col gap-4">
      <div>
        <p className="eyebrow">Gate 3</p>
        <h2 className="text-xl font-semibold tracking-tight">Reconcile the contractor's points</h2>
        <p className="text-sm text-fg-1 mt-1">The points list is matched against the brief's required contract. Alias suggestions, unit conversions, and duplicates are shown; nothing is accepted silently.</p>
      </div>
      <div className="panel p-3 flex items-center gap-3">
        <FileSpreadsheet size={18} className="text-fg-2" />
        <div className="flex-1 min-w-0 text-sm">
          <span className="font-medium">Points list</span>
          {file && <span className="ml-2 font-mono text-xs">{file.name}</span>}
        </div>
        <label className="shrink-0">
          <input type="file" name="points" accept=".csv,.xlsx,text/csv" className="sr-only" aria-label="Attach points list" onChange={(event) => patch(templateId, { pointsFile: event.target.files?.[0] ?? null, reconciliation: null, sequenceReconciliation: null, review: null, approval: null, preflight: null })} />
          <span className="inline-flex items-center h-8 px-3 rounded-control border border-line-2 text-sm cursor-pointer hover:bg-bg-2">{file ? 'Replace' : 'Attach'}</span>
        </label>
        <Button variant="primary" size="md" disabled={!file || check.isPending} onClick={() => check.mutate()}>
          {check.isPending ? 'Checking…' : 'Check points'}
        </Button>
      </div>
      {check.isError && <div role="alert" className="rounded-panel border border-fail/40 bg-fail-soft p-3 text-sm text-fail">{check.error instanceof Error ? check.error.message : 'The server rejected the points list.'}</div>}
      {result && (
        <>
          <div className="flex items-center gap-2 flex-wrap">
            <StatusPill tone={result.ready_for_sequence_reconciliation ? 'ok' : 'fail'}>{result.ready_for_sequence_reconciliation ? 'Point contract satisfied' : 'Point contract not satisfied'}</StatusPill>
            <span className="num text-fg-2">
              {result.matched_requirement_count}/{result.required_point_count} required matched · {result.provided_point_count} provided
            </span>
            <span className="num text-fg-2" title="Retained reconciliation">{result.point_reconciliation_id.slice(0, 12)}</span>
            {result.complete_niagara_job_ready && <StatusPill tone="info">complete Niagara job ready</StatusPill>}
          </div>
          {result.missing_required.length > 0 && (
            <div className="rounded-panel border border-fail/40 p-3 text-xs">
              <strong className="text-fail">Missing required points</strong>
              <p className="font-mono mt-1">{result.missing_required.join(', ')}</p>
            </div>
          )}
          <IssueList title="Blocking issues" items={result.blocking_issues} />
          <IssueList title="Ambiguous matches" items={result.ambiguous} />
          <IssueList title="Duplicates" items={result.duplicates} />
          <IssueList title="Unit conversions" items={result.unit_conversions} />
          <IssueList title="Provided but unmatched" items={result.unmatched_provided} />
        </>
      )}
    </section>
  );
}
