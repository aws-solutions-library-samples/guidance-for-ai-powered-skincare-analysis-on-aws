# Delivery and migration plan

This plan implements the [technical specification](technical.md) and produces the
evidence defined in the [verification strategy](verification.md). Estimates are
planning ranges based on the current code, not measured implementation velocity.
No infrastructure sizing or ranking winner is established by this document.

## 1. Effort and staffing

The full scope is **59–90 engineering person-days before contingency**, or
**71–108 person-days with approximately 20% contingency**. One person-day means
eight hours of focused engineering work. Domain judgments are additional.

| Work package | Base person-days | Deliverables and exit evidence | Dependencies |
|---|---:|---|---|
| A. Discovery and contracts | 5–8 | Customer feed audit, stable identity, G0 capability check, request/result contracts, frozen planning targets | Customer feed sample and deployment requirements |
| B. Catalog projection and synchronization | 10–15 | Chunked import, revisions, normalization, durable change capture, embedding lifecycle, deletes, reconciliation and generation recovery | A |
| C. Indexed retrieval foundation | 8–12 | Private search deployment/connectivity, lexical adapter, filters, bounded hydration, ingredient lookup and readiness | A; fixture projection can unblock work before B finishes |
| D. Semantic retrieval and ranking experiments | 8–12 | Embedding adapter, filtered ANN, RRF, bounded reranking, model manifests and ablations | C and representative normalized product text |
| E. Application integration | 8–12 | Preferences, v1/v2 contracts, server-selected products, no-match, graph/SSE/compiler/UI binding | A; fixture adapter can unblock work before C finishes |
| F. Evaluation tooling | 8–12 | Judgment import/review workflow, production run capture, metrics, profile-cluster statistics and reproducible reports | A; reviewers and customer data |
| G. Capacity, resilience and cost qualification | 6–10 | Open-loop load tests, ANN oracle, million-product runs, faults, freshness/rebuild results and cost report | B–F; cloud capacity and model quotas |
| H. Release and operational hardening | 6–9 | Deployment checks, dashboards/alarms, runbooks, shadow/canary controls and rollback rehearsal | G and release approval evidence |
| **Base total** | **59–90** | | |
| **Including contingency** | **71–108** | | |

Package F covers building and operating the evaluation workflow, not authoring
tens of thousands of domain judgments. Package G includes planned qualification
and bounded tuning; substantial failures requiring redesign consume contingency
or require a revised estimate.

Indicative staffing:

- Engineer 1: catalog, ingestion, private deployment, capacity and operations.
- Engineer 2: retrieval, application contracts, evaluation and experiment analysis.
- Part-time search/operations support for engine tuning and capacity review.
- A product/domain owner plus independent reviewers for the rubric and judgments.

With two engineers, plan **9–13 elapsed weeks** for the production scope, assuming
data, reviewers and quotas arrive in time. With one engineer, the engineering work
alone is approximately 14–22 full-time weeks; dependency waiting and release
observation can extend this. Adding engineers does not remove labeling, data
readiness or observation-period dependencies.

## 2. Milestones and scope options

Milestone efforts below are cumulative and already reflected in the total.
They must not be summed.

| Milestone | Cumulative person-days | Indicative elapsed time with two engineers | Exit condition |
|---|---:|---:|---|
| G0: decisions and contracts | 5–8 | Week 1 | Owners accept the workload, feed/identity strategy, region/capabilities, proposed targets and review plan |
| G1: indexed MVP | 20–30 | Weeks 3–4 | Bounded lexical search and initial projection work in a test environment; preferences/no-match and canonical binding pass contract tests |
| G2: quality-qualified candidate | Part of the 45–65 range below | Weeks 5–7, subject to judgments | Frozen comparisons identify a candidate that passes absolute quality, constraint and statistical gates |
| G3: customer-scale validation candidate | 45–65 | Weeks 6–9 | Representative million-product index passes serving, freshness, recovery and cost gates |
| G4: production rollout | 71–108 | Weeks 9–13 | Operational hardening, compatibility, shadow/canary and rollback evidence accepted |

G1 is not a million-product or production claim. G2 can select the lexical
baseline if it passes the absolute quality gates; ANN and reranking are optional.
If no method passes the quality gates, the release remains blocked while the
catalog, query planner, relevance policy or ranking is improved.

### Smaller first delivery

