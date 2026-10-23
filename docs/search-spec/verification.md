# Testing and evaluation strategy

This document defines evidence required to implement and release the
[technical specification](technical.md). Numerical defaults live in
[acceptance-targets.yaml](acceptance-targets.yaml). Freeze targets, rubric,
configuration selection rules and dataset splits before confirmatory evaluation.

## 1. Evidence levels and limitations

| Evidence | What it establishes | What it cannot establish |
|---|---|---|
| Unit/property tests | Deterministic rules, invariants, metrics and error handling | Relevance, service configuration or production capacity |
| Local synthetic profiles/catalog | Harness behavior, reproducible regressions | Best customer method, real suitability, million-product latency |
| Real engine integration | Query/filter/version/authorization behavior of the selected engine | High-load behavior without a load test |
| Public product benchmark | Broader retrieval behavior on actual product-query data | Skin-profile or routine suitability |
| Independent customer/profile judgments | Recommendation relevance for the covered population | Unmeasured populations, photo-model accuracy or infrastructure capacity |
| Deployed load and fault tests | Performance/recovery under the specified corpus, configuration and workload | Other hardware, traffic distributions, regions or models |
| Controlled customer rollout | Observed operational and user outcomes | Unmeasured safety properties or causal efficacy |

Keep the existing 24 cases as regression fixtures. Do not turn their current
scores into a release gate. The current local runner's 10k cap is not removed to
simulate a production implementation; production adapters execute against the
full index.

## 2. Test layers and execution

### T01 — Public contracts and trusted context

Required cases:

- Existing v1 photos-only requests and valid v2 preference requests work.
- Unknown keys, oversized lists, unknown schema versions, malformed amounts,
  missing price currency, invalid IDs and incompatible hard constraints fail.
- The proxy and runtime validators agree on accepted/rejected payloads.
- Market/catalog scope cannot be supplied through an LLM result, forged header,
  query text or arbitrary request field.
- User-provided exact exclusions survive every graph transformation unchanged.
- Budget/ingredient preferences are never inferred from images.
- Same user/request/step identifiers do not authorize another user's state.

Evidence: table-driven request tests at proxy and runtime boundaries, real
authenticated integration tests and recorded contract-version compatibility.

### T02 — Ingredient semantics and eligibility

Use a small exact oracle catalog with deliberately adversarial records.

- Normalize case/whitespace without double counting.
- Exact ingredient, alias and family expansion have distinct expected outcomes.
- An exact match does not match an arbitrary derivative through substring overlap.
- Missing/unknown price, currency, stock, market or incomplete ingredient lists
  fail the constraints that depend on those facts.
- Requirements and exclusions conflict deterministically; hard exclusion wins
  over soft preference.
- No semantic score or LLM output overrides an ineligible product.
- Filter predicates agree between BM25, ANN and canonical revalidation.
- A filter excluding all records, one eligible record, and fewer than k eligible
  records each produce the specified outcome.
- Boundary values: zero price, equal-to-budget price, one minor unit over budget,
  explicit unavailable state, tombstone and updated category.
- Metamorphic checks: adding a hard constraint cannot expand eligibility;
  increasing a price cap cannot remove eligibility; renaming a product does not
  change its ID; input list order does not change hard constraints.

Compare engine results to exhaustive eligibility, not only a mocked query builder.
Run against the selected engine/version in CI or a controlled integration
environment.

### T03 — Retrieval, fusion and bounded execution

- Verify approved templates, analyzer settings and independent lexical/vector
  candidate counts.
- A relevant rare-ingredient item outside the old top-frequency vocabulary remains
  retrievable.
- RRF hand examples verify rank-based fusion and deterministic tie behavior.
- Different branch score scales do not affect rank-fusion semantics.
- Candidates are deduplicated by canonical ID, not display name.
- Hydration, rerank and selected pools stay within limits, including refill.
- Confirm bounded work after fewer eligible items survive hydration.
- Spy/prohibit DynamoDB `Scan` and category-wide `Query` from production search
  requests; confirm through deployed traces and IAM where practical.
- Partial shards, timeouts and missing branch results follow qualified fallback
  behavior; partial results never silently count as success.
