import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiService } from './api';
import { getIdToken } from './auth';
import { analysisErrors } from './analysisErrors';
import { compileEvent, finalEvent, profileFixture, routineFixture } from '../test/fixtures';

vi.mock('./auth', () => ({ getIdToken: vi.fn() }));

function mockStream(text: string, chunkSize = Number.MAX_SAFE_INTEGER) {
  const bytes = new TextEncoder().encode(text);
  let offset = 0;
  const reader = {
    read: vi.fn(async () => {
      if (offset >= bytes.length) return { done: true, value: undefined };
      const value = bytes.slice(offset, offset + chunkSize);
      offset += chunkSize;
      return { done: false, value };
    }),
    cancel: vi.fn(async () => undefined),
    releaseLock: vi.fn(),
  };
  const fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, body: { getReader: () => reader } });
  vi.stubGlobal('fetch', fetch);
  return { reader, fetch };
}

function frames(events: unknown[], newline = '\n') {
  return events.map(event => `data: ${JSON.stringify(event)}${newline}${newline}`).join('');
}

const start = (onUpdate = vi.fn(), signal?: AbortSignal) =>
  new ApiService('https://example.invalid/api/').startAnalysis(['image'], 'test-job', onUpdate, signal);

beforeEach(() => vi.mocked(getIdToken).mockResolvedValue('dummy-token'));
afterEach(() => vi.clearAllMocks());

describe('SSE transport and application contract', () => {
  it.each(['USER_RATE_LIMITED', 'ANALYSIS_IN_PROGRESS'])('distinguishes proxy %s from service throttling', async code => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      code, request_id: 'safe-reference', message: 'PRIVATE PROVIDER DETAILS',
    }), { status: 429, headers: { 'Content-Type': 'application/json' } })));
    await expect(start()).rejects.toMatchObject({
      code, requestId: 'safe-reference', message: analysisErrors[code as keyof typeof analysisErrors].message,
    });
  });

  it('ignores unexpected provider JSON on a throttled HTTP response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      code: 'PRIVATE_CODE', message: 'PRIVATE PROVIDER DETAILS',
    }), { status: 429, headers: { 'Content-Type': 'application/json' } })));
    await expect(start()).rejects.toMatchObject({ code: 'RATE_LIMITED' });
  });

  it('handles arbitrarily split UTF-8, CRLF, comments and an intermediate phase result', async () => {
    const routine = routineFixture();
    routine.routine_steps[0].products[0].name = 'Crème hydratante 🌿';
    const onUpdate = vi.fn();
    const events = [
      { type: 'multiagent_node_start', node_id: 'skin_analysis' },
      { type: 'multiagent_node_stop', node_id: 'skin_analysis', node_result: {
        status: 'completed', result: { structured_output: profileFixture() },
      } },
      finalEvent(), compileEvent(routine), finalEvent(),
    ];
    const { reader, fetch } = mockStream(`: heartbeat\r\n\r\n${frames(events, '\r\n')}`, 1);
    expect(await start(onUpdate)).toEqual(routine);
    expect(onUpdate.mock.calls.map(([update]) => update.type)).toEqual(['progress', 'skin_profile']);
    expect(fetch.mock.calls[0][0]).toBe('https://example.invalid/api/analyze');
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ images: ['image'], job_id: 'test-job' });
    expect(fetch.mock.calls[0][1].headers.Authorization).toBe('Bearer dummy-token');
    expect(reader.cancel).toHaveBeenCalledOnce();
    expect(reader.releaseLock).toHaveBeenCalledOnce();
  });

  it('decodes JSON-string payloads and the final frame without a trailing newline', async () => {
    mockStream(frames([JSON.stringify(compileEvent())]) + `data: ${JSON.stringify(JSON.stringify(finalEvent()))}`);
    expect(await start()).toEqual(routineFixture());
  });

  it('joins multiline data fields in one SSE event', async () => {
    const data = JSON.stringify(compileEvent(), null, 2).split('\n').map(line => `data: ${line}`).join('\n');
    mockStream(`${data}\n\n${frames([finalEvent()])}`);
    expect(await start()).toEqual(routineFixture());
  });

  it('maps planned, ingredient, and product outputs to typed updates', async () => {
    const step = routineFixture().routine_steps[0];
    const onUpdate = vi.fn();
    const stop = (node_id: string, structured_output: unknown) => ({
      type: 'multiagent_node_stop', node_id, node_result: { status: 'completed', result: { structured_output } },
    });
    mockStream(frames([
      stop('step_analysis', { routine_steps: [{ ...step, why_this_step_for_you: step.why_for_you }] }),
      stop('ingredients_Cleanser', { step_name: 'Cleanser', key_ingredients: step.ingredients, analysis_notes: 'Gentle' }),
      stop('products_Cleanser', { step_name: 'Cleanser', top_recommendations: step.products }),
      compileEvent(), finalEvent(),
    ]));
    await start(onUpdate);
    expect(onUpdate.mock.calls.map(([update]) => update.type)).toEqual(['plan', 'ingredients', 'products']);
    expect(onUpdate.mock.calls[1][0].ingredients).toEqual(step.ingredients);
    expect(onUpdate.mock.calls[2][0].products).toEqual(step.products);
  });

  it.each([
    ['error event', frames([{ type: 'error', message: 'Compilation failed' }]), /analysis could not complete/],
    ['truncated graph', frames([finalEvent()]), /complete routine/],
    ['missing final result', frames([compileEvent()]), /complete routine/],
    ['malformed JSON', 'data: {"type":\n\n', /complete routine/],
    ['invalid routine', frames([compileEvent({}), finalEvent()]), /complete routine/],
    ['failed final graph', frames([compileEvent(), { type: 'multiagent_result', result: { status: 'failed' } }]), /complete/],
  ])('rejects %s and releases the stream', async (_name, wire, error) => {
    const { reader } = mockStream(wire);
    await expect(start()).rejects.toThrow(error);
    expect(reader.cancel).toHaveBeenCalledOnce();
    expect(reader.releaseLock).toHaveBeenCalledOnce();
  });

  it.each(['pending', 'executing'])('does not call a %s terminal graph successful', async status => {
    mockStream(frames([compileEvent(), { type: 'multiagent_result', result: { status } }]));
    await expect(start()).rejects.toThrow();
  });

  it('does not hide a late error behind a successful terminal result', async () => {
    mockStream(frames([compileEvent(), finalEvent(), { type: 'error', message: 'late failure' }]));
    await expect(start()).rejects.toMatchObject({ code: 'ANALYSIS_FAILED' });
  });

  it('ignores duplicate successful terminal events without duplicating updates', async () => {
    const update = vi.fn();
    mockStream(frames([compileEvent(), finalEvent(), finalEvent()]));
    expect(await start(update)).toEqual(routineFixture());
    expect(update).not.toHaveBeenCalled();
  });

  it('rejects a recommendation attached to the wrong routine step', async () => {
    mockStream(frames([{
      type: 'multiagent_node_stop', node_id: 'products_Cleanser',
      node_result: { status: 'completed', result: {
        structured_output: { step_name: 'Sunscreen', top_recommendations: [] },
      } },
    }]));
    await expect(start()).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
  });
});

