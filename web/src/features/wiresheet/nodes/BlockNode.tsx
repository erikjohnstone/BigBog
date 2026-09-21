import { Handle, Position } from '@xyflow/react';
import type { NodeProps } from '@xyflow/react';
import { Binary, Box, Factory, Filter, Hash, Layers, Plug, Repeat, Scale, ShieldAlert, Sigma, Timer, ToggleLeft } from 'lucide-react';
import { memo, useEffect, useRef } from 'react';
import type { CSSProperties, ReactNode } from 'react';

import { cn } from '../../../design-system/cn';
import { bindSignal } from '../../../stores/trace';
import { delayFor } from '../intro/materialize';
import { familyColor, LOD_NODE_CHIPS } from '../graph-model';
import type { BlockNode as BlockNodeType, Family, PortSpec } from '../graph-model';
import { ValueChip } from '../ValueChip';

const glyphs: Record<Family, ReactNode> = {
  io: <Plug size={12} />,
  const: <Hash size={12} />,
  math: <Sigma size={12} />,
  compare: <Scale size={12} />,
  logic: <Binary size={12} />,
  switch: <ToggleLeft size={12} />,
  timing: <Timer size={12} />,
  state: <Layers size={12} />,
  filter: <Filter size={12} />,
  loop: <Repeat size={12} />,
  plant: <Factory size={12} />,
  assert: <ShieldAlert size={12} />,
  unknown: <Box size={12} />,
};

const handleStyle: CSSProperties = { position: 'relative', top: 'auto', left: 'auto', right: 'auto', transform: 'none' };

function InputPort({ port }: { port: PortSpec }) {
  return (
    <div className="flex items-center gap-1.5 h-5 min-w-0">
      <Handle
        type="target"
        id={port.name}
        position={Position.Left}
        isConnectable={false}
        className={port.type === 'boolean' ? 'handle-boolean' : 'handle-numeric'}
        style={handleStyle}
        title={`${port.name}: ${port.type}${port.from ? ` ← ${port.from}` : ' (unlinked)'}`}
      />
      <span className={cn('text-2xs font-mono truncate', port.from ? 'text-fg-1' : 'text-fg-2 italic')}>{port.name}</span>
    </div>
  );
}

function OutputPort({ port, unit }: { port: PortSpec; unit?: string }) {
  return (
    <div className="flex items-center justify-end gap-1.5 h-5 min-w-0">
      <span className="text-2xs font-mono text-fg-1 truncate">{port.name}</span>
      <ValueChip signalId={port.signalId} kind={port.type} unit={unit} group={LOD_NODE_CHIPS} />
      <Handle
        type="source"
        id={port.name}
        position={Position.Right}
        isConnectable={false}
        className={port.type === 'boolean' ? 'handle-boolean' : 'handle-numeric'}
        style={handleStyle}
        title={`${port.name}: ${port.type}`}
      />
    </div>
  );
}

