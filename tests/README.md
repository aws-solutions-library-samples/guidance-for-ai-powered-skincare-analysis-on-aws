# Testing

Run `make setup` once to install the locked Python, frontend, and streaming proxy dependencies, then `make test`.
The default suites require no AWS credentials and make no live model requests.

| Layer | Command | What it checks |
|---|---|---|
| Python unit | `uv run --locked pytest tests/unit` | Exact identity/eligibility/count rules, input validation, bounds, and SSE serialization. |
| Python integration | `uv run --locked pytest tests/integration` | Bounded reads/retries, canonical binding, sharded publication/recovery, reconciliation, summary pagination, real graph/compiler/SSE and explanation cancellation, deployment wiring and archive contents. |
| Frontend | `npm test --prefix frontend` | SSE framing/auth/errors, missing-config startup, cancellation and stale callbacks, sign-out isolation, concurrent photo uploads, final result empty states. |
| Streaming proxy | `npm test --prefix api_proxy` | Verified-claim identity, payload limits, runtime invocation, error handling, transactional usage limits, and lease release/failure behavior with mocked AWS boundaries. |
| Static checks | `make validate` | Python compilation, TypeScript, Terraform formatting/validation. Terraform providers must already be initialized. |
| Live smoke | `uv run --locked python -m tests.live_sse --image /path/to/photo.jpg` | A deployed authenticated request, all planned node outputs and a successful compiled routine. Set `API_URL` and `AUTH_TOKEN` explicitly. |
| Live release | `uv run --locked python -m tests.live_release --help` | Opt-in test-account controls, temporary identities, real quota/lease enforcement, direct IAM denial, and optional timed photo analysis. See the [release runbook](../docs/release-validation.md). |
| Live model contracts | `uv run --locked python -m tests.live_models --help` | Synthetic schema, vision, structured-output retry, and live catalog-tool checks with both configured models and deployed Guardrails. See [model configuration](../docs/model-configuration.md). |
| Local OpenSearch | `uv run --locked python tests/local_search_engine.py --credentials /absolute/path/credentials.json --report /absolute/path/report.json` | Actual exact-query ordering, external version replay, PIT summary counts, reconciliation, and reader/writer/maintenance permission denials. Dedicated HTTPS loopback engine only; temporary resources are removed. |

The local-engine suite uses 420 varied fixture records and 120 exhaustive
ordered comparisons. It explicitly records connection warm-up separately from
the bounded queries. This is correctness and permission evidence, not managed
AWS capacity evidence. It does not substitute for the one-million-product,
20-routine/second, update, failure and soak gates in
[the search verification specification](../docs/search-spec/verification.md).
The approved qualification budget is recorded
[separately](../docs/search-spec/qualification-budget.md).

`aws_catalog_publication.py` is an opt-in managed DynamoDB transaction test.
Pass `--profile`, `--region eu-west-1`, `--account` and `--report`; without
`--execute` it only reports its estimate. An executed run creates three uniquely
tagged tables and deletes them after the checks.

`aws_search_qualification.py prepare --directory /absolute/new/run-directory
--profile PROFILE --account ACCOUNT` copies the current Terraform and locked
archives, creates an isolated local state configuration, and saves a plan.
It first checks the worker archive against application source, rejecting stale,
deleted and duplicate members. The report records source/specification, archive
and saved-plan SHA-256 manifests. Execution verifies those frozen inputs before
obtaining an AWS session; source or artifact changes require a new preparation.
Review `plan.log`, `plan.json` and `report.json` before running `execute` with the
same arguments. Execution is limited to the eu-west-1 component phase described
in the budget record and always attempts teardown. Do not use it without the
corresponding approved spending reserve. Its scheduled rules are disabled and
the search probe uses Lambda with the runtime's search/read policy fragment;
this does not qualify the actual AgentCore runtime, public API, models or capacity.

When a terminal failed component run retains exactly its five test roles, preparation
can take `--reuse-roles-from /absolute/failed/run-directory`. The original creation
plan and state must identify those roles, and live IAM checks must confirm their
immutable IDs, trust policies, and empty test-role permissions. The new plan reads
the roles through Terraform data sources and rejects any managed IAM role; it
does not import them or modify the predecessor's state. Changes to predecessor
evidence or role permissions stop execution. Teardown must remove the new
resources and policies and verify the roles have returned to their prior state.
The predecessor's five outstanding role deletions remain explicitly unverified.

The managed reader probe captures the same bounded candidates used by application
selection, without an additional query. The independent oracle compares every
ordered top-100 ID/count and the final top three before and after rebuild/rollback.
The raw query cases and expected results are retained with a checksum.

Role reuse follows the official [IAM GetRole](https://docs.aws.amazon.com/IAM/latest/APIReference/API_GetRole.html),
[inline policy listing](https://docs.aws.amazon.com/IAM/latest/APIReference/API_ListRolePolicies.html),
[attached policy listing](https://docs.aws.amazon.com/IAM/latest/APIReference/API_ListAttachedRolePolicies.html),
[OpenSearch service-linked role](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/slr-aos.html)
and [Terraform role data source](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_role)
documentation. It uses the existing approved account/profile and spending reserve.

The integration suite uses real application modules and substitutes external
boundaries. Python tests reject socket connections. Deployment scripts run from
a temporary project with fake AWS, Terraform, npm and uv commands; they cannot
apply or destroy real resources. Frontend tests use jsdom and mocked transport,
authentication and camera devices.

When adding a behavior, test its smallest deterministic rule first, then test
the boundary where it can fail: absent data, malformed output, partial work,
retries, cancellation or completion arriving out of order. Use the integration
layer for contracts between modules instead of duplicating unit assertions.
Every fixed defect should have a regression that would fail before the fix.

The live smoke test is deliberately outside pytest discovery and needs a real
skin photo. It can incur AWS charges. It fails on any error event, incomplete
graph, missing recommendations or invalid final result. It does not assess the
medical quality of model advice, IAM policies, deployment behavior, load,
cross-browser rendering or real camera permissions. Validate those separately
before a release; passing offline tests is not evidence that AWS is deployed.
The broader live release checker records event arrival times and checks deployed
controls. It still requires separate browser, guardrail, operational and capacity
evidence; its report cannot approve a release automatically.

Test APIs follow the official [pytest monkeypatch guide](https://docs.pytest.org/en/stable/how-to/monkeypatch.html),
[Vitest configuration](https://vitest.dev/config/) and
[React Testing Library](https://testing-library.com/docs/react-testing-library/intro/).