- Query/embedding/metadata cache keys include all context/version fields.

### T04 — Ingestion and catalog correctness

Use ordered, duplicate and deliberately out-of-order event sequences. Include:

1. Insert, rename, category change, price change, market/availability change.
2. Update while an old embedding job is running.
3. Delete before an old update/embedding completes.
4. Duplicate insert/update/delete and replay after worker restart.
5. The same source revision with different contents: reject and alarm.
6. Poison record and partial bulk acknowledgement.
7. Snapshot while products are changing; capture/catch-up boundary.
8. Simulated stream-retention gap: detect invalid completeness and rebuild.
9. Journal replay after seven-day retention boundary.
10. Missing vectors, wrong dimension/model revision, incomplete taxonomy mapping.
11. Index refresh delay, source revision mismatch and reconciliation differences.
12. Atomic cutover, in-flight routine generation pinning, retained-generation
    updates and rollback without record resurrection.

For each sequence, compare canonical products, projection state and indexed
state against the revision oracle. Require convergence within the declared
freshness window and zero stale-over-new overwrite events.

### T05 — ANN/filter integration

- Test efficient filtering on every supported ANN method/configuration.
- Exercise filter selectivity near 100%, 10%, 1%, 0.1%, fewer than k and zero.
- Separate precomputed vectors with missing/stale metadata from healthy records.
- Verify reported exact fallback versus ANN execution under restrictive filters.
- Apply canonical revalidation after retrieval and measure lost candidates.
- Check deterministic exact-neighbor ground truth against returned candidates.
- Re-run when engine version, quantization, dimension, HNSW parameters or shard
  topology changes.

### T06 — Hydration and explanation binding

- Batch responses arriving out of order bind by ID.
- Unprocessed keys, missing keys and actual deleted products remain distinct.
- Canonical price/stock/ingredients override old indexed facts.
- Same product name in different scopes cannot cross-bind.
- The product agent cannot add IDs, reorder selections, reuse another step's
  result or modify price/image/match metadata.
- All generated text refers to the currently bound record.
- Product deletion/change between search and final serialization is caught.
- Removing the entire selected set after successful canonical checks produces
  `catalog_changed`; failed reads still produce an error.
- Template fallback has only source-grounded statements and no invented usage
  advice.
- A model-generated URL cannot bypass the existing safe-image policy.

### T07 — Failure, deadlines, retries and cancellation

- Query embedding timeout, ANN timeout, reranker timeout and throttling.
- Lexical/index unavailability, canonical-store failure and unresolved batch reads.
- Stale-ingestion health signal and configuration/index mismatch.
- Service error versus valid no-match: every failure path preserves the distinction.
- Retry and refill caps include nested SDK retries; total elapsed time respects
  the original deadline.
- Fallbacks preserve all eligibility constraints and configured minimum quality.
- Circuit breakers recover; overload does not create multiplying retries.
- Cancellation before search, during inference and during finalization releases
  work and prevents late outputs from mutating another request.

Fault tests must assert actual public outcomes and trace reasons, not just that
an exception was raised somewhere.

### T08 — Graph, SSE, compiler and frontend

- Mixed matched/no-match routines compile; missing/failed steps do not.
- All-no-match is explicit and does not claim a useful product routine.
- No-match messages explain the relevant constraint without exposing engine names
  or internal implementation details.
- Browser loading state terminates for matched, no-match and error outcomes.
- v1 matched responses preserve shape; v1 no-match terminates through the domain
  error adapter. The compatibility browser renders the new code, and older cached
  browsers retain their documented generic-error fallback.
- Partial events, stream closure, sign-out, reset and cancellation do not create
  a false final routine.
- Supported two-to-eight-step graphs preserve ordering and status.
- Whole-routine exclusions, catalog scope and reviewed compatibility rules hold.
- Explanation lag does not let stale canonical facts bypass final revalidation.
- First-product, final-routine and SSE-silence timers are measured from the actual
  browser/request boundary.

### T09 — Authorization and data isolation

