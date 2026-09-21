import { BaseEdge, EdgeLabelRenderer, getBezierPath, useStore } from '@xyflow/react';
import type { EdgeProps } from '@xyflow/react';
import { memo, useCallback } from 'react';
import type { CSSProperties } from 'react';

import { useSelection } from '../../../stores/selection';
import { useSignalRef } from '../../../stores/trace';
import type { Signal } from '../../../stores/trace';
import { delayFor } from '../intro/materialize';
import { LOD_EDGE_FLOW } from '../graph-model';
import type { SignalEdge as SignalEdgeType } from '../graph-model';
import { ValueChip } from '../ValueChip';

const CHIP_MIN_ZOOM = 0.6;

function applyFlow(element: HTMLElement | SVGElement, value: number, signal: Signal | undefined): void {
  let rate = 0;
  if (!Number.isNaN(value)) {
    if (signal?.kind === 'boolean') rate = value ? 1 : 0;
    else {
      const range = Math.max(Math.abs(signal?.min ?? 0), Math.abs(signal?.max ?? 0));
      rate = range > 0 ? Math.min(1, Math.abs(value) / range) : value !== 0 ? 1 : 0;
    }
  }
  const el = element as SVGElement;
  // Quantize: rewriting the rate retimes the CSS animation, which is costly
  // across hundreds of wires, so only a bucket change touches the DOM.
  const bucket = rate === 0 ? '0' : String(Math.max(1, Math.round(rate * 8)) / 8);
  if (el.dataset.rate !== bucket) {
    el.dataset.rate = bucket;
    el.style.setProperty('--flow-rate', bucket);
  }
  const idle = rate === 0 ? 'true' : 'false';
  if (el.dataset.idle !== idle) el.dataset.idle = idle;
}

export const SignalEdge = memo(function SignalEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  selected,
}: EdgeProps<SignalEdgeType>) {
  const [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  const zoom = useStore((state) => state.transform[2]);
  const highlighted = useSelection(useCallback((state) => (data ? state.highlightedLinkKeys.has(data.key) : false), [data]));
  const flowRef = useSignalRef<SVGPathElement>(data?.signalId, applyFlow, LOD_EDGE_FLOW);

  const type = data?.type ?? 'numeric';
  const removed = data?.diff === 'removed';
  const added = data?.diff === 'added';
  const emphasized = selected || highlighted || added;
  const color = emphasized ? 'var(--accent)' : type === 'boolean' ? 'var(--m-status)' : 'var(--m-cmd)';
  const style = { '--materialize-delay': `${delayFor(data?.rank ?? 0) + 80}ms` } as CSSProperties;

  return (
    <g className={data?.intro ? 'materialize-edge' : undefined} style={style} data-diff={data?.diff}>
      <BaseEdge
        id={id}
        path={path}
        style={{
          stroke: color,
          strokeWidth: emphasized ? 2 : 1.25,
          opacity: removed ? 0.35 : 0.7,
          strokeDasharray: removed ? '3 5' : data?.feedback ? '6 4' : undefined,
        }}
      />
      {!removed && (
        <path
          ref={flowRef}
          d={path}
          className="edge-flow"
          data-idle="true"
          style={{ stroke: color, strokeWidth: emphasized ? 2.5 : 2, fill: 'none', pointerEvents: 'none' }}
        />
      )}
      {data?.signalId && zoom >= CHIP_MIN_ZOOM && (
        <EdgeLabelRenderer>
          <div
            className="nodrag nopan absolute"
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`, pointerEvents: 'all' }}
          >
            <ValueChip signalId={data.signalId} kind={type} title={data.key} />
          </div>
        </EdgeLabelRenderer>
      )}
    </g>
  );
});
