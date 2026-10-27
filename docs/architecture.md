# Architecture

![Previously approved Smart Beauty reference architecture](architecture.png)

[View the reference architecture at full resolution](architecture.png)

This image is the unchanged export of the previously approved reference-architecture
PPTX. Its seven numbered steps cover the original application, including the Lambda
proxy. Private indexed search and the publication pipeline extend that architecture
and are documented below.

The application has authenticated analysis and ingredient-lookup endpoints.
Analysis streams through a Lambda proxy. The reference image does not yet include
the exact-search network or publication paths. Background job polling, PDF services,
translation agents, and federated sign-in are not included.

## Request flow

1. The React app signs in an administrator-created Cognito user and captures or uploads three photos.
2. CloudFront serves the app from S3 and routes `/api/analyze` and `/api/ingredients/lookup` through WAF and API Gateway. Exact ingredient lookup has its own allowance and makes no model call.
3. API Gateway validates the Cognito token. The Lambda streaming proxy checks verified authorizer claims, acquires a per-user allowance and active-analysis lease in DynamoDB, creates a server-owned session ID, and invokes AgentCore with IAM credentials.
4. `agentcore_entrypoint.py` validates the payload and normalizes 1–3 images, each no more than 1 MiB or 2048 pixels per side. The request's `job_id` is a log correlation value, not a stored job.
5. `agents/orchestrator.py` streams the two-phase graph. The entrypoint serializes graph events into the AgentCore SSE transport.
6. The frontend validates incoming data once, updates progress, and displays a typed compiled routine only after successful completion.

## Agent workflow

The diagnose graph runs `skin_analysis` followed by `step_analysis`. Its output is a validated plan with 2–8 unique steps, matching summary counts, supported timing values, and categories present in `data/catalog.yaml`. Skin metrics are constrained to 0–100.

For each planned step, the prescribe graph validates the ingredient agent's canonical IDs, selects products deterministically, and requests an explanation of those approved products. Those chains run concurrently and converge on `CompileNode`. Compilation keeps plan order and makes no additional model request.

Ingredient tools make at most three bounded discovery calls per step. Their common-ingredient summary contains at most 30 entries and remains advisory; exact registry lookup can resolve other ingredients. Related vitamins and derivatives are distinct unless an explicitly reviewed alias denotes the same identity.

`ProductService` pins one configuration and physical index generation per routine. One OpenSearch query returns at most 100 candidates, sorted by distinct preferred ingredient count and then product ID. Category must-haves are an AND; exclusions apply to every step. Exclusions require both a complete ingredient list and complete identity resolution. Market, currency, price and availability constraints use explicit canonical facts.

An initial canonical read covers ten candidates. At most one refill covers the remaining candidates. The server selects at most three products per step and rejects changed matching facts. The compiler rereads at most 24 products once before the final response. Display changes refresh facts and invalidate old explanations. Model-produced product IDs cannot replace, reorder or reduce the approved list.

API v2 completes matched and no-match steps explicitly. Legacy v1 keeps photos-only input and reports a terminal `NO_MATCHING_PRODUCTS` error when needed. Dependency failures, stale readiness and partial search results are service failures. Explanation timeouts/provider failures use factual templates; guardrail intervention remains terminal.

## Catalog publication and maintenance

The trusted publisher atomically writes the canonical product, immutable outbox
event and one of 16 source counters. Stable product IDs choose their shard
deterministically. Supplier revisions order updates to a product. A worker leases
one shard, writes full external-version documents and refreshes the index before
acknowledging each generation independently. Stream notifications accelerate work;
minute schedules recover missed notifications from the durable outbox.

A separate maintenance role performs resumable backfills and reconciliation in
both directions, including hashes and tombstones. Equal-revision conflicts are
quarantined; missing/older projections can be repaired by authoritative replay.
Ingredient counts use paginated composite aggregation over a fixed PIT snapshot.
The maintenance worker refreshes readiness during each scheduled invocation.
Missing/stale source health, integrity failures and overdue reconciliation prevent
admission. A live feed requires a fresh heartbeat; an immutable snapshot has an
explicitly different health mode.

Generation registration, fenced checkpoints and source-watermark cutover are
transactional. Runtime resolves the physical generation from the manifest.
The operational alias is updated atomically without deleting indices. Retained
rollback generations continue receiving updates for at least seven days.
See [the operations runbook](search-spec/operations.md).

## Stream contract

| Graph event | Meaning |
|---|---|
| `multiagent_node_start` | A named node has started. |
| `multiagent_node_stop` | A node completed, with status and structured output when applicable. |
| `multiagent_result` | A graph finished. The diagnose result is intermediate; completion requires the compiled routine. |
| `error` | The pipeline failed; an allowlisted code, safe message, and correlation reference are returned. |
| `heartbeat` | The request is still running; emitted during model silence, within the 120-second routine deadline. |

The API client supports SSE comments, CRLF, multiline data, split UTF-8 chunks and AgentCore's JSON-string encoding. It rejects malformed data, unsuccessful node/graph statuses and streams that end without a final routine. A transport or pipeline error never becomes an empty success object.

`frontend/src/hooks/useAnalysis.ts` owns the request and all analysis state. Reset, sign-out and unmount abort the active request and invalidate stale callbacks. Components receive canonical types from `frontend/src/types/index.ts`; they do not parse JSON or infer stages from prose. Final empty recommendations have explicit messages instead of loading skeletons.

## Infrastructure and builds

