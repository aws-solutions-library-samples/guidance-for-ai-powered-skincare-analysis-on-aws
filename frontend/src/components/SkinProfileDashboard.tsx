import { useState, useEffect } from 'react';
import { motion } from 'motion/react';
import { SkinRadarChart } from './SkinRadarChart';
import { SkinTypeCards } from './SkinTypeCards';
import { SkinMetricsPanel } from './SkinMetricsPanel';

import type { SkinAnalysisProfile } from "../types";

interface SkinProfileDashboardProps {
  skinProfile: SkinAnalysisProfile | null;
  isLoading?: boolean;
  compact?: boolean;
  capturedImages?: string[];
}

const DEFAULT_METRICS = {
  skin_health: 0, hydration: 0, texture: 0,
  pore_size: 0, elasticity: 0, radiance: 0,
};

/* ── Analysis labels that cycle ── */
const ANALYSIS_LABELS = [
  'Analyzing texture…',
  'Checking hydration…',
  'Measuring pores…',
  'Evaluating elasticity…',
  'Assessing radiance…',
];

/* ── Single Photo Card — clean scan line only ── */
const PhotoCard = ({ imgSrc, index }: { imgSrc: string; index: number }) => {
  return (
    <div className="relative flex-1 rounded-xl overflow-hidden shadow-lg bg-black aspect-[3/4]">
      <img src={imgSrc} alt={`Photo ${index + 1}`} className="absolute inset-0 w-full h-full object-cover" />

      {/* Subtle dark vignette */}
      <div className="absolute inset-0 z-10" style={{
        background: 'radial-gradient(ellipse at center, transparent 50%, rgba(0,0,0,0.3) 100%)',
      }} />

      {/* Primary scan line — green to rose gradient */}
      <motion.div
        className="absolute left-0 right-0 z-20"
        style={{ height: '2px' }}
        animate={{ top: ['0%', '100%', '0%'] }}
        transition={{ duration: 3.5, repeat: Infinity, ease: 'easeInOut', delay: index * 0.6 }}
      >
        <div className="w-full h-full" style={{
          background: 'linear-gradient(90deg, transparent 2%, #8B9D83 20%, #B76E79 80%, transparent 98%)',
        }} />
        {/* Glow beneath the line */}
        <div className="w-full h-8 -mt-3 opacity-40" style={{
          background: 'linear-gradient(90deg, transparent 5%, rgba(139,157,131,0.6) 30%, rgba(183,110,121,0.6) 70%, transparent 95%)',
          filter: 'blur(8px)',
        }} />
      </motion.div>

      {/* Secondary faint scan line — offset timing */}
      <motion.div
        className="absolute left-0 right-0 h-[1px] z-20 opacity-30"
        style={{
          background: 'linear-gradient(90deg, transparent 10%, rgba(255,255,255,0.5) 50%, transparent 90%)',
        }}
        animate={{ top: ['100%', '0%', '100%'] }}
        transition={{ duration: 5, repeat: Infinity, ease: 'easeInOut', delay: index * 0.4 + 1 }}
      />

      {/* Corner brackets */}
      {(['top-2 left-2', 'top-2 right-2', 'bottom-2 left-2', 'bottom-2 right-2'] as const).map((pos, i) => (
        <div key={i} className={`absolute ${pos} w-4 h-4 z-20`} style={{
          borderColor: 'rgba(255,255,255,0.5)', borderWidth: 0,
          ...(i < 2 ? { borderTopWidth: 1.5 } : { borderBottomWidth: 1.5 }),
          ...(i % 2 === 0 ? { borderLeftWidth: 1.5 } : { borderRightWidth: 1.5 }),
        }} />
      ))}
    </div>
  );
};

