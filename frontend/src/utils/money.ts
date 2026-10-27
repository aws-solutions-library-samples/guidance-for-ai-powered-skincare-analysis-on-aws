/** Decimal input is converted as integer text, without floating-point rounding. */
export function parseMinorUnits(raw: string, digits: number): number | null | undefined {
  if (raw === '') return null;
  if (!Number.isInteger(digits) || digits < 0 || digits > 4 || raw.length > 32
      || !new RegExp(digits ? `^\\d+(?:\\.\\d{1,${digits}})?$` : '^\\d+$').test(raw)) return undefined;
  const [whole, fraction = ''] = raw.split('.');
  const amount = BigInt(whole) * 10n ** BigInt(digits) + BigInt(fraction.padEnd(digits, '0') || '0');
  return amount <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(amount) : undefined;
}

export function formatMinorUnits(amount: number | null | undefined, digits: number): string {
  if (amount == null) return '';
  if (!Number.isSafeInteger(amount) || amount < 0) throw new Error('Invalid price amount.');
  const scale = 10n ** BigInt(digits), value = BigInt(amount);
  return `${value / scale}${digits ? `.${String(value % scale).padStart(digits, '0')}` : ''}`;
}
