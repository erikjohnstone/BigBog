/**
 * What the engineer is looking at, as removable chips the model receives
 * as plain context lines. Derived from the shared selection and clock.
 */

import type { ControlGraph } from '../../api/client';
import type { SelectionState } from '../../stores/selection';
import type { Trace } from '../../stores/trace';
import type { TimeCursorState } from '../../stores/timeCursor';
import { phaseAt } from '../../trace/build-trace';
import type { ContextChip } from '../../stores/assistant';

export function buildContextChips(
  selection: Pick<SelectionState, 'blockIds' | 'assertionId'>,
  cursor: Pick<TimeCursorState, 'index' | 't' | 'traceId'>,
  trace: Trace | undefined,
  graph: ControlGraph | undefined,
  stage: string,
): ContextChip[] {
  const chips: ContextChip[] = [{ id: 'stage', label: `Stage: ${stage}`, text: `The engineer is on the ${stage} stage.` }];
  const blocks = [...selection.blockIds];
  if (blocks.length > 0) {
    const described = blocks.slice(0, 6).map((id) => {
      const block = graph?.blocks.find((item) => item.id === id);
      return block ? `${id} (${block.kind}, "${block.label}")` : id;
    });
    chips.push({ id: 'blocks', label: blocks.length === 1 ? `Block ${blocks[0]}` : `${blocks.length} blocks`, text: `Selected blocks: ${described.join('; ')}.` });
  }
  if (trace && cursor.traceId === trace.id) {
    const phase = phaseAt(trace, cursor.index);
    chips.push({
      id: 'time',
      label: phase ? `${phase.name} · ${cursor.t}s` : `t = ${cursor.t}s`,
      text: `Clock at scan ${cursor.index + 1} of ${trace.time.length}, t = ${cursor.t} s${phase ? `, phase "${phase.name}"` : ''}.`,
    });
  }
  if (selection.assertionId && trace) {
    const assertion = trace.assertions.find((item) => item.id === selection.assertionId);
    if (assertion) {
      chips.push({
        id: 'assertion',
        label: `${assertion.passed ? 'Assertion' : 'Failing'}: ${assertion.name}`,
        text: `${assertion.passed ? 'Assertion' : 'Failing assertion'} "${assertion.name}": observed ${assertion.observed}, expected ${assertion.expected}.`,
      });
    }
  }
  return chips;
}
