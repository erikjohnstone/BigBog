import { Crosshair } from 'lucide-react';

import type { TestReport } from '../../api/client';
import { Button, StatusPill } from '../../design-system/primitives';
import { useSelection } from '../../stores/selection';
import type { Trace } from '../../stores/trace';
import { useTimeCursor } from '../../stores/timeCursor';

/** Declared faults, their targets, and where in the trace they were active. */
export function FaultMatrix({ report, trace }: { report: TestReport; trace?: Trace }) {
  const coverage = report.coverage?.fault_injection;
  const selectBlocks = useSelection((state) => state.selectBlocks);
  if (!coverage || coverage.declarations.length === 0) {
    return (
      <p className="p-4 text-sm text-fg-2">
        {coverage?.interpretation ?? 'No fault behavior was exercised by this acceptance suite.'}
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-3 p-4">
      <div className="flex items-center gap-3 flex-wrap text-sm">
        <span className="inline-flex items-baseline gap-1">
          <span className="text-2xl font-semibold num">{coverage.fault_cases_passed}</span>
          <span className="text-fg-1">of {coverage.fault_case_count} fault cases passed</span>
        </span>
        <span className="num text-fg-2">{coverage.activation_count} activations</span>
        <span className="text-xs text-fg-2">{coverage.interpretation}</span>
      </div>
      <table className="w-full text-sm">
        <thead className="text-left">
          <tr className="hairline-b">
            <th className="eyebrow px-2 h-8 font-semibold">Fault</th>
            <th className="eyebrow px-2 h-8 font-semibold">Kind</th>
            <th className="eyebrow px-2 h-8 font-semibold">Target</th>
            <th className="eyebrow px-2 h-8 font-semibold">Case · phase</th>
            <th className="eyebrow px-2 h-8 font-semibold">Active windows</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line-1">
          {coverage.declarations.map((declaration, index) => {
            const windows = (trace?.faultWindows ?? []).filter((window) => window.id === declaration.id);
            return (
              <tr key={`${declaration.id}-${index}`} className="hover:bg-bg-2">
                <td className="px-2 h-8 font-mono text-xs">{declaration.id}</td>
                <td className="px-2">
                  <StatusPill tone="warn" icon={null}>{declaration.kind}</StatusPill>
                </td>
                <td className="px-2">
                  <button type="button" className="font-mono text-xs text-accent" onClick={() => selectBlocks([declaration.target])}>
                    {declaration.target}
                  </button>
                  {declaration.quality_target && <span className="text-2xs text-fg-2"> · quality {declaration.quality_target}</span>}
                </td>
                <td className="px-2 text-xs text-fg-1">
                  {declaration.case}
                  {declaration.phase ? ` · ${declaration.phase}` : ''}
                </td>
                <td className="px-2">
                  {windows.length === 0 ? (
                    <span className="text-2xs text-fg-2">not observed in samples</span>
                  ) : (
                    <span className="inline-flex gap-1 flex-wrap">
                      {windows.map((window) => (
                        <Button
                          key={window.startIdx}
                          size="xs"
                          variant="ghost"
                          onClick={() => {
                            useTimeCursor.getState().pause();
                            useTimeCursor.getState().seekIndex(window.startIdx);
                            selectBlocks([declaration.target]);
                          }}
                          title="Seek to this activation"
                        >
                          <Crosshair size={11} />
                          <span className="num">
                            {trace!.time[window.startIdx]}s – {trace!.time[window.endIdx]}s
                          </span>
                        </Button>
                      ))}
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {coverage.recovery_phases.length > 0 && (
        <p className="text-xs text-fg-2">
          Recovery phases: <span className="font-mono">{coverage.recovery_phases.join(', ')}</span>
        </p>
      )}
    </div>
  );
}
