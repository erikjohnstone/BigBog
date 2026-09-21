import { Check, X } from 'lucide-react';

import type { RunDetail } from '../../api/client';
import { useReport } from '../../api/queries';
import { StatusPill } from '../../design-system/primitives';
import { ErrorState, LoadingState } from '../../design-system/states';
import { KeyValue, SectionCard, StageFrame } from '../shared/StageFrame';

/**
 * Test stage. Phase 3 adds the shared clock, timeline, and trend panes; this
 * renders every scenario and assertion from the retained report verbatim.
 */
export function TestStage({ run }: { run: RunDetail }) {
  const report = useReport(run.id);
  if (report.isLoading) return <LoadingState label="Loading test report" />;
  if (report.isError || !report.data) return <ErrorState error={report.error ?? 'Report unavailable'} onRetry={() => report.refetch()} />;

  const data = report.data;
  const assertionCount = data.scenarios.reduce((sum, scenario) => sum + scenario.assertions.length, 0);
  const passedCount = data.scenarios.reduce((sum, scenario) => sum + scenario.assertions.filter((a) => a.passed).length, 0);

  return (
    <StageFrame wide>
      <SectionCard
        title="Deterministic tests"
        aside={<StatusPill tone={data.passed ? 'ok' : 'fail'}>{data.passed ? 'Passed' : 'Failed'}</StatusPill>}
      >
        <KeyValue
          items={[
            { label: 'Engine', value: <span className="font-mono text-xs">{data.engine}</span> },
            { label: 'Scenarios', value: <span className="num">{data.scenarios.length}</span> },
            {
              label: 'Assertions',
              value: (
                <span className="num">
                  {passedCount} / {assertionCount} passed
                </span>
              ),
            },
            ...(data.coverage?.percent !== undefined
              ? [{ label: 'Decision coverage', value: <span className="num">{data.coverage.percent.toFixed(1)}%</span> }]
              : []),
          ]}
        />
      </SectionCard>
      {data.scenarios.map((scenario) => (
        <SectionCard
          key={scenario.name}
          title={scenario.name}
          aside={<StatusPill tone={scenario.passed ? 'ok' : 'fail'}>{scenario.passed ? 'Passed' : 'Failed'}</StatusPill>}
        >
          <table className="w-full text-sm">
            <thead className="text-left">
              <tr className="hairline-b">
                <th className="eyebrow px-4 h-8 font-semibold">Assertion</th>
                <th className="eyebrow px-4 h-8 font-semibold">Observed</th>
                <th className="eyebrow px-4 h-8 font-semibold">Expected</th>
                <th className="eyebrow px-4 h-8 font-semibold w-16">Result</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line-1">
              {scenario.assertions.map((assertion, index) => (
                <tr key={`${assertion.name}-${index}`}>
                  <td className="px-4 h-9 font-mono text-xs">{assertion.name}</td>
                  <td className="px-4 num">{assertion.observed}</td>
                  <td className="px-4 num">{assertion.expected}</td>
                  <td className="px-4">
                    {assertion.passed ? (
                      <span className="inline-flex items-center gap-1 text-ok text-xs"><Check size={12} /> pass</span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-fail text-xs"><X size={12} /> fail</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="px-4 py-2 text-2xs text-fg-2 hairline-t">
            <span className="num">{scenario.samples.length}</span> scan samples retained
          </p>
        </SectionCard>
      ))}
    </StageFrame>
  );
}
