import { useEffect, useState } from 'react';
import { motion } from 'motion/react';

import type { SkinMetrics } from "../types";

interface SkinRadarChartProps {
  metrics: SkinMetrics;
  size?: number;
  animated?: boolean;
}

const LABELS = [
  { key: 'skin_health', label: 'Health', emoji: '💚' },
  { key: 'hydration', label: 'Hydration', emoji: '💧' },
  { key: 'texture', label: 'Texture', emoji: '✨' },
  { key: 'pore_size', label: 'Pores', emoji: '🔬' },
  { key: 'elasticity', label: 'Elasticity', emoji: '🤸' },
  { key: 'radiance', label: 'Radiance', emoji: '🌟' },
];

function polarToCartesian(cx: number, cy: number, r: number, angleDeg: number) {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

// Extra padding around the SVG so labels don't overflow
const LABEL_PAD = 40;

export const SkinRadarChart = ({ metrics, size = 260, animated = true }: SkinRadarChartProps) => {
  const [animatedMetrics, setAnimatedMetrics] = useState<SkinMetrics>(
    animated ? { skin_health: 0, hydration: 0, texture: 0, pore_size: 0, elasticity: 0, radiance: 0 } : metrics,
  );

  useEffect(() => {
    if (!animated) { setAnimatedMetrics(metrics); return; }
    const timer = setTimeout(() => setAnimatedMetrics(metrics), 300);
    return () => clearTimeout(timer);
  }, [metrics, animated]);

  const cx = size / 2;
  const cy = size / 2;
  const maxR = size * 0.36;
  const levels = [25, 50, 75, 100];
  const angleStep = 360 / LABELS.length;

  const points = LABELS.map((l, i) => {
    const val = animatedMetrics[l.key as keyof SkinMetrics] || 0;
    const r = (val / 100) * maxR;
    const angle = i * angleStep;
    return polarToCartesian(cx, cy, r, angle);
  });
  const polygonStr = points.map(p => `${p.x},${p.y}`).join(' ');

  // Outer container is larger than the SVG to hold labels
  const outerSize = size + LABEL_PAD * 2;

  return (
    <div
      className="relative flex-shrink-0"
      style={{ width: outerSize, height: outerSize }}
    >
      {/* SVG centered inside the padded container */}
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        style={{ position: 'absolute', left: LABEL_PAD, top: LABEL_PAD }}
      >
        {levels.map(level => {
          const r = (level / 100) * maxR;
          const ringPoints = LABELS.map((_, i) => {
            const angle = i * angleStep;
            return polarToCartesian(cx, cy, r, angle);
          });
          return (
            <polygon
              key={level}
              points={ringPoints.map(p => `${p.x},${p.y}`).join(' ')}
              fill="none"
              stroke="#E5E7EB"
              strokeWidth={level === 100 ? 1.5 : 0.8}
              opacity={0.6}
            />
          );
        })}

        {LABELS.map((_, i) => {
          const angle = i * angleStep;
          const end = polarToCartesian(cx, cy, maxR, angle);
          return <line key={i} x1={cx} y1={cy} x2={end.x} y2={end.y} stroke="#E5E7EB" strokeWidth={0.8} opacity={0.5} />;
        })}

        <motion.polygon
          points={polygonStr}
          fill="url(#radarGradient)"
          stroke="#8B9D83"
          strokeWidth={2}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.8, ease: 'easeOut' }}
        />

        {points.map((p, i) => (
          <motion.circle
            key={i}
            cx={p.x}
            cy={p.y}
            r={4}
            fill="#8B9D83"
            stroke="white"
            strokeWidth={2}
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ delay: 0.3 + i * 0.1, duration: 0.3 }}
          />
        ))}

        <defs>
          <linearGradient id="radarGradient" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#8B9D83" stopOpacity={0.35} />
            <stop offset="100%" stopColor="#B76E79" stopOpacity={0.2} />
          </linearGradient>
        </defs>
      </svg>

      {/* Labels positioned relative to the outer container */}
      {LABELS.map((l, i) => {
        const angle = i * angleStep;
        const labelR = maxR + 30;
        const pos = polarToCartesian(cx, cy, labelR, angle);
        const val = metrics[l.key as keyof SkinMetrics] || 0;
        return (
          <motion.div
            key={l.key}
            className="absolute flex flex-col items-center"
            style={{
              left: pos.x + LABEL_PAD,
              top: pos.y + LABEL_PAD,
              transform: 'translate(-50%, -50%)',
            }}
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.2 + i * 0.08 }}
          >
            <span className="text-xs">{l.emoji}</span>
            <span className="text-[10px] font-semibold text-gray-700 leading-tight">{l.label}</span>
            <span className="text-[10px] font-bold text-[#8B9D83]">{val}</span>
          </motion.div>
        );
      })}
    </div>
  );
};
