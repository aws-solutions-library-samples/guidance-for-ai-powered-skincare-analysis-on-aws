export interface SkinMetrics {
  skin_health: number;
  hydration: number;
  texture: number;
  pore_size: number;
  elasticity: number;
  radiance: number;
}

export interface SkinAnalysisProfile {
  skin_type: string;
  age: string;
  concerns: string[];
  current_condition: string;
  recommended_goals: string;
  skin_metrics: SkinMetrics;
  strengths: string[];
}

export interface RoutineProfile {
  skin_type: string;
  age: string;
  concerns: string[];
  routine_rationale: string;
}

export interface PlannedStep {
  step_name: string;
  when: string;
  why_this_step_for_you: string;
}

export interface Ingredient {
  name: string;
  benefit: string;
  why_for_you: string;
  usage: string;
}

export interface Product {
  name: string;
  price: string;
  match_score: string;
  image_url: string;
  matched_ingredients: string[];
  why_for_you: string;
  usage_tip: string;
}

export interface CompiledStep {
  step_name: string;
  when: string;
  description: string;
  why_for_you: string;
  ingredients: Ingredient[];
  products: Product[];
}

export interface CompiledRoutine {
  user_profile: RoutineProfile;
  routine_steps: CompiledStep[];
}

export interface PartialRoutineStep {
  step_name: string;
  ingredients?: Ingredient[];
  products?: Product[];
  analysis_notes?: string;
  status: 'waiting' | 'ingredients' | 'ready';
}

export type AnalysisStage = 'preparing' | 'skin_analysis' | 'routine_planning' | 'ingredients' | 'products' | 'complete';

export type AnalysisUpdate =
  | { type: 'progress'; step: AnalysisStage; message: string; stepName?: string }
  | { type: 'skin_profile'; profile: SkinAnalysisProfile }
  | { type: 'plan'; steps: PlannedStep[] }
  | { type: 'ingredients'; stepName: string; ingredients: Ingredient[]; analysisNotes: string }
  | { type: 'products'; stepName: string; products: Product[] };

export type Screen = 'landing' | 'signin' | 'camera' | 'loading' | 'results';
