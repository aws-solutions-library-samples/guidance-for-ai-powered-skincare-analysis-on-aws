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
  ingredient_id?: string;
  name: string;
  benefit: string;
  why_for_you: string;
  usage: string;
}

export interface Product {
  product_id?: string;
  name: string;
  price: string;
  match_score: string;
  image_url: string;
  matched_ingredients: string[];
  why_for_you: string;
  usage_tip: string;
  matched_count?: number;
  preferred_count?: number;
  matched_ingredient_ids?: string[];
  matched_must_have_ingredient_ids?: string[];
  price_minor?: number | null;
  currency?: string | null;
  availability?: 'available' | 'unavailable' | 'unknown';
}

export interface CompiledStep {
  step_name: string;
  when: string;
  description: string;
  why_for_you: string;
  ingredients: Ingredient[];
  products: Product[];
  recommendation_status?: 'matched' | 'no_match';
  no_match_reason?: 'no_matching_products' | 'catalog_changed' | null;
}

export interface CompiledRoutine {
  api_version?: 2;
  applied_preferences?: IngredientPreferences;
  user_profile: RoutineProfile;
  routine_steps: CompiledStep[];
}

export interface PartialRoutineStep {
  step_name: string;
  ingredients?: Ingredient[];
  products?: Product[];
  analysis_notes?: string;
  status: 'waiting' | 'ingredients' | 'ready' | 'no_match';
}

export type AnalysisStage = 'preparing' | 'skin_analysis' | 'routine_planning' | 'ingredients' | 'products' | 'complete';

export type AnalysisUpdate =
  | { type: 'progress'; step: AnalysisStage; message: string; stepName?: string }
  | { type: 'skin_profile'; profile: SkinAnalysisProfile }
  | { type: 'plan'; steps: PlannedStep[] }
  | { type: 'ingredients'; stepName: string; ingredients: Ingredient[]; analysisNotes: string }
  | { type: 'products'; stepName: string; products: Product[]; recommendationStatus?: 'matched' | 'no_match' };

export interface IngredientPreferences {
  excluded_ingredient_ids?: string[];
  must_have_by_category?: { category_id: string; ingredient_ids: string[] }[];
  market?: string | null;
  currency?: string | null;
  max_price_minor?: number | null;
}

export interface PreferenceDraft {
  preferences: IngredientPreferences;
  labels: Record<string, string>;
}

export interface IngredientOption {
  ingredient_id: string;
  display_name: string;
}

export interface IngredientLookupResult {
  taxonomy_version: string;
  categories: string[];
  supported_markets: string[];
  supported_currencies: string[];
  default_market: string | null;
  default_currency: string | null;
  currency_minor_units: Record<string, number>;
  as_of?: number | null;
  ingredients?: IngredientOption[];
  results?: ({ status: 'resolved' } & IngredientOption | { status: 'unresolved' | 'ambiguous' })[];
}

export type Screen = 'landing' | 'signin' | 'camera' | 'loading' | 'results';
