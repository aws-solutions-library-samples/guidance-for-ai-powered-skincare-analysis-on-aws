import test from 'node:test';
import assert from 'node:assert/strict';
import { Readable, Writable } from 'node:stream';
import { createHandler } from '../handler.mjs';
import { PublicError } from '../errors.mjs';

const config = { apiId: 'api-test', issuer: 'https://issuer.invalid/pool', clientId: 'client-test', runtimeArn: 'arn:test:runtime' };
function event() {
  return {
    httpMethod: 'POST', resource: '/analyze',
    requestContext: { apiId: config.apiId, authorizer: { claims: {
      iss: config.issuer, aud: config.clientId, token_use: 'id', sub: 'user-one',
    } } },
    headers: { Authorization: 'Bearer secret-not-forwarded', 'x-user-id': 'attacker' },
    body: JSON.stringify({ job_id: 'browser-job', images: ['aGVsbG8='] }),
  };
}
async function run(input = event(), overrides = {}) {
  const calls = { invoke: [], acquire: [], release: [], logs: [] };
  const chunks = [];
  let metadata;
  let sequence = 0;
  const response = new Writable({ write(chunk, encoding, next) { chunks.push(Buffer.from(chunk)); next(); } });
  const handler = createHandler({
    config, uuid: () => `00000000-0000-4000-8000-${String(++sequence).padStart(12, '0')}`,
    limits: {
      acquire: async (...args) => { calls.acquire.push(args); return { key: 'lease', owner: args[1] }; },
      release: async lease => { calls.release.push(lease); },
    },
    invoke: async (request, signal) => {
      calls.invoke.push(request);
      return { contentType: 'text/event-stream', response: Readable.from(['data: {"ok":true}\n\n']) };
    },
    wrapResponse: (stream, value) => { metadata = value; return stream; },
    log: value => calls.logs.push(value),
    ...overrides,
  });
  await handler(input, response, { getRemainingTimeInMillis: () => 60000 });
  return { calls, metadata, body: Buffer.concat(chunks).toString(), response };
}

test('streams through the real handler using verified identity and a server-owned session', async () => {
  const { calls, metadata, body } = await run();
  assert.equal(metadata.statusCode, 200);
  assert.equal(body, 'data: {"ok":true}\n\n');
  assert.equal(calls.acquire[0][0], `${config.issuer}\0user-one`);
  const request = calls.invoke[0];
  assert.equal(request.agentRuntimeArn, config.runtimeArn);
  assert.equal(request.qualifier, 'DEFAULT');
  assert.notEqual(request.runtimeSessionId, 'browser-job');
  assert.equal(request.runtimeSessionId, calls.acquire[0][1]);
  assert.deepEqual(JSON.parse(request.payload.toString()), JSON.parse(event().body));
  assert.ok(!JSON.stringify(request).includes('secret-not-forwarded'));
  assert.equal(calls.release.length, 1);
});

for (const [name, change] of [
  ['missing verifier', e => { delete e.requestContext.authorizer; }],
  ['wrong client', e => { e.requestContext.authorizer.claims.aud = 'other-client'; }],
  ['wrong issuer', e => { e.requestContext.authorizer.claims.iss = 'other-pool'; }],
  ['access token', e => { e.requestContext.authorizer.claims.token_use = 'access'; }],
  ['missing subject', e => { delete e.requestContext.authorizer.claims.sub; }],
  ['wrong API', e => { e.requestContext.apiId = 'other-api'; }],
  ['wrong route', e => { e.resource = '/other'; }],
]) {
  test(`${name} is denied before quota or model access`, async () => {
    const input = event(); change(input);
    const result = await run(input);
    assert.equal(result.metadata.statusCode, 401);
    assert.equal(JSON.parse(result.body).code, 'AUTH_REQUIRED');
    assert.equal(result.calls.acquire.length + result.calls.invoke.length, 0);
  });
}

for (const [name, payload, code] of [
  ['missing photos', { job_id: 'safe', images: [] }, 'INVALID_INPUT'],
  ['forged principal in body', { job_id: 'safe', images: ['aGVsbG8='], user_id: 'other' }, 'INVALID_INPUT'],
  ['client-selected session', { job_id: 'safe', images: ['aGVsbG8='], runtimeSessionId: 'other' }, 'INVALID_INPUT'],
  ['unsafe reference', { job_id: 'secret\nline', images: ['aGVsbG8='] }, 'INVALID_INPUT'],
  ['invalid base64', { job_id: 'safe', images: ['????'] }, 'INVALID_INPUT'],
  ['four photos', { job_id: 'safe', images: Array(4).fill('aGVsbG8=') }, 'REQUEST_TOO_LARGE'],
  ['oversized photo', { job_id: 'safe', images: [Buffer.alloc(1024 * 1024 + 1).toString('base64')] }, 'REQUEST_TOO_LARGE'],
]) {
  test(`${name} is rejected before acquiring a lease`, async () => {
    const input = event(); input.body = JSON.stringify(payload);
    const result = await run(input);
    assert.equal(JSON.parse(result.body).code, code);
    assert.equal(result.calls.acquire.length + result.calls.invoke.length, 0);
  });
}

