import { Check, X } from 'lucide-react';

import type { RunDetail } from '../../api/client';
import { cn } from '../../design-system/cn';

/** The coding model's iterations that produced this candidate, in order. */
export function AttemptsTimeline({ attempts }: { attempts: RunDetail['agent_attempts'] }) {
  if (attempts.length === 0) return null;
  return (
    <section className="px-3 py-2 hairline-b" aria-label="Agent attempts">
      <h3 className="eyebrow mb-1.5">Coding attempts</h3>
      <ol className="flex items-center gap-1 flex-wrap">
        {attempts.map((attempt) => {
          const failures = attempt.failed_assertions?.length ?? 0;
          return (
            <li
              key={attempt.iteration}
              className={cn('inline-flex items-center gap-1 h-6 px-1.5 rounded-chip border text-2xs num', attempt.passed ? 'border-ok/40 text-ok bg-ok-soft' : 'border-fail/40 text-fail bg-fail-soft')}
              title={attempt.passed ? `Iteration ${attempt.iteration} passed` : `Iteration ${attempt.iteration} failed ${failures} assertions`}
            >
              {attempt.passed ? <Check size={11} /> : <X size={11} />}
              #{attempt.iteration}
              {!attempt.passed && failures > 0 && <span className="text-fg-2">·{failures}</span>}
            </li>
          );
        })}
      </ol>
      <p className="mt-1 text-2xs text-fg-2">Each iteration was validated, compiled, and tested by BACTalk before the next; the model never marked its own work passed.</p>
    </section>
  );
}
