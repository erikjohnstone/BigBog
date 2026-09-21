import { ChevronRight } from 'lucide-react';
import { useEffect, useState } from 'react';

import { cn } from '../../../design-system/cn';
import { Textarea } from '../../../design-system/primitives';

/**
 * "Expert JSON": the same value as the structured editor above it, editable
 * as text. It parses on blur and hands back a value only when valid.
 */
export function JsonDisclosure<T>({
  value,
  onCommit,
  validate,
  label = 'Expert JSON',
  rows = 8,
}: {
  value: T;
  onCommit: (value: T) => void;
  validate: (parsed: unknown) => T | string;
  label?: string;
  rows?: number;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(() => JSON.stringify(value, null, 2));
  const [error, setError] = useState<string | null>(null);
  const serialized = JSON.stringify(value, null, 2);
  const [lastSerialized, setLastSerialized] = useState(serialized);
  if (serialized !== lastSerialized) {
    setLastSerialized(serialized);
    setText(serialized);
    setError(null);
  }
  useEffect(() => {
    // no-op: keeps hook order stable when the disclosure toggles
  }, [open]);

  const commit = () => {
    try {
      const parsed = JSON.parse(text) as unknown;
      const result = validate(parsed);
      if (typeof result === 'string') {
        setError(result);
        return;
      }
      setError(null);
      onCommit(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Invalid JSON');
    }
  };

  return (
    <div className="rounded-control border border-line-1">
      <button type="button" onClick={() => setOpen((current) => !current)} className="w-full flex items-center gap-2 px-3 h-8 text-xs text-fg-1 hover:text-fg-0" aria-expanded={open}>
        <ChevronRight size={13} className={cn('transition-transform', open && 'rotate-90')} />
        {label}
        <span className="text-2xs text-fg-2">round-trips the structured editor</span>
      </button>
      {open && (
        <div className="p-2 pt-0 flex flex-col gap-1">
          <Textarea mono rows={rows} value={text} onChange={(event) => setText(event.target.value)} onBlur={commit} aria-label={label} spellCheck={false} />
          {error ? <span role="alert" className="text-2xs text-fail">{error}</span> : <span className="text-2xs text-fg-2">Applied when the field loses focus.</span>}
        </div>
      )}
    </div>
  );
}
