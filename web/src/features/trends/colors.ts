/**
 * Canvas colours resolved from the theme tokens at draw time, so uPlot
 * panes follow the dark/light switch. Series colours cycle through the
 * media hues; temperatures use the warm ramp.
 */

const SERIES_VARS = ['--m-cmd', '--m-chw', '--m-elec', '--m-refrig', '--m-hw', '--m-air-supply', '--m-status', '--sim', '--m-steam', '--m-air-return'];

export interface ThemeColors {
  fg0: string;
  fg1: string;
  fg2: string;
  line1: string;
  line2: string;
  bg1: string;
  accent: string;
  accentSoft: string;
  fail: string;
  failSoft: string;
  warn: string;
  warnSoft: string;
  ok: string;
  series: string[];
  font: string;
}

export function readThemeColors(): ThemeColors {
  const style = getComputedStyle(document.documentElement);
  const read = (name: string) => style.getPropertyValue(name).trim();
  return {
    fg0: read('--fg-0'),
    fg1: read('--fg-1'),
    fg2: read('--fg-2'),
    line1: read('--line-1'),
    line2: read('--line-2'),
    bg1: read('--bg-1'),
    accent: read('--accent'),
    accentSoft: read('--accent-soft'),
    fail: read('--fail'),
    failSoft: read('--fail-soft'),
    warn: read('--warn'),
    warnSoft: read('--warn-soft'),
    ok: read('--ok'),
    series: SERIES_VARS.map(read),
    font: `11px ${read('--font-mono') || 'monospace'}`,
  };
}

export function seriesColor(colors: ThemeColors, index: number): string {
  return colors.series[index % colors.series.length];
}

/** CSS var name for a series, for DOM legends that should follow the theme live. */
export function seriesColorVar(index: number): string {
  return `var(${SERIES_VARS[index % SERIES_VARS.length]})`;
}
