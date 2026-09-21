/**
 * Query keys and typed hooks over the API client.
 *
 * Every feature goes through these so cache keys are consistent and a
 * mutation can invalidate exactly the right reads.
 */

import { useQuery } from '@tanstack/react-query';
import type { UseQueryOptions } from '@tanstack/react-query';

import { api } from './client';

export const keys = {
  health: ['health'] as const,
  readiness: ['readiness'] as const,
  capabilities: ['capabilities'] as const,
  optionalCapabilities: ['optional-capabilities'] as const,
  aiStatus: ['ai-status'] as const,
  securityStatus: ['security-status'] as const,
  auditStatus: ['security-audit-status'] as const,
  integrationAudit: ['integration-audit'] as const,
  blockCatalog: ['block-catalog'] as const,
  runs: ['runs'] as const,
  run: (id: string) => ['run', id] as const,
  graph: (id: string) => ['run', id, 'graph'] as const,
  report: (id: string) => ['run', id, 'report'] as const,
  deliverables: (id: string) => ['run', id, 'deliverables'] as const,
  releaseSummary: (id: string) => ['run', id, 'release-summary'] as const,
  graphicsModel: (id: string) => ['run', id, 'graphics-model'] as const,
  graphicsPlan: (id: string) => ['run', id, 'graphics-plan'] as const,
  bacnetLab: (id: string) => ['run', id, 'bacnet-lab'] as const,
  boptest: (id: string) => ['run', id, 'boptest'] as const,
  alfalfa: (id: string) => ['run', id, 'alfalfa'] as const,
  environment: (id: string) => ['run', id, 'environment'] as const,
  latestJob: (id: string) => ['run', id, 'qualification-job', 'latest'] as const,
  job: (id: string) => ['qualification-job', id] as const,
  projects: ['projects'] as const,
  project: (id: string) => ['project', id] as const,
  projectReport: (id: string) => ['project', id, 'report'] as const,
  libraryCatalogs: ['library-catalogs'] as const,
  ctrlFlowTemplates: ['ctrl-flow-templates'] as const,
  ctrlFlowConfiguration: (templateId: string, selections: Record<string, unknown>) => ['ctrl-flow-configuration', templateId, selections] as const,
  g36Parameters: (controllerId: string) => ['g36-parameters', controllerId] as const,
  retainedDesign: ['retained-design'] as const,
  boptestCatalog: ['boptest-catalog'] as const,
};

type Opts<T> = Omit<UseQueryOptions<T, Error, T, readonly unknown[]>, 'queryKey' | 'queryFn'>;

