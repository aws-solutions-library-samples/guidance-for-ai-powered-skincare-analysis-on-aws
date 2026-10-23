import type { PropsWithChildren } from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import App from './App';
import { ApiService } from './utils/api';
import { AnalysisError } from './utils/analysisErrors';
import { getAuthState, signOut } from './utils/auth';
import type { AnalysisUpdate, CompiledRoutine } from './types';
import { deferred, routineFixture } from './test/fixtures';

vi.mock('./utils/auth', () => ({ getAuthState: vi.fn(), signOut: vi.fn() }));
vi.mock('./utils/api', () => ({ ApiService: vi.fn() }));
vi.mock('motion/react', () => ({
  motion: { div: ({ children }: PropsWithChildren) => <div>{children}</div> },
  AnimatePresence: ({ children }: PropsWithChildren) => <>{children}</>,
}));
vi.mock('./components/Layout', () => ({
  Layout: ({ children, userEmail, onSignOut }: PropsWithChildren<{ userEmail: string | null; onSignOut: () => void }>) => (
    <div>{userEmail && <button onClick={onSignOut}>Sign out</button>}{children}</div>
  ),
}));
vi.mock('./pages/LandingPage', () => ({
  LandingPage: ({ onStart }: { onStart: () => void }) => <button onClick={onStart}>Start</button>,
}));
vi.mock('./pages/SignInPage', () => ({ SignInPage: () => <div>Sign in</div> }));
vi.mock('./pages/CameraPage', () => ({
  CameraPage: ({ onComplete, error }: { onComplete: (images: string[]) => void; error: string }) => (
    <div><button onClick={() => onComplete(['private-photo'])}>Analyze</button><p>{error}</p></div>
  ),
}));
vi.mock('./pages/LoadingPage', () => ({
  LoadingPage: ({ onClose, insight }: { onClose: () => void; insight: string }) => (
    <div>Analyzing<span>{insight}</span><button onClick={onClose}>Cancel analysis</button></div>
  ),
}));
vi.mock('./pages/ResultsPage', () => ({
  ResultsPage: () => <div>Private results</div>,
}));

let request: ReturnType<typeof deferred<CompiledRoutine>>;
let update: (value: AnalysisUpdate) => void;
let signal: AbortSignal | undefined;

beforeEach(() => {
  request = deferred<CompiledRoutine>();
  vi.mocked(getAuthState).mockResolvedValue({ isAuthenticated: true, email: 'test@example.invalid', idToken: 'dummy' });
  vi.mocked(ApiService).mockImplementation(function () {
    return {
      startAnalysis: (_images: string[], _job: string, onUpdate: typeof update, abortSignal?: AbortSignal) => {
        update = onUpdate;
        signal = abortSignal;
        return request.promise;
      },
    } as ApiService;
  });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

async function startAnalysis() {
  await act(async () => { render(<App />); });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Start' })); });
  fireEvent.click(screen.getByRole('button', { name: 'Analyze' }));
}

it('sign-out clears the active session and blocks stale results and progress', async () => {
  await startAnalysis();
  fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
  expect(signal?.aborted).toBe(true);
  expect(signOut).toHaveBeenCalledOnce();
  await act(async () => {
    update({ type: 'progress', step: 'products', message: 'private late progress' });
    request.resolve(routineFixture());
    await request.promise;
  });
  expect(screen.getByRole('button', { name: 'Start' })).toBeDefined();
  expect(screen.queryByText('Private results')).toBeNull();
  expect(screen.queryByText('private late progress')).toBeNull();
  expect(screen.queryByRole('button', { name: 'Sign out' })).toBeNull();
});

it('cancel returns to the camera and ignores late completion', async () => {
  await startAnalysis();
  fireEvent.click(screen.getByRole('button', { name: 'Cancel analysis' }));
  expect(signal?.aborted).toBe(true);
  await act(async () => { request.resolve(routineFixture()); await request.promise; });
  expect(screen.getByRole('button', { name: 'Analyze' })).toBeDefined();
  expect(screen.queryByText('Private results')).toBeNull();
});

it('shows the current request failure at the camera', async () => {
  await startAnalysis();
  await act(async () => {
    request.reject(new AnalysisError('SERVICE_UNAVAILABLE', 'job-reference'));
    await request.promise.catch(() => undefined);
  });
  expect(screen.getByText(/service is temporarily unavailable/)).toBeDefined();
  expect(screen.getByRole('button', { name: 'Analyze' })).toBeDefined();
});
