import { lazy, Suspense, useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  Blocks,
  Bot,
  Box,
  Building2,
  Cable,
  ChevronRight,
  CircleAlert,
  Command,
  FileCheck2,
  FlaskConical,
  Gauge,
  Library,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom';

import { api, type RunSummary } from '../api/client';
import { CommandCenter, type CommandMode } from './CommandCenter';

const ControlStudio = lazy(() => import('../features/control-studio/ControlStudio').then((module) => ({ default: module.ControlStudio })));
const IntakeStudio = lazy(() => import('../features/intake/IntakeStudio').then((module) => ({ default: module.IntakeStudio })));
const ProjectIntake = lazy(() => import('../features/projects/ProjectIntake').then((module) => ({ default: module.ProjectIntake })));
const ProjectWorkspace = lazy(() => import('../features/projects/ProjectWorkspace').then((module) => ({ default: module.ProjectWorkspace })));
const StudioIndex = lazy(() => import('../features/workspaces/WorkspacePages').then((module) => ({ default: module.StudioIndex })));
const SimulationIndex = lazy(() => import('../features/workspaces/WorkspacePages').then((module) => ({ default: module.SimulationIndex })));
const LibraryWorkspace = lazy(() => import('../features/workspaces/WorkspacePages').then((module) => ({ default: module.LibraryWorkspace })));
const EnvironmentWorkspace = lazy(() => import('../features/workspaces/WorkspacePages').then((module) => ({ default: module.EnvironmentWorkspace })));
const SystemWorkspace = lazy(() => import('../features/workspaces/WorkspacePages').then((module) => ({ default: module.SystemWorkspace })));

const nav = [
  { label: 'Home', icon: Gauge, to: '/' },
  { label: 'Projects', icon: Building2, to: '/projects' },
  { label: 'Studio', icon: Blocks, to: '/studio' },
  { label: 'Simulations', icon: FlaskConical, to: '/simulations' },
  { label: 'Libraries', icon: Library, to: '/libraries' },
  { label: 'Connections', icon: Cable, to: '/environments' },
];

const statusCopy: Record<RunSummary['status'], string> = {
  failed: 'Failed',
  ready_for_review: 'Ready for review',
  approved: 'Approved',
  rejected: 'Rejected',
};

function ProductShell() {
  const location = useLocation();
  const [commandMode, setCommandMode] = useState<CommandMode | null>(null);

  useEffect(() => {
    const openSearch = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setCommandMode('search');
      }
    };
    window.addEventListener('keydown', openSearch);
    return () => window.removeEventListener('keydown', openSearch);
  }, []);

  return (
    <div className="product-shell">
      <aside className="rail" aria-label="Primary navigation">
        <a className="brand" href="/next/" aria-label="BACTalk home">
          <span className="brand-symbol" aria-hidden="true"><i /><i /><i /></span>
          <span><strong>BACTalk</strong><small>Engineering OS</small></span>
        </a>
        <nav className="primary-nav">
          {nav.map(({ label, icon: Icon, to }) => {
            const active = to === '/' ? location.pathname === '/' : location.pathname.startsWith(to);
            return (
            <Link aria-label={label} className={active ? 'nav-link active' : 'nav-link'} key={label} to={to}>
              <Icon aria-hidden="true" size={18} />
              <span>{label}</span>
            </Link>
          );})}
        </nav>
        <div className="environment-card">
          <div><ShieldCheck size={16} aria-hidden="true" /><strong>Offline engineering</strong></div>
          <span>No live building writes</span>
        </div>
        <Link aria-label="Administration" className={location.pathname.startsWith('/system') ? 'nav-link active' : 'nav-link'} to="/system"><Settings aria-hidden="true" size={18} /><span>Administration</span></Link>
      </aside>
      <div className="application">
        <header className="global-header">
          <button className="organization-switcher" type="button">
            <Box size={17} aria-hidden="true" />
            <span><small>Workspace</small>Contractor sandbox</span>
            <ChevronRight size={15} aria-hidden="true" />
          </button>
          <button className="command-search" onClick={() => setCommandMode('search')} type="button">
            <Search size={17} aria-hidden="true" />
            <span>Search projects, points, equipment, and runs</span>
            <kbd><Command size={12} /> K</kbd>
          </button>
          <button className="agent-button" onClick={() => setCommandMode('agent')} type="button"><Sparkles size={17} />Ask BACTalk</button>
        </header>
        <main className="main-content">
          <Routes>
            <Route path="/" element={<Home onOpenAgent={() => setCommandMode('agent')} />} />
            <Route path="/intake" element={<Suspense fallback={<div className="route-loading">Opening contractor intake…</div>}><IntakeStudio /></Suspense>} />
            <Route path="/projects/new" element={<Suspense fallback={<div className="route-loading">Opening building project intake…</div>}><ProjectIntake /></Suspense>} />
            <Route path="/projects/:projectId?" element={<Suspense fallback={<div className="route-loading">Opening building projects…</div>}><ProjectWorkspace /></Suspense>} />
            <Route path="/studio" element={<Suspense fallback={<div className="route-loading">Opening Control Studio…</div>}><StudioIndex /></Suspense>} />
            <Route path="/studio/:runId/:view?" element={<Suspense fallback={<div className="route-loading">Opening Control Studio…</div>}><ControlStudio /></Suspense>} />
            <Route path="/simulations" element={<Suspense fallback={<div className="route-loading">Opening simulation evidence…</div>}><SimulationIndex /></Suspense>} />
            <Route path="/libraries" element={<Suspense fallback={<div className="route-loading">Indexing installed controls libraries…</div>}><LibraryWorkspace /></Suspense>} />
            <Route path="/environments" element={<Suspense fallback={<div className="route-loading">Opening contractor environments…</div>}><EnvironmentWorkspace /></Suspense>} />
            <Route path="/system" element={<Suspense fallback={<div className="route-loading">Loading production controls…</div>}><SystemWorkspace /></Suspense>} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
      {commandMode && <CommandCenter mode={commandMode} onClose={() => setCommandMode(null)} />}
    </div>
  );
}

