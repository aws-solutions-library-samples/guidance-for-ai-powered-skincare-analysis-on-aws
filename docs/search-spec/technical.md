# Technical specification

Status: proposed. Read [scope and assumptions](README.md) and
[acceptance targets](acceptance-targets.yaml) with this document. MUST denotes a
release requirement. Starting parameters are subject to G0 agreement and measured
tuning; they are not performance claims.

## 1. Current implementation and required changes

The code, rather than older architecture prose, is the implementation baseline.
Some existing architecture prose predates current IAM/proxy changes.

| Current location | Observed behavior | Required change |
|---|---|---|
| `agents/product_repository.py` | Reads all category pages for ingredient aggregation and again for Python ranking | Bounded indexed retrieval; batch hydration by stable ID; materialized ingredient availability |
| `agents/tools.py` | Returns three harmonic-ranked products; empty results become a tool error | Typed search outcomes; constrained bounded search; operational errors distinct from valid no-match |
| `agents/models.py` | Products are mandatory in every product output | Versioned result contract permitting explicit no-match; separate generated and authoritative fields |
| `agents/catalog_binding.py` | Binds model-selected IDs to the latest tool result for the step | Bind approved server-selected IDs, source revisions, generation and request; preserve order |
| `agents/orchestrator.py` | N ingredient/product chains; product agent selects and explains | Freeze query context, bound concurrency, capture search outcomes, explain approved selections |
| `agents/compile_node.py` | Rejects empty product outputs | Accept explicit no-match, reject missing/failed steps; validate whole-routine constraints |
| `agents/input_validation.py`, `api_proxy/handler.mjs` | Request allowlists accept only `job_id` and `images` | Versioned optional preferences contract validated at both boundaries |
| Frontend API/types/parser/views | Sends photos; has no structured preference entry | Preference entry, v2 outcomes, clear no-match display, backward-compatible transition |
| `scripts/migrate_products.py` | Identity is a hash of category and name; loads CSV into memory | Stable supplier identity; streaming/chunked import, revisions, quarantine and delete semantics |
| Terraform | DynamoDB catalog; AgentCore PUBLIC network mode; no search index | Private search deployment, runtime connectivity, ingestion and inference permissions |
| `experiments/search/` | Exact local reference methods; small unreviewed fixture set | Production adapters, independent judgments, load generation, full-pipeline evaluation |

