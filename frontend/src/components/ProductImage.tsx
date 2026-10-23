import { useState } from 'react';
import { ShoppingBag, Sun } from 'lucide-react';
import { safeProductImage } from '../utils/productImage';

interface ProductImageProps {
  src?: string;
  name: string;
  stepName: string;
  compact?: boolean;
}

export function ProductImage({ src, name, stepName, compact = false }: ProductImageProps) {
  src = safeProductImage(src);
  const [failedSource, setFailedSource] = useState<string>();
  const sunscreen = stepName === 'Sunscreen';
  const size = compact ? 'h-28' : 'h-36 sm:h-48';
  if (src && failedSource !== src) {
    return (
      <div className={`${size} bg-white flex items-center justify-center p-3`}>
        <img src={src} alt={name} referrerPolicy="no-referrer" className="w-full h-full object-contain" onError={() => setFailedSource(src)} />
      </div>
    );
  }
  return (
    <div className={`${size} flex items-center justify-center bg-gradient-to-br ${sunscreen ? 'from-amber-50 to-orange-100' : 'from-gray-100 to-gray-200'}`} aria-label={`No image available for ${name}`}>
      {sunscreen ? <Sun size={40} className="text-amber-500" /> : <ShoppingBag size={40} className="text-gray-400" />}
    </div>
  );
}
