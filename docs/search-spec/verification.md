# Verification and release evidence

Version 2.0, 2026-10-26. Verify the exact matching contract in
[technical.md](technical.md), using the proposed limits in
[acceptance-targets.yaml](acceptance-targets.yaml). Freeze deployment targets and
test populations before release qualification.

## 1. What is already established

| Evidence | Established result | Boundary |
|---|---|---|
| Public ingredient study | 6,000 requests; both indexed variants matched every ordered exhaustive top-100 result | Generated requests over public records, not independently judged clinical suitability |
| Ranking ablation | Filtered exact harmonic lost attainable top-three matches on 1,807 requests | Supports the agreed count objective; not a clinical ranking metric |
| Finite eligibility audit | 486 requests over 2,847 generated records; zero oracle/engine differences | Finite predicate matrices, not customer feed validation |
| Million-record synthetic check | 360 complete top-100 ID/score oracle comparisons; zero differences | Engine component on an engineered distribution |
| Local capacity screen | Six cells; 151,256 measured requests; zero failures/late responses; p95 16.95–19.84 ms | 30-second warmup/180-second cells; no canonical reads, agents, AWS topology or deployed qualification |

The [decision report](decision-evidence.md) identifies
source hashes, complete run artifacts and limitations. Preserve these regressions.
The search decision does not require another shopping-text/embedding study.

## 2. Functional and integration verification

### T01 — Contracts and constraint propagation

- Accept legacy photos-only v1 and bounded v2 preferences; reject unsupported
  versions, fields, IDs, family references, negative/noninteger prices and oversize
  payloads consistently at proxy/runtime boundaries.
- Resolve approved same-identity aliases; reject unknown/ambiguous hard input.
- Enforce total/per-category bounds, unique categories and required/excluded
  conflicts. A must-have applies only to its named step; an exclusion applies to all.
- Detect a required category missing from the generated plan. No hard constraint
  disappears during graph propagation.
- Remove excluded soft preferences before computing the denominator; empty plans
  fail explicitly. Legacy `required_ingredients` map to preferences.
- Catalog scope, generations, deadlines, weights and DSL cannot come from user or
  model-controlled fields.

### T02 — Identity, eligibility and exact score

Use an independent set-based oracle, not the production query builder:

`eligible(p, request) and len(preferences & ingredient_ids(p)) > 0`, ordered by
`(-intersection_count, product_id)`.

Cover exact aliases versus distinct ingredients/derivatives, duplicate inputs,
reordered lists, required IDs outside preferences, multiple simultaneous must-haves,
exclusions, incomplete/unresolved lists and equal-count ties. Test unknown/boundary
prices, currencies, market, availability, active/deleted state and schema/taxonomy.

Run `catalog` and `purchasable` modes separately. Unknown stock must not become an
in-stock claim. With exclusions, either incomplete flag makes the record ineligible.
Ingredient order and unrelated text/frequency changes must not change scores.
Adding a hard constraint cannot expand eligibility. Adding a duplicate preference
cannot change scores or percentages.

### T03 — Actual engine query and bounded selection

Against the pinned managed engine version, compare complete ordered top-100 IDs
and scores to exhaustive reference over the same full snapshot. Include every
eligibility slice, rare/common ingredients, ties spanning shards, zero matches,
one/two matches, exactly 100 and more than 100 matches.

Assert one constant-score clause per preference, an AND of must-have terms,
`minimum_should_match=1`, stable ties and no boost/text/script contribution.
Do not use a mocked query as the only evidence. An equivalent keyword-term query
is a count implementation, not a BM25 relevance baseline.

Validate shard failures, timeouts, malformed IDs/scores, wrong generations and
truncated transport responses. A partial/error response cannot establish no-match.
Check at most 100 distinct hit IDs, initial read of at most ten, one refill and
three final products. No search pagination or category fallback.

### T04 — Ingredient discovery and readiness

Prohibit runtime product `Scan`/category enumeration using repository spies and
deployed role/traces. Test `has_products()` replacement, category summaries and
exact registry lookup together.

A rare resolved ingredient absent from the common summary remains selectable.
Stale zero counts are advisory; they cannot preclude a valid product query.
Verify discovery call/entry limits, correct namespace/taxonomy, deduplication,
replayed aggregation, summary replacement and missing registry error behavior.

### T05 — Canonical hydration, changes and binding

- Unordered batch results bind by ID; unprocessed, absent, deleted and throttled
  records are distinct. Unresolved higher-ranked records cannot be skipped.
- Initial ten contain fewer than three survivors; one refill succeeds, returns a
  shorter list or exhausts the original 100 IDs within the deadline.
- Newer price/stock/ingredient/category facts invalidate changed matches. A
  display-only change with unchanged matching hash uses current facts.
- All bounded candidates disappearing yields `catalog_changed`, not a claim that
  the catalog has no matches. On static synchronized data, final IDs equal exact top three.