Repository paths above are relative to the project root. The
[delivery file map](delivery.md#5-file-and-module-impact) gives the planned edits.

## 2. Required behavior

| ID | Requirement | Verification group |
|---|---|---|
| R01 | MUST derive customer/catalog scope from trusted configuration/authentication, never an LLM or arbitrary request field | T01, T09 |
| R02 | MUST validate and preserve user-declared hard constraints; unknown constrained facts MUST fail eligibility | T01, T02 |
| R03 | MUST perform no runtime category enumeration or full-catalog vector scoring in production | T03, P01 |
| R04 | MUST distinguish ingredient identity, spelling aliases, ingredient families and suitability policy | T02, E02 |
| R05 | MUST bound retrieval, hydration, reranking, concurrency and retries | T03, T07, P01 |
| R06 | MUST preserve source identity, revisions, deletions and freshness through ingestion | T04, P03 |
| R07 | MUST use identical scope/eligibility semantics in every retrieval branch and final validation | T02, T05 |
| R08 | MUST bind returned facts and selected order to authorized, current product records | T06, T09 |
| R09 | MUST distinguish matched, valid no-match, degraded service and failed service | T07, T08 |
| R10 | MUST support configuration/model/index versioning and tested rollback | T04, T10 |
| R11 | MUST expose adequate traces, metrics and reproducibility records | T11, E01, P01 |
| R12 | MUST gate ranking changes on independent relevance and scale evidence | E01–E04, P01–P04 |
| R13 | MUST keep search data private and authorize reading separately from indexing/admin operations | T09 |
| R14 | MUST validate complete routines and explanation grounding, not only individual search lists | T08, E03 |
| R15 | MUST handle explicit no-match in the compiler and browser without masking an outage | T07, T08 |
| R16 | MUST prevent new runtime modules/resources from being omitted by packaging/deployment manifests | T10 |
| R17 | MUST preserve retry/error/cancellation isolation across simultaneous users and steps | T07, T08, T09 |
| R18 | MUST document measured cost and enforce the agreed release cost ceiling | P04 |

## 3. Architecture and implementation choices

### 3.1 Components

1. **Canonical catalog:** DynamoDB remains the authoritative product store for the
   first customer implementation. The design accepts a different upstream PIM or
   commerce feed through the import contract.
2. **Projection pipeline:** asynchronous normalization, text construction,
   embedding and versioned projection. It owns indexable product facts.
3. **Search index:** a private, provisioned Amazon OpenSearch Service domain for
   initial qualification. It stores lexical fields, structured eligibility
   attributes and optional ANN vectors.
4. **Retrieval adapter:** Python application component behind a provider-neutral
   interface. It compiles validated query objects to fixed query templates, runs
   retrieval, applies fusion, hydrates candidates, optionally reranks and selects.
5. **Inference adapters:** query/product embedding and reranking through managed
   AWS inference interfaces. Initial provider preference is Bedrock where the
   chosen model and region support the required operation and quotas. A different
   provider requires a separate capability/cost decision, not a silent substitution.
6. **Agent integration:** existing graph orchestration receives validated profile
   context, resolves ingredient preferences, and explains approved products.
7. **Evaluation and operations:** independent relevance datasets, production run
   capture, load tests, ingestion reconciliation, dashboards and release gates.

The request path is:

`validated profile and preferences -> ingredient/query planning -> indexed candidate
retrieval -> fusion -> authoritative hydration and eligibility -> optional reranker
-> server selection -> explanation -> deterministic routine validation/binding`.

OpenSearch Serverless is a possible later deployment variant, not assumed
interchangeable. G0 MUST verify chosen engine/version support for filters, ANN
method, alias operations, inference integration, security and monitoring.

DynamoDB is not responsible for ranking full categories in this architecture.
No million-product index or large local model is loaded inside each AgentCore
session.

### 3.2 Capability and model manifest

Each runnable configuration MUST pin:

- Engine/provider versions, region, analyzer definitions, index mappings and ANN
  method/settings.
- Embedding and reranking model identifier/revision, dimension, similarity
  function, prompt/template revision, truncation and token limits.
- Query normalization/taxonomy and reviewed policy versions.
- Candidate limits, fusion parameters, reranking limits, relevance threshold
  configuration, stage deadlines and fallback policy.
- Deployment hardware, shards/replicas, capacity settings and inference quotas.

Changing any of these produces a new configuration ID and triggers the applicable
evaluation gates. The local MiniLM models are baselines, not preselected production
models. Verify managed reranker availability from [AWS's current matrix][S08].

### 3.3 Capacity worksheet

For each candidate, record active products, text/metadata bytes, vector dimension,
numeric representation, ANN/index overhead, shard count, replicas and measured
working memory. Raw uncompressed vector storage is
`products × dimensions × bytes_per_component × physical_copies`.
For example, one million 768-dimensional float32 vectors require 3.072 GB per
copy (decimal units), before ANN structures, text, metadata, caches and replicas.
This arithmetic is not a node-sizing recommendation.

At the agreed 20 routines/second, distinguish search capacity from inference and
authoritative-read capacity:

| Upper work budget, excluding retries/shadow traffic | Six-step case | Eight-step case |
|---|---:|---:|
| Logical step searches/second | 120 | 160 |
| Lexical + ANN branch executions/second | 240 | 320 |
| Query embeddings/second without reuse | 120 | 160 |
| Reranking pairs/second at 50 per step | 6,000 | 8,000 |
| Distinct canonical candidate records read/second at the 100-per-step cap | 12,000 | 16,000 |
| Additional selected-record checks/second at finalization | 360 | 480 |
| Current graph agent-node executions/second before compilation | 280 | 360 |

Record reads are not billing units; item sizes and read consistency matter.
Agent nodes are not model-call counts; tool loops, retries and generated tokens
must be measured. Include admission/concurrency limits for the full graph,
upstream model quotas, query/rerank quotas, update embeddings and rebuild jobs.
Use separate serving/background budgets so a rebuild cannot starve requests.

## 4. Product and identity contract

### 4.1 Canonical product

These are application fields, not a claim about an existing AWS API schema.

| Field | Required semantics |
|---|---|
| `catalog_id`, `product_id` | Stable supplier SKU identity in a customer namespace; renaming/category edits do not change identity |
| `source_revision` | Monotonically increasing integer for this product; older events cannot overwrite newer state |
| `source_updated_at`, `ingested_at` | UTC times for audit/lag; timestamps do not replace revision ordering |
| `category_id`, `name`, `brand`, `description` | Canonical category and source-provided descriptive facts |
| `ingredient_ids` | Canonical exact ingredient identities |
| `raw_ingredients`, `ingredient_list_complete` | Source evidence and explicit completeness flag |
| `ingredient_family_ids` | Reviewed taxonomy memberships; distinct from exact aliases |
| `price_minor`, `currency` | Integer minor units and currency; unknown is explicit |
| `market_ids`, `availability`, `active`, `is_deleted` | Eligibility fields; unknown stock state is explicit |
| `source_provenance`, `attribute_evidence` | Origin/version for attributes used in constraints and explanations |
| `image_path` | Validated existing asset policy; source text cannot create arbitrary URLs |
| `content_hash` | Hash of the facts used in the retrieval text/embedding |

The original name/category hash IDs MUST be migrated with an explicit mapping.
Existing IDs must remain resolvable during migration. Customer feeds lacking
durable IDs or ordering need a documented ingestion identity strategy before
production import. Do not resolve identity through fuzzy product-name matching.

Version one allows one active offer per product/market/currency combination.
Multiple seller offers and inventory reservation are separate commerce work.
If the feed includes offers, normalize the chosen offer deterministically and
record its identity.

### 4.2 Search document

The projection adds:

- `projection_revision`: monotonic for every projection write, including embedding
  completion for the same source revision.
- `schema_version`, `taxonomy_version`, `text_template_version`.
- `retrieval_text`: source-grounded product text, excluding user profiles and photos.
- `embedding`, `embedding_model_revision`, `embedded_content_hash`,
  `embedding_state` (`ready`, `pending`, `failed`, `not_enabled`).
- Source revision, eligibility fields, and identifiers needed to detect staleness.

Index identity is the namespaced canonical product ID. Exact IDs/categories are
keyword fields; free text uses the qualified analyzer; prices use numeric fields;
vectors use the pinned dimension/method. Avoid unbounded dynamic mappings.

Embedding text may include source-backed concerns/usage attributes. It MUST NOT
include assistant-invented efficacy claims or expected relevance judgments.
Unknown concentrations, SPF, suitability or exclusions cannot be reconstructed
from a suggestive product name. A real ingredient list's order is not a calibrated
concentration or efficacy score.

## 5. Profile, preferences and search contracts

### 5.1 Public request v2

Retain the existing image limits and job-ID validation. Add:

- `api_version: 2`.
- Optional `preferences`: market, currency, per-product maximum price, explicit
  required/excluded ingredient IDs or validated resolvable names, and allowed
  soft product-format/texture preferences.
- No public `catalog_id`, search DSL, model IDs, index names, scores or arbitrary
  provider configuration.

Both proxy and runtime MUST validate the versioned allowlist. Existing v1 requests
remain accepted with empty explicit preferences during rollout. Unknown
constraints must be rejected or clarified; they must not be silently ignored.

Resolve absent market/currency from trusted deployment defaults established from
the customer catalog. Validate supplied values against the deployment's supported
values. Price limits are nonnegative integer minor units and require currency.
Initial bounds: at most 20 required and 20 excluded ingredient/family references,
20 soft ingredient preferences, and 2,048 characters of internal rendered query.
An exact ingredient and a reviewed family have distinct typed references; names
must resolve unambiguously to one. Soft format/texture values come from a versioned
allowlist and are scored only against source-backed attributes.

The frontend needs bounded controls for supported preferences and a review screen
showing what will be enforced. It must not imply that an ingredient exclusion is
a medical allergy determination. Per-product budgets must be labeled per product;
a total-routine budget is outside version one.

The current proxy derives the authenticated caller from validated claims but does
not pass a general tenant selector to the runtime. Version one uses a deployment-
bound catalog. Any future shared deployment requires a separately verified
trusted-context propagation and authorization design.

### 5.2 Internal `SearchRequest`

| Field | Semantics |
|---|---|
| `request_id`, `step_id`, `catalog_scope` | Server-controlled identifiers/scope |
| `profile` | Validated skin type, concerns and goals, with provenance and uncertainty |
| `category_id`, `market`, `currency` | Validated routing/eligibility context |
| `preferred_ingredients` | Canonical IDs and optional bounded importance weights; soft preferences |
| `required_ingredients`, `excluded_ingredients` | Hard constraints with their user/policy origin |
| `per_product_max_price_minor` | Optional hard price limit |
| `query_text` | Versioned rendering of the profile/step/soft preferences |
| `configuration_id`, `index_generation`, `policy_version` | Frozen for the routine |
| `deadline` | Remaining server deadline; callers cannot expand it |

Rename the old `required_ingredients` meaning: the current tool actually treats
these as positive scoring preferences. Migration MUST distinguish that legacy
meaning from a new hard requirement.

The LLM can propose soft ingredients and query wording. It cannot weaken hard
constraints, change catalog scope, submit provider DSL, alter query limits, or
replace canonical fields. Hard exclusions override contradictory positive
preferences; contradictory hard requirements are an invalid request/policy result.

### 5.3 Ingredient availability

Replace live product enumeration with materialized counts/presence by category
and canonical ingredient ID, generated asynchronously during ingestion.

Provide a bounded ingredient lookup and relevant taxonomy view rather than the
30 most frequent ingredients. Rare ingredients remain resolvable by ID/name.
Availability counts are advisory and versioned; a stale zero count cannot forbid
retrieving an otherwise known ingredient. Unknown aliases are not inferred by
substring matching. Family expansion is explicit, reviewed and traceable.

For example, an exact ingredient exclusion and a family exclusion are different
contracts. The latter expands through a qualified taxonomy version. A product
with an incomplete ingredient list cannot satisfy an exclusion requiring complete
knowledge of that list.

### 5.4 `SearchResult` and step outcome

Internal result fields include:

- `status: matched | no_match`.
- For no-match: `reason: no_eligible_indexed_products | insufficient_relevance | catalog_changed`,
  plus the validated constraints used.
- Approved ordered product IDs, canonical records and source revisions.
- Separate ingredient coverage, ranking score/features, and confidence/threshold
  evidence. Scores are not probabilities unless explicitly calibrated.
- Configuration/index/model versions, bounded stage counts/timings, and degradation
  reason for logs/evaluation.

`no_eligible_indexed_products` requires an exact filtered existence check on a
healthy, sufficiently fresh index. An ANN miss alone is not proof of no eligible
products. Within a deadline, inability to establish that fact produces
`insufficient_relevance` only when all required search stages completed; an
operational failure remains an error.

This status describes the current index/consistency window. It does not promise
that every live product worldwide has been ruled out.

Public `CompiledStep` v2 adds `recommendation_status`, an optional user-facing
reason, and allows `products: []` only for explicit no-match. Missing output,
malformed results, failed hydration and search outages MUST still fail the step.
The routine can complete with clearly marked no-match steps. A search outage does
not become a successful empty routine.

If final canonical revalidation removes every selected product, return a distinct
`catalog_changed` no-match reason only when the canonical reads completed
successfully. It means the selection became unavailable during generation, not
that the entire catalog has no suitable product. Surface a retry suggestion and
count it separately from search abstention. A failed canonical read remains a
service error.

### 5.5 Compatibility behavior

The request version selects the output schema. Deploy a browser compatibility
release that understands v1, v2 and the new terminal domain codes before enabling
v2 controls or assigning v2 canary traffic.

Fully matched v1 requests retain the current response shape. A v1 client cannot
represent per-step no-match, so the compatibility adapter returns the existing
terminal error envelope with a new domain code such as `NO_SUITABLE_PRODUCTS`;
it does not serialize an invalid empty v1 product list. Add that code to
`agents/errors.py` and `frontend/src/utils/analysisErrors.ts`, with factual
localized presentation. Keep its domain-outcome metric separate from service
failures. An older cached browser without the compatibility release will show its
existing generic error, not the v2 no-match experience; test and document this
limit rather than claiming transparent support.

For v2, matched/no-match mixtures are valid compiled routines. Operational failures
retain the existing terminal error channel and never become a domain no-match.
Measure completion and quality by protocol version during migration.

## 6. Retrieval and ranking algorithm

### 6.1 Eligibility

Compile a single predicate containing customer/deployment scope, category, market,
active/nondeleted/available state, explicit ingredient requirements/exclusions,
and price/currency constraints.

Apply equivalent predicates in lexical retrieval, efficient ANN filtering, and
authoritative post-hydration validation. Post-filtering a global ANN shortlist
alone is insufficient under restrictive filters. [OpenSearch filtering][S01]
describes the engine behavior; record any exact-search fallback and include it in
tail-latency tests.

### 6.2 Candidate generation

Baseline: indexed exact ingredient features and BM25 over source-grounded text.
Positive features must remain separate from exclusions; prohibited ingredients
must not accidentally become query boosts.

Optional variant:

1. Start lexical retrieval and query-embedding work concurrently.
2. Execute filtered ANN after the query embedding is ready.
3. Retrieve up to 100 candidates from each branch.
4. Deduplicate by canonical product ID and fuse rankings with RRF, initially
   equal weights and constant 60. [RRF reference][S02].
5. Retain at most 200 candidate IDs, with per-branch ranks recorded.

Engine internals may inspect more documents than returned. The guarantee is
bounded application transfer and inference work; ANN search effort is separately
bounded/tuned and measured. No mathematical constant-time search claim is made.

### 6.3 Hydration, reranking and selection

Hydrate the first 50 fused candidates from the authoritative product store.
Check canonical facts, eligibility and source revisions. If necessary, hydrate
one additional slice from the already-retrieved candidate list, for at most 100
distinct products per step. This refill does not trigger unbounded pagination.

Use strongly consistent canonical reads where supported. Handle batch partial
responses explicitly; retry only unprocessed keys within the same deadline.
Unprocessed keys must not be mistaken for nonexistent or ineligible products.
See [DynamoDB BatchGetItem][S09].

For each hydrated item:

- A deleted, inactive, disallowed, unknown-constrained or missing product is excluded.
- A changed price/availability is evaluated from the current canonical record.
- An embedding/content revision mismatch cannot provide claimed current semantic
  evidence. Drop that semantic contribution or the candidate under a qualified
  deterministic policy; record the event.
- A newer canonical content record may participate in the lexical baseline only
  under the qualified current-text scoring policy; do not silently reuse a stale
  reranker explanation.

Keep up to 50 eligible hydrated candidates for optional reranking. The reranker
receives only current source-grounded text and validated query context. Rank
scores never bypass eligibility. Preserve the same candidates when comparing
rerankers experimentally.

Select up to three eligible products above the configuration's development-set
qualified relevance policy. Thresholds are method/category-specific where
necessary; BM25, cosine, RRF and reranker scores cannot share an arbitrary numeric
cutoff. Validate abstention separately. Do not pad with zero-evidence products.

### 6.4 Explanation and whole-routine binding

The product agent explains server-selected IDs; it does not replace, reorder or
extend the approved list. Keep product facts and explanatory text in separate
models. The binder validates request/step identity, exact approved IDs and order,
source revisions and configuration IDs.

Before final serialization, revalidate the small selected set if generation took
long enough to outlive the selection validity window. Default: revalidate at
finalization, with no more than 24 selected products for eight steps. If a product
is no longer eligible, remove it and regenerate/omit its explanation; do not
perform an unbounded second recommendation cycle.

The result is accurate at that final validation point, not an inventory reservation.

The compiler validates all planned steps and applies reviewed cross-step rules.
Rule sources and versions must be explicit. If a customer has not supplied a
qualified compatibility policy, the product must not claim automated clinical
compatibility. Technical invariants—scope, user exclusions, consistency and
binding—remain mandatory.

## 7. Ingestion, updates and recovery

### 7.1 Default synchronization design

Use a versioned search-projection table as the single index source. A projection
worker normalizes canonical product changes and owns projection writes. OpenSearch
Ingestion synchronizes that projection table to the search domain.

The canonical-change capture path MUST journal events durably with at least
seven days of replay before acknowledgement. The queue/journal is part of the
ingestion work package. DynamoDB Streams' own retention is not sufficient as a
seven-day recovery log.

OpenSearch Ingestion supports snapshot plus CDC and documents acknowledgements
and change reconciliation. Its DynamoDB integration has same-region/account and
single-source-table constraints. It also documents a 24-hour stream retention
hazard for long snapshots. [AWS ingestion documentation][S03].

The projector and journal are new components; this design is not "zero
application work" merely because the last synchronization stage is managed.

### 7.2 Event processing

1. Validate identity, revision and source completeness. Quarantine invalid data
   with reasons; do not silently drop a failed row.
2. Resolve canonical ingredients and construct deterministic retrieval text.
3. Publish updated lexical/eligibility attributes promptly.
4. Reuse an embedding only if its content hash and model revision match.
5. For changed content, mark the embedding pending; clear or exclude stale vectors
   from the ANN path while retaining qualified lexical visibility.
6. On embedding completion, commit only if source revision, content hash and model
   revision still match. The commit must atomically check the authoritative revision.
7. Apply monotonic projection revision checks to every writer, including retries.
8. Record successful index acknowledgement and freshness; retain replay evidence.

Deletions initially create versioned tombstones and make the product ineligible.
Retain tombstones for at least the journal/retry horizon before physical cleanup.
Late embedding completions and replayed updates cannot resurrect a deleted record.
Canonical hydration protects final results during ordinary index lag.

Do not permit two independent writers to patch the same OpenSearch document
without a qualified version/merge protocol. Embedding completion and catalog
updates otherwise race.

### 7.3 Backfill and reconciliation

Backfill into a new index generation using a consistent catalog snapshot and a
documented CDC boundary. Buffer/journal subsequent changes, catch up, and reconcile
counts, revisions, deletions and sampled content hashes before serving.

A stream-retention gap invalidates incremental completeness. Rebuild/reconcile
from the source snapshot; do not mark the new generation healthy after simply
restarting a consumer.

Initial targets: lexical p95 freshness 30 seconds; changed-content embedding p95
freshness five minutes; at least 99% eligible embedding coverage when enabling
the ANN configuration. Exact definitions and outage behavior are in verification.

Run daily catalog reconciliation and a full rebuild drill. A million-product
rebuild target is 12 hours, including snapshot/export, embedding when needed,
index construction and catch-up. Record model-token and inference capacity needed
to meet this target instead of assuming embeddings are free.

### 7.4 Reindex and rollback

Keep immutable generation names. Freeze a generation for each routine so its
steps do not cross different mappings/models.

Cutover uses an atomic alias update that removes the alias from the old index and
adds it to the new index. **Do not use an index-deletion action for cutover.**
[OpenSearch alias operations][S04].

Keep the old generation queryable and updated during the seven-day rollback
window, or replay it to a qualified freshness point before rollback. An old stale
index is not a safe rollback merely because it exists. Keep old model/configuration
versions available for in-flight routines.

## 8. Latency, concurrency and degradation

Step search has a proposed 1,200 ms hard deadline. Reserve explicit stage budgets:
query embedding 200 ms; search 250 ms after embedding; hydration 150 ms; reranking
400 ms; selection/binding 50 ms; residual budget for scheduling and bounded retries.
These are starting upper budgets, not separate p95 promises. Deadline propagation
and measured end-to-end percentiles decide whether the configuration qualifies.

For the routine retrieval wave, target p99 at most 1,500 ms and a 1,600 ms hard
deadline, including step scheduling. Do not add parallel step durations to
estimate routine latency. At six/eight steps, bound per-runtime and deployment-wide
concurrency so a single routine cannot monopolize inference capacity.

| Failure | Required behavior |
|---|---|
| Embedding or ANN unavailable | Use the already-completed, healthy lexical baseline if that fallback configuration passed release gates |
| Reranker unavailable/late | Use the qualified fused or lexical ordering; no new model call loop |
| Required index shards fail/timeout | Reject partial results; use an independently healthy qualified baseline only if available, otherwise return service error |
| Canonical store unavailable/partial hydration unresolved | Return service error; cannot trust source facts |
| Ingestion hard-stale over five minutes | Disable the affected search generation; use an independently healthy generation or return service error |
| No eligible products in healthy fresh index | Explicit no-match, never an infrastructure error |
| Completed search below relevance threshold | Explicit insufficient-relevance no-match |
| Explanation model unavailable | Use qualified factual template explanation or omit generated advice; preserve selected catalog facts |
| User cancels/disconnects | Cancel downstream work where supported; do not emit late success or leak state to another routine |

Allow at most one additional remote attempt per step across the retrieval stages,
including nested SDK retries, within the original deadline. Finalization has a
separate routine-level budget of one retry, bounded by the routine deadline.
Retry storms are prevented by bounded concurrency, backoff and circuit breaking.
Do not fall back
to DynamoDB category scans at customer scale.

Normal steady-state fallback must remain below 1%; otherwise the expensive
configuration is not actually meeting its serving contract.

## 9. Network, authorization and data handling

Deploy the search domain, projection workers and inference access within the
intended private boundary. Runtime, ingestion and administration roles are
separate. The runtime can search/read and hydrate authorized products; it cannot
write mappings/documents or manage aliases.

The current AgentCore network mode is PUBLIC. Access to a private domain requires
verified private connectivity. Proposed default: AgentCore VPC mode with private
subnets, scoped security groups, DNS, service endpoints and controlled egress.
This affects ECR/S3 image loading, logs, Bedrock and DynamoDB connectivity as well
as search. [AgentCore VPC requirements][S05].

Use native IAM/SigV4 service authentication. Preserve the existing authenticated
API proxy boundary. Test source role, action and catalog access—not merely the
presence of an authorization header. No browser-to-search-domain access.

Raw photos and identity attributes are not search documents or product embeddings.
Use pseudonymous evaluation/profile IDs. Retention of profile traces, judgments
and inference payloads must follow the customer's agreed data policy.

Cache keys include catalog, market, constraints, normalized profile/query,
configuration, policy and generation. Disable cross-user personalization caching
unless the key accounts for every input. Final canonical checks still apply to
cached candidate IDs. Report cache-on/off performance separately.

## 10. Observability and configuration

Capture a trace per routine and child spans for planning, retrieval branches,
hydration, reranking, explanation and compilation. Record:

- Offered/admitted/completed routine traffic and logical step/branch rates.
- Stage and user-visible latency histograms; deadlines, queueing, cancellation.
- Candidates at each stage, drops by reason, shard completeness, fallback reasons.
- Canonical/index revision mismatches, embedding coverage and projection lag.
- Ingestion acknowledgements, oldest event age, dead-letter depth, reconciliation
  differences, tombstone/replay progress.
- Model requests, input/output tokens, rerank pairs, throttles and utilization.
- No-match, false-abstention audit samples, constraint/binding failures.
- Cost allocation tags and recorded pricing snapshot.

Avoid raw profile/ingredient text as high-cardinality metric dimensions. Sensitive
trace details require access controls and retention limits.

Replace `has_products()` scanning on each request with a lightweight readiness
record indicating healthy generation, ingestion health and catalog readiness.
Readiness is not evidence that a particular query has a match.

Configuration promotion must be reversible without a code deployment. Implement
customer/deployment-specific canary assignment, model/index rollback and independent
fallback toggles. Do not let a client request turn on an experimental configuration.

## 11. Sources and implementation verification

All sources were consulted on 2026-10-22. G0 MUST check selected versions/regions
and capture exact syntax from official documentation before writing provider code.
There is no requirement to adopt the newest engine or SDK.

[S01]: https://docs.opensearch.org/latest/vector-search/filter-search-knn/efficient-knn-filtering/
[S02]: https://docs.opensearch.org/latest/vector-search/ai-search/hybrid-search/rrf/
[S03]: https://docs.aws.amazon.com/opensearch-service/latest/developerguide/configure-client-ddb.html
[S04]: https://docs.opensearch.org/latest/api-reference/alias/aliases-api/
[S05]: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html
[S08]: https://docs.aws.amazon.com/bedrock/latest/userguide/rerank-supported.html
[S09]: https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_BatchGetItem.html
