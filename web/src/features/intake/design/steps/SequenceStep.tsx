import { useMutation } from '@tanstack/react-query';
import { FileText } from 'lucide-react';

import { api } from '../../../../api/client';
import { cn } from '../../../../design-system/cn';
import { Button, StatusPill } from '../../../../design-system/primitives';
import { useDesign } from '../../../../stores/design';

const coverageTone = { 'all-facets-mentioned': 'ok', partial: 'warn', 'not-mentioned': 'fail', 'coverage-rule-missing': 'offline' } as const;

export function SequenceStep({ templateId }: { templateId: string }) {
  const state = useDesign((store) => store.byTemplate[templateId]);
  const patch = useDesign((store) => store.patch);
  const file = state?.sequenceFile ?? null;
  const result = state?.sequenceReconciliation ?? null;
  const check = useMutation({
    mutationFn: () => {
      if (!file) throw new Error('Choose a sequence document first.');
      return api.inspectCtrlFlowSequence(templateId, state?.selections ?? {}, file);
    },
    onSuccess: (data) => patch(templateId, { sequenceReconciliation: data, decisions: {}, review: null, approval: null, preflight: null }),
  });
  const candidates = result?.requirement_candidates;

  return (
    <section className="flex flex-col gap-4">
      <div>
        <p className="eyebrow">Gate 4</p>
        <h2 className="text-xl font-semibold tracking-tight">Check the sequence against the template's scenarios</h2>
        <p className="text-sm text-fg-1 mt-1">Phrase coverage only: the narrative is matched against each scenario facet, and structured requirement candidates are extracted for your review. Nothing is executable from text alone.</p>
      </div>
      <div className="panel p-3 flex items-center gap-3">
        <FileText size={18} className="text-fg-2" />
        <div className="flex-1 min-w-0 text-sm">
          <span className="font-medium">Sequence of operations</span>
          {file && <span className="ml-2 font-mono text-xs">{file.name}</span>}
        </div>
        <label className="shrink-0">
          <input type="file" name="sequence" accept=".txt,.md,.json,.docx,.pdf" className="sr-only" aria-label="Attach sequence document" onChange={(event) => patch(templateId, { sequenceFile: event.target.files?.[0] ?? null, sequenceReconciliation: null, decisions: {}, review: null, approval: null, preflight: null })} />
          <span className="inline-flex items-center h-8 px-3 rounded-control border border-line-2 text-sm cursor-pointer hover:bg-bg-2">{file ? 'Replace' : 'Attach'}</span>
        </label>
        <Button variant="primary" disabled={!file || check.isPending} onClick={() => check.mutate()}>
          {check.isPending ? 'Checking…' : 'Check sequence'}
        </Button>
      </div>
      {check.isError && <div role="alert" className="rounded-panel border border-fail/40 bg-fail-soft p-3 text-sm text-fail">{check.error instanceof Error ? check.error.message : 'The server rejected the document.'}</div>}
      {result && candidates && (
        <>
          <div className="flex items-center gap-2 flex-wrap">
            <StatusPill tone={result.language_coverage_complete ? 'ok' : 'warn'}>{result.language_coverage_complete ? 'All scenario facets mentioned' : 'Sequence gaps found'}</StatusPill>
            <span className="num text-fg-2">
              {result.all_facets_mentioned_count} full · {result.partial_count} partial · {result.not_mentioned_count} missing · {result.coverage_rule_missing_count} no rule
            </span>
            <StatusPill tone="neutral" icon={null}>{result.gate}</StatusPill>
          </div>
          <div className="panel">
            <header className="px-4 h-9 flex items-center gap-2 hairline-b">
              <h3 className="text-sm font-medium">Scenario facet coverage</h3>
              <span className="num text-fg-2">{result.scenario_count}</span>
            </header>
            <ul className="divide-y divide-line-1">
              {result.scenarios.map((scenario) => (
                <li key={scenario.id} className="px-4 py-2 text-xs">
                  <div className="flex items-center gap-2">
                    <StatusPill tone={coverageTone[scenario.coverage_status]} icon={null}>{scenario.coverage_status.replaceAll('-', ' ')}</StatusPill>
                    <span className="font-medium">{scenario.title}</span>
                    <span className="text-fg-2">{scenario.level}</span>
                    <span className="num text-fg-2 ml-auto">
                      {scenario.mentioned_facet_count}/{scenario.facet_count}
                    </span>
                  </div>
                  <ul className="mt-1 flex flex-wrap gap-1">
                    {scenario.facets.map((facet) => (
                      <li key={facet.id} className={cn('chip', facet.mentioned ? 'text-ok border-ok/40' : 'text-fg-2')} title={facet.evidence[0]?.excerpt ?? 'Not mentioned in the narrative'}>
                        {facet.label}
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          </div>
          <div className="panel p-4 text-xs flex flex-col gap-1">
            <h3 className="text-sm font-medium">Structured requirement candidates</h3>
            <p className="text-fg-1">
              <span className="num">{candidates.quantity_count}</span> quantities · <span className="num">{candidates.action_count}</span> actions · <span className="num">{candidates.policy_count}</span> policies · <span className="num">{candidates.unresolved_count}</span> unresolved
            </p>
            <p className="text-fg-2">Unapproved · never executable from text alone. Continue to give every candidate an explicit decision.</p>
            {result.limitations.length > 0 && (
              <ul className="list-disc pl-4 text-fg-2">
                {result.limitations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </section>
  );
}
