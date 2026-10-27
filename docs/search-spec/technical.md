# Technical specification

Version 2.0, 2026-10-26. Implements the
[confirmed matching decision](decision-evidence.md).
MUST identifies an implementation/release requirement. Proposed numerical targets
live in [acceptance-targets.yaml](acceptance-targets.yaml).

## 1. Current application

The table records the application baseline before implementation. It is retained
to explain the migration. The current exact path and outstanding work are tracked
in [implementation status](implementation.md); neither document proves deployment.
Paths are relative to the repository root.

| Location | Previous behavior | Required change |
|---|---|---|
| `agents/product_repository.py` | Enumerates all category pages; scores ingredient substrings with harmonic weights; separately enumerates availability; readiness scans | Indexed matching, bounded ID reads, materialized discovery and readiness |
| `agents/tools.py` | Legacy `required_ingredients` means scoring preferences; empty results become errors | Separate preferences/must-haves; typed no-match; trusted ordered selections |
| `agents/models.py` | Ingredients have names; product output requires 1–3 model-selected products | Canonical ingredient IDs, versioned outcomes and separate explanations |
| `agents/catalog_binding.py` | Rebinds facts for model-selected IDs, permitting their subset/order | Enforce server-approved IDs/order, revisions and current facts |
| `agents/orchestrator.py`, `agents/compile_node.py` | Parallel ingredient/product chains; rejects empty outputs | Deterministic selection between planning and explanation; no-match and final reads |
| Ingredient prompt/tool | Restricts planning to 30 frequent returned ingredients | Common summaries for discovery plus bounded exact registry lookup |
| `agents/input_validation.py`, `api_proxy/handler.mjs` | Photos/job-ID allowlist | Matching v1/v2 validators and explicit preferences |
| Frontend types/parser/hook/views | No structured preference or per-step no-match contract | Preference controls, v2 outcomes and terminal UI states |
| `scripts/migrate_products.py` | Loads CSV into memory; hashes category/name for IDs; direct writes | Streaming import, stable IDs and durable change publication |
| Terraform/packaging | DynamoDB and PUBLIC-mode AgentCore; no search resources in this checkout | Private search connectivity, scoped roles, ingestion and packaging |

Experiments provide evidence/reference logic. They MUST NOT be imported as the
production adapter or packaged with downloaded data.

## 2. Requirements

| ID | Requirement | Verification |
|---|---|---|
| R01 | Versioned exact ingredient identities; no inferred substitutions | T01, T02 |
| R02 | Preserve explicit constraints; filter before ranking and after canonical reads | T01–T03, T05 |
| R03 | Distinct preferred-ID count descending; product ID ascending for ties | T02, T03 |
| R04 | Bound search, reads, discovery, concurrency and retries | T03, T04, T07, P01 |
| R05 | No runtime product/category enumeration, including discovery/readiness | T04, T09, P01 |
| R06 | Stable identity, ordered updates and durable deletion state | T06, P02 |
| R07 | Server-controlled facts, match metadata and final product order | T05, T08 |
| R08 | Distinguish no-match, catalog change and operational failure | T03, T05, T07, T08 |
| R09 | v1 compatibility and complete v2 SSE/compiler/browser behavior | T01, T08 |
| R10 | Private index; separate runtime, ingestion and administration access | T09 |
| R11 | Version configurations; rehearse fresh-generation rollback | T06, T10, P02 |
| R12 | Qualify deployed search, full routines, operations and cost | P01–P03 |
| R13 | Request isolation, cancellation and authoritative final validation | T05, T07–T09 |
| R14 | Verify registry/planning/explanations separately from match-count correctness | T02, T04, T08, E01 |

## 3. Selected design

### Components

1. **DynamoDB canonical catalog:** normalized IDs, source revisions, display facts
   and explicit unknowns.
2. **Catalog publisher and durable outbox:** a canonical update and its indexing
   event committed together.
3. **Projection workers:** publish versioned documents, maintain ingredient
   discovery data and report freshness/reconciliation.
