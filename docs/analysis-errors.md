# Analysis errors

An application failure in an open analysis stream is an SSE event, even when the
HTTP status is `200`. Clients must inspect the event before accepting completion:

```json
{
  "type": "error",
  "code": "GUARDRAIL_PROMPT_ATTACK",
  "message": "The safety check blocked content that may contain instructions to bypass the analysis. Please try different photos. If this seems incorrect, share the reference below with support.",
  "retryable": false,
  "request_id": "the-job-id-sent-by-the-browser"
}
```

The UI shows a friendly message, stable code and request reference. It uses
allowlisted copy rather than raw server messages. The reference correlates with
`Job <request_id>` and `error_code=<code>` in backend logs.

| Code | Meaning / recovery |
| --- | --- |
| `GUARDRAIL_PROMPT_ATTACK` | AWS reported a blocked prompt attack. Try different photos or contact support if unexpected. |
| `GUARDRAIL_SENSITIVE_DATA` | AWS blocked personal or sensitive information. Remove personal details. |
| `GUARDRAIL_TOPIC` | AWS blocked a denied topic, such as medical diagnosis. |
| `GUARDRAIL_CONTENT` | AWS blocked a content category. |
| `GUARDRAIL_BLOCKED` | An intervention was reported without a specific blocked category. |
| `INVALID_INPUT` | Invalid request or unsupported image. Replace the photos. |
| `INVALID_PREFERENCES` | Invalid, unknown or conflicting constraints, or a mandatory category omitted by the plan. Review the preferences. |
| `NO_MATCHING_PRODUCTS` | Legacy v1 terminal domain outcome. V2 instead completes each step with its explicit matched/no-match status. |
| `AUTH_REQUIRED` | No session, expired session, or HTTP 401. Sign in again. |
| `ACCESS_DENIED` | HTTP 403. Contact support; this is not assumed to be a guardrail block. |
| `REQUEST_TOO_LARGE` | HTTP 413 or backend image/count/dimension limits. Use up to three images, each at most 1 MiB and 2048 pixels per side. |
| `RATE_LIMITED` | HTTP 429 or provider throttling. Wait before retrying. |
| `TIMEOUT` | Provider/request timeout or HTTP 408/504. Retry. |
| `SERVICE_UNAVAILABLE` | Provider, backend access/configuration, or HTTP 5xx failure. Retry later. |
| `NETWORK_ERROR` | Fetch or stream connection failed. Check connectivity. |
| `INVALID_RESPONSE` | Malformed/incomplete stream, model output, or missing compiled routine. Retry. |
| `ANALYSIS_FAILED` | Unexpected or legacy untyped failure. Retry and report the reference if repeated. |

`retryable` means that an unchanged request may succeed later. The application
does not retry automatically. User cancellation remains a cancellation and does
not display an error.

Both model factories use `GUARDRAIL_ID` and `GUARDRAIL_VERSION`. AgentCore requires
both; local development can omit both. Streaming uses synchronous guardrail
processing. The model adapter reads the final trace before raising a typed
failure, so Strands structured-output validation cannot obscure a guardrail
block. The public stream excludes raw model deltas, guardrail traces and failed
node exception strings.

AGE is intentionally absent from the PII blocking policy. Prompt attack filtering
remains HIGH on input. Guardrails also retain the other configured content, PII
and topic policies. Detection is not a guarantee that every attack will be caught.
Bedrock Converse does not assess tool results, tool definitions or structured
tool-use inputs; the application's tools and deterministic output validation
remain separate controls.

## Verification

Run `.venv/bin/pytest -q`, then `npm test`, `npm run typecheck`, and
`npm run build` in `frontend/`. The integration tests use the pinned Bedrock,
Strands graph and AgentCore HTTP adapters with mocked AWS responses. They cover
each blocking category on input/output, allowed content, safe error serialization
and provider error classification. Frontend tests cover HTTP/SSE/network
distinctions, cancellation, visible error codes and sign-in recovery.

For live policy isolation without repeating browser uploads, see
[CLI guardrail diagnostics](guardrail-diagnostics.md). A guardrail block identifies
the policy decision; it does not prove that the user's photos were malicious.

Official references:

- [Bedrock guardrails with Converse](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-converse-api.html)
- [Strands Bedrock provider](https://strandsagents.com/latest/documentation/docs/user-guide/concepts/model-providers/amazon-bedrock/)
- [Terraform resource lifecycle](https://developer.hashicorp.com/terraform/language/meta-arguments/lifecycle)
- [AWS provider guardrail versions](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrock_guardrail_version)
