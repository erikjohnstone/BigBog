import { Check, Crosshair, X } from 'lucide-react';

import type { ControlGraph } from '../../api/client';
import { cn } from '../../design-system/cn';
import { Button } from '../../design-system/primitives';
import { useSelection } from '../../stores/selection';
import type { Trace } from '../../stores/trace';
import { useTimeCursor } from '../../stores/timeCursor';
import { upstream } from '../wiresheet/graph-model';

/** Every assertion grouped by phase; clicking one seeks and highlights. */
export function AssertionList({ trace, graph }: { trace: Trace; graph?: ControlGraph }) {
  const assertionId = useSelection((state) => state.assertionId);
  const jump = (id: string) => {
    const assertion = trace.assertions.find((item) => item.id === id);
    if (!assertion) return;
    useTimeCursor.getState().jumpToFailure(id);
    const selection = useSelection.getState();
    selection.setAssertion(id);
    if (assertion.blockIds[0]) {
      selection.selectBlocks(assertion.blockIds);
      if (graph) {
        const path = upstream(graph, assertion.blockIds[0]);
        selection.setHighlight(path.blockIds, path.linkKeys);
      }
    }
  };
  const failing = trace.assertions.filter((item) => !item.passed);
  return (
    <div className="p-4 flex flex-col gap-3">
      <div className="flex items-center gap-3 text-sm">
        <span className="inline-flex items-baseline gap-1">
          <span className={cn('text-2xl font-semibold num', failing.length > 0 ? 'text-fail' : 'text-ok')}>{trace.assertions.length - failing.length}</span>
          <span className="text-fg-1">of {trace.assertions.length} assertions passed</span>
        </span>
        {failing.length > 0 && (
          <Button size="sm" variant="danger" onClick={() => jump(failing[0].id)}>
            <Crosshair size={12} /> First failure
          </Button>
        )}
      </div>
      {trace.phases.map((phase) => {
        const items = trace.assertions.filter((item) => item.phaseIndex === phase.index);
        if (items.length === 0) return null;
        return (
          <section key={phase.index}>
            <h2 className="eyebrow mb-1">{phase.name}</h2>
            <ul className="flex flex-col divide-y divide-line-1">
              {items.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => jump(item.id)}
                    aria-current={assertionId === item.id ? 'true' : undefined}
                    className={cn('w-full text-left flex items-center gap-3 px-2 h-9 text-sm hover:bg-bg-2 rounded-control', assertionId === item.id && 'bg-accent-soft')}
                  >
                    {item.passed ? <Check size={14} className="text-ok shrink-0" /> : <X size={14} className="text-fail shrink-0" />}
                    <span className="flex-1 min-w-0 truncate">{item.name}</span>
                    <span className="num text-fg-2 shrink-0">observed {item.observed}</span>
                    <span className="num text-fg-2 shrink-0">expected {item.expected}</span>
                    {item.blockIds[0] && <span className="font-mono text-2xs text-fg-2 shrink-0">{item.blockIds[0]}</span>}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
