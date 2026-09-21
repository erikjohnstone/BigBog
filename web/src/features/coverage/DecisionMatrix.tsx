import type { TestReport } from '../../api/client';
import { cn } from '../../design-system/cn';
import { StatusPill } from '../../design-system/primitives';
import { useSelection } from '../../stores/selection';

/** Every decision point and which outcomes the acceptance suite observed. */
export function DecisionMatrix({ report }: { report: TestReport }) {
  const coverage = report.coverage;
  const decisions = coverage?.decisions ?? [];
  const selectBlocks = useSelection((state) => state.selectBlocks);
  const selected = useSelection((state) => state.blockIds);
  if (decisions.length === 0) {
    return <p className="p-4 text-sm text-fg-2">This report records no decision points.</p>;
  }
  return (
    <div className="flex flex-col gap-3 p-4">
      <div className="flex items-center gap-3 flex-wrap text-sm">
        {coverage?.percent !== undefined && (
          <span className="inline-flex items-baseline gap-1">
            <span className="text-2xl font-semibold num">{coverage.percent.toFixed(0)}%</span>
            <span className="text-fg-1">of decision outcomes observed</span>
          </span>
        )}
        {coverage?.outcomes_observed !== undefined && coverage?.outcomes_possible !== undefined && (
          <span className="num text-fg-2">
            {coverage.outcomes_observed} / {coverage.outcomes_possible}
          </span>
        )}
        {coverage?.interpretation && <span className="text-xs text-fg-2">{coverage.interpretation}</span>}
      </div>
      <table className="w-full text-sm">
        <thead className="text-left">
          <tr className="hairline-b">
            <th className="eyebrow px-2 h-8 font-semibold">Decision</th>
            <th className="eyebrow px-2 h-8 font-semibold w-28">False</th>
            <th className="eyebrow px-2 h-8 font-semibold w-28">True</th>
            <th className="eyebrow px-2 h-8 font-semibold w-40">Coverage</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line-1">
          {decisions.map((decision) => {
            const blockId = decision.decision.split('.')[0];
            const observed = decision.observed.map(String);
            const cell = (value: string) => (
              <span className={cn('inline-flex items-center justify-center h-5 px-2 rounded-chip text-2xs font-mono', observed.includes(value) ? 'bg-ok-soft text-ok' : 'bg-bg-2 text-fg-2')}>
                {observed.includes(value) ? 'seen' : 'never'}
              </span>
            );
            return (
              <tr
                key={decision.decision}
                className={cn('cursor-pointer hover:bg-bg-2', selected.has(blockId) && 'bg-accent-soft')}
                onClick={() => selectBlocks([blockId])}
              >
                <td className="px-2 h-8 font-mono text-xs">{decision.decision}</td>
                <td className="px-2">{cell('false')}</td>
                <td className="px-2">{cell('true')}</td>
                <td className="px-2">
                  <StatusPill tone={decision.both_outcomes ? 'ok' : 'warn'}>{decision.both_outcomes ? 'both outcomes' : 'one outcome'}</StatusPill>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {(coverage?.gaps?.length ?? 0) > 0 && (
        <div>
          <h2 className="eyebrow mb-1">Gaps</h2>
          <ul className="text-xs text-fg-1 flex flex-col gap-0.5">
            {coverage!.gaps!.map((gap) => (
              <li key={gap}>{gap}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
