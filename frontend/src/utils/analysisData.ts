import type { CompiledRoutine, Ingredient, IngredientPreferences, PlannedStep, Product, SkinAnalysisProfile, SkinMetrics } from '../types';
import { safeProductImage } from './productImage';

/** Validate data once at the network boundary; components consume typed objects. */
export function object(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error('Analysis returned an invalid object.');
  }
  return value as Record<string, unknown>;
}

function text(value: unknown): string {
  if (typeof value !== 'string') throw new Error('Analysis returned an invalid text field.');
  return value;
}

function list(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new Error('Analysis returned an invalid list.');
  return value;
}

const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
function identifier(value: unknown): string {
  const id = text(value);
  if (!ID.test(id)) throw new Error('Invalid catalog identity.');
  return id;
}
function ids(value: unknown, maximum: number): string[] {
  const result = list(value).map(identifier);
  if (result.length > maximum || new Set(result).size !== result.length) throw new Error('Invalid catalog identity list.');
  return result;
}

export function parsePreferences(value: unknown): IngredientPreferences {
  const data = object(value);
  const excluded = ids(data.excluded_ingredient_ids, 20);
  const required = list(data.must_have_by_category).map(value => {
    const entry = object(value);
    const category = text(entry.category_id);
    const ingredients = ids(entry.ingredient_ids, 20);
    if (!category.length || [...category].length > 128 || !ingredients.length
        || ingredients.some(id => excluded.includes(id))) throw new Error('Invalid ingredient constraint.');
    return { category_id: category, ingredient_ids: ingredients };
  });
  if (required.length > 8 || new Set(required.map(entry => entry.category_id)).size !== required.length
      || required.reduce((count, entry) => count + entry.ingredient_ids.length, 0) > 20
      || (data.market !== null && !/^[A-Z]{2}$/.test(text(data.market)))
      || (data.currency !== null && !/^[A-Z]{3}$/.test(text(data.currency)))
      || (data.max_price_minor !== null && (!Number.isSafeInteger(data.max_price_minor) || Number(data.max_price_minor) < 0))
      || (data.max_price_minor !== null && data.currency === null)) throw new Error('Invalid applied preferences.');
  return {
    excluded_ingredient_ids: excluded, must_have_by_category: required,
    market: data.market as string | null, currency: data.currency as string | null,
    max_price_minor: data.max_price_minor as number | null,
  };
}

function namedSteps<T extends { step_name: string }>(steps: T[]): T[] {
  if (!steps.length || steps.some(step => !step.step_name.trim()) ||
      new Set(steps.map(step => step.step_name)).size !== steps.length) {
    throw new Error('Analysis returned an empty or duplicate routine step.');
  }
  return steps;
}

export function decodeJson(value: unknown): unknown {
  // AgentCore may encode an SSE payload as a JSON string.
  for (let depth = 0; typeof value === 'string' && depth < 2; depth++) {
    value = JSON.parse(value);
  }
  return value;
}

export function parseSkinProfile(value: unknown): SkinAnalysisProfile {
  const data = object(value);
  const metrics = object(data.skin_metrics);
  const keys: (keyof SkinMetrics)[] = ['skin_health', 'hydration', 'texture', 'pore_size', 'elasticity', 'radiance'];
  for (const key of keys) {
    const score = metrics[key];
    if (typeof score !== 'number' || !Number.isFinite(score) || score < 0 || score > 100) {
      throw new Error('Analysis returned an invalid skin metric.');
    }
  }
  return {
    skin_type: text(data.skin_type),
    age: text(data.age),
    concerns: list(data.concerns).map(text),
    current_condition: text(data.current_condition),
    recommended_goals: text(data.recommended_goals),
    skin_metrics: metrics as unknown as SkinMetrics,
    strengths: list(data.strengths ?? []).map(text),
  };
}

export function parsePlan(value: unknown): PlannedStep[] {
  return namedSteps(list(object(value).routine_steps).map(value => {
    const step = object(value);
    return {
      step_name: text(step.step_name),
      when: text(step.when),
      why_this_step_for_you: text(step.why_this_step_for_you),
    };
  }));
}