4. **Private Amazon OpenSearch Service domain:** exact keyword IDs and eligibility
   fields. Use a provisioned domain for initial deployment qualification.
5. **Application search service:** validate, execute one fixed exact-count query,
   read bounded canonical candidates and select products.
6. **Existing agents/compiler:** plan ingredients, explain approved products and
   assemble the routine. They do not generate search DSL or choose products.

Per step: `ingredient plan → validated IDs + server constraints → exact search →
canonical reads → server selection → explanation → final binding`.

No free-text query, embedding, vector field, ANN branch, fusion, reranker or learned
score belongs in this path. Descriptions may remain canonical display facts; the
matcher does not retrieve or score them.

Pin engine/client versions, mapping hash, taxonomy/query versions, eligibility
mode, generation, limits and resources. The study used OpenSearch 3.9.0 locally;
that is not a managed-service version prescription. Pin a supported version in
the deployment Region and run the exact query/filter tests before activation.

### Scope and identity

The initial implementation serves one deployment-bound catalog in one Region,
with one authoritative offer per product in its configured market/currency
context. Multiple sellers, offer optimization, reservation, shared tenants and
cross-region consistency are separate work.

`catalog_id` comes from trusted configuration. `product_id` is a stable catalog-local
ID, at most 128 characters. Name/category changes MUST NOT change it. The search
document ID combines catalog/product unambiguously; a separate keyword
`product_id` supplies ties.

Migrate legacy hashes with an explicit old-to-new map. Where suppliers lack durable
SKUs, persist an identity ledger established at first import. Never regenerate IDs
from mutable names. Quarantine ambiguous identities before publication.

## 4. Ingredient and product contracts

### Ingredient registry

Entries contain `ingredient_id`, `display_name`, reviewed aliases, taxonomy version,
provenance and review state. Normalize case/whitespace for exact lookup; additional
aliases require reviewed evidence of the same identity.

IDs are nonempty and at most 128 characters. Ingredient lookup names are at most
256 characters. Categories come from the trusted catalog allowlist; model text
and input IDs cannot create categories or registry entries.

Related ingredients, derivatives, salts and families MUST NOT be merged because
names/descriptions resemble one another. Family-level requests are unsupported in
v2 and rejected; a future family policy needs a separate typed contract.

Preserve raw lists and unresolved tokens. Known evidenced tokens can contribute
positive matches even when another token is unresolved. Exclusions require a
complete source list and complete identity resolution. Ambiguous hard input is
invalid, not guessed. Public-study literal labels are research IDs, not a verified
production registry; they do not certify aliases, completeness or stock.

### Canonical product

| Field | Meaning |
|---|---|
| `catalog_id`, `product_id` | Trusted namespace and stable identity |
| `source_revision` | Positive monotonically increasing integer per product, including deletes |
| `source_updated_at`, `ingested_at` | UTC provenance times; ordering uses revisions |
| `category_id` | One supported routine category in the initial projection |
| `name`, `brand`, `image_path` | Source facts; current safe-image policy applies |
| `ingredient_ids` | Deduplicated resolved IDs evidenced by the source list |
| `raw_ingredients`, `unresolved_ingredients` | Original evidence and unresolved tokens |
| `ingredient_list_complete` | Explicit source-backed Boolean; unknown is false |
| `ingredient_resolution_complete` | Every listed token resolved; unknown is false |
| `price_minor`, `currency` | Optional nonnegative integer amount and explicit ISO currency |
| `market_ids`, `availability` | Evidenced markets; `available`, `unavailable` or `unknown` |
| `active`, `is_deleted` | Explicit publication/deletion state |
| `taxonomy_version`, `source_provenance` | Registry and original source/revision evidence |
| `matching_hash` | Deterministic hash of all identity, eligibility and matching fields |
| `record_hash` | Deterministic normalized-record hash for replay verification |

Define the matching-hash field set once: catalog/product/category, schema/taxonomy
interpretation, resolved IDs, completeness flags, active/deleted state, price/
currency, markets and availability. Sort/deduplicate set-valued fields and serialize
unknowns deterministically. Exclude display text/images, timestamps and revision
counters. Indexing and canonical validation use the same versioned hash contract.

