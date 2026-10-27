# Release validation

Use a **separate AWS test account** and the `test` environment for release checks.
Mocks establish local contracts; they do not establish that deployed IAM, WAF,
model access, streaming, or browser permissions work. Do not merge on the strength
of local tests alone. The cost section is maintained separately and is not
validated by this runbook.

## 1. Freeze and check the candidate locally

Record the reviewed commit and retain the lockfiles. From the repository root:

```bash
make setup
make test
terraform -chdir=terraform init -backend=false -lockfile=readonly
terraform -chdir=terraform/shared init -backend=false -lockfile=readonly
make validate
npm run build --prefix frontend
npm run build --prefix api_proxy
```

`make validate` checks README section order, local documentation links and
referenced Terraform outputs, Python compilation, Terraform and TypeScript.
It does not check the accuracy of every sentence or reach external URLs.
Review the architecture, setup, request/error flow, catalog behavior and cleanup
against source changes. Preserve the approved architecture export and README
template. Dependency audit results and exception reasoning belong in the release
evidence; see [dependency review](dependency-review.md).

## 2. Deploy the same candidate to AWS

Authenticate the intended test profile and inspect the account before deployment:

```bash
export AWS_PROFILE=your-test-profile
export AWS_REGION=us-east-1
aws sts get-caller-identity
make deploy ENV=test
```

