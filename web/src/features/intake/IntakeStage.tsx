import type { RunDetail } from '../../api/client';
import { StatusPill } from '../../design-system/primitives';
import { KeyValue, SectionCard, StageFrame } from '../shared/StageFrame';

/** Intake stage of an existing job: the normalized job record and its points. */
export function IntakeStage({ run }: { run: RunDetail }) {
  const points = run.job.points;
  const mapped = points.filter((point) => point.bacnet_object).length;
  return (
    <StageFrame wide>
      <SectionCard title="Job">
        <KeyValue
          items={[
            { label: 'Name', value: run.job.name },
            { label: 'Site', value: run.job.site },
            { label: 'Equipment', value: <span className="font-mono text-xs">{run.job.equipment_name}</span> },
            {
              label: 'Sequence',
              value: (
                <span>
                  {run.job.sequence.family} <span className="text-fg-2">v{run.job.sequence.version}</span>
                </span>
              ),
            },
            { label: 'Origin', value: run.origin === 'ai_proposal' ? <StatusPill tone="sim">AI proposal</StatusPill> : run.origin },
            { label: 'Created', value: <span className="num">{run.created_at}</span> },
          ]}
        />
      </SectionCard>
      <SectionCard
        title="Points"
        aside={
          <span className="text-xs text-fg-2">
            <span className="num">{mapped}</span> of <span className="num">{points.length}</span> mapped to BACnet
          </span>
        }
      >
        <table className="w-full text-sm">
          <thead className="text-left">
            <tr className="hairline-b">
              <th className="eyebrow px-4 h-8 font-semibold">Point</th>
              <th className="eyebrow px-4 h-8 font-semibold">Role</th>
              <th className="eyebrow px-4 h-8 font-semibold">Type</th>
              <th className="eyebrow px-4 h-8 font-semibold">Units</th>
              <th className="eyebrow px-4 h-8 font-semibold">Brick</th>
              <th className="eyebrow px-4 h-8 font-semibold">BACnet</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line-1">
            {points.map((point) => (
              <tr key={point.name}>
                <td className="px-4 h-9">
                  <span className="block truncate">{point.label}</span>
                  <span className="block font-mono text-2xs text-fg-2">{point.name}</span>
                </td>
                <td className="px-4 text-xs text-fg-1">{point.role}</td>
                <td className="px-4 font-mono text-xs">{point.data_type}</td>
                <td className="px-4 text-xs">{point.units ?? <span className="text-fg-2">—</span>}</td>
                <td className="px-4 font-mono text-2xs text-fg-1">{point.brick_class ?? <span className="text-fg-2">—</span>}</td>
                <td className="px-4 font-mono text-2xs">
                  {point.bacnet_object ? (
                    <span>
                      {point.bacnet_device_instance ?? '?'}:{point.bacnet_object}
                    </span>
                  ) : (
                    <span className="text-fg-2">unmapped</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </SectionCard>
    </StageFrame>
  );
}
