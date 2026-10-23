import React from 'react';
import { motion } from 'motion/react';
import { Sparkles, LogOut, User } from 'lucide-react';

interface LayoutProps {
  children: React.ReactNode;
  userEmail?: string | null;
  onSignOut?: () => void;
}

export const Layout = ({ children, userEmail, onSignOut }: LayoutProps) => {
  return (
    <div className="relative min-h-screen w-full overflow-hidden bg-gradient-to-br from-rose-50 via-white to-rose-100 font-sans selection:bg-rose-200">

      {/* Floating Particles */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none z-0">
        {[...Array(6)].map((_, i) => (
          <motion.div
            key={i}
            className="absolute rounded-full bg-rose-200/20 blur-3xl"
            initial={{
              x: Math.random() * 100 + "%",
              y: Math.random() * 100 + "%",
              scale: Math.random() * 0.5 + 0.5,
            }}
            animate={{
              x: [
                Math.random() * 100 + "%",
                Math.random() * 100 + "%",
                Math.random() * 100 + "%",
              ],
              y: [
                Math.random() * 100 + "%",
                Math.random() * 100 + "%",
                Math.random() * 100 + "%",
              ],
            }}
            transition={{
              duration: Math.random() * 20 + 20,
              repeat: Infinity,
              ease: "linear",
            }}
            style={{
              width: Math.random() * 400 + 200 + "px",
              height: Math.random() * 400 + 200 + "px",
            }}
          />
        ))}
      </div>

      {/* Header */}
      <header className="relative z-10 px-4 py-3 sm:px-6 sm:py-6 flex justify-between items-center max-w-7xl mx-auto w-full">
        <motion.div
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          className="flex items-center gap-2"
        >
          <div className="w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-gradient-to-br from-rose-400 to-orange-300 flex items-center justify-center text-white shadow-lg shadow-rose-200">
            <Sparkles size={14} fill="currentColor" />
          </div>
          <h1 className="text-lg sm:text-2xl font-serif font-bold text-gray-800 tracking-tight">Smart Beauty</h1>
        </motion.div>

        {/* User Status */}
        {userEmail && (
          <motion.div
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            className="flex items-center gap-2 sm:gap-3"
          >
            <div className="hidden sm:flex items-center gap-2 px-3 py-2 rounded-full bg-white/60 backdrop-blur-sm border border-white/80 shadow-sm">
              <User size={14} className="text-rose-500" />
              <span className="text-sm text-gray-700 font-medium">Logged in</span>
            </div>
            {onSignOut && (
              <button
                onClick={onSignOut}
                className="p-2.5 rounded-full bg-white/60 backdrop-blur-sm border border-white/80 hover:bg-rose-50 transition-colors shadow-sm"
                title="Sign out"
              >
                <LogOut size={16} className="text-gray-600" />
              </button>
            )}
          </motion.div>
        )}
      </header>

      {/* Main Content */}
      <main className="relative z-10 w-full min-h-[calc(100vh-80px)]">
        {children}
      </main>
    </div>
  );
};
