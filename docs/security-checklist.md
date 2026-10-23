# Security remediation checklist

Updated: 2026-10-23 (M-03/M-05 implementation status; no additional live closure). Source baseline: the PACE security review of the
`open-source` branch. This is a work tracker, not a claim that the application
is ready for public deployment.

**Completion rule:** check an item only after its implementation, relevant
automated checks and live verification have passed. Record the date, tested
revision/artifact, environment and evidence. A local fix, static scan, mocked
AWS response, or direct service test alone does not prove that the deployed
application enforces a control. An accepted exception is recorded separately
and is not marked as a tested fix.

Keep account IDs, internal demo URLs, credentials, personal images and raw
private evidence out of this document. Local evidence is retained in ignored
`.ash/` directories. Recheck this list when code or deployment configuration
changes.

## Confirmed source/configuration risks — 3 of 11 closed

- [ ] **M-01 · HIGH — Guardrails not connected to model clients.**
  Code implemented in both factories, including validation and typed block
  handling. Offline tests exercise the pinned Bedrock/Strands/AgentCore adapters
  for all five public block codes on input and output, plus allowed content.
  Live test confirms the deployed client uses the intended policy and an output
  block reaches the browser as `GUARDRAIL_TOPIC` with a reference. The synthetic
  drawing was correctly recognized as unsuitable for photo analysis; its refusal
  text matched `medical-diagnosis` on output (no input block). Evidence:
  `.ash/remediation/guardrail-live-diagnosis.json` and `live-guardrail-error.jpg`.
  The user's ordinary-photo test completed diagnosis but was blocked at the first
  ingredient call. Exact CLI replay isolated an application-added tool instruction
  as a LOW-confidence `PROMPT_ATTACK` false positive. Removing only that duplicate
  instruction preserves the full plan and HIGH filter. Three policy repetitions
  allow the corrected plan and block an injected attack; the actual agent does
  likewise. All 13 prescribe nodes completed in a live AWS replay from the captured
  diagnosis (27 model calls). Python suite: 187 passed.
  Deployed on 2026-10-19 to isolated `test`, runtime version 3, source artifact
  `b21d8d8e768643a116911dd27f77bac974ae5c50`; guardrail version and role unchanged.
  All 14 deployed input/error smoke checks passed:
  `.ash/remediation/live-guardrail-fix-smoke.json`.
  See [diagnosis and repeatable CLI command](guardrail-diagnostics.md).
  **Live closure pending:** verify a complete normal-photo request on the updated
  deployed application. Replaying captured diagnosis through local application
  code with real AWS services does not prove that entire deployed request path.
  Text filters also must not be described as assessing all image pixels.

- [ ] **M-02 · HIGH — WAF logs/sample requests can expose bearer and origin credentials.**
  Implemented and verified live in `test`: Authorization, origin-verification and
  Cookie headers were `REDACTED` in both WAF log groups; all seven ACL/rule sampling
  checks returned zero requests and sampling is disabled. Evidence:
  `.ash/remediation/live-control-verification.json`.
  **Still open:** assess previous demo exposure and rotate/revoke affected
  credentials if exposure is confirmed. The test-stack fix does not repair
  previously captured credentials or deploy the fix to the existing demo.

- [ ] **M-03 · MEDIUM — Matching JWT can bypass gateway WAF/throttles.**
  Code implemented: API Gateway verifies Cognito; the Lambda streaming proxy
  uses verified claims and IAM runtime invocation, with a runtime resource policy
  restricting invocation to the proxy role. Offline tests cover proxy identity,
  failure paths, usage controls, and policy configuration. **Live closure pending:**
  exercise normal and direct-runtime requests against the deployed revision;
  prove direct invocation is rejected. Verify unauthenticated and wrong-audience
  rejection too.

- [ ] **M-04 · MEDIUM — Product fields/image URLs are trusted from model output.**
  Implemented: bind recommendations to stable IDs from the executing node's
  trusted query and hydrate catalog fields before intermediate/final events.
  Restrict product images to published same-origin assets. **Closure:** fabricated IDs, modified
  prices and arbitrary image URLs fail offline and in deployed requests, while
  valid catalog recommendations render correctly.

