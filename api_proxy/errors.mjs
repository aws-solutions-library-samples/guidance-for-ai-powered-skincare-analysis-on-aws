const definitions = {
  AUTH_REQUIRED: [401, 'Please sign in again.'],
  INVALID_INPUT: [400, 'Please upload valid photos and try again.'],
  INVALID_PREFERENCES: [400, 'Check the selected ingredient preferences and try again.'],
  REQUEST_TOO_LARGE: [413, 'Use up to three images, each no larger than 1 MiB and 2048 pixels per side.'],
  USER_RATE_LIMITED: [429, 'You have reached the analysis limit for your account. Please try again later.'],
  ANALYSIS_IN_PROGRESS: [429, 'An analysis is already running for your account. Wait for it to finish before starting another.'],
  RATE_LIMITED: [429, 'The analysis service is busy. Please try again later.'],
  TIMEOUT: [504, 'The analysis took too long. Please try again later.'],
  SERVICE_UNAVAILABLE: [503, 'The analysis service is temporarily unavailable. Please try again later.'],
};

export class PublicError extends Error {
  constructor(code, retryAfter) {
    const [status, message] = definitions[code] ?? definitions.SERVICE_UNAVAILABLE;
    super(message);
    this.code = Object.hasOwn(definitions, code) ? code : 'SERVICE_UNAVAILABLE';
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

export function publicError(error, timedOut = false) {
  if (error instanceof PublicError) return error;
  if (timedOut) return new PublicError('TIMEOUT');
  if (error?.name === 'ThrottlingException') return new PublicError('RATE_LIMITED');
  return new PublicError('SERVICE_UNAVAILABLE');
}

export function errorEvent(error, requestId) {
  return {
    type: 'error', code: error.code, message: error.message,
    request_id: requestId,
    retryable: !['AUTH_REQUIRED', 'INVALID_INPUT', 'INVALID_PREFERENCES', 'REQUEST_TOO_LARGE'].includes(error.code),
    ...(Number.isInteger(error.retryAfter) ? { retry_after_seconds: error.retryAfter } : {}),
  };
}
