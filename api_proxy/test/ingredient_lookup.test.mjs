import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { IngredientLookup } from '../ingredient_lookup.mjs';
import { validatePreferences, validateLookup } from '../preferences.mjs';

const config = {
  catalog_id: 'fixture', taxonomy_version: 'fixture-v1', categories: ['Cleanser', 'Serum'],
  supported_markets: ['GB'], supported_currencies: ['GBP'], default_market: 'GB', default_currency: 'GBP',
  currency_minor_units: { GBP: 2 },
};
function encode(value) {
  if (value === null) return { NULL: true };
  if (typeof value === 'string') return { S: value };
  if (typeof value === 'number') return { N: String(value) };
  if (typeof value === 'boolean') return { BOOL: value };
  if (Array.isArray(value)) return { L: value.map(encode) };
  return { M: Object.fromEntries(Object.entries(value).map(([key, item]) => [key, encode(item)])) };
}
const row = (pk, value) => ({ pk: { S: pk }, catalog_id: { S: 'fixture' }, value: encode(value) });
const ingredientKey = id => `INGREDIENT#fixture-v1#${id}`;
const aliasKey = name => `ALIAS#fixture-v1#${createHash('sha256').update(name).digest('hex')}`;
function lookupFixture(records = {}, custom) {
  const calls = [];
  const entries = { CONFIG: config, ...records };
  const client = { send: async (command, options) => {
    calls.push(command.input);
    assert.ok(options.abortSignal instanceof AbortSignal);
    if (custom) return custom(command.input, calls.length);
    return { Responses: { metadata: command.input.RequestItems.metadata.Keys.flatMap(key => (
      entries[key.pk.S] ? [row(key.pk.S, entries[key.pk.S])] : []
    )) } };
  } };
  return { lookup: new IngredientLookup(client, { tableName: 'metadata', catalogId: 'fixture' }), calls };
}

test('configuration-only lookup reads one scoped key and never scans inventory', async () => {
  const { lookup, calls } = lookupFixture();
  assert.deepEqual(await lookup.lookup({}), {
    taxonomy_version: config.taxonomy_version, categories: config.categories,
    supported_markets: ['GB'], supported_currencies: ['GBP'], default_market: 'GB', default_currency: 'GBP',
    currency_minor_units: { GBP: 2 },
  });
  assert.deepEqual(calls, [{ RequestItems: { metadata: { Keys: [{ pk: { S: 'CONFIG' } }], ConsistentRead: true } } }]);
});

test('exact names resolve distinct vitamin identities and unknown names stay unresolved', async () => {
  const records = {};
  for (const [id, name] of [['b3', 'Niacinamide'], ['c', 'Ascorbic Acid']]) {
    records[ingredientKey(id)] = { ingredient_id: id, display_name: name, taxonomy_version: 'fixture-v1' };
    records[aliasKey(name.toLowerCase())] = { normalized_name: name.toLowerCase(), ingredient_ids: [id], taxonomy_version: 'fixture-v1' };
  }
  const { lookup, calls } = lookupFixture(records);
  const result = await lookup.lookup({ references: [{ name: '  NIACINAMIDE  ' }, { name: 'Ascorbic\u0085Acid' }, { name: 'Vitamin B' }] });
  assert.deepEqual(result.results.map(item => [item.status, item.ingredient_id]), [['resolved', 'b3'], ['resolved', 'c'], ['unresolved', undefined]]);
  assert.equal(calls.length, 3);
  assert.ok(calls.every(call => call.RequestItems.metadata.Keys.length <= 20));
});

test('ambiguous names are never automatically substituted', async () => {
  const { lookup } = lookupFixture({ [aliasKey('vitamin c')]: {
    normalized_name: 'vitamin c', ingredient_ids: ['ascorbic-acid', 'ascorbyl-glucoside'], taxonomy_version: 'fixture-v1',
  } });
  assert.equal((await lookup.lookup({ references: [{ name: 'Vitamin C' }] })).results[0].status, 'ambiguous');
});

test('an absent category summary is advisory and does not block rare-name lookup', async () => {
  const { lookup } = lookupFixture();
  const result = await lookup.lookup({ category_id: 'Serum' });
  assert.deepEqual(result.ingredients, []);
  assert.equal(result.advisory, true);
});

test('unprocessed metadata is retried once and never reported as an unknown ingredient', async () => {
  const { lookup, calls } = lookupFixture({}, (input, count) => count === 1
    ? { Responses: { metadata: [row('CONFIG', config)] } }
    : { Responses: {}, UnprocessedKeys: { metadata: input.RequestItems.metadata } });
  await assert.rejects(lookup.lookup({ references: [{ ingredient_id: 'b3' }] }), error => error.code === 'SERVICE_UNAVAILABLE');
  assert.equal(calls.length, 3);
});

for (const malformed of [
  {},
  { Responses: { foreign: [] } },
  { Responses: {}, UnprocessedKeys: { metadata: { Keys: [{ pk: { S: 'CONFIG' }, extra: { S: 'x' } }] } } },
  { Responses: { metadata: [row('CONFIG', { ...config, categories: null })] } },
]) {
  test(`malformed dependency response fails closed: ${JSON.stringify(malformed)}`, async () => {
    const { lookup } = lookupFixture({}, () => malformed);
    await assert.rejects(lookup.lookup({}), error => error.code === 'SERVICE_UNAVAILABLE');
  });
}

for (const value of [
  null, { excluded_ingredient_ids: null }, { must_have_by_category: null },
  { excluded_ingredient_ids: Array(21).fill('a') }, { max_price_minor: 1.5 },
  { max_price_minor: Number.MAX_SAFE_INTEGER + 1 }, { market: 'gb' },
  { must_have_by_category: [{ category_id: 'Serum', ingredient_ids: ['a'] }], excluded_ingredient_ids: ['a'] },
  { must_have_by_category: [{ category_id: 'Serum', ingredient_ids: ['a'] }, { category_id: 'Serum', ingredient_ids: ['b'] }] },
  { query: 'semantic text' }, { excluded_ingredient_ids: ['ingredient\n'] },
]) {
  test(`invalid preferences fail before I/O: ${JSON.stringify(value)}`, () => {
    assert.throws(() => validatePreferences(value), error => error.code === 'INVALID_PREFERENCES');
  });
}

test('lookup accepts at most twenty explicit references and preferences deduplicate exact IDs', () => {
  assert.throws(() => validateLookup({ references: Array(21).fill({ name: 'A' }) }));
  assert.deepEqual(validatePreferences({ excluded_ingredient_ids: ['b', 'a', 'a'] }).excluded_ingredient_ids, ['a', 'b']);
});
