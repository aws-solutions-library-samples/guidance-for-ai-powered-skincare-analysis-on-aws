import { Info, ShoppingBag, Sparkles } from 'lucide-react';
import { ProductImage } from './ProductImage';
import type { CompiledStep } from '../types';

export function RoutineStepDetails({ step }: { step: CompiledStep }) {
  return (
    <article className="bg-white rounded-3xl shadow-xl overflow-hidden md:max-h-[70vh] md:flex md:flex-col">
      <div className="bg-gradient-to-r from-[#8B9D83]/10 to-[#B76E79]/10 p-4 sm:p-6 border-b-2 border-gray-100">
        <h2 className="text-2xl sm:text-3xl font-serif font-bold text-[#2D3436] mb-2">{step.step_name}</h2>
        <p className="text-sm text-gray-500 mb-3">{step.when}</p>
        {step.why_for_you && (
          <div className="bg-[#A8E6CF]/20 rounded-xl p-3 flex items-start gap-2">
            <Info size={16} className="text-[#8B9D83] flex-shrink-0 mt-0.5" />
            <p className="text-gray-700 text-sm">{step.why_for_you}</p>
          </div>
        )}
      </div>
      <div className="p-4 sm:p-6 space-y-6 overflow-y-auto flex-1">
        <section>
          <h3 className="text-xl font-semibold text-[#2D3436] mb-4 flex items-center gap-2">
            <Sparkles size={20} className="text-[#B76E79]" />Key Ingredients ({step.ingredients.length})
          </h3>
          {step.ingredients.length === 0 ? <p className="text-gray-500">No ingredients were recommended for this step.</p> : (
            <div className="space-y-3">
              {step.ingredients.map((ingredient, index) => (
                <div key={`${ingredient.name}-${index}`} className="px-4 py-3 rounded-xl bg-gray-50">
                  <h4 className="font-semibold text-gray-900">{ingredient.name}</h4>
                  <p className="text-sm text-gray-600">{ingredient.benefit}</p>
                  {ingredient.why_for_you && ingredient.why_for_you !== ingredient.benefit && (
                    <p className="text-sm text-[#8B9D83] mt-1 italic">For you: {ingredient.why_for_you}</p>
                  )}
                  {ingredient.usage && <p className="text-sm text-gray-500 mt-1">{ingredient.usage}</p>}
                </div>
              ))}
            </div>
          )}
        </section>
        <section>
          <h3 className="text-xl font-semibold text-[#2D3436] mb-4 flex items-center gap-2">
            <ShoppingBag size={20} className="text-[#B76E79]" />Recommended Products ({step.products.length})
          </h3>
          {step.products.length === 0 ? <p className="text-gray-500">No matching products were found for this step.</p> : (
            <div className="space-y-4">
              {step.products.map((product, index) => (
                <article key={`${product.name}-${index}`} className="bg-gray-50 rounded-2xl overflow-hidden">
                  <ProductImage src={product.image_url} name={product.name} stepName={step.step_name} />
                  <div className="p-4">
                    {product.match_score && (
                      <p className="text-xs text-[#8B9D83] mb-2">Ingredient match: {product.match_score} · {product.matched_ingredients.length} matching ingredients</p>
                    )}
                    <h4 className="font-semibold text-gray-900 mb-2">{product.name}</h4>
                    <p className="text-xl font-bold text-[#B76E79] mb-3">{product.price}</p>
                    {product.why_for_you && <p className="bg-[#A8E6CF]/20 rounded-lg p-3 mb-2 text-sm text-gray-700"><strong>Why this works for you:</strong> {product.why_for_you}</p>}
                    {product.usage_tip && <p className="bg-blue-50 rounded-lg p-3 mb-2 text-sm text-gray-700"><strong>Usage tip:</strong> {product.usage_tip}</p>}
                    {product.matched_ingredients.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-3">
                        {product.matched_ingredients.map((ingredient, i) => <span key={`${ingredient}-${i}`} className="px-2 py-0.5 bg-[#8B9D83]/20 text-[#8B9D83] rounded text-xs">{ingredient}</span>)}
                      </div>
                    )}
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
    </article>
  );
}