test('decodes API Gateway base64 bodies while preserving the same request contract', async () => {
  const input = event(); input.body = Buffer.from(input.body).toString('base64'); input.isBase64Encoded = true;
  assert.equal((await run(input)).metadata.statusCode, 200);
});

for (const code of ['USER_RATE_LIMITED', 'ANALYSIS_IN_PROGRESS']) {
  test(`${code} has a distinct public 429 code and no model invocation`, async () => {
    const result = await run(event(), { limits: {
      acquire: async () => { throw new PublicError(code, 120); },
      release: async () => assert.fail('No acquired lease'),
    } });
    assert.equal(result.metadata.statusCode, 429);
    assert.equal(result.metadata.headers['Retry-After'], '120');
    assert.equal(JSON.parse(result.body).code, code);
    assert.equal(result.calls.invoke.length, 0);
  });
}

test('quota-store failure fails closed without leaking provider details', async () => {
  const result = await run(event(), { limits: {
    acquire: async () => { throw new Error('SECRET internal database details'); },
  } });
  assert.equal(result.metadata.statusCode, 503);
  assert.equal(result.calls.invoke.length, 0);
  assert.ok(!result.body.includes('SECRET') && !result.calls.logs.join().includes('SECRET'));
});

test('a definite runtime rejection releases the lease and masks provider text', async () => {
  const result = await run(event(), { invoke: async () => {
    throw Object.assign(new Error('SECRET role ARN'), { name: 'AccessDeniedException' });
  } });
  assert.equal(result.metadata.statusCode, 503);
  assert.equal(result.calls.release.length, 1);
  assert.ok(!result.body.includes('SECRET'));
});

test('an ambiguous transport failure retains the lease because work may still run', async () => {
  const result = await run(event(), { invoke: async () => { throw new Error('connection lost'); } });
  assert.equal(result.metadata.statusCode, 503);
  assert.equal(result.calls.release.length, 0);
});

test('a mid-stream failure retains the lease', async () => {
  const result = await run(event(), { invoke: async () => ({
    contentType: 'text/event-stream',
    response: Readable.from((async function* () { yield 'data: {}\n\n'; throw new Error('upstream lost'); })()),
  }) });
  assert.equal(result.calls.release.length, 0);
  assert.ok(!result.body.includes('upstream lost'));
});

test('an application-level SSE failure finishes normally and releases the lease', async () => {
  const result = await run(event(), { invoke: async () => ({
    contentType: 'text/event-stream', response: Readable.from(['data: {"type":"error","code":"INVALID_INPUT"}\n\n']),
  }) });
  assert.equal(result.calls.release.length, 1);
  assert.equal(JSON.parse(result.body.slice(6)).code, 'INVALID_INPUT');
});

test('v2 constraints survive the verified proxy without client-controlled search context', async () => {
  const input = event();
  input.body = JSON.stringify({ ...JSON.parse(input.body), api_version: 2, preferences: {
    excluded_ingredient_ids: ['b'], must_have_by_category: [{ category_id: 'Serum', ingredient_ids: ['c'] }],
  } });
  const result = await run(input);
  const forwarded = JSON.parse(result.calls.invoke[0].payload);
  assert.equal(forwarded.api_version, 2);
  assert.deepEqual(forwarded.preferences.must_have_by_category, [{ category_id: 'Serum', ingredient_ids: ['c'] }]);
  const invalid = event();
  invalid.body = JSON.stringify({ ...JSON.parse(input.body), preferences: { index_generation: 'attacker' } });
  const denied = await run(invalid);
  assert.equal(JSON.parse(denied.body).code, 'INVALID_PREFERENCES');
  assert.equal(denied.calls.acquire.length + denied.calls.invoke.length, 0);
});

test('ingredient lookup uses verified identity and its own quota without invoking the model', async () => {
  const input = event(); input.resource = '/ingredients/lookup'; input.body = '{}';
  const acquired = [], released = [];
  const result = await run(input, {
    lookup: async () => ({ categories: ['Cleanser', 'Serum'] }),
    lookupLimits: {
      acquire: async identity => { acquired.push(identity); return 'lookup-lease'; },
      release: async lease => released.push(lease),
    },
  });
  assert.equal(result.metadata.headers['Content-Type'], 'application/json');
  assert.deepEqual(acquired, [`${config.issuer}\0user-one\0ingredient-lookup`]);
  assert.deepEqual(released, ['lookup-lease']);
  assert.equal(result.calls.invoke.length + result.calls.acquire.length, 0);
});

test('v1 keeps its smaller envelope budget while v2 allows bounded preference metadata', async () => {
  const legacy = event(); legacy.body = `${' '.repeat(5000)}${legacy.body}`;
  assert.equal(JSON.parse((await run(legacy)).body).code, 'REQUEST_TOO_LARGE');
  const v2 = event(); v2.body = `${' '.repeat(5000)}${JSON.stringify({ ...JSON.parse(v2.body), api_version: 2 })}`;
  assert.equal((await run(v2)).metadata.statusCode, 200);
});
