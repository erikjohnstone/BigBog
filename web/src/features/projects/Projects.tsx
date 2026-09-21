import { FolderKanban } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';

import type { ProjectRecord } from '../../api/client';
import { useProject, useProjects } from '../../api/queries';
import { cn } from '../../design-system/cn';
import { StatusPill, runStatusTone } from '../../design-system/primitives';
import { EmptyState, ErrorState, LoadingState } from '../../design-system/states';
import { KeyValue, SectionCard } from '../shared/StageFrame';

/** Projects: multi-equipment sites with typed relationships and signal bindings. */
export function Projects() {
  const { projectId } = useParams();
  const projects = useProjects();

  if (projects.isLoading) return <LoadingState label="Loading projects" />;
  if (projects.isError) return <ErrorState error={projects.error} onRetry={() => projects.refetch()} />;
  const list = projects.data ?? [];

  return (
    <div className="flex-1 min-h-0 flex">
      <aside className="w-72 shrink-0 hairline-r overflow-auto bg-bg-1">
        <header className="px-4 h-11 flex items-center hairline-b">
          <h1 className="text-sm font-medium">Projects</h1>
          <span className="ml-2 num text-fg-2">{list.length}</span>
        </header>
        {list.length === 0 ? (
          <p className="p-4 text-sm text-fg-2">No projects yet.</p>
        ) : (
          <ul>
            {list.map((project) => {
              const status = runStatusTone(project.status);
              return (
                <li key={project.id}>
                  <Link
                    to={`/projects/${project.id}`}
                    className={cn(
                      'flex items-center gap-3 px-4 h-12 hairline-b hover:bg-bg-2',
                      project.id === projectId && 'bg-bg-2',
                    )}
                  >
                    <span className="flex-1 min-w-0">
                      <span className="block text-sm truncate">{project.project.name}</span>
                      <span className="block text-xs text-fg-2 truncate">{project.project.site}</span>
                    </span>
                    <StatusPill tone={status.tone} icon={null}>{status.label}</StatusPill>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </aside>
      <div className="flex-1 min-w-0 overflow-auto">
        {projectId ? (
          <ProjectDetail projectId={projectId} />
        ) : (
          <EmptyState
            icon={<FolderKanban size={28} strokeWidth={1.5} />}
            title="Pick a project"
            detail="Each project bundles equipment candidates with typed relationships and cross-equipment signal bindings."
          />
        )}
      </div>
    </div>
  );
}

function ProjectDetail({ projectId }: { projectId: string }) {
  const project = useProject(projectId);
  if (project.isLoading) return <LoadingState label="Loading project" />;
  if (project.isError || !project.data) return <ErrorState error={project.error ?? 'Project not found'} onRetry={() => project.refetch()} />;
  const data: ProjectRecord = project.data;
  const status = runStatusTone(data.status);
  return (
    <div className="max-w-5xl mx-auto px-6 py-6 flex flex-col gap-4">
      <header className="flex items-center gap-3">
        <h2 className="text-xl font-semibold tracking-tight">{data.project.name}</h2>
        <StatusPill tone={status.tone}>{status.label}</StatusPill>
        <span className="num text-fg-2">{data.artifact_sha256.slice(0, 12)}</span>
      </header>
      <SectionCard title="Site">
        <KeyValue
          items={[
            { label: 'Site', value: data.project.site },
            { label: 'Equipment', value: <span className="num">{data.project.equipment.length}</span> },
            { label: 'Relationships', value: <span className="num">{data.project.relationships.length}</span> },
            { label: 'Signal bindings', value: <span className="num">{data.project.signal_bindings.length}</span> },
            { label: 'Station assembly', value: data.project.station_assembly_mode },
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
                <span>{binding.source_equipment}.{binding.source_point}</span>
                <span className="text-fg-2">→</span>
                <span>{binding.target_equipment}.{binding.target_point}</span>
              </li>
            ))}
          </ul>
        </SectionCard>
      )}
    </div>
  );
}
