# Testing

Run `make setup` once to install the locked Python, frontend, and streaming proxy dependencies, then `make test`.
The default suites require no AWS credentials and make no live model requests.

| Layer | Command | What it checks |
|---|---|---|
| Python unit | `uv run --locked pytest tests/unit` | Catalog input validation, routine and metric constraints, product scoring, SSE serialization. |
| Python integration | `uv run --locked pytest tests/integration` | Repository pagination/failures, tool retry state, deterministic compilation, entrypoint → orchestrator → compiler → SSE, AgentCore ASGI `/ping` and `/invocations`, deployment command wiring, archive contents. |
| Frontend | `npm test --prefix frontend` | SSE framing/auth/errors, missing-config startup, cancellation and stale callbacks, sign-out isolation, concurrent photo uploads, final result empty states. |
| Streaming proxy | `npm test --prefix api_proxy` | Verified-claim identity, payload limits, runtime invocation, error handling, transactional usage limits, and lease release/failure behavior with mocked AWS boundaries. |
| Static checks | `make validate` | Python compilation, TypeScript, Terraform formatting/validation. Terraform providers must already be initialized. |
| Live smoke | `uv run --locked python -m tests.live_sse --image /path/to/photo.jpg` | A deployed authenticated request, all planned node outputs and a successful compiled routine. Set `API_URL` and `AUTH_TOKEN` explicitly. |

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

Test APIs follow the official [pytest monkeypatch guide](https://docs.pytest.org/en/stable/how-to/monkeypatch.html),
[Vitest configuration](https://vitest.dev/config/) and
[React Testing Library](https://testing-library.com/docs/react-testing-library/intro/).
