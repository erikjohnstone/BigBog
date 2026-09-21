import { Check, ChevronRight, Sparkles, X } from 'lucide-react';
import { Link, NavLink } from 'react-router-dom';

import type { RunDetail } from '../../api/client';
import { cn } from '../../design-system/cn';
import { Button, Dot, StatusPill, runStatusTone } from '../../design-system/primitives';
import type { Tone } from '../../design-system/primitives';
import type { Stage } from '../../stores/ui';
import { useUi } from '../../stores/ui';

interface StageState {
  id: Stage;
  label: string;
  tone: Tone;
  hint: string;
}

/**
 * Derive each stage's state from the server record alone. Nothing here is
 * inferred from client state, so the rail always agrees with the backend.
 */
export function deriveStages(run: RunDetail): StageState[] {
  const pointsComplete = run.job.points.length > 0;
  const graphPresent = Boolean(run.graph_path);
  const report = run.report_passed;
  const status = run.status;
  return [
    {
      id: 'intake',
      label: 'Intake',
      tone: pointsComplete ? 'ok' : 'warn',
      hint: pointsComplete ? `${run.job.points.length} points normalized` : 'Points incomplete',
    },
    {
      id: 'build',
      label: 'Build',
      tone: graphPresent ? 'ok' : 'neutral',
      hint: graphPresent ? 'Typed control graph retained' : 'No graph yet',
    },
    {
      id: 'test',
      label: 'Test',
      tone: report === true ? 'ok' : report === false ? 'fail' : 'neutral',
      hint: report === true ? 'Deterministic tests passed' : report === false ? 'Deterministic tests failed' : 'Not tested',
    },
    {
      id: 'review',
      label: 'Review',
      tone: status === 'approved' ? 'ok' : status === 'rejected' ? 'warn' : status === 'ready_for_review' ? 'info' : 'neutral',
      hint:
        status === 'approved'
          ? `Approved by ${run.approval?.reviewer ?? 'reviewer'}`
          : status === 'rejected'
            ? 'Rejected'
            : status === 'ready_for_review'
              ? 'Awaiting a named engineer'
              : 'Not reviewable',
    },
    {
      id: 'release',
      label: 'Release',
      tone: status === 'approved' ? 'ok' : 'neutral',
      hint: status === 'approved' ? 'Approved artifact exportable' : 'Export locked until approval',
    },
  ];
}

export function JobHeader({ run, stage }: { run: RunDetail; stage: Stage }) {
  const toggleAssistant = useUi((state) => state.toggleAssistant);
  const status = runStatusTone(run.status);
  const stages = deriveStages(run);

  return (
    <header className="shrink-0 bg-bg-1 hairline-b">
      <div className="flex items-center gap-3 px-4 h-11">
        <Link to="/jobs" className="text-xs text-fg-2 hover:text-fg-0">
          Jobs
        </Link>
        <ChevronRight size={12} className="text-fg-2" />
        <h1 className="text-sm font-medium truncate">{run.job.name}</h1>
        <span className="text-xs text-fg-2 truncate hidden md:inline">
          {run.job.site} · <span className="font-mono">{run.job.equipment_name}</span> · {run.job.sequence.family}
        </span>
        <div className="flex-1" />
        {run.origin === 'ai_proposal' && run.parent_run_id && (
          <Link to={`/jobs/${run.parent_run_id}/build`}>
            <StatusPill tone="sim">AI proposal · from {run.parent_run_id.slice(0, 8)}</StatusPill>
          </Link>
        )}
        <StatusPill tone={status.tone}>{status.label}</StatusPill>
        <span className="num text-fg-2" title={run.artifact_sha256}>
          {run.artifact_sha256.slice(0, 12)}
        </span>
        <Button variant="outline" size="sm" onClick={toggleAssistant}>
          <Sparkles size={14} /> Assistant
        </Button>
      </div>

      <nav aria-label="Job stages" className="flex items-stretch px-2 h-10 gap-1">
        {stages.map((item, index) => (
          <NavLink
            key={item.id}
            to={`/jobs/${run.id}/${item.id}`}
            title={item.hint}
            className={({ isActive }) =>
              cn(
                'relative flex items-center gap-2 px-3 text-sm rounded-t-control',
                isActive ? 'text-fg-0' : 'text-fg-1 hover:text-fg-0',
              )
            }
          >
            {({ isActive }) => (
              <>
                <span className="num text-fg-2">{index + 1}</span>
                <span>{item.label}</span>
                <StageMark tone={item.tone} />
                {isActive && <span aria-hidden className="absolute left-2 right-2 -bottom-px h-0.5 bg-accent rounded-pill" />}
                <span className="sr-only">{item.hint}</span>
              </>
            )}
          </NavLink>
        ))}
        <span className="flex-1" />
        <span className="self-center text-2xs text-fg-2 pr-2 hidden lg:inline">
          Stage {stages.findIndex((item) => item.id === stage) + 1} of 5
        </span>
      </nav>
    </header>
  );
}

function StageMark({ tone }: { tone: Tone }) {
  if (tone === 'ok') return <Check size={12} className="text-ok" aria-hidden />;
  if (tone === 'fail') return <X size={12} className="text-fail" aria-hidden />;
  return <Dot tone={tone} />;
}