| Area | Responsibility |
|---|---|
| CloudFront, S3 and WAF | Frontend delivery and the protected API origin path. |
| Cognito | Direct SRP/password/refresh authentication for administrator-created users. |
| API Gateway | Cognito authorization, streaming integration, and CORS responses. |
| Lambda proxy | Verified user identity, usage limits, server-owned sessions, and IAM-authenticated runtime invocation. |
| AgentCore and Bedrock | Runtime hosting, graph execution and model calls. |
| DynamoDB | Canonical products, metadata/leases, sharded durable outbox and separate per-user usage allowances. |
| OpenSearch | Private keyword projection with exact count ranking; no semantic or description scoring. |
| Publication and maintenance Lambdas | Ordered replay, per-generation acknowledgements, snapshots, reconciliation and readiness. |
| S3, CodeBuild and ECR | Source archive, ARM64 image build and immutable image publication. |
| CloudWatch | Runtime, build and API observability. |

`terraform/shared/` owns account-level API Gateway logging configuration and the OpenSearch service-linked role. Import pre-existing shared resources before applying. Each application environment has its own state key. Deployment resolves the Region once and passes it to provisioning and migration.

A shared source-file manifest controls runtime packaging and change detection. It includes the catalog and Python lockfile. Image tags follow the complete content hash. Archives are recreated so deleted files cannot survive in subsequent builds. API stage deployment similarly tracks configuration content, including integration and OPTIONS response settings.

The runtime image installs locked dependencies using uv and runs as a non-root user. Python and npm locks are tracked; local test dependencies are separate from the runtime instrumentation group.

## Network and authentication details

The reference diagram groups services by responsibility. Its AWS Cloud outline is
not a VPC or single-region boundary. Deployment and authentication settings are
described below.

CloudFront and its WAF are global edge services. The frontend S3 bucket is
regional and private; CloudFront accesses it through OAC / SigV4. API requests
are uncached, and a CloudFront Function rewrites `/api/analyze` for the regional
API origin. Regional WAF checks a custom origin-verification header.

AgentCore uses VPC networking in two private subnets. OpenSearch accepts HTTPS
from the workload security group and native IAM authentication. VPC endpoints
provide required AWS API access without an internet gateway or NAT. Runtime,
projection, maintenance and administration have separate index permissions.
The runtime uses IAM authentication. Its resource policy allows the Lambda proxy
role and explicitly denies invocation by other principals. Browser Cognito tokens
are verified at API Gateway, rather than forwarded as runtime authentication.
Normal gateway access and direct-runtime rejection still require live deployment
verification; source configuration and offline policy assertions are not proof of
enforcement in AWS.

The default limits allow five accepted analyses per user per fixed UTC hour and
one active analysis per user, with ten concurrent proxy invocations per deployment.
DynamoDB transactions coordinate counters and leases. Ambiguous runtime failures
retain the lease until expiry because disconnecting does not prove runtime work
has stopped. These controls bound accepted usage; they do not establish production
throughput.

The default Bedrock model IDs use global inference profiles. Model processing
can occur outside the deployment region. CloudFront access logs go to S3; API, WAF and build logs go to
CloudWatch. Runtime telemetry is instrumented but its delivery has not been
verified live.

## Verification and limits

See [the testing guide](../tests/README.md) for unit, offline integration, frontend, and live smoke layers. Offline integration exercises the real AgentCore HTTP/SSE adapter with external work substituted; deployment tests use command stubs and temporary files.

Live behavior still depends on model access, regional availability, quotas, IAM and network timeouts. In particular, the configured CloudFront read timeout is 60 seconds between upstream responses. There is no persisted recovery path after disconnecting.

Guardrails are connected to both model clients. Regional WAF managed blocking
rules run before the origin-header allow rule, and sensitive headers are redacted
from WAF logs. Remaining live verification and deployment decisions are tracked
in [the security checklist](security-checklist.md), including the default
CloudFront certificate's TLS policy and historical credential exposure.

## Diagram maintenance

The reference image's source of truth is
`guidance-for-ai-powered-skincare-analysis-on-aws.pptx`, retained with the
Guidance publishing artefacts. Its existing PNG export is copied unchanged to
`assets/images/architecture.png` for the README and `docs/architecture.png` for
this guide. Both copies must stay identical. The slide has not been redrawn,
relabelled, cropped, or generated with an image model.

The older [draw.io diagram](architecture.drawio) is retained only as historical
source. It predates the Lambda proxy and is not the editable source of the
approved reference architecture. A future architecture revision must incorporate
private exact search, canonical publication and maintenance in the PPTX through
the Guidance review process, then replace both PNG copies with the approved
export. Until then, use the descriptions above for these implementation details.

## Reference documentation

- [AWS architecture icons](https://aws.amazon.com/architecture/icons/)
- [CloudFront OAC and private S3 access](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-s3.html)
- [AWS WAF resource scope](https://docs.aws.amazon.com/waf/latest/developerguide/how-aws-waf-works-resources.html)
- [AgentCore VPC networking](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html)
- [AgentCore JWT authentication](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/inbound-jwt-authorizer.html)
- [AgentCore runtime security](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-security-best-practices.html)
- [Strands structured output](https://strandsagents.com/docs/user-guide/concepts/agents/structured-output)
- [AgentCore Python SDK](https://github.com/aws/bedrock-agentcore-sdk-python)
- [DynamoDB query pagination](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Query.Pagination.html)
- [React effect cleanup](https://react.dev/learn/synchronizing-with-effects)
- [uv project locking](https://docs.astral.sh/uv/concepts/projects/sync/)
- [npm clean installs](https://docs.npmjs.com/cli/v11/commands/npm-ci)
