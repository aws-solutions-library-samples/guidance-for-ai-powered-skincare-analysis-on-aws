# Dependency review — 2026-10-27

This records the selected fixes and their limits. Version matches are not proof
that a published exploit is reachable in this application. Passing local tests
also does not establish that the rebuilt container works on AWS.

## Selected updates

| Package | Previous → selected | Evidence and application relevance |
| --- | --- | --- |
| `bedrock-agentcore` | 1.4.0 → 1.18.1 | Fixes [GHSA-6rfw-mq36-jm8h](https://github.com/advisories/GHSA-6rfw-mq36-jm8h) and [GHSA-j6g5-3hh3-pgw8](https://github.com/advisories/GHSA-j6g5-3hh3-pgw8). Both concern Code Interpreter package installation; this application does not call that API. |
| `boto3` | 1.43.14 → 1.43.31 | The selected AgentCore SDK requires boto3/botocore ≥1.43.31; this is a compatibility update. |
| `strands-agents` | 1.28.0 → 1.43.0 | Fixes [GHSA-4v6f-7vjh-6x4m](https://github.com/advisories/GHSA-4v6f-7vjh-6x4m), an A2A server session-isolation issue. This app uses Strands graphs, not its A2A server. |
| `pytest` | 9.0.2 → 9.0.3 | Fixes [GHSA-6w46-j5rx-g56g](https://github.com/advisories/GHSA-6w46-j5rx-g56g). Development dependency; excluded from the runtime image. |
| `requests` | 2.32.5 → 2.33.0 | Fixes [GHSA-gc5v-m9x4-r6x2](https://github.com/advisories/GHSA-gc5v-m9x4-r6x2). The affected archive-path helper is not called by application code. |
| `postcss-selector-parser` | 6.1.4 → 6.1.5 | Fixes [GHSA-rj75-hqrm-r3gf](https://github.com/advisories/GHSA-rj75-hqrm-r3gf) in the frontend development/build tree. |
| `certifi` | 2026.10.18 → 2026.10.19 | The [updated advisory](https://github.com/advisories/GHSA-6q48-6c7w-9gw2) identifies 2026.10.18 as already removing the compromised root; some scanner data still reports it vulnerable. Select the maintainer-recommended 2026.10.19, which restores unaffected roots while excluding the compromised root. |

The Python lock update also resolves the required `s3transfer` version. No broad
unconstrained upgrade or npm force-fix is used. The original review's `braces`
finding is not reproduced by the current npm audit; retain the original record
as historical evidence instead of describing it as a current confirmed finding.

## Outstanding OpenTelemetry advisory

[GHSA-xcq7-p3pf-p88h](https://github.com/advisories/GHSA-xcq7-p3pf-p88h)
affects `opentelemetry-api` through 1.45.0. The first fixed version is 1.45.1.
Its W3C `tracestate` parser can perform quadratic work on a malformed header.
The installed parser contains the affected expression and has no preceding
header-length check.

The runtime's `aws-opentelemetry-distro==0.10.1` pins
`opentelemetry-api==1.33.1`. As checked on the review date, even
`aws-opentelemetry-distro==0.21.0` pins `opentelemetry-api==1.44.0`, which remains
in the advisory's affected range. See the publisher metadata for
[0.10.1](https://pypi.org/pypi/aws-opentelemetry-distro/0.10.1/json),
[0.21.0](https://pypi.org/pypi/aws-opentelemetry-distro/0.21.0/json), and
[OpenTelemetry 1.45.1](https://pypi.org/pypi/opentelemetry-api/1.45.1/json).

Forcing just the API package to 1.45.1 would violate AWS distro requirements.
Disabling propagation or replacing the telemetry distribution could affect
tracing. Neither change is made silently.

Existing application boundaries reduce exposure:

- CloudFront forwards an explicit header allowlist that excludes viewer
  `traceparent` and `tracestate`.
- The Lambda handler constructs a fresh runtime invocation and does not copy
  incoming trace headers; a regression test checks that behavior.
- The configured runtime resource policy restricts invocation to the proxy role.

These are source-level findings, not proof that every deployed tracing path is
safe. SDK/platform-generated tracing and direct runtime access need deployed
verification. **This advisory remains open, with no accepted exception.** Before
release, use a compatible patched AWS telemetry distribution when available, or
complete an explicitly reviewed mitigation with tracing and ingress tests.

## Verification and remaining evidence

Validate all Python groups, including `runtime`, because a default development
environment can omit AWS telemetry. Run Python graph/guardrail/HTTP integration
tests, frontend tests and build, proxy tests and packaging, dependency consistency
checks, and fresh Python/npm audits. Preserve raw reports, including remaining
findings; do not globally suppress the telemetry advisory.

Then rebuild and scan the actual ARM64 image and run the
[release validation checks](release-validation.md) against the same candidate.
Check telemetry startup, complete normal-photo streaming, typed guardrail
failures, and direct runtime denial. Until that happens these updates are
locally verified candidates, not closed production findings.
