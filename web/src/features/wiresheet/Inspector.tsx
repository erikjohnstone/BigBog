import { Check, Crosshair, X } from 'lucide-react';

import type { ControlGraph, RunDetail, TestReport } from '../../api/client';
import { cn } from '../../design-system/cn';
import { Button, Kbd, StatusPill } from '../../design-system/primitives';
import { useSelection } from '../../stores/selection';
import { useSignalValue, formatSignalValue } from '../../stores/trace';
import type { Trace } from '../../stores/trace';
import { useTimeCursor } from '../../stores/timeCursor';
import { familyColor, familyLabel, upstream } from './graph-model';
import type { BlockNode, PortSpec } from './graph-model';

function LiveValue({ signalId, trace, unit }: { signalId?: string; trace?: Trace; unit?: string }) {
  const value = useSignalValue(signalId);
  const signal = signalId ? trace?.signals.get(signalId) : undefined;
  if (!signalId) return <span className="text-fg-2 text-2xs">no sample</span>;
  const text = formatSignalValue(value, signal);
  return (
    <span className={cn('num', signal?.kind === 'boolean' && (value === 1 ? 'text-m-status' : 'text-fg-2'))}>
      {text}
      {unit && signal?.kind !== 'boolean' && !Number.isNaN(value) ? ` ${unit}` : ''}
    </span>
  );
}

function PortRow({ port, trace, unit, direction }: { port: PortSpec; trace?: Trace; unit?: string; direction: 'in' | 'out' }) {
  return (
    <li className="flex items-center gap-2 h-7 text-xs">
      <span className={cn('size-1.5 rounded-pill', port.type === 'boolean' ? 'bg-m-status' : 'bg-m-cmd')} aria-hidden />
      <span className="font-mono">{port.name}</span>
      <span className="text-2xs text-fg-2">{port.type}</span>
      <span className="flex-1" />
      {direction === 'in' ? (
        <span className="font-mono text-2xs text-fg-2 truncate max-w-40">{port.from ?? 'unlinked'}</span>
      ) : (
        <LiveValue signalId={port.signalId} trace={trace} unit={unit} />
      )}
    </li>
  );
}