This creates billable resources. The deploy script applies Terraform without a
second approval prompt. It reuses existing account-level API Gateway logging;
when none is configured it creates shared logging resources. Verify an existing
role permits this API's log groups, and preserve other applications' configuration.
A dedicated test account remains preferable to a shared customer account.
Review optional `terraform/terraform.tfvars` values first: environment defaults
are loaded first, local overrides second, and the selected environment/region
last. See [Terraform variable precedence](https://developer.hashicorp.com/terraform/language/values/variables).

Retain the commit, Terraform plan/apply logs, source hash, image digest, CodeBuild
result, proxy code hash, frontend asset hashes, runtime version and guardrail
version. A successful apply is not a functional test. The live checker compares
the deployed runtime's image URI with the source-hash tag in Terraform outputs;
the release owner must also tie that state and the frontend artifact to the
reviewed commit. A manually supplied `--revision` label is not proof of identity.

Build and scan the actual ARM64 container, including its OS packages, before
release. Python/npm audits alone do not cover the base image.

## 3. Run automated checks against the real deployment

Save outputs locally; `output/` is ignored by Git:

```bash
umask 077
mkdir -p output/release-validation
terraform -chdir=terraform output -json > output/release-validation/outputs.json
uv run --locked python -m tests.live_release \
  --outputs output/release-validation/outputs.json \
  --expected-account YOUR_TEST_ACCOUNT_ID \
  --revision "$(git rev-parse HEAD)" \
  --report output/release-validation/controls.json \
  --allow-test-resources
```

The checker refuses a non-`test` environment or an account mismatch. It creates
one unique temporary Cognito user, a second temporary app client for the
wrong-audience test, and that user's temporary DynamoDB limit records. Invitation
messages are suppressed. It removes the user/client and seeded records on normal
completion or an exception, recording cleanup failures. It never edits an existing
user or counter. A killed process or ambiguous AWS timeout can leave test objects:
use the report's run ID (`release-<run-id>`) to identify and remove only those
objects. Real analysis counters expire through the table's TTL.

The test role needs read access to STS, CloudFront, the runtime, Lambda
configuration and the product table; create/authenticate/delete permissions for
test users and clients in this pool; and conditional read/write/delete access to
the limits table. Scope permissions to the test deployment. Do not give these
test-management permissions to end users or to the runtime role.

The automated control checks cover:

| Check | Expected evidence |
| --- | --- |
| Account, environment, CloudFront and runtime | Matching target, `Deployed`, `READY`, matching runtime image tag and proxy configuration |
| Anonymous request | HTTP 401 |
| Anonymous ingredient lookup | HTTP 401 |
| Valid user in the application client | Cognito issues tokens |
| Same user with another app client's ID token | HTTP 401 |
| Access token used instead of ID token | HTTP 401 |
| Empty images, extra fields, excessive image count | Specific safe HTTP error and application code |
| Conflicting API v2 must-have/exclusion preferences | HTTP 400, `INVALID_PREFERENCES`, before model work |
| Free-text search submitted to ingredient lookup | HTTP 400, `INVALID_PREFERENCES` |
| Ingredient configuration, category summary and exact resolution | Bounded summary; exact ID/name resolve to the same identity; absent ID stays unresolved |
| Exhausted hourly counter | HTTP 429, `USER_RATE_LIMITED`, retry delay |
| Existing active lease | HTTP 429, `ANALYSIS_IN_PROGRESS`, no counter increment |
| Direct IAM runtime request with invalid input | `AccessDeniedException`, not a timeout, missing resource or validation error |
| Corrupt image with API v2 preferences through the proxy and runtime (control-only run) | HTTP 200 with exactly one `INVALID_INPUT` SSE event; container startup and transport work without starting model nodes |

The quota tests seed counters for the newly created identity, avoiding five paid
analyses just to exhaust an allowance. They use a syntactically valid but corrupt
image, so a broken admission control still cannot start the normal model workflow.
Repeat with genuinely concurrent requests during the optional real analysis.

**Direct-access interpretation:** test with a non-proxy principal whose identity
policy otherwise allows invocation of this test runtime. Inspect the deployed
resource policy and retain both policies as evidence. A denial for a principal
that already lacks an allow does not prove that the proxy-only resource policy
works. Separately try a valid Cognito token directly against the runtime; this
checker currently automates the IAM probe, not the direct JWT probe.

For the real image workflow, provide a photo approved for sending to this test
deployment, at most 1 MiB and 2048 pixels per side:

```bash
uv run --locked python -m tests.live_release \
  --outputs output/release-validation/outputs.json \
  --expected-account YOUR_TEST_ACCOUNT_ID \
  --revision "$(git rev-parse HEAD)" \
  --report output/release-validation/analysis.json \
  --allow-test-resources \
  --image /absolute/path/to/approved-photo.jpg \
  --allow-model-invocations
```

This starts one billable analysis. It verifies the entire CloudFront → API Gateway
→ Lambda → AgentCore → Bedrock/catalog path, observes the events as they arrive,
checks every planned agent result and final routine, checks product IDs against
the deployed table, and submits a second request while the first is running to
check admission enforcement. For a one-request hourly allowance the second
request is expected to hit the hourly limit instead of the active lease.

Initial test thresholds are first event within 30 seconds, no inter-event gap of
60 seconds or more, and stage completions arriving over at least one second.
These are test criteria, not a measured production SLA. The timing check rejects
a complete result delivered in one burst. Record actual first-event, gap and
total times; investigate failures instead of simply relaxing thresholds.
The report does not store tokens, images, skin profiles or routine text.

A control-only run marks image validation `SKIPPED`. Every report leaves
`release_ready` false because the remaining checks below require separate
evidence. An automated `PASS` applies only to the checks that ran.

## 4. Finish browser and operational checks

| Area | Method and pass criterion |
| --- | --- |
| Fresh user | In the deployed browser, complete the temporary-password challenge; reject reuse and mismatch; confirm sign-out and expired-session recovery. The automated checker sets its test password administratively and does not cover this UI. |
| Camera and uploads | Chrome, Safari and Firefox: permit/deny camera access, capture three photos, upload three files, reject invalid files, complete analysis. Include one supported mobile device. |
| Visible progress | Observe stage updates before completion, parallel step progress, final routine order and usable product cards. Capture timing/video with synthetic or consented data. |
| Cancellation and failure | Cancel during analysis; verify no stale UI updates or cross-user result reuse. Retry, disconnect and refresh; confirm a retained lease does not imply the runtime was cancelled. |
| Content and catalog | Use reviewed normal profiles and negative inputs. Verify names/prices/images against the catalog, safe error codes, no fabricated products, and sensible routine explanations. Existing unit tests cover fabricated IDs; the live checker covers ID existence only. |
| Guardrails | Run approved allow/block fixtures through the actual application; confirm a normal photo completes and an intended block reaches the browser with a safe code/reference. Use [guardrail diagnostics](guardrail-diagnostics.md) to isolate unexpected blocks. |
| Runtime boundary | Direct IAM and valid-JWT probes must fail while the same user's proxied request succeeds. Exercise unused actions under the deployed roles; record the actual denial reasons. |
| WAF, headers and logs | Verify origin bypass and managed-rule behavior, CSP/TLS policy and credential redaction in both WAF log paths. Verify no photos, tokens or raw model content in the selected application/telemetry logs. |
| Telemetry | Confirm a request reference can be followed through the proxy/runtime and that instrumentation starts correctly in the built container. Check the outstanding OpenTelemetry advisory before claiming closure. |
| Cleanup and redeployment | Destroy only the test environment, confirm its resources/data are gone, identify intentionally retained shared/state resources, and deploy again from the same documented instructions. |

Use browser automation for repeatable sign-in, file upload, SSE-driven progress
and error flows. Keep a short human check for real camera permissions, device
behavior and visual quality. Simulated webcam/browser tests complement that
check; they cannot replace it.

## 5. Evaluate capacity separately from functional correctness

The demo defaults to **10 concurrent streaming Lambda invocations**, held for the
duration of each analysis. It is not configured or proven for 20 routines/second.
For illustration, 20 arrivals/second at 60 seconds per routine implies about
1,200 in-flight routines before headroom. The current Terraform variable permits
at most 3,000; increasing it and relevant service quotas requires a capacity review.

Use a budgeted, isolated load test: first a small baseline, then increasing
arrival rates and a steady hold, followed by a recovery test. Use multiple test
identities so the per-user allowance does not mask service capacity. Measure
accepted/completed routines, admission/provider throttling, p50/p95/p99 latency,
first-event delay, maximum streaming gap, memory, model token use and cost.
Agree thresholds before execution. Do not send a 20-routine/second test at a
customer account or infer capacity from a handful of successful requests.

The included catalog has 48 synthetic products. Search uses exact canonical
ingredient IDs, bounded index candidates, and canonical revalidation. Validate
retrieval quality, identity fidelity, latency and memory across 1K, 100K and 1M
products as specified in the [search verification plan](search-spec/verification.md).
Those acceptance targets are not claims about the demo deployment.

## Release decision

Record each requirement as passed, failed, skipped, or explicitly accepted with
an owner and rationale. Keep the tested artifacts and evidence with the release.
Fixes require repeating affected checks. Merge approval remains a separate human
decision after reviewing the candidate and the outstanding exceptions.

Official API references:

- [Cognito AdminCreateUser and suppressed invitations](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_AdminCreateUser.html)
- [Cognito password setup](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_AdminSetUserPassword.html)
- [Cognito InitiateAuth](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_InitiateAuth.html)
- [Cognito app clients](https://docs.aws.amazon.com/cognito-user-identity-pools/latest/APIReference/API_CreateUserPoolClient.html)
- [Requests streaming](https://requests.readthedocs.io/en/latest/user/advanced/#streaming-requests)
- [AgentCore runtime status](https://docs.aws.amazon.com/cli/latest/reference/bedrock-agentcore-control/get-agent-runtime.html)