export function parseIngredients(value: unknown, strict = false): Ingredient[] {
  const ingredients = list(value).map(value => {
    const ingredient = object(value);
    if (strict) identifier(ingredient.ingredient_id);
    return {
      ...(ingredient.ingredient_id !== undefined ? { ingredient_id: text(ingredient.ingredient_id) } : {}),
      name: text(ingredient.name),
      benefit: text(ingredient.benefit),
      why_for_you: text(ingredient.why_for_you),
      usage: text(ingredient.usage),
    };
  });
  if (strict && (!ingredients.length || ingredients.length > 5
      || new Set(ingredients.map(item => item.ingredient_id)).size !== ingredients.length)) throw new Error('Invalid preferred ingredient list.');
  return ingredients;
}

export function parseProducts(value: unknown, strict = false): Product[] {
  return list(value).map(value => {
    const product = object(value);
    let exact = {};
    if (strict || product.matched_count !== undefined) {
      const matched = product.matched_count, preferred = product.preferred_count;
      const matchedIds = ids(product.matched_ingredient_ids, 5);
      const requiredIds = ids(product.matched_must_have_ingredient_ids, 20);
      identifier(product.product_id);
      if (typeof product.product_id !== 'string' || !product.product_id
          || typeof matched !== 'number' || !Number.isInteger(matched) || matched < 1
          || typeof preferred !== 'number' || !Number.isInteger(preferred) || preferred < matched || preferred > 5
          || matchedIds.length !== matched
          || !['available', 'unavailable', 'unknown'].includes(text(product.availability))
          || (product.price_minor !== null && (!Number.isSafeInteger(product.price_minor) || Number(product.price_minor) < 0))
          || (product.currency !== null && !/^[A-Z]{3}$/.test(text(product.currency)))) {
        throw new Error('Invalid exact ingredient match metadata.');
      }
      exact = {
        matched_count: matched, preferred_count: preferred, matched_ingredient_ids: matchedIds,
        matched_must_have_ingredient_ids: requiredIds,
        price_minor: product.price_minor, currency: product.currency, availability: product.availability,
      };
    }
    return {
      ...exact,
      ...(product.product_id !== undefined ? { product_id: text(product.product_id) } : {}),
      name: text(product.name),
      price: text(product.price),
      match_score: text(product.match_score),
      image_url: safeProductImage(product.image_url),
      matched_ingredients: list(product.matched_ingredients ?? []).map(text),
      why_for_you: text(product.why_for_you),
      usage_tip: text(product.usage_tip),
    };
  });
}

export function recommendationOutcome(status: unknown, reason: unknown, products: Product[]) {
  if (status === 'matched' && reason == null && products.length >= 1 && products.length <= 3) {
    return { recommendation_status: 'matched' as const, no_match_reason: null };
  }
  if (status === 'no_match' && products.length === 0 && ['no_matching_products', 'catalog_changed'].includes(String(reason))) {
    return { recommendation_status: 'no_match' as const, no_match_reason: reason as 'no_matching_products' | 'catalog_changed' };
  }
  throw new Error('Invalid recommendation outcome.');
}

export function parseRoutine(value: unknown): CompiledRoutine {
  const data = object(decodeJson(value));
  const profile = object(data.user_profile);
  const strict = data.api_version === 2;
  if (data.api_version !== undefined && data.api_version !== 1 && data.api_version !== 2) throw new Error('Unknown routine version.');
  const steps = list(data.routine_steps);
  if (strict && (steps.length < 2 || steps.length > 8)) throw new Error('Invalid routine length.');
  return {
    ...(strict ? { api_version: 2 as const, applied_preferences: parsePreferences(data.applied_preferences) } : {}),
    user_profile: {
      skin_type: text(profile.skin_type),
      age: text(profile.age),
      concerns: list(profile.concerns).map(text),
      routine_rationale: text(profile.routine_rationale),
    },
    routine_steps: namedSteps(steps.map(value => {
      const step = object(value);
      const products = parseProducts(step.products, strict);
      if (strict && new Set(products.map(product => product.product_id)).size !== products.length) throw new Error('Duplicate product identity.');
      return {
        ...(strict ? recommendationOutcome(step.recommendation_status, step.no_match_reason, products) : {}),
        step_name: text(step.step_name),
        when: text(step.when),
        description: text(step.description),
        why_for_you: text(step.why_for_you),
        ingredients: parseIngredients(step.ingredients, strict),
        products,
      };
    })),
  };
}
