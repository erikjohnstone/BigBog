import { memo, useCallback } from 'react';

import { cn } from '../../design-system/cn';
import { useSelection } from '../../stores/selection';
import type { Trace } from '../../stores/trace';
import { mediumColor, symbolFor } from './symbols';
import { useLiveSymbol } from './symbols/live';
import type { SchematicFlow, SchematicLayout } from './types';

function Flow({ flow }: { flow: SchematicFlow }) {
  const ref = useLiveSymbol<SVGGElement>({ speed: flow.flow, temp: flow.temp });
  const points = flow.points.map(([x, y]) => `${x},${y}`).join(' ');
  const color = mediumColor(flow.medium);
  const width = flow.width ?? 8;
  return (
    <g ref={ref} className="schematic-flow" data-medium={flow.medium}>
      <polyline points={points} fill="none" stroke={color} strokeWidth={width} strokeLinejoin="round" strokeLinecap="butt" opacity={0.28} className="flow-body" />
      <polyline points={points} fill="none" stroke={color} strokeWidth={Math.max(2, width * 0.35)} strokeLinejoin="round" className="edge-flow flow-dash" data-idle={flow.flow ? 'false' : 'true'} />
    </g>
  );
}

/**
 * Draws a layout. Symbols animate through CSS variables from the shared
 * clock; clicking a bound symbol selects its block so the wiresheet and
 * trends follow.
 */
export const Schematic = memo(function Schematic({ layout, trace, className }: { layout: SchematicLayout; trace?: Trace; className?: string }) {
  const selected = useSelection((state) => state.blockIds);
  const selectBlocks = useSelection((state) => state.selectBlocks);

  const blockFor = useCallback(
    (signalId: string | undefined) => {
      if (!signalId) return undefined;
      const signal = trace?.signals.get(signalId);
      return signal?.blockId ?? signalId;
    },
    [trace],
  );

  return (
    <svg
      viewBox={`0 0 ${layout.width} ${layout.height}`}
      className={cn('schematic w-full h-full select-none', className)}
      role="img"
      aria-label={layout.title}
      preserveAspectRatio="xMidYMid meet"
    >
      <title>{layout.title}</title>
      <defs>
        <pattern id="schematic-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="6" height="6" fill="var(--bg-2)" />
          <rect width="2" height="6" fill="var(--line-2)" />
        </pattern>
      </defs>
      {layout.flows.map((flow) => (
        <Flow key={flow.id} flow={flow} />
      ))}
      {layout.elements.map((element) => {
        const Symbol = symbolFor[element.type];
        const primary = element.bindings.value ?? element.bindings.position ?? element.bindings.on ?? element.bindings.speed ?? element.bindings.temp;
        const blockId = blockFor(primary);
        const isSelected = blockId ? selected.has(blockId) : false;
        return (
          <Symbol
            key={element.id}
            element={element}
            selected={isSelected}
            onSelect={blockId ? () => selectBlocks([blockId]) : undefined}
          />
        );
      })}
    </svg>
  );
});
