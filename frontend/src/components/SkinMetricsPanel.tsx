import { motion } from 'motion/react';
import { Droplet, AlertTriangle, Shield } from 'lucide-react';

interface SkinMetricsPanelProps {
  concerns: string[];
  strengths: string[];
  currentCondition: string;
  hydration: number;
  skinHealth: number;
  /** Show only the progress bars (health + hydration) */
  barsOnly?: boolean;
  /** Show only the text sections (condition, concerns, strengths) */
  textOnly?: boolean;
}

export const SkinMetricsPanel = ({
  concerns,
  strengths,
  currentCondition,
  hydration,
  skinHealth,
  barsOnly = false,
  textOnly = false,
}: SkinMetricsPanelProps) => {
  const showBars = !textOnly;
  const showText = !barsOnly;

  return (
    <div className="space-y-4">
      {showBars && (
        <div className="space-y-3 pb-2">
          {/* Skin Health Score */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-gray-700 flex items-center gap-1">
                <Shield size={12} className="text-[#8B9D83]" />
                Skin Health
              </span>
              <span className="text-xs font-bold text-[#8B9D83]">{skinHealth}/100</span>
            </div>
            <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
              <motion.div
                className="h-full rounded-full"
                style={{
                  background: `linear-gradient(90deg, #B76E79 0%, #8B9D83 ${Math.min(skinHealth, 100)}%)`,
                }}
                initial={{ width: 0 }}
                animate={{ width: `${skinHealth}%` }}
                transition={{ duration: 1, ease: 'easeOut', delay: 0.3 }}
              />
            </div>
          </div>

          {/* Hydration Level */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-gray-700 flex items-center gap-1">
                <Droplet size={12} className="text-blue-500" />
                Hydration Level
              </span>
              <span className="text-xs font-bold text-blue-500">{hydration}%</span>
            </div>
            <div className="h-2 bg-blue-100 rounded-full overflow-hidden">
              <motion.div
                className="h-full bg-gradient-to-r from-blue-300 to-blue-500 rounded-full"
                initial={{ width: 0 }}
                animate={{ width: `${hydration}%` }}
                transition={{ duration: 1, ease: 'easeOut', delay: 0.5 }}
              />
            </div>
          </div>
        </div>
      )}

      {showText && (
        <>
          {/* Current Condition */}
          {currentCondition && (
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.4 }}
              className="bg-[#8B9D83]/10 rounded-xl p-3"
            >
              <p className="text-xs text-gray-700 leading-relaxed">{currentCondition}</p>
            </motion.div>
          )}

          {/* Concerns + Strengths side by side when both exist */}
          <div className={concerns.length > 0 && strengths.length > 0 ? 'grid grid-cols-2 gap-3' : ''}>
            {/* Concerns */}
            {concerns.length > 0 && (
              <div>
                <p className="text-sm font-semibold text-gray-700 mb-2 flex items-center gap-1.5">
                  <AlertTriangle size={14} className="text-amber-500" />
                  Areas of Focus
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {concerns.map((concern, i) => (
                    <motion.span
                      key={concern}
                      initial={{ opacity: 0, scale: 0.8 }}
                      animate={{ opacity: 1, scale: 1 }}
                      transition={{ delay: 0.5 + i * 0.1 }}
                      className="inline-flex items-center px-2.5 py-1 rounded-full text-[11px] font-medium bg-amber-50 text-amber-800 border border-amber-200"
                    >
                      {concern}
                    </motion.span>
                  ))}
                </div>
              </div>
            )}

            {/* Strengths */}
            {strengths.length > 0 && (
              <div>
                <p className="text-sm font-semibold text-gray-700 mb-2 flex items-center gap-1.5">
                  <span className="text-sm">💪</span>
                  Strengths
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {strengths.map((strength, i) => (
                    <motion.span
                      key={strength}
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: 0.6 + i * 0.1 }}
                      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium bg-emerald-100 text-emerald-700"
                    >
                      ✓ {strength}
                    </motion.span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
};
