import { ArrowRight, GitCompareArrows } from 'lucide-react';
import { Link } from 'react-router-dom';

import { buttonClass, StatusPill, runStatusTone } from '../../design-system/primitives';
import type { ProposalSummary } from '../../stores/assistant';

/**
 * A proposed change is a separate candidate run. It is never applied here:
 * preview it as a ghost diff on the wiresheet, or open it to review its
 * own tests and evidence.
 */
export function ProposalCard({ proposal, assumptions }: { proposal: ProposalSummary; assumptions?: string[] }) {
  const tone = runStatusTone(proposal.status);
  const count = proposal.changes.added.length + proposal.changes.modified.length + proposal.changes.removed.length;
  return (
    <div className="mt-2 rounded-panel border border-sim/40 bg-sim-soft/40 p-3 flex flex-col gap-2" role="group" aria-label="Proposed candidate">
      <div className="flex items-center gap-2 flex-wrap">
        <StatusPill tone="sim">AI proposal</StatusPill>
        <StatusPill tone={tone.tone}>{tone.label}</StatusPill>
        {proposal.reportPassed === false && <StatusPill tone="fail">tests failed</StatusPill>}
        <span className="num text-fg-2">{proposal.runId.slice(0, 8)}</span>
      </div>
      <p className="text-xs text-fg-1">
        A separate candidate with <span className="num">{count}</span> recorded change{count === 1 ? '' : 's'}. Nothing was applied to this run.
      </p>
      {count > 0 && (
        <ul className="font-mono text-2xs flex flex-col gap-0.5 max-h-32 overflow-auto">
          {proposal.changes.added.map((item) => (
            <li key={`a-${item}`} className="text-accent">+ {item}</li>
          ))}
          {proposal.changes.modified.map((item) => (
            <li key={`m-${item}`} className="text-warn">~ {item}</li>
          ))}
          {proposal.changes.removed.map((item) => (
            <li key={`r-${item}`} className="text-fail">− {item}</li>
          ))}
        </ul>
      )}
      {assumptions && assumptions.length > 0 && (
        <div>
          <h4 className="eyebrow mb-0.5">Assumptions</h4>
          <ul className="text-xs text-fg-1 list-disc pl-4 flex flex-col gap-0.5">
            {assumptions.map((assumption) => (
              <li key={assumption}>{assumption}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="flex items-center gap-2 pt-1">
        <Link to={`/jobs/${proposal.runId}/build?compare=1`} className={buttonClass('secondary', 'sm')}>
          <GitCompareArrows size={13} /> Preview diff
        </Link>
        <Link to={`/jobs/${proposal.runId}/test`} className={buttonClass('primary', 'sm')}>
          Open candidate <ArrowRight size={13} />
        </Link>
      </div>
    </div>
  );
}
