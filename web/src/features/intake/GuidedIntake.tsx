import { Upload } from 'lucide-react';

import { EmptyState } from '../../design-system/states';

/**
 * Guided intake lands in Phase 6. Until then the page is explicit about it
 * and points at the legacy intake, which still creates jobs.
 */
export function GuidedIntake() {
  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-5xl mx-auto px-6 py-8">
        <p className="eyebrow">New job</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Guided intake</h1>
        <EmptyState
          icon={<Upload size={28} strokeWidth={1.5} />}
          title="Guided intake is being rebuilt"
          detail={
            <span>
              Jobs are still created from contractor documents through the legacy intake at{' '}
              <a className="text-accent" href="/">the legacy workbench</a>. They appear in Jobs here once created.
            </span>
          }
        />
      </div>
    </div>
  );
}
