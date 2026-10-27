# Implementation and qualification status

Updated 2026-10-27. **In progress; not a production qualification or deployment approval.**
The requirements in the specification remain the acceptance contract.

## Implemented application path

The application uses exact canonical ingredient IDs, an AND of explicit must-haves,
routine-wide exclusions and deterministic distinct-match counts. OpenSearch returns
at most 100 candidates; canonical reads use an initial ten and one bounded refill.
The compiler performs one final read of at most 24 selected products. Changed
matching facts remove a product; changed display facts refresh it and invalidate
the earlier generated explanation.

Ingredient discovery uses bounded metadata reads and exact registry resolution.
The product model explains the approved list; invented, missing or reordered
product IDs cannot replace the server's list. API v2 accepts preferences and
completes mixed/all-no-match routines. Legacy v1 keeps photos-only input and
receives a terminal `NO_MATCHING_PRODUCTS` error when appropriate.

The browser resolves names before submitting IDs, preserves explicit constraints,
shows match counts and availability facts, and cancels stale lookup results.
Runtime IAM removes product scans and catalog administration. The infrastructure
declares a private OpenSearch domain, private AgentCore connectivity and separate
publisher, projection and administrator permissions.

## Evidence obtained

| Check | Observed result | Limit |
|---|---|---|
| Python suite on 2026-10-27 | 315 passed, including the importer-summary, native TLS and qualification-provenance regressions | Managed TLS rerun remains |
| Qualification artifact checks on 2026-10-27 | 10 new regressions passed; 28 checks passed with deployment-script coverage; the rebuilt worker archive matches all 20 application files | No new cloud run; hashes cannot retroactively qualify earlier attempts |
| Proxy suite on 2026-10-27 | 52 passed; deployment archive rebuilt | AWS invocation remains |
| Frontend suite/build on 2026-10-27 | 96 passed; TypeScript and production build passed | Browser smoke in AWS remains |
| Terraform modules | Environment and shared modules validated on 2026-10-27 using cached locked providers, including monitoring | Only an isolated search-component subset was applied; full environment and enforcement remain untested |
| Actual OpenSearch adapter | 120 exhaustive ordered top-100 comparisons over 420 varied records; zero differences | Local OpenSearch 3.9.0, two shards, no replicas; target managed version is 3.5 |
| Actual engine permissions | Seven denials: reader write/mget/foreign-index; writer search/create-index; maintenance create-index/foreign-index | Local engine roles; AWS IAM/VPC enforcement is untested |
| Actual version replay | Duplicate replay and late update after a deletion retained the newer version | Local engine; DynamoDB transaction boundary tested with controlled I/O |
| Actual maintenance snapshots | Exact category/ingredient count agreement and 420 index-to-canonical identity/revision/hash/tombstone checks | Local engine plus controlled canonical boundary |
| Managed DynamoDB | 17 events across 16 shards; duplicate/stale/tombstone and competing/released lease checks passed; all three tables removed | Small fixture test, not update throughput |
| Managed infrastructure | Isolated OpenSearch 3.5, VPC endpoints, tables and Lambda functions provisioned after separate service-role setup | First native client initialization failed; see below |

An initial bounded local-engine run failed with a 350 ms search timeout. The
separate successful run explicitly warmed the new basic-auth connection first;
that warm-up took 441.11 ms. The failed run is retained in the task output and
must not be counted as a passing latency sample. These runs establish query and
permission behavior, not a cloud latency SLO.

The 2026-10-27 engine run also exercised PIT aggregation and reconciliation.
Two failures found during that work were fixed: background count queries now
collect full hit counts before passing the strict completion validator, and PIT
deletion is authorized at index scope. The successful rerun retained all strict
completion and scope checks; it recorded a separate 269.29 ms connection warm-up.

The managed component phase retained two failed runs. The first received AWS's
service-linked-role validation error immediately after IAM creation; all 60
partially created resources were removed. A retry provisioned the role separately,
verified its managed policy and allowed propagation before creating the domain.
That deployment succeeded, but initialization exposed a client defect:
`ssl_assert_hostname=True` reached urllib3 as a hostname and raised `bool.strip`.
The client now passes the endpoint hostname explicitly with certificate validation
required. A regression reproduced the original exception, then verified matching
hostname acceptance and mismatched-certificate rejection after the fix.

The second run removed its domain, functions, tables and networking. Four
policy-free test roles remain after explicit session-policy denials of `DeleteRole`.
AWS's authorization-details response confirms that the role's administrator
policies allow the action and a session-policy statement denies it. The
service-linked role remains after a separate generic deletion failure; a permission
denial has not been established for that role. A later cleanup plan targeted only
that role and failed with the same generic result after the domain was gone. The
private manifest retains exact
identities and diagnostics. Cleanup access and a repeat of the managed
correctness/permission/rebuild checks are still required; successful infrastructure
creation is not a passing native-search test.