- The model cannot select a subset, reorder/add IDs, reuse another request/step,
  or overwrite price, image, matched IDs or match counts.
- Final reads cover at most 24 selected products; invalid products/explanations
  are removed without a new search loop. Failed reads produce errors.
- Public facts and generated text are checked independently. Final-read timestamps
  do not imply atomic inventory reservation.

### T06 — Publication, replay and generation recovery

Exercise insert, rename, category change, price/stock change, delete, reactivation,
duplicate/out-of-order events and equal-revision conflicting bodies. Verify stable
IDs through the legacy migration map.

Inject a crash before/after each canonical/outbox transaction, lease, bulk item
acknowledgement and delivery-state update. A committed canonical update must leave
recoverable publication work. Test pending-index propagation delay, expired worker
leases, repeated summaries, partial bulk failures and poison records.

Compare canonical/outbox/index state to a revision oracle. A late event cannot
overwrite a newer revision or resurrect a deleted record. Pending events cannot
expire. Retention/high-water marks cover every replay and rollback horizon.

Build under concurrent updates, replay, reconcile and cut over; interrupt between
alias and manifest publication and recover safely. Keep in-flight routines on their
generation. Update the retained generation and roll back under live changes. A
stale retained index or capture gap must not become healthy by assertion.

### T07 — Deadlines, overload and cancellation

Inject real search/auth failures, slow/unavailable shards, partial canonical reads,
throttling, stale health records, feed gaps and model explanation failure. Assert
public outcomes and trace reasons, including no-match/error separation.

Count nested SDK attempts in the one-retry step budget. The refill is one planned
read, never an unbounded loop. Measure scheduled-arrival latency, including queueing.
Reject bounded overload visibly; normal-load rejection counts against capacity.
Cancellation must stop supported work and prevent stale callbacks/state mutation.
Factual explanation fallback preserves approved facts and adds no unsupported advice.

### T08 — Graph, SSE, compiler and browser

Test mixed matched/no-match, all-no-match, missing step, omitted required category,
malformed plan, model-added product, failed final reads, stream closure and cancellation.
A failed step cannot become an apparently successful empty routine.

Exercise real v1/v2 boundary serialization and browser parsing. Valid v1 remains
compatible; v1 no-match is a terminal domain error; v2 terminates each step visibly.
Reset/sign-out/unmount abort stale work. Measure first-step-outcome/final-routine latency
from request admission and browser observations, not summed node durations.

Every public product fact must match the server-bound record. Verify the reviewed
routine constraints independently of the ingredient-count metric. Model explanations
cannot imply concentration, efficacy or stock from match percentage.

### T09 — Authorization and isolation

Verify anonymous/wrong-role denial, private reachability, native TLS/IAM signing,
read-only runtime search permissions and bounded canonical/discovery access. Runtime
cannot write documents, manage aliases or scan categories. Verify required runtime
service connectivity after switching to VPC networking.

IDs, caches, configuration and invocation state cannot cross catalog/request/step
boundaries. Index documents contain no photos or user profiles. Test the authenticated
registry/options endpoint's limits and authorization as well as product search.

### T10 — Packaging, deployment and rollback

New runtime modules/configuration must enter the source manifest and image hash;
experiments/datasets must not. Test clean packaging after file deletion. Provision
private search/ingestion before enabling the adapter. Mapping/taxonomy changes
create a generation and require relevant regressions.

Keep v1/v2 compatibility through rollback. Rehearse unavailable handling if no
healthy generation exists. No rollback to the old unbounded substring scorer.

## 3. E01 — Data and planning validation

Keep three independent acceptance questions:

1. **Matching conformance:** exact oracle equality on a fixed normalized snapshot.
   Requires no human relevance labels or model-based nDCG ranking experiment.
2. **Data fidelity:** verify a customer/public feed sample against its source,
   including stable IDs, ingredient parsing, approved aliases and completeness.
   An unresolved mapping is an explicit data limitation. Do not fabricate fields
   to make a benchmark pass.
3. **End-to-end product behavior:** review ingredient choices, hard-constraint
   preservation, explanations and routine presentation with the product/domain
   owner. Search conformance cannot establish the quality of upstream choices.

For customer release, start with at least 100 distinct representative profiles/
preference cases spanning supported categories and critical data conditions,
plus explicit adversarial contract cases. Freeze the rubric and sample before
acceptance review. Every required critical scenario must be covered; expand the
sample when gaps or unstable behavior appear. This is a proposed functional
acceptance sample, not a statistical efficacy or medical-safety study.

Require zero observed hard-constraint/catalog-fact violations and a documented
product-owner acceptance of planner/explanation behavior. Any unsupported claim
must be fixed or removed. Do not substitute ingredient overlap for independently
reviewed benefit judgments. Domain-policy definitions are an input to application
acceptance, not a reason to change exact ingredient identity or count ordering.

## 4. P01 — Deployed capacity

### Environment and workloads