describe('authentication and cancellation', () => {
  it('requires authentication before starting a request', async () => {
    const { fetch } = mockStream('');
    vi.mocked(getIdToken).mockResolvedValue(null);
    await expect(start()).rejects.toMatchObject({ code: 'AUTH_REQUIRED' });
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each([
    [400, 'INVALID_INPUT'], [401, 'AUTH_REQUIRED'], [403, 'ACCESS_DENIED'],
    [413, 'REQUEST_TOO_LARGE'], [429, 'RATE_LIMITED'], [500, 'SERVICE_UNAVAILABLE'], [504, 'TIMEOUT'],
  ])('classifies HTTP %s before reading the body', async (status, code) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status }));
    await expect(start()).rejects.toMatchObject({ code, requestId: 'test-job' });
  });

  it('does not fetch when the request was already aborted', async () => {
    const { fetch } = mockStream('');
    const controller = new AbortController();
    controller.abort();
    await expect(start(vi.fn(), controller.signal)).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetch).not.toHaveBeenCalled();
  });

  it('passes cancellation to fetch and rejects stream callbacks after abort', async () => {
    const controller = new AbortController();
    const update = vi.fn(() => controller.abort());
    const { fetch, reader } = mockStream(frames([
      { type: 'multiagent_node_start', node_id: 'skin_analysis' }, compileEvent(), finalEvent(),
    ]));
    await expect(start(update, controller.signal)).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetch.mock.calls[0][1].signal).toBe(controller.signal);
    expect(update).toHaveBeenCalledOnce();
    expect(reader.releaseLock).toHaveBeenCalledOnce();
  });
});

describe('safe, differentiated analysis errors', () => {
  it.each(Object.keys(analysisErrors))('preserves %s without displaying raw backend text', async code => {
    mockStream(frames([{ type: 'error', code, message: 'Internal ARN and private text', request_id: 'server-reference' }]));
    const request = start();
    await expect(request).rejects.toMatchObject({ code, requestId: 'server-reference' });
    await expect(request).rejects.not.toThrow('Internal ARN');
  });

  it('safely handles an unknown code or unsafe reference from a legacy backend', async () => {
    mockStream(frames([{ type: 'error', code: 'toString', message: 'secret', request_id: '<script>' }]));
    await expect(start()).rejects.toMatchObject({ code: 'ANALYSIS_FAILED', requestId: 'test-job' });
  });

  it('distinguishes connection failures from malformed responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(start()).rejects.toMatchObject({ code: 'NETWORK_ERROR' });
    const { reader } = mockStream('');
    reader.read.mockRejectedValueOnce(new TypeError('Connection lost'));
    await expect(start()).rejects.toMatchObject({ code: 'NETWORK_ERROR' });
    expect(reader.releaseLock).toHaveBeenCalledOnce();
  });
});
