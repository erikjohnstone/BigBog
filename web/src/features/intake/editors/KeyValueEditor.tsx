import { Plus, Trash2 } from 'lucide-react';

import { Button, Input } from '../../../design-system/primitives';

export function KeyValueEditor({
  rows,
  onChange,
  keyLabel = 'Name',
  valueLabel = 'Value',
  keyPlaceholder = 'parameter_name',
  valuePlaceholder = '0',
  suggestions,
}: {
  rows: Array<{ key: string; value: string }>;
  onChange: (rows: Array<{ key: string; value: string }>) => void;
  keyLabel?: string;
  valueLabel?: string;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
  suggestions?: string[];
}) {
  const update = (index: number, patch: Partial<{ key: string; value: string }>) => onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  return (
    <div className="flex flex-col gap-1.5">
      {rows.length > 0 && (
        <div className="grid grid-cols-[1fr_1fr_auto] gap-2 text-2xs text-fg-2 px-1">
          <span>{keyLabel}</span>
          <span>{valueLabel}</span>
          <span />
        </div>
      )}
      {rows.map((row, index) => (
        <div key={index} className="grid grid-cols-[1fr_1fr_auto] gap-2 items-center">
          <Input value={row.key} onChange={(event) => update(index, { key: event.target.value })} placeholder={keyPlaceholder} aria-label={`${keyLabel} ${index + 1}`} mono list={suggestions ? 'kv-suggestions' : undefined} />
          <Input value={row.value} onChange={(event) => update(index, { value: event.target.value })} placeholder={valuePlaceholder} aria-label={`${valueLabel} ${index + 1}`} mono />
          <Button size="icon" variant="ghost" onClick={() => onChange(rows.filter((_, i) => i !== index))} aria-label={`Remove row ${index + 1}`}>
            <Trash2 size={13} />
          </Button>
        </div>
      ))}
      {suggestions && suggestions.length > 0 && (
        <datalist id="kv-suggestions">
          {suggestions.map((item) => (
            <option key={item} value={item} />
          ))}
        </datalist>
      )}
      <div>
        <Button size="sm" variant="outline" onClick={() => onChange([...rows, { key: '', value: '' }])}>
          <Plus size={13} /> Add
        </Button>
      </div>
    </div>
  );
}
