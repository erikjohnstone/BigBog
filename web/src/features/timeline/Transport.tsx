import { ChevronFirst, ChevronLast, Pause, Play, Repeat, SkipBack, SkipForward } from 'lucide-react';
import { useMemo } from 'react';

import { cn } from '../../design-system/cn';
import { Button, StatusPill } from '../../design-system/primitives';
import type { Trace } from '../../stores/trace';
import { useTimeCursor } from '../../stores/timeCursor';
import type { PlaybackSpeed } from '../../stores/timeCursor';

const speeds: PlaybackSpeed[] = [0.25, 0.5, 1, 2, 4, 8];

function formatSeconds(t: number): string {
  if (!Number.isFinite(t)) return '—';
  const whole = Math.round(t);
  const h = Math.floor(whole / 3600);
  const m = Math.floor((whole % 3600) / 60);
  const s = whole % 60;
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
}

/**
 * The one clock's controls: scrub, play, step, loop a phase, jump between
 * failures. Every view on the page follows it.
 */
export function Transport({ trace, compact }: { trace: Trace | undefined; compact?: boolean }) {
  const index = useTimeCursor((state) => state.index);
  const length = useTimeCursor((state) => state.length);
  const t = useTimeCursor((state) => state.t);
  const playing = useTimeCursor((state) => state.playing);
  const speed = useTimeCursor((state) => state.speed);
  const loop = useTimeCursor((state) => state.loop);
  const { seekIndex, step, toggle, setSpeed, setLoop, jumpToNextFailure } = useTimeCursor.getState();

  const phase = useMemo(() => trace?.phases.find((item) => index >= item.startIdx && index <= item.endIdx), [trace, index]);
  const failures = trace?.assertions.filter((item) => !item.passed).length ?? 0;
  const disabled = !trace || length <= 1;

  return (
    <div className={cn('flex items-center gap-2 px-3 bg-bg-1 hairline-t', compact ? 'h-10' : 'h-12')} role="group" aria-label="Playback">
      <Button size="icon" variant="ghost" className="size-7" disabled={disabled || failures === 0} onClick={() => jumpToNextFailure(-1)} title="Previous failure" aria-label="Previous failure">
        <ChevronFirst size={14} />
      </Button>
      <Button size="icon" variant="ghost" className="size-7" disabled={disabled} onClick={() => step(-1)} title="Step back one scan ([)" aria-label="Step back">
        <SkipBack size={14} />
      </Button>
      <Button size="icon" variant={playing ? 'primary' : 'secondary'} className="size-7" disabled={disabled} onClick={toggle} title="Play / pause (space)" aria-label={playing ? 'Pause' : 'Play'}>
        {playing ? <Pause size={14} /> : <Play size={14} />}
      </Button>
      <Button size="icon" variant="ghost" className="size-7" disabled={disabled} onClick={() => step(1)} title="Step forward one scan (])" aria-label="Step forward">
        <SkipForward size={14} />
      </Button>
      <Button size="icon" variant="ghost" className="size-7" disabled={disabled || failures === 0} onClick={() => jumpToNextFailure(1)} title="Next failure" aria-label="Next failure">
        <ChevronLast size={14} />
      </Button>

      <div className="relative flex-1 min-w-0 h-6 flex items-center">
        {trace && (
          <div aria-hidden className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-1.5 flex rounded-pill overflow-hidden">
            {trace.phases.map((item) => {
              const failed = trace.assertions.some((assertion) => assertion.phaseIndex === item.index && !assertion.passed);
              const width = ((item.endIdx - item.startIdx + 1) / Math.max(1, length)) * 100;
              return (
                <span
                  key={item.index}
                  style={{ width: `${width}%`, background: failed ? 'var(--fail-soft)' : item.index % 2 ? 'var(--bg-3)' : 'var(--line-1)' }}
                  title={item.name}
                />
              );
            })}
          </div>
        )}
        <input
          type="range"
          min={0}
          max={Math.max(0, length - 1)}
          value={index}
          disabled={disabled}
          onChange={(event) => seekIndex(Number(event.target.value))}
          aria-label="Scan position"
          aria-valuetext={`scan ${index + 1} of ${length}, ${formatSeconds(t)}`}
          className="relative w-full transport-range"
        />
      </div>

      <span className="num text-fg-1 min-w-24 text-right" aria-live="polite">
        {formatSeconds(t)} · {length ? index + 1 : 0}/{length}
      </span>
      {phase && (
        <span className="text-xs text-fg-2 truncate max-w-48 hidden md:inline" title={phase.name}>
          {phase.name}
        </span>
      )}
      <Button
        size="xs"
        variant={loop ? 'primary' : 'ghost'}
        disabled={disabled || !phase}
        onClick={() => setLoop(loop ? null : phase ? [phase.startIdx, phase.endIdx] : null)}
        title="Loop the current phase"
        aria-pressed={Boolean(loop)}
      >
        <Repeat size={12} /> Loop
      </Button>
      <select
        value={speed}
        onChange={(event) => setSpeed(Number(event.target.value) as PlaybackSpeed)}
        aria-label="Playback speed"
        className="h-6 px-1 rounded-control bg-bg-2 border border-line-1 text-2xs num"
      >
        {speeds.map((item) => (
          <option key={item} value={item}>
            {item}×
          </option>
        ))}
      </select>
      {trace?.axisReconstructed && (
        <StatusPill tone="warn" icon={null} title="The seconds axis was reconstructed because scenario cases could not be matched to their samples.">
          reconstructed axis
        </StatusPill>
      )}
    </div>
  );
}
