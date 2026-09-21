import { Boxes, Download, FolderKanban, Plus, ThumbsUp } from 'lucide-react';
import { Suspense, lazy, useCallback, useEffect, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';

import type { ProjectRecord } from '../../api/client';
import { useProject, useProjectReport, useProjects } from '../../api/queries';
import { cn } from '../../design-system/cn';
import { Button, StatusPill, buttonClass, runStatusTone } from '../../design-system/primitives';
import { EmptyState, ErrorState, LoadingState, MissingEvidence } from '../../design-system/states';
import { traceStore, useTrace } from '../../stores/trace';
import type { Signal } from '../../stores/trace';
import { useTimeCursor } from '../../stores/timeCursor';
import { useTrends } from '../../stores/trends';
import { buildProjectTrace, projectTraceId } from '../../trace/project-trace';
import { SystemMap } from '../schematic/SystemMap';
import { KeyValue, SectionCard } from '../shared/StageFrame';
import { AssertionList } from '../test/AssertionList';
import { MasterTimeline } from '../timeline/MasterTimeline';
import { Transport } from '../timeline/Transport';
import { SignalRail } from '../trends/SignalRail';
import { StateRibbon } from '../trends/StateRibbon';
import { TrendPane } from '../trends/TrendPane';
import { composeDefaultTrends } from '../trends/unit-groups';
import { ProjectApproveDialog } from './ProjectApproveDialog';
import { ProjectBuilder } from './ProjectBuilder';

const ZoneMassing = lazy(() => import('../massing/ZoneMassing').then((m) => ({ default: m.ZoneMassing })));

/** Projects: multi-equipment sites with typed relationships and signal bindings. */
export function Projects() {
  const { projectId } = useParams();
  const location = useLocation();
  const creating = location.pathname.endsWith('/projects/new');
  const projects = useProjects();

  if (projects.isLoading) return <LoadingState label="Loading projects" />;
  if (projects.isError) return <ErrorState error={projects.error} onRetry={() => projects.refetch()} />;
  const list = projects.data ?? [];

  return (
    <div className="flex-1 min-h-0 flex">
      <aside className="w-72 shrink-0 hairline-r overflow-auto bg-bg-1">
        <header className="px-4 h-11 flex items-center hairline-b gap-2">
          <h1 className="text-sm font-medium">Projects</h1>
          <span className="num text-fg-2">{list.length}</span>
          <span className="flex-1" />
          <Link to="/projects/new" className={buttonClass('outline', 'xs')} aria-label="Build a project">
            <Plus size={12} /> New
          </Link>
        </header>
        {list.length === 0 ? (
          <p className="p-4 text-sm text-fg-2">No projects yet.</p>
        ) : (
          <ul>
            {list.map((project) => {
              const status = runStatusTone(project.status);
              return (
                <li key={project.id}>
                  <Link to={`/projects/${project.id}`} className={cn('flex items-center gap-3 px-4 h-12 hairline-b hover:bg-bg-2', project.id === projectId && 'bg-bg-2')}>
                    <span className="flex-1 min-w-0">
                      <span className="block text-sm truncate">{project.project.name}</span>
                      <span className="block text-xs text-fg-2 truncate">
                        {project.project.site} · {project.project.equipment.length} equipment
                      </span>
                    </span>
                    <StatusPill tone={status.tone} icon={null}>
                      {status.label}
                    </StatusPill>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </aside>
      <div className="flex-1 min-w-0 overflow-auto">
        {creating ? (
          <ProjectBuilder />
        ) : projectId ? (
          <ProjectDetail projectId={projectId} />
        ) : (
          <EmptyState icon={<FolderKanban size={28} strokeWidth={1.5} />} title="Pick a project" detail="Each project bundles equipment candidates with typed relationships and cross-equipment signal bindings." action={<Link to="/projects/new" className={buttonClass('primary', 'sm')}>Build a project</Link>} />
        )}
      </div>
    </div>
  );
}

function ProjectDetail({ projectId }: { projectId: string }) {
  const project = useProject(projectId);
  if (project.isLoading) return <LoadingState label="Loading project" />;
  if (project.isError || !project.data) return <ErrorState error={project.error ?? 'Project not found'} onRetry={() => project.refetch()} />;
  return <ProjectCockpit data={project.data} />;
}

/**
 * The project cockpit: the system map, the project trace on the shared
 * clock (timeline, lanes, trend panes), the project acceptance assertions,
 * equipment candidates, and the project approval.
 */
function ProjectCockpit({ data }: { data: ProjectRecord }) {
  const report = useProjectReport(data.id);
  const status = runStatusTone(data.status);
  const traceId = projectTraceId(data.id);
  const trace = useTrace(traceId);
  const trends = useTrends((state) => state.byTrace[traceId]);
  const ensure = useTrends((state) => state.ensure);
  const toggleSignal = useTrends((state) => state.toggleSignal);
  const removePane = useTrends((state) => state.removePane);
  const [approving, setApproving] = useState(false);
  const [massing, setMassing] = useState(false);

  useEffect(() => {
    if (report.data && !traceStore.has(traceId)) traceStore.put(buildProjectTrace(data, report.data));
  }, [report.data, data, traceId]);
  useEffect(() => {
    if (trace && useTimeCursor.getState().traceId !== traceId) useTimeCursor.getState().setTrace(traceId);
  }, [trace, traceId]);
  useEffect(() => {
    if (trace && !trends) ensure(traceId, () => composeDefaultTrends(trace));
  }, [trace, trends, ensure, traceId]);

  const onToggle = useCallback((signal: Signal) => toggleSignal(traceId, signal.id, { kind: signal.kind, unit: signal.unit }), [toggleSignal, traceId]);
  const totals = trace ? { total: trace.assertions.length, passed: trace.assertions.filter((item) => item.passed).length } : null;

  return (
    <div className="flex flex-col min-h-full">
      <div className="max-w-6xl w-full mx-auto px-6 py-6 flex flex-col gap-4">
        <header className="flex items-center gap-3 flex-wrap">
          <h2 className="text-xl font-semibold tracking-tight">{data.project.name}</h2>
          <StatusPill tone={status.tone}>{status.label}</StatusPill>
          {trace && totals && (
            <StatusPill tone={trace.passed ? 'ok' : 'fail'}>
              {totals.passed}/{totals.total} project assertions
            </StatusPill>
          )}
          <span className="num text-fg-2">{data.artifact_sha256.slice(0, 12)}</span>
          <span className="flex-1" />
          <Button size="sm" variant={massing ? 'secondary' : 'outline'} onClick={() => setMassing(!massing)} aria-pressed={massing}>
            <Boxes size={13} /> 3D massing
          </Button>
          {data.status === 'approved' ? (
            <a className={buttonClass('primary', 'sm')} href={`/api/projects/${data.id}/export`} download>
              <Download size={13} /> Export project
            </a>
          ) : data.status === 'ready_for_review' ? (
            <Button size="sm" variant="primary" onClick={() => setApproving(true)}>
              <ThumbsUp size={13} /> Approve project
            </Button>
          ) : null}
        </header>

        <SectionCard title="System map" aside={<span className="text-2xs text-fg-2">Bindings carry live Equip.Point values from the clock · double-click equipment to open its job</span>}>
          <div className="p-3">
            <SystemMap project={data} trace={trace} />
          </div>
        </SectionCard>

        {massing && (
          <SectionCard title="Zone massing" aside={<StatusPill tone="sim">Schematic, not to scale</StatusPill>}>
            <Suspense fallback={<LoadingState compact label="Loading 3D" />}>
              <ZoneMassing project={data} trace={trace} />
            </Suspense>
          </SectionCard>
        )}

        <SectionCard title="Project evidence on the clock" aside={report.data && <StatusPill tone={report.data.passed ? 'ok' : 'fail'}>{report.data.passed ? 'project tests passed' : 'project tests failed'}</StatusPill>}>
          {report.isLoading ? (
            <LoadingState compact label="Loading project report" />
          ) : report.isError ? (
            <MissingEvidence kind="Project test" state="missing" detail="This project has no retained project test report." />
          ) : trace && trends ? (
            <div className="flex flex-col">
              <MasterTimeline trace={trace} />
              <div className="grid lg:grid-cols-[16rem_1fr] min-h-0">
                <div className="hairline-r max-h-[28rem] overflow-hidden">
                  <SignalRail trace={trace} trends={trends} onToggle={onToggle} />
                </div>
                <div className="min-w-0 max-h-[28rem] overflow-auto">
                  <StateRibbon trace={trace} signalIds={trends.ribbon} />
                  {trends.panes.map((pane) => (
                    <TrendPane key={pane.id} trace={trace} pane={pane} onRemove={() => removePane(traceId, pane.id)} />
                  ))}
                </div>
              </div>
              <Transport trace={trace} compact />
            </div>
          ) : (
            <LoadingState compact label="Building project trace" />
          )}
        </SectionCard>

        {trace && (
          <SectionCard title="Project assertions">
            <AssertionList trace={trace} />
          </SectionCard>
        )}

        <SectionCard title="Site">
          <KeyValue
            items={[
              { label: 'Site', value: data.project.site },
              { label: 'Equipment', value: <span className="num">{data.project.equipment.length}</span> },
              { label: 'Relationships', value: <span className="num">{data.project.relationships.length}</span> },
              { label: 'Signal bindings', value: <span className="num">{data.project.signal_bindings.length}</span> },
              { label: 'Station assembly', value: data.project.station_assembly_mode },
              ...(data.assembled_station_path ? [{ label: 'Assembled station', value: <span className="font-mono text-xs">{data.assembled_station_path}</span> }] : []),
              ...(data.approval ? [{ label: 'Approved', value: `${data.approval.reviewer} · ${data.approval.approved_at}` }] : []),
            ]}
          />
        </SectionCard>

        <SectionCard title="Equipment candidates">
          <ul className="divide-y divide-line-1">
            {data.equipment_runs.map((item) => {
              const tone = runStatusTone(item.status);
              return (
                <li key={item.run_id} className="flex items-center gap-3 px-4 h-10 text-sm">
                  <Link to={`/jobs/${item.run_id}/build`} className="font-mono text-xs text-accent">
                    {item.equipment_name}
                  </Link>
                  <span className="flex-1" />
                  <StatusPill tone={tone.tone}>{tone.label}</StatusPill>
                  <span className="num text-fg-2">{item.run_id.slice(0, 8)}</span>
                </li>
              );
            })}
          </ul>
        </SectionCard>

        {data.project.signal_bindings.length > 0 && (
          <SectionCard title="Signal bindings">
            <ul className="divide-y divide-line-1 font-mono text-xs">
              {data.project.signal_bindings.map((binding, index) => (
                <li key={index} className="px-4 h-9 flex items-center gap-2">
                  <span>
                    {binding.source_equipment}.{binding.source_point}
                  </span>
                  <span className="text-fg-2">→</span>
                  <span>
                    {binding.target_equipment}.{binding.target_point}
                  </span>
                </li>
              ))}
            </ul>
          </SectionCard>
        )}
      </div>
      {approving && <ProjectApproveDialog project={data} open onOpenChange={(open) => !open && setApproving(false)} />}
    </div>
  );
}
