import { expect, test } from 'vitest';
import { parseRoutine } from './analysisData';
import { routineFixture } from '../test/fixtures';

function exactRoutine() {
  const base = routineFixture();
  return {
    ...base, api_version: 2,
    applied_preferences: { excluded_ingredient_ids: [], must_have_by_category: [], market: 'GB', currency: 'GBP', max_price_minor: null },
    routine_steps: base.routine_steps.map((step, index) => ({
      ...step, recommendation_status: index ? 'no_match' : 'matched', no_match_reason: index ? 'catalog_changed' : null,
      ingredients: step.ingredients.map(item => ({ ...item, ingredient_id: 'glycerin' })),
      products: index ? [] : step.products.map(item => ({
        ...item, product_id: 'product-a', matched_count: 1, preferred_count: 1,
        matched_ingredient_ids: ['glycerin'], matched_must_have_ingredient_ids: [],
        price_minor: 1200, currency: 'GBP', availability: 'unknown',
      })),
    })),
  };
}

test('v2 preserves explicit no-match outcomes and canonical match facts', () => {
  const result = parseRoutine(exactRoutine());
  expect(result.routine_steps[1].no_match_reason).toBe('catalog_changed');
  expect(result.routine_steps[0].products[0].matched_count).toBe(1);
});

test.each(['bad-count', 'duplicate-id', 'empty-matched', 'missing-preferences', 'bad-must-haves'])('%s rejects malformed v2 wire data', change => {
  const value = exactRoutine();
  if (change === 'bad-count') value.routine_steps[0].products[0].matched_count = 3;
  if (change === 'duplicate-id') value.routine_steps[0].products.push(value.routine_steps[0].products[0]);
  if (change === 'empty-matched') value.routine_steps[0].products = [];
  if (change === 'missing-preferences') Object.assign(value, { applied_preferences: null });
  if (change === 'bad-must-haves') Object.assign(value.applied_preferences, { must_have_by_category: [{}] });
  expect(() => parseRoutine(value)).toThrow();
});
