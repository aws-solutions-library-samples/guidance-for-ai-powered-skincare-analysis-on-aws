/** Stable public codes. Never display arbitrary provider or server error text. */
export const analysisErrors = {
  GUARDRAIL_PROMPT_ATTACK: { message: 'The safety check blocked content that may contain instructions to bypass the analysis. Please try different photos. If this seems incorrect, share the reference below with support.', retryable: false },
  GUARDRAIL_SENSITIVE_DATA: { message: 'The safety check blocked personal or sensitive information. Please use photos without personal details.', retryable: false },
  GUARDRAIL_TOPIC: { message: 'The safety check blocked content outside skincare guidance, such as medical diagnosis. If this seems incorrect, share the reference below with support.', retryable: false },
  GUARDRAIL_CONTENT: { message: 'The safety check blocked content that is not allowed. Please try different photos. If this seems incorrect, share the reference below with support.', retryable: false },
  GUARDRAIL_BLOCKED: { message: 'A safety check blocked this analysis. If this seems incorrect, share the reference below with support.', retryable: false },
  INVALID_INPUT: { message: 'We could not read these photos. Please upload valid JPEG, PNG, GIF, or WebP images and try again.', retryable: false },
  INVALID_PREFERENCES: { message: 'These preferences could not be applied. Check your selected ingredients, categories, market, and price limit.', retryable: false },
  NO_MATCHING_PRODUCTS: { message: 'No products matched the selected ingredients and constraints. Adjust your preferences or try again.', retryable: false },
  AUTH_REQUIRED: { message: 'Your session has expired or you are not signed in. Please sign in again.', retryable: false },
  ACCESS_DENIED: { message: 'Your account cannot access this analysis. Please contact support with the reference below.', retryable: false },
  REQUEST_TOO_LARGE: { message: 'These photos are too large. Please upload smaller images and try again.', retryable: false },
  RATE_LIMITED: { message: 'The analysis service is busy. Please wait a minute and try again.', retryable: true },
  USER_RATE_LIMITED: { message: 'You have reached the analysis limit for your account. Please try again later.', retryable: true },
  ANALYSIS_IN_PROGRESS: { message: 'An analysis is already running for your account. Wait for it to finish before starting another.', retryable: true },
  TIMEOUT: { message: 'The analysis took too long. Please try again.', retryable: true },
  SERVICE_UNAVAILABLE: { message: 'The analysis service is temporarily unavailable. Please try again later.', retryable: true },
  NETWORK_ERROR: { message: 'The connection was lost. Check your internet connection and try again.', retryable: true },
  INVALID_RESPONSE: { message: 'We could not produce a complete routine. Please try again.', retryable: true },
  ANALYSIS_FAILED: { message: 'The analysis could not complete. Please try again. If it happens again, share the reference below with support.', retryable: true },
} as const;

export type AnalysisErrorCode = keyof typeof analysisErrors;

export class AnalysisError extends Error {
  readonly retryable: boolean;

  constructor(readonly code: AnalysisErrorCode, readonly requestId: string) {
    super(analysisErrors[code].message);
    this.name = 'AnalysisError';
    this.retryable = analysisErrors[code].retryable;
  }
}

export function serverError(event: Record<string, unknown>, jobId: string): AnalysisError {
  const code = typeof event.code === 'string' && Object.prototype.hasOwnProperty.call(analysisErrors, event.code)
    ? event.code as AnalysisErrorCode : 'ANALYSIS_FAILED';
  const requestId = typeof event.request_id === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(event.request_id)
    ? event.request_id : jobId;
  return new AnalysisError(code, requestId);
}

export function httpError(status: number, jobId: string): AnalysisError {
  const code: AnalysisErrorCode = status === 401 ? 'AUTH_REQUIRED'
    : status === 403 ? 'ACCESS_DENIED'
    : status === 413 ? 'REQUEST_TOO_LARGE'
    : status === 429 ? 'RATE_LIMITED'
    : status === 408 || status === 504 ? 'TIMEOUT'
    : status === 400 || status === 422 ? 'INVALID_INPUT'
    : status >= 500 ? 'SERVICE_UNAVAILABLE' : 'ANALYSIS_FAILED';
  return new AnalysisError(code, jobId);
}
