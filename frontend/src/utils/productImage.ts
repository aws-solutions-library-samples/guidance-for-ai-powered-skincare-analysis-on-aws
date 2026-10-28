/** Catalog pictures must be published beneath /products on this application's origin. */
export function safeProductImage(value: unknown): string {
  return typeof value === 'string' && /^\/products\/(?:[A-Za-z0-9_-]+\/)*[A-Za-z0-9_-]+\.(?:png|jpg|jpeg|webp)$/.test(value)
    ? value : '';
}

const placeholderTypes = new Set([
  'cleanser', 'toner', 'serum', 'moisturiser', 'exfoliator', 'sunscreen',
]);

/** Illustrations are local display fallbacks, never catalog product photographs. */
export function productPlaceholder(stepName: string): string {
  const type = stepName.toLowerCase();
  return placeholderTypes.has(type) ? `/products/placeholders/${type}.webp` : '';
}