Qualify the intended AWS Region, private network, supported engine/client versions,
shards/replicas, canonical store, runtime artifact and model quotas. Capture the
load generator's own saturation. Test catalog checkpoints at 1k, 10k, 100k and 1m.
The million-record gate includes representative category skew, ingredient frequency,
missing fields, record sizes and ties. Synthetic extensions must disclose their
generator and limitations; copying a small fixture is insufficient.

Measure three boundaries separately:

| Boundary | Required workload |
|---|---|
| Engine query | 120 and 160 searches/second; useful component diagnosis |
| Application search | Same rates, including readiness, real canonical reads/refill and binding |
| Full application | 20 routines/second, six typical/eight maximum steps, real planning/discovery/explanation/finalization and SSE |

Full routines generate correlated per-step bursts. Use enough authenticated test
users for current per-user concurrency limits; do not disable production controls
to manufacture throughput. Measure discovery, initial/refill/final reads and model
calls, not just nominal product-search requests.

### Procedure and gates

Use scheduled open-loop arrivals and record offered/admitted/completed/rejected/
timed-out requests. Latency starts at scheduled arrival, including generator and
application queueing. Report engine service time separately. Failed/unfinished
requests remain in denominators; quick successes alone cannot define a passing p99.

For each required release configuration and target-load cell, warm up at least
15 minutes, measure at least 30 minutes and run three independent repetitions.
Every repetition must pass; do not average away a failure. Freeze the query mix
from YAML, and additionally report customer-distribution results if it differs.
No result-cache hits in gating runs.

Required steady-state targets:

- Application step search: p95 ≤500 ms, p99 ≤1,000 ms; 1,200 ms hard deadline;
  failed/late/rejected fraction ≤0.1%.
- Full routine: first step outcome (products or explicit no-match) p95 ≤30 s;
  completion p95 ≤60 s and p99 ≤90 s;
  hard completion deadline 120 s; operational failure fraction ≤1%.
- Valid completed routine fraction ≥99%; valid no-match counts as a completed
  domain outcome and its rate is reported separately.
- SSE silence ≤15 s using progress/heartbeat events, not invented progress.

Run a four-hour nominal-load soak with updates. Exercise a five-minute burst at
40 routines/second; bounded rejection is allowed during overload, with recovery
to nominal gates within five minutes. The ordinary-load gate cannot reject traffic
to produce good latency. Sample output invariants throughout all runs.

## 5. P02 — Freshness, faults and rebuild

Run 100 updates/second alongside serving, plus 1,000/second for five minutes.
These are proposed qualification rates, to confirm against the customer feed.
Measure source-to-canonical and canonical-to-search visibility separately; use
per-revision visibility probes rather than bulk-acknowledgement time.

Targets: search visibility p95 ≤30 s; unresolved lag alarm at 60 s; reject an affected
generation at 300 s or unknown capture/health state. Daily reconciliation and a
complete million-product rebuild within 12 hours include catch-up and validation.
Discovery summaries may be advisory/stale but must expose their time/generation.

Inject worker/search-node/AZ dependency failures supported by the deployment,
queue/lease stalls, throttling and feed interruption. Verify denial and recovery
outcomes, no stale-over-new writes and no resurrection. Rehearse generation/config
rollback within five minutes while serving updates and in-flight routines. Retain
per-generation publication evidence; configuration pinning alone is insufficient.

## 6. P03 — Cost and operational acceptance

Record measured index resources/storage/replicas, DynamoDB reads/writes/outbox,
background workers, discovery, private networking, logging and existing agent/model
usage. Include failed work, retries and explanation fallbacks. Report:

- Total cost per 1,000 valid completed routines and the no-match share.
- Monthly fixed infrastructure at the measured configuration.
- Update/rebuild cost separately, with volume assumptions and pricing date.

Do not extrapolate cloud cost from the laptop benchmark. Customer cost ceilings
must be populated before release approval. Dashboards/runbooks need named owners,
alert thresholds and rollback verification steps.

## 7. Evidence and definition of done

Every qualification run records source/code/patch hashes, corpus/query checksums,
configuration, actual resources, environment/version, raw events, failures and
completed artifacts. Recompute counts/percentiles from raw records and reconcile
every offered request. Preserve failed runs with reasons.

Research is complete. Implementation acceptance requires T01–T10, customer data/
product validation, and the applicable P01–P03 deployment gates. The local study
is reusable evidence, not a substitute for these new integration boundaries.

### Documentation check

On 2026-10-26, Context7 supplied official OpenSearch keyword, Boolean, constant-score,
Search API and external-version/Bulk API documentation. The AWS documentation MCP
timed out; official AWS BatchGetItem, DynamoDB transactions, OpenSearch VPC/FGAC and
AgentCore VPC pages were then fetched and read directly, along with OpenSearch's
alias API. Links are in [technical.md](technical.md#11-official-implementation-references).
No Strands/AgentCore SDK code was written for this specification; verify their
current SDK docs and official code examples before implementing graph changes.
