import { memo, useEffect, useRef, useState } from 'react';

import { cn } from '../../design-system/cn';
import { useSelection } from '../../stores/selection';
import type { Trace } from '../../stores/trace';
import { useTimeCursor } from '../../stores/timeCursor';

const LANE = 18;

/**
 * Boolean lanes: one row per signal, filled while true, with the shared
 * needle. Cheap SVG; it re-renders only when the range or lanes change and
 * moves the needle by ref.
 */
export const StateRibbon = memo(function StateRibbon({ trace, signalIds }: { trace: Trace; signalIds: string[] }) {
  const host = useRef<HTMLDivElement>(null);
  const needle = useRef<SVGLineElement>(null);
  const [width, setWidth] = useState(600);
  const range = useTimeCursor((state) => state.range);
  const selectBlocks = useSelection((state) => state.selectBlocks);
  const selectedBlocks = useSelection((state) => state.blockIds);
  const labelWidth = 150;
  const plotWidth = Math.max(10, width - labelWidth);
  const [t0, t1] = range[1] > range[0] ? range : [trace.time[0] ?? 0, trace.time[trace.time.length - 1] ?? 1];
  const xAt = (t: number) => labelWidth + ((t - t0) / Math.max(1e-9, t1 - t0)) * plotWidth;

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const observer = new ResizeObserver(() => setWidth(element.clientWidth));
    observer.observe(element);
    setWidth(element.clientWidth);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const apply = () => {
      const line = needle.current;
      if (!line) return;
      const x = xAt(useTimeCursor.getState().t);
      line.setAttribute('x1', String(x));
      line.setAttribute('x2', String(x));
    };
    apply();
    let frame: number | null = null;
    return useTimeCursor.subscribe(() => {
      if (frame !== null) return;
      frame = requestAnimationFrame(() => {
        frame = null;
        apply();
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [t0, t1, plotWidth]);

  const lanes = signalIds.map((id) => trace.signals.get(id)).filter((signal): signal is NonNullable<typeof signal> => Boolean(signal));
  if (lanes.length === 0) return null;
  const height = lanes.length * LANE + 4;

  const seek = (event: React.PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left - labelWidth;
    if (x < 0) return;
    useTimeCursor.getState().seekTime(t0 + (x / plotWidth) * (t1 - t0));
  };

  return (
    <div ref={host} className="hairline-b" aria-label="Boolean state lanes" role="img">
      <svg
        width="100%"
        height={height}
        className="block select-none"
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture(event.pointerId);
          useTimeCursor.getState().pause();
          seek(event);
        }}
        onPointerMove={(event) => {
          if (event.buttons & 1) seek(event);
        }}
      >
        {lanes.map((signal, row) => {
          const y = 2 + row * LANE;
          const runs: Array<[number, number]> = [];
          let open: number | null = null;
          for (let i = 0; i <= signal.values.length; i += 1) {
            const on = i < signal.values.length && signal.values[i] === 1;
            if (on && open === null) open = i;
            if (!on && open !== null) {
              runs.push([open, i - 1]);
              open = null;
            }
          }
          const isFault = signal.source === 'fault';
          const selected = signal.blockId ? selectedBlocks.has(signal.blockId) : false;
          return (
            <g key={signal.id} transform={`translate(0 ${y})`}>
              <rect x={0} y={0} width="100%" height={LANE} fill={selected ? 'var(--accent-soft)' : row % 2 ? 'var(--bg-1)' : 'transparent'} />
              <text
                x={8}
                y={LANE / 2 + 3.5}
                className={cn('text-[10px] font-mono cursor-pointer', selected ? 'fill-fg-0' : 'fill-fg-1')}
                onClick={() => signal.blockId && selectBlocks([signal.blockId])}
              >
                <title>{signal.label}</title>
                {signal.label.length > 22 ? `${signal.label.slice(0, 21)}…` : signal.label}
              </text>
              {runs.map(([start, end]) => {
                const stepAfter = trace.phases.find((phase) => end >= phase.startIdx && end <= phase.endIdx)?.stepSeconds ?? 0;
                const x0 = xAt(trace.time[start]);
                const x1 = xAt(trace.time[end] + stepAfter);
                return (
                  <rect
                    key={start}
                    x={x0}
                    y={4}
                    width={Math.max(1.5, x1 - x0)}
                    height={LANE - 8}
                    rx={2}
                    fill={isFault ? 'var(--warn)' : 'var(--m-status)'}
                    opacity={0.85}
                  >
                    <title>{`${signal.label}: true from ${trace.time[start]}s to ${trace.time[end] + stepAfter}s`}</title>
                  </rect>
                );
              })}
            </g>
          );
        })}
        {trace.phases.slice(1).map((phase) => (
          <line key={phase.index} x1={xAt(phase.t0)} x2={xAt(phase.t0)} y1={0} y2={height} stroke="var(--line-2)" />
        ))}
        <line ref={needle} x1={labelWidth} x2={labelWidth} y1={0} y2={height} stroke="var(--accent)" strokeWidth={1.5} />
      </svg>
    </div>
  );
});
