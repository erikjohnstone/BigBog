import { Plus, Trash2 } from 'lucide-react';
import { z } from 'zod';

import { Button, Input, NativeSelect } from '../../../design-system/primitives';
import type { AcceptanceCase, Expectation, Operator } from '../../../stores/intake';
import { KeyValueEditor } from './KeyValueEditor';
import { JsonDisclosure } from './JsonDisclosure';

const operators: Operator[] = ['eq', 'lt', 'le', 'gt', 'ge', 'between'];

const caseSchema = z.array(
  z.object({
    name: z.string(),
    inputs: z.record(z.string(), z.union([z.number(), z.boolean()])).default({}),
    expectations: z
      .array(
        z.object({
          target: z.string(),
          operator: z.enum(['eq', 'lt', 'le', 'gt', 'ge', 'between']),
          value: z.union([z.number(), z.boolean()]),
          upper: z.number().nullable().optional(),
          tolerance: z.number().optional(),
        }),
      )
      .default([]),
    repeat: z.number().int().positive().default(1),
    step_seconds: z.number().positive().default(1),
  }),
);

function parseScalar(text: string): number | boolean {
  const trimmed = text.trim().toLowerCase();
  if (trimmed === 'true') return true;
  if (trimmed === 'false') return false;
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : 0;
}

/**
 * Engineer-authored acceptance cases: inputs held for `repeat` scans of
 * `step_seconds`, then expectations on outputs. Structured first, JSON
 * disclosure for experts.
 */
export function AcceptanceTestsEditor({
  cases,
  onChange,
  pointNames,
  error,
}: {
  cases: AcceptanceCase[];
  onChange: (cases: AcceptanceCase[]) => void;
  pointNames: string[];
  error?: string;
}) {
  const update = (index: number, patch: Partial<AcceptanceCase>) => onChange(cases.map((item, i) => (i === index ? { ...item, ...patch } : item)));
  const updateExpectation = (caseIndex: number, index: number, patch: Partial<Expectation>) =>
    update(caseIndex, { expectations: cases[caseIndex].expectations.map((item, i) => (i === index ? { ...item, ...patch } : item)) });

  return (
    <div className="flex flex-col gap-3">
      {cases.map((testCase, caseIndex) => (
        <section key={caseIndex} className="rounded-panel border border-line-1 p-3 flex flex-col gap-3" aria-label={`Acceptance case ${caseIndex + 1}`}>
          <div className="grid grid-cols-[1fr_auto_auto_auto] gap-2 items-end">
            <label className="flex flex-col gap-1 text-xs text-fg-1">
              Case name
              <Input value={testCase.name} onChange={(event) => update(caseIndex, { name: event.target.value })} placeholder="occupied cooling" />
            </label>
            <label className="flex flex-col gap-1 text-xs text-fg-1">
              Repeat
              <Input type="number" min={1} value={testCase.repeat} onChange={(event) => update(caseIndex, { repeat: Math.max(1, Number(event.target.value) || 1) })} className="w-20" mono />
            </label>
            <label className="flex flex-col gap-1 text-xs text-fg-1">
              Step (s)
              <Input type="number" min={0.001} step="any" value={testCase.step_seconds} onChange={(event) => update(caseIndex, { step_seconds: Math.max(0.001, Number(event.target.value) || 1) })} className="w-24" mono />
            </label>
            <Button size="icon" variant="ghost" onClick={() => onChange(cases.filter((_, i) => i !== caseIndex))} aria-label={`Remove case ${caseIndex + 1}`}>
              <Trash2 size={13} />
            </Button>
          </div>
          <div>
            <h4 className="eyebrow mb-1">Inputs held during the case</h4>
            <KeyValueEditor
              rows={Object.entries(testCase.inputs).map(([key, value]) => ({ key, value: String(value) }))}
              onChange={(rows) => update(caseIndex, { inputs: Object.fromEntries(rows.filter((row) => row.key.trim()).map((row) => [row.key.trim(), parseScalar(row.value)])) })}
              keyLabel="Point"
              valueLabel="Value"
              keyPlaceholder="ZoneTemp"
              valuePlaceholder="76 or true"
              suggestions={pointNames}
            />
          </div>
          <div>
            <h4 className="eyebrow mb-1">Expectations at the end of the case</h4>
            <div className="flex flex-col gap-1.5">
              {testCase.expectations.map((expectation, index) => (
                <div key={index} className="grid grid-cols-[1fr_auto_auto_auto_auto_auto] gap-2 items-center">
                  <Input value={expectation.target} onChange={(event) => updateExpectation(caseIndex, index, { target: event.target.value })} placeholder="DamperCommand" aria-label={`Expectation ${index + 1} target`} mono list="kv-suggestions" />
                  <NativeSelect size="md" value={expectation.operator} onChange={(event) => updateExpectation(caseIndex, index, { operator: event.target.value as Operator })} aria-label={`Expectation ${index + 1} operator`} className="w-28">
                    {operators.map((operator) => (
                      <option key={operator} value={operator}>
                        {operator}
                      </option>
                    ))}
                  </NativeSelect>
                  <Input value={String(expectation.value)} onChange={(event) => updateExpectation(caseIndex, index, { value: parseScalar(event.target.value) })} placeholder="100" aria-label={`Expectation ${index + 1} value`} mono className="w-24" />
                  {expectation.operator === 'between' ? (
                    <Input type="number" step="any" value={expectation.upper ?? ''} onChange={(event) => updateExpectation(caseIndex, index, { upper: Number(event.target.value) })} placeholder="upper" aria-label={`Expectation ${index + 1} upper`} mono className="w-24" />
                  ) : (
                    <span />
                  )}
                  <Input type="number" step="any" min={0} value={expectation.tolerance ?? 0} onChange={(event) => updateExpectation(caseIndex, index, { tolerance: Number(event.target.value) || 0 })} aria-label={`Expectation ${index + 1} tolerance`} mono className="w-20" title="Tolerance" />
                  <Button size="icon" variant="ghost" onClick={() => update(caseIndex, { expectations: testCase.expectations.filter((_, i) => i !== index) })} aria-label={`Remove expectation ${index + 1}`}>
                    <Trash2 size={13} />
                  </Button>
                </div>
              ))}
              <div>
                <Button size="sm" variant="outline" onClick={() => update(caseIndex, { expectations: [...testCase.expectations, { target: '', operator: 'eq', value: 0, tolerance: 0 }] })}>
                  <Plus size={13} /> Expectation
                </Button>
              </div>
            </div>
          </div>
        </section>
      ))}
      <div className="flex items-center gap-2">
        <Button size="sm" variant="secondary" onClick={() => onChange([...cases, { name: '', inputs: {}, expectations: [], repeat: 1, step_seconds: 1 }])}>
          <Plus size={13} /> Acceptance case
        </Button>
        {error && <span role="alert" className="text-2xs text-fail">{error}</span>}
      </div>
      <JsonDisclosure<AcceptanceCase[]>
        value={cases}
        onCommit={onChange}
        validate={(parsed) => {
          const result = caseSchema.safeParse(parsed);
          return result.success ? (result.data as AcceptanceCase[]) : result.error.issues.map((issue) => `${issue.path.join('.')}: ${issue.message}`).join('; ');
        }}
      />
    </div>
  );
}
