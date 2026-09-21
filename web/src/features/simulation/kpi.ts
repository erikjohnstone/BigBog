/** Format a BOPTEST KPI for a tile: three significant-ish digits, never a fake zero. */
export function formatKpi(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  return value.toFixed(abs >= 100 ? 0 : abs >= 10 ? 1 : abs >= 1 ? 2 : 3);
}
