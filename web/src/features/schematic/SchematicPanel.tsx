import { Link2, RotateCcw } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';

import type { RunDetail } from '../../api/client';
import { useGraphicsModel } from '../../api/queries';
import { Button, Popover, StatusPill } from '../../design-system/primitives';
import { LoadingState } from '../../design-system/states';
import type { Trace } from '../../stores/trace';
import { readOverrides, resolveSlots, writeOverrides } from './bindings';
import { sourcesFromGraphicsModel, sourcesFromJob, sourcesFromTrace } from './layout/sources';
import { Schematic } from './Schematic';
import { pickTemplate } from './templates';
import type { Medium } from './types';

const legend: Array<[Medium, string]> = [
  ['air-supply', 'Supply air'],
  ['air-return', 'Return air'],
  ['air-outside', 'Outside air'],
  ['chw', 'Chilled water'],
  ['hw', 'Heating water'],
  ['refrig', 'Condenser / refrigerant'],
];

/**
 * The schematic for a run: template by Brick class, slots bound from the
 * graphics model or the job's points, animated from the shared clock.
 * Bindings can be overridden per run; that preference never touches the
 * deliverable.
 */
export function SchematicPanel({ run, trace }: { run: RunDetail; trace?: Trace }) {
  const model = useGraphicsModel(run.id);
  const [overrides, setOverrides] = useState<Record<string, string>>(() => readOverrides(run.id));

  useEffect(() => {
    writeOverrides(run.id, overrides);
  }, [run.id, overrides]);

  const modelData = model.data?.state === 'available' ? model.data.data : undefined;
  const brick = modelData?.equipment_brick_class ?? (run.job as { equipment_brick_class?: string | null }).equipment_brick_class ?? null;
  const template = useMemo(() => pickTemplate(brick, run.job.sequence.family), [brick, run.job.sequence.family]);

  const sources = useMemo(() => {
    const primary = modelData ? sourcesFromGraphicsModel(modelData, trace) : sourcesFromJob(run, trace);
    const extra = sourcesFromTrace(trace, new Set(primary.map((item) => item.id)));
    return { primary, all: [...primary, ...extra] };
  }, [modelData, run, trace]);

  const resolution = useMemo(() => resolveSlots(template, sources.all, overrides), [template, sources.all, overrides]);
  const layout = useMemo(() => template.build(resolution.slots, sources.primary), [template, resolution.slots, sources.primary]);
  const boundCount = template.slots.filter((slot) => resolution.slots[slot.id]).length;

  const setOverride = useCallback((slotId: string, sourceId: string) => {
    setOverrides((current) => {
      const next = { ...current };
      if (sourceId === '') delete next[slotId];
      else next[slotId] = sourceId;
      return next;
    });
  }, []);

  if (model.isLoading) return <LoadingState compact label="Loading schematic" />;

  return (
    <div className="h-full flex flex-col min-h-0">
      <header className="flex items-center gap-2 px-3 h-9 hairline-b shrink-0 bg-bg-1">
        <span className="eyebrow">Schematic</span>
        <span className="text-xs text-fg-1 truncate">{template.title}</span>
        <span className="flex-1" />
        <StatusPill tone={modelData ? 'info' : 'neutral'} icon={null} title={modelData ? 'Slots bound from the retained graphics model' : 'No graphics model retained; slots bound from the job points'}>
          {modelData ? 'graphics model' : 'job points'}
        </StatusPill>
        {template.slots.length > 0 && (
          <Popover
            trigger={
              <Button size="xs" variant="outline" title="Which signal drives each symbol">
                <Link2 size={12} /> {boundCount}/{template.slots.length} bound
              </Button>
            }
            align="end"
            className="w-96 max-h-[60vh] overflow-auto"
          >
            <div className="flex items-center justify-between mb-2">
              <span className="eyebrow">Symbol bindings</span>
              {Object.keys(overrides).length > 0 && (
                <Button size="xs" variant="ghost" onClick={() => setOverrides({})}>
                  <RotateCcw size={11} /> Auto
                </Button>
              )}
            </div>
            <ul className="flex flex-col gap-1.5">
              {template.slots.map((slot) => {
                const bound = resolution.slots[slot.id];
                const current = Object.entries(overrides).find(([id]) => id === slot.id)?.[1] ?? sources.all.find((item) => (item.signalId ?? item.id) === bound)?.id ?? '';
                return (
                  <li key={slot.id} className="grid grid-cols-[1fr_1fr] gap-2 items-center text-xs">
                    <span className="truncate" title={slot.id}>
                      {slot.label}
                      {resolution.matchedBy[slot.id] && <span className="text-fg-2"> · {resolution.matchedBy[slot.id]}</span>}
                    </span>
                    <select
                      value={current}
                      onChange={(event) => setOverride(slot.id, event.target.value)}
                      aria-label={`Signal for ${slot.label}`}
                      className="h-7 px-1 rounded-control bg-bg-2 border border-line-1 text-xs min-w-0"
                    >
                      <option value="">{bound ? 'auto' : 'unbound'}</option>
                      {sources.all
                        .filter((item) => item.kind === slot.kind)
                        .map((item) => (
                          <option key={item.id} value={item.id}>
                            {item.label}
                            {item.signalId ? '' : ' (no sample)'}
                          </option>
                        ))}
                    </select>
                  </li>
                );
              })}
            </ul>
            <p className="mt-2 text-2xs text-fg-2">Overrides are a viewer preference stored in this browser. The graphics deliverable is server-generated.</p>
          </Popover>
        )}
      </header>
      <div className="flex-1 min-h-0 p-3">
        <Schematic layout={layout} trace={trace} />
      </div>
      <footer className="flex items-center gap-3 px-3 h-7 hairline-t shrink-0 text-2xs text-fg-2 overflow-hidden">
        {legend.map(([medium, label]) => (
          <span key={medium} className="inline-flex items-center gap-1 whitespace-nowrap">
            <span className="w-3 h-1 rounded-pill" style={{ background: `var(--m-${medium})` }} aria-hidden />
            {label}
          </span>
        ))}
        {modelData?.blocker && <span className="truncate text-warn" title={modelData.blocker}>· {modelData.blocker}</span>}
      </footer>
    </div>
  );
}
