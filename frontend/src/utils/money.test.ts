import { expect, test } from 'vitest';
import { formatMinorUnits, parseMinorUnits } from './money';

test.each([[0, '1500', 1500], [2, '12.34', 1234], [3, '12.345', 12345], [4, '12.3456', 123456]])(
  '%i decimal currency uses exact integer amounts', (digits, text, amount) => {
    expect(parseMinorUnits(text, digits)).toBe(amount);
    expect(formatMinorUnits(amount, digits)).toBe(text);
  },
);
test('maximum supported JSON integer survives decimal editing exactly', () => {
  expect(parseMinorUnits('90071992547409.91', 2)).toBe(Number.MAX_SAFE_INTEGER);
  expect(formatMinorUnits(Number.MAX_SAFE_INTEGER, 2)).toBe('90071992547409.91');
  expect(parseMinorUnits('90071992547409.92', 2)).toBeUndefined();
  expect(parseMinorUnits('1.01', 0)).toBeUndefined();
  expect(parseMinorUnits('1.001', 2)).toBeUndefined();
});