- Anonymous and wrong-role requests to search/index administration fail.
- Search runtime cannot index documents or mutate aliases.
- Ingestion role cannot expose profiles or invoke unrelated application APIs.
- One customer/deployment cannot resolve another's IDs or cached candidates.
- Private endpoints are unreachable from an untrusted network.
- Runtime private connectivity still reaches required image, logging, canonical
  store and model services.
- Captured product documents/vectors contain no photos or user identifiers.
- Trace/judgment storage access and retention follow the configured data policy.

Only approved restricted test fixtures are uploaded after access controls are
verified. Local integration services bind to loopback or unpublished private
container networks.

### T10 — Packaging, deployment and compatibility

- New runtime modules and configuration enter the image manifest/hash.
- Experiments, customer judgment data and model caches do not enter the runtime
  artifact accidentally.
- Deployment provisions search, ingestion and inference dependencies before
  switching the runtime.
- IAM includes bounded canonical reads without index-write privileges.
- A schema/model update creates a new generation and cannot be enabled against
  an incompatible mapping.
- Rollback preserves v1/v2 request and stream compatibility.
- Destroy/recreate drills in an isolated test environment preserve protected
  source data and clearly identify disposable derived indexes.

### T11 — Metrics and evaluator correctness

- Verify linear nDCG by hand-calculated examples, ties and short lists.
- New binary relevance metrics use grade ≥2. This explicitly differs from the
  current fixture harness's grade >0 definition.
- Missing queries, duplicate IDs, mismatched snapshots, incomplete run files,
  nonfinite scores and unknown products fail validation.
- Empty results on answerable queries cannot inflate quality metrics.
- Candidate recall, hydrated-pool recall and rerank-pool recall are distinct.
- Unjudged products remain visible; they are not silently dropped from ranking.
- Profile-cluster bootstrap keeps all steps and repeated model runs together.
- Errors, timeouts and rejected offered load cannot disappear from latency or
  completion denominators.
- Pricing inputs, inference usage and fixed-cost allocation reconcile to the
  experiment's measured resource period.

## 3. E01 — Datasets and independent judgments

### 3.1 Required dataset tracks

1. **Engineering fixtures:** existing fictional catalog plus targeted edge cases.
2. **General product retrieval:** a public product benchmark such as
   [Amazon ESCI][E01], subject to its data terms, useful for broader retrieval
   behavior. Its shopping queries do not establish skin-profile suitability.
3. **Customer recommendation evaluation:** representative normalized customer
   catalog and independently reviewed skin profiles/preferences.
4. **Full pipeline:** consented, suitable image/profile cases to evaluate the
   existing photo-to-profile path and the final routine.

Index the full corpus for retrieval. Evaluation judgments can be a pooled subset,
but must not shrink the searchable corpus to known answers.

The one-million-product capacity corpus must have realistic category skew,
ingredient frequency, description lengths, missing attributes, price/stock churn,
languages and near-duplicate variants. Duplicating 48 rows is not acceptable.
Generated records are permitted for load mechanics when their limitations are
explicit, but do not provide recommendation relevance evidence.

### 3.2 Profile sampling and leakage control

Start with 200 development and 200 frozen test profiles. This is a planning
volume, not a guarantee of statistical power. Sample at the profile/user level:

- Common and rare concerns and combinations.
- Product categories and two-, six- and eight-step routines.
- Budgets, exclusions, hard requirements and conflicting preferences.
- Broad, restrictive and known-impossible eligibility.
- Relevant supported languages/markets and ambiguous ingredient terms.
- Missing/uncertain profile facts and unanswerable requests.

Split by user/session and near-duplicate intent family. Keep a temporal holdout
where feeds evolve. Use the full supported population's proportions for the
primary estimate and deliberately oversample critical slices for separate checks.
Report any reweighting.

Do not write test queries after observing candidate failures, tune on test scores,
or use the same LLM to generate queries, expected answers and judge its outputs.
Adversarial cases discovered later go into a new regression set; preserve the
original confirmatory test result.

### 3.3 Rubric

Domain reviewers define suitability from the stated profile, constraints,
source-backed product facts and a versioned policy. Ingredient overlap is one
feature, not the grading oracle.