- [ ] **M-05 · MEDIUM — Backend image/resource limits are missing.**
  Implemented: strict request schema; 1–3 images, 1 MiB per image, 2048 pixels
  per side; encoded/decoded size checks, actual pixel decoding, animation
  rejection and metadata removal before runtime construction.
  Live verification on test artifact `e1ad713213d7216b97e0480a6e9eaff246c60883`
  passed 14 rejection cases across gateway and direct-runtime paths, with no agent
  work started. Evidence: `.ash/remediation/live-image-limits.json`.
  Per-user rate and active-analysis limits are now implemented in the Lambda
  proxy using DynamoDB transactions, with a deployment-wide concurrency cap.
  Live enforcement of these new limits remains unverified. **Closure:** boundary,
  oversized, excessive-count, corrupt and decompression-heavy requests are
  rejected before model work, including direct runtime calls; valid photos pass.

- [ ] **M-06 · MEDIUM — Runtime/model permissions and build trust are too broad.**
  Code implemented: unused runtime/identity actions removed, model resources
  limited to the active primary/fast models, and CodeBuild trust constrained to
  this account/project. **Closure:** policy validation plus actual allowed
  workflow tests and denied unused-action checks under the deployed roles.
  Preserve permissions that observed application/build behavior requires.

- [x] **M-07 · MEDIUM — Regional WAF Allow terminates before managed rules.**
  Verified 2026-10-19 in `test`, source artifact
  `dbd375b1926fd96b62612cd24363ec95a0e94321`. With the same valid origin
  credential, benign traffic reached the application (HTTP 200), while a synthetic
  KnownBadInputs header was blocked (HTTP 403). Regional WAF logs identify
  `Log4JRCE_HEADER` as the terminating managed rule and `allow-cloudfront-only`
  for the benign control. Evidence: `.ash/remediation/live-control-verification.json`.

- [x] **M-08 · MEDIUM — First login reuses the temporary password.**
  Verified 2026-10-19 in the isolated `test` deployment. The deployed UI displays
  the new-password challenge; the actual application auth module, exercised
  against Cognito with a dedicated synthetic account, rejects temporary-password
  reuse, completes the challenge, rejects the old password and accepts the new
  password. UI confirmation/mismatch and SDK failure tests pass. No existing
  user's password was changed. Evidence: `.ash/remediation/live-auth-tests.json`
  (includes source SHA-256) and `live-password-challenge.jpg`; frontend suite
  66 passed. This closure applies to the tested open-source deployment.

- [x] **M-09 · LOW — Internal error text is displayed to the user.**
  Verified 2026-10-19 in `test`, source artifact
  `dbd375b1926fd96b62612cd24363ec95a0e94321`. Invalid input and a real unavailable
  catalog produced distinct safe SSE errors and correlation references; anonymous
  access returned HTTP 401. The deployed browser displayed `SERVICE_UNAVAILABLE`
  and its reference, matching restricted runtime logs with the diagnostic stack
  trace. Public errors contain only allowlisted fields/messages. Python adapter
  tests, 66 frontend tests and the production build passed. Evidence:
  `.ash/remediation/live-control-requests.json`, `live-error-log-correlation.json`
  and `live-service-error.jpg`. Guardrail enforcement remains tracked under M-01.
  See [analysis error contract](analysis-errors.md).

- [ ] **M-10 · LOW — CSP permits broad scripts and arbitrary HTTPS images.**
  Implemented: scripts restricted to self, images restricted to self/data/blob,
  connections restricted to self/regional Cognito; object/base/form restrictions
  added. The deployed browser allowed same-origin JavaScript and recorded enforced
  violations for inline script, eval, external script and external image probes.
  Evidence: `.ash/remediation/live-csp-browser.txt` and `live-csp-browser.jpg`.
  **Closure:** production
  browser tests cover sign-in, photo capture/upload and results; live headers
  enforce the policy and an unapproved image/script origin is blocked.

