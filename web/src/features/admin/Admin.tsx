import { useOptionalCapabilities, useReadiness, useSecurityStatus } from '../../api/queries';
import { StatusPill } from '../../design-system/primitives';
import { ErrorState, LoadingState } from '../../design-system/states';
import { KeyValue, SectionCard, StageFrame } from '../shared/StageFrame';

/** Administration: security posture, optional capabilities, integration maturity. */
export function Admin() {
  const security = useSecurityStatus();
  const capabilities = useOptionalCapabilities();
  const readiness = useReadiness();

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
