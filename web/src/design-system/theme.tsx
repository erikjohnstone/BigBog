/**
 * Theme and density.
 *
 * Both themes are first-class. With no stored choice the document follows the
 * operating system; an explicit choice persists. `data-theme` always carries
 * the resolved theme: the inline script in index.html sets it before first
 * paint so there is no flash, and this provider keeps it in sync afterwards,
 * including when the OS preference changes while the app is open.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

export type ThemeChoice = 'system' | 'dark' | 'light';
export type ResolvedTheme = 'dark' | 'light';
export type Density = 'compact' | 'default' | 'comfortable';

const THEME_KEY = 'bactalk.theme';
const DENSITY_KEY = 'bactalk.density';

interface ThemeContextValue {
  choice: ThemeChoice;
  resolved: ResolvedTheme;
  setChoice: (choice: ThemeChoice) => void;
  toggle: () => void;
  density: Density;
  setDensity: (density: Density) => void;
  reducedMotion: boolean;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readStored<T extends string>(key: string, allowed: readonly T[]): T | null {
  try {
    const value = localStorage.getItem(key);
    return value && (allowed as readonly string[]).includes(value) ? (value as T) : null;
  } catch {
    return null;
  }
}

function writeStored(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // Storage can be unavailable in private windows; the choice just does not persist.
  }
}

function systemPrefersDark(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches;
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice>(
    () => readStored(THEME_KEY, ['dark', 'light'] as const) ?? 'system',
  );
  const [systemDark, setSystemDark] = useState(systemPrefersDark);
  const [density, setDensityState] = useState<Density>(
    () => readStored(DENSITY_KEY, ['compact', 'default', 'comfortable'] as const) ?? 'default',
  );
  const [reducedMotion, setReducedMotion] = useState(prefersReducedMotion);

  useEffect(() => {
    const dark = window.matchMedia('(prefers-color-scheme: dark)');
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const onDark = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    const onMotion = (event: MediaQueryListEvent) => setReducedMotion(event.matches);
    dark.addEventListener('change', onDark);
    motion.addEventListener('change', onMotion);
    return () => {
      dark.removeEventListener('change', onDark);
      motion.removeEventListener('change', onMotion);
    };
  }, []);

  const resolved: ResolvedTheme = choice === 'system' ? (systemDark ? 'dark' : 'light') : choice;

  useEffect(() => {
    document.documentElement.dataset.theme = resolved;
    writeStored(THEME_KEY, choice === 'system' ? null : choice);
  }, [choice, resolved]);

  useEffect(() => {
    const root = document.documentElement;
    if (density === 'default') delete root.dataset.density;
    else root.dataset.density = density;
    writeStored(DENSITY_KEY, density === 'default' ? null : density);
  }, [density]);

  const setChoice = useCallback((next: ThemeChoice) => setChoiceState(next), []);
  const toggle = useCallback(() => {
    setChoiceState(resolved === 'dark' ? 'light' : 'dark');
  }, [resolved]);
  const setDensity = useCallback((next: Density) => setDensityState(next), []);

  const value = useMemo(
    () => ({ choice, resolved, setChoice, toggle, density, setDensity, reducedMotion }),
    [choice, resolved, setChoice, toggle, density, setDensity, reducedMotion],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (!value) throw new Error('useTheme must be used inside ThemeProvider');
  return value;
}
