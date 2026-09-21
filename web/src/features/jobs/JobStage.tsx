import { lazy, Suspense } from 'react';
import { Navigate, useParams } from 'react-router-dom';

import { useRun } from '../../api/queries';
import { LoadingState, ErrorState } from '../../design-system/states';
import type { Stage } from '../../stores/ui';
import { JobHeader } from './JobHeader';

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
      <div className="flex-1 min-h-0">
        <Suspense fallback={<LoadingState />}>
          {current === 'intake' && <IntakeStage run={run.data} />}
          {current === 'build' && <BuildStage run={run.data} />}
          {current === 'test' && <TestStage run={run.data} />}
          {current === 'review' && <ReviewStage run={run.data} />}
          {current === 'release' && <ReleaseStage run={run.data} />}
        </Suspense>
      </div>
    </div>
  );
}
