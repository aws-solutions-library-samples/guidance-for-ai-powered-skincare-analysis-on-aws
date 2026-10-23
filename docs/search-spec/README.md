# Scalable product recommendation search

**Status:** proposed specification, ready for implementation planning.

**Date:** 2026-10-23.

**Scope:** recommendations from a skin profile, from thousands to millions of products.

**Agreed planning assumption:** 20 incoming routines/second.

**Planning team:** two experienced engineers, with part-time search, operations,
and product/domain review support. These are estimates, not delivery commitments.

## Decision and effort

Build an indexed search layer that retrieves a bounded candidate pool. Keep the
canonical product store and server-side product binding. Ship a filtered lexical
baseline first; qualify semantic retrieval and reranking through the same tests.
Promote additional ranking stages only when their quality benefit justifies their
latency and cost.

This is a moderate application change and a substantial data/evaluation/operations
change. Replacing the score function alone does not meet the scale requirement.

| Deliverable | Cumulative engineering effort | Indicative elapsed time with two engineers | What the milestone establishes |
|---|---:|---:|---|
| Indexed MVP | 20–30 person-days | 3–4 weeks | Working bounded lexical search, initial synchronization, preferences and explicit no-match handling in a test environment |
| Customer-scale validation candidate | 45–65 person-days | 6–9 weeks | Hybrid/reranking experiments, representative index, independent evaluation pipeline, capacity/resilience evidence |
| Production release | **71–108 person-days** | **9–13 weeks** | Operational ingestion, release gates, rollback, monitoring, complete application integration and controlled rollout |

Milestones overlap and are cumulative; do not add their estimates together.
The production range includes approximately 20% engineering contingency. It assumes
one customer deployment, one region, an available catalog feed, and existing
photo-analysis behavior. Data cleanup, unfamiliar infrastructure, restrictive
model quotas, and waiting for domain judgments can extend elapsed time.

Domain review is additional work, potentially a critical path. A planning example
of 400 profiles × three steps × 20 pooled products yields 24,000 judgments.
At 45 seconds per judgment that is 300 hours; 25% double review adds 75 hours,
before rubric calibration and adjudication. Budget about **50–65 reviewer-days**
for that example, distributed across qualified reviewers. A timed pilot determines
the actual volume and rate. More labels are required if power analysis or judgment
coverage shows the sample is insufficient.

Labeling all six typical steps under the same assumptions doubles this to
**100–120 reviewer-days** including calibration/adjudication. Pools can exceed
20 distinct products per step. The delivery plan makes these cost drivers explicit.

See [delivery plan](delivery.md) for the work breakdown, staffing, dependencies,
and alternative scope choices.

## Specification package

| Document | Contents |
|---|---|
| [Technical specification](technical.md) | Requirements, architecture, product/profile contracts, ingestion, retrieval, ranking, failure semantics, application changes, security and observability |
| [Testing and evaluation strategy](verification.md) | Test cases, independent relevance judgments, statistical analysis, ANN recall, load/resilience tests, cost measurement and release gates |
| [Delivery and migration plan](delivery.md) | Person-day estimates, implementation work packages, file impact, milestones, rollout and rollback |
| [Acceptance targets](acceptance-targets.yaml) | Proposed numerical targets and workload assumptions; source of truth for numbers repeated in the documents |

The numerical gates are proposed engineering/product targets, not claims about
measured performance or industry-wide standards. Freeze them at milestone G0
before judging candidate configurations. The cost ceiling remains a customer
decision and is a release dependency.

## Scale contract

Initial qualification is for **one million active products per customer**, with
1k, 10k and 100k checkpoints. A 10-million-product run is an extension; success at
one million does not authorize a claim about ten million.

At 20 routines/second, six steps per routine, and the starting search configuration:

| Work item | Nominal rate or bound |
|---|---:|
| Logical step searches | 120/second |
| Lexical plus ANN branches | 240 branch executions/second |
| Query embeddings without reuse | Up to 120/second |
| Cross-encoder pairs at 50 candidates per step | 6,000/second |
| Candidate IDs returned to application | At most 200 per step |
| Authoritative product hydration | At most 100 distinct products per step |
| Final user-visible recommendations | At most three products per step |