/** Everything the server knows about the selected block, plus its live values. */
export function Inspector({
  graph,
  nodes,
  trace,
  report,
  run,
}: {
  graph: ControlGraph;
  nodes: BlockNode[];
  trace?: Trace;
  report?: TestReport;
  run: RunDetail;
}) {
  const selected = useSelection((state) => state.blockIds);
  const setAssertion = useSelection((state) => state.setAssertion);
  const setHighlight = useSelection((state) => state.setHighlight);
  const selectBlocks = useSelection((state) => state.selectBlocks);
  const jumpToFailure = useTimeCursor((state) => state.jumpToFailure);
  const id = [...selected][0];
  const node = nodes.find((item) => item.id === id);

  if (!node) {
    return (
      <div className="h-full flex flex-col">
        <header className="px-3 h-9 flex items-center hairline-b">
          <span className="eyebrow">Inspector</span>
        </header>
        <div className="p-4 text-sm text-fg-2 flex flex-col gap-3">
          <p>Select a block to see its ports, configuration, coverage, and the assertions that observe it.</p>
          <ul className="text-xs flex flex-col gap-1">
            <li><Kbd>/</Kbd> find a block</li>
            <li><Kbd>←</Kbd> <Kbd>→</Kbd> walk along links</li>
            <li><Kbd>[</Kbd> <Kbd>]</Kbd> step one scan · <Kbd>space</Kbd> play</li>
            <li><Kbd>T</Kbd> tidy · <Kbd>F</Kbd> fit</li>
          </ul>
        </div>
      </div>
    );
  }

  const data = node.data;
  const declarations = (report?.coverage?.fault_injection?.declarations ?? []).filter((item) => item.target === id);
  const assertions = (trace?.assertions ?? []).filter((item) => item.blockIds.includes(id));
  const config = Object.entries(data.config);

  const jump = (assertionId: string) => {
    jumpToFailure(assertionId);
    setAssertion(assertionId);
    const path = upstream(graph, id);
    setHighlight(path.blockIds, path.linkKeys);
    selectBlocks([id]);
  };

  return (
    <div className="h-full overflow-auto text-sm">
      <header className="sticky top-0 z-10 bg-bg-1 hairline-b px-3 h-9 flex items-center gap-2">
        <span className="eyebrow">Inspector</span>
        <span className="flex-1" />
        <span className="size-1.5 rounded-pill" style={{ background: familyColor(data.family) }} aria-hidden />
        <span className="text-2xs text-fg-2">{familyLabel[data.family]}</span>
      </header>

      <section className="px-3 py-3 flex flex-col gap-1 hairline-b">
        <h2 className="text-base font-medium leading-tight">{data.label}</h2>
        <p className="font-mono text-2xs text-fg-2">
          {data.id} · {data.kind}
        </p>
        <div className="flex gap-1 flex-wrap pt-1">
          {data.stateful && <StatusPill tone="neutral" icon={null}>stateful</StatusPill>}
          {data.feedback && <StatusPill tone="neutral" icon={null}>feedback</StatusPill>}
          {data.diff && <StatusPill tone={data.diff === 'added' ? 'info' : data.diff === 'removed' ? 'fail' : 'warn'} icon={null}>{data.diff}</StatusPill>}
          {data.coverage && (
            <StatusPill tone={data.coverage.bothOutcomes ? 'ok' : 'warn'}>
              {data.coverage.bothOutcomes ? 'both outcomes' : `only ${data.coverage.observed.map(String).join(', ') || 'none'}`}
            </StatusPill>
          )}
        </div>
      </section>

      {data.diffFields && data.diffFields.length > 0 && (
        <section className="px-3 py-3 hairline-b">
          <h3 className="eyebrow mb-1">Proposed change</h3>
          <ul className="font-mono text-xs flex flex-col gap-1">
            {data.diffFields.map((field) => (
              <li key={field.field}>
                {field.field}: <span className="text-fail line-through">{String(field.before)}</span> → <span className="text-accent">{String(field.after)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="px-3 py-3 hairline-b">
        <h3 className="eyebrow mb-1">Ports</h3>
        <ul>
          {data.inputs.map((port) => (
            <PortRow key={`in-${port.name}`} port={port} direction="in" trace={trace} />
          ))}
          {data.outputs.map((port) => (
            <PortRow key={`out-${port.name}`} port={port} direction="out" trace={trace} unit={data.unit} />
          ))}
        </ul>
        {data.overrideSignalId && (
          <p className="mt-1 text-2xs text-fg-2 flex items-center gap-2">
            effective (after fault) <LiveValue signalId={data.overrideSignalId} trace={trace} unit={data.unit} />
          </p>
        )}
      </section>

      {config.length > 0 && (
        <section className="px-3 py-3 hairline-b">
          <h3 className="eyebrow mb-1">Configuration</h3>
          <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-xs">
            {config.map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="font-mono text-fg-2">{key}</dt>
                <dd className="num break-all">{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      {data.pointName && (
        <section className="px-3 py-3 hairline-b">
          <h3 className="eyebrow mb-1">Point</h3>
          {(() => {
            const point = run.job.points.find((item) => item.name === data.pointName);
            if (!point) return null;
            return (
              <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-xs">
                <dt className="text-fg-2">Role</dt>
                <dd>{point.role}</dd>
                <dt className="text-fg-2">Units</dt>
                <dd>{point.units ?? '—'}</dd>
                <dt className="text-fg-2">Brick</dt>
                <dd className="font-mono text-2xs">{point.brick_class ?? '—'}</dd>
                <dt className="text-fg-2">BACnet</dt>
                <dd className="font-mono text-2xs">{point.bacnet_object ? `${point.bacnet_device_instance ?? '?'}:${point.bacnet_object}` : 'unmapped'}</dd>
              </dl>
            );
          })()}
        </section>
      )}

      {declarations.length > 0 && (
        <section className="px-3 py-3 hairline-b">
          <h3 className="eyebrow mb-1">Fault declarations targeting this block</h3>
          <ul className="text-xs flex flex-col gap-1">
            {declarations.map((item) => (
              <li key={item.id} className="flex items-center gap-2">
                <StatusPill tone="warn" icon={null}>{item.kind}</StatusPill>
                <span className="font-mono text-2xs">{item.id}</span>
                <span className="text-fg-2 truncate">{item.case}{item.phase ? ` · ${item.phase}` : ''}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="px-3 py-3">
        <h3 className="eyebrow mb-1">Assertions observing this block</h3>
        {assertions.length === 0 ? (
          <p className="text-xs text-fg-2">None. This block is not an acceptance target.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {assertions.map((assertion) => (
              <li key={assertion.id} className="flex items-start gap-2 text-xs">
                {assertion.passed ? <Check size={12} className="text-ok mt-0.5 shrink-0" /> : <X size={12} className="text-fail mt-0.5 shrink-0" />}
                <span className="flex-1 min-w-0">
                  <span className="block truncate">{assertion.name}</span>
                  <span className="block num text-fg-2">
                    observed {assertion.observed} · expected {assertion.expected}
                  </span>
                </span>
                <Button size="xs" variant="ghost" onClick={() => jump(assertion.id)} title="Jump to this assertion and highlight the path that produced it">
                  <Crosshair size={11} /> Jump
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
