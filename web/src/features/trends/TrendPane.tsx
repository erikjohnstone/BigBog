import { X } from 'lucide-react';
import { memo, useEffect, useMemo, useRef } from 'react';
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';

import { cn } from '../../design-system/cn';
import { Button } from '../../design-system/primitives';
import { useTheme } from '../../design-system/theme';
import { useSelection } from '../../stores/selection';
import { formatSignalValue, useSignalValue } from '../../stores/trace';
import type { Trace } from '../../stores/trace';
import { useTimeCursor } from '../../stores/timeCursor';
import type { Pane } from '../../stores/trends';
import { readThemeColors, seriesColor, seriesColorVar } from './colors';

function formatAxisSeconds(t: number, increment: number): string {
  if (increment < 60) {
    const decimals = increment >= 1 ? 0 : increment >= 0.1 ? 1 : 2;
    return `${t.toFixed(decimals)}s`;
  }
  const whole = Math.round(t);
  const h = Math.floor(whole / 3600);
  const m = Math.floor((whole % 3600) / 60);
  const s = whole % 60;
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
}

function toNullable(values: Float64Array | Uint8Array, boolean: boolean): (number | null)[] {
  const out = new Array<number | null>(values.length);
  for (let i = 0; i < values.length; i += 1) {
    const value = values[i];
    out[i] = boolean ? (value === 255 ? null : value) : Number.isNaN(value) ? null : value;
  }
  return out;
}

/** Live readout for assistive tech and the pane header. */
function SeriesReadout({ trace, signalId, index }: { trace: Trace; signalId: string; index: number }) {
  const value = useSignalValue(signalId);
  const signal = trace.signals.get(signalId);
  return (
    <span className="inline-flex items-center gap-1 text-2xs whitespace-nowrap">
      <span className="size-1.5 rounded-pill" style={{ background: seriesColorVar(index) }} aria-hidden />
      <span className="text-fg-1 truncate max-w-32">{signal?.label ?? signalId}</span>
      <span className="num text-fg-0">{formatSignalValue(value, signal)}</span>
    </span>
  );
}

/**
 * One uPlot pane on the shared clock. The needle, phase boundaries, fault
 * windows, and assertion marks are drawn in the draw hook; pointer drags
 * seek the clock; the range from the master timeline sets the x scale.
 */
