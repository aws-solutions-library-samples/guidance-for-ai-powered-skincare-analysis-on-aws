import { randomUUID } from 'node:crypto';
import { pipeline } from 'node:stream/promises';
import { PublicError, errorEvent, publicError } from './errors.mjs';
import { validatePreferences, validateLookup } from './preferences.mjs';
import { emitMetrics } from './metrics.mjs';

const MAX_IMAGE_BYTES = 1024 * 1024;
const MAX_ENCODED_IMAGE = 4 * Math.ceil(MAX_IMAGE_BYTES / 3);
const MAX_BODY_BYTES = 3 * MAX_ENCODED_IMAGE + 16384;
const JOB_ID = /^[A-Za-z0-9_-]{1,128}$/;
const DEFINITE_REJECTIONS = new Set([
  'AccessDeniedException', 'ValidationException', 'ResourceNotFoundException',
  'ThrottlingException', 'ServiceQuotaExceededException',
]);

function parsePayload(event) {
  if (typeof event.body !== 'string') throw new PublicError('INVALID_INPUT');
  if (Buffer.byteLength(event.body) > (event.isBase64Encoded ? 4 * Math.ceil(MAX_BODY_BYTES / 3) : MAX_BODY_BYTES)) {
    throw new PublicError('REQUEST_TOO_LARGE');
  }
  const body = event.isBase64Encoded ? Buffer.from(event.body, 'base64').toString('utf8') : event.body;
  if (Buffer.byteLength(body) > MAX_BODY_BYTES) throw new PublicError('REQUEST_TOO_LARGE');
  let value;
  try { value = JSON.parse(body); } catch { throw new PublicError('INVALID_INPUT'); }
  if (!value || Array.isArray(value) || typeof value !== 'object'
      || Object.keys(value).some(key => !(value.api_version === 2
        ? ['job_id', 'images', 'api_version', 'preferences'] : ['job_id', 'images']).includes(key))
      || typeof value.job_id !== 'string' || !JOB_ID.test(value.job_id)
      || !Array.isArray(value.images) || !value.images.length) throw new PublicError('INVALID_INPUT');
  if (value.images.length > 3) throw new PublicError('REQUEST_TOO_LARGE');
  const envelopeBytes = Buffer.byteLength(body) - value.images.reduce(
    (size, image) => size + (typeof image === 'string' ? Buffer.byteLength(JSON.stringify(image)) : 0), 0,
  );
  if (envelopeBytes > (value.api_version === 2 ? 16384 : 4096)) throw new PublicError('REQUEST_TOO_LARGE');
  for (const image of value.images) {
    if (typeof image !== 'string' || !image.length) throw new PublicError('INVALID_INPUT');
    if (image.length > MAX_ENCODED_IMAGE) throw new PublicError('REQUEST_TOO_LARGE');
    if (image.length % 4 || !/^[A-Za-z0-9+/]+={0,2}$/.test(image)) throw new PublicError('INVALID_INPUT');
    if (Buffer.byteLength(image, 'base64') > MAX_IMAGE_BYTES) throw new PublicError('REQUEST_TOO_LARGE');
  }
  if (value.api_version === 2) value.preferences = validatePreferences(value.preferences);
  return value;
}

export function verifiedIdentity(event, config) {
  // These claims come from API Gateway's Cognito verifier, never from a decoded
  // client header/body. Lambda's resource policy restricts invocation to this API.
  const claims = event.requestContext?.authorizer?.claims;
  if (event.requestContext?.apiId !== config.apiId
      || event.httpMethod !== 'POST' || !['/analyze', '/ingredients/lookup'].includes(event.resource)
      || claims?.iss !== config.issuer || claims?.aud !== config.clientId
      || claims?.token_use !== 'id'
      || typeof claims?.sub !== 'string'
      || !/^[A-Za-z0-9_-]{1,128}$/.test(claims.sub)) throw new PublicError('AUTH_REQUIRED');
  return `${claims.iss}\0${claims.sub}`;
}