export const BlockNode = memo(function BlockNode({ data, selected }: NodeProps<BlockNodeType>) {
  const wrapper = useRef<HTMLDivElement>(null);

  // Fault halo: pulses while any declared fault targeting this block is active.
  useEffect(() => {
    const element = wrapper.current;
    if (!element || data.faultSignalIds.length === 0) return;
    const active = new Set<string>();
    const unbinders = data.faultSignalIds.map((signalId) =>
      bindSignal({
        element,
        signalId,
        apply: (_element, value) => {
          if (value === 1) active.add(signalId);
          else active.delete(signalId);
          element.classList.toggle('fault-halo', active.size > 0);
        },
      }),
    );
    return () => {
      unbinders.forEach((unbind) => unbind());
      element.classList.remove('fault-halo');
    };
  }, [data.faultSignalIds]);

  const color = familyColor(data.family);
  const style = { '--materialize-delay': `${delayFor(data.rank)}ms`, '--family': color } as CSSProperties;
  const ghost = data.diff === 'removed';
  const configEntries = Object.entries(data.config).filter(([, value]) => value !== null && typeof value !== 'object');

  return (
    <div
      ref={wrapper}
      style={style}
      className={cn(
        'wiresheet-node relative min-w-[176px] max-w-[260px] rounded-control border bg-bg-2 text-fg-0 transition-[box-shadow] duration-[var(--duration-micro)]',
        data.intro && 'materialize',
        selected ? 'border-accent shadow-[0_0_0_2px_var(--accent-soft)]' : 'border-line-2',
        ghost && 'opacity-35 border-dashed',
        data.diff === 'added' && 'border-accent shadow-[0_0_18px_var(--accent-soft)]',
        data.diff === 'modified' && 'border-warn',
        data.isInput && 'rounded-l-pill',
        data.isOutput && 'rounded-r-pill',
      )}
      data-family={data.family}
      data-diff={data.diff}
      aria-label={`${data.label} (${data.kind})`}
    >
      <span aria-hidden className="absolute left-0 top-2 bottom-2 w-0.75 rounded-pill" style={{ background: color }} />
      <header className="flex items-center gap-1.5 px-2.5 pt-1.5 pb-1 min-w-0">
        <span className="text-fg-2 shrink-0" style={{ color }}>
          {glyphs[data.family]}
        </span>
        <span className="text-2xs font-mono text-fg-2 truncate">{data.kind}</span>
        <span className="flex-1" />
        {data.stateful && (
          <span className="text-2xs text-fg-2" title="Stateful: output depends on earlier scans">
            ⟳
          </span>
        )}
        {data.coverage && (
          <span
            className={cn('size-1.5 rounded-pill shrink-0', data.coverage.bothOutcomes ? 'bg-ok' : 'bg-warn')}
            title={
              data.coverage.bothOutcomes
                ? 'Decision coverage: both outcomes observed'
                : `Decision coverage: only ${data.coverage.observed.map(String).join(', ') || 'no outcome'} observed`
            }
            role="img"
            aria-label={data.coverage.bothOutcomes ? 'both outcomes observed' : 'one outcome observed'}
          />
        )}
        {data.diff === 'modified' && (
          <span className="chip text-warn border-warn/40" title={data.diffFields?.map((f) => `${f.field}: ${String(f.before)} → ${String(f.after)}`).join('\n')}>
            ~
          </span>
        )}
        {data.diff === 'added' && <span className="chip text-accent border-accent/40">+</span>}
        {data.diff === 'removed' && <span className="chip text-fail border-fail/40">−</span>}
      </header>
      <div className="px-2.5 pb-1 text-sm leading-tight truncate" title={data.label}>
        {data.label}
      </div>
      {data.pointName && data.pointName !== data.label && (
        <div className="px-2.5 pb-1 text-2xs font-mono text-fg-2 truncate">
          {data.pointName}
          {data.unit ? ` · ${data.unit}` : ''}
        </div>
      )}
      {data.family === 'const' && configEntries.length > 0 && (
        <div className="px-2.5 pb-1.5 num text-fg-1">{configEntries.map(([key, value]) => `${key} = ${String(value)}`).join(' · ')}</div>
      )}
      {data.overrideSignalId && (
        <div className="px-2.5 pb-1 flex items-center gap-1 text-2xs text-fg-2">
          <span>effective</span>
          <ValueChip signalId={data.overrideSignalId} kind={data.outputs[0]?.type ?? 'numeric'} unit={data.unit} className="text-warn" group={LOD_NODE_CHIPS} />
        </div>
      )}
      {(data.inputs.length > 0 || data.outputs.length > 0) && (
        <div className="grid grid-cols-[1fr_auto] gap-x-3 px-1.5 pb-1.5">
          <div className="flex flex-col">
            {data.inputs.map((port) => (
              <InputPort key={port.name} port={port} />
            ))}
          </div>
          <div className="flex flex-col">
            {data.outputs.map((port) => (
              <OutputPort key={port.name} port={port} unit={data.isOutput || data.isInput ? data.unit : undefined} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
});
