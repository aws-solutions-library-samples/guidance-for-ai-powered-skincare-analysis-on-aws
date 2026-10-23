import type { CompiledRoutine, Ingredient, PlannedStep, Product, SkinAnalysisProfile, SkinMetrics } from '../types';
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

export function parseIngredients(value: unknown): Ingredient[] {
  return list(value).map(value => {
    const ingredient = object(value);
    return {
      name: text(ingredient.name),
      benefit: text(ingredient.benefit),
      why_for_you: text(ingredient.why_for_you),
      usage: text(ingredient.usage),
    };
  });
}

export function parseProducts(value: unknown): Product[] {
  return list(value).map(value => {
    const product = object(value);
    return {
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

export function parseRoutine(value: unknown): CompiledRoutine {
  const data = object(decodeJson(value));
  const profile = object(data.user_profile);
  return {
    user_profile: {
      skin_type: text(profile.skin_type),
      age: text(profile.age),
      concerns: list(profile.concerns).map(text),
      routine_rationale: text(profile.routine_rationale),
    },
    routine_steps: namedSteps(list(data.routine_steps).map(value => {
      const step = object(value);
      return {
        step_name: text(step.step_name),
        when: text(step.when),
        description: text(step.description),
        why_for_you: text(step.why_for_you),
        ingredients: parseIngredients(step.ingredients),
        products: parseProducts(step.products),
      };
    })),
  };
}
