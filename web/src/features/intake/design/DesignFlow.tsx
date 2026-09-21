import { Check, ChevronLeft, ChevronRight, Compass } from 'lucide-react';
import { useMemo } from 'react';
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom';

import { useCtrlFlowTemplates } from '../../../api/queries';
import { cn } from '../../../design-system/cn';
import { Button, StatusPill } from '../../../design-system/primitives';
import { EmptyState, ErrorState, LoadingState } from '../../../design-system/states';
import { DESIGN_STEPS, reachableSteps, useDesign } from '../../../stores/design';
import type { DesignStep } from '../../../stores/design';
import { BriefStep } from './steps/BriefStep';
import { CandidateStep } from './steps/CandidateStep';
import { ConfigureStep } from './steps/ConfigureStep';
import { OraclesStep } from './steps/OraclesStep';
import { PointsStep } from './steps/PointsStep';
import { PreflightStep } from './steps/PreflightStep';
import { ReviewStep } from './steps/ReviewStep';
import { SequenceStep } from './steps/SequenceStep';

const stepIds = DESIGN_STEPS.map((step) => step.id);

/** Template picker when no template is in the URL. */
function TemplatePicker() {
  const templates = useCtrlFlowTemplates();
  if (templates.isLoading) return <LoadingState label="Loading design templates" />;
  if (templates.isError) return <ErrorState error={templates.error} onRetry={() => templates.refetch()} />;
  const list = templates.data?.templates ?? [];
  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-5xl mx-auto px-6 py-8 flex flex-col gap-4">
        <div>
          <p className="eyebrow">Design</p>
          <h1 className="text-2xl font-semibold tracking-tight">Design from an LBNL system template</h1>
          <p className="text-sm text-fg-1 mt-1">
            Configure a Modelica Buildings template, reconcile the contractor's points and sequence against it, review every requirement, author independent tests, and generate a candidate.
          </p>
          {templates.data?.license && <p className="text-2xs text-fg-2 mt-1">{templates.data.source} · {templates.data.license}</p>}
        </div>
        {list.length === 0 ? (
          <EmptyState icon={<Compass size={28} strokeWidth={1.5} />} title="No design templates are installed" detail="The ctrl-flow template stack is part of the full bootstrap. Run make bootstrap-full, or create a job from documents instead." />
        ) : (
          <ul className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {list.map((template) => (
              <li key={template.id}>
                <Link to={`/intake/design/${encodeURIComponent(template.id)}/configure`} className="block panel p-4 hover:bg-bg-2">
                  <span className="block text-sm font-medium">{template.name}</span>
                  <span className="block font-mono text-2xs text-fg-2 mt-0.5 break-all">{template.id}</span>
                  <span className="mt-2 flex gap-2 flex-wrap">
                    {template.family && <StatusPill tone="neutral" icon={null}>{template.family}</StatusPill>}
                    {template.visible_option_count !== undefined && <span className="text-2xs text-fg-2 self-center">{template.visible_option_count} choices</span>}
                    {template.product_status && <StatusPill tone="info" icon={null}>{template.product_status}</StatusPill>}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/**
 * The promoted design pipeline: eight gates, each retained on the server
 * with a digest. Later gates open only when earlier ones passed.
 */
export function DesignFlow() {
  const { templateId, step } = useParams<{ templateId?: string; step?: string }>();
  const navigate = useNavigate();
  const decoded = templateId ? decodeURIComponent(templateId) : undefined;
  const state = useDesign((store) => (decoded ? store.byTemplate[decoded] : undefined));
  const reset = useDesign((store) => store.reset);
  const reachable = useMemo(() => reachableSteps(state ?? { ...useDesign.getState().get('') }), [state]);

  if (!decoded) return <TemplatePicker />;
  const current = (step ?? 'configure') as DesignStep;
  const index = stepIds.indexOf(current);
  if (index < 0) return <Navigate to={`/intake/design/${encodeURIComponent(decoded)}/configure`} replace />;
  if (!reachable.has(current)) return <Navigate to={`/intake/design/${encodeURIComponent(decoded)}/configure`} replace />;
  const previous = stepIds[index - 1];
  const next = stepIds[index + 1];

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <header className="shrink-0 bg-bg-1 hairline-b">
        <div className="max-w-6xl mx-auto px-6 h-12 flex items-center gap-3 min-w-0">
          <Link to="/intake/design" className="text-xs text-fg-2 hover:text-fg-0 shrink-0">
            Design
          </Link>
          <ChevronRight size={12} className="text-fg-2" />
          <h1 className="text-sm font-medium truncate font-mono">{decoded}</h1>
          <span className="flex-1" />
          <Button variant="ghost" size="sm" onClick={() => reset(decoded)}>
            Start over
          </Button>
        </div>
        <nav aria-label="Design steps" className="max-w-6xl mx-auto px-6 h-10 flex items-stretch gap-1 overflow-x-auto">
          {DESIGN_STEPS.map((item, i) => {
            const enabled = reachable.has(item.id);
            const done = i < index && reachable.has(stepIds[i + 1]);
            return (
              <button
                key={item.id}
                type="button"
                disabled={!enabled}
                onClick={() => navigate(`/intake/design/${encodeURIComponent(decoded)}/${item.id}`)}
                aria-current={item.id === current ? 'step' : undefined}
                className={cn('relative flex items-center gap-2 px-3 text-sm whitespace-nowrap', item.id === current ? 'text-fg-0' : enabled ? 'text-fg-1 hover:text-fg-0' : 'text-fg-2 cursor-not-allowed')}
              >
                <span className={cn('num', done && 'text-ok')}>{done ? <Check size={12} /> : i + 1}</span>
                {item.label}
                {item.id === current && <span aria-hidden className="absolute left-2 right-2 -bottom-px h-0.5 bg-accent rounded-pill" />}
              </button>
            );
          })}
        </nav>
      </header>
      <div className="flex-1 min-h-0 overflow-auto" tabIndex={0} role="region" aria-label={`${DESIGN_STEPS[index].label} step`}>
        <div className="max-w-6xl mx-auto px-6 py-6 flex flex-col gap-6">
          {current === 'configure' && <ConfigureStep templateId={decoded} />}
          {current === 'brief' && <BriefStep templateId={decoded} />}
          {current === 'points' && <PointsStep templateId={decoded} />}
          {current === 'sequence' && <SequenceStep templateId={decoded} />}
          {current === 'review' && <ReviewStep templateId={decoded} />}
          {current === 'oracles' && <OraclesStep templateId={decoded} />}
          {current === 'preflight' && <PreflightStep templateId={decoded} />}
          {current === 'candidate' && <CandidateStep templateId={decoded} />}
        </div>
      </div>
      <footer className="shrink-0 bg-bg-1 hairline-t">
        <div className="max-w-6xl mx-auto px-6 h-12 flex items-center gap-2">
          {previous ? (
            <Button variant="ghost" onClick={() => navigate(`/intake/design/${encodeURIComponent(decoded)}/${previous}`)}>
              <ChevronLeft size={14} /> Back
            </Button>
          ) : (
            <span />
          )}
          <span className="flex-1 text-xs text-fg-2">Every gate is retained with a digest. Graph generation and deployment stay blocked until the independent oracle gate passes.</span>
          {next && (
            <Button variant="primary" disabled={!reachable.has(next)} onClick={() => navigate(`/intake/design/${encodeURIComponent(decoded)}/${next}`)}>
              Continue <ChevronRight size={14} />
            </Button>
          )}
        </div>
      </footer>
    </div>
  );
}