export const TrendPane = memo(function TrendPane({
  trace,
  pane,
  onRemove,
  height = 176,
}: {
  trace: Trace;
  pane: Pane;
  onRemove?: () => void;
  height?: number;
}) {
  const host = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);
  const { resolved } = useTheme();
  const signals = useMemo(() => pane.signalIds.map((id) => trace.signals.get(id)).filter((signal): signal is NonNullable<typeof signal> => Boolean(signal)), [pane.signalIds, trace]);
  const selectedBlocks = useSelection((state) => state.blockIds);
  const assertionId = useSelection((state) => state.assertionId);

  useEffect(() => {
    const element = host.current;
    if (!element || signals.length === 0) return;
    const colors = readThemeColors();
    const data: uPlot.AlignedData = [Array.from(trace.time), ...signals.map((signal) => toNullable(signal.values, signal.kind === 'boolean'))];
    const width = element.clientWidth || 600;

    const drawOverlays = (u: uPlot) => {
      const ctx = u.ctx;
      const { left, top, width: plotWidth, height: plotHeight } = u.bbox;
      ctx.save();
      ctx.beginPath();
      ctx.rect(left, top, plotWidth, plotHeight);
      ctx.clip();
      const xAt = (t: number) => u.valToPos(t, 'x', true);
      // Phase boundaries.
      ctx.strokeStyle = colors.line2;
      ctx.lineWidth = 1;
      for (const phase of trace.phases.slice(1)) {
        const x = xAt(phase.t0);
        ctx.beginPath();
        ctx.moveTo(x, top);
        ctx.lineTo(x, top + plotHeight);
        ctx.stroke();
      }
      // Fault windows.
      ctx.fillStyle = colors.warnSoft;
      for (const window of trace.faultWindows) {
        const x0 = xAt(trace.time[window.startIdx]);
        const stepAfter = trace.phases.find((phase) => window.endIdx >= phase.startIdx && window.endIdx <= phase.endIdx)?.stepSeconds ?? 0;
        const x1 = xAt(trace.time[window.endIdx] + stepAfter);
        ctx.fillRect(x0, top, Math.max(2, x1 - x0), plotHeight);
      }
      // Oracle tolerance bands, dashed references, and counterexample windows.
      for (const band of trace.oracles) {
        const seriesIndex = signals.findIndex((signal) => signal.id === band.signalId);
        if (seriesIndex < 0) continue;
        const reference = trace.signals.get(band.referenceSignalId)?.values;
        if (!reference) continue;
        // Each contiguous run of reference samples is one filled ribbon.
        let start = -1;
        const flush = (end: number) => {
          if (start < 0) return;
          ctx.beginPath();
          for (let i = start; i <= end; i += 1) ctx.lineTo(xAt(trace.time[i]), u.valToPos(reference[i] + band.tolerance, 'y', true));
          for (let i = end; i >= start; i -= 1) ctx.lineTo(xAt(trace.time[i]), u.valToPos(reference[i] - band.tolerance, 'y', true));
          ctx.closePath();
          ctx.fillStyle = colors.simSoft;
          ctx.fill();
          ctx.beginPath();
          for (let i = start; i <= end; i += 1) ctx.lineTo(xAt(trace.time[i]), u.valToPos(reference[i], 'y', true));
          ctx.setLineDash([4, 3]);
          ctx.strokeStyle = colors.sim;
          ctx.lineWidth = 1;
          ctx.stroke();
          ctx.setLineDash([]);
          start = -1;
        };
        for (let i = 0; i < reference.length; i += 1) {
          if (Number.isNaN(reference[i])) flush(i - 1);
          else if (start < 0) start = i;
        }
        flush(reference.length - 1);
        if (band.window) {
          const x0 = xAt(trace.time[band.window.startIdx]);
          const x1 = xAt(trace.time[band.window.endIdx]);
          ctx.fillStyle = colors.failSoft;
          ctx.fillRect(Math.min(x0, x1), top, Math.max(2, Math.abs(x1 - x0)), plotHeight);
          const peakValue = data[seriesIndex + 1][band.window.peakIdx];
          if (peakValue !== null && peakValue !== undefined) {
            const px = xAt(trace.time[band.window.peakIdx]);
            const py = u.valToPos(peakValue as number, 'y', true);
            ctx.beginPath();
            ctx.arc(px, py, 5, 0, Math.PI * 2);
            ctx.strokeStyle = colors.fail;
            ctx.lineWidth = 1.5;
            ctx.stroke();
          }
        }
      }
      // Assertion marks for series on this pane.
      const { index: cursorIndex, t } = useTimeCursor.getState();
      for (const assertion of trace.assertions) {
        const seriesIndex = assertion.signalId ? signals.findIndex((signal) => signal.id === assertion.signalId) : -1;
        if (seriesIndex < 0) continue;
        const value = data[seriesIndex + 1][assertion.index];
        if (value === null || value === undefined) continue;
        const x = xAt(trace.time[assertion.index]);
        const y = u.valToPos(value as number, 'y', true);
        ctx.beginPath();
        ctx.arc(x, y, assertion.id === assertionId ? 6 : 4, 0, Math.PI * 2);
        ctx.fillStyle = assertion.passed ? colors.ok : colors.fail;
        ctx.fill();
        if (!assertion.passed) {
          ctx.strokeStyle = colors.fail;
          ctx.lineWidth = 1.5;
          ctx.beginPath();
          ctx.moveTo(x - 3, y - 3);
          ctx.lineTo(x + 3, y + 3);
          ctx.moveTo(x + 3, y - 3);
          ctx.lineTo(x - 3, y + 3);
          ctx.strokeStyle = colors.bg1;
          ctx.stroke();
        }
      }
      // The clock needle.
      if (cursorIndex >= 0 && cursorIndex < trace.time.length) {
        const x = xAt(t);
        ctx.strokeStyle = colors.accent;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(x, top);
        ctx.lineTo(x, top + plotHeight);
        ctx.stroke();
      }
      ctx.restore();
    };

    const options: uPlot.Options = {
      width,
      height,
      legend: { show: false },
      scales: { x: { time: false } },
      cursor: {
        sync: { key: trace.id },
        drag: { x: false, y: false, setScale: false },
        points: { show: false },
        focus: { prox: 20 },
        y: false,
      },
      axes: [
        {
          stroke: colors.fg2,
          font: colors.font,
          grid: { stroke: colors.line1, width: 1 },
          ticks: { stroke: colors.line1, width: 1 },
          values: (_u, values, _axisIdx, _space, increment) => values.map((value) => formatAxisSeconds(value, increment)),
          space: 64,
        },
        {
          stroke: colors.fg2,
          font: colors.font,
          grid: { stroke: colors.line1, width: 1 },
          ticks: { stroke: colors.line1, width: 1 },
          size: 52,
        },
      ],
      series: [
        {},
        ...signals.map((signal, index) => ({
          label: signal.label,
          stroke: seriesColor(colors, index),
          width: 1.5,
          spanGaps: false,
          points: { show: false },
          paths: signal.kind === 'boolean' ? uPlot.paths.stepped!({ align: 1 }) : undefined,
        })),
      ],
      hooks: { draw: [drawOverlays] },
    };
    const plot = new uPlot(options, data, element);
    plotRef.current = plot;

    // Pointer drag seeks the clock.
    const over = plot.over;
    let dragging = false;
    const seekAt = (event: PointerEvent) => {
      const rect = over.getBoundingClientRect();
      const t = plot.posToVal(event.clientX - rect.left, 'x');
      useTimeCursor.getState().seekTime(t);
    };
    const onDown = (event: PointerEvent) => {
      if (event.button !== 0) return;
      dragging = true;
      over.setPointerCapture(event.pointerId);
      useTimeCursor.getState().pause();
      seekAt(event);
    };
    const onMove = (event: PointerEvent) => {
      if (dragging) seekAt(event);
    };
    const onUp = (event: PointerEvent) => {
      dragging = false;
      if (over.hasPointerCapture(event.pointerId)) over.releasePointerCapture(event.pointerId);
    };
    over.addEventListener('pointerdown', onDown);
    over.addEventListener('pointermove', onMove);
    over.addEventListener('pointerup', onUp);
    over.addEventListener('pointercancel', onUp);

    // Redraw (cached paths) when the clock or the range moves.
    let frame: number | null = null;
    const redraw = () => {
      if (frame !== null) return;
      frame = requestAnimationFrame(() => {
        frame = null;
        plot.redraw(false, false);
      });
    };
    let lastRange: [number, number] | null = null;
    const unsubscribe = useTimeCursor.subscribe((state) => {
      if (state.range !== lastRange) {
        lastRange = state.range;
        const [min, max] = state.range;
        if (max > min) plot.setScale('x', { min, max });
      } else redraw();
    });
    const initial = useTimeCursor.getState().range;
    if (initial[1] > initial[0]) plot.setScale('x', { min: initial[0], max: initial[1] });

    const observer = new ResizeObserver(() => {
      const next = element.clientWidth;
      if (next > 0 && next !== plot.width) plot.setSize({ width: next, height });
    });
    observer.observe(element);

    return () => {
      unsubscribe();
      observer.disconnect();
      over.removeEventListener('pointerdown', onDown);
      over.removeEventListener('pointermove', onMove);
      over.removeEventListener('pointerup', onUp);
      over.removeEventListener('pointercancel', onUp);
      if (frame !== null) cancelAnimationFrame(frame);
      plot.destroy();
      plotRef.current = null;
    };
    // Theme changes re-create the plot with new canvas colours.
  }, [trace, signals, height, resolved, assertionId]);

  // Selected blocks focus their series.
  useEffect(() => {
    const plot = plotRef.current;
    if (!plot) return;
    const focused = signals.findIndex((signal) => signal.blockId && selectedBlocks.has(signal.blockId));
    plot.setSeries(focused >= 0 ? focused + 1 : null, { focus: true });
  }, [selectedBlocks, signals]);

  const label = `Trend of ${signals.map((signal) => signal.label).join(', ')}${pane.unit ? ` in ${pane.unit}` : ''}`;

  return (
    <section className={cn('flex flex-col hairline-b')} aria-label={label}>
      <header className="flex items-center gap-3 px-3 h-8 min-w-0">
        <span className="text-xs font-medium shrink-0">{pane.title}</span>
        <div className="flex-1 min-w-0 flex items-center gap-3 overflow-hidden" aria-live="polite">
          {signals.map((signal, index) => (
            <SeriesReadout key={signal.id} trace={trace} signalId={signal.id} index={index} />
          ))}
        </div>
        {onRemove && (
          <Button size="icon" variant="ghost" className="size-6" onClick={onRemove} aria-label={`Remove ${pane.title} pane`}>
            <X size={12} />
          </Button>
        )}
      </header>
      <div ref={host} role="img" aria-label={label} className="px-1 pb-1" style={{ height: height + 4 }} />
    </section>
  );
});