| Grade | Meaning |
|---:|---|
| 0 | Ineligible, contradicted by available evidence, or unsuitable for the stated request |
| 1 | Eligible but weak/marginal match |
| 2 | Good supported match |
| 3 | Excellent supported match |

Separately annotate: hard-constraint violation, insufficient source evidence,
policy conflict, exact no-match certification, explanation claim support and
routine compatibility. Reviewers can mark `unjudgeable`; do not force missing
evidence into an invented positive/negative label.

### 3.4 Pooling and review

- Pool the top 20 or more from every competing method, including both retrieval
  and reranking variants. Add known positives, exact-ingredient candidates and
  sampled hard/random negatives.
- Deduplicate by product ID; randomize order and hide originating method/rank.
- Review at least 25% independently twice; adjudicate material disagreements.
- Time a small pilot and revise the reviewer effort estimate accordingly.
- Require at least 99% judgment coverage of each candidate system's top 10 before
  making a confirmatory comparison.
- New methods retrieving unseen items require pool expansion and consistent
  rescoring of every method against the same new qrels snapshot.
- Record inter-reviewer agreement, disagreements and rubric revisions. Poor
  agreement pauses method selection until the rubric/evidence issue is resolved.

An LLM can propose labels or prioritize review but cannot be the sole release
judge. Display its role in provenance. No-match certification requires exhaustive
eligibility evidence or a dedicated reviewed case; absence of a positive in a
partial pool is not proof that no match exists.

### 3.5 Example profile and query cases

These are specification examples for fixture construction, not prewritten
customer relevance judgments or medical advice. A domain reviewer supplies the
expected relevant products from source evidence. The full query set must include
independent customer cases.

| Case | Profile/request context | Explicit input or catalog condition | What the evaluation must establish |
|---|---|---|---|
| Q01 | Dryness concern; moisturizer step | France, EUR, maximum 3,000 minor units per product | Useful eligible recommendations; exact budget boundary and currency enforced |
| Q02 | Combination skin; lightweight-texture preference | Hard exact-ingredient exclusion plus soft texture preference | Exclusion survives planning; semantic similarity cannot override it |
| Q03 | Sensitivity concern with uncertain profile facts | An excluded ingredient and incomplete ingredient lists | Unknown constrained products fail eligibility; no invented suitability claim |
| Q04 | Skin profile plus a user-requested rare ingredient | Valid exact ID present in only a few eligible products | Retrieval is not limited to the old 30 most frequent ingredients |
| Q05 | Otherwise ordinary profile | Same exact ingredient both required and excluded | Validation rejects the conflict before retrieval |
| Q06 | Moisturizer request | Oracle proves zero products meet market and price constraints | Correct explicit no-match; healthy-index existence check, no padded result |
| Q07 | Restrictive request | Oracle has exactly two eligible, well-supported products | Return two; do not pad with an irrelevant third product |
| Q08 | Same profile in a supported second language | Equivalent meaning and identical explicit constraints | Measure language-specific relevance and constraint preservation |
| Q09 | Six-step routine with mixed categories | Some steps answerable, others certified no-match | Per-step states remain correct; whole-routine review evaluates the result |
| Q10 | Otherwise answerable request | Price/stock changes after initial retrieval | Final canonical validation excludes stale ineligible selections |
| Q11 | Same request across an index update | Product renamed without changing supplier identity | Stable identity, no duplicate recommendation, reproducible generation record |
| Q12 | Ambiguous ingredient name | No approved exact alias resolution | Clarify/reject the unresolved hard constraint; no substring guess |

## 4. E02 — Controlled retrieval and ranking comparison

### 4.1 Configurations

| ID | Configuration | Purpose |
|---|---|---|
| B0 | Current category/harmonic scorer on tractable data | Historical behavior; never the only quality baseline |
| B1 | Production indexed lexical/ingredient baseline with all hard filters | Required scalable reference and fallback |
| B2 | Filtered ANN with the same model/text/eligibility contract | Measure semantic retrieval independently |
| B3 | B1 + B2 with RRF | Measure hybrid contribution |
| B4 | B1 candidates + cross-encoder | Separate reranker value from ANN value |
| B5 | B3 candidates + the same cross-encoder | Combined candidate system |

