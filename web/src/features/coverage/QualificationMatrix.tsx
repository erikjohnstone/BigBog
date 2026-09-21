import type { TestReport } from '../../api/client';
import { cn } from '../../design-system/cn';
import { StatusPill } from '../../design-system/primitives';
import type { Tone } from '../../design-system/primitives';
import { useSelection } from '../../stores/selection';
import type { Trace } from '../../stores/trace';
import { useTimeCursor } from '../../stores/timeCursor';

const STATUS_ORDER = ['passed', 'failed', 'missing', 'insufficient_fault_evidence', 'insufficient_recovery_evidence', 'needs_applicability_review', 'not_applicable'];

/** Only `passed` is ever green; every other status is a distinct, honest tone. */
export function qualificationTone(status: string): Tone {
  switch (status) {
    case 'passed':
      return 'ok';
    case 'failed':
      return 'fail';
    case 'not_applicable':
      return 'neutral';
    case 'missing':
      return 'offline';
    default:
      return 'warn';
  }
}

function statusLabel(status: string): string {
  return status.replaceAll('_', ' ');
}

/**
 * Sequence-family qualification profile: what the profile requires, which
 * acceptance cases are the evidence, and what is still missing.
 */
export function QualificationMatrix({ report, trace }: { report: TestReport; trace?: Trace }) {
  const matrix = report.coverage?.qualification_matrix;
  const selectBlocks = useSelection((state) => state.selectBlocks);
  if (!matrix) return <p className="p-4 text-sm text-fg-2">No qualification profile applies to this sequence family.</p>;

  const categories = [...new Set(matrix.requirements.map((item) => item.category))];
  const statuses = STATUS_ORDER.filter((status) => matrix.requirements.some((item) => item.status === status));

  const seekToCase = (caseName: string) => {
    const phase = trace?.phases.find((item) => item.name === caseName || item.name.startsWith(`${caseName} ·`));
    if (!phase) return;
    useTimeCursor.getState().pause();
    useTimeCursor.getState().setLoop([phase.startIdx, phase.endIdx]);
    useTimeCursor.getState().seekIndex(phase.startIdx);
    const assertion = trace?.assertions.find((item) => item.phaseIndex === phase.index && item.blockIds[0]);
    if (assertion?.blockIds[0]) selectBlocks(assertion.blockIds);
  };

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center gap-3 flex-wrap text-sm">
        <span className="inline-flex items-baseline gap-1">
          <span className="text-2xl font-semibold num">{matrix.required_passed}</span>
          <span className="text-fg-1">of {matrix.required_count} required conditions passed</span>
        </span>
        <span className="num text-fg-2">
          {matrix.conditional_addressed} / {matrix.conditional_count} conditional addressed
        </span>
        <StatusPill tone={matrix.engineering_matrix_complete ? 'ok' : 'warn'}>
          {matrix.engineering_matrix_complete ? 'engineering matrix complete' : 'engineering matrix incomplete'}
        </StatusPill>
        {matrix.profile && (
          <span className="text-2xs text-fg-2 font-mono">
            {matrix.profile.id} v{matrix.profile.version} · {matrix.profile.source}
          </span>
        )}
      </div>
      {matrix.interpretation && <p className="text-xs text-fg-2">{matrix.interpretation}</p>}

      <div className="overflow-auto">
        <table className="text-xs" aria-label="Qualification status by category">
          <thead>
            <tr>
              <th className="eyebrow text-left px-2 h-7 font-semibold">Category</th>
              {statuses.map((status) => (
                <th key={status} className="eyebrow px-2 h-7 font-semibold text-center whitespace-nowrap">
                  {statusLabel(status)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {categories.map((category) => (
              <tr key={category} className="hairline-t">
                <td className="px-2 h-7 font-mono whitespace-nowrap">{category}</td>
                {statuses.map((status) => {
                  const count = matrix.requirements.filter((item) => item.category === category && item.status === status).length;
                  const tone = qualificationTone(status);
                  return (
                    <td key={status} className="px-2 text-center">
                      {count > 0 && (
                        <span
                          className={cn(
                            'inline-flex items-center justify-center size-5 rounded-chip num',
                            tone === 'ok' && 'bg-ok-soft text-ok',
                            tone === 'fail' && 'bg-fail-soft text-fail',
                            tone === 'warn' && 'bg-warn-soft text-warn',
                            tone === 'offline' && 'bg-bg-2 text-offline',
                            tone === 'neutral' && 'bg-bg-2 text-fg-1',
                          )}
                        >
                          {count}
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ul className="flex flex-col divide-y divide-line-1">
        {matrix.requirements.map((item) => (
          <li key={`${item.category}-${item.description}`} className="py-2 flex items-start gap-3 text-sm">
            <StatusPill tone={qualificationTone(item.status)} className="mt-0.5 shrink-0">
              {statusLabel(item.status)}
            </StatusPill>
            <div className="flex-1 min-w-0">
              <p className="leading-snug">
                <span className="font-mono text-xs text-fg-2">{item.category}</span> · {item.description}
              </p>
              <p className="text-xs text-fg-2 mt-0.5">
                {item.level}
                {item.fault_required ? ' · fault evidence required' : ''}
                {item.recovery_required ? ' · recovery evidence required' : ''}
                {item.reason ? ` · ${item.reason}` : ''}
              </p>
              {item.evidence_cases.length > 0 && (
                <p className="mt-1 flex gap-1 flex-wrap">
                  {item.evidence_cases.map((caseName) => (
                    <button
                      key={caseName}
                      type="button"
                      onClick={() => seekToCase(caseName)}
                      className="h-5 px-1.5 rounded-chip bg-bg-2 border border-line-1 text-2xs font-mono hover:border-accent"
                      title="Loop this case on the clock"
                    >
                      {caseName}
                    </button>
                  ))}
                </p>
              )}
            </div>
          </li>
        ))}
      </ul>

      {matrix.blockers.length > 0 && (
        <div>
          <h2 className="eyebrow mb-1">Blockers</h2>
          <ul className="text-xs text-warn flex flex-col gap-0.5">
            {matrix.blockers.map((blocker) => (
              <li key={blocker}>{blocker}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
