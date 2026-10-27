# Delivery and migration plan

Version 2.0, 2026-10-26. Implements the selected exact-count method. It replaces
the earlier hybrid/embedding plan and its estimates. These ranges are engineering
planning judgments, not measured velocity or commitments.

## 1. Effort and milestones

One person-day is eight focused engineering hours. Reuse the existing app,
research oracle/query logic and regression evidence, but implement the production
adapter independently of experiment scripts.

| Package | Base person-days | Deliverable and exit evidence |
|---|---:|---|
| A. Contracts and feed audit | 3–4 | Ingredient/identity mapping, v2 constraints/outcomes, deployment policy and fixed targets |
| B. Canonical publication and projection | 7–10 | Streaming import, stable-ID migration, transactional outbox, ordered index writes, discovery, deletes/reconciliation |
| C. Exact search and private infrastructure | 5–7 | Private index/connectivity, query/filter adapter, bounded hydration and readiness |
| D. Application integration | 7–10 | ID-based ingredient plan, deterministic selection, server binding, v2 API/SSE/compiler/preferences UI |
| E. Correctness and integration evidence | 4–6 | Independent exact oracle, real-engine tests, update/fault contracts, data/planner review harness |
| F. Deployment capacity and cost | 5–8 | Application-search/full-routine load, soak, updates, rebuild, resource and cost report |
| G. Release and operations | 5–9 | Packaging, dashboards, runbooks, shadow/canary and rollback drill |
| **Base total** | **36–54** | |
| **Including approximately 20% contingency, rounded** | **44–65** | |

Product/domain review time is additional and starts with a bounded representative
sample defined in [verification.md](verification.md). There is no fixed budget for
large semantic-ranking judgment pools or embedding/reranking infrastructure.
Existing photo/planner shortcomings, difficult registry cleanup or unsupported
feed ordering can require separately scoped work.

| Milestone | Cumulative effort | Indicative elapsed time with two engineers | Exit |
|---|---:|---|---|
| G0 — Contracts ready | 3–4 days | Week 1 | A and fixture assumptions recorded |
| G1 — Integrated test MVP | 15–22 days | Weeks 2–3 | Exact-search vertical slice, imported fixture catalog, no-match and authoritative binding |
| G2 — Deployment candidate | 30–44 days | Weeks 4–6 | Live publication/recovery, real app capacity and cost evidence, critical contract tests |
| G3 — Production release | 44–65 days | Weeks 6–9 | Full acceptance evidence, observation periods and rollback/operations handover |

Milestone efforts are cumulative: do not add them. G1 is not production capacity
qualification. G2/G3 require the remaining applicable work packages; milestone
ranges are scheduling estimates, not different definitions of done.

Engineer 1 can own catalog/private infrastructure/operations; engineer 2 can own
search/contracts/app/verification. Two-engineer elapsed estimates allow dependency
and rollout time. One engineer needs roughly 9–13 full-time engineering weeks,
plus external waiting/observation. Data readiness, quotas or major gate failures
can extend either estimate.

## 2. Implementation order

1. Record the baseline revision plus any working-tree patch hash; no commit is
   needed. Preserve the completed study and old-ID migration map.
2. Define contracts and registry fixtures. Separate preferred/must-have/excluded
   IDs, decide catalog versus purchasable mode and define explicit unknowns.
3. Build the exact vertical slice in a test environment: private index, fixed query,
   bounded canonical reads, server-selected result and no-match.
4. Integrate ingredient IDs, discovery, explanations, compiler, validators and v2
   browser behavior. Keep all explicit constraints in trusted server state.
5. Complete live publication/outbox, discovery summaries, revision/tombstone rules,
   readiness, generation build/catch-up and retained-generation updates.
6. Run exact oracle and adversarial integration tests against the selected engine;
   verify customer feed identity/field evidence and review planner/output behavior.
7. Qualify actual application-search and full-routine boundaries at one million
   products/20 routines per second, including updates, faults, soak, rebuild and cost.
8. Deploy compatible clients, shadow the new path, then canary and rehearse rollback.
   Enable production only with the required evidence and deployment authorization.

There is no model sweep or semantic research phase. A new weighting objective,
family substitution or free-text product search would need a separate explicit
product decision, not a hidden extension of this work.

## 3. Repository change map

The table records planned responsibilities; actual paths and outstanding work are
tracked in [implementation status](implementation.md). It is not a completion report.