Preparation now verifies the worker ZIP's application bytes against source,
including deleted and duplicate members, before obtaining an AWS session. It
also checks the copied archive against the frozen source. Source, specification,
archive and saved-plan SHA-256 manifests are retained with the run and checked
again before execution. Changed or missing evidence requires a new preparation.
The post-prerequisite execution plan and fixture corpus receive separate hashes;
failed Lambda invocations remain in the reported invocation count. These checks
prevent stale local artifacts from being reported as qualification of newer code.

The final review also reproduced the demo importer's overwrite of a maintenance
summary after readiness. Maintenance now owns all replacement summaries, and the
publisher policy no longer permits summary writes. Its regression preserves the
generation-bound summary published while import completion waits.

`tests/local_search_engine.py` reproduces the isolated engine checks and removes
its temporary indices/users/roles. It accepts only loopback endpoints. Its report
is written under ignored `output/exact-search-implementation/`.

## Completion audit

| Requirement/gate | Evidence or current gap | State |
|---|---|---|
| R01 / T01–T02 identities | Explicit registry, same-name normalization, no related-ingredient substitution, contract/predicate tests | Local coverage; production registry review pending |
| R02–R03 constraints/order | Exact adapter, canonical checks, independent local-engine oracle | Local coverage; managed-engine qualification pending |
| R04–R05 bounds/no scans | Search/discovery limits, shared retry ledger, runtime role changes, tests | Local coverage; deployed tracing/overload checks pending |
| R06 / T06 publication | Sixteen sharded transactional outboxes, fenced leases, per-generation acknowledgements, external versions, tombstones, partial-failure replay and quarantine/reconciliation; small managed DynamoDB transaction test | Concurrency/update-load and complete managed projection evidence remain |
| R07 / T05 facts | Server binding, display refresh, matching-change removal, final read tests | Local coverage; sample live output audit pending |
| R08 / T07 failures | No-match/error separation, readiness denial, deadline/heartbeat, explanation provider fallback/cancellation and terminal guardrail tests | Local coverage; deployed fault tests remain |
| R09 / T08 client/graph | Real graph/compiler/SSE tests including v2 mixed/all-no-match, proxy and browser tests | Local coverage; live browser/SSE checks remain |
| R10 / T09 access | Private Terraform, scoped IAM, real local engine role denials | Anonymous/native IAM/network negative tests in AWS remain |
| R11 / T06/T10 rollback | Resumable backfill/reconciliation, source-watermark/fenced cutover, independent acknowledgements and seven-day grace | Local coverage; interrupted-cutover/rollback drill in AWS remains |
| R12 / P01–P03 | Targets remain one million products and 20 routines/second | No deployed capacity/soak/update/failure/cost qualification yet |
| R13 isolation/cancellation | Per-routine state, server request/step binding, cancelled stale browser lookups | Full live disconnect and queue/cancellation checks remain |
| R14 / E01 behavior review | Match counts are coverage; synthetic fixture identities explicitly labelled | At least 100 representative cases, reviewed source fidelity and product-owner acceptance remain |
| Discovery maintenance | Deterministic paginated PIT replacement snapshots with time/generation, bounded top-30 state and periodic rebuild | Local/engine coverage; five-minute refresh at scale remains unqualified |
| Operational observability | EMF counters/latency, lag/readiness/reconciliation alarms and a deployment dashboard | Telemetry added; deployed delivery, model-cost/feed-lag and alarm verification remain |
| Packaging and documentation | Worker/proxy builds and source manifest; documentation update underway | Rebuild final artifacts, verify clean packaging, complete runbooks/link checks |
| GitHub deliverable | Dedicated `feat/exact-ingredient-search` worktree; application base retained; branch tips rechecked on 2026-10-27 | No commit, push or PR yet; explicit commit approval and organization SSO access required |

The application change is not declared complete by this checklist. Outstanding
items are work to finish, not waived requirements. No merge to main is authorized.

The application base advanced to `4a90fc5099d03c775aed303f9b6c8fceeef8154c`
during this work. The feature branch was fast-forwarded to that existing
documentation commit without creating a new commit. All other uncommitted file
hashes were preserved. Its four image files were retained byte-for-byte, while
README/architecture prose was reconciled with exact selection and its additional
private infrastructure. The reference illustrations still require a future
approved update to depict these extensions.

## Deployment inputs

The approved target is the explicitly selected qualification account in
eu-west-1, with a USD 200 total ceiling. The account/profile are retained in the
private run manifest. See [the budget record](qualification-budget.md).
Production cost ceilings, representative source/identity evidence, reviewed
profile cases, acceptance owner and operating owners must be recorded before
the corresponding gates can pass. Existing local research does not establish
those inputs.