Do not infer currency solely from a symbol, reconstruct contents from titles, or
infer concentration from list position. Reject/quarantine malformed records;
unknown optional facts stay unknown.

### Search projection

The [mapping](examples/index-mapping.json) contains IDs, eligibility, versions,
hashes and timestamps. Use explicit `dynamic: strict` mappings; ID fields are
keywords without text analysis. No descriptions, photos, profiles or generated
claims enter the product index.

A generation fixes schema/taxonomy/normalization. Projection is deterministic for
one canonical revision under that configuration; normalization changes require a
new generation. Source revisions become external document versions. Tombstones
are versioned documents with `is_deleted=true`, not immediate physical deletes.

## 5. Request and outcome contracts

### Public request v2

Retain current `job_id`/image validation. Add `api_version: 2` and optional:

| `preferences` field | Meaning |
|---|---|
| `excluded_ingredient_ids` | Routine-wide exact exclusions; at most 20 |
| `must_have_by_category` | At most eight unique category entries; at most 20 ingredient references total after deduplicating within each category |
| `market`, `currency` | Values from deployment allowlists |
| `max_price_minor` | Maximum for each product, not the whole routine |

The browser resolves names through `POST /api/ingredients/lookup` and submits IDs.
The API proxy authenticates this route using the same caller boundary as analysis
and reads only the deployment's registry/discovery records; no model is invoked.
An empty body object returns bounded public category, market and currency options.
A supported `category_id` without references returns the at-most-30 entry discovery
summary. Optional `references` contain at most 20 exact `ingredient_id` or `name`
objects; a category is not required for global identity resolution. With references,
return a per-input `resolved`,
`unresolved` or `ambiguous` status, resolved ID/name where applicable, taxonomy
version and advisory count timestamp. Unknown names are not guessed.

Apply request-size/rate limits and scoped lookup permissions to this route. It
cannot return a full catalog. No public customer selector, search DSL, index name,
arbitrary weights or model configuration. Registry version changes invalidate
cached options and require server revalidation of submitted IDs.

Proxy/runtime validators agree on allowlists, bounds and conflicts. Increase the
current non-image allowance only to the explicit v2 budget; keep image limits.
Price caps require currency explicitly or through a documented deployment default.
Amounts and caps are nonnegative integers no greater than 9,007,199,254,740,991,
so Python and browser JSON retain the same integer exactly.

Must-have categories must be supported and present in the validated plan. If the
planner omits one, return an explicit constraint/planning error; search cannot
silently discard the requirement or insert a step.

Required/excluded overlap is invalid. Exclusions remove contradictory soft IDs
before ranking and the server records that removal. No surviving preference is an
invalid ingredient plan, not an all-products query. v1 accepts photos only and
supplies no explicit constraints. Legacy tool `required_ingredients` migrate to
preferences, never automatically to must-haves.

### Ingredient plan and internal request

Add canonical `ingredient_id` to each ingredient output. The agent ordinarily
chooses 3–5; accept 1–5 distinct resolved IDs for sparse catalogs. Generated
benefit/usage text never establishes product contents.

| Internal `SearchRequest` | Owner/meaning |
|---|---|
| `request_id`, `step_id`, `category_id` | Server-bound routine/validated step |
| `catalog_id`, `eligibility_mode` | Trusted deployment configuration |
| `preferred_ingredient_ids` | Deduplicated resolved choices after exclusions |
| `must_have_ingredient_ids`, `excluded_ingredient_ids` | Frozen explicit constraints with origin |
| `market`, `currency`, `max_price_minor` | Validated values/defaults |
| `taxonomy_version`, `configuration_id`, `index_generation` | Routine-pinned configuration |

The server carries the monotonic deadline and shared retry ledger in a separate
`SearchBudget`, alongside this immutable request. They are not serializable tool
arguments. Constraint origin is established by the server's frozen preference
binding; a model cannot supply or change it.

The product agent receives approved selections. A retained tool interface may
retrieve only the bound request/result for its assigned step, not request a new
product selection.

