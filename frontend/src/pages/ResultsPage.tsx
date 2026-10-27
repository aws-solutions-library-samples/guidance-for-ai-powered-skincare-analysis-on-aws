import { useState, useRef } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { RefreshCw, Sparkles, ChevronDown, ChevronUp } from 'lucide-react';
import { Button } from '../components/ui/button';
import { SkinProfileDashboard } from '../components/SkinProfileDashboard';
import { ProductImage } from '../components/ProductImage';
import { RoutineStepDetails } from '../components/RoutineStepDetails';
import type { CompiledRoutine, SkinAnalysisProfile } from '../types';

interface ResultsPageProps {
  results: CompiledRoutine;
  onStartOver: () => void;
  skinProfile?: SkinAnalysisProfile | null;
  preferenceLabels?: Record<string, string>;
}

export function ResultsPage({ results, onStartOver, skinProfile, preferenceLabels = {} }: ResultsPageProps) {
  const [selectedName, setSelectedName] = useState('');
  const [showSkinProfile, setShowSkinProfile] = useState(false);
  const detailsRef = useRef<HTMLDivElement>(null);
  const steps = results.routine_steps;
  const selected = steps.find(step => step.step_name === selectedName) ?? steps[0];
  const profile = results.user_profile;

  if (!selected) {
    return (
      <div className="min-h-screen flex items-center justify-center p-8 bg-[#F5F3F0]">
        <div className="bg-white rounded-3xl p-8 text-center shadow-xl">
          <h2 className="text-2xl font-serif mb-4">Unable to Generate Routine</h2>
          <p className="text-gray-600 mb-4">No routine steps were returned. Please try again.</p>
          <Button onClick={onStartOver}>Try Again</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-[#F5F3F0] via-[#FAF9F6] to-[#E8E6E3]">
      <header className="bg-gradient-to-br from-[#8B9D83] to-[#2D3436] text-white py-6 px-4">
        <div className="max-w-7xl mx-auto">
          <div className="inline-flex items-center gap-2 bg-white/20 px-4 py-2 rounded-full mb-3 text-sm"><Sparkles size={14} />Your Personalized Routine</div>
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <h1 className="text-3xl font-serif font-bold mb-2">{steps.every(step => step.products.length === 0) ? 'No matching products' : 'Your skincare routine'}</h1>
              <p>{profile.skin_type} skin · Skin age: {profile.age}</p>
              <div className="flex flex-wrap gap-2 mt-3">
                {profile.concerns.map((concern, index) => <span key={`${concern}-${index}`} className="px-3 py-1 bg-white/20 rounded-full text-sm">{concern}</span>)}
              </div>
            </div>
            <div className="flex gap-3">
              {skinProfile && (
                <Button onClick={() => setShowSkinProfile(value => !value)} aria-expanded={showSkinProfile} className="gap-2 bg-white/20 hover:bg-white/30">
                  {showSkinProfile ? <ChevronUp size={16} /> : <ChevronDown size={16} />}Skin Profile
                </Button>
              )}
              <Button onClick={onStartOver} className="gap-2 bg-white/20 hover:bg-white/30"><RefreshCw size={16} />New Analysis</Button>
            </div>
          </div>
        </div>
      </header>
      <main className="max-w-7xl mx-auto p-4 md:p-8">
        {results.applied_preferences && <section className="rounded-2xl bg-white p-4 mb-6 text-sm text-gray-700" aria-label="Applied preferences">
          <h2 className="font-semibold mb-2">Applied preferences</h2>
          {!!results.applied_preferences.excluded_ingredient_ids?.length && <p>Excluded from every step: {results.applied_preferences.excluded_ingredient_ids.map(id => preferenceLabels[id] ?? 'selected ingredient').join(', ')}</p>}
          {results.applied_preferences.must_have_by_category?.map(entry => <p key={entry.category_id}>Required in {entry.category_id}: {entry.ingredient_ids.map(id => preferenceLabels[id] ?? 'selected ingredient').join(', ')}</p>)}
          {results.applied_preferences.market && <p>Market: {results.applied_preferences.market}</p>}
          {results.applied_preferences.max_price_minor != null && <p>Maximum per product: {results.applied_preferences.currency} {(results.applied_preferences.max_price_minor / 100).toFixed(2)}</p>}
          <p className="mt-2 text-gray-500">Counts show how many selected ingredients each product contains.</p>
        </section>}
        <AnimatePresence>
          {showSkinProfile && skinProfile && (
            <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
              <div className="bg-white rounded-2xl shadow-lg p-6 mb-6"><SkinProfileDashboard skinProfile={skinProfile} compact /></div>
            </motion.div>
          )}
        </AnimatePresence>
        <section className="bg-gradient-to-br from-[#8B9D83]/10 to-[#B76E79]/10 rounded-3xl p-6 shadow-lg mb-6">
          <h2 className="text-2xl font-serif font-bold text-[#2D3436] mb-3">Why This Routine?</h2>
          {skinProfile?.current_condition && <p className="text-gray-600 text-sm italic mb-3">{skinProfile.current_condition}</p>}
          <p className="text-gray-700 leading-relaxed">{profile.routine_rationale}</p>
          {skinProfile?.recommended_goals && <p className="mt-3 text-sm"><strong>Goals:</strong> {skinProfile.recommended_goals}</p>}
        </section>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 md:items-start">
          <nav aria-label="Routine steps" className="md:col-span-1">
            <h2 className="text-lg font-semibold text-[#2D3436] mb-4">Your {steps.length}-Step Routine</h2>
            <div className="flex md:flex-col gap-3 overflow-x-auto md:overflow-y-auto md:max-h-[70vh] p-1">
              {steps.map((step, index) => {
                const product = step.products[0];
                const active = selected.step_name === step.step_name;
                return (
                  <button key={step.step_name} type="button" aria-pressed={active}
                    onClick={() => { setSelectedName(step.step_name); detailsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }}
                    className={`text-left rounded-2xl overflow-hidden min-w-[200px] md:min-w-0 bg-white ${active ? 'shadow-xl ring-2 ring-[#8B9D83]' : 'border-2 border-gray-100 hover:shadow-md'}`}>
                    <div className="px-3 py-2 font-semibold text-[#2D3436]">{index + 1}. {step.step_name}</div>
                    <ProductImage src={product?.image_url} name={product?.name ?? step.step_name} stepName={step.step_name} compact />
                    <div className="p-3">
                      <div className="flex flex-wrap gap-1 mb-2">
                        {step.ingredients.slice(0, 3).map((ingredient, i) => <span key={`${ingredient.name}-${i}`} className="px-2 py-1 bg-[#8B9D83]/10 text-[#8B9D83] rounded-full text-xs">{ingredient.name}</span>)}
                      </div>
                      {product ? <><p className="text-sm font-semibold text-gray-900">{product.name}</p><p className="font-bold text-[#B76E79]">{product.price}</p></> : <p className="text-sm text-gray-500">No matching products</p>}
                    </div>
                  </button>
                );
              })}
            </div>
          </nav>
          <div ref={detailsRef} className="md:col-span-2">
            <RoutineStepDetails step={selected} />
          </div>
        </div>
      </main>
    </div>
  );
}
