import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiService } from '../utils/api';
import type { AnalysisUpdate, CompiledRoutine } from '../types';
import { deferred, routineFixture } from '../test/fixtures';
import { useAnalysis } from './useAnalysis';

vi.mock('../utils/api', () => ({ ApiService: vi.fn() }));

type Request = ReturnType<typeof deferred<CompiledRoutine>> & {
  update: (update: AnalysisUpdate) => void;
  signal?: AbortSignal;
};
let requests: Request[];

beforeEach(() => {
  requests = [];
  vi.mocked(ApiService).mockImplementation(function () {
    return {
      startAnalysis: (_images: string[], _job: string, update: Request['update'], signal?: AbortSignal) => {
        const request = { ...deferred<CompiledRoutine>(), update, signal };
        requests.push(request);
        return request.promise;
      },
    } as ApiService;
  });
});
afterEach(cleanup);

it('reset aborts the request and ignores late progress and results', async () => {
  const { result } = renderHook(useAnalysis);
  let running!: Promise<void>;
  act(() => { running = result.current.start(['private-photo']); });
  expect(result.current.state.status).toBe('running');
  act(() => result.current.reset());
  expect(requests[0].signal?.aborted).toBe(true);
  await act(async () => {
    requests[0].update({ type: 'progress', step: 'products', message: 'stale progress' });
    requests[0].resolve(routineFixture());
    await running;
  });
  expect(result.current.state.status).toBe('idle');
  expect(result.current.state.results).toBeNull();
  expect(result.current.state.capturedImages).toEqual([]);
  expect(result.current.state.insight).toBe('');
});

it('a newer analysis owns state even if the old request completes last', async () => {
  const { result } = renderHook(useAnalysis);
  let first!: Promise<void>;
  let second!: Promise<void>;
  act(() => { first = result.current.start(['old-photo']); });
  act(() => { second = result.current.start(['new-photo']); });
  expect(requests[0].signal?.aborted).toBe(true);
  const latest = routineFixture();
  latest.user_profile.skin_type = 'Combination';
  await act(async () => { requests[1].resolve(latest); await second; });
  await act(async () => { requests[0].resolve(routineFixture()); await first; });
  expect(result.current.state.results?.user_profile.skin_type).toBe('Combination');
  expect(result.current.state.capturedImages).toEqual(['new-photo']);
});

it('an old failure cannot replace the newer run with an error', async () => {
  const { result } = renderHook(useAnalysis);
  let first!: Promise<void>;
  let second!: Promise<void>;
  act(() => { first = result.current.start(['old']); });
  act(() => { second = result.current.start(['new']); });
  await act(async () => { requests[0].reject(new Error('old error')); await first; });
  expect(result.current.state.status).toBe('running');
  expect(result.current.state.error).toBe('');
  await act(async () => { requests[1].resolve(routineFixture()); await second; });
});

it('unmount cancels the active request', async () => {
  const { result, unmount } = renderHook(useAnalysis);
  let running!: Promise<void>;
  act(() => { running = result.current.start(['photo']); });
  unmount();
  expect(requests[0].signal?.aborted).toBe(true);
  requests[0].resolve(routineFixture());
  await running;
});

it('merges progressive outputs into one planned step and preserves ready status', async () => {
  const { result } = renderHook(useAnalysis);
  let running!: Promise<void>;
  act(() => { running = result.current.start(['photo']); });
  const step = routineFixture().routine_steps[0];
  act(() => {
    requests[0].update({ type: 'plan', steps: [{ step_name: step.step_name, when: step.when, why_this_step_for_you: step.why_for_you }] });
    requests[0].update({ type: 'products', stepName: step.step_name, products: step.products });
    requests[0].update({ type: 'ingredients', stepName: step.step_name, ingredients: step.ingredients, analysisNotes: 'Gentle' });
  });
  expect(result.current.state.partialRoutine).toHaveLength(1);
  expect(result.current.state.partialRoutine[0]).toMatchObject({
    step_name: 'Cleanser', products: step.products, ingredients: step.ingredients, status: 'ready',
  });
  await act(async () => { requests[0].resolve(routineFixture()); await running; });
  expect(result.current.state.status).toBe('complete');
});