An indexed lexical MVP is the fastest useful first change: **20–30 person-days**.
It establishes bounded retrieval, filters, authoritative product facts and valid
no-match handling. Customer deployment still requires the applicable data,
quality, capacity and operational gates.

If lexical retrieval meets the customer quality target, omit production ANN/
reranking and reduce the associated embedding/inference operations. Package D is
8–12 base days; some comparison work is still necessary to justify that choice.
Do not subtract all of B, F or G: synchronization, independent relevance evidence
and load testing remain required.

### Thousands versus millions

For 1k–10k products, qualify the same lexical adapter at a smaller checkpoint.
Exact vector retrieval can be an experiment at this size, but benchmark its actual
CPU/latency and do not use it as the million-product implementation.

At one million products, use inverted-index retrieval, filtered ANN if qualified,
bounded transfer/hydration and bounded reranking. Engine work and memory still
depend on corpus size, filter selectivity, vectors, shards and traffic. The
20-routines/second workload also includes agent/model concurrency independent of
catalog size. A small catalog does not eliminate the inference bottleneck.

Provisioned OpenSearch has fixed operating cost. At thousands of products, measure
whether that cost is acceptable; if the customer already operates another suitable
index, evaluate it through the same adapter and gates. An alternative backend is
a scoped design change, not assumed equivalent.

Qualifying ten million products, multiple regions or a shared customer platform
requires a new capacity/operations estimate. This plan does not extrapolate a
passing one-million run to those cases.

## 3. Reviewer effort and data readiness

Run a timed, blind review pilot before reserving the full label budget. Measure
deduplicated pool size, judgment time, agreement, unjudgeable products, profile
variance and adjudication rate.

The following examples use 400 total development/test profiles, **20 distinct
pooled products per evaluated step after deduplication**, 45 seconds per judgment,
25% independent double review, and eight-hour reviewer-days:

| Coverage example | Initial judgments | Initial + double-review hours | Planning allowance including calibration/adjudication |
|---|---:|---:|---:|
| Three evaluated steps per profile | 24,000 | 375 | 50–65 reviewer-days |
| All six typical steps per profile | 48,000 | 750 | 100–120 reviewer-days |

These are illustrations, not a cap on the evaluation. Pooling top 20 results from
six methods can yield substantially more than 20 distinct products per step.
The required 99% top-10 judgment coverage, power analysis, critical-slice coverage
and routine-level review determine the final workload. Full image-to-routine
assessment adds work. Partial step sampling must be declared in the metric
population; it cannot support a claim about unreviewed full routines.

To reduce effort responsibly, use shared deduplicated pools, staged elimination
on development data, source evidence alongside each product, and review tooling.
Use active selection to prioritize additional labels, while preserving a
representative frozen test population. Do not replace independent judgments with
ingredient-overlap labels or a single uncalibrated LLM judge.

Required customer inputs:

- A representative catalog export and documented changes/deletes, stable supplier
  IDs, field completeness and rights to use the data for evaluation.
- Category/ingredient taxonomy, supported markets/currencies and reviewed policy.
- A rubric owner, reviewers and representative profile/preferences cases.
- Region/residency requirements, model access, expected catalog/update distribution.
- A cost ceiling per 1,000 completed routines and monthly fixed infrastructure.

The agreed traffic assumption is 20 routines/second. Product count, update rates,
latency targets and cost ceilings still need customer confirmation at the stated
gates. Engineering can proceed on fixtures and contracts while these are resolved;
customer-quality and production-release claims cannot.

## 4. Implementation sequence

1. **Freeze the baseline.** Record the current revision plus a patch hash for any
   uncommitted work, existing regression results, catalog snapshot and fixture
   limitations. No Git commit is required to create this record.
2. **Agree G0 contracts and capability matrix.** Verify selected engine/model
   features, region availability, IAM, VPC access, provider limits, quotas and
   pricing from official documentation. Confirm product identity and event order.
3. **Create the test-only data plane.** Deploy private search and ingestion,
   validate denied unauthorized access, import the oracle catalog, and verify
   revisions/deletions. Keep the current user-facing route until the new path is
   ready for controlled qualification.
4. **Implement the lexical vertical slice.** Validated profile/preferences through
   search, canonical hydration, server selection, explanation, compiler and UI.
   Add no-match and operational-error behavior together.
5. **Complete synchronization.** Add durable replay, asynchronous embeddings when
   enabled, reconciliation, freshness readiness and generation rebuild/cutover.
   Prove deletes and out-of-order events before representative catalog import.