| Path | Planned responsibility |
|---|---|
| `agents/search/contracts.py` — new | Validated internal requests, selections and outcomes |
| `agents/search/eligibility.py` — new | Exact identity/constraint predicate and match metadata |
| `agents/search/opensearch_adapter.py` — new in this checkout | Fixed query, deadlines, response checks and ordered candidate IDs |
| `agents/search/service.py` — new | Bounded canonical reads/refill, selection and no-match semantics |
| `agents/product_repository.py` | Bounded ID reads; remove runtime category scorer/discovery/readiness scans |
| `agents/tools.py` | Bound discovery/registry lookup and trusted step results |
| `agents/models.py`, `agents/ingredients_analysis_agent.py` | Canonical IDs, explanation-only model outputs and v2 compiled outcomes |
| `agents/product_agent.py`, `prompts/product_agent_prompt.txt` | Explain server selections, no product selection or reordered IDs |
| `prompts/ingredients_analysis_prompt.txt` | Separate preferences from hard constraints; rare exact-ID discovery |
| `agents/catalog_binding.py` | Approved order, request/step ownership, facts and revisions |
| `agents/orchestrator.py`, `agents/compile_node.py` | Deterministic selection, mixed no-match, final reads, cancellation |
| `agents/input_validation.py`, `agentcore_entrypoint.py` | v1/v2 allowlist, preference propagation and outcomes |
| `agents/errors.py`, `api_proxy/errors.mjs` | Separate domain no-match/validation and operational errors |
| `api_proxy/handler.mjs`, registry/options route — new | Matching payload bounds, preferences and authenticated bounded lookup |
| `frontend/src/types/index.ts`, `frontend/src/utils/api.ts` | Versioned request/outcome types and lookup client |
| `frontend/src/utils/analysisData.ts`, `frontend/src/hooks/useAnalysis.ts` | Streaming state, no-match and terminal errors |
| `frontend/src/utils/analysisErrors.ts`, result/preference components | Factual counts, constraint review, sparse/no-match display |
| `catalog_pipeline/` — new | Canonical publisher/outbox, normalization/registry, leases, projection, discovery and reconciliation |
| `scripts/migrate_products.py`, `scripts/search/` — new | Streaming migration, bootstrap, generation promotion/rollback |
| `terraform/search.tf`, `terraform/catalog_pipeline.tf` — new | Private domain, outbox/worker/discovery resources, health and alarms |
| `terraform/agentcore.tf`, `terraform/iam.tf`, `terraform/dynamodb.tf`, network config | VPC access, bounded roles, tables and runtime source manifest |
| `terraform/apigateway.tf`, `terraform/cloudfront.tf`, `terraform/api_proxy.tf` | Authenticated `/api/ingredients/lookup` route, proxy read permissions and matching origin routing |
| `scripts/deploy.sh`, packaging scripts, dependency locks if needed | Deployment order and verified client dependency; exclude research data |
| `tests/unit/`, `tests/integration/`, `api_proxy/test/`, frontend tests | Contract/oracle/integration/browser coverage |
| New load/recovery tools under `experiments/` or `scripts/search/` | Actual production adapter runs, raw evidence and reconciliation |
| `docs/architecture.md`, operational runbooks | Update actual architecture when integration exists; document measured limits |

Verify current official APIs before writing provider code. In particular, consult
Strands SDK documentation and official DeepWiki examples before implementing
AgentCore/Strands graph changes. The spec does not prescribe guessed SDK methods.

## 4. Data and deployment inputs

Record before the relevant gate:

| Input | Needed for |
|---|---|
| Stable supplier IDs or persisted identity strategy; source revision/order contract | Live ingestion and deletes |
| Reviewed registry/aliases, raw lists and completeness evidence | Production identity/exclusion behavior |
| Market/currency/price/availability semantics and mode | Eligibility and truthful presentation |
| Supported categories and explicit constraint origin | Planner/API agreement |
| Region, supported engine/client, quotas, networking and residency | Cloud qualification |
| Representative feed sizes/skew/change rate and user cases | Capacity/data/product validation |
| Fixed monthly and per-1,000-routine cost ceilings | Production budgeting |
| Product acceptance owner and operational owners | Acceptance, monitoring and recovery |

Public data and explicit fixture facts can unblock development. Unknown customer
fields remain unknown. Review/resolve live-feed gaps before enabling the behavior
that depends on them; do not invent stock or completeness to ship a demo.

## 5. Migration, release and rollback

### Compatibility and generation migration

Deploy the browser's v1/v2/terminal-domain-code support before v2 preference controls.
Preserve v1 request acceptance. Backfill stable IDs and validate old-to-new references.
Build/catch up/reconcile the new index before making its manifest eligible for routing.
Use atomic alias reassignment without index deletion; pin a physical generation and
configuration per routine. Continue publication to the retained generation.

The legacy scorer may remain available for an isolated development comparison, but
it cannot receive v2 hard-constraint requests or production million-product fallback
traffic. If no healthy compatible exact path exists, return service unavailable.

### Shadow and canary

Start non-user-visible shadow at 1%; increase to at most 5% after accounting for
additional search/read cost. Reuse validated ingredient requests when isolating
search behavior; do not double-run upstream models unintentionally. Any broader
full-pipeline shadow has its own explicit resource budget.

Canary stages: 1%, 5%, 25%, 100%, assigned on the server and stable per routine.
Each stage needs at least 24 hours and 1,000 completed routines before acceptance;
low traffic extends the window. Inspect hard constraints, factual binding, short/
no-match rates, planner samples, errors, latency, freshness and cost. Explain that
new exact-count results can differ from old harmonic results by design.

### Rollback

Stop promotion immediately for confirmed scope/constraint/fact violations, data
resurrection or broken client completion. For operational SLO/freshness breaches,
use two consecutive five-minute windows, except immediate hard-stale denial.

1. Restore a healthy compatible configuration/generation with verified freshness.
2. Preserve request/response compatibility when reverting application code.
3. If neither generation is healthy, stop affected admission and report unavailable.
4. Verify canonical binding, new updates and client terminal behavior after recovery.

Target configuration/index recovery within five minutes; measure application
rollback separately. Never disable hard constraints as a mitigation. Retain prior
generation/history at least seven days and longer than replay/retry horizons.

### Handover

Runbooks cover publication lag/gaps, poison records, registry/data errors, index
saturation, model throttling, partial canonical reads, rebuild, cutover, rollback,
no-match anomalies and cost. Each includes owner, detection, bounded mitigation
and a verification step.

## 6. Definition of done

The specification is delivered when its documents, JSON examples and targets are
consistent and linked. That does not activate the application.

The implementation is release-ready when R01–R14 and T01–T10 pass, the customer
feed/registry and product behavior are accepted, deployed P01–P03 gates pass, cost
ceilings are met, and rollout/rollback evidence is recorded. Exact-count research
is already complete and is not reopened as a delivery prerequisite.

Official implementation references are linked in
[technical.md](technical.md#11-official-implementation-references).
