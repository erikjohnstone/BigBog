import type { ShadowDivergence } from '../../api/client';

function formatDivergenceValue(value: ShadowDivergence['shadow']): string {
  if (typeof value === 'number') return value.toFixed(2);
  if (value === null || value === undefined) return '—';
  return String(value);
}

/** `t=90 s · block yDam.out shadow 0.50 vs interpreter 0.70 (band 0.02)` */
export function formatDivergence(divergence: ShadowDivergence): string {
  const band = typeof divergence.band === 'number' ? ` (band ${divergence.band})` : '';
  return `t=${divergence.time_seconds} s · block ${divergence.block}.${divergence.slot} shadow ${formatDivergenceValue(divergence.shadow)} vs interpreter ${formatDivergenceValue(divergence.interpreter)}${band}`;
}
