import { motion } from 'motion/react';

interface SkinTypeCardsProps {
  activeType: string;
}

const SKIN_TYPES = [
  { type: 'Normal', emoji: '✨', color: 'from-emerald-400 to-emerald-600', desc: 'Balanced, even texture' },
  { type: 'Dry', emoji: '🏜️', color: 'from-amber-400 to-amber-600', desc: 'Tight, flaky patches' },
  { type: 'Oily', emoji: '💧', color: 'from-blue-400 to-blue-600', desc: 'Shiny, enlarged pores' },
  { type: 'Combination', emoji: '🔄', color: 'from-purple-400 to-purple-600', desc: 'Mixed zones' },
  { type: 'Sensitive', emoji: '🌸', color: 'from-rose-400 to-rose-600', desc: 'Reactive, easily irritated' },
];

export const SkinTypeCards = ({ activeType }: SkinTypeCardsProps) => {
  const normalizedActive = activeType.toLowerCase();

  return (
    <div className="flex flex-wrap gap-2">
      {SKIN_TYPES.map((st, i) => {
        const isActive = normalizedActive === st.type.toLowerCase();
        return (
          <motion.div
            key={st.type}
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: i * 0.08, duration: 0.3 }}
            className={`relative rounded-xl px-3 py-2 transition-all ${
              isActive
                ? 'ring-2 ring-[#8B9D83] shadow-lg bg-white'
                : 'bg-white/60 opacity-50'
            }`}
          >
            <div className="flex items-center gap-2">
              <div className={`w-8 h-8 rounded-lg bg-gradient-to-br ${st.color} flex items-center justify-center text-sm`}>
                {st.emoji}
              </div>
              <div>
                <p className="text-xs font-semibold text-gray-800 leading-tight">{st.type}</p>
                {isActive && (
                  <motion.p
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    className="text-[10px] text-gray-500 leading-tight"
                  >
                    {st.desc}
                  </motion.p>
                )}
              </div>
            </div>
            {isActive && (
              <motion.div
                layoutId="activeIndicator"
                className="absolute -top-1 -right-1 w-4 h-4 bg-[#8B9D83] rounded-full flex items-center justify-center"
              >
                <span className="text-white text-[8px]">✓</span>
              </motion.div>
            )}
          </motion.div>
        );
      })}
    </div>
  );
};
