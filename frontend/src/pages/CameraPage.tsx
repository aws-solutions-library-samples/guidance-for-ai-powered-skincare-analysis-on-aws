import { useState, useRef, useEffect } from 'react';
import Webcam from 'react-webcam';
import { motion } from 'motion/react';
import { Camera, X, RotateCcw, Check, Upload } from 'lucide-react';
import { Button } from '../components/ui/button';
import type { AnalysisErrorCode } from '../utils/analysisErrors';

interface CameraCaptureProps {
  onComplete: (images: string[]) => void;
  onCancel: () => void;
  error?: string;
  errorCode?: AnalysisErrorCode;
  requestId?: string;
  onSignIn?: () => void;
}

export const CameraPage = ({ onComplete, onCancel, error, errorCode, requestId, onSignIn }: CameraCaptureProps) => {
  const webcamRef = useRef<Webcam>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isReady, setIsReady] = useState(false);
  const [capturedImages, setCapturedImages] = useState<string[]>([]);
  const [cameraStarted, setCameraStarted] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [countdown, setCountdown] = useState<number | null>(null);
  const [showFlash, setShowFlash] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const uploadGeneration = useRef(0);
  const pendingUploads = useRef(0);
  const flashTimer = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => () => {
    uploadGeneration.current += 1;
    clearTimeout(flashTimer.current);
  }, []);

  const photoLabels = ['Photo 1', 'Photo 2', 'Photo 3'];

  const fileToBase64 = (file: File): Promise<string> =>
    new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error('Could not read this image. Please try another file.'));
      reader.onload = () => {
        const img = new Image();
        img.onload = () => {
          // Resize to max 1280px on longest side and convert to JPEG
          const MAX_DIM = 1280;
          let { width, height } = img;
          if (width > MAX_DIM || height > MAX_DIM) {
            const scale = MAX_DIM / Math.max(width, height);
            width = Math.round(width * scale);
            height = Math.round(height * scale);
          }
          const canvas = document.createElement('canvas');
          canvas.width = width;
          canvas.height = height;
          const ctx = canvas.getContext('2d');
          if (!ctx) { reject(new Error('Canvas not supported')); return; }
          ctx.drawImage(img, 0, 0, width, height);
          // toDataURL('image/jpeg', 0.85) ensures JPEG output at good quality
          try {
            const dataUrl = canvas.toDataURL('image/jpeg', 0.85);
            resolve(dataUrl.split(',')[1]);
          } catch {
            reject(new Error('Could not convert this image. Please try another file.'));
          }
        };
        img.onerror = () => reject(new Error('Failed to load image'));
        img.src = reader.result as string;
      };
      reader.readAsDataURL(file);
    });

  const handleFiles = async (files: FileList | File[]) => {
    const imageFiles = Array.from(files).filter(f => f.type.startsWith('image/'));
    const remaining = 3 - capturedImages.length;
    const toProcess = imageFiles.slice(0, remaining);
    if (!toProcess.length) return;
    const generation = uploadGeneration.current;
    pendingUploads.current += 1;
    setIsUploading(true);
    setUploadError('');
    try {
      const newImages = await Promise.all(toProcess.map(fileToBase64));
      if (generation === uploadGeneration.current) {
        // Capacity must be checked against current state after conversion.
        setCapturedImages(previous => [...previous, ...newImages].slice(0, 3));
      }
    } catch (error) {
      if (generation === uploadGeneration.current) {
        setUploadError(error instanceof Error ? error.message : 'Could not load these photos. Please try again.');
      }
    } finally {
      if (generation === uploadGeneration.current) {
        pendingUploads.current -= 1;
        setIsUploading(pendingUploads.current > 0);
      }
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files.length > 0) handleFiles(e.dataTransfer.files);
  };

  const handleDragOver = (e: React.DragEvent) => { e.preventDefault(); setIsDragging(true); };
  const handleDragLeave = () => setIsDragging(false);

  const startCamera = async () => {
    // Pre-check: is getUserMedia available?
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      console.error('[Camera] getUserMedia not available. Secure context:', window.isSecureContext, 'Protocol:', location.protocol);
      setCameraError(
        window.isSecureContext
          ? 'Camera API not available on this browser.'
          : 'Camera requires HTTPS. Your connection is not secure.'
      );
      return;
    }
    console.log('[Camera] Starting camera. Secure context:', window.isSecureContext);

    // iOS WebKit requires getUserMedia to be called directly within a user
    // gesture (tap/click). Calling it here triggers the permission prompt;
    // once granted, react-webcam's own getUserMedia call will succeed.
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'user' },
        audio: false,
      });
      // Permission granted — stop this temporary stream so react-webcam
      // can acquire its own.
      stream.getTracks().forEach(t => t.stop());
      console.log('[Camera] Permission granted via user gesture');
      setCameraStarted(true);
    } catch (err) {
      console.error('[Camera] getUserMedia error during gesture:', err);
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.includes('Permission') || msg.includes('NotAllowed')) {
        setCameraError('Camera permission denied. Please allow camera access in your browser settings.');
      } else if (msg.includes('NotFound') || msg.includes('DevicesNotFound')) {
        setCameraError('No camera found on this device.');
      } else if (msg.includes('NotReadable') || msg.includes('TrackStartError')) {
        setCameraError('Camera is in use by another app. Close other apps and try again.');
      } else {
        setCameraError(`Could not access camera: ${msg}`);
      }
    }
  };

  const startCountdown = () => {
    if (capturedImages.length >= 3 || isUploading) return;
    setCountdown(1);
  };

  useEffect(() => {
    if (countdown === null) return;
    if (countdown === 0) {
      setShowFlash(true);
      flashTimer.current = setTimeout(() => setShowFlash(false), 200);
      const imageSrc = webcamRef.current?.getScreenshot();
      if (imageSrc) {
        const base64 = imageSrc.split(',')[1];
        setCapturedImages(prev => [...prev, base64].slice(0, 3));
      }
      setCountdown(null);
      return;
    }
    const timer = setTimeout(() => setCountdown(countdown - 1), 1000);
    return () => clearTimeout(timer);
  }, [countdown]);

  const reset = () => {
    uploadGeneration.current += 1;
    pendingUploads.current = 0;
    clearTimeout(flashTimer.current);
    setIsUploading(false);
    setUploadError('');
    setShowFlash(false);
    setCapturedImages([]);
    setCountdown(null);
  };

  const handleComplete = () => {
    if (capturedImages.length === 3 && !isUploading) onComplete(capturedImages);
  };

  return (
    <div className="min-h-screen pt-16 sm:pt-20 bg-gradient-to-br from-rose-100 via-rose-50 to-pink-100 flex flex-col items-center justify-start sm:justify-center px-3 py-4 sm:p-4">
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={{ opacity: 0, scale: 0.95 }}
        className="relative w-full max-w-4xl mx-auto flex flex-col gap-3 sm:gap-6"
      >
        {/* Header */}
        <div className="flex justify-between items-center relative z-50">
          <button
            onClick={onCancel}
            aria-label="Cancel photo capture"
            className="text-gray-700 p-2.5 rounded-full bg-white/80 backdrop-blur-md hover:bg-white transition-colors shadow-lg"
          >
            <X size={20} />
          </button>
          <div className="text-gray-700 font-medium text-xs sm:text-sm bg-white/80 px-3 py-1.5 sm:px-4 sm:py-2 rounded-full backdrop-blur-md shadow-lg">
            {capturedImages.length}/3 Photos
          </div>
          <div className="w-10"></div>
        </div>

        {/* Instructions */}
        <div className="text-center">
          <h2 className="text-xl sm:text-3xl font-serif font-bold mb-1 sm:mb-2 text-gray-900">Capture Your Skin 📸</h2>
          <p className="text-gray-600 text-sm sm:text-base">Take 3 photos or upload from different angles</p>
          {error && (
            <div role="alert" className="text-red-800 mt-3 bg-red-50 border border-red-200 px-4 py-3 rounded-lg text-sm text-left">
              <p className="font-semibold">{errorCode?.startsWith('GUARDRAIL_') ? 'Analysis blocked by a safety check' : 'Analysis could not complete'}</p>
              <p className="mt-1">{error}</p>
              {errorCode && <p className="mt-2 text-xs">Error code: <span className="font-mono">{errorCode}</span></p>}
              {requestId && <p className="mt-1 text-xs break-all">Reference: <span className="font-mono">{requestId}</span></p>}
              {errorCode === 'AUTH_REQUIRED' && onSignIn && (
                <button onClick={onSignIn} className="mt-2 font-semibold underline">Sign in again</button>
              )}
            </div>
          )}
          {uploadError && <p role="alert" className="text-red-600 mt-2">{uploadError}</p>}
          {isUploading && <p role="status" className="text-gray-600 mt-2">Preparing photos...</p>}
        </div>

        {/* Main Content — stacks on mobile, side-by-side on md+ */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 sm:gap-6">
          {/* Camera Preview / Upload Zone */}
          <div className="md:col-span-2">
            <div className="relative aspect-[4/3] rounded-2xl overflow-hidden bg-black shadow-2xl">
              {cameraStarted ? (
                <>
                  <Webcam
                    audio={false}
                    ref={webcamRef}
                    screenshotFormat="image/jpeg"
                    forceScreenshotSourceSize={false}
                    videoConstraints={{ facingMode: "user" }}
                    playsInline
                    onUserMedia={() => { setIsReady(true); setCameraError(null); }}
                    onUserMediaError={(err) => {
                      console.error('[Camera] getUserMedia error:', err);
                      setIsReady(false);
                      const msg = err instanceof Error ? err.message : String(err);
                      if (msg.includes('Permission') || msg.includes('NotAllowed')) {
                        setCameraError('Camera permission denied. Please allow camera access in your browser settings.');
                      } else if (msg.includes('NotFound') || msg.includes('DevicesNotFound')) {
                        setCameraError('No camera found on this device.');
                      } else if (msg.includes('NotReadable') || msg.includes('TrackStartError')) {
                        setCameraError('Camera is in use by another app. Close other apps and try again.');
                      } else if (msg.includes('secure') || msg.includes('HTTPS')) {
                        setCameraError('Camera requires HTTPS. Make sure you are on a secure connection.');
                      } else {
                        setCameraError(`Could not access camera: ${msg}`);
                      }
                    }}
                    className="w-full h-full object-cover"
                    style={{ WebkitTransform: 'scaleX(1)' }}
                  />
                  {showFlash && <div className="absolute inset-0 bg-white animate-flash pointer-events-none" />}
                  {!isReady && (
                    <div className="absolute inset-0 flex flex-col items-center justify-center text-white/70 text-center p-8 bg-black/50 gap-4">
                      {cameraError ? (
                        <>
                          <p className="text-white">{cameraError}</p>
                          <Button
                            onClick={() => { setCameraStarted(false); setCameraError(null); }}
                            size="lg"
                            variant="outline"
                            className="gap-2 bg-white/10 border-white/30 text-white hover:bg-white/20"
                          >
                            <Upload size={20} />
                            Upload Photos Instead
                          </Button>
                        </>
                      ) : (
                        <p>Waiting for camera permission...</p>
                      )}
                    </div>
                  )}
                  {countdown !== null && (
                    <div className="absolute inset-0 flex items-center justify-center bg-black/30 backdrop-blur-sm">
                      <motion.div
                        key={countdown}
                        initial={{ scale: 1.5, opacity: 0 }}
                        animate={{ scale: 1, opacity: 1 }}
                        exit={{ scale: 0.5, opacity: 0 }}
                        className="text-white text-9xl font-bold"
                      >
                        {countdown}
                      </motion.div>
                    </div>
                  )}
                  {/* Pose guidance: show what's expected next */}
                  {isReady && countdown === null && capturedImages.length < 3 && (
                    <div className="absolute bottom-3 left-1/2 -translate-x-1/2 bg-black/60 backdrop-blur-sm rounded-full px-4 py-1.5 z-30">
                      <p className="text-white text-xs font-medium">
                        {photoLabels[capturedImages.length]}
                      </p>
                    </div>
                  )}
                </>
              ) : (
                /* Upload zone + Start Camera when camera is not started */
                <div
                  className={`absolute inset-0 flex flex-col items-center justify-center gap-6 transition-colors ${isDragging ? 'bg-rose-100/80' : 'bg-white/60'
                    } backdrop-blur-sm`}
                  onDrop={handleDrop}
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                >
                  <input
                    ref={fileInputRef}
                    aria-label="Upload photos"
                    type="file"
                    accept="image/*"
                    multiple
                    className="hidden"
                    onChange={(e) => { if (e.target.files) handleFiles(e.target.files); e.target.value = ''; }}
                  />
                  <div className="flex flex-col items-center gap-4">
                    <Button onClick={startCamera} size="lg" className="gap-2">
                      <Camera size={20} />
                      Start Camera
                    </Button>
                    <span className="text-gray-400 text-sm">or</span>
                    <Button
                      onClick={() => fileInputRef.current?.click()}
                      size="lg"
                      variant="outline"
                      className="gap-2"
                      disabled={capturedImages.length >= 3}
                    >
                      <Upload size={20} />
                      Upload Photos
                    </Button>
                    <p className="text-gray-400 text-xs mt-2 hidden sm:block">
                      {isDragging ? 'Drop images here' : 'You can also drag & drop images here'}
                    </p>
                  </div>
                </div>
              )}
            </div>

            {/* Tips — hidden on small mobile to save space */}
            <div className="hidden sm:block bg-white/90 backdrop-blur-md rounded-xl p-3 sm:p-4 text-gray-700 text-sm shadow-lg mt-3 sm:mt-4">
              <p className="font-semibold mb-1 sm:mb-2">💡 Tips for best results:</p>
              <ul className="space-y-1 text-xs text-gray-600">
                <li>• Use natural lighting if possible</li>
                <li>• Remove makeup for accurate analysis</li>
                <li>• Keep your face centered in the guide</li>
              </ul>
            </div>

            {/* Controls */}
            <div className="bg-white/95 backdrop-blur-md rounded-xl sm:rounded-2xl p-3 sm:p-6 mt-3 sm:mt-4 shadow-2xl border-2 border-gray-200">
              <div className="flex gap-2 sm:gap-4 justify-center flex-wrap">
                <button
                  onClick={reset}
                  disabled={capturedImages.length === 0 && !isUploading}
                  className="gap-1.5 sm:gap-2 px-3 sm:px-6 py-2.5 sm:py-3 rounded-lg bg-gray-800 text-white hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium flex items-center shadow-lg text-sm sm:text-base"
                >
                  <RotateCcw size={18} />
                  Reset
                </button>
                {cameraStarted && (
                  <button
                    onClick={startCountdown}
                    disabled={capturedImages.length >= 3 || !cameraStarted || countdown !== null || isUploading}
                    className="gap-1.5 sm:gap-2 px-4 sm:px-8 py-2.5 sm:py-3 rounded-lg bg-rose-600 text-white hover:bg-rose-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium flex items-center shadow-lg text-sm sm:text-base"
                  >
                    <Camera size={18} />
                    {countdown !== null ? `${countdown}...` : 'Capture (1s)'}
                  </button>
                )}
                {!cameraStarted && (
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    disabled={capturedImages.length >= 3}
                    className="gap-1.5 sm:gap-2 px-4 sm:px-8 py-2.5 sm:py-3 rounded-lg bg-rose-600 text-white hover:bg-rose-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium flex items-center shadow-lg text-sm sm:text-base"
                  >
                    <Upload size={18} />
                    Upload
                  </button>
                )}
                <button
                  onClick={handleComplete}
                  disabled={capturedImages.length !== 3 || isUploading}
                  className="gap-1.5 sm:gap-2 px-3 sm:px-6 py-2.5 sm:py-3 rounded-lg bg-green-600 text-white hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium flex items-center shadow-lg text-sm sm:text-base"
                >
                  <Check size={18} />
                  Analyze
                </button>
              </div>
            </div>
          </div>

          {/* Captured Photos Grid — horizontal on mobile, vertical column on md+ */}
          <div className="flex flex-row md:flex-col gap-2 sm:gap-3">
            {[0, 1, 2].map((index) => (
              <div
                key={index}
                className={`relative flex-1 md:flex-none aspect-[4/3] rounded-lg overflow-hidden border-2 transition-all ${capturedImages[index]
                  ? 'border-green-500 shadow-lg bg-white'
                  : 'border-dashed border-gray-300 bg-white/80'
                  }`}
              >
                {capturedImages[index] ? (
                  <>
                    <img
                      src={`data:image/jpeg;base64,${capturedImages[index]}`}
                      alt={`Captured ${index + 1}`}
                      className="w-full h-full object-cover"
                    />
                    <div className="absolute top-1 right-1 bg-green-500 text-white rounded-full p-0.5 sm:p-1">
                      <Check size={12} />
                    </div>
                  </>
                ) : (
                  <div className="absolute inset-0 flex flex-col items-center justify-center text-gray-400">
                    <Camera size={18} className="mb-0.5 sm:mb-1" />
                    <p className="text-[10px] sm:text-xs font-medium">{photoLabels[index]}</p>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </motion.div>
    </div>
  );
};
