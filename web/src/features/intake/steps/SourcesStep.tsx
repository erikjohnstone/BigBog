import { FileSpreadsheet, FileText, Package, Radio, Upload, X } from 'lucide-react';
import type { ReactNode } from 'react';

import { cn } from '../../../design-system/cn';
import { Button } from '../../../design-system/primitives';
import { useIntake } from '../../../stores/intake';
import type { IntakeFiles } from '../../../stores/intake';

function FilePicker({
  id,
  label,
  hint,
  accept,
  icon,
  required,
  error,
}: {
  id: keyof IntakeFiles;
  label: string;
  hint: string;
  accept: string;
  icon: ReactNode;
  required?: boolean;
  error?: string;
}) {
  const file = useIntake((state) => state.files[id]);
  const setFile = useIntake((state) => state.setFile);
  return (
    <div className={cn('rounded-panel border p-3 flex items-center gap-3', error ? 'border-fail/50' : file ? 'border-ok/40' : 'border-line-1')}>
      <span className="text-fg-2 shrink-0">{icon}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">{label}</span>
          {required && <span className="text-2xs text-fg-2">required</span>}
        </div>
        <p className="text-2xs text-fg-2">{hint}</p>
        {file && (
          <p className="text-xs mt-1 inline-flex items-center gap-2">
            <span className="font-mono">{file.name}</span>
            <span className="num text-fg-2">{(file.size / 1024).toFixed(1)} KB</span>
            <button type="button" className="text-fg-2 hover:text-fail" onClick={() => setFile(id, null)} aria-label={`Remove ${label}`}>
              <X size={12} />
            </button>
          </p>
        )}
        {error && <p role="alert" className="text-2xs text-fail mt-1">{error}</p>}
      </div>
      <label className="shrink-0">
        <input type="file" name={id} accept={accept} className="sr-only" onChange={(event) => setFile(id, event.target.files?.[0] ?? null)} aria-label={`Attach ${label}`} />
        <span className={cn('inline-flex items-center gap-1.5 h-8 px-3 rounded-control border border-line-2 text-sm cursor-pointer hover:bg-bg-2')}>
          <Upload size={13} /> {file ? 'Replace' : 'Attach'}
        </span>
      </label>
    </div>
  );
}

export function SourcesStep({ errors }: { errors: Record<string, string> }) {
  const reset = useIntake((state) => state.reset);
  return (
    <section className="flex flex-col gap-4">
      <div>
        <p className="eyebrow">Step 2</p>
        <h2 className="text-xl font-semibold tracking-tight">Attach the contractor documents</h2>
        <p className="text-sm text-fg-1 mt-1">Files stay in this browser until the job is created. A reload clears them; the rest of the draft is kept.</p>
      </div>
      <FilePicker id="points" label="Points list" hint="CSV or XLSX: name, label, data type, role, units, default, required, BACnet object." accept=".csv,.xlsx,text/csv" icon={<FileSpreadsheet size={18} />} required error={errors.points} />
      <FilePicker id="sequence" label="Sequence of operations" hint="TXT, MD, JSON, DOCX, or PDF. Used to suggest a family and, for AI custom, as the program brief." accept=".txt,.md,.json,.docx,.pdf" icon={<FileText size={18} />} error={errors.sequence} />
      <FilePicker id="bacnet" label="BACnet scan" hint="JSON device and object scan; retained to build the isolated virtual lab." accept=".json,application/json" icon={<Radio size={18} />} />
      <FilePicker id="template" label="Niagara station template" hint="A .bog used only for structural comparison; never executed." accept=".bog" icon={<Package size={18} />} />
      <FilePicker id="environment" label="Environment pack" hint="Contractor environment archive; inspected, never executed." accept=".zip,.json" icon={<Package size={18} />} />
      <div>
        <Button variant="ghost" size="sm" onClick={reset}>
          Clear the draft
        </Button>
      </div>
    </section>
  );
}
