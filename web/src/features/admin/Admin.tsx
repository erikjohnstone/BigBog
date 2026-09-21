import { useAuditStatus, useIntegrationAudit, useOptionalCapabilities, useReadiness, useSecurityStatus } from '../../api/queries';
import { StatusPill } from '../../design-system/primitives';
import { ErrorState, LoadingState } from '../../design-system/states';
import { KeyValue, SectionCard, StageFrame } from '../shared/StageFrame';

/** Administration: security posture, the audit chain, optional capabilities, integration use audit, and integration maturity. */
export function Admin() {
  const security = useSecurityStatus();
  const capabilities = useOptionalCapabilities();
  const readiness = useReadiness();
  const audit = useAuditStatus();
  const integration = useIntegrationAudit();

  if (security.isLoading || readiness.isLoading) return <LoadingState label="Loading system status" />;
  if (security.isError) return <ErrorState error={security.error} onRetry={() => security.refetch()} />;
  if (readiness.isError) return <ErrorState error={readiness.error} onRetry={() => readiness.refetch()} />;

  const sec = security.data;
  const components = readiness.data?.components ?? [];

  return (
    <StageFrame wide>
      <header>
        <p className="eyebrow">System</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Administration</h1>
      </header>

      {sec && (
        <SectionCard
          title="Security"
          aside={<StatusPill tone={sec.live_writes_enabled ? 'fail' : 'ok'}>{sec.live_writes_enabled ? 'live writes enabled' : 'live writes off'}</StatusPill>}
        >
          <KeyValue
            items={[
              { label: 'Mode', value: sec.mode },
              { label: 'Authentication', value: sec.authentication_enabled ? 'enabled' : 'disabled' },
              { label: 'HTTPS required', value: sec.https_required ? 'yes' : 'no' },
              { label: 'Credentials', value: <span className="num">{sec.configured_credentials}</span> },
              { label: 'Review identity', value: sec.review_identity },
            ]}
          />
        </SectionCard>
      )}

      <SectionCard
        title="Audit chain"
        aside={audit.data && <StatusPill tone={audit.data.valid ? 'ok' : 'fail'}>{audit.data.valid ? 'chain intact' : 'chain broken'}</StatusPill>}
      >
        {audit.isLoading ? (
          <LoadingState compact />
        ) : audit.isError || !audit.data ? (
          <ErrorState compact error={audit.error ?? 'Unavailable'} onRetry={() => audit.refetch()} />
        ) : (
          <>
            <KeyValue
              items={[
                { label: 'Events', value: <span className="num">{audit.data.event_count}</span> },
                { label: 'Head hash', value: <span className="num break-all">{audit.data.head_hash}</span> },
                {
                  label: 'External retention',
                  value: audit.data.external_immutable_retention ? <StatusPill tone="ok">immutable copy retained</StatusPill> : <span className="text-fg-1">Local chain only. Configure external immutable retention before relying on it as evidence.</span>,
                },
              ]}
            />
            <p className="px-4 pb-3 text-xs text-fg-2">Every approval, rejection, export, and probe appends a hash-linked event. The chain is re-verified on each request for this status.</p>
          </>
        )}
      </SectionCard>

      <SectionCard title="Optional capabilities">
        {capabilities.isLoading ? (
          <LoadingState compact />
        ) : capabilities.isError || !capabilities.data ? (
          <ErrorState compact error={capabilities.error ?? 'Unavailable'} onRetry={() => capabilities.refetch()} />
        ) : (
          <ul className="divide-y divide-line-1">
            {capabilities.data.dependencies.map((cap) => (
              <li key={cap.capability} className="flex items-center gap-3 px-4 h-10 text-sm">
                <span className="w-56 truncate">{cap.capability}</span>
                <span className="font-mono text-2xs text-fg-2 truncate">{cap.distribution}{cap.version ? ` ${cap.version}` : ''}</span>
                <span className="flex-1" />
                {cap.installed ? (
                  <StatusPill tone="ok">installed</StatusPill>
                ) : (
                  <span className="inline-flex items-center gap-2">
                    <StatusPill tone="offline">not installed</StatusPill>
                    {cap.remediation && <code className="text-2xs text-fg-2">{cap.remediation}</code>}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </SectionCard>

      <SectionCard
        title="Integration use audit"
        aside={integration.data && <StatusPill tone={integration.data.passed ? 'ok' : 'fail'}>{integration.data.passed ? `${integration.data.bound_component_count}/${integration.data.pinned_component_count} bound` : 'unbound components'}</StatusPill>}
      >
        {integration.isLoading ? (
          <LoadingState compact />
        ) : integration.isError || !integration.data ? (
          <ErrorState compact error={integration.error ?? 'Unavailable'} onRetry={() => integration.refetch()} />
        ) : (
          <>
            <p className="px-4 py-3 text-xs text-fg-1">{integration.data.policy}</p>
            {(integration.data.missing_bindings.length > 0 || integration.data.stale_bindings.length > 0) && (
              <p className="px-4 pb-3 text-xs text-fail">
                Missing: {integration.data.missing_bindings.join(', ') || 'none'} · Stale: {integration.data.stale_bindings.join(', ') || 'none'}
              </p>
            )}
            <table className="w-full text-sm">
              <thead className="text-left">
                <tr className="hairline-b">
                  <th className="eyebrow px-4 h-8 font-semibold">Component</th>
                  <th className="eyebrow px-4 h-8 font-semibold">Mode</th>
                  <th className="eyebrow px-4 h-8 font-semibold">Product path</th>
                  <th className="eyebrow px-4 h-8 font-semibold">Proof</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line-1">
                {integration.data.components.map((component) => (
                  <tr key={component.id} className={component.bound ? undefined : 'text-fg-2'}>
                    <td className="px-4 py-2 align-top">
                      <span className="block">{component.id}</span>
                      <span className="block font-mono text-2xs text-fg-2 truncate max-w-48">{component.revision_or_package ?? ''}</span>
                      <span className="block text-2xs text-fg-2">{component.license ?? ''}</span>
                    </td>
                    <td className="px-4 py-2 align-top text-xs">
                      <StatusPill tone={component.bound ? 'ok' : 'offline'} icon={null}>
                        {component.mode ?? (component.bound ? 'bound' : 'unbound')}
                      </StatusPill>
                    </td>
                    <td className="px-4 py-2 align-top text-xs max-w-md">{component.product_path ?? '—'}</td>
                    <td className="px-4 py-2 align-top">
                      <code className="text-2xs text-fg-1 break-all">{component.proof ?? '—'}</code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </SectionCard>

      <SectionCard
        title="Integration maturity"
        aside={<span className="text-xs text-fg-2">{readiness.data?.policy}</span>}
      >
        <table className="w-full text-sm">
          <thead className="text-left">
            <tr className="hairline-b">
              <th className="eyebrow px-4 h-8 font-semibold">Component</th>
              <th className="eyebrow px-4 h-8 font-semibold">Role</th>
              <th className="eyebrow px-4 h-8 font-semibold">Stage</th>
              <th className="eyebrow px-4 h-8 font-semibold">License</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line-1">
            {components.map((component) => (
              <tr key={component.id} className={component.selected ? undefined : 'text-fg-2'}>
                <td className="px-4 h-9 align-top py-2">
                  <span className="block truncate">{component.name}</span>
                  <span className="block font-mono text-2xs text-fg-2">{component.id}{component.version ? ` · ${component.version}` : ''}</span>
                </td>
                <td className="px-4 py-2 text-xs max-w-md">
                  <span className="block">{component.role}</span>
                  {component.blocker && <span className="block mt-1 text-warn">{component.blocker}</span>}
                </td>
                <td className="px-4">
                  <StatusPill
                    tone={
                      ['verified', 'field-qualified', 'production-supported'].includes(component.stage)
                        ? 'ok'
                        : component.installed
                          ? 'info'
                          : 'offline'
                    }
                    icon={null}
                  >
                    {component.stage}
                  </StatusPill>
                </td>
                <td className="px-4 text-xs whitespace-nowrap">{component.license}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </SectionCard>
    </StageFrame>
  );
}
