import { useState } from 'react';
import { ShoppingBag, Sun } from 'lucide-react';
import { productPlaceholder, safeProductImage } from '../utils/productImage';

interface ProductImageProps {
  src?: string;
  name: string;
  stepName: string;
  compact?: boolean;
}

export function ProductImage({ src, name, stepName, compact = false }: ProductImageProps) {
  src = safeProductImage(src);
  const [failedSources, setFailedSources] = useState<string[]>([]);
  const placeholder = productPlaceholder(stepName);
  const catalogSource = src && !failedSources.includes(src) ? src : '';
  const imageSource = catalogSource || (placeholder && !failedSources.includes(placeholder) ? placeholder : '');
  const illustrative = !!imageSource && !catalogSource;
  const sunscreen = stepName === 'Sunscreen';
  const size = compact ? 'h-28' : 'h-36 sm:h-48';
  if (imageSource) {
    return (
      <div className={`${size} relative flex items-center justify-center ${illustrative ? 'bg-[#F5F3F0]' : 'bg-white p-3'}`}>
        <img
          src={imageSource}
          alt={illustrative ? `Illustrative ${stepName.toLowerCase()} packaging, not a photo of ${name}` : name}
          referrerPolicy="no-referrer"
          loading="lazy"
          decoding="async"
          className="w-full h-full object-contain"
          onError={() => setFailedSources(previous => previous.includes(imageSource) ? previous : [...previous, imageSource])}
        />
        {illustrative && (
          <span className="absolute bottom-2 left-2 rounded-full bg-white/90 px-2 py-0.5 text-[10px] text-gray-600">
            Illustrative image
          </span>
        )}
      </div>
    );
  }
  return (
    <div className={`${size} flex items-center justify-center bg-gradient-to-br ${sunscreen ? 'from-amber-50 to-orange-100' : 'from-gray-100 to-gray-200'}`} aria-label={`No image available for ${name}`}>
      {sunscreen ? <Sun size={40} className="text-amber-500" /> : <ShoppingBag size={40} className="text-gray-400" />}
    </div>
  );
}
