> Archived decision report from the completed study. Its application baseline describes 2026-10-25, before this implementation. Research scripts and raw downloaded/generated outputs remain in the research workspace and are not included in the runtime package. See [implementation status](implementation.md) for current code and validation.

# Product matching decision

Updated 2026-10-25. **Research decision complete for the user's confirmed
ingredient-matching contract.** The public-record comparison and local capacity
screen are complete. This document does not authorize a production release.

## Recommendation

Use **an inverted index over exact ingredient IDs, hard eligibility filters, and
deterministic ranking by the number of distinct preferred ingredients matched**.
OpenSearch is the implementation tested here. The evidence does not establish
that OpenSearch is universally better than every other database.

This implements the user's confirmed contract: ingredient-agent selections are
preferences; separately marked must-haves are mandatory. Similarity, ingredient
families and different ingredients do not authorize substitutions. Explicit,
reviewed aliases for the same identity belong in ingestion/normalization.

The retrieval score needs no embedding model, cross-encoder or product-description
match. Keep the ingredient-planning decision upstream and keep generated
explanations bound to server-selected product facts.

## Why this method fits the objective

Let `P` be the set of distinct preferred ingredient IDs and `I(p)` the IDs in
product `p`. Among products satisfying all hard constraints, rank by:

```
score(p) = |P ∩ I(p)|
```

A fixed request's percentage match divides every score by the same `|P|`, so it
has the same ranking. Duplicate preferences or repeated ingredient entries must
not increase the score. Zero-match products are excluded.

Sorting eligible products by this score directly implements the specified
objective. Any alternative that places a lower count above a higher count
violates that ordering. This is a contract-conformance argument: the benchmark
checks the implementation, rather than establishing clinical benefit from an
ingredient-count metric.

Hard constraints are applied before top-k selection. A product missing a
must-have cannot compensate by matching several preferences. Exclusions,
unknown/incomplete records, price and availability need their own authoritative
fields and fail-closed rules.

The index replaces application-side category enumeration with a bounded result
interface. Search returns at most 100 candidate IDs; authoritative hydration and
final selection remain bounded. Internal index work still depends on term
frequency, selectivity, index size and resources, which is why serving is
measured separately.

## Public-record comparison

The pinned Open Beauty Facts snapshot contains 78,566 records. One invalid
product ID was rejected, leaving **78,565 indexed records**. Of these, **22,555**
have usable parsed ingredient labels. Ingredient tags inherited from broader
taxonomies and estimated percentage fields were excluded.

The frozen workload contains **6,000 requests from distinct anchor products**,
covering 1,376 literal source category tags:

- 5,100 requests with three to five preferences drawn from the anchor.
- 300 mixed-preference requests.
- 300 with a must-have absent from the snapshot.
- 300 with all preferences absent from the snapshot.

These are generated software requests over public records, not patient profiles
or independent suitability judgments. Normalization changes only case and
whitespace. The opaque IDs identify recorded labels; they do not constitute a
validated cosmetic ingredient registry.

Every request was evaluated against the full matching category. The current
production `_compute_position_scores` function was invoked directly. The exact
harmonic variant fixes identity matching and mandatory filtering while retaining
position weighting, separating those changes from the ranking objective.

| Method | Requests with a returned must-have violation | Requests losing attainable top-three exact matches | Correct no-match behavior |
|---|---:|---:|---:|
| Current substring/harmonic implementation | 3,018 / 6,000 | 3,129 / 6,000 | 90% |
| Exact harmonic, after mandatory filters | 0 / 6,000 | 1,807 / 6,000 | 100% |
| Exhaustive exact-count reference | 0 / 6,000 | 0 / 6,000 | 100% |
| OpenSearch exact count | 0 / 6,000 | 0 / 6,000 | 100% |
| OpenSearch default keyword-term sum | 0 / 6,000 | 0 / 6,000 | 100% |

The indexed exact-count method reproduced the reference's **entire ordered
top-100 list on all 6,000 requests**, and every returned score equaled its actual
exact-match count. Both indexed variants returned empty results for all 600
known no-match requests.

The result is not driven solely by the deliberate no-match controls. On the
5,100 anchor-preference requests, filtered exact harmonic lost attainable
top-three matches on **1,695 requests (33.24%)**. On the 300 mixed requests it
lost matches on **112 (37.33%)**.

One illustrative facial-cream request has three preferred recorded labels:
`caprylyl glycol`, `aqua`, and `glyceryl stearate`. Filtered harmonic returns
products matching **3, 2, 2** preferences; exact count returns **3, 3, 3**.
The full aggregate, not this example, supports the conclusion. Product identities
and recorded positions are retained in `ingredient-findings-v1/examples.json`.
No effectiveness or concentration inference is made from those positions.

## Two equivalent indexed implementations

The default keyword-term control also returned exact counts. This was verified
in a real score explanation: each matched ingredient contributes
`ConstantScore(...)=1`, and the Boolean query sums those contributions.

OpenSearch documents `keyword.use_similarity=false` as the default, using
constant scores. Therefore this control is **not a BM25 ingredient-ranking
experiment**. The evidence supports both implementations of the same count
rule, and provides no reason to claim a relevance advantage for either.

For an explicit, reviewable implementation, use one `constant_score` clause
with boost 1 per preferred ID; put category/must-have/exclusion rules in filter
clauses; require at least one preferred match; sort by score then product ID.
Alternatively, explicitly pin keyword similarity off and sum exact term clauses.

## Other correctness evidence

