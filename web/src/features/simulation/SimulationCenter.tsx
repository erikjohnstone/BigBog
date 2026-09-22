import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Cpu, FlaskConical } from 'lucide-react';
import { useId, useState } from 'react';

import { api } from '../../api/client';
import type { ControlGraph, RunDetail, ShadowQualificationRequest } from '../../api/client';
import { keys } from '../../api/queries';
import { Button, Field, Input, NativeSelect, StatusPill } from '../../design-system/primitives';
import { BacnetLabCard } from './BacnetLabCard';
import { EvidenceCockpit } from './EvidenceCockpit';
import type { EvidenceKind } from './EvidenceCockpit';
import { JobProgress } from './JobProgress';
import { QualificationWizard } from './QualificationWizard';
import type { QualificationKind } from './QualificationWizard';

/**
 * Enqueue the Niagara Shadow Runtime on the exported .bog. Three knobs, no
 * wizard: the request is small and everything about it is bog-simulated.
 */
function ShadowRuntimeForm({ runId, onClose }: { runId: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const ids = { policy: useId(), kernel: useId(), bands: useId() };
  const [request, setRequest] = useState<ShadowQualificationRequest>({ policy: 'default', kernel_backend: 'auto', band_set: 'default' });
  const enqueue = useMutation({
    mutationFn: () => api.enqueueShadowQualification(runId, request),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.latestJob(runId) });
      onClose();
    },
  });
  return (
    <form
      className="px-4 py-3 hairline-b flex flex-wrap items-end gap-3"
      aria-label="Shadow Runtime qualification"
      onSubmit={(event) => {
        event.preventDefault();
        enqueue.mutate();
      }}
    >
      <Field label="Policy" htmlFor={ids.policy} className="w-40">
        <Input id={ids.policy} mono value={request.policy} onChange={(event) => setRequest({ ...request, policy: event.target.value })} />
      </Field>
      <Field label="Kernel backend" htmlFor={ids.kernel} className="w-36">
        <NativeSelect id={ids.kernel} size="sm" value={request.kernel_backend} onChange={(event) => setRequest({ ...request, kernel_backend: event.target.value as ShadowQualificationRequest['kernel_backend'] })}>
          <option value="auto">auto</option>
          <option value="python">python</option>
          <option value="jvm">jvm</option>
        </NativeSelect>
      </Field>
      <Field label="Bands" htmlFor={ids.bands} className="w-32">
        <NativeSelect id={ids.bands} size="sm" value={request.band_set} onChange={(event) => setRequest({ ...request, band_set: event.target.value as ShadowQualificationRequest['band_set'] })}>
          <option value="default">default</option>
          <option value="coarse">coarse</option>
        </NativeSelect>
      </Field>
      <StatusPill tone="sim">bog-simulated</StatusPill>
      <span className="flex-1" />
      <Button type="button" size="sm" variant="ghost" onClick={onClose}>
        Close
      </Button>
      <Button type="submit" size="sm" variant="primary" disabled={enqueue.isPending || request.policy.trim() === ''}>
        {enqueue.isPending ? 'Enqueuing…' : 'Enqueue Shadow Runtime'}
      </Button>
      {enqueue.isError && (
        <p role="alert" className="basis-full text-xs text-fail">
          {(enqueue.error as Error).message}
        </p>
      )}
    </form>
  );
}

/**
 * The Test stage's simulation panel: live job progress, retained
 * high-fidelity evidence, the virtual BACnet lab, and the wizard that queues
 * a new qualification. Everything here is marked simulated.
 */
export function SimulationCenter({ run, graph, onLoadTrace }: { run: RunDetail; graph: ControlGraph | undefined; onLoadTrace: (kind: EvidenceKind) => void }) {
  const runId = run.id;
  const [wizard, setWizard] = useState<{ kind: QualificationKind; nonce: number } | null>(null);
  const [shadowOpen, setShadowOpen] = useState(false);
  return (
    <div className="p-3 flex flex-col gap-3" data-testid="simulation-center">
      <section className="panel" aria-label="Qualification job">
        <header className="flex items-center gap-2 px-4 h-9 hairline-b">
          <h3 className="text-xs font-medium">Qualification job</h3>
          <span className="flex-1" />
          <Button size="xs" variant="outline" onClick={() => setWizard({ kind: 'boptest', nonce: Date.now() })}>
            <FlaskConical size={12} /> BOPTEST case
          </Button>
          <Button size="xs" variant="outline" onClick={() => setWizard({ kind: 'alfalfa', nonce: Date.now() })}>
            <FlaskConical size={12} /> FMU on Alfalfa
          </Button>
          <Button size="xs" variant={shadowOpen ? 'secondary' : 'outline'} onClick={() => setShadowOpen((open) => !open)} aria-pressed={shadowOpen} aria-expanded={shadowOpen}>
            <Cpu size={12} /> Shadow Runtime
          </Button>
        </header>
        {shadowOpen && <ShadowRuntimeForm runId={runId} onClose={() => setShadowOpen(false)} />}
        <JobProgress runId={runId} />
      </section>
      <EvidenceCockpit run={run} onLoad={onLoadTrace} />
      <section className="panel" aria-label="BACnet lab">
        <h3 className="px-4 h-9 flex items-center text-xs font-medium hairline-b">Virtual BACnet lab</h3>
        <BacnetLabCard runId={runId} />
      </section>
      {wizard && <QualificationWizard key={`${wizard.kind}:${wizard.nonce}`} runId={runId} graph={graph} kind={wizard.kind} open onOpenChange={(open) => !open && setWizard(null)} />}
    </div>
  );
}
