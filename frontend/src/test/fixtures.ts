import type { CompiledRoutine, SkinAnalysisProfile } from '../types';

export function routineFixture(): CompiledRoutine {
  return {
    user_profile: { skin_type: 'Dry', age: '25-32', concerns: ['dryness'], routine_rationale: 'Gentle cleansing and protection.' },
    routine_steps: ['Cleanser', 'Sunscreen'].map(step_name => ({
      step_name, when: 'Morning', description: 'Use daily', why_for_you: 'Suitable for dry skin',
      ingredients: [{ name: 'Glycerin', benefit: 'Hydration', why_for_you: 'Helps dryness', usage: 'Daily' }],
      products: [{
        name: `Gentle ${step_name}`, price: '£12.00', match_score: '100%', image_url: '',
        matched_ingredients: ['Glycerin'], why_for_you: 'Gentle care', usage_tip: 'Use as directed',
      }],
    })),
  };
}

export function profileFixture(): SkinAnalysisProfile {
  return {
    skin_type: 'Dry', age: '25-32', concerns: ['dryness'], current_condition: 'Dry',
    recommended_goals: 'Hydration', strengths: ['Even tone'],
    skin_metrics: { skin_health: 70, hydration: 60, texture: 70, pore_size: 80, elasticity: 80, radiance: 70 },
  };
}

export function compileEvent(routine: unknown = routineFixture()) {
  return {
    type: 'multiagent_node_stop', node_id: 'compile', node_result: {
      status: 'completed',
      result: { results: { compile: { status: 'completed', result: {
        message: { role: 'assistant', content: [{ text: JSON.stringify(routine) }] },
      } } } },
    },
  };
}

export const finalEvent = () => ({ type: 'multiagent_result', result: { status: 'completed' } });

export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((success, failure) => { resolve = success; reject = failure; });
  return { promise, resolve, reject };
}
