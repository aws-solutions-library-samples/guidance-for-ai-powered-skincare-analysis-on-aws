import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { ProductImage } from './ProductImage';

afterEach(cleanup);

it.each([
  'https://attacker.invalid/image.jpg', '//attacker.invalid/image.jpg',
  '/products/../secret.jpg', '/products/%2f%2fexample.com/image.jpg',
  'data:image/svg+xml,anything', '/products/image.jpg?tracking=1',
])('does not create an image request for an unapproved source: %s', src => {
  render(<ProductImage src={src} name="Sample product" stepName="Cleanser" />);
  expect(screen.queryByRole('img')).toBeNull();
  expect(screen.getByLabelText('No image available for Sample product')).toBeDefined();
});

it('renders a same-origin catalog asset without a referrer', () => {
  render(<ProductImage src="/products/sample.jpg" name="Sample product" stepName="Cleanser" />);
  const image = screen.getByRole('img');
  expect(image.getAttribute('src')).toBe('/products/sample.jpg');
  expect(image.getAttribute('referrerpolicy')).toBe('no-referrer');
});
