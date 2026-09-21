import { Field, Input, Textarea } from '../../../design-system/primitives';
import { useIntake } from '../../../stores/intake';

export function JobStep({ errors }: { errors: Record<string, string> }) {
  const draft = useIntake((state) => state.draft);
  const update = useIntake((state) => state.update);
  return (
    <section className="flex flex-col gap-4">
      <div>
        <p className="eyebrow">Step 1</p>
        <h2 className="text-xl font-semibold tracking-tight">What are we building?</h2>
        <p className="text-sm text-fg-1 mt-1">The job record names the site and the equipment; everything else is derived from the contractor's documents.</p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Field label="Job name" error={errors.name} htmlFor="intake-name">
          <Input id="intake-name" value={draft.name} onChange={(event) => update({ name: event.target.value })} placeholder="East wing VAV-101" autoFocus />
        </Field>
        <Field label="Site" error={errors.site} htmlFor="intake-site">
          <Input id="intake-site" value={draft.site} onChange={(event) => update({ site: event.target.value })} placeholder="Riverview Medical Office" />
        </Field>
        <Field label="Equipment identifier" hint="Becomes the program name; letters, digits, underscores." error={errors.equipmentName} htmlFor="intake-equipment">
          <Input id="intake-equipment" value={draft.equipmentName} onChange={(event) => update({ equipmentName: event.target.value })} placeholder="VAV_101" mono />
        </Field>
        <Field label="Sequence version" hint="Free text recorded with the candidate." htmlFor="intake-version">
          <Input id="intake-version" value={draft.sequenceVersion} onChange={(event) => update({ sequenceVersion: event.target.value })} />
        </Field>
        <Field label="Notes" className="md:col-span-2" htmlFor="intake-notes">
          <Textarea id="intake-notes" value={draft.notes} onChange={(event) => update({ notes: event.target.value })} placeholder="Anything the reviewer should know." rows={3} />
        </Field>
      </div>
    </section>
  );
}
