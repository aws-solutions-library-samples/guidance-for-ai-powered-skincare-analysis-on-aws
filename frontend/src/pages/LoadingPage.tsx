import { motion } from 'motion/react';
import type { PartialRoutineStep, PlannedStep, SkinAnalysisProfile } from '../types';
import { SkinProfileDashboard } from '../components/SkinProfileDashboard';
import { RoutineSidebar } from '../components/RoutineSidebar';

interface LoadingPageProps {
  currentStep?: string;
  insight?: string;
  partialRoutine?: PartialRoutineStep[];
  skinProfile?: SkinAnalysisProfile | null;
  plannedSteps?: PlannedStep[];
  capturedImages?: string[];
  onClose?: () => void;
}

const stepConfig: Record<string, { emoji: string; title: string; progress: string }> = {
  preparing:        { emoji: '📸', title: 'Preparing Images',       progress: '5%' },
  skin_analysis:    { emoji: '🔍', title: 'Analyzing Your Skin',    progress: '20%' },
  routine_planning: { emoji: '✨', title: 'Creating Your Routine',   progress: '40%' },
  ingredients:      { emoji: '🌿', title: 'Selecting Ingredients',  progress: '60%' },
  products:         { emoji: '🛍️', title: 'Finding Best Products',  progress: '80%' },
  complete:         { emoji: '✅', title: 'Your Routine is Ready!', progress: '100%' },
};

export const LoadingPage = ({
  currentStep = 'preparing',
  insight = '',
  partialRoutine = [],
  skinProfile = null,
  plannedSteps = [],
  capturedImages = [],
  onClose,
}: LoadingPageProps) => {
  const config = stepConfig[currentStep] ?? stepConfig.preparing;

  // Phase 1 = still doing skin analysis or planning (no planned steps yet)
  const isAnalysisPhase =
    currentStep === 'preparing' ||
    currentStep === 'skin_analysis' ||
    (currentStep === 'routine_planning' && plannedSteps.length === 0);

  return (
    <div className="min-h-screen pt-16 bg-gradient-to-br from-[#F5F3F0] via-[#FAF9F6] to-[#E8E6E3]">
      {/* Floating orbs */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none -z-10">
        <motion.div
          animate={{ x: [0, 100, 0], y: [0, -100, 0] }}
          transition={{ duration: 20, repeat: Infinity, ease: 'linear' }}
          className="absolute top-20 left-20 w-96 h-96 bg-[#8B9D83]/20 rounded-full blur-3xl"
        />
        <motion.div
          animate={{ x: [0, -100, 0], y: [0, 100, 0] }}
          transition={{ duration: 25, repeat: Infinity, ease: 'linear' }}
          className="absolute bottom-20 right-20 w-96 h-96 bg-[#B76E79]/20 rounded-full blur-3xl"
        />
      </div>

      <div className="max-w-7xl mx-auto px-4 md:px-8 py-4 sm:py-6">
        {onClose && <button onClick={onClose} className="mb-4 text-sm text-gray-600 hover:text-gray-900">Cancel analysis</button>}
        {/* Header + Progress */}
        <div className="text-center mb-4 sm:mb-6">
          <motion.div
            key={currentStep}
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            className="text-4xl sm:text-5xl mb-2"
          >
            {config.emoji}
          </motion.div>
          <h1 className="text-xl sm:text-2xl font-serif font-bold text-[#2D3436] mb-1">{config.title}</h1>
          {insight && (
            <motion.p
              key={insight}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              className="text-gray-500 text-sm max-w-md mx-auto"
            >
              {insight}
            </motion.p>
          )}
        </div>

        <div className="h-1.5 bg-gray-200 rounded-full overflow-hidden mb-4 sm:mb-6 max-w-xl mx-auto">
          <motion.div
            className="h-full bg-gradient-to-r from-[#8B9D83] to-[#B76E79] rounded-full"
            animate={{ width: config.progress }}
            transition={{ duration: 0.6, ease: 'easeOut' }}
          />
        </div>

        {/* Split Layout: Skin Profile (65%) | Routine Sidebar (35%) */}
        <div className="flex flex-col md:flex-row gap-4 sm:gap-6">
          {/* LEFT — Skin Profile Dashboard (65%) */}
          <motion.div
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.4 }}
            className="md:w-[65%] bg-white rounded-2xl shadow-lg p-4 sm:p-6 min-h-[300px] sm:min-h-[400px]"
          >
            <SkinProfileDashboard
              skinProfile={skinProfile}
              isLoading={!skinProfile}
              capturedImages={capturedImages}
            />
          </motion.div>

          {/* RIGHT — Routine Sidebar (35%) */}
          <motion.div
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.4, delay: 0.1 }}
            className="md:w-[35%] bg-white rounded-2xl shadow-lg p-4 sm:p-5 min-h-[250px] sm:min-h-[400px]"
          >
            <RoutineSidebar
              plannedSteps={plannedSteps}
              partialRoutine={partialRoutine}
              currentStep={currentStep}
              isAnalysisPhase={isAnalysisPhase}
            />
          </motion.div>
        </div>


      </div>
    </div>
  );
};
