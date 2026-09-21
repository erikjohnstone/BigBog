import { useMemo, useState } from 'react';

import { cn } from '../../design-system/cn';
import type { Trace } from '../../stores/trace';
import { useTimeCursor } from '../../stores/timeCursor';
import { formatSignalValue } from '../../stores/trace';
import { visibleSignals } from '../trends/unit-groups';

const PAGE = 60;

/** The trace as numbers, for anyone who wants to read the evidence directly. */
export function DataTable({ trace }: { trace: Trace }) {
  const index = useTimeCursor((state) => state.index);
  const [page, setPage] = useState(0);
  const signals = useMemo(() => visibleSignals(trace).sort((a, b) => a.label.localeCompare(b.label)), [trace]);
  const rows = trace.time.length;
  const start = page * PAGE;
  const end = Math.min(rows, start + PAGE);
  const pages = Math.ceil(rows / PAGE);
  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-4 h-9 hairline-b text-xs text-fg-2 shrink-0">
        <span className="num">{rows}</span> scans · <span className="num">{signals.length}</span> signals
        <span className="flex-1" />
        {pages > 1 && (
          <span className="inline-flex items-center gap-1">
            <button type="button" className="px-2 h-6 rounded-control hover:bg-bg-2" disabled={page === 0} onClick={() => setPage(page - 1)}>
              ‹
            </button>
            <span className="num">
              {page + 1}/{pages}
            </span>
            <button type="button" className="px-2 h-6 rounded-control hover:bg-bg-2" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>
              ›
            </button>
          </span>
        )}
      </div>
      <div className="flex-1 overflow-auto outline-none focus-visible:[box-shadow:inset_0_0_0_2px_var(--accent)]" tabIndex={0} role="region" aria-label="Trace data">
        <table className="text-xs whitespace-nowrap">
          <thead className="sticky top-0 bg-bg-1">
            <tr className="hairline-b">
              <th className="eyebrow px-3 h-8 font-semibold text-left sticky left-0 bg-bg-1">t (s)</th>
              {signals.map((signal) => (
                <th key={signal.id} className="eyebrow px-3 h-8 font-semibold text-right" title={signal.id}>
                  {signal.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line-1">
            {Array.from({ length: end - start }, (_, offset) => {
              const i = start + offset;
              return (
                <tr
                  key={i}
                  className={cn('hover:bg-bg-2 cursor-pointer', i === index && 'bg-accent-soft')}
                  onClick={() => useTimeCursor.getState().seekIndex(i)}
                >
                  <td className="px-3 h-7 num sticky left-0 bg-bg-1">{trace.time[i]}</td>
                  {signals.map((signal) => (
                    <td key={signal.id} className="px-3 num text-right">
                      {formatSignalValue(signal.kind === 'boolean' ? (signal.values[i] === 255 ? Number.NaN : signal.values[i]) : signal.values[i], signal)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
