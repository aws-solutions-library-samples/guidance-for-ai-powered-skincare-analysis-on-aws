import { motion } from 'motion/react';
import { Camera, ScanFace, Sparkles, ArrowRight } from 'lucide-react';
import { Button } from '../components/ui/button';

interface LandingPageProps {
  onStart: () => void;
}

export const LandingPage = ({ onStart }: LandingPageProps) => {
  const steps = [
    {
      icon: <Camera size={24} className="text-white" />,
      title: "Snap a Selfie",
      desc: "Take a quick photo in natural light",
      color: "bg-rose-400"
    },
    {
      icon: <ScanFace size={24} className="text-white" />,
      title: "AI Analysis",
      desc: "Our smart tech scans for 12+ skin metrics",
      color: "bg-rose-500"
    },
    {
      icon: <Sparkles size={24} className="text-white" />,
      title: "Get Your Glow",
      desc: "Receive a personalized routine instantly",
      color: "bg-rose-600"
    }
  ];

  return (
    <div className="flex flex-col items-center justify-center min-h-[85vh] px-5 py-8 sm:px-6 sm:py-12 md:px-8 max-w-7xl mx-auto">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 lg:gap-12 items-center w-full">

        {/* Left Content */}
        <motion.div
          initial={{ opacity: 0, x: -50 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.8, ease: "easeOut" }}
          className="space-y-8 z-10"
        >
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-white/60 backdrop-blur-sm border border-white/40 shadow-sm text-rose-800 text-sm font-medium">
            <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse"></span>
            AI-Powered Skincare Analysis
          </div>

          <h1 className="text-3xl sm:text-5xl md:text-7xl font-serif font-bold text-gray-900 leading-[1.1]">
            Unlock Your <br />
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-rose-400 to-orange-400">Perfect Glow</span>
          </h1>

          <p className="text-base sm:text-lg md:text-xl text-gray-600 max-w-lg leading-relaxed">
            Experience the future of skincare with our advanced AI analysis. Get a personalized routine tailored to your unique skin profile in seconds.
          </p>

          <div className="pt-4">
            <Button
              size="lg"
              onClick={onStart}
              className="shadow-rose-300/40 shadow-xl"
            >
              Start Analysis <ArrowRight className="ml-2 h-5 w-5" />
            </Button>
          </div>

          <div className="pt-8 sm:pt-12 grid grid-cols-1 sm:grid-cols-3 gap-4 sm:gap-6">
            {steps.map((step, idx) => (
              <motion.div
                key={idx}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.4 + idx * 0.1 }}
                className="flex flex-col gap-3"
              >
                <div className={`w-12 h-12 rounded-2xl ${step.color} shadow-lg shadow-rose-200 flex items-center justify-center rotate-3 hover:rotate-6 transition-transform`}>
                  {step.icon}
                </div>
                <div>
                  <h3 className="font-semibold text-gray-900">{step.title}</h3>
                  <p className="text-sm text-gray-500 leading-snug">{step.desc}</p>
                </div>
              </motion.div>
            ))}
          </div>
        </motion.div>

        {/* Right Image - Abstract Skincare */}
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.8 }}
          className="relative h-[400px] lg:h-[600px] hidden lg:block"
        >
          <div className="absolute inset-0 bg-gradient-to-tr from-rose-200 to-transparent rounded-[3rem] transform rotate-3 opacity-50 blur-2xl"></div>
          <div className="absolute inset-0 z-10 rounded-[3rem] overflow-hidden shadow-2xl shadow-rose-200/50 border-8 border-white">
            <img
              src="/hero-skincare.jpg"
              alt="Skincare products"
              className="w-full h-full object-cover"
            />
          </div>
        </motion.div>
      </div>
    </div>
  );
};
