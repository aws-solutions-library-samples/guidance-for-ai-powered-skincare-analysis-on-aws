"""Public analysis errors. Provider details belong in logs, never in SSE."""

from botocore.exceptions import (
    ClientError, ConnectionClosedError, ConnectTimeoutError, EndpointConnectionError,
    ReadTimeoutError,
)
from strands.types.exceptions import ModelThrottledException, StructuredOutputException


# Keep the public codes stable; the browser owns the localized presentation.
ERRORS = {
    "GUARDRAIL_PROMPT_ATTACK": ("The safety check blocked content that may contain instructions to bypass the analysis. Please try different photos. If this seems incorrect, share the reference below with support.", False),
    "GUARDRAIL_SENSITIVE_DATA": ("The safety check blocked personal or sensitive information. Please use photos without personal details.", False),
    "GUARDRAIL_TOPIC": ("The safety check blocked content outside skincare guidance, such as medical diagnosis. If this seems incorrect, share the reference below with support.", False),
    "GUARDRAIL_CONTENT": ("The safety check blocked content that is not allowed. Please try different photos. If this seems incorrect, share the reference below with support.", False),
    "GUARDRAIL_BLOCKED": ("A safety check blocked this analysis. If this seems incorrect, share the reference below with support.", False),
    "INVALID_INPUT": ("We could not read these photos. Please upload valid JPEG, PNG, GIF, or WebP images and try again.", False),
    "REQUEST_TOO_LARGE": ("These photos exceed the analysis limits. Use up to three images, each no larger than 1 MiB and 2048 pixels per side.", False),
    "RATE_LIMITED": ("The analysis service is busy. Please wait a minute and try again.", True),
    "TIMEOUT": ("The analysis took too long. Please try again.", True),
    "SERVICE_UNAVAILABLE": ("The analysis service is temporarily unavailable. Please try again later.", True),
    "INVALID_RESPONSE": ("We could not produce a complete routine. Please try again.", True),
    "ANALYSIS_FAILED": ("The analysis could not complete. Please try again. If it happens again, share the reference below with support.", True),
}


class AnalysisFailure(Exception):
    def __init__(self, code: str):
        self.code = code if code in ERRORS else "ANALYSIS_FAILED"
        super().__init__(ERRORS[self.code][0])


def classify_error(exc: Exception) -> AnalysisFailure:
    """Use exception types/provider codes, including SDK wrappers, not message matching."""
    chain = []
    current = exc
    while isinstance(current, Exception) and all(current is not item for item in chain):
        chain.append(current)
        if isinstance(current, AnalysisFailure):
            return current
        current = getattr(current, "original_exception", None) or current.__cause__ or current.__context__
    for error in chain:
        if isinstance(error, ModelThrottledException):
            return AnalysisFailure("RATE_LIMITED")
        if isinstance(error, (TimeoutError, ReadTimeoutError, ConnectTimeoutError)):
            return AnalysisFailure("TIMEOUT")
        if isinstance(error, (EndpointConnectionError, ConnectionClosedError)):
            return AnalysisFailure("SERVICE_UNAVAILABLE")
        if isinstance(error, ClientError):
            code = error.response.get("Error", {}).get("Code", "")
            if code in {"ThrottlingException", "throttlingException", "TooManyRequestsException", "ProvisionedThroughputExceededException", "RequestLimitExceeded"}:
                return AnalysisFailure("RATE_LIMITED")
            if code in {"ModelTimeoutException", "RequestTimeout", "RequestTimeoutException"}:
                return AnalysisFailure("TIMEOUT")
            # Backend credentials/model access errors are not the user's sign-in error.
            return AnalysisFailure("SERVICE_UNAVAILABLE")
        if isinstance(error, (ValueError, StructuredOutputException)):
            return AnalysisFailure("INVALID_RESPONSE")
    return AnalysisFailure("ANALYSIS_FAILED")


def error_event(exc: Exception, request_id: str) -> dict:
    failure = classify_error(exc)
    message, retryable = ERRORS[failure.code]
    return {
        "type": "error", "code": failure.code, "message": message,
        "retryable": retryable, "request_id": request_id,
    }


def guardrail_failure(trace: dict) -> AnalysisFailure | None:
    """Read only actions/types from Bedrock trace; never return matched text."""
    codes = set()

    def inspect(value, policy=""):
        if isinstance(value, list):
            for item in value:
                inspect(item, policy)
        elif isinstance(value, dict):
            if value.get("action") == "BLOCKED":
                if policy == "contentPolicy":
                    codes.add("GUARDRAIL_PROMPT_ATTACK" if value.get("type") == "PROMPT_ATTACK" else "GUARDRAIL_CONTENT")
                elif policy == "sensitiveInformationPolicy":
                    codes.add("GUARDRAIL_SENSITIVE_DATA")
                elif policy == "topicPolicy":
                    codes.add("GUARDRAIL_TOPIC")
                else:
                    codes.add("GUARDRAIL_BLOCKED")
            for key, item in value.items():
                inspect(item, key if key.endswith("Policy") else policy)

    inspect(trace)
    for code in ("GUARDRAIL_PROMPT_ATTACK", "GUARDRAIL_SENSITIVE_DATA", "GUARDRAIL_TOPIC", "GUARDRAIL_CONTENT", "GUARDRAIL_BLOCKED"):
        if code in codes:
            return AnalysisFailure(code)
    return None
