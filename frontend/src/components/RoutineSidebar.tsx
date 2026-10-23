import { motion, AnimatePresence } from 'motion/react';
import { CheckCircle2, Loader2, Circle, Sparkles } from 'lucide-react';
import type { PartialRoutineStep, PlannedStep } from '../types';

interface RoutineSidebarProps {
  plannedSteps: PlannedStep[];
  partialRoutine: PartialRoutineStep[];
  currentStep: string;
  isAnalysisPhase: boolean;
}

export const RoutineSidebar = ({
  plannedSteps,
  partialRoutine,
  currentStep,
  isAnalysisPhase,
}: RoutineSidebarProps) => {
  if (isAnalysisPhase) {
    return (
      <div className="h-full flex flex-col">
        <h3 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
          <Sparkles size={14} className="text-[#B76E79]" />
          Your Routine
        </h3>
        <div className="flex-1 flex flex-col items-center justify-center text-center py-8">
          <motion.div
            animate={{ rotate: 360 }}
            transition={{ duration: 3, repeat: Infinity, ease: 'linear' }}
            className="w-12 h-12 rounded-full border-2 border-dashed border-[#B76E79]/40 flex items-center justify-center mb-4"
          >
            <Sparkles size={18} className="text-[#B76E79]" />
          </motion.div>
          <p className="text-sm text-gray-500 font-medium">
            {currentStep === 'preparing' && 'Preparing your images...'}
            {currentStep === 'skin_analysis' && 'Analyzing your skin first...'}
            {currentStep === 'routine_planning' && 'Planning your routine...'}
            {!['preparing', 'skin_analysis', 'routine_planning'].includes(currentStep) && 'Getting ready...'}
          </p>
          <p className="text-xs text-gray-400 mt-1">Steps will appear here</p>
        </div>
      </div>
    );
  }

  const steps = plannedSteps.length > 0 ? plannedSteps : [];

  return (
    <div className="h-full flex flex-col">
      <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
        <Sparkles size={14} className="text-[#B76E79]" />
        Your {steps.length}-Step Routine
      </h3>

      <div className="flex-1 overflow-y-auto space-y-2 pr-1">
        <AnimatePresence mode="popLayout">
          {steps.map((step, idx) => {
            const partial = partialRoutine.find(
              p => p.step_name.toLowerCase() === step.step_name.toLowerCase(),
            );
            const status = partial?.status || 'waiting';
            const isReady = status === 'ready';
            const isIngredients = status === 'ingredients';
            // Show spinner for all waiting steps once we're past planning phase
            const isActive = !isReady && !isIngredients && (
              currentStep === 'ingredients' || currentStep === 'products'
            );

            const ingredientNames = partial?.ingredients?.map(i => i.name).slice(0, 3) || [];

            return (
              <motion.div
                key={step.step_name}
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: idx * 0.08 }}
                className={`rounded-xl p-3 transition-all border ${
                  isReady
                    ? 'bg-[#8B9D83]/5 border-[#8B9D83]/30'
                    : isIngredients || isActive
                      ? 'bg-[#B76E79]/5 border-[#B76E79]/30'
                      : 'bg-white border-gray-100'
                }`}
              >
                <div className="flex items-start gap-2.5">
                  <div className="flex-shrink-0 mt-0.5">
                    {isReady ? (
                      <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }}>
                        <CheckCircle2 size={16} className="text-[#8B9D83]" />
                      </motion.div>
                    ) : isIngredients || isActive ? (
                      <Loader2 size={16} className="animate-spin text-[#B76E79]" />
                    ) : (
                      <Circle size={16} className="text-gray-300" />
                    )}
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-2">
                      <p className={`text-sm font-medium leading-tight ${
                        isReady ? 'text-[#2D3436]' : 'text-gray-600'
                      }`}>
                        {step.step_name}
                      </p>
                      <span className="text-[10px] text-gray-400 flex-shrink-0">{step.when}</span>
                    </div>

                    {/* Why this step */}
                    {step.why_this_step_for_you && (
                      <p className="text-[11px] text-gray-400 mt-0.5 leading-snug line-clamp-2">
                        {step.why_this_step_for_you}
                      </p>
                    )}

                    {/* Ingredient names as they arrive */}
                    {ingredientNames.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1.5">
                        {ingredientNames.map((name) => (
                          <span
                            key={name}
                            className="px-1.5 py-0.5 bg-[#8B9D83]/10 text-[#8B9D83] rounded text-[10px] font-medium"
                          >
                            {name}
                          </span>
                        ))}
                        {(partial?.ingredients?.length || 0) > 3 && (
                          <span className="px-1.5 py-0.5 bg-gray-100 text-gray-500 rounded text-[10px]">
                            +{(partial?.ingredients?.length || 0) - 3}
                          </span>
                        )}
                      </div>
                    )}

                    {/* Status text */}
                    {isReady && partial?.products && (
                      <p className="text-[11px] text-[#8B9D83] mt-1">
                        ✓ {partial.products.length} product{partial.products.length > 1 ? 's' : ''} matched
                      </p>
                    )}
                    {isIngredients && !ingredientNames.length && (
                      <p className="text-[11px] text-[#B76E79] mt-1">
                        Selecting ingredients...
                      </p>
                    )}
                    {isIngredients && ingredientNames.length > 0 && (
                      <p className="text-[11px] text-[#B76E79] mt-1">
                        Finding matching products...
                      </p>
                    )}
                    {!isReady && !isIngredients && isActive && (
                      <p className="text-[11px] text-gray-400 mt-1">Selecting ingredients...</p>
                    )}
                  </div>
                </div>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>

      {/* Progress summary */}
      <div className="mt-3 pt-3 border-t border-gray-100">
        <div className="flex items-center justify-between text-xs text-gray-500">
          <span>
            {partialRoutine.filter(p => p.status === 'ready').length} of {steps.length} complete
          </span>
          <div className="flex gap-1">
            {steps.map((step, i) => {
              const partial = partialRoutine.find(
                p => p.step_name.toLowerCase() === step.step_name.toLowerCase(),
              );
              return (
                <div
                  key={i}
                  className={`w-2 h-2 rounded-full transition-colors ${
                    partial?.status === 'ready'
                      ? 'bg-[#8B9D83]'
                      : partial?.status === 'ingredients'
                        ? 'bg-[#B76E79]'
                        : 'bg-gray-200'
                  }`}
                />
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};
