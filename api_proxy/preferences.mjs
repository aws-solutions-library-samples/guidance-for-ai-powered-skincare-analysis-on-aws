import { PublicError } from './errors.mjs';

const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);

function ids(value) {
  if (!Array.isArray(value) || value.length > 20 || value.some(id => typeof id !== 'string' || !ID.test(id))) {
    throw new PublicError('INVALID_PREFERENCES');
  }
  return [...new Set(value)].sort();
}

export function validatePreferences(value = {}) {
  const fail = () => { throw new PublicError('INVALID_PREFERENCES'); };
  if (!object(value) || Object.keys(value).some(key => ![
    'excluded_ingredient_ids', 'must_have_by_category', 'market', 'currency', 'max_price_minor',
  ].includes(key))) fail();
  const excluded = ids(value.excluded_ingredient_ids === undefined ? [] : value.excluded_ingredient_ids);
  const required = value.must_have_by_category === undefined ? [] : value.must_have_by_category;
  if (!Array.isArray(required) || required.length > 8) fail();
  const categories = new Set();
  const mustHave = required.map(entry => {
    if (!object(entry) || Object.keys(entry).some(key => !['category_id', 'ingredient_ids'].includes(key))
        || typeof entry.category_id !== 'string' || !entry.category_id.length || [...entry.category_id].length > 128
        || categories.has(entry.category_id)) fail();
    categories.add(entry.category_id);
    const ingredients = ids(entry.ingredient_ids);
    if (!ingredients.length || ingredients.some(id => excluded.includes(id))) fail();
    return { category_id: entry.category_id, ingredient_ids: ingredients };
  });
  if (mustHave.reduce((sum, entry) => sum + entry.ingredient_ids.length, 0) > 20) fail();
  if (value.market != null && (typeof value.market !== 'string' || !/^[A-Z]{2}$/.test(value.market))) fail();
  if (value.currency != null && (typeof value.currency !== 'string' || !/^[A-Z]{3}$/.test(value.currency))) fail();
  if (value.max_price_minor != null && (!Number.isSafeInteger(value.max_price_minor) || value.max_price_minor < 0)) fail();
  return {
    excluded_ingredient_ids: excluded, must_have_by_category: mustHave,
    market: value.market ?? null, currency: value.currency ?? null, max_price_minor: value.max_price_minor ?? null,
  };
}

export function validateLookup(value) {
  if (!object(value) || Object.keys(value).some(key => !['category_id', 'references'].includes(key))) {
    throw new PublicError('INVALID_PREFERENCES');
  }
  if (value.category_id !== undefined && (
    typeof value.category_id !== 'string' || !value.category_id.length || [...value.category_id].length > 128
  )) throw new PublicError('INVALID_PREFERENCES');
  if (value.references !== undefined && (
    !Array.isArray(value.references) || !value.references.length || value.references.length > 20
    || value.references.some(reference => !object(reference) || Object.keys(reference).length !== 1
      || !(('ingredient_id' in reference && typeof reference.ingredient_id === 'string' && ID.test(reference.ingredient_id))
        || ('name' in reference && typeof reference.name === 'string' && reference.name.trim().length
          && [...reference.name].length <= 256)))
  )) throw new PublicError('INVALID_PREFERENCES');
  return value;
}
