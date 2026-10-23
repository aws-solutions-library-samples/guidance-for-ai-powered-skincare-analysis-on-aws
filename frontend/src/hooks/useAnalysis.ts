import { useEffect, useReducer, useRef } from 'react';
import { API_CONFIG } from '../config/constants';
import { ApiService } from '../utils/api';
import { AnalysisError } from '../utils/analysisErrors';
import type { AnalysisErrorCode } from '../utils/analysisErrors';
import type { AnalysisStage, AnalysisUpdate, CompiledRoutine, PartialRoutineStep, PlannedStep, SkinAnalysisProfile } from '../types';

interface AnalysisState {
  status: 'idle' | 'running' | 'complete' | 'failed';
  currentStep: AnalysisStage;
  insight: string;
  error: string;
  errorCode?: AnalysisErrorCode;
  requestId?: string;
  results: CompiledRoutine | null;
  skinProfile: SkinAnalysisProfile | null;
  plannedSteps: PlannedStep[];
  partialRoutine: PartialRoutineStep[];
  capturedImages: string[];
}

const initialState: AnalysisState = {
  status: 'idle', currentStep: 'preparing', insight: '', error: '', results: null,
  skinProfile: null, plannedSteps: [], partialRoutine: [], capturedImages: [],
};

type Action =
  | { type: 'reset' }
  | { type: 'start'; images: string[] }
  | { type: 'update'; update: AnalysisUpdate }
  | { type: 'complete'; results: CompiledRoutine }
  | { type: 'failed'; error: AnalysisError };

function reducer(state: AnalysisState, action: Action): AnalysisState {
  if (action.type === 'reset') return initialState;
  if (action.type === 'start') return { ...initialState, status: 'running', capturedImages: action.images };
  if (action.type === 'complete') return { ...state, status: 'complete', currentStep: 'complete', results: action.results };
  if (action.type === 'failed') return { ...state, status: 'failed', error: action.error.message, errorCode: action.error.code, requestId: action.error.requestId };
  const update = action.update;
  if (update.type === 'progress') return { ...state, currentStep: update.step, insight: update.message };
  if (update.type === 'skin_profile') return { ...state, skinProfile: update.profile, insight: 'Skin analysis complete.' };
  if (update.type === 'plan') {
    return {
      ...state, plannedSteps: update.steps, insight: `Created your ${update.steps.length}-step routine.`,
      partialRoutine: update.steps.map(step => ({ step_name: step.step_name, status: 'waiting' })),
    };
  }
  const existing = state.partialRoutine.find(step => step.step_name === update.stepName);
  const step: PartialRoutineStep = update.type === 'ingredients'
    ? { ...existing, step_name: update.stepName, ingredients: update.ingredients, analysis_notes: update.analysisNotes, status: existing?.status === 'ready' ? 'ready' : 'ingredients' }
    : { ...existing, step_name: update.stepName, products: update.products, status: 'ready' };
  return {
    ...state,
    partialRoutine: existing
      ? state.partialRoutine.map(previous => previous.step_name === step.step_name ? step : previous)
      : [...state.partialRoutine, step],
  };
}

/** Own the request and its state together, including cancellation on reset/unmount. */
export function useAnalysis() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const active = useRef<AbortController | null>(null);

  const cancel = () => {
    const previous = active.current;
    active.current = null;
    previous?.abort();
  };
  useEffect(() => cancel, []);

  const reset = () => {
    cancel();
    dispatch({ type: 'reset' });
  };
  const start = async (images: string[]) => {
    cancel();
    const controller = new AbortController();
    active.current = controller;
    const jobId = crypto.randomUUID();
    dispatch({ type: 'start', images });
    try {
      const results = await new ApiService(API_CONFIG.DEFAULT_URL).startAnalysis(
        images,
        jobId,
        update => {
          if (active.current === controller) dispatch({ type: 'update', update });
        },
        controller.signal,
      );
      if (active.current === controller) dispatch({ type: 'complete', results });
    } catch (error) {
      if (active.current === controller) {
        dispatch({ type: 'failed', error: error instanceof AnalysisError ? error : new AnalysisError('ANALYSIS_FAILED', jobId) });
      }
    } finally {
      if (active.current === controller) active.current = null;
    }
  };
  return { state, start, reset };
}
