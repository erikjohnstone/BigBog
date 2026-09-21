import { StatusPill } from '../../design-system/primitives';
import { formatKpi } from './kpi';

/** Units BOPTEST publishes for its standard KPIs. */
const KPI_META: Record<string, { label: string; unit: string }> = {
  ener_tot: { label: 'HVAC energy', unit: 'kWh/m²' },
  tdis_tot: { label: 'Thermal discomfort', unit: 'K·h/zone' },
  idis_tot: { label: 'IAQ discomfort', unit: 'ppm·h/zone' },
  cost_tot: { label: 'Operational cost', unit: '$/m²' },
  emis_tot: { label: 'CO₂ emissions', unit: 'kg/m²' },
  pele_tot: { label: 'Peak electrical', unit: 'kW/m²' },
  pgas_tot: { label: 'Peak gas', unit: 'kW/m²' },
  pdih_tot: { label: 'Peak district heat', unit: 'kW/m²' },
  time_rat: { label: 'Compute ratio', unit: 's/ss' },
};

/**
 * KPI tiles. Every tile carries its unit and the violet simulated badge, and
 * none of them implies a pass or fail: only an oracle can do that.
 */
export function KpiCards({ kpis, title }: { kpis: Record<string, number | null>; title?: string }) {
  const entries = Object.entries(kpis);
  if (entries.length === 0) return null;
  return (
    <div className="px-4 py-3">
      <div className="flex items-center gap-2 mb-2">
        <span className="eyebrow">{title ?? 'Key performance indicators'}</span>
        <StatusPill tone="sim">Simulated</StatusPill>
      </div>
      <ul className="grid gap-2 grid-cols-[repeat(auto-fill,minmax(9.5rem,1fr))]" aria-label={title ?? 'Key performance indicators'}>
        {entries.map(([key, value]) => {
          const meta = KPI_META[key];
          return (
            <li key={key} className="raised px-3 py-2 min-w-0">
              <div className="text-2xs text-fg-2 truncate" title={key}>
                {meta?.label ?? key}
              </div>
              <div className="flex items-baseline gap-1">
                <span className="num text-lg text-fg-0">{formatKpi(value)}</span>
                {meta?.unit && value !== null && <span className="text-2xs text-fg-2">{meta.unit}</span>}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
