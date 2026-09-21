import { Link } from 'react-router-dom';

import { useRuns } from '../../api/queries';
import { StatusPill } from '../../design-system/primitives';
import { EmptyState, ErrorState, LoadingState } from '../../design-system/states';
import { SectionCard, StageFrame } from '../shared/StageFrame';

/**
 * Connections: every isolated BACnet lab retained for a candidate. Nothing
 * here can reach a live network; the device grid and probe come in Phase 9.
 */
export function Connections() {
  const runs = useRuns();
  if (runs.isLoading) return <LoadingState label="Loading connections" />;
  if (runs.isError) return <ErrorState error={runs.error} onRetry={() => runs.refetch()} />;
  const labs = (runs.data ?? []).filter((run) => run.bacnet_lab_manifest_path);

  return (
    <StageFrame>
      <header>
        <p className="eyebrow">Isolated loopback only</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Connections</h1>
        <p className="mt-2 text-sm text-fg-1">
          Every BACnet device here is virtual and bound to loopback. Approval never enables live writes.
        </p>
      </header>
      {labs.length === 0 ? (
        <EmptyState title="No BACnet labs retained" detail="Candidates with BACnet-mapped points retain a virtual lab manifest." />
      ) : (
        <SectionCard title="Virtual BACnet labs">
          <ul className="divide-y divide-line-1">
            {labs.map((run) => (
              <li key={run.id} className="flex items-center gap-3 px-4 h-11 text-sm">
                <Link to={`/jobs/${run.id}/test`} className="flex-1 min-w-0">
                  <span className="block truncate">{run.job.name}</span>
                  <span className="block text-xs text-fg-2 font-mono">{run.job.equipment_name}</span>
                </Link>
                <StatusPill tone="sim">virtual</StatusPill>
                <span className="num text-fg-2">{run.id.slice(0, 8)}</span>
              </li>
            ))}
          </ul>
        </SectionCard>
      )}
    </StageFrame>
  );
}
