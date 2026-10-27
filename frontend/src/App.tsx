import { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Layout } from './components/Layout';
import { IngredientPreferencesForm } from './components/IngredientPreferencesForm';
import { LandingPage } from './pages/LandingPage';
import { SignInPage } from './pages/SignInPage';
import { CameraPage } from './pages/CameraPage';
import { LoadingPage } from './pages/LoadingPage';
import { ResultsPage } from './pages/ResultsPage';
import { getAuthState, signOut } from './utils/auth';
import { useAnalysis } from './hooks/useAnalysis';
import type { PreferenceDraft, Screen } from './types';

function App() {
  const [screen, setScreen] = useState<Screen>('landing');
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const authGeneration = useRef(0);
  const [preferenceDraft, setPreferenceDraft] = useState<PreferenceDraft>({ preferences: {}, labels: {} });
  const [preferencesValid, setPreferencesValid] = useState(true);
  const analysis = useAnalysis();
  const { state } = analysis;

  useEffect(() => {
    const generation = authGeneration.current;
    let mounted = true;
    void getAuthState().then(auth => {
      if (mounted && authGeneration.current === generation) setUserEmail(auth.email);
    });
    return () => { mounted = false; };
  }, []);

  const handleStart = async () => {
    const generation = authGeneration.current;
    const auth = await getAuthState();
    if (authGeneration.current !== generation) return;
    setUserEmail(auth.email);
    analysis.reset();
    setPreferenceDraft({ preferences: {}, labels: {} });
    setPreferencesValid(true);
    setScreen(auth.isAuthenticated ? 'camera' : 'signin');
  };
  const handleSignInSuccess = async () => {
    const generation = authGeneration.current;
    const auth = await getAuthState();
    if (authGeneration.current !== generation) return;
    setUserEmail(auth.email);
    setPreferenceDraft({ preferences: {}, labels: {} });
    setPreferencesValid(true);
    setScreen(auth.isAuthenticated ? 'camera' : 'signin');
  };
  const handleReset = () => {
    analysis.reset();
    setScreen('camera');
  };
  const handleSignOut = () => {
    authGeneration.current += 1;
    analysis.reset();
    signOut();
    setUserEmail(null);
    setPreferenceDraft({ preferences: {}, labels: {} });
    setPreferencesValid(true);
    setScreen('landing');
  };

  const activeScreen = screen === 'loading'
    ? state.status === 'complete' ? 'results' : state.status === 'failed' ? 'camera' : 'loading'
    : screen;

  return (
    <Layout userEmail={userEmail} onSignOut={handleSignOut}>
      <AnimatePresence mode="wait">
        <motion.div key={activeScreen} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="w-full">
          {activeScreen === 'landing' && <LandingPage onStart={handleStart} />}
          {activeScreen === 'signin' && <SignInPage onSuccess={handleSignInSuccess} onBack={() => setScreen('landing')} />}
          {activeScreen === 'camera' && (
            <CameraPage
              onComplete={images => { setScreen('loading'); void analysis.start(images, preferenceDraft.preferences); }}
              preferencesValid={preferencesValid}
              preferencesForm={<IngredientPreferencesForm value={preferenceDraft} onChange={setPreferenceDraft} onValidityChange={setPreferencesValid} />}
              onCancel={() => { analysis.reset(); setScreen('landing'); }}
              error={state.error}
              errorCode={state.errorCode}
              requestId={state.requestId}
              onSignIn={() => { analysis.reset(); setScreen('signin'); }}
            />
          )}
          {activeScreen === 'loading' && (
            <LoadingPage
              currentStep={state.currentStep}
              insight={state.insight}
              partialRoutine={state.partialRoutine}
              skinProfile={state.skinProfile}
              plannedSteps={state.plannedSteps}
              capturedImages={state.capturedImages}
              onClose={handleReset}
            />
          )}
          {activeScreen === 'results' && state.results && (
            <ResultsPage results={state.results} skinProfile={state.skinProfile} preferenceLabels={preferenceDraft.labels} onStartOver={handleReset} />
          )}
        </motion.div>
      </AnimatePresence>
    </Layout>
  );
}

export default App;
