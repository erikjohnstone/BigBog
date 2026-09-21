import { Compass } from 'lucide-react';
import { useParams } from 'react-router-dom';

import { EmptyState } from '../../../design-system/states';

/** The ctrl-flow design pipeline moves here in Phase 6. */
export function DesignFlow() {
  const { templateId } = useParams();
  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-5xl mx-auto px-6 py-8">
        <p className="eyebrow">Design</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">
          Design with template <span className="font-mono text-base text-fg-1">{templateId}</span>
        </h1>
        <EmptyState
          icon={<Compass size={28} strokeWidth={1.5} />}
          title="The design pipeline is being rebuilt"
          detail={
            <span>
              Configure, brief, reconcile points, review requirements, and approve oracles through{' '}
              <a className="text-accent" href="/">the legacy Libraries tab</a> for now.
            </span>
          }
        />
      </div>
    </div>
  );
}
