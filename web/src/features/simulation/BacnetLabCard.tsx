import { useMutation } from '@tanstack/react-query';
import { Activity } from 'lucide-react';

import { api } from '../../api/client';
import { useBacnetLab } from '../../api/queries';
import { Button, StatusPill } from '../../design-system/primitives';
import { MissingEvidence } from '../../design-system/states';

/**
 * The isolated BACnet loopback lab attached to a run: devices, points, and a
 * probe that reads every mapped point through the independent protocol
 * oracle. The safety block is repeated verbatim because it is the boundary.
 */
export function BacnetLabCard({ runId }: { runId: string }) {
  const lab = useBacnetLab(runId);
  const probe = useMutation({ mutationFn: () => api.probeBacnetLab(runId) });

  if (lab.isLoading) return <p className="px-4 py-3 text-sm text-fg-2">Loading BACnet lab manifest…</p>;
  if (!lab.data || lab.data.state !== 'available') {
    return <MissingEvidence kind="BACnet lab" state={lab.data?.state === 'invalid' ? 'invalid' : 'missing'} detail={lab.data?.state === 'invalid' ? lab.data.message : 'This candidate has no virtual BACnet lab manifest.'} />;
  }
  const manifest = lab.data.data;
  const points = Object.values(manifest.point_index);
  const injectable = points.filter((point) => point.scenario_injectable).length;
  const capture = points.filter((point) => point.command_capture).length;
  const safe = Object.values(manifest.safety).every((flag) => flag === true || flag === false) && !manifest.safety.live_network_routes_allowed && manifest.safety.writes_affect_virtual_objects_only;

  return (
    <div className="px-4 py-3 flex flex-col gap-3 text-sm">
      <div className="flex items-center gap-2 flex-wrap">
        <StatusPill tone="sim">{manifest.mode}</StatusPill>
        <StatusPill tone={safe ? 'ok' : 'warn'}>{safe ? 'Virtual objects only' : 'Review safety block'}</StatusPill>
        <span className="text-xs text-fg-2 truncate">{manifest.independent_protocol_oracle.implementation} {manifest.independent_protocol_oracle.revision}</span>
        <span className="flex-1" />
        <Button size="xs" variant="outline" onClick={() => probe.mutate()} disabled={probe.isPending}>
          <Activity size={12} /> {probe.isPending ? 'Probing…' : 'Probe points'}
        </Button>
      </div>
      <dl className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {[
          ['Devices', manifest.devices.length],
          ['Points', points.length],
          ['Injectable', injectable],
          ['Command capture', capture],
        ].map(([label, value]) => (
          <div key={String(label)} className="raised px-3 py-2">
            <dt className="text-2xs text-fg-2">{label}</dt>
            <dd className="num text-lg text-fg-0">{value}</dd>
          </div>
        ))}
      </dl>
      <ul className="flex flex-col gap-1 text-xs">
        {manifest.devices.map((device) => (
          <li key={device.device_instance} className="flex items-center gap-2 min-w-0">
            <span className="num text-fg-2 w-16 shrink-0">{device.device_instance}</span>
            <span className="text-fg-0 truncate">{device.device_name}</span>
            <span className="text-fg-2 truncate hidden sm:inline">{device.network_address}</span>
            <span className="num text-fg-2 ml-auto shrink-0">{device.object_count} objects</span>
          </li>
        ))}
      </ul>
      {probe.data && (
        <div className="raised px-3 py-2" role="status">
          <div className="flex items-center gap-2">
            <StatusPill tone={probe.data.passed ? 'ok' : 'fail'}>{probe.data.passed ? 'Probe passed' : 'Probe failed'}</StatusPill>
            <span className="num text-xs text-fg-2">{probe.data.point_count} points read</span>
          </div>
          <ul className="mt-2 grid gap-x-4 gap-y-0.5 grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] text-2xs">
            {Object.entries(probe.data.values).map(([name, value]) => (
              <li key={name} className="flex justify-between gap-2 min-w-0">
                <span className="text-fg-1 truncate">{name}</span>
                <span className="num text-fg-0 shrink-0">{String(value)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {probe.isError && (
        <p role="alert" className="text-xs text-fail">
          {(probe.error as Error).message}
        </p>
      )}
      <p className="text-2xs text-fg-2">
        Bind scope {manifest.safety.bind_scope}. Live network discovery {manifest.safety.live_network_discovery_performed ? 'was' : 'was not'} performed; live routes {manifest.safety.live_network_routes_allowed ? 'allowed' : 'never allowed'}. Human approval does not enable live writes.
      </p>
    </div>
  );
}
