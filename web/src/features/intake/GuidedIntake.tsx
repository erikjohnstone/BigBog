import { Check, ChevronLeft, ChevronRight, Compass } from 'lucide-react';
import { useMemo } from 'react';
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom';

import { cn } from '../../design-system/cn';
import { Button, buttonClass } from '../../design-system/primitives';
import { INTAKE_STEPS, useIntake } from '../../stores/intake';
import type { IntakeStep } from '../../stores/intake';
import { validateStep } from './build-import-form';
import { CreateStep } from './steps/CreateStep';
import { JobStep } from './steps/JobStep';
import { NormalizeStep } from './steps/NormalizeStep';
import { SourcesStep } from './steps/SourcesStep';
import { StrategyStep } from './steps/StrategyStep';

const stepIds = INTAKE_STEPS.map((step) => step.id);

/**
 * Guided intake: Job → Sources → Normalize → Strategy → Create. The draft
 * persists across reloads (files excepted); each step validates before
 * the next opens, and the server's own validation is shown verbatim.
 */
export function GuidedIntake() {
  const { step } = useParams<{ step?: string }>();
  const navigate = useNavigate();
  const draft = useIntake((state) => state.draft);
  const files = useIntake((state) => state.files);
  const current = (step ?? 'job') as IntakeStep;
  const index = stepIds.indexOf(current);
  const errors = useMemo(() => validateStep(current, draft, files), [current, draft, files]);
  const reached = useMemo(() => {
    // A step is reachable when every earlier step validates.
    const out = new Set<IntakeStep>(['job']);
    for (let i = 1; i < stepIds.length; i += 1) {
      const previous = stepIds.slice(0, i);
      if (previous.every((id) => Object.keys(validateStep(id, draft, files)).length === 0)) out.add(stepIds[i]);
      else break;
    }
    return out;
  }, [draft, files]);

  if (index < 0) return <Navigate to="/intake/job" replace />;
  const next = stepIds[index + 1];
  const previous = stepIds[index - 1];
  const canContinue = Object.keys(errors).length === 0;

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <header className="shrink-0 bg-bg-1 hairline-b">
        <div className="max-w-5xl mx-auto px-6 h-12 flex items-center gap-3">
          <Link to="/jobs" className="text-xs text-fg-2 hover:text-fg-0">
            Jobs
          </Link>
          <ChevronRight size={12} className="text-fg-2" />
          <h1 className="text-sm font-medium">New job</h1>
          <span className="flex-1" />
          <Link to="/intake/design" className={buttonClass('ghost', 'sm')}>
            <Compass size={13} /> Design from a template instead
          </Link>
        </div>
        <nav aria-label="Intake steps" className="max-w-5xl mx-auto px-6 h-10 flex items-stretch gap-1">
          {INTAKE_STEPS.map((item, i) => {
            const done = i < index && reached.has(stepIds[i + 1] ?? item.id);
            const enabled = reached.has(item.id);
            return (
              <button
                key={item.id}
                type="button"
                disabled={!enabled}
                onClick={() => navigate(`/intake/${item.id}`)}
                aria-current={item.id === current ? 'step' : undefined}
                className={cn('relative flex items-center gap-2 px-3 text-sm', item.id === current ? 'text-fg-0' : enabled ? 'text-fg-1 hover:text-fg-0' : 'text-fg-2 cursor-not-allowed')}
              >
                <span className={cn('num', done && 'text-ok')}>{done ? <Check size={12} /> : i + 1}</span>
                {item.label}
                {item.id === current && <span aria-hidden className="absolute left-2 right-2 -bottom-px h-0.5 bg-accent rounded-pill" />}
              </button>
            );
          })}
        </nav>
      </header>

      <div className="flex-1 min-h-0 overflow-auto" tabIndex={0} role="region" aria-label={`${INTAKE_STEPS[index].label} step`}>
        <div className="max-w-5xl mx-auto px-6 py-6 flex flex-col gap-6">
          {current === 'job' && <JobStep errors={errors} />}
          {current === 'sources' && <SourcesStep errors={errors} />}
          {current === 'normalize' && <NormalizeStep />}
          {current === 'strategy' && <StrategyStep errors={errors} />}
          {current === 'create' && <CreateStep errors={errors} />}
        </div>
      </div>

      <footer className="shrink-0 bg-bg-1 hairline-t">
        <div className="max-w-5xl mx-auto px-6 h-12 flex items-center gap-2">
          {previous ? (
            <Button variant="ghost" onClick={() => navigate(`/intake/${previous}`)}>
              <ChevronLeft size={14} /> Back
            </Button>
          ) : (
            <span />
          )}
          <span className="flex-1 text-xs text-fg-2">Nothing here writes to a building. Creating a job runs typed validation and the deterministic tests.</span>
          {next && (
            <Button variant="primary" disabled={!canContinue} onClick={() => navigate(`/intake/${next}`)} title={canContinue ? undefined : Object.values(errors)[0]}>
              Continue <ChevronRight size={14} />
            </Button>
          )}
        </div>
      </footer>
    </div>
  );
}