/* ── Scan Animation — shows all 3 photos with scan lines ── */
const ScanAnimation = ({ capturedImages }: { capturedImages: string[] }) => {
  const [labelIndex, setLabelIndex] = useState(0);

  useEffect(() => {
    const t = setInterval(() => setLabelIndex(i => (i + 1) % ANALYSIS_LABELS.length), 2000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="flex flex-col items-center justify-center py-2 text-gray-400">
      <div className="w-full flex gap-2 sm:gap-3">
        {capturedImages.map((img, i) => (
          <PhotoCard key={i} imgSrc={`data:image/jpeg;base64,${img}`} index={i} />
        ))}
      </div>
      <motion.div
        key={labelIndex}
        className="mt-3 bg-black/5 backdrop-blur-sm rounded-full px-4 py-1.5"
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <p className="text-gray-600 text-xs font-medium tracking-wide">{ANALYSIS_LABELS[labelIndex]}</p>
      </motion.div>
      <p className="text-xs mt-2 text-gray-400">This takes a few seconds</p>
    </div>
  );
};


/* ── Fallback scan (no photos) ── */
const FallbackScan = () => (
  <div className="flex flex-col items-center justify-center py-4 text-gray-400">
    <div className="relative w-56 h-72 sm:w-64 sm:h-80 rounded-2xl overflow-hidden bg-gradient-to-br from-[#8B9D83]/10 to-[#B76E79]/10 flex items-center justify-center">
      <motion.div
        className="absolute left-0 right-0 h-[3px]"
        style={{
          background: 'linear-gradient(90deg, transparent, #8B9D83, #B76E79, transparent)',
          boxShadow: '0 0 20px 4px rgba(139,157,131,0.5)',
        }}
        animate={{ top: ['0%', '100%', '0%'] }}
        transition={{ duration: 4, repeat: Infinity, ease: 'easeInOut' }}
      />
      <motion.p
        className="text-sm font-medium text-gray-500 z-10"
        animate={{ opacity: [0.5, 1, 0.5] }}
        transition={{ duration: 2, repeat: Infinity }}
      >
        Analyzing your skin…
      </motion.p>
    </div>
    <p className="text-xs mt-3 text-gray-400">This takes a few seconds</p>
  </div>
);

/* ── Main Dashboard Component ── */
export const SkinProfileDashboard = ({
  skinProfile,
  isLoading = false,
  compact = false,
  capturedImages = [],
}: SkinProfileDashboardProps) => {

  /* Loading state */
  if (isLoading && !skinProfile) {
    if (capturedImages.length > 0) {
      return <ScanAnimation capturedImages={capturedImages} />;
    }
    return <FallbackScan />;
  }

  if (!skinProfile) return null;

  const metrics = skinProfile.skin_metrics || DEFAULT_METRICS;
  const concerns = skinProfile.concerns || [];
  const strengths = skinProfile.strengths || [];
  const chartSize = compact ? 150 : 160;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      className="space-y-3"
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className={`font-serif font-bold text-[#2D3436] ${compact ? 'text-base' : 'text-lg'}`}>
            Your Skin Profile
          </h2>
          {skinProfile.age && (
            <p className="text-xs text-gray-500 mt-0.5">Age range: {skinProfile.age}</p>
          )}
        </div>
      </div>

      {/* Goal — horizontal banner */}
      {skinProfile.recommended_goals && !compact && (
        <div className="bg-[#8B9D83]/10 rounded-lg px-3 py-2 flex items-center gap-2">
          <span className="text-[9px] text-gray-500 uppercase tracking-wide whitespace-nowrap">🎯 Goal</span>
          <p className="text-xs text-gray-700 font-medium leading-snug">{skinProfile.recommended_goals}</p>
        </div>
      )}

      {/* Skin Type Cards */}
      {skinProfile.skin_type && (
        <SkinTypeCards activeType={skinProfile.skin_type} />
      )}

      {/* Radar Chart + Health/Hydration bars */}
      <div className="flex flex-row items-center gap-6">
        <div className="flex-shrink-0">
          <SkinRadarChart metrics={metrics} size={chartSize} animated={true} />
        </div>
        <div className="flex-1 min-w-0">
          <SkinMetricsPanel
            concerns={[]}
            strengths={[]}
            currentCondition=""
            hydration={metrics.hydration}
            skinHealth={metrics.skin_health}
            barsOnly
          />
        </div>
      </div>

      {/* Condition + Concerns + Strengths */}
      <SkinMetricsPanel
        concerns={concerns}
        strengths={strengths}
        currentCondition={skinProfile.current_condition || ''}
        hydration={0}
        skinHealth={0}
        textOnly
      />
    </motion.div>
  );
};
