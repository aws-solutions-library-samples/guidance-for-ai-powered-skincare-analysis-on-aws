import { createHash } from 'node:crypto';
import { BatchGetItemCommand } from '@aws-sdk/client-dynamodb';
import { PublicError } from './errors.mjs';
import { validateLookup } from './preferences.mjs';

const hash = value => createHash('sha256').update(value).digest('hex');
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const uniqueStrings = (value, max, valid) => Array.isArray(value) && value.length <= max
  && new Set(value).size === value.length && value.every(item => typeof item === 'string' && valid(item));
const displayName = value => typeof value === 'string' && value.trim().length > 0 && [...value].length <= 256;
const ingredient = value => object(value) && typeof value.ingredient_id === 'string' && ID.test(value.ingredient_id) && displayName(value.display_name);
// Match Python's str.split whitespace set, including U+0085 and U+001C–001F.
export const normalizeName = value => value.toLowerCase()
  .split(/[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/u)
  .filter(Boolean).join(' ');
function decode(value) {
  if (!object(value) || Object.keys(value).length !== 1) throw new PublicError('SERVICE_UNAVAILABLE');
  if (typeof value.S === 'string') return value.S;
  if (value.N !== undefined) {
    const number = Number(value.N);
    if (!Number.isFinite(number)) throw new PublicError('SERVICE_UNAVAILABLE');
    return number;
  }
  if (typeof value.BOOL === 'boolean') return value.BOOL;
  if (value.NULL === true) return null;
  if (Array.isArray(value.L)) return value.L.map(decode);
  if (object(value.M)) return Object.fromEntries(Object.entries(value.M).map(([key, item]) => [key, decode(item)]));
  throw new PublicError('SERVICE_UNAVAILABLE');
}

export class IngredientLookup {
  constructor(client, { tableName, catalogId }) {
    Object.assign(this, { client, tableName, catalogId });
  }

  async values(keys, ledger) {
    let pending = [...new Set(keys)];
    if (pending.length > 100) throw new PublicError('INVALID_PREFERENCES');
    const found = new Map();
    while (pending.length) {
      const response = await this.client.send(new BatchGetItemCommand({
        RequestItems: { [this.tableName]: { Keys: pending.map(pk => ({ pk: { S: pk } })), ConsistentRead: true } },
      }), { abortSignal: ledger.signal });
      if (!object(response.Responses)
          || Object.keys(response.Responses).some(table => table !== this.tableName)
          || Object.keys(response.UnprocessedKeys ?? {}).some(table => table !== this.tableName)) {
        throw new PublicError('SERVICE_UNAVAILABLE');
      }
      const unprocessed = response.UnprocessedKeys?.[this.tableName];
      if (unprocessed !== undefined && (!object(unprocessed) || !Array.isArray(unprocessed.Keys)
          || (unprocessed.ConsistentRead !== undefined && unprocessed.ConsistentRead !== true)
          || Object.keys(unprocessed).some(key => !['Keys', 'ConsistentRead'].includes(key))
          || unprocessed.Keys.some(key => !object(key) || Object.keys(key).length !== 1 || typeof key.pk?.S !== 'string'))) {
        throw new PublicError('SERVICE_UNAVAILABLE');
      }
      const next = (unprocessed?.Keys ?? []).map(key => key.pk.S);
      if (new Set(next).size !== next.length || next.some(key => !pending.includes(key))) {
        throw new PublicError('SERVICE_UNAVAILABLE');
      }
      const rows = response.Responses[this.tableName] ?? [];
      if (!Array.isArray(rows)) throw new PublicError('SERVICE_UNAVAILABLE');
      for (const item of rows) {
        const key = item.pk?.S;
        if (!pending.includes(key) || found.has(key) || next.includes(key)
            || item.catalog_id?.S !== this.catalogId || !item.value) throw new PublicError('SERVICE_UNAVAILABLE');
        found.set(key, decode(item.value));
      }
      pending = next;
      if (pending.length && ledger.retries++ >= 1) throw new PublicError('SERVICE_UNAVAILABLE');
    }
    return found;
  }

  async lookup(input, parentSignal) {
    const payload = validateLookup(input);
    const ledger = { retries: 0, signal: AbortSignal.any([...(parentSignal ? [parentSignal] : []), AbortSignal.timeout(1200)]) };
    const config = (await this.values(['CONFIG'], ledger)).get('CONFIG');
    if (!config || config.catalog_id !== this.catalogId || typeof config.taxonomy_version !== 'string' || !ID.test(config.taxonomy_version)
        || !uniqueStrings(config.categories, 100, name => name.length > 0 && [...name].length <= 128) || config.categories.length < 2
        || !uniqueStrings(config.supported_markets, 50, value => /^[A-Z]{2}$/.test(value))
        || !uniqueStrings(config.supported_currencies, 50, value => /^[A-Z]{3}$/.test(value))
        || !object(config.currency_minor_units) || Object.keys(config.currency_minor_units).length > 50
        || Object.entries(config.currency_minor_units).some(([currency, digits]) => !/^[A-Z]{3}$/.test(currency)
          || !Number.isInteger(digits) || digits < 0 || digits > 4)
        || config.supported_currencies.some(currency => config.currency_minor_units[currency] === undefined)
        || (config.default_market !== null && !config.supported_markets.includes(config.default_market))
        || (config.default_currency !== null && !config.supported_currencies.includes(config.default_currency))) {
      throw new PublicError('SERVICE_UNAVAILABLE');
    }
    if (payload.category_id !== undefined && !config.categories.includes(payload.category_id)) {
      throw new PublicError('INVALID_PREFERENCES');
    }
    const base = {
      taxonomy_version: config.taxonomy_version,
      categories: config.categories,
      supported_markets: config.supported_markets, supported_currencies: config.supported_currencies,
      default_market: config.default_market, default_currency: config.default_currency,
      currency_minor_units: config.currency_minor_units,
    };
    const version = config.taxonomy_version;
    if (!payload.references) {
      if (!payload.category_id) return base;
      const key = `SUMMARY#${version}#${hash(payload.category_id)}`;
      const value = (await this.values([key], ledger)).get(key);
      if (value && (value.category_id !== payload.category_id || value.taxonomy_version !== version
          || !Array.isArray(value.ingredients) || value.ingredients.length > 30
          || value.ingredients.some(item => !ingredient(item) || !Number.isSafeInteger(item.count) || item.count < 0)
          || new Set(value.ingredients.map(item => item.ingredient_id)).size !== value.ingredients.length
          || typeof value.as_of !== 'number' || !Number.isFinite(value.as_of) || value.as_of < 0)) {
        throw new PublicError('SERVICE_UNAVAILABLE');
      }
      return { ...base, category_id: payload.category_id, ingredients: value?.ingredients ?? [], as_of: value?.as_of ?? null, advisory: true };
    }
    const keys = payload.references.map(reference => reference.ingredient_id
      ? `INGREDIENT#${version}#${reference.ingredient_id}` : `ALIAS#${version}#${hash(normalizeName(reference.name))}`);
    const values = await this.values(keys, ledger);
    const results = payload.references.map((reference, index) => {
      const value = values.get(keys[index]);
      if (!value) return { input: reference, status: 'unresolved' };
      if (value.taxonomy_version !== version) throw new PublicError('SERVICE_UNAVAILABLE');
      if (reference.ingredient_id) {
        if (value.ingredient_id !== reference.ingredient_id || !ingredient(value)) {
          throw new PublicError('SERVICE_UNAVAILABLE');
        }
        return { input: reference, status: 'resolved', ingredient_id: value.ingredient_id, display_name: value.display_name };
      }
      if (value.normalized_name !== normalizeName(reference.name)
          || !uniqueStrings(value.ingredient_ids, 20, id => ID.test(id))
          || !value.ingredient_ids.length) throw new PublicError('SERVICE_UNAVAILABLE');
      return value.ingredient_ids.length === 1
        ? { input: reference, status: 'resolved', ingredient_id: value.ingredient_ids[0] }
        : { input: reference, status: 'ambiguous' };
    });
    const unresolvedNames = results.filter(result => result.status === 'resolved' && !result.display_name);
    const entries = await this.values(unresolvedNames.map(result => `INGREDIENT#${version}#${result.ingredient_id}`), ledger);
    for (const result of unresolvedNames) {
      const entry = entries.get(`INGREDIENT#${version}#${result.ingredient_id}`);
      if (!entry || entry.ingredient_id !== result.ingredient_id || entry.taxonomy_version !== version
          || !ingredient(entry)) throw new PublicError('SERVICE_UNAVAILABLE');
      result.display_name = entry.display_name;
    }
    return { ...base, results };
  }
}