### Outcomes and compatibility

Internal success includes ordered canonical records/revisions, matched preferred
IDs, `matched_count`, `preferred_count`, matched must-haves, generation and read
time. `returned_count` is not total catalog matches. Engine scores/health details
stay in traces.

Public v2 products retain current display fields and add `price_minor`, `currency`,
`availability`, `matched_count`, `preferred_count`, `matched_ingredient_ids` and
`matched_must_have_ingredient_ids`. Unknown price/currency are null with factual
unavailable display text. `match_score` remains only a legacy formatted percentage;
the v2 interface uses the integer counts. See [contract examples](examples/contracts.json).

| Outcome | Meaning |
|---|---|
| `matched` | One to three validated products; factual match counts |
| `no_match / no_matching_products` | Complete healthy exact query found zero eligible positive matches in its indexed view |
| `no_match / catalog_changed` | Hits existed but all bounded candidates/final selections became invalid; suggest retry |
| Service error | Timeout/partial shards, unhealthy generation, unresolved reads or dependency failure |
| Validation/planning error | Invalid/conflicting inputs or ingredient plan; not a catalog no-match |

Do not name a single constraint as the cause of no-match unless established; list
applied constraints without inventing a diagnosis. No-match is not a clinical
judgment or a claim about every live product.

`CompiledStep` v2 adds `recommendation_status` and nullable `no_match_reason`.
`products: []` requires explicit no-match; matched requires 1–3. Every planned step
must exist. Mixed/all-no-match routines terminate visibly; all-no-match is shown
as no products found. Operational failures use the terminal error channel.

Fully matched v1 keeps its shape with exact-count percentage display. For v1
no-match, use a terminal domain code such as `NO_MATCHING_PRODUCTS` in the existing
error envelope; count it separately from service failures. Deploy the compatible
browser before v2 controls. Older cached browsers can show their generic-error
fallback; do not claim they support per-step no-match.

## 6. Exact search and authoritative selection

### Eligibility and score

Let `P` be distinct preferences, `R` must-haves, `X` exclusions and `I(p)` resolved
product ingredient IDs. Eligibility requires:

- Trusted catalog/category/schema/taxonomy, active and nondeleted state.
- Every must-have: `R ⊆ I(p)`; no exclusion: `X ∩ I(p) = ∅`.
- Both completeness flags true whenever exclusions are present.
- Every supplied market, currency and price predicate, using source facts.
- In `purchasable` mode, verified availability and configured market/currency.
  In `catalog` mode, unknown stock is permitted and displayed truthfully.

Unknown facts fail predicates that depend on them. Unknown price alone does not
exclude a catalog-mode product when no price/currency predicate needs it.

For eligible products, `score = |P ∩ I(p)|`; require at least one match. Sort by
`(-score, product_id)` and select up to three. A must-have outside `P` is only a
filter. Duplicates, position, corpus frequency, description and price add no points.
Legacy percentage is `100 × matched_count / preferred_count`, rounded to one
decimal for display. The v2 UI shows integer numerator/denominator.

### Query template

Submit the [example body](examples/search-query.json) to:

`POST /<pinned-generation>/_search?allow_partial_search_results=false`.

- One `constant_score` with `boost: 1` and exact keyword `term` filter per preference
  in `bool.should`; set `minimum_should_match: 1` explicitly.
- One filter `term` per must-have. One `terms` query means any value and does not
  enforce all must-haves.
- Scope/state/version and conditional market/currency/range/completeness filters;
  exclusions in `must_not`.
- At most 100 hits; `_score` descending then `product_id` ascending; limited source
  fields, `track_total_hits: false`, server-bounded timeout.

See [constant score][S01], [Boolean queries][S02], [keyword fields][S03] and
[Search API][S04]. Explicit constant-score clauses make the count rule independent
of implicit keyword-similarity defaults. No scoring `must`, scripts, boosts,
rescoring or early-termination cap.

