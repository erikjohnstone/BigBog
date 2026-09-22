import { Suspense, lazy } from 'react';
import { Navigate, Route, Routes, useParams } from 'react-router-dom';

import { AppErrorBoundary } from './AppErrorBoundary';
import { LoadingState } from '../design-system/states';
import { Shell } from '../shell/Shell';
import { usePlaybackLoop } from '../stores/playback';

const Home = lazy(() => import('../features/home/Home').then((m) => ({ default: m.Home })));
const JobList = lazy(() => import('../features/jobs/JobList').then((m) => ({ default: m.JobList })));
const JobStage = lazy(() => import('../features/jobs/JobStage').then((m) => ({ default: m.JobStage })));
const GuidedIntake = lazy(() => import('../features/intake/GuidedIntake').then((m) => ({ default: m.GuidedIntake })));
const DesignFlow = lazy(() => import('../features/intake/design/DesignFlow').then((m) => ({ default: m.DesignFlow })));
const Projects = lazy(() => import('../features/projects/Projects').then((m) => ({ default: m.Projects })));
const Libraries = lazy(() => import('../features/libraries/Libraries').then((m) => ({ default: m.Libraries })));
const Requirements = lazy(() => import('../features/libraries/Requirements').then((m) => ({ default: m.Requirements })));
const Connections = lazy(() => import('../features/connections/Connections').then((m) => ({ default: m.Connections })));
const Admin = lazy(() => import('../features/admin/Admin').then((m) => ({ default: m.Admin })));

/** Old `/studio/:id/:view` links map onto the five-stage model. */
function LegacyStudioRedirect() {
  const { runId, view } = useParams();
  const stage =
    view === 'tests' ? 'test' : view === 'simulation' ? 'test' : view === 'review' ? 'review' : view === 'graphics' ? 'test' : 'build';
  return <Navigate to={`/jobs/${runId}/${stage}`} replace />;
}

export function App() {
  usePlaybackLoop();
  return (
    <Shell>
      <AppErrorBoundary scope="This page">
        <Suspense fallback={<LoadingState />}>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/jobs" element={<JobList />} />
            <Route path="/jobs/:runId" element={<JobStageIndexRedirect />} />
            <Route path="/jobs/:runId/:stage" element={<JobStage />} />
            <Route path="/intake" element={<GuidedIntake />} />
            <Route path="/intake/design" element={<DesignFlow />} />
            <Route path="/intake/design/:templateId" element={<DesignFlow />} />
            <Route path="/intake/design/:templateId/:step" element={<DesignFlow />} />
            <Route path="/intake/:step" element={<GuidedIntake />} />
            <Route path="/projects" element={<Projects />} />
            <Route path="/projects/:projectId" element={<Projects />} />
            <Route path="/projects/new" element={<Projects />} />
            <Route path="/libraries" element={<Libraries />} />
            <Route path="/libraries/requirements" element={<Requirements />} />
            <Route path="/libraries/requirements/:sequenceId" element={<Requirements />} />
            <Route path="/connections" element={<Connections />} />
            <Route path="/environments" element={<Navigate to="/connections" replace />} />
            <Route path="/admin" element={<Admin />} />
            <Route path="/system" element={<Navigate to="/admin" replace />} />
            {/* legacy routes */}
            <Route path="/studio" element={<Navigate to="/jobs" replace />} />
            <Route path="/studio/:runId" element={<LegacyStudioRedirect />} />
            <Route path="/studio/:runId/:view" element={<LegacyStudioRedirect />} />
            <Route path="/simulations" element={<Navigate to="/jobs?facet=qualification" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </AppErrorBoundary>
    </Shell>
  );
}

function JobStageIndexRedirect() {
  const { runId } = useParams();
  return <Navigate to={`/jobs/${runId}/build`} replace />;
}