6. **Build evaluation in parallel with the slice.** Validate metrics against hand
   examples, run the review pilot, freeze splits and create reproducible run
   manifests. Independent labels must be ready for G2.
7. **Compare ranking methods.** Development sweeps and ablations narrow the field;
   freeze the candidate, thresholds and fallback before the confirmatory test.
8. **Qualify the actual deployment.** Full-index ANN recall, search/routine load,
   update churn, faults, rebuild, model quotas and measured cost. Rerun only
   affected gates after a change; retain all failed-run evidence.
9. **Release through shadow and canary.** Follow the staged procedure below and
   document the selected configuration and operational limits.

## 5. File and module impact

The new paths below are proposed implementation locations. They do not describe
files implemented by this specification-only change.

| Existing or proposed location | Planned responsibility |
|---|---|
| `agents/search/contracts.py` — new | Validated request/result models and provider-neutral adapter contract |
| `agents/search/eligibility.py` — new | Canonical constraint semantics and reviewed taxonomy handling |
| `agents/search/opensearch_adapter.py` — new | Approved lexical/ANN templates, fusion, deadlines and stage traces |
| `agents/search/inference.py` — new | Pinned embedding/reranking adapters, quotas, deadlines and fallbacks |
| `agents/product_repository.py` | Bounded authoritative ID reads; retire request-time category scoring and availability enumeration |
| `agents/tools.py` | Materialized ingredient lookup and typed search tool; distinguish no-match from errors |
| `agents/models.py`, `agents/input_validation.py` | v2 preferences and outcomes; preserve v1 acceptance; generated fields separate from product facts |
| `agents/errors.py`, `frontend/src/utils/analysisErrors.ts` | v1 terminal domain-outcome compatibility and versioned presentation |
| `agents/catalog_binding.py` | Request/step/configuration/revision binding, approved order and final canonical checks |
| `agents/orchestrator.py`, `agents/compile_node.py` | Frozen context, bounded concurrency, no-match assembly, cancellation and routine validation |
| `agentcore_entrypoint.py`, `config.py` | Versioned request propagation, readiness, runtime configuration and streaming outcomes |
| `prompts/product_agent_prompt.txt` and ingredient prompt | Explain approved products; ingredient planning is soft and cannot alter hard constraints |
| `api_proxy/handler.mjs` | Matching v1/v2 validation and authenticated request handling |
| `frontend/src/utils/api.ts`, `frontend/src/types/index.ts` | Preferences request and outcome types |
| `frontend/src/utils/analysisData.ts`, `frontend/src/hooks/useAnalysis.ts` | Compatible streamed-state parsing and terminal matched/no-match/error handling |
| Frontend preference and result components — new/updated | Bounded preference entry/review and explicit no-match presentation |
| `catalog_pipeline/` — new | Feed normalization, revision ledger/projection, embedding completion, tombstones and reconciliation |
| `scripts/migrate_products.py` | Chunked supplier import, stable-ID migration and resume/quarantine reporting |
| `scripts/search/` — new | Generation build, catch-up, validation, cutover and rollback operations |
| `experiments/search/` | Production adapters, dataset/run manifests, judgments, metrics, statistical decisions and fault/load drivers |
| `tests/unit/`, `tests/integration/`, frontend tests | T01–T11 coverage and real-engine fixtures |
| `terraform/search.tf`, `terraform/catalog_pipeline.tf` — new | Private index, projection/replay resources, ingestion and operational signals |
| `terraform/dynamodb.tf`, `terraform/iam.tf` | Product/projection state, streams, bounded reads and separate writer/admin permissions |
| `terraform/agentcore.tf`, network configuration — new/updated | Runtime private connectivity, endpoints, packaging/hashing of new runtime modules |
| `pyproject.toml`, `uv.lock`, deployment scripts | Verified dependencies and deploy order; exclude experiment data/model caches from runtime |
| `docs/architecture.md` and operational docs | Update to the implemented architecture after qualification; add runbooks and evidence links |

Provider code must use verified official APIs for the chosen versions. Proposed
module names are not reasons to rewrite unrelated current work.

## 6. Release and rollback

### 6.1 Compatibility and migration

- Publish v2 request/result handling before enabling v2 preference controls.
  Keep v1 acceptance and parsing tests throughout the transition.
- Backfill stable product IDs with an explicit old-to-new mapping. Validate counts,
  categories, source revisions, eligibility and representative product facts.