export function useHealth(opts?: Opts<Awaited<ReturnType<typeof api.health>>>) {
  return useQuery({ queryKey: keys.health, queryFn: api.health, staleTime: 30_000, ...opts });
}
export function useReadiness(opts?: Opts<Awaited<ReturnType<typeof api.readiness>>>) {
  return useQuery({ queryKey: keys.readiness, queryFn: api.readiness, staleTime: 60_000, ...opts });
}
export function useOptionalCapabilities() {
  return useQuery({ queryKey: keys.optionalCapabilities, queryFn: api.optionalCapabilities, staleTime: 60_000 });
}
export function useAiStatus() {
  return useQuery({ queryKey: keys.aiStatus, queryFn: api.aiStatus, staleTime: 60_000 });
}
export function useSecurityStatus() {
  return useQuery({ queryKey: keys.securityStatus, queryFn: api.securityStatus, staleTime: 60_000 });
}
export function useRuns(opts?: Opts<Awaited<ReturnType<typeof api.runs>>>) {
  return useQuery({ queryKey: keys.runs, queryFn: api.runs, ...opts });
}
export function useRun(id: string | undefined) {
  return useQuery({ queryKey: keys.run(id ?? ''), queryFn: () => api.run(id!), enabled: Boolean(id) });
}
export function useBlockCatalog() {
  return useQuery({ queryKey: keys.blockCatalog, queryFn: api.blockCatalog, staleTime: Infinity });
}
export function useGraph(id: string | undefined) {
  return useQuery({ queryKey: keys.graph(id ?? ''), queryFn: () => api.graph(id!), enabled: Boolean(id), staleTime: Infinity });
}
export function useReport(id: string | undefined) {
  return useQuery({ queryKey: keys.report(id ?? ''), queryFn: () => api.report(id!), enabled: Boolean(id), staleTime: Infinity });
}
export function useDeliverables(id: string | undefined) {
  return useQuery({ queryKey: keys.deliverables(id ?? ''), queryFn: () => api.deliverables(id!), enabled: Boolean(id) });
}
export function useReleaseSummary(id: string | undefined) {
  return useQuery({ queryKey: keys.releaseSummary(id ?? ''), queryFn: () => api.releaseSummary(id!), enabled: Boolean(id) });
}
export function useGraphicsModel(id: string | undefined) {
  return useQuery({ queryKey: keys.graphicsModel(id ?? ''), queryFn: () => api.graphicsModel(id!), enabled: Boolean(id) });
}
export function useBacnetLab(id: string | undefined) {
  return useQuery({ queryKey: keys.bacnetLab(id ?? ''), queryFn: () => api.bacnetLab(id!), enabled: Boolean(id) });
}
export function useBoptestEvidence(id: string | undefined) {
  return useQuery({ queryKey: keys.boptest(id ?? ''), queryFn: () => api.boptest(id!), enabled: Boolean(id) });
}
export function useAlfalfaEvidence(id: string | undefined) {
  return useQuery({ queryKey: keys.alfalfa(id ?? ''), queryFn: () => api.alfalfa(id!), enabled: Boolean(id) });
}
export function useAuditStatus() {
  return useQuery({ queryKey: keys.auditStatus, queryFn: api.securityAuditStatus, staleTime: 30_000 });
}
export function useIntegrationAudit() {
  return useQuery({ queryKey: keys.integrationAudit, queryFn: api.integrationAudit, staleTime: 5 * 60_000 });
}
export function useProjects() {
  return useQuery({ queryKey: keys.projects, queryFn: api.projects });
}
export function useProject(id: string | undefined) {
  return useQuery({ queryKey: keys.project(id ?? ''), queryFn: () => api.project(id!), enabled: Boolean(id) });
}
export function useProjectReport(id: string | undefined) {
  return useQuery({ queryKey: keys.projectReport(id ?? ''), queryFn: () => api.projectReport(id!), enabled: Boolean(id) });
}
export function useLibraryCatalogs() {
  return useQuery({ queryKey: keys.libraryCatalogs, queryFn: api.libraryCatalogs, staleTime: 5 * 60_000 });
}
export function useCtrlFlowTemplates() {
  return useQuery({ queryKey: keys.ctrlFlowTemplates, queryFn: api.ctrlFlowTemplates, staleTime: 5 * 60_000 });
}
export function useCtrlFlowConfiguration(templateId: string | undefined, selections: Record<string, unknown>) {
  return useQuery({
    queryKey: keys.ctrlFlowConfiguration(templateId ?? '', selections),
    queryFn: () => api.ctrlFlowConfigure(templateId!, selections),
    enabled: Boolean(templateId),
    placeholderData: (previous) => previous,
  });
}
export function useG36Parameters(controllerId: string | undefined) {
  return useQuery({ queryKey: keys.g36Parameters(controllerId ?? ''), queryFn: () => api.g36Parameters(controllerId!), enabled: Boolean(controllerId), staleTime: Infinity });
}
export function useLatestQualificationJob(runId: string | undefined, opts?: { refetchInterval?: number | false }) {
  return useQuery({ queryKey: keys.latestJob(runId ?? ''), queryFn: () => api.latestQualificationJob(runId!), enabled: Boolean(runId), refetchInterval: opts?.refetchInterval ?? false });
}
export function useBoptestCatalog(enabled = true) {
  return useQuery({ queryKey: keys.boptestCatalog, queryFn: api.boptestCatalog, enabled, staleTime: 5 * 60_000, retry: false });
}