A separate finite audit compared an independently written predicate oracle,
the proposed Python eligibility implementation and actual OpenSearch filters:
**486 requests over 2,847 generated records**, with zero differing result sets.
It includes exact identities, ingredient-family references supplied explicitly,
list completeness, price boundaries, scope, taxonomy version, currency, markets,
availability and deletion/active states.

That audit establishes behavior within its finite matrices. It does not validate
ingredient taxonomy, customer-feed accuracy or clinical rules. The public-record
comparison does not fabricate missing stock, prices or complete disclosure.

## Scale evidence

The million-record synthetic index has been built and its document count
verified. Its 360 independently scanned validation requests, 60 per workload
class, all matched the engine's complete top-100 IDs and scores.

The corrected open-loop screen completed all six cells, three at each target
rate. Each cell included 30 seconds of warmup and 180 measured seconds. Latency
starts at scheduled arrival, including dispatch and worker-queue delay.

| Repetition | Target searches/s | Actual searches/s | Measured requests | p95 ms | p99 ms | Failed or late |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 120 | 120.02 | 21,603 | 19.07 | 25.60 | 0 |
| 1 | 160 | 158.27 | 28,488 | 17.39 | 22.35 | 0 |
| 2 | 160 | 161.56 | 29,081 | 16.95 | 21.96 | 0 |
| 2 | 120 | 121.52 | 21,874 | 19.84 | 24.63 | 0 |
| 3 | 120 | 120.43 | 21,678 | 19.42 | 24.19 | 0 |
| 3 | 160 | 158.51 | 28,532 | 17.27 | 24.70 | 0 |

All **151,256 measured requests** succeeded within the 1,200 ms deadline.
The maximum individual latency was **558.72 ms**; p99 is not a maximum.
Every cell passed the component thresholds: p95 ≤500 ms, p99 ≤1,000 ms and
unsuccessful fraction ≤0.1%. Raw-event reconciliation independently checked
offered-work IDs/counts, request identity, result bounds, statuses, percentiles
and checksums against the published summaries.

These target rates correspond arithmetically to 20 routines per second with
six or eight searches. Only the indexed search component ran; agent calls,
authoritative hydration and full routines were excluded.

The measured host was an Apple M3 Pro with 18 GiB RAM. Actual Docker limits
were verified as four CPUs and 4 GiB, with a configured 2 GiB JVM heap,
OpenSearch 3.9.0, one shard and zero replicas. The synthetic index contains
six category partitions and 4,232 possible ingredient IDs with engineered
frequency tiers. It stores compact ID/filter fields. Its initial store size
was 140,860,594 bytes. This is an explicit engineering workload, not a claim
about a customer's ingredient distribution, index footprint or AWS deployment.

An initial load attempt printed a known loopback demo-certificate warning on
each request. It was stopped and preserved as an instrumentation failure.
The corrected run uses the qualified load helper's narrow warning suppression.
Data, query bodies, rates, timing boundaries and thresholds were unchanged.
Only the corrected run contributes the capacity results above.

Offline reference timings and the eight-worker public correctness survey have
different boundaries and are not used to claim an end-to-end latency advantage.
The production specification's longer load/soak, update, failure, full-routine
and cost gates remain separate release work.

## Application changes implied by this decision

The active application still uses category enumeration and substring/harmonic
scoring. The proposed search adapter remains unconnected. Before adopting it:

1. Express preferred and mandatory ingredients separately.
2. Remove the proposed `retrieval_text` scoring clause from this search path.
3. Use exact-count scoring and truthful match counts, with stable ties.
4. Preserve hard filtering, bounded authoritative hydration and server-controlled
   product IDs/order.
5. Materialize ingredient availability during ingestion; its current category
   scan is a separate scaling issue.
6. Validate the real feed's canonical identities and disclosure/availability
   fields, then run the deployed pipeline's acceptance tests.

These items are implementation/release implications, not claims that the current
application has been changed. No application activation, commit or deployment
was performed by this research.

## Reproducibility and sources

Repository code and frozen protocols:

- `INGREDIENT_PROTOCOL.md`, `ingredient_prepare.py`, `ingredient_study.py`
- `INGREDIENT_SCALE_PROTOCOL.md`, `ingredient_scale.py`
- `SCOPE_CORRECTION.md`

Authoritative outputs under `output/search-decision/`:

- `ingredient-sources-v1/download.json` — pinned source and published SHA-256.
- `ingredient-records-v1/` — records, requests, label namespace and audit.
- `ingredient-reference-v1/` and `ingredient-indexed-results-v1/` — all results.
- `ingredient-comparison-v1/` — aggregate and per-request measurements.
- `ingredient-findings-v1/` — complete request-type breakdowns and illustrations.
- `ingredient-sources-v1/native-keyword-explanation.json` — actual engine scoring.
- `constraint-audit-v1/` — separate eligibility matrices and counterexamples.
- `ingredient-scale-v1/` — synthetic data, index, validation and capacity evidence.
- `ingredient-scale-v1/final-audit.json` — independent raw-event reconciliation.
- `ingredient-scale-v1/resource-verification.json` — actual container/host limits.

The earlier ESCI shopping-title experiments are preserved but excluded from this
ingredient-matching decision.

Official documentation:

- [Open Beauty Facts data and exports](https://world.openbeautyfacts.org/data)
- [OpenSearch keyword fields](https://docs.opensearch.org/latest/mappings/supported-field-types/keyword/)
- [OpenSearch constant-score query](https://docs.opensearch.org/latest/query-dsl/compound/constant-score/)
- [OpenSearch Boolean query](https://docs.opensearch.org/latest/query-dsl/compound/bool/)

Contains data from Open Beauty Facts, available under the Open Database License.
