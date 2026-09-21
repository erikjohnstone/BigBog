import { FlaskConical } from 'lucide-react';
import { useState } from 'react';

import type { ControlGraph } from '../../api/client';
import { Button } from '../../design-system/primitives';
import { BacnetLabCard } from './BacnetLabCard';
import { EvidenceCockpit } from './EvidenceCockpit';
import type { EvidenceKind } from './EvidenceCockpit';
import { JobProgress } from './JobProgress';
import { QualificationWizard } from './QualificationWizard';
import type { QualificationKind } from './QualificationWizard';

/**
 * The Test stage's simulation panel: live job progress, retained
 * high-fidelity evidence, the virtual BACnet lab, and the wizard that queues
 * a new qualification. Everything here is marked simulated.
 */
export function SimulationCenter({ runId, graph, onLoadTrace }: { runId: string; graph: ControlGraph | undefined; onLoadTrace: (kind: EvidenceKind) => void }) {
  const [wizard, setWizard] = useState<{ kind: QualificationKind; nonce: number } | null>(null);
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
        </header>
        <JobProgress runId={runId} />
      </section>
      <EvidenceCockpit runId={runId} onLoad={onLoadTrace} />
      <section className="panel" aria-label="BACnet lab">
        <h3 className="px-4 h-9 flex items-center text-xs font-medium hairline-b">Virtual BACnet lab</h3>
        <BacnetLabCard runId={runId} />
      </section>
      {wizard && <QualificationWizard key={`${wizard.kind}:${wizard.nonce}`} runId={runId} graph={graph} kind={wizard.kind} open onOpenChange={(open) => !open && setWizard(null)} />}
    </div>
  );
}