- Build a versioned index while capturing changes; verify catch-up and freshness.
- Validate the new generation before atomic alias cutover. The operation removes
  the old **alias association**, not the old index.
- Pin the selected configuration/generation for each routine. In-flight work
  finishes consistently or returns a defined error; it does not silently mix
  generations.
- Keep the previous compatible generation available and updated for at least
  seven days, or demonstrate replay/catch-up within the five-minute rollback
  target. Retaining an old but stale index is not a working rollback.

### 6.2 Shadow and canary

Start shadow traffic at 1%; increase to at most 5% only after checking its additional
index, hydration and inference load. Shadow output is captured for comparison and
does not change the visible recommendation. Apply the same retention policy.

Roll out to 1%, 5%, 25% and 100% using stable server-side assignment. Each stage
requires at least 24 hours and 1,000 completed routines; both conditions apply.
Inspect quality samples, no-match/fallback rates, constraints, latency, errors,
freshness, cost and browser completion. Low traffic extends observation time.
Do not silently loosen thresholds to complete a stage.

Production interaction signals are secondary to reviewed relevance. If traffic
permits a randomized online comparison, preregister a user-level outcome
(for example, routine acceptance/save), guardrails, allocation and a power-based
sample/horizon. Analyze assignment rather than only successful completions.
Clicks alone do not establish product suitability or clinical efficacy.

### 6.3 Rollback triggers and actions

Immediately stop promotion for any confirmed catalog-scope leak, hard-constraint
violation, fabricated product fact, critical routine-policy failure or deletion
resurrection. At nominal load, also stop for sustained service/freshness/SLO
breaches. At G0 freeze alert evaluation windows; proposed default for sustained
operational breaches is two consecutive five-minute windows.

Use the following order when applicable:

1. Disable the optional failing ANN/reranking stage only if its fallback was
   independently qualified and all constraints remain enforced.
2. Restore the last compatible configuration/index generation and verify
   freshness, schema compatibility and canonical binding.
3. Revert the application release if needed, retaining v1/v2 compatibility.
4. If no healthy qualified path exists, return an explicit unavailable outcome
   and halt admission as needed.

The category-scan legacy implementation is not a fallback at million-product
scale. Rollback must be exercised under updates and in-flight routines before G4.
Target recovery is within five minutes for configuration/index rollback; record
actual application rollback time separately.

### 6.4 Runbooks and ownership

Assign owners and escalation paths for ingestion lag/gap recovery, quarantine,
model throttling, search saturation, rebuild/cutover, deletion correctness,
relevance regression and cost overspend. Each runbook includes detection, bounded
mitigation, verification and the condition for restoring normal operation.

G4 hands over dashboards, configuration/model manifests, evaluated limits,
remaining risks, data/judgment retention and rollback evidence. The acceptance
report records the actual selected method; this plan does not predeclare hybrid
search the winner.

## 7. Definition of done

Production completion requires G0–G4 evidence, not just merged code:

- Traceable R01–R18 requirements and passing applicable T01–T11 tests.
- A frozen independently judged dataset and reproducible B0–B5 comparisons
  sufficient to justify the selected configuration.
- Absolute relevance, statistical, constraint, routine and abstention gates.
- Million-product, 20-routines/second evidence including the eight-step case,
  zero result-cache gating, updates, faults and cost.
- Demonstrated freshness, deletion correctness, rebuild and rollback.
- Compatible frontend/API behavior and actual browser-to-result timing.
- An agreed cost ceiling, operational ownership and completed controlled rollout.

The current specification delivers the plan and acceptance criteria only.
Implementation, customer judgments, load tests and deployment remain future work.

## 8. Official implementation references

- [OpenSearch efficient vector filtering](https://docs.opensearch.org/latest/vector-search/filter-search-knn/efficient-knn-filtering/)
- [OpenSearch reciprocal rank fusion](https://docs.opensearch.org/latest/vector-search/ai-search/hybrid-search/rrf/)
- [OpenSearch atomic alias operations](https://docs.opensearch.org/latest/api-reference/alias/aliases-api/)
- [DynamoDB integration with OpenSearch Ingestion](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/configure-client-ddb.html)
- [AgentCore runtime VPC connectivity](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html)
- [Supported Bedrock reranking regions/models](https://docs.aws.amazon.com/bedrock/latest/userguide/rerank-supported.html)
- [DynamoDB BatchGetItem behavior](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_BatchGetItem.html)

Consulted 2026-10-22; recheck chosen versions, region capabilities and syntax at G0.
