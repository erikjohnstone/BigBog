import { Command } from 'cmdk';
import { Boxes, FolderKanban, Home, Library, Sparkles, Upload } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { useProjects, useRuns } from '../api/queries';
import { cn } from '../design-system/cn';
import { Kbd, StatusPill, runStatusTone } from '../design-system/primitives';
import { useUi } from '../stores/ui';

/**
 * ⌘K palette. In `search` mode it reaches every job, project, and workspace.
 * In `agent` mode it routes a question to the AI thread of the current or
 * chosen job. It never applies a change itself.
 */
export function CommandPalette() {
  const mode = useUi((state) => state.commandMode);
  if (!mode) return null;
  // Mounted only while open, so query and list state reset on every open.
  return <Palette mode={mode} />;
}

function Palette({ mode }: { mode: 'search' | 'agent' }) {
  const close = useUi((state) => state.closeCommand);
  const setAssistantOpen = useUi((state) => state.setAssistantOpen);
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const runs = useRuns();
  const projects = useProjects();
  const runItems = useMemo(() => (runs.data ?? []).slice(0, 200), [runs.data]);

  const go = (to: string) => {
    close();
    navigate(to);
  };

  return (
    <div
      role="presentation"
      className="fixed inset-0 z-[60] flex items-start justify-center pt-[12vh] bg-black/40 backdrop-blur-[2px]"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <Command
        label={mode === 'agent' ? 'Ask BACTalk' : 'Search'}
        className="floating w-[min(720px,calc(100vw-32px))] overflow-hidden"
        onKeyDown={(event) => {
          if (event.key === 'Escape') close();
        }}
      >
        <div className="flex items-center gap-2 px-3 h-12 hairline-b">
          {mode === 'agent' ? <Sparkles size={16} className="text-accent" /> : <span className="text-fg-2">/</span>}
          <Command.Input
            autoFocus
            value={query}
            onValueChange={setQuery}
            placeholder={mode === 'agent' ? 'Ask about a job, then pick which one…' : 'Jump to a job, project, or workspace'}
            className="flex-1 bg-transparent outline-none text-sm placeholder:text-fg-2"
          />
          <Kbd>esc</Kbd>
        </div>
        <Command.List className="max-h-[52vh] overflow-auto p-1.5">
          <Command.Empty className="p-6 text-center text-sm text-fg-2">Nothing matches.</Command.Empty>

          <Command.Group heading="Workspaces" className={groupClass}>
            <Item onSelect={() => go('/')} icon={<Home size={14} />}>Home</Item>
            <Item onSelect={() => go('/jobs')} icon={<Boxes size={14} />}>Jobs</Item>
            <Item onSelect={() => go('/intake')} icon={<Upload size={14} />}>New job · intake</Item>
            <Item onSelect={() => go('/projects')} icon={<FolderKanban size={14} />}>Projects</Item>
            <Item onSelect={() => go('/libraries')} icon={<Library size={14} />}>Libraries</Item>
          </Command.Group>

          {runItems.length > 0 && (
            <Command.Group heading={mode === 'agent' ? 'Ask about a job' : 'Jobs'} className={groupClass}>
              {runItems.map((run) => {
                const status = runStatusTone(run.status);
                return (
                  <Item
                    key={run.id}
                    value={`${run.job.name} ${run.job.equipment_name} ${run.id}`}
                    icon={<Boxes size={14} />}
                    onSelect={() => {
                      if (mode === 'agent') setAssistantOpen(true);
                      go(`/jobs/${run.id}/build`);
                    }}
                    trailing={<StatusPill tone={status.tone}>{status.label}</StatusPill>}
                  >
                    <span className="truncate">{run.job.name}</span>
                    <span className="text-fg-2 text-xs truncate">
                      {run.job.equipment_name} · <span className="font-mono">{run.id.slice(0, 8)}</span>
                    </span>
                  </Item>
                );
              })}
            </Command.Group>
          )}

          {(projects.data ?? []).length > 0 && (
            <Command.Group heading="Projects" className={groupClass}>
              {(projects.data ?? []).map((project) => (
                <Item
                  key={project.id}
                  value={`${project.project.name} ${project.id}`}
                  icon={<FolderKanban size={14} />}
                  onSelect={() => go(`/projects/${project.id}`)}
                >
                  <span className="truncate">{project.project.name}</span>
                  <span className="text-fg-2 text-xs">{project.project.site}</span>
                </Item>
              ))}
            </Command.Group>
          )}
        </Command.List>
      </Command>
    </div>
  );
}

const groupClass =
  '[&_[cmdk-group-heading]]:eyebrow [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:pb-1';

function Item({
  children,
  icon,
  trailing,
  onSelect,
  value,
}: {
  children: React.ReactNode;
  icon?: React.ReactNode;
  trailing?: React.ReactNode;
  onSelect: () => void;
  value?: string;
}) {
  return (
    <Command.Item
      value={value}
      onSelect={onSelect}
      className={cn(
        'flex items-center gap-3 h-9 px-2 rounded-control text-sm cursor-default',
        'data-[selected=true]:bg-bg-2 data-[selected=true]:text-fg-0 text-fg-1',
      )}
    >
      {icon && <span className="text-fg-2 shrink-0">{icon}</span>}
      <span className="flex-1 min-w-0 flex items-center gap-2">{children}</span>
      {trailing}
    </Command.Item>
  );
}