- [ ] **F-001 · MEDIUM — Default-certificate TLS policy limitation; deployment decision remains.**
  **Source correction complete:** the default-certificate branch in
  `terraform/cloudfront.tf` now states its actual `TLSv1` policy. The original
  setting incorrectly implied that this branch enforced TLS 1.2.
  Both intended deployment options are already implemented: the default
  `*.cloudfront.net` hostname provides HTTPS with AWS's fixed `TLSv1` policy;
  the optional custom-domain/ACM branch selects `TLSv1.2_2021`.
  The default policy permits older TLS versions; it does not mean every client
  connection uses TLS 1.0. See the official
  [CloudFront ViewerCertificate reference](https://docs.aws.amazon.com/cloudfront/latest/APIReference/API_ViewerCertificate.html).
  **Remaining decision:** a deployment requiring a TLS 1.2 minimum must use the
  existing custom-certificate option and verify it live. Keeping the default
  option retains this documented platform limitation; any accepted exception
  must be recorded separately. This finding does not require making custom
  domains mandatory for the project.
  **Closure:** for a TLS upgrade, inspect the deployed certificate/security policy
  and verify that live TLS probes reject obsolete versions and accept supported
  versions. Correcting the source description alone does not upgrade the default
  deployment's TLS minimum.

## Dependency advisories — 0 of 6 closed

These are the version matches in the original review, not demonstrated remote
exploits. Recheck official advisories and compatibility before selecting fixes.
For runtime changes, run integration tests and a deployed smoke test. For build
or test dependencies, verify the relevant attack condition, rebuild and audit
the dependency tree, then smoke-test the resulting deployed artifact.

- [ ] **D-01 — bedrock-agentcore / GHSA-6rfw-mq36-jm8h.**
  Code Interpreter dependency surface; no application call was found.
- [ ] **D-02 — bedrock-agentcore / GHSA-j6g5-3hh3-pgw8.**
  Same unused surface; the selected upgrade must address both AgentCore advisories.
- [ ] **D-03 — pytest / GHSA-6w46-j5rx-g56g.**
  Development/test temporary-directory issue; excluded from the runtime image.
- [ ] **D-04 — requests / GHSA-gc5v-m9x4-r6x2.**
  Affected archive-path helper; no application call was found.
- [ ] **D-05 — braces / GHSA-vfj7-8cjw-p6xm.**
  Build/development parsing denial of service; original audit reported no patched
  braces version. Confirm exposure and a compatible dependency-path resolution.
- [ ] **D-06 — postcss-selector-parser / GHSA-rj75-hqrm-r3gf.**
  Build/development parsing issue requiring untrusted selector input.

## Scanner findings requiring a decision or more evidence

The following are the 27 original `needs-triage` records. They are not promoted
to confirmed vulnerabilities just because a scanner assigned CRITICAL severity.
Resolve the deployment requirement, implement any needed control, and verify it
live before checking a record as remediated. Record a justified exception or
not-applicable verdict explicitly instead of silently checking it.

- [ ] **F-002** Source-bucket lifecycle/retention.
- [ ] **F-003** Source-bucket event detection requirement.
- [ ] **F-004** Source-bucket cross-region recovery/residency requirement.
- [ ] **F-005** Source-bucket explicit encryption and CMK requirement.
- [ ] **F-006** Source-bucket access audit coverage.
- [ ] **F-007** Privileged CodeBuild isolation and trusted-source boundary.
- [ ] **F-008** API replacement/availability behavior.
- [ ] **F-009** API log-group CMK requirement.
- [ ] **F-010** API tracing coverage.
- [ ] **F-011** Frontend-bucket lifecycle/retention.
- [ ] **F-012** Frontend-bucket event detection requirement.
- [ ] **F-013** Frontend-bucket cross-region recovery/residency requirement.
- [ ] **F-014** Frontend-bucket CMK requirement.
- [ ] **F-015** Frontend-bucket access audit coverage.
- [ ] **F-016** Log-bucket event detection requirement.
- [ ] **F-017** Log-bucket cross-region recovery/residency requirement.
- [ ] **F-018** Log-bucket CMK requirement.
- [ ] **F-019** Log-bucket access audit coverage; avoid recursive self-logging.
- [ ] **F-020** CloudFront origin-failover/availability requirement.
- [ ] **F-021** Audience/geographic restriction requirement.
- [ ] **F-022** Catalog DynamoDB CMK requirement.
- [ ] **F-023** ECR CMK requirement.
- [ ] **F-024** Edge WAF log-group CMK requirement.
- [ ] **F-025** Edge WAF log retention requirement.
- [ ] **F-026** Regional WAF log-group CMK requirement.
- [ ] **F-027** Regional WAF log retention requirement.
- [ ] **F-028** Dependency cooldown/update policy.

## Architecture and assurance follow-ups

- [ ] **A-01** Confirm intended audience, user approval process and MFA requirement;
  verify deployed membership and access behavior.
- [ ] **A-02** Confirm permitted photo data, processing regions, retention/content
  capture and non-diagnostic product claims; verify actual service/log settings.
- [ ] **A-03** Verify build, deployment and Terraform-state writer trust boundaries.
- [ ] **A-04** Complete container/OS/SBOM scanning and verify the deployed image,
  telemetry coverage and retention. Static source tests alone do not close this.

## Requested guardrail adjustment

- [x] **G-01 — Allow age while retaining prompt-attack protection.**
  Verified live on 2026-10-19: policy version 2 omits AGE and retains PROMPT_ATTACK
  input HIGH; normal skincare, explicit age and age-range cases passed; synthetic
  prompt attack and medical-topic controls were blocked by the expected filters.
  The existing demo's DEFAULT endpoint is READY on runtime version 24 referencing
  policy version 2. The application image, authorizer and other environment values
  were preserved; AWS additionally populated previously absent platform metadata
  as `V1`. Policy version 1 is retained for rollback.
  This policy adjustment does not close M-01 or prove end-to-end application coverage.

## Evidence log

| Date | Scope | Result | Closure effect |
| --- | --- | --- | --- |
| 2026-10-19 | Baseline ASH and manual review | 11 source/configuration findings; 27 scanner triage records; 6 dependency advisories; 153 scanner false positives | Establishes baseline; no remediation closed |
| 2026-10-19 | Python suite after M-01/M-09 code changes | 145 tests passed; external AWS calls mocked in integration tests | Local validation only |
| 2026-10-19 | Frontend suite/type check/production build | 60 tests passed; TypeScript and Vite build passed | Local validation only |
| 2026-10-19 | Deployment plan inspection | Open-source application plan also changes existing demo SSO and legacy pipeline configuration | Broad application plan not applied; M-01/M-09 live verification pending |
| 2026-10-19 | Open-source source-link audit | No internal demo URL found in tracked files; local deployment settings remain ignored | Scope check, not a security-risk closure |
| 2026-10-19 | G-01 live service and active runtime checks | Five policy-isolation tests passed; active DEFAULT endpoint references the tested version | G-01 closed only; private evidence in `.ash/remediation/age-policy-live-tests.json` and `runtime-guardrail-verification.json` |
| 2026-10-19 | Isolated test deployment | Separate Terraform state and 57 new resources; image `dbd375b1926fd96b62612cd24363ec95a0e94321`; anonymous analysis rejected with HTTP 401 | Test environment established without replacing the demo application |
| 2026-10-19 | M-08 live authentication | Four real Cognito checks passed using the application auth module; deployed challenge UI verified; 66 frontend tests and production build passed | M-08 closed for the test deployment |
| 2026-10-19 | M-02/M-07 live WAF tests | Both log paths redact credentials, all seven sample queries empty; benign regional request allowed and synthetic attack blocked by `Log4JRCE_HEADER` | M-07 closed; M-02 historical exposure still pending |
| 2026-10-19 | M-09 live API and browser errors | Distinct input/service/auth failures; safe browser message and reference correlated with restricted server logs | M-09 closed for the test deployment |
