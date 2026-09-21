/**
 * Parametric SVG symbols. Each takes the element box and draws itself with
 * a uniform contract; animation is CSS driven by variables that
 * `useLiveSymbol` writes in the frame. Every symbol has a title for
 * assistive technology and never encodes state by colour alone.
 */

import type { MouseEvent } from 'react';

import { cn } from '../../../design-system/cn';
import type { Medium, SchematicElement } from '../types';
import { useLiveSymbol } from './live';

export function mediumColor(medium: Medium | undefined): string {
  switch (medium) {
    case 'air-supply':
      return 'var(--m-air-supply)';
    case 'air-return':
      return 'var(--m-air-return)';
    case 'air-outside':
      return 'var(--m-air-outside)';
    case 'chw':
      return 'var(--m-chw)';
    case 'hw':
      return 'var(--m-hw)';
    case 'steam':
      return 'var(--m-steam)';
    case 'refrig':
      return 'var(--m-refrig)';
    case 'elec':
      return 'var(--m-elec)';
    case 'cmd':
      return 'var(--m-cmd)';
    case 'status':
      return 'var(--m-status)';
    default:
      return 'var(--fg-2)';
  }
}

export interface SymbolProps {
  element: SchematicElement;
  selected?: boolean;
  onSelect?: (event: MouseEvent) => void;
}

function Title({ element }: { element: SchematicElement }) {
  return <title>{`${element.label ?? element.id}${element.slot ? ` (${element.slot})` : ''}`}</title>;
}

function Frame({ element, selected, children, onSelect, className }: SymbolProps & { children: React.ReactNode; className?: string }) {
  const ref = useLiveSymbol<SVGGElement>(element.bindings, element.unit);
  const bound = Object.values(element.bindings).some((value) => (Array.isArray(value) ? value.length > 0 : Boolean(value)));
  return (
    <g
      ref={ref}
      className={cn('schematic-symbol', `sym-${element.type}`, selected && 'is-selected', !bound && element.slot && 'is-unbound', className)}
      transform={`translate(${element.x} ${element.y})`}
      onClick={onSelect}
      role="img"
      aria-label={`${element.label ?? element.id}${element.slot ? `, ${element.slot}` : ''}`}
      data-slot={element.slot}
      data-symbol={element.type}
      style={{ cursor: onSelect ? 'pointer' : undefined }}
    >
      <Title element={element} />
      {children}
      {selected && <rect x={-4} y={-4} width={element.w + 8} height={element.h + 8} rx={6} fill="none" stroke="var(--accent)" strokeWidth={1.5} strokeDasharray="4 3" />}
    </g>
  );
}

function LiveText({ x, y, anchor = 'middle', className }: { x: number; y: number; anchor?: 'start' | 'middle' | 'end'; className?: string }) {
  return (
    <text x={x} y={y} textAnchor={anchor} data-live-value className={cn('sym-value', className)}>
      —
    </text>
  );
}

export function Casing(props: SymbolProps) {
  const { element } = props;
  return (
    <Frame {...props}>
      <rect width={element.w} height={element.h} rx={6} fill="var(--bg-2)" stroke="var(--line-2)" strokeWidth={1.5} />
      {element.label && (
        <text x={8} y={-6} className="sym-label">
          {element.label}
        </text>
      )}
    </Frame>
  );
}

export function Fan(props: SymbolProps) {
  const { element } = props;
  const r = Math.min(element.w, element.h) / 2 - 6;
  const cx = element.w / 2;
  const cy = element.h / 2;
  return (
    <Frame {...props}>
      <circle cx={cx} cy={cy} r={r} fill="var(--bg-3)" stroke="var(--fg-1)" strokeWidth={1.5} />
      <g className="impeller spin-by-speed" style={{ transformOrigin: `${cx}px ${cy}px` }}>
        {[0, 90, 180, 270].map((angle) => (
          <path
            key={angle}
            d={`M ${cx} ${cy} L ${cx + r * 0.85} ${cy - r * 0.25} A ${r} ${r} 0 0 1 ${cx + r * 0.85} ${cy + r * 0.25} Z`}
            fill="var(--fg-2)"
            transform={`rotate(${angle} ${cx} ${cy})`}
          />
        ))}
        <circle cx={cx} cy={cy} r={r * 0.18} fill="var(--fg-1)" />
      </g>
      <circle className="sym-run" cx={cx + r * 0.8} cy={cy - r * 0.8} r={4} />
      {element.label && (
        <text x={cx} y={element.h + 12} textAnchor="middle" className="sym-label">
          {element.label}
        </text>
      )}
      {element.bindings.value && <LiveText x={cx} y={element.h + 24} />}
    </Frame>
  );
}

