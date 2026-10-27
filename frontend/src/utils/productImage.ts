/** Catalog pictures must be published beneath /products on this application's origin. */
export function safeProductImage(value: unknown): string {
  return typeof value === 'string' && /^\/products\/(?:[A-Za-z0-9_-]+\/)*[A-Za-z0-9_-]+\.(?:png|jpg|jpeg|webp)$/.test(value)
    ? value : '';
}
