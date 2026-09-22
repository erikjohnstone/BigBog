import { useVirtualizer } from '@tanstack/react-virtual';
import { Search } from 'lucide-react';
import { useMemo, useRef, useState } from 'react';

import { cn } from '../../design-system/cn';
import { useSelection } from '../../stores/selection';
import type { Signal, Trace } from '../../stores/trace';
import type { TraceTrends } from '../../stores/trends';
import { visibleSignals } from './unit-groups';

const groupOrder: Array<[Signal['source'][], string]> = [
  [['input'], 'Inputs'],
  [['command'], 'Commands'],
  [['block'], 'Block outputs'],
  [['slot'], 'Slots'],
  [['effective'], 'Effective (after faults)'],
  [['fault'], 'Faults'],
  [['measurement', 'reference', 'kpi'], 'Simulation'],
  [['echo', 'bacnet', 'override', 'actuator'], 'Transport'],
];

type Row = { kind: 'group'; label: string; count: number } | { kind: 'signal'; signal: Signal; on: boolean };

/**
 * Every signal in the trace, grouped, searchable, virtualized. Click toggles
 * it on a pane (numeric) or the ribbon (boolean); drag it onto a pane.
 */
export function SignalRail({
  trace,
  trends,
  onToggle,
  outputsOf,
}: {
  trace: Trace;
  trends: TraceTrends;
  onToggle: (signal: Signal) => void;
  outputsOf?: (blockId: string) => string[];
}) {
  const [query, setQuery] = useState('');
  const scroller = useRef<HTMLDivElement>(null);
  const selectedBlocks = useSelection((state) => state.blockIds);
  const selectBlocks = useSelection((state) => state.selectBlocks);

  const onIds = useMemo(() => new Set([...trends.panes.flatMap((pane) => pane.signalIds), ...trends.ribbon]), [trends]);

  const rows = useMemo<Row[]>(() => {
    const needle = query.trim().toLowerCase();
    const signals = visibleSignals(trace, outputsOf).filter(
      (signal) => !needle || signal.id.toLowerCase().includes(needle) || signal.label.toLowerCase().includes(needle),
    );
    const out: Row[] = [];
    for (const [sources, label] of groupOrder) {
      const members = signals.filter((signal) => sources.includes(signal.source)).sort((a, b) => a.label.localeCompare(b.label));
      if (members.length === 0) continue;
      out.push({ kind: 'group', label, count: members.length });
      for (const signal of members) out.push({ kind: 'signal', signal, on: onIds.has(signal.id) });
    }
    return out;
  }, [trace, query, onIds, outputsOf]);

  // TanStack Virtual returns functions the React Compiler cannot memoize; the
  // compiler skips this component, which is the documented behaviour.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scroller.current,
    estimateSize: (index) => (rows[index].kind === 'group' ? 28 : 26),
    overscan: 12,
  });

  return (
    <div className="h-full flex flex-col bg-bg-1">
      <header className="px-3 h-9 flex items-center gap-2 hairline-b shrink-0">
        <span className="eyebrow">Signals</span>
        <span className="num text-fg-2">{trace.signals.size}</span>
      </header>
      <div className="px-2 py-1.5 hairline-b shrink-0">
        <div className="flex items-center gap-2 h-7 px-2 rounded-control bg-bg-2 border border-line-1">
          <Search size={12} className="text-fg-2" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter signals"
            aria-label="Filter signals"
            className="flex-1 bg-transparent outline-none text-xs placeholder:text-fg-2 min-w-0"
          />
        </div>
      </div>
      <div ref={scroller} className="flex-1 overflow-auto" role="listbox" aria-label="Signals" aria-multiselectable="true">
        <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
          {virtualizer.getVirtualItems().map((item) => {
            const row = rows[item.index];
            const style = { position: 'absolute' as const, top: 0, left: 0, width: '100%', height: item.size, transform: `translateY(${item.start}px)` };
            if (row.kind === 'group') {
              return (
                <div key={item.key} style={style} className="px-3 flex items-end pb-1 gap-2 text-2xs uppercase tracking-wider text-fg-2" role="presentation">
                  {row.label} <span className="num">{row.count}</span>
                </div>
              );
            }
            const { signal, on } = row;
            const selected = signal.blockId ? selectedBlocks.has(signal.blockId) : false;
            return (
              <div
                key={item.key}
                style={style}
                role="option"
                aria-selected={on}
                tabIndex={0}
                draggable
                onDragStart={(event) => {
                  event.dataTransfer.setData('application/x-bactalk-signal', signal.id);
                  event.dataTransfer.effectAllowed = 'copy';
                }}
                onClick={() => onToggle(signal)}
                onDoubleClick={() => signal.blockId && selectBlocks([signal.blockId])}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    onToggle(signal);
                  }
                }}
                className={cn(
                  'px-3 flex items-center gap-2 text-xs cursor-pointer hover:bg-bg-2 outline-none focus-visible:bg-bg-2',
                  selected && 'bg-accent-soft',
                )}
                title={`${signal.id}${signal.unit ? ` (${signal.unit})` : ''} · ${signal.kind} · click to ${on ? 'hide' : 'show'}, double-click to select the block`}
              >
                <span
                  className={cn('size-3 rounded-chip border shrink-0 flex items-center justify-center', on ? 'bg-accent border-accent' : 'border-line-2')}
                  aria-hidden
                >
                  {on && <span className="size-1.5 bg-accent-fg rounded-pill" />}
                </span>
                <span className={cn('size-1.5 rounded-pill shrink-0', signal.kind === 'boolean' ? 'bg-m-status' : 'bg-m-cmd')} aria-hidden />
                <span className="truncate flex-1 min-w-0">{signal.label}</span>
                {signal.unit && <span className="text-2xs text-fg-2 shrink-0">{signal.unit}</span>}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