function Home({ onOpenAgent }: { onOpenAgent: () => void }) {
  const health = useQuery({ queryKey: ['health'], queryFn: api.health });
  const runs = useQuery({ queryKey: ['runs'], queryFn: api.runs });
  const readiness = useQuery({ queryKey: ['readiness'], queryFn: api.readiness });
  const reviewRuns = (runs.data ?? []).filter((run) => run.status === 'ready_for_review');
  const activeComponents = readiness.data?.components.filter((item) => item.selected) ?? [];
  const wired = activeComponents.filter((item) =>
    ['product-wired', 'target-compiled', 'verified', 'field-qualified', 'production-supported'].includes(item.stage),
  ).length;

  return (
    <div className="home-page">
      <section className="page-heading">
        <div>
          <span className="eyebrow">ENGINEERING COMMAND CENTER</span>
          <h1>Good morning. What are we building?</h1>
          <p>Move contractor jobs from raw documents to tested, reviewable Niagara deliverables.</p>
        </div>
        <Link className="primary-action" to="/intake"><Sparkles size={18} />Start a contractor job</Link>
      </section>

      <section className="workflow-rail" aria-label="Programming workflow">
        {['Intake', 'Build', 'Test', 'Review', 'Release'].map((label, index) => (
          <div className={index === 0 ? 'workflow-step active' : 'workflow-step'} key={label}>
            <span>{index + 1}</span><strong>{label}</strong>
            {index < 4 && <ChevronRight aria-hidden="true" size={16} />}
          </div>
        ))}
      </section>

      {(health.isError || runs.isError || readiness.isError) && (
        <div className="system-error" role="alert"><CircleAlert size={18} />The workbench API could not be loaded.</div>
      )}

      <section className="metrics-grid" aria-label="Workspace summary">
        <Metric label="Jobs awaiting review" value={String(reviewRuns.length)} detail="Human decision required" tone="amber" />
        <Metric label="Recent programming runs" value={String(runs.data?.length ?? '—')} detail="Across this workspace" />
        <Metric label="Integration coverage" value={activeComponents.length ? `${wired}/${activeComponents.length}` : '—'} detail="Product-wired or beyond" />
        <Metric label="Runtime boundary" value={health.data?.mode === 'offline-safe' ? 'Offline' : 'Unknown'} detail="No live building writes" tone="green" />
      </section>

      <div className="content-grid">
        <section className="surface work-queue">
          <div className="surface-header">
            <div><span className="eyebrow">YOUR WORK</span><h2>Needs attention</h2></div>
            <Link className="text-button" to="/studio">View all</Link>
          </div>
          {runs.isLoading ? <LoadingRows /> : reviewRuns.length ? (
            <div className="queue-list">
              {reviewRuns.slice(0, 6).map((run) => <RunRow run={run} key={run.id} />)}
            </div>
          ) : (
            <div className="empty-message"><FileCheck2 size={24} /><strong>No reviews waiting</strong><span>New tested candidates will appear here.</span></div>
          )}
        </section>

        <aside className="side-column">
          <section className="surface agent-card">
            <div className="agent-orb"><Bot size={22} /></div>
            <span className="eyebrow">AI CONTROLS ENGINEER</span>
            <h2>Start with the job, not the tool.</h2>
            <p>Upload a point list and sequence. BACTalk will map the scope, expose assumptions, build a candidate, and prove what it can.</p>
            <button className="secondary-action" onClick={onOpenAgent} type="button">Open agent workspace<ChevronRight size={16} /></button>
          </section>
          <section className="surface capability-card">
            <div className="surface-header compact"><div><span className="eyebrow">RELEASE POSTURE</span><h2>Evidence, not optimism</h2></div><Activity size={19} /></div>
            <p>{readiness.data?.production_ready ? 'All selected components are qualified.' : 'Production blockers remain visible and enforceable.'}</p>
            <div className="readiness-meter"><i style={{ width: activeComponents.length ? `${(wired / activeComponents.length) * 100}%` : '0%' }} /></div>
            <span>{wired} of {activeComponents.length} selected components product-wired or beyond</span>
          </section>
        </aside>
      </div>
    </div>
  );
}

function Metric({ label, value, detail, tone = 'neutral' }: { label: string; value: string; detail: string; tone?: string }) {
  return <article className={`metric-card ${tone}`}><span>{label}</span><strong>{value}</strong><small>{detail}</small></article>;
}

function RunRow({ run }: { run: RunSummary }) {
  return (
    <Link className="run-row" to={`/studio/${run.id}`}>
      <div className="run-icon"><Blocks size={18} /></div>
      <div className="run-copy"><strong>{run.job.name}</strong><span>{run.job.site} · {run.job.equipment_name}</span></div>
      <div className="run-sequence"><span>Sequence</span><strong>{run.job.sequence.family.replaceAll('_', ' ')}</strong></div>
      <span className={`status-badge ${run.status}`}>{statusCopy[run.status]}</span>
      <ChevronRight size={17} aria-hidden="true" />
    </Link>
  );
}

function LoadingRows() {
  return <div className="loading-rows" aria-label="Loading work queue" role="status"><i /><i /><i /></div>;
}

export function App() {
  return <ProductShell />;
}