Listwise reranking, learned sparse retrieval and learned-to-rank can be later
experiments. They are not required to ship the first qualified baseline.

Freeze input product text, taxonomy, eligibility, profile planner and model
revisions across comparisons. Hold candidate pools fixed when comparing
rerankers. Record ablations for normalization, filters, ingredient weighting,
ANN and reranking so a gain is attributable.

On development data, sweep:

- Retrieval depth 25/50/100/200 and rerank depth 20/50/100.
- Two or three plausible embedding models, at least one small inexpensive baseline.
- At least two compatible rerankers or one reranker plus none.
- Engine-supported ANN search effort/graph parameters and compression modes.
- Fusion weights/constants and qualified relevance/abstention thresholds.

Use staged elimination; do not run every possible Cartesian combination at full
scale. Qualify the lexical baseline, shortlist quality contenders, then load-test
the contenders. Freeze one candidate for the confirmatory comparison to B1.

### 4.2 Metrics and definitions

| Metric | Required definition |
|---|---|
| nDCG@3 | Linear gain from grades 0–3; compute per answerable step, aggregate steps within each profile, then macro-average profiles |
| P@3 | Products with grade ≥2 divided by three; short lists retain denominator three |
| MRR@10 | Reciprocal position of first grade ≥2 result |
| Candidate recall@100 | Fraction of known grade ≥2 products present in the first 100 fused candidates, before hydration/reranking |
| Fraction of attainable recall@100 | Known relevant hits divided by `min(100, number of known relevant products)`; used for the candidate gate so a query with more than 100 positives has an achievable ceiling |
| Hydrated/rerank-pool recall | Same known relevant set measured after each reduction stage |
| Constraint violations | Counts and rates for all returned products and any-violation routines; no dilution by empty results |
| False abstention | No-match on independently answerable cases |
| Correct no-match abstention | No returned products for independently certified no-match cases |
| Unjudged coverage | Per-method top-k fraction with no reviewed label |
| Routine appropriateness | Reviewed whole-routine result, distinct from mean per-step ranking |
| Explanation grounding | Supported factual claims / all factual claims, with critical errors separately counted |

