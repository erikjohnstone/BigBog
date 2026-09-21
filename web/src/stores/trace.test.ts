import { describe, expect, it } from 'vitest';

import { formatSignalValue } from './trace';
import type { Signal } from './trace';

const numeric: Signal = { id: 'n', label: 'n', kind: 'numeric', source: 'block', values: new Float64Array(0), min: 0, max: 0 };
const boolean: Signal = { id: 'b', label: 'b', kind: 'boolean', source: 'block', values: new Uint8Array(0), min: 0, max: 1 };

describe('formatSignalValue', () => {
  it('scales precision with magnitude', () => {
    expect(formatSignalValue(0.12345, numeric)).toBe('0.123');
    expect(formatSignalValue(12.345, numeric)).toBe('12.35');
    expect(formatSignalValue(123.45, numeric)).toBe('123.5');
    expect(formatSignalValue(1234.5, numeric)).toBe('1235');
    expect(formatSignalValue(-56.789, numeric)).toBe('-56.79');
  });

  it('renders booleans and missing values honestly', () => {
    expect(formatSignalValue(1, boolean)).toBe('true');
    expect(formatSignalValue(0, boolean)).toBe('false');
    expect(formatSignalValue(Number.NaN, boolean)).toBe('—');
    expect(formatSignalValue(Number.NaN, undefined)).toBe('—');
  });
});