export function Pump(props: SymbolProps) {
  const { element } = props;
  const r = Math.min(element.w, element.h) / 2 - 4;
  const cx = element.w / 2;
  const cy = element.h / 2;
  return (
    <Frame {...props}>
      <circle cx={cx} cy={cy} r={r} fill="var(--bg-3)" stroke={mediumColor(element.medium)} strokeWidth={2} />
      <g className="impeller spin-by-speed" style={{ transformOrigin: `${cx}px ${cy}px` }}>
        <polygon points={`${cx - r * 0.5},${cy - r * 0.55} ${cx + r * 0.7},${cy} ${cx - r * 0.5},${cy + r * 0.55}`} fill="var(--fg-1)" />
      </g>
      <circle className="sym-run" cx={cx + r * 0.75} cy={cy - r * 0.75} r={4} />
      {element.label && (
        <text x={cx} y={element.h + 12} textAnchor="middle" className="sym-label">
          {element.label}
        </text>
      )}
    </Frame>
  );
}

export function Damper(props: SymbolProps) {
  const { element } = props;
  const cx = element.w / 2;
  const blades = 3;
  const gap = element.h / (blades + 1);
  return (
    <Frame {...props}>
      <rect width={element.w} height={element.h} fill="var(--bg-1)" stroke="var(--line-2)" />
      {Array.from({ length: blades }, (_, i) => {
        const y = gap * (i + 1);
        return <line key={i} className="blade" x1={cx - element.w * 0.36} x2={cx + element.w * 0.36} y1={y} y2={y} stroke="var(--fg-0)" strokeWidth={2.5} strokeLinecap="round" style={{ transformOrigin: `${cx}px ${y}px` }} />;
      })}
      <LiveText x={cx} y={element.h + 14} />
      {element.label && (
        <text x={cx} y={-6} textAnchor="middle" className="sym-label">
          {element.label}
        </text>
      )}
    </Frame>
  );
}

export function Valve(props: SymbolProps) {
  const { element } = props;
  const w = element.w;
  const h = element.h;
  const color = mediumColor(element.medium);
  return (
    <Frame {...props}>
      <polygon points={`0,${h * 0.35} ${w / 2},${h * 0.62} 0,${h * 0.9}`} fill="var(--bg-3)" stroke={color} strokeWidth={1.5} />
      <polygon points={`${w},${h * 0.35} ${w / 2},${h * 0.62} ${w},${h * 0.9}`} fill="var(--bg-3)" stroke={color} strokeWidth={1.5} />
      <line x1={w / 2} x2={w / 2} y1={h * 0.62} y2={h * 0.2} stroke="var(--fg-1)" strokeWidth={2} />
      <rect className="stem" x={w / 2 - 8} y={h * 0.05} width={16} height={h * 0.16} rx={2} fill="var(--fg-1)" />
      <rect className="opening" x={w * 0.2} y={h * 0.5} width={w * 0.6} height={h * 0.24} fill={color} />
      <LiveText x={w / 2} y={h + 14} />
    </Frame>
  );
}

export function Coil(props: SymbolProps) {
  const { element } = props;
  const color = mediumColor(element.medium);
  const rows = 4;
  const step = element.w / 8;
  const path = Array.from({ length: rows }, (_, row) => {
    const y = 8 + ((element.h - 16) / (rows - 1)) * row;
    let d = `M 4 ${y}`;
    for (let i = 0; i < 8; i += 1) d += ` L ${4 + step * (i + 0.5)} ${y + (i % 2 ? -5 : 5)}`;
    d += ` L ${element.w - 4} ${y}`;
    return d;
  }).join(' ');
  return (
    <Frame {...props}>
      <rect width={element.w} height={element.h} fill="var(--bg-1)" stroke="var(--line-2)" />
      <path d={path} fill="none" stroke={color} strokeWidth={1.5} />
      {element.label && (
        <text x={element.w / 2} y={-6} textAnchor="middle" className="sym-label">
          {element.label}
        </text>
      )}
    </Frame>
  );
}

export function Filter(props: SymbolProps) {
  const { element } = props;
  return (
    <Frame {...props}>
      <rect width={element.w} height={element.h} fill="url(#schematic-hatch)" stroke="var(--line-2)" />
      {element.label && (
        <text x={element.w / 2} y={-6} textAnchor="middle" className="sym-label">
          {element.label}
        </text>
      )}
    </Frame>
  );
}

export function Chiller(props: SymbolProps) {
  const { element } = props;
  return (
    <Frame {...props}>
      <rect width={element.w} height={element.h} rx={8} fill="var(--bg-2)" stroke="var(--m-chw)" strokeWidth={2} />
      <rect x={10} y={16} width={element.w - 20} height={element.h * 0.28} rx={4} fill="var(--bg-3)" stroke="var(--m-refrig)" />
      <rect x={10} y={element.h - 16 - element.h * 0.28} width={element.w - 20} height={element.h * 0.28} rx={4} fill="var(--bg-3)" stroke="var(--m-chw)" />
      <path d={`M ${element.w / 2} ${element.h * 0.44} v ${element.h * 0.12}`} stroke="var(--fg-2)" strokeWidth={4} className="sym-compressor" />
      <circle className="sym-run" cx={element.w - 12} cy={12} r={4} />
      <text x={element.w / 2} y={element.h + 14} textAnchor="middle" className="sym-label">
        {element.label ?? 'Chiller'}
      </text>
    </Frame>
  );
}