These counts exclude upstream LLM calls, generated explanations, retries, refresh
traffic and shadow evaluation. A six-step routine currently has 14 agent nodes
before compilation; agent nodes are not equivalent to individual model calls.
Measure actual tool loops and inference token/request rates.

The same admission rate must also be exercised with the supported eight-step
maximum: 160 step searches/second and up to 8,000 reranking pairs/second.
Capacity decisions must include that case.

## What will count as evidence

Release requires all three:

1. **Correctness:** request constraints, canonical product facts, valid no-match
   handling, consistent synchronization, isolation and fault behavior.
2. **Recommendation quality:** independently reviewed product and routine judgments
   from profile-only inputs, with a frozen test set and uncertainty reported.
3. **Serving performance:** the actual deployed path meets latency, throughput,
   freshness and cost gates against a representative million-product index.

The existing [local experiments](../../experiments/search/README.md) remain useful
for regression tests and metric checks. Their 48 fictional products, manually
supplied ingredient targets, and assistant-authored judgments are not release
evidence. Unit-test counts and public vendor benchmarks do not replace these gates.

## Principal changes

- Replace per-request DynamoDB category enumeration with an OpenSearch-backed
  retrieval adapter.
- Materialize ingredient availability during ingestion; preserve access to rare
  ingredients without passing a full taxonomy to an LLM.
- Add explicit, validated user preferences; do not infer budgets or exclusions
  from photographs.
- Add `matched` and `no_match` step outcomes across backend, SSE, compiler and UI.
- Make search ranking deterministic for a fixed configuration; use the product
  agent to explain server-selected products.
- Synchronize product updates, deletions, availability and embeddings with version
  checks, reconciliation and reindex recovery.
- Preserve bounded authoritative product hydration and server-side binding.
- Qualify optional ANN and reranking on the full indexed catalog.
- Add production load generation, judgments, failure injection and release reports.

## Scope boundaries

Included: one customer/region deployment, catalog search, per-product price limits,
explicit ingredient requirements/exclusions, standard availability and market
filters, optional semantic retrieval/reranking, routine assembly and the evidence
needed to release them.

Deferred: a shared multi-tenant SaaS control plane, training a new embedding model,
learning-to-rank from clicks, a global routine-budget optimizer, checkout,
inventory reservation, and redesigning the vision model. Clinical suitability
rules require a reviewed domain policy; this work does not create medical evidence
from ingredient lists or model explanations.

Search-boundary tests use frozen skin profiles to isolate this change. Full-system
tests still exercise the existing photo-to-profile path and report its contribution
to final recommendation errors.

## Outstanding decisions

| Decision | Proposed default | Required by |
|---|---|---|
| Peak routine traffic | 20/second, user-approved planning assumption | Already set for planning |
| Peak product count | 1 million active products | G0; validate customer expectation |
| Primary region and residency | One supported region matching customer requirements | G0 |
| Deployment | Private provisioned OpenSearch Service domain for initial reproducible qualification | G0 |
| Model provider | Managed AWS embedding/reranking interfaces; pin compatible region/model revisions after evaluation | G0/G2 |
| Canonical customer feed and SKU identity | Stable supplier IDs, explicit revisions and delete semantics | G0 |
| Cost ceiling | Not yet supplied; measure and agree ceiling per 1,000 completed routines plus monthly fixed cost | Before G3 exit |
| Relevance rubric and domain reviewers | Customer-approved rubric, independent judgments | Before G2 test-set freeze |
| Profile/routine completion targets | Proposed in acceptance targets | G0 |

## Official references

The detailed specifications link each relevant design choice to official sources:
OpenSearch filtering, RRF and aliases; AWS DynamoDB ingestion and AgentCore
networking; OpenSearch Benchmark; and BEIR/trec_eval evaluation conventions.
Selected service versions, model availability, quotas and
provider syntax must be verified again when implementation starts.