Reject timed-out, malformed, nonfinite, incomplete or wrong-generation results.
Check pinned-engine shard completion semantics, including skipped shards, and test
missing/unallocated shards. A healthy complete zero-hit query proves indexed-view
no-match without `track_total_hits` or a second existence query.

### Bounded canonical reads

1. Validate/deduplicate at most 100 ordered hit IDs.
2. Read the first ten (or fewer) by ID from the authoritative table.
3. Restore index order and check scope, current eligibility, exact coverage and
   matching hash. For an unchanged hash, the engine score must equal the recomputed
   count; a disagreement is an integrity error, not a different ranking signal.
4. If fewer than three survive, read one remaining slice from those original hits,
   up to 100 distinct candidates total.
5. Select the first three valid unchanged candidates in that ordering.

Use strongly consistent base-table reads. [BatchGetItem][S05] supports up to
100 items/16 MB, unordered responses and `UnprocessedKeys`. Include keys, retry
only unresolved keys within the shared deadline/retry budget, and distinguish
unprocessed from missing. Do not skip an unread higher-ranked candidate and call
the selection complete.

Drop missing/deleted/ineligible products and changed matching hashes. A newer
source revision with unchanged matching hash may supply current display facts.
Do not rescore changed products within a small pool and call that a global optimum.
If all candidates disappear, use `catalog_changed`; one or two valid survivors are
a matched short result. Record invalidation and short-result counts.

No category query, scan, scroll, search pagination or additional refill query is
allowed. The cap bounds application transfer/reads, not all engine work.

### Consistency and finalization

Exact top-100 ordering is guaranteed for the indexed view. On an unchanged,
synchronized catalog it reproduces canonical exhaustive top three. During updates,
bounded retrieval cannot guarantee the latest global canonical optimum. Generation
pinning fixes schema/configuration, not a frozen document snapshot.

Reread selected products before final serialization: at most 24 for eight steps.
Reapply constraints/hash checks; remove changed selections and affected explanations.
No new search cycle occurs. Refresh display-only facts. Successful reads removing
all selections produce `catalog_changed`; unresolved reads remain service errors.

The binder allows only approved IDs/order for the request/step. Generated text
cannot provide price, stock, images, ingredient identity, coverage or concentration.
Invalidate affected explanation text after source changes and omit it or use a
factual template. Facts are valid at recorded read times, not an inventory
reservation or an atomic full-catalog snapshot.

## 7. Ingredient discovery without category scans

Maintain versioned category summaries and exact ingredient presence/count entries
outside the request-time product enumeration path. Counts are advisory.

Return at most 30 common ingredients for initial discovery. Add exact ID/approved-
alias registry lookup: at most 20 references per call and three discovery calls
per step. The prompt may select a resolved rare ingredient outside the summary.
It cannot invent IDs or use a stale zero count to forbid an exact product query.

Use catalog/category/taxonomy keys and bounded reads/lookup queries. Background
aggregation publishes deterministic replacement summaries with generation and
`as_of`, avoiding replay double-increments. Background sweeps are permitted;
runtime category enumeration is not.

Mark stale summaries advisory and permit registry lookup. Registry failure or an
unresolved chosen ID is an explicit planning dependency error. Include discovery
reads in full-routine capacity/cost; they are additional to product-search traffic.

## 8. Ingestion, freshness and rollback

### Reliable publication

Live writers use one publication contract. A DynamoDB transaction conditionally
writes a new canonical revision, an outbox event and a shard counter together.
The event's immutable identity is catalog/product/revision; its normalized
body/hash is immutable. Its storage key is catalog/shard plus the monotonically
increasing sequence within that shard. [Transactions][S06]
provide atomic writes across tables in one account/Region. Two independent writes
or short SDK idempotency windows are insufficient.

Stable product IDs choose one of 16 shards. Workers use strongly consistent base
table queries after each retained generation's acknowledged sequence, lease the
shard conditionally, and publish at most 100 events per batch. They refresh the
generation before advancing its acknowledgement. Expired leases recover and
fenced checkpoint writes reject old owners. A stream notification accelerates
work; periodic shard queries recover missed notifications without scanning.
An unhealthy generation retains its failure evidence and cannot advance its
checkpoint; successful generations can continue independently.