export function Boiler(props: SymbolProps) {
  const { element } = props;
  return (
    <Frame {...props}>
      <rect width={element.w} height={element.h} rx={8} fill="var(--bg-2)" stroke="var(--m-hw)" strokeWidth={2} />
      <path
        className="sym-flame"
        d={`M ${element.w / 2} ${element.h * 0.72} c -18 -14 -10 -30 0 -40 c 4 12 12 10 12 22 c 0 10 -6 18 -12 18 z`}
        fill="var(--m-elec)"
      />
      <circle className="sym-run" cx={element.w - 12} cy={12} r={4} />
      <LiveText x={element.w / 2} y={element.h - 10} />
      <text x={element.w / 2} y={element.h + 14} textAnchor="middle" className="sym-label">
        {element.label ?? 'Boiler'}
      </text>
    </Frame>
  );
}

export function Tower(props: SymbolProps) {
  const { element } = props;
  const cx = element.w / 2;
  return (
    <Frame {...props}>
      <polygon points={`0,${element.h} ${element.w},${element.h} ${element.w * 0.85},0 ${element.w * 0.15},0`} fill="var(--bg-2)" stroke="var(--m-refrig)" strokeWidth={1.5} />
      <g className="impeller spin-by-speed" style={{ transformOrigin: `${cx}px 16px` }}>
        <line x1={cx - 16} x2={cx + 16} y1={16} y2={16} stroke="var(--fg-1)" strokeWidth={3} />
        <line x1={cx} x2={cx} y1={0} y2={32} stroke="var(--fg-1)" strokeWidth={3} />
      </g>
      <circle className="sym-run" cx={element.w - 10} cy={element.h - 10} r={4} />
      <text x={cx} y={element.h + 14} textAnchor="middle" className="sym-label">
        {element.label ?? 'Tower'}
      </text>
    </Frame>
  );
}

export function Zone(props: SymbolProps) {
  const { element } = props;
  return (
    <Frame {...props}>
      <rect className="zone-fill" width={element.w} height={element.h} rx={8} stroke="var(--line-2)" strokeDasharray="6 4" />
      {element.label && (
        <text x={8} y={-6} className="sym-label">
          {element.label}
        </text>
      )}
    </Frame>
  );
}

export function Sensor(props: SymbolProps) {
  const { element } = props;
  const r = Math.min(element.w, element.h) / 2;
  return (
    <Frame {...props}>
      <circle cx={r} cy={r} r={r - 1} fill="var(--bg-3)" stroke="var(--fg-1)" strokeWidth={1.5} />
      <text x={r} y={r - 3} textAnchor="middle" className="sym-tag">
        {element.tag ?? 'XT'}
      </text>
      <LiveText x={r} y={r + 10} className="sym-value-small" />
      {element.label && (
        <text x={r} y={r * 2 + 12} textAnchor="middle" className="sym-label">
          {element.label}
        </text>
      )}
    </Frame>
  );
}

export function Lamp(props: SymbolProps) {
  const { element } = props;
  return (
    <Frame {...props}>
      <rect width={element.w} height={element.h} rx={element.h / 2} fill="var(--bg-2)" stroke="var(--line-2)" />
      <circle className="lamp-dot" cx={element.h / 2 + 2} cy={element.h / 2} r={element.h / 2 - 6} />
      <text x={element.h + 4} y={element.h / 2 + 4} className="sym-label-strong">
        {element.label}
      </text>
    </Frame>
  );
}

export function Readout(props: SymbolProps) {
  const { element } = props;
  return (
    <Frame {...props}>
      <rect width={element.w} height={element.h} rx={4} fill="var(--bg-2)" stroke="var(--line-1)" />
      <text x={6} y={element.h / 2 + 4} className="sym-label">
        {element.label}
      </text>
      <LiveText x={element.w - 6} y={element.h / 2 + 4} anchor="end" className="sym-value-small" />
    </Frame>
  );
}

export function Label(props: SymbolProps) {
  const { element } = props;
  return (
    <Frame {...props}>
      <text x={0} y={12} className="sym-label">
        {element.label}
      </text>
    </Frame>
  );
}

export const symbolFor: Record<SchematicElement['type'], (props: SymbolProps) => React.JSX.Element> = {
  fan: Fan,
  damper: Damper,
  valve: Valve,
  coil: Coil,
  filter: Filter,
  pump: Pump,
  chiller: Chiller,
  boiler: Boiler,
  tower: Tower,
  casing: Casing,
  zone: Zone,
  sensor: Sensor,
  lamp: Lamp,
  readout: Readout,
  label: Label,
};
