import { useState } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { IngredientPreferencesForm } from './IngredientPreferencesForm';
import { ApiService } from '../utils/api';
import type { IngredientLookupResult, PreferenceDraft } from '../types';
import { deferred } from '../test/fixtures';

const options: IngredientLookupResult = {
  taxonomy_version: 'fixture-v1', categories: ['Cleanser', 'Serum'], supported_markets: ['GB'],
  supported_currencies: ['GBP'], default_market: 'GB', default_currency: 'GBP',
  currency_minor_units: { GBP: 2 },
};
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
function Harness({ initial = { preferences: {}, labels: {} } }: { initial?: PreferenceDraft }) {
  const [draft, setDraft] = useState<PreferenceDraft>(initial);
  const [valid, setValid] = useState(true);
  return <>
    <IngredientPreferencesForm value={draft} onChange={setDraft} onValidityChange={setValid} />
    <button disabled={!valid}>Analyze</button>
    <output data-testid="draft">{JSON.stringify(draft)}</output>
  </>;
}
async function open() {
  render(<Harness />);
  fireEvent.click(screen.getByRole('button', { name: /Ingredient preferences/ }));
  await screen.findByLabelText('Exact ingredient name');
}

test('resolved identities become category must-haves and unresolved names block submission', async () => {
  const lookup = vi.spyOn(ApiService.prototype, 'lookupIngredients')
    .mockResolvedValueOnce(options)
    .mockResolvedValueOnce({ ...options, results: [{ status: 'unresolved' }] })
    .mockResolvedValueOnce({ ...options, results: [{ status: 'resolved', ingredient_id: 'b3', display_name: 'Niacinamide' }] });
  await open();
  fireEvent.change(screen.getByLabelText('Preference'), { target: { value: 'require' } });
  fireEvent.change(screen.getByLabelText('Product category'), { target: { value: 'Serum' } });
  fireEvent.change(screen.getByLabelText('Exact ingredient name'), { target: { value: 'Vitamin B' } });
  fireEvent.click(screen.getByText('Find and add'));
  await screen.findByText(/No exact ingredient identity/);
  expect((screen.getByText('Analyze') as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Exact ingredient name'), { target: { value: 'Niacinamide' } });
  fireEvent.click(screen.getByText('Find and add'));
  await screen.findByText('Must have in Serum');
  expect(JSON.parse(screen.getByTestId('draft').textContent!).preferences.must_have_by_category)
    .toEqual([{ category_id: 'Serum', ingredient_ids: ['b3'] }]);
  expect((screen.getByText('Analyze') as HTMLButtonElement).disabled).toBe(false);
  expect(lookup.mock.calls[2][0]).toEqual({ references: [{ name: 'Niacinamide' }] });
});

test.each(['Clear all preferences', 'Clear name'])('%s cancels a lookup even when its transport returns late', async button => {
  const late = deferred<IngredientLookupResult>();
  vi.spyOn(ApiService.prototype, 'lookupIngredients').mockResolvedValueOnce(options).mockReturnValueOnce(late.promise);
  await open();
  fireEvent.change(screen.getByLabelText('Exact ingredient name'), { target: { value: 'Niacinamide' } });
  fireEvent.click(screen.getByText('Find and add'));
  expect((screen.getByLabelText('Maximum price per product') as HTMLInputElement).disabled).toBe(true);
  fireEvent.click(screen.getByText(button));
  await act(async () => late.resolve({ ...options, results: [{ status: 'resolved', ingredient_id: 'b3', display_name: 'Niacinamide' }] }));
  expect(JSON.parse(screen.getByTestId('draft').textContent!).preferences).toEqual({});
  expect(screen.queryByText('Exclude from every step')).toBeNull();
});

test('a conflicting common-ingredient choice must be resolved or cleared', async () => {
  const common = { ...options, ingredients: [{ ingredient_id: 'b3', display_name: 'Niacinamide' }] };
  vi.spyOn(ApiService.prototype, 'lookupIngredients').mockResolvedValueOnce(options).mockResolvedValue(common);
  await open();
  fireEvent.click(screen.getByText('Browse common ingredients for Cleanser'));
  await screen.findByLabelText('Common ingredients (advisory)');
  fireEvent.change(screen.getByLabelText('Common ingredients (advisory)'), { target: { value: 'b3' } });
  fireEvent.change(screen.getByLabelText('Preference'), { target: { value: 'require' } });
  fireEvent.change(screen.getByLabelText('Common ingredients (advisory)'), { target: { value: 'b3' } });
  await screen.findByText(/Remove this ingredient from exclusions/);
  expect((screen.getByText('Analyze') as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByText('Clear name'));
  await waitFor(() => expect((screen.getByText('Analyze') as HTMLButtonElement).disabled).toBe(false));
});

test('a removed saved currency preserves the cap and requires explicit review', async () => {
  vi.spyOn(ApiService.prototype, 'lookupIngredients').mockResolvedValue(options);
  render(<Harness initial={{ preferences: { currency: 'USD', max_price_minor: 2500 }, labels: {} }} />);
  fireEvent.click(screen.getByRole('button', { name: /Ingredient preferences/ }));
  await screen.findByText(/re-enter your saved price limit/);
  expect((screen.getByText('Analyze') as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Currency'), { target: { value: 'GBP' } });
  expect(JSON.parse(screen.getByTestId('draft').textContent!).preferences.max_price_minor).toBe(2500);
  expect((screen.getByText('Analyze') as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Maximum price per product'), { target: { value: '30.00' } });
  expect(JSON.parse(screen.getByTestId('draft').textContent!).preferences).toEqual({ currency: 'GBP', max_price_minor: 3000 });
  await waitFor(() => expect((screen.getByText('Analyze') as HTMLButtonElement).disabled).toBe(false));
});
