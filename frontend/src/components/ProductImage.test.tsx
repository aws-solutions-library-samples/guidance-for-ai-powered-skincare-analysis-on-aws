import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { ProductImage } from './ProductImage';

afterEach(cleanup);

it.each([
  'https://attacker.invalid/image.jpg', '//attacker.invalid/image.jpg',
  '/products/../secret.jpg', '/products/%2f%2fexample.com/image.jpg',
  'data:image/svg+xml,anything', '/products/image.jpg?tracking=1',
])('does not create an image request for an unapproved source: %s', src => {
  render(<ProductImage src={src} name="Sample product" stepName="Cleanser" />);
  expect(screen.getByRole('img').getAttribute('src')).toBe('/products/placeholders/cleanser.webp');
  expect(screen.getByText('Illustrative image')).toBeDefined();
});

it('renders a same-origin catalog asset without a referrer', () => {
  render(<ProductImage src="/products/sample.jpg" name="Sample product" stepName="Cleanser" />);
  const image = screen.getByRole('img');
  expect(image.getAttribute('src')).toBe('/products/sample.jpg');
  expect(image.getAttribute('referrerpolicy')).toBe('no-referrer');
  expect(image.getAttribute('alt')).toBe('Sample product');
  expect(screen.queryByText('Illustrative image')).toBeNull();
});

it.each(['Cleanser', 'Toner', 'Serum', 'Moisturiser', 'Exfoliator', 'Sunscreen'])(
  'uses a labelled category illustration when a %s has no image', stepName => {
    render(<ProductImage name="Sample product" stepName={stepName} />);
    const image = screen.getByRole('img');
    expect(image.getAttribute('src')).toBe(`/products/placeholders/${stepName.toLowerCase()}.webp`);
    expect(image.getAttribute('alt')).toContain('not a photo of Sample product');
    expect(screen.getByText('Illustrative image')).toBeDefined();
  },
);

it('falls back from a failed catalog photo to the illustration, then an icon if both fail', () => {
  render(<ProductImage src="/products/missing.jpg" name="Sample product" stepName="Cleanser" />);
  fireEvent.error(screen.getByRole('img'));
  expect(screen.getByRole('img').getAttribute('src')).toBe('/products/placeholders/cleanser.webp');
  fireEvent.error(screen.getByRole('img'));
  expect(screen.queryByRole('img')).toBeNull();
  expect(screen.getByLabelText('No image available for Sample product')).toBeDefined();
});

it('uses a new catalog image after an earlier source failed', () => {
  const { rerender } = render(<ProductImage src="/products/missing.jpg" name="Sample product" stepName="Cleanser" />);
  fireEvent.error(screen.getByRole('img'));
  rerender(<ProductImage src="/products/replacement.webp" name="Sample product" stepName="Cleanser" />);
  expect(screen.getByRole('img').getAttribute('src')).toBe('/products/replacement.webp');
  expect(screen.queryByText('Illustrative image')).toBeNull();
});

it('keeps the icon for unknown categories instead of constructing an arbitrary asset URL', () => {
  render(<ProductImage name="Sample product" stepName="../Unknown" />);
  expect(screen.queryByRole('img')).toBeNull();
  expect(screen.getByLabelText('No image available for Sample product')).toBeDefined();
});