The primary gain function is consistent with [trec_eval's linear nDCG][E02].
Use [BEIR-compatible data/run conventions][E03] where possible; record deviations
such as the grade ≥2 binary threshold and profile-level aggregation.

Pooled recall is recall of **known** relevant products. It is not absolute recall
of every relevant product in a million-product catalog. Include an audit set with
exhaustively judged tractable categories/eligibility sets and a targeted search
for missed positives.

Report both ordinary candidate recall and its fraction of the attainable ceiling,
with the known-positive count. Queries with no known positives have no recall
denominator and belong in the separately certified no-match/unjudged analysis.
For each pool-reduction stage, report its own depth and attainable ceiling.

Primary metrics retain unjudged items at their returned rank with gain zero; they
are not treated as reviewed negatives in the judgment dataset. Report sensitivity
to unresolved labels, including optimistic gain bounds. If unresolved labels can
change the release decision, complete their review before promotion. Calculate
IDCG from the shared frozen judgments, with the linear gain convention.

In the frozen-snapshot quality run, unexpected `catalog_changed` is a consistency
failure. In live churn tests, count it separately and evaluate coverage against
the canonical state at final validation; do not silently discard those routines.

### 4.3 Statistical decision rule

Every candidate, including B1, must first pass absolute proposed quality floors:

- Profile-macro nDCG@3 at least 0.75 on independently answerable steps.
- Critical-slice nDCG@3 at least 0.65.
- At least 95% of independently answerable steps contain a grade ≥2 product in
  the top three.
- At least 90% of reviewed full routines meet the customer-approved routine
  acceptance rubric, with zero observed critical policy/constraint violations.

These floors apply to observed point estimates; also report confidence intervals
and denominators. The routine rubric
must require useful coverage of answerable steps and supported explanations;
empty routines cannot pass by merely avoiding violations. These starting numbers
are product targets to accept or revise at G0, not externally established standards.

Use a 10,000-resample paired bootstrap at the profile level with seed 17. Preserve
all steps and repeated model runs within a resampled profile. Report the mean
difference, 95% interval, profile count, slice counts and missing/failed runs.

Initial noninferiority gate for a release candidate: lower 95% bound of nDCG@3
delta versus B1 must be at least −0.02, with no critical-slice breach.

To enable an optional expensive stage by default, require:

- At least +0.02 absolute nDCG@3 point improvement over its parent configuration.
- Paired 95% interval lower bound above zero.
- Candidate recall, critical-slice, constraint, abstention, serving and cost gates.

This is a proposed product decision rule. It can be changed at G0, not after
observing confirmatory results. If no optional contender passes, ship B1 only if
B1 passes the absolute quality, correctness, serving and cost gates. If B1 also
fails, there is no release-qualified method yet.

Estimate sample size from pilot paired-profile variance and the smallest useful
effect. As an illustrative approximation, detecting a 0.02 effect with 80% power
at a two-sided 5% level needs about 196 profiles when paired standard deviation
is 0.10, or about 441 when it is 0.15. Confirm with the observed distribution and
planned statistical procedure; do not count six steps as six independent users.

Report critical slices with at least 30 independent profiles or label them
insufficiently measured. Correct for multiple comparisons if confirmatory claims
are made for several candidates; development sweeps are exploratory.

Zero observed constraint violations is a required gate, not proof that the true
violation probability is zero. Report the exposure count and an appropriate upper
confidence bound, accounting for profile clustering.

## 5. E03 — Profile-only and full-routine evaluation

Two modes are mandatory:

1. **Controlled search:** fixed validated profiles and ingredient/query targets.
   Isolates retrieval/ranking effects.
2. **End-to-end planning:** profile and explicit user preferences only. The real
   planner selects steps/ingredients and search executes normally.

Run the second mode with three fixed model seeds/configured repeated runs where
supported; if a provider does not expose seed control, capture three independent
runs and document that limitation. Repeated calls do not increase the number of
independent profiles.

Evaluate missed useful ingredients, invented hard constraints, premature
availability restrictions, inappropriate step selection, repeated/contradictory
products, unsupported explanations and unstable recommendations. Trace every
failure to profile extraction, planning, retrieval, ranking, binding or presentation.

Then run a separately reviewed image-to-routine subset through the actual browser/
API path. This measures the contribution of the current vision model. A search
release must not claim to repair an unmeasured photo-model error.

## 6. E04 — ANN accuracy

Approximation accuracy and recommendation relevance are different measurements.

For a sampled query set, compute exact cosine/dot-product neighbors against the
**same full filtered vector corpus** used by ANN, with identical embeddings,
normalization and eligibility predicates. Chunking/offline acceleration is allowed.
Sampling the queries is acceptable; replacing the full document collection with
a small easy subset is not a valid full-index ground truth.

Measure exact-neighbor recall@100, plus relevance recall@100, for each selectivity
slice. Default target: ANN exact-neighbor macro recall at least 0.95. Report cases
where the eligible set has fewer than 100 products using its actual size.

Measure memory, graph/index size, build time, vector dimensionality, compression,
search effort, filter fallback and latency together. An ANN configuration with
excellent neighbor recall can still retrieve irrelevant skincare products.

## 7. P01 — Serving capacity and latency

### 7.1 Test environment

Use the intended cloud region, private networking, authentication, index engine,
canonical store, model endpoints and runtime artifact. Pin hardware, topology,
quotas and scaling rules. Give the load generator enough independent capacity
and capture its own saturation.

Reference checkpoints: 1k, 10k, 100k and 1m active products. Qualify the 1m case;
10m is a separately budgeted extension. Include realistic skew, hard negatives,
long descriptions and imperfect but explicitly represented metadata.

### 7.2 Workload

Test both:

- Search-only offered load at 120 step requests/second and the eight-step
  equivalent of 160/second.
- Full routines at 20/second, generating correlated per-routine step bursts rather
  than only unrelated independent search queries.

Use enough distinct authenticated test users to respect the existing per-user
active-analysis limit. If mean routine lifetime were 40 seconds, 20 arrivals/second
would imply about 800 concurrent routines; this is an illustrative capacity
calculation, not a measured latency or quota.

Proposed query mix: 25% broad additional filters retaining at least 10% within
category, 25% category-only beyond mandatory market/availability, 20% at about 1%
eligible within category, 15% at about 0.1%, 10% fewer than k eligible products,
5% certified no-match. Preserve category popularity skew and cold/rare requests.

Run with result-cache hit rate zero for release gating. Run a separate measured
production-like cache mix, never assume its hit rate.

### 7.3 Arrival process and measurement

Use scheduled/open-loop arrivals at 1, 5, 10, 20 and 40 routines/second equivalents.
Record scheduled arrival, actual send, admission, completion, timeout and rejection
times. A closed-loop generator alone can hide saturation by slowing its own
request rate.

OpenSearch Benchmark distinguishes service time from latency including scheduled
queue delay when target throughput is configured. [Official semantics][E04].
Capture both; engine `took` is not user-visible latency.

For each shortlisted configuration/scale/load cell:

- Warm up for at least 15 minutes and confirm stable state.
- Measure for at least 30 minutes; repeat independently three times.
- Record sample counts, histograms, errors, timeouts, queue growth and CPU/memory/
  disk/inference utilization.
- Treat unfinished/time-limited requests explicitly as failures/censored
  observations; never compute a flattering p99 using only quick successes.
- Report every repetition and variability. If a repetition breaches a release
  gate, investigate rather than averaging it away.

The four-hour soak uses the target load with updates. A five-minute 40-routines/
second burst tests bounded overload, clear admission rejection and recovery to
nominal gates within five minutes. Normal-load admission cannot reject traffic
to manufacture a passing latency result.

### 7.4 Performance gates

Proposed steady-state targets at one million products and 20 routines/second:

| Boundary | Gate |
|---|---|
| Step search, including query embedding, network, hydration, rerank and binding | p95 ≤500 ms; p99 ≤1,000 ms; 1,200 ms hard deadline |
| Routine retrieval wave, including step scheduling | p99 ≤1,500 ms; 1,600 ms hard deadline |
| Full routine | First product p95 ≤30 s; completion p95 ≤60 s and p99 ≤90 s |
| SSE continuity | No unexplained silence over 15 seconds |
| Step service errors | ≤0.1% at nominal load |
| Routine service failure / valid completion | ≤1% failures / ≥99% valid completion |
| Normal-load fallback use | ≤1% |

Valid no-match is counted as protocol completion and separately evaluated for
correctness. Do not infer the routine failure rate from the step error rate;
measure both with correlated failures. Timings and denominators must include
all supported two-to-eight-step routines.

## 8. P02/P03 — Resilience, freshness and rebuild

### P02: Fault matrix

During nominal load inject: one search data-node loss, shard relocation, ANN
unavailability, model throttling/timeouts, canonical-store partial responses,
projection-worker restart and runtime cancellation. Include availability-zone
failure if the chosen topology claims that resilience.

Require bounded retries, no constraint/catalog-binding violations, correct
fallback/error states and recovery evidence. Preserve offered load and record
degraded completion/quality, not just infrastructure alarms.

### P03: Change workload

Sustain 100 source events/second and a five-minute burst at 1,000/second. Split
metadata-only and embedding-changing updates, and explicitly include deletions
and availability flips. Record the actual mix; proposed rates are planning
assumptions to validate against the customer feed.

Measure freshness from **canonical commit acknowledgement to searchable
visibility**, not from when a consumer happens to receive the event. Use canary
products and revision markers visible in both systems.

Targets:

- Lexical/eligibility p95 visibility within 30 seconds.
- Changed-content embedding p95 visibility within five minutes.
- Alert on source-change age over 60 seconds.
- Mark a generation hard-stale beyond five minutes; do not silently use it.
- At least 99% ready, version-correct embedding coverage when semantic search is
  enabled. Missing vectors remain visible in a qualified lexical path.
- Zero lost acknowledged changes or stale-over-new writes in replay/reconciliation.

A million-product full rebuild must finish within the proposed 12-hour gate,
including embeddings/catch-up where required. Exercise missed-stream recovery,
dead-letter replay and rollback. Retained old indexes must be current enough for
rollback, not merely present.

## 9. P04 — Cost evaluation

Use actual metering and the selected region/provider's pricing snapshot at test
time. No dollar target is asserted without customer agreement.

Report:

- Fixed hourly/monthly search, ingestion, inference, network and observability cost.
- Marginal query embedding, reranking, upstream planning and explanation cost.
- Canonical read units, retries, failures, shadow calls and cache hit rates.
- Catalog embedding, ingestion, update and complete rebuild cost.
- Effective cost per 1,000 **completed routines**, allocating failed work and fixed
  infrastructure over measured throughput.
- The same metric at 1, 5 and 20 routines/second to reveal low-utilization cost.

Compare quality/cost/latency trade-offs. A system that wins nDCG but exceeds the
agreed ceiling does not pass. A null ceiling in the target file is a release
dependency, not permission for unlimited expenditure.

## 10. Release gates and required artifacts

| Gate | Evidence required | Decision |
|---|---|---|
| G0 — Design/workload freeze | Contracts, source identity/feed, scope, region/features/quotas, targets, owners, initial cost model and labeling plan | Implementation baseline agreed |
| G1 — Indexed baseline | T01–T11 relevant cases, real engine filter oracle, initial ingestion and explicit no-match, bounded runtime proof | B1 may enter evaluation |
| G2 — Quality qualification | Frozen independent qrels, adequate coverage/power, E01–E04, profile-only and full-routine evidence, absolute quality floors and critical-slice results | Select a qualified candidate, or stop if no method passes |
| G3 — Scale/operations qualification | P01–P04 on full 1m index, freshness/fault/rebuild/rollback evidence, cost ceiling, all correctness tests | Candidate may enter canary |
| G4 — Controlled release | Shadow/canary results, no binding/constraint regression, SLO/cost compliance, operational owner/runbooks | Release to qualified traffic |

For G2, proposed gates also include the fraction of attainable known-positive
candidate recall@100 ≥0.95 macro and ≥0.90 per critical slice, correct
certified-no-match abstention ≥99%,
false abstention on answerable cases ≤2%, no observed critical constraint/routine
rule violations, and factual explanation support ≥99%.

A failed gate produces an issue with evidence and a named remediation owner.
Targets are not weakened retrospectively to obtain a pass; scope or requirements
changes require a newly versioned decision and rerun.

Every release bundle MUST contain:

- Catalog snapshot/checksums and evaluation/index corpus relationship.
- Profile/query split manifest and judgment provenance/coverage/agreement.
- Engine, model, policy, schema and configuration manifests.
- Raw candidates, hydration drops, reranker inputs, selected IDs and outcomes.
- Per-profile metrics, slice tables, confidence intervals and error taxonomy.
- Raw load traces/histograms, generator utilization and offered/completed rates.
- Freshness/rebuild/replay and rollback evidence.
- Pricing snapshot, usage/cost calculation and environment resources.
- Test reports, unresolved limitations and the named release/operations owner.

## 11. Harness changes required

Extend `experiments/search/`; the following are implementation work, not existing
capabilities:

1. Production lexical/ANN/hybrid/rerank adapters with real credentials and fixed
   query templates.
2. Profile-only agent runner and repeated-run capture.
3. Stage-specific candidates, metadata drops and latency/cost fields.
4. Profile-cluster aggregation/bootstrap and grade ≥2 binary metric configuration.
5. Blinded judgment import, adjudication, unknown-label handling and provenance.
6. Full-index exact-neighbor ground-truth jobs for sampled queries.
7. Open-loop routine load generator plus OpenSearch Benchmark workload export.
8. Fault/update workload drivers and source-to-index freshness probes.
9. Machine-readable gate evaluation against versioned acceptance targets.
10. Report integrity checks that reject missing, partial or mismatched experiments.

[E01]: https://github.com/amazon-science/esci-data
[E02]: https://github.com/usnistgov/trec_eval/blob/main/m_ndcg_cut.c
[E03]: https://github.com/beir-cellar/beir/wiki/Load-your-custom-dataset
[E04]: https://docs.opensearch.org/latest/benchmark/target-throughput/
