import { ArrowRight, Boxes, FlaskConical, ShieldCheck, Upload } from 'lucide-react';
import { Link } from 'react-router-dom';

import { useReadiness, useRuns } from '../../api/queries';
import { buttonClass, StatusPill, runStatusTone } from '../../design-system/primitives';
import { ErrorState, LoadingState } from '../../design-system/states';

/**
 * Home is a work queue, not a dashboard: what needs review, what failed, what
 * shipped, and where the toolchain stands. No metric here is decorative.
 */
export function Home() {
  const runs = useRuns();
  const readiness = useReadiness();

  if (runs.isLoading) return <LoadingState label="Loading jobs" />;
  if (runs.isError) return <ErrorState error={runs.error} onRetry={() => runs.refetch()} />;

  const all = runs.data ?? [];
  const review = all.filter((run) => run.status === 'ready_for_review');
  const failed = all.filter((run) => run.status === 'failed');
  const approved = all.filter((run) => run.status === 'approved');
  const selected = (readiness.data?.components ?? []).filter((component) => component.selected);
  const productWired = selected.filter((component) =>
    ['product-wired', 'target-compiled', 'bog-simulated', 'verified', 'field-qualified', 'production-supported'].includes(component.stage),
  );

  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-6xl mx-auto px-6 py-8 flex flex-col gap-8">
        <header className="flex items-end justify-between gap-6 flex-wrap">
          <div>
            <p className="eyebrow">Controls programming workbench</p>
            <h1 className="mt-1 text-3xl font-semibold tracking-tight">Program, test, and release building controls.</h1>
            <p className="mt-2 text-sm text-fg-1 max-w-2xl">
              Every candidate is built from a typed control graph, simulated before anyone sees it, and approved
              against one exact digest. Nothing here writes to a live building.
            </p>
          </div>
          <div className="flex gap-2">
            <Link to="/intake" className={buttonClass('primary', 'lg')}>
              <Upload size={16} /> New job
            </Link>
          </div>
        </header>

        <section className="grid grid-cols-1 sm:grid-cols-3 gap-3" aria-label="Queues">
          <Metric to="/jobs?facet=ready_for_review" label="Awaiting review" value={review.length} tone="info" icon={<ShieldCheck size={16} />} />
          <Metric to="/jobs?facet=failed" label="Failed candidates" value={failed.length} tone="fail" icon={<FlaskConical size={16} />} />
          <Metric to="/jobs?facet=approved" label="Approved" value={approved.length} tone="ok" icon={<Boxes size={16} />} />
        </section>

        <section className="panel">
          <header className="flex items-center justify-between px-4 h-11 hairline-b">
            <h2 className="text-sm font-medium">Review queue</h2>
            <Link to="/jobs" className="text-xs text-accent inline-flex items-center gap-1">
              All jobs <ArrowRight size={12} />
            </Link>
          </header>
          {review.length === 0 ? (
            <p className="p-6 text-sm text-fg-2">Nothing is waiting for an engineer.</p>
          ) : (
            <ul className="divide-y divide-line-1">
              {review.slice(0, 8).map((run) => {
                const status = runStatusTone(run.status);
                return (
                  <li key={run.id}>
                    <Link to={`/jobs/${run.id}/review`} className="flex items-center gap-4 px-4 h-12 hover:bg-bg-2">
                      <span className="flex-1 min-w-0">
                        <span className="block text-sm truncate">{run.job.name}</span>
                        <span className="block text-xs text-fg-2 truncate">
                          {run.job.site} · {run.job.equipment_name} · {run.job.sequence.family}
                        </span>
                      </span>
                      {run.origin === 'ai_proposal' && <StatusPill tone="sim">AI proposal</StatusPill>}
                      <StatusPill tone={status.tone}>{status.label}</StatusPill>
                      <span className="num text-fg-2">{run.id.slice(0, 8)}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section className="panel">
          <header className="flex items-center justify-between px-4 h-11 hairline-b">
            <h2 className="text-sm font-medium">Toolchain maturity</h2>
            <Link to="/admin" className="text-xs text-accent inline-flex items-center gap-1">
              Administration <ArrowRight size={12} />
            </Link>
          </header>
          <div className="p-4 flex flex-col gap-3">
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-semibold num">{productWired.length}</span>
              <span className="text-sm text-fg-1">of {selected.length} selected integrations are product-wired or beyond</span>
            </div>
            <MaturityStrip stages={readiness.data?.stage_order ?? []} components={selected} />
            <p className="text-xs text-fg-2">
              Installed is not supported. No integration is marked field-qualified or production-supported until a
              licensed runtime proves it.
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}

function Metric({
  to,
  label,
  value,
  tone,
  icon,
}: {
  to: string;
  label: string;
  value: number;
  tone: 'info' | 'fail' | 'ok';
  icon: React.ReactNode;
}) {
  const color = tone === 'info' ? 'text-accent' : tone === 'fail' ? 'text-fail' : 'text-ok';
  return (
    <Link to={to} className="panel p-4 flex items-center gap-4 hover:bg-bg-2 transition-colors">
      <span className={`shrink-0 ${color}`}>{icon}</span>
      <span className="flex-1">
        <span className="block text-2xl font-semibold num leading-none">{value}</span>
        <span className="block mt-1 text-xs text-fg-1">{label}</span>
      </span>
      <ArrowRight size={14} className="text-fg-2" />
    </Link>
  );
}

function MaturityStrip({
  stages,
  components,
}: {
  stages: string[];
  components: Array<{ stage: string }>;
}) {
  if (stages.length === 0) return null;
  const counts = stages.map((stage) => components.filter((component) => component.stage === stage).length);
  return (
    <ol className="grid gap-1" style={{ gridTemplateColumns: `repeat(${stages.length}, minmax(0, 1fr))` }} aria-label="Maturity stages">
      {stages.map((stage, index) => (
        <li key={stage} className="flex flex-col gap-1">
          <div
            className="h-1.5 rounded-pill"
            style={{
              background:
                counts[index] > 0
                  ? index >= stages.indexOf('verified')
                    ? 'var(--ok)'
                    : 'var(--accent)'
                  : 'var(--line-1)',
            }}
          />
          <span className="text-2xs text-fg-2 truncate">
            {stage.replaceAll('-', ' ')} <span className="num">{counts[index]}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}