Stream the importer. Establish feed ordering or a persisted ingestion sequence;
timestamps alone do not order updates. Same revision/hash is idempotent; equal
revision/different content is an integrity error. Quarantine malformed rows.

An initial immutable bulk import may bootstrap directly using a manifest,
checkpoint and reconciliation. Capture subsequent changes through the outbox before
making the deployment writable/servable. Prohibit other direct catalog writers.

### Index versions and deletes

Publish full documents through Bulk API `index` with `version_type: external` and
`source_revision` as `version`. [External versioning][S07] rejects equal/lower
revisions. Inspect every item acknowledgement. A conflict is delivered only after
verifying a newer stored revision or an equal revision with identical hash.
Equal revision/different body is quarantined and alarms. Retry transient background
failures with bounded backoff; partial bulk success is not full acknowledgement.

Delete through a newer canonical/outbox/index tombstone. Pending events never
expire. Retain delivered history/tombstones at least seven days and beyond every
replay/retry/rollback horizon. Keep a durable identity high-water mark beyond
physical cleanup to prevent resurrection; reactivation needs a higher revision.
Searchable visibility, including refresh delay, is distinct from write acknowledgement.

### Readiness, rebuild and cutover

Replace `has_products()` with a lightweight record containing generation/config,
health/source-feed heartbeats and oldest unresolved change. No source updates and
missing feed health are distinct. Missing/stale health evidence disables admission.

Refresh readiness heartbeats within 60 seconds and advisory discovery summaries
within a five-minute target. A stale summary is marked advisory; a stale readiness
heartbeat prevents search, independently of the publication-lag threshold.

Targets: update visibility p95 ≤30 seconds; unresolved-lag alarm at 60 seconds;
unavailable at 300 seconds or an unknown capture gap. Measure feed-to-canonical
lag separately. Reconcile IDs, revisions, hashes and tombstones daily.

Build from a declared snapshot/checkpoint while capturing changes; replay and
reconcile before serving. A retention/capture gap requires rebuild, not a worker
restart. Million-product rebuild target: 12 hours including replay/checks.

Cut over with atomic alias `remove`/`add`; never `remove_index`, which deletes
an index. [Alias API][S08]. A trusted configuration manifest resolves one physical
generation per routine. Promotion reconciles alias/manifest state, resumes safely
after either operation and never serves an unready generation. Existing routines
keep their compatible generation.

Write updates to active and retained rollback generations, recording per-generation
acknowledgements. Keep the prior generation at least seven days and rehearse fresh
rollback within five minutes. An old stale index or legacy category-scan scorer
is not a fallback.

Automatic rollback requires compatible canonical IDs and matching semantics.
An incompatible registry/schema migration needs retained normalized representations
and reader compatibility, or a separately qualified migration plan before cutover.
Keeping an old index alone does not preserve its ability to validate current records.

## 9. Deadlines, capacity and failure behavior

Step search starts at a validated request's scheduled arrival and ends with bound
selection/no-match. It includes queueing, readiness, search, reads and selection;
it excludes ingredient/explanation models. Targets: p95 ≤500 ms, p99 ≤1,000 ms,
hard deadline 1,200 ms.

Starting budget: scheduling/readiness 100 ms, search 350 ms, canonical reads/refill
500 ms, selection 50 ms, shared retry reserve 200 ms. These are upper planning
budgets, not per-stage percentile promises. Clients share the remaining deadline
and retry ledger.

At most one additional remote attempt per step, including nested SDK retries and
unprocessed-key retries. The one planned refill is not a retry. Final selected
reads have one routine-level retry within the overall routine deadline.

Searches become ready after their ingredient agents finish. Measure each from its
own scheduled arrival; full-routine latency includes late ingredient steps. The
current graph has no synchronized retrieval wave to which a separate timer applies.

