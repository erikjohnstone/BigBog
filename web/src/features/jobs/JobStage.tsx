import { lazy, Suspense, useState } from 'react';
import { Navigate, useParams } from 'react-router-dom';
import { Group, Panel, Separator } from 'react-resizable-panels';

import { useRun } from '../../api/queries';
import { LoadingState, ErrorState } from '../../design-system/states';
import type { Stage } from '../../stores/ui';
import { useUi } from '../../stores/ui';
import { JobHeader } from './JobHeader';

const Thread = lazy(() => import('../assistant/Thread').then((m) => ({ default: m.Thread })));

const BuildStage = lazy(() => import('../wiresheet/BuildStage').then((m) => ({ default: m.BuildStage })));
const TestStage = lazy(() => import('../test/TestStage').then((m) => ({ default: m.TestStage })));
const ReviewStage = lazy(() => import('../review/ReviewStage').then((m) => ({ default: m.ReviewStage })));
const ReleaseStage = lazy(() => import('../release/ReleaseStage').then((m) => ({ default: m.ReleaseStage })));
const IntakeStage = lazy(() => import('../intake/IntakeStage').then((m) => ({ default: m.IntakeStage })));

const stages: Stage[] = ['intake', 'build', 'test', 'review', 'release'];

/**
 * `/jobs/:runId/:stage`. The header with the five-stage rail is shared; each
 * stage owns a fixed, resizable layout below it.
 */
export function JobStage() {
  const { runId, stage } = useParams<{ runId: string; stage: string }>();
  const run = useRun(runId);

  if (!runId) return <Navigate to="/jobs" replace />;
  if (!stages.includes(stage as Stage)) return <Navigate to={`/jobs/${runId}/build`} replace />;
  if (run.isLoading) return <LoadingState label="Opening job" />;
  if (run.isError || !run.data) return <ErrorState error={run.error ?? 'Job not found'} onRetry={() => run.refetch()} />;

  const current = stage as Stage;
  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <JobHeader run={run.data} stage={current} />
      <StageWithAssistant run={run.data} stage={current} />
    </div>
  );
}

function StageWithAssistant({ run, stage }: { run: NonNullable<ReturnType<typeof useRun>['data']>; stage: Stage }) {
  const assistantOpen = useUi((state) => state.assistantOpen);
  const savePanelSizes = useUi((state) => state.savePanelSizes);
  // The saved layout is read once per mount; feeding every save back in as
  // a new default would make the group report the change again, forever.
  const [initialLayout] = useState(() => useUi.getState().panelSizes.assistant ?? { stage: 72, assistant: 28 });
  const body = (
    <Suspense fallback={<LoadingState />}>
      {stage === 'intake' && <IntakeStage run={run} />}
      {stage === 'build' && <BuildStage run={run} />}
      {stage === 'test' && <TestStage run={run} />}
      {stage === 'review' && <ReviewStage run={run} />}
      {stage === 'release' && <ReleaseStage run={run} />}
    </Suspense>
  );
  if (!assistantOpen) return <div className="flex-1 min-h-0">{body}</div>;
  return (
    <Group orientation="horizontal" className="flex-1 min-h-0" defaultLayout={initialLayout} onLayoutChanged={(layout) => savePanelSizes('assistant', layout)}>
      <Panel id="stage" minSize="40" className="min-w-0">
        {body}
      </Panel>
      <Separator className="w-px bg-line-1 hover:bg-accent transition-colors" />
      <Panel id="assistant" minSize="18" className="min-w-0 hairline-l">
        <Suspense fallback={<LoadingState compact />}>
          <Thread run={run} stage={stage} />
        </Suspense>
      </Panel>
    </Group>
  );
}
