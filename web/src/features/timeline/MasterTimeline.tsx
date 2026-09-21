import { scaleLinear } from '@visx/scale';
import { Check, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';

import { Button } from '../../design-system/primitives';
import { useSelection } from '../../stores/selection';
import type { Trace } from '../../stores/trace';
import { useTimeCursor } from '../../stores/timeCursor';

const PHASE_ROW = 22;
const LANE = 10;
const MARK_ROW = 16;

/**
 * The master timeline: phase bands, one hatched lane per fault target,
 * assertion marks at phase ends, the needle, and a brush that sets the
 * visible range of every trend pane. Click seeks; drag brushes.
 */
export function MasterTimeline({ trace }: { trace: Trace }) {
  const host = useRef<HTMLDivElement>(null);
  const needle = useRef<SVGGElement>(null);
  const [width, setWidth] = useState(800);
  const range = useTimeCursor((state) => state.range);
  const setRange = useTimeCursor((state) => state.setRange);
  const assertionId = useSelection((state) => state.assertionId);
  const [drag, setDrag] = useState<{ x0: number; x1: number } | null>(null);

  const t0 = trace.time[0] ?? 0;
  const lastPhase = trace.phases[trace.phases.length - 1];
  const tEnd = (trace.time[trace.time.length - 1] ?? 0) + (lastPhase?.stepSeconds ?? 0);
  const x = useMemo(() => scaleLinear<number>({ domain: [t0, tEnd], range: [0, width] }), [t0, tEnd, width]);
  const targets = useMemo(() => [...new Set(trace.faultWindows.map((window) => window.target))], [trace]);
  const height = PHASE_ROW + targets.length * LANE + MARK_ROW + 4;

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
      const g = needle.current;
      if (!g) return;
      g.setAttribute('transform', `translate(${x(useTimeCursor.getState().t)} 0)`);
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
  }, [x]);

  const toT = (clientX: number) => {
    const rect = host.current?.getBoundingClientRect();
    return x.invert(clientX - (rect?.left ?? 0));
  };
  const hasRange = range[1] > range[0] && (range[0] > t0 || range[1] < tEnd);

  return (
    <div ref={host} className="relative hairline-b bg-bg-1 select-none" role="group" aria-label="Master timeline">
      <svg
        width="100%"
        height={height}
        className="block"
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          event.currentTarget.setPointerCapture(event.pointerId);
          useTimeCursor.getState().pause();
          const start = event.clientX - (host.current?.getBoundingClientRect().left ?? 0);
          setDrag({ x0: start, x1: start });
        }}
        onPointerMove={(event) => {
          if (!drag) return;
          const px = event.clientX - (host.current?.getBoundingClientRect().left ?? 0);
          setDrag({ x0: drag.x0, x1: px });
        }}
        onPointerUp={(event) => {
          if (!drag) return;
          const moved = Math.abs(drag.x1 - drag.x0) > 4;
          if (moved) {
            const a = x.invert(Math.min(drag.x0, drag.x1));
            const b = x.invert(Math.max(drag.x0, drag.x1));
            setRange([Math.max(t0, a), Math.min(tEnd, b)]);
          } else {
            useTimeCursor.getState().seekTime(toT(event.clientX));
          }
          setDrag(null);
        }}
      >
        <defs>
          <pattern id="fault-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="2" height="6" fill="var(--warn)" />
          </pattern>
        </defs>
        {/* Phase bands */}
        {trace.phases.map((phase) => {
          const x0 = x(phase.t0);
          const x1 = x(phase.t1 + phase.stepSeconds);
          const failed = trace.assertions.some((assertion) => assertion.phaseIndex === phase.index && !assertion.passed);
          if (x1 - x0 < 1) return null;
          return (
            <g key={phase.index}>
              <rect x={x0} y={0} width={Math.max(1, x1 - x0)} height={PHASE_ROW} fill={failed ? 'var(--fail-soft)' : phase.index % 2 ? 'var(--bg-2)' : 'var(--bg-1)'} />
              <line x1={x0} x2={x0} y1={0} y2={height} stroke="var(--line-2)" />
              {x1 - x0 > 40 && (
                <text x={x0 + 6} y={14.5} className="text-[11px] fill-fg-1" clipPath={`inset(0 ${Math.max(0, width - x1)}px 0 0)`}>
                  <title>{phase.name}</title>
                  {phase.name}
                </text>
              )}
            </g>
          );
        })}
        {/* Fault lanes */}
        {targets.map((target, row) => {
          const y = PHASE_ROW + row * LANE;
          return (
            <g key={target} transform={`translate(0 ${y})`}>
              <rect x={0} y={0} width="100%" height={LANE} fill={row % 2 ? 'var(--bg-2)' : 'transparent'} />
              {trace.faultWindows
                .filter((window) => window.target === target)
                .map((window) => {
                  const stepAfter = trace.phases.find((phase) => window.endIdx >= phase.startIdx && window.endIdx <= phase.endIdx)?.stepSeconds ?? 0;
                  const x0 = x(trace.time[window.startIdx]);
                  const x1 = x(trace.time[window.endIdx] + stepAfter);
                  return (
                    <rect key={`${window.id}-${window.startIdx}`} x={x0} y={1.5} width={Math.max(2, x1 - x0)} height={LANE - 3} rx={1.5} fill="url(#fault-hatch)">
                      <title>{`${window.kind} on ${window.target} (${window.id})`}</title>
                    </rect>
                  );
                })}
              <text x={4} y={LANE - 2} className="text-[9px] fill-fg-1 font-mono" stroke="var(--bg-1)" strokeWidth={3} paintOrder="stroke">
                {target}
              </text>
            </g>
          );
        })}
        {/* Assertion marks */}
        {trace.assertions.map((assertion) => {
          const phase = trace.phases[assertion.phaseIndex];
          const px = x(trace.time[assertion.index] + (phase?.stepSeconds ?? 0));
          const y = PHASE_ROW + targets.length * LANE + 2;
          const siblings = trace.assertions.filter((item) => item.phaseIndex === assertion.phaseIndex);
          const offset = siblings.indexOf(assertion) * -7;
          return (
            <g key={assertion.id} transform={`translate(${px - 6 + offset} ${y})`} className="cursor-pointer" onClick={(event) => {
              event.stopPropagation();
              useTimeCursor.getState().jumpToFailure(assertion.id);
              useSelection.getState().setAssertion(assertion.id);
              if (assertion.blockIds[0]) useSelection.getState().selectBlocks(assertion.blockIds);
            }}>
              <title>{`${assertion.name}: ${assertion.passed ? 'passed' : 'failed'} (observed ${assertion.observed}, expected ${assertion.expected})`}</title>
              <circle cx={0} cy={6} r={assertion.id === assertionId ? 6 : 5} fill={assertion.passed ? 'var(--ok)' : 'var(--fail)'} />
            </g>
          );
        })}
        {/* Brush shading */}
        {hasRange && (
          <>
            <rect x={0} y={0} width={Math.max(0, x(range[0]))} height={height} fill="var(--bg-0)" opacity={0.55} />
            <rect x={x(range[1])} y={0} width={Math.max(0, width - x(range[1]))} height={height} fill="var(--bg-0)" opacity={0.55} />
          </>
        )}
        {drag && Math.abs(drag.x1 - drag.x0) > 4 && (
          <rect x={Math.min(drag.x0, drag.x1)} y={0} width={Math.abs(drag.x1 - drag.x0)} height={height} fill="var(--accent-soft)" stroke="var(--accent)" />
        )}
        <g ref={needle}>
          <line x1={0} x2={0} y1={0} y2={height} stroke="var(--accent)" strokeWidth={1.5} />
          <polygon points="-5,0 5,0 0,6" fill="var(--accent)" />
        </g>
      </svg>
      <div className="absolute right-2 top-1 flex items-center gap-1">
        {hasRange && (
          <Button size="xs" variant="outline" onClick={() => setRange([t0, tEnd])}>
            Show all
          </Button>
        )}
      </div>
      <span className="sr-only">
        {trace.phases.length} phases, {trace.assertions.filter((assertion) => !assertion.passed).length} failing assertions, {trace.faultWindows.length} fault windows.
        <Check size={0} />
        <X size={0} />
      </span>
    </div>
  );
}