| Work at 20 routines/second, excluding retries/shadow | Six steps | Eight steps |
|---|---:|---:|
| Indexed product searches/second | 120 | 160 |
| Initial candidate records read/second at ten per step | 1,200 | 1,600 |
| Maximum distinct candidate reads/second with refill | 12,000 | 16,000 |
| Maximum selected-record final reads/second | 360 | 480 |
| Current agent nodes/second before deterministic compilation | 280 | 360 |

Reads are item counts, not billing units. Discovery, tool loops, retries, shadow,
writes and rebuilds add work. Limit per-routine searches to eight concurrent and
use finite deployment queues/admission based on measured capacity. Qualify engine
replication/AZ failure tolerance; the local zero-replica test is not deployment sizing.

| Condition | Behavior |
|---|---|
| Healthy complete query, zero hits | `no_matching_products` |
| Candidates/final selections become invalid | Remove; remaining products or `catalog_changed` |
| Timeout, missing/partial shards, unavailable index | Service error |
| Unresolved canonical reads or registry/config mismatch | Service/planning error |
| Capture gap or hard-stale generation | Stop affected admission; only separately healthy compatible generation may serve |
| Explanation fails | Qualified factual template or omitted advice |
| Cancellation/disconnect | Stop work where supported; prevent late state/events |

Never loosen constraints, issue broad searches or enumerate DynamoDB on failure.

## 10. Private access and operations

Use an [OpenSearch VPC domain][S09], TLS verification, encryption and scoped roles.
Runtime searches and reads bounded canonical/discovery records; ingestion publishes;
administrators manage schemas/generations. Use IAM/SigV4 and scoped engine role
mappings; runtime gets no master access. [Access control][S10].

The previous AgentCore network mode was PUBLIC. The replacement uses [VPC connectivity][S11]
to private search with supported AZs, scoped security groups and required image,
logging, model and DynamoDB access. Preserve caller authentication. No browser
access to search or public database port. Verify anonymous/wrong-role denial before
restricted imports.

Separate readiness records from administrative APIs. Remove runtime `Scan` and
category-index enumeration permissions; background publication/reconciliation use
separate roles.

Trace candidate/read/retry counts, exact coverage, invalidation, scheduled latency,
no-match reasons, errors, revisions/generation, source lag and replay/rebuild.
Track offered/admitted/completed routines, model requests/tokens and final reads.
Do not put raw profiles/photos/ingredients in metric labels; protect detailed traces.

Disable result caching for initial qualification. Future cache keys include every
constraint/configuration/generation and never bypass canonical reads. Add runtime
modules to packaging; exclude experiments/datasets. Ship runbooks and measured
infrastructure/model/read cost. Unset customer cost ceilings block release
budgeting, not contract implementation.

## 11. Official implementation references

Verify exact SDK/provider syntax and selected Region capabilities during
implementation; no SDK upgrade is prescribed. Source verification for this spec
is recorded in [verification.md](verification.md#documentation-check).

- [Constant-score query][S01]
- [Boolean query and minimum_should_match][S02]
- [Keyword mapping and similarity][S03]
- [Search API and partial-result controls][S04]
- [DynamoDB BatchGetItem][S05]
- [DynamoDB transactions][S06]
- [Bulk API and external versions][S07]
- [Atomic aliases][S08]
- [OpenSearch VPC domains][S09]
- [Fine-grained access and IAM signing][S10]
- [AgentCore VPC connectivity][S11]

[S01]: https://docs.opensearch.org/latest/query-dsl/compound/constant-score/
[S02]: https://docs.opensearch.org/latest/query-dsl/compound/bool/
[S03]: https://docs.opensearch.org/latest/mappings/supported-field-types/keyword/
[S04]: https://docs.opensearch.org/latest/api-reference/search-apis/search/
[S05]: https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_BatchGetItem.html
[S06]: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html
[S07]: https://docs.opensearch.org/latest/api-reference/document-apis/bulk/
[S08]: https://docs.opensearch.org/latest/api-reference/alias/aliases-api/
[S09]: https://docs.aws.amazon.com/opensearch-service/latest/developerguide/vpc.html
[S10]: https://docs.aws.amazon.com/opensearch-service/latest/developerguide/fgac.html
[S11]: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html