export function createHandler({ invoke, limits, lookup, lookupLimits, wrapResponse, config, uuid = randomUUID, log = console.error }) {
  return async (event, rawStream, context) => {
    let requestId = uuid();
    let stream;
    let lease;
    let leaseManager = limits;
    let started = false;
    let completed = false;
    let stage = 'validate';
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(),
      Math.max(1, context.getRemainingTimeInMillis() - 5000));
    timer.unref();
    try {
      const identity = verifiedIdentity(event, config);
      if (event.resource === '/ingredients/lookup') {
        stage = 'lookup';
        if (!lookup || !lookupLimits || typeof event.body !== 'string' || Buffer.byteLength(event.body) > 16384) {
          throw new PublicError('INVALID_PREFERENCES');
        }
        let payload;
        try {
          payload = validateLookup(JSON.parse(event.isBase64Encoded
            ? Buffer.from(event.body, 'base64').toString('utf8') : event.body));
        } catch { throw new PublicError('INVALID_PREFERENCES'); }
        leaseManager = lookupLimits;
        lease = await leaseManager.acquire(`${identity}\0ingredient-lookup`, uuid());
        const result = await lookup(payload, controller.signal);
        stream = wrapResponse(rawStream, {
          statusCode: 200, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
        });
        stream.end(JSON.stringify(result));
        return;
      }
      const payload = parsePayload(event);
      emitMetrics('routine_offered', { RoutinesOffered: 1 });
      requestId = payload.job_id;
      const sessionId = uuid();
      stage = 'limits';
      lease = await limits.acquire(identity, sessionId);
      emitMetrics('routine_admitted', { RoutinesAdmitted: 1 });
      started = true;
      stage = 'runtime';
      const response = await invoke({
        agentRuntimeArn: config.runtimeArn, qualifier: 'DEFAULT',
        // A client cannot select/reuse another user's runtime session.
        runtimeSessionId: sessionId, contentType: 'application/json',
        accept: 'text/event-stream', payload: Buffer.from(JSON.stringify(payload)),
      }, controller.signal);
      if (!response.response || !response.contentType?.toLowerCase().startsWith('text/event-stream')) {
        throw new PublicError('SERVICE_UNAVAILABLE');
      }
      stream = wrapResponse(rawStream, {
        statusCode: 200,
        headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store' },
      });
      stage = 'stream';
      await pipeline(response.response, stream);
      completed = true;
      emitMetrics('routine_transport_completed', { RoutineStreamsCompleted: 1 });
    } catch (error) {
      if (DEFINITE_REJECTIONS.has(error?.name)) completed = true;
      const failure = publicError(error, controller.signal.aborted);
      if (event.resource === '/analyze') {
        emitMetrics('routine_proxy_failure', { RoutineProxyFailures: 1, RoutineAdmissionRejections: started ? 0 : 1 });
      }
      log(JSON.stringify({
        request_id: requestId, code: failure.code, stage,
        provider_error: /^[A-Za-z0-9_]{1,80}$/.test(error?.name ?? '') ? error.name : undefined,
        provider_request_id: /^[A-Za-z0-9-]{1,128}$/.test(error?.$metadata?.requestId ?? '')
          ? error.$metadata.requestId : undefined,
      }));
      if (!stream) {
        stream = wrapResponse(rawStream, {
          statusCode: failure.status,
          headers: {
            'Content-Type': 'application/json', 'Cache-Control': 'no-store',
            ...(failure.retryAfter ? { 'Retry-After': String(failure.retryAfter) } : {}),
          },
        });
        stream.end(JSON.stringify(errorEvent(failure, requestId)));
      } else if (!stream.destroyed && !stream.writableEnded) {
        stream.end(`data: ${JSON.stringify(errorEvent(failure, requestId))}\n\n`);
      }
    } finally {
      clearTimeout(timer);
      // A lost connection does not prove the runtime stopped. Keep its lease
      // until expiry after an ambiguous invocation/stream failure.
      if (lease && (!started || completed)) {
        try { await leaseManager.release(lease); }
        catch { log(JSON.stringify({ request_id: requestId, code: 'LIMIT_LEASE_RELEASE_FAILED' })); }
      }
    }
  };
}
