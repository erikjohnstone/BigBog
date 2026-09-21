import { ChevronDown, ChevronRight, Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import type { RunSummary } from '../../api/client';
import { useBacnetLab, useRuns } from '../../api/queries';
import { Input, StatusPill } from '../../design-system/primitives';
import { EmptyState, ErrorState, LoadingState } from '../../design-system/states';
import { SectionCard, StageFrame } from '../shared/StageFrame';
import { BacnetLabCard } from '../simulation/BacnetLabCard';

function PointGrid({ runId, equipment }: { runId: string; equipment: string }) {
  const lab = useBacnetLab(runId);
  const [query, setQuery] = useState('');
  const points = useMemo(() => {
    if (lab.data?.state !== 'available') return [];
    const needle = query.trim().toLowerCase();
    return Object.entries(lab.data.data.point_index)
      .map(([name, point]) => ({ name, ...point }))
      .filter((point) => !needle || `${point.name} ${point.object_identifier} ${point.data_type}`.toLowerCase().includes(needle))
      .sort((a, b) => a.device_instance - b.device_instance || a.name.localeCompare(b.name));
  }, [lab.data, query]);
  if (lab.data?.state !== 'available') return null;
  return (
    <div className="hairline-t">
      <div className="px-4 h-9 flex items-center gap-2">
        <span className="eyebrow">Points</span>
        <span className="num text-2xs text-fg-2">{points.length}</span>
        <span className="flex-1" />
        <span className="relative">
          <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-fg-2" aria-hidden />
          <Input aria-label="Filter points" className="pl-6 h-7 text-xs w-52" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter points" />
        </span>
      </div>
      <div className="overflow-auto max-h-80 outline-none focus-visible:[box-shadow:inset_0_0_0_2px_var(--accent)]" tabIndex={0} role="region" aria-label={`${equipment} lab points`}>
        <table className="w-full text-xs">
          <thead className="text-left sticky top-0 bg-bg-1">
            <tr className="hairline-b">
              <th className="eyebrow px-4 h-8 font-semibold">Point</th>
              <th className="eyebrow px-4 h-8 font-semibold">Device</th>
              <th className="eyebrow px-4 h-8 font-semibold">Object</th>
              <th className="eyebrow px-4 h-8 font-semibold">Type</th>
              <th className="eyebrow px-4 h-8 font-semibold">Lab role</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line-1">
            {points.map((point) => (
              <tr key={`${point.device_instance}:${point.name}`}>
                <td className="px-4 py-1.5 font-mono text-fg-0">{point.name}</td>
                <td className="px-4 py-1.5 num text-fg-1">
                  {point.device_instance} <span className="text-fg-2">{point.network_address}</span>
                </td>
                <td className="px-4 py-1.5 font-mono text-fg-1">{point.object_identifier}</td>
                <td className="px-4 py-1.5 text-fg-1">{point.data_type}</td>
                <td className="px-4 py-1.5">
                  <span className="inline-flex gap-1">
                    {point.scenario_injectable && <StatusPill tone="sim" icon={null}>injectable</StatusPill>}
                    {point.command_capture && <StatusPill tone="info" icon={null}>command capture</StatusPill>}
                    {!point.scenario_injectable && !point.command_capture && <span className="text-fg-2">read only</span>}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function LabRow({ run, open, onToggle }: { run: RunSummary; open: boolean; onToggle: () => void }) {
  return (
    <li>
      <div className="flex items-center gap-3 px-4 h-11 text-sm">
        <button type="button" className="inline-flex items-center gap-2 flex-1 min-w-0 text-left" onClick={onToggle} aria-expanded={open} aria-controls={`lab-${run.id}`}>
          {open ? <ChevronDown size={14} className="text-fg-2 shrink-0" /> : <ChevronRight size={14} className="text-fg-2 shrink-0" />}
          <span className="min-w-0">
            <span className="block truncate">{run.job.name}</span>
            <span className="block text-xs text-fg-2 font-mono">{run.job.equipment_name}</span>
          </span>
        </button>
        <StatusPill tone="sim">virtual</StatusPill>
        <Link to={`/jobs/${run.id}/test`} className="text-xs text-accent whitespace-nowrap">
          Open job
        </Link>
        <span className="num text-fg-2">{run.id.slice(0, 8)}</span>
      </div>
      {open && (
        <div id={`lab-${run.id}`} className="hairline-t bg-bg-0/40">
          <BacnetLabCard runId={run.id} />
          <PointGrid runId={run.id} equipment={run.job.equipment_name} />
        </div>
      )}
    </li>
  );
}

/**
 * Connections: every isolated BACnet lab retained for a candidate, with its
 * devices, the point grid (injectable and command-capture points marked),
 * and a probe through the independent protocol oracle. Nothing here can
 * reach a live network.
 */
export function Connections() {
  const runs = useRuns();
  const [open, setOpen] = useState<string | null>(null);
  if (runs.isLoading) return <LoadingState label="Loading connections" />;
  if (runs.isError) return <ErrorState error={runs.error} onRetry={() => runs.refetch()} />;
  const labs = (runs.data ?? []).filter((run) => run.bacnet_lab_manifest_path);

  return (
    <StageFrame wide>
      <header>
        <p className="eyebrow">Isolated loopback only</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Connections</h1>
        <p className="mt-2 text-sm text-fg-1">Every BACnet device here is virtual and bound to loopback. Approval never enables live writes.</p>
      </header>
      {labs.length === 0 ? (
        <EmptyState title="No BACnet labs retained" detail="Candidates with BACnet-mapped points retain a virtual lab manifest." />
      ) : (
        <SectionCard title="Virtual BACnet labs" aside={<span className="num text-xs text-fg-2">{labs.length}</span>}>
          <ul className="divide-y divide-line-1">
            {labs.map((run) => (
              <LabRow key={run.id} run={run} open={open === run.id} onToggle={() => setOpen(open === run.id ? null : run.id)} />
            ))}
          </ul>
        </SectionCard>
      )}
    </StageFrame>
  );
}
