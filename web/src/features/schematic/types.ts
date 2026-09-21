/**
 * Schematic model. A template lays out parametric symbols and names the
 * slots it can animate; bindings map each slot to a trace signal. Symbols
 * animate through CSS variables set in the animation frame, never through
 * React state.
 */

export type Medium = 'air-supply' | 'air-return' | 'air-outside' | 'chw' | 'hw' | 'steam' | 'refrig' | 'elec' | 'cmd' | 'status';

export type SymbolType =
  | 'fan'
  | 'damper'
  | 'valve'
  | 'coil'
  | 'filter'
  | 'pump'
  | 'chiller'
  | 'boiler'
  | 'tower'
  | 'casing'
  | 'zone'
  | 'sensor'
  | 'lamp'
  | 'readout'
  | 'label';

export interface SymbolBindings {
  /** Numeric readout shown on the symbol. */
  value?: string;
  /** Boolean: running / open / active. */
  on?: string;
  /** Numeric 0..1 or 0..100: damper blade, valve stem. */
  position?: string;
  /** Numeric 0..1 or 0..100, or boolean: fan / pump speed. */
  speed?: string;
  /** Numeric temperature that tints the symbol from cool to warm. */
  temp?: string;
  /** Boolean fault signals (`fault.<id>.active`) that pulse the halo. */
  faults?: string[];
}

export interface SchematicElement {
  id: string;
  type: SymbolType;
  x: number;
  y: number;
  w: number;
  h: number;
  label?: string;
  /** ISA-style tag drawn on sensors and readouts. */
  tag?: string;
  unit?: string;
  medium?: Medium;
  /** Template slot this element animates from. */
  slot?: string;
  bindings: SymbolBindings;
  /** Air flows left→right by default; set for reversed ducts. */
  reverse?: boolean;
}

export interface SchematicFlow {
  id: string;
  points: Array<[number, number]>;
  medium: Medium;
  /** Signal that drives the dash flow (numeric magnitude or boolean on). */
  flow?: string;
  /** Temperature signal that tints the line. */
  temp?: string;
  width?: number;
}

export interface SchematicLayout {
  title: string;
  width: number;
  height: number;
  elements: SchematicElement[];
  flows: SchematicFlow[];
}

export interface SlotSpec {
  id: string;
  label: string;
  kind: 'numeric' | 'boolean';
  /** Brick class suffixes that match this slot, most specific first. */
  brick?: string[];
  /** Point roles that match, combined with units when given. */
  roles?: string[];
  units?: string[];
  /** Name / label patterns as a last resort. */
  names?: RegExp[];
}

export type SlotBindings = Record<string, string | undefined>;

export interface Template {
  id: string;
  title: string;
  /** Brick class suffixes this template renders. */
  brick: string[];
  slots: SlotSpec[];
  build: (bindings: SlotBindings, sources: SignalSource[]) => SchematicLayout;
}

/** A candidate signal for a slot: a graphics-model widget, a job point, or a block. */
export interface SignalSource {
  id: string;
  label: string;
  kind: 'numeric' | 'boolean';
  unit?: string;
  brick?: string | null;
  role?: string;
  /** Signal id in the trace, when one exists. */
  signalId?: string;
}
